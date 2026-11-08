import AsyncStorage from '@react-native-async-storage/async-storage';
import * as FileSystem from 'expo-file-system/legacy';
import {
  UserProfile,
  VocabularyItem,
  SavedLessonCard,
  PageAnalysisResponse,
  getTierFromGrade,
  getDefaultInterestsForTier,
  isDefaultInterestsList,
} from '../types';
import { AudioQueueManager } from './audioQueueManager';
import { clearAuthSession, deleteServerAccountData } from './api';

const STORAGE_KEYS = {
  PROFILE: '@tarkapp_user_profile',
  PROFILE_DRAFT: '@tarkapp_profile_draft',
  VOCABULARY: '@tarkapp_saved_vocabulary',
  HISTORY: '@tarkapp_saved_history',
  AUTH_TOKEN: '@tarkapp_auth_token',
};

/**
 * Lightweight metadata stored in AsyncStorage (@tarkapp_saved_history)
 * to permanently prevent Android SQLite CursorWindow (~2 MB) crashes.
 * Full PageAnalysisResponse payloads are stored as individual files in
 * FileSystem.documentDirectory + 'lessons/' + id + '.json'.
 */
interface SavedLessonMetadata {
  id: string;
  timestamp: number;
  dateFormatted: string;
  grade: number;
  tier: SavedLessonCard['tier'];
  task_title: string;
  task_type?: string;
  themeSnippet?: string;
  imageUri?: string;
  imageUris?: string[];
}

const DOC_ROOT = FileSystem.documentDirectory || '';
const LESSONS_DIR = `${DOC_ROOT}lessons/`;
const LESSON_MEDIA_DIR = `${DOC_ROOT}lesson_media/`;
const AVATARS_DIR = `${DOC_ROOT}avatars/`;

const DEFAULT_PROFILE: UserProfile = {
  grade: 3,
  tier: 'primary',
  interests: getDefaultInterestsForTier('primary'),
  interestsByGrade: {
    3: getDefaultInterestsForTier('primary'),
  },
  hasCustomInterests: false,
  nickname: '',
};

// In-memory fallback cache to ensure instant, zero-crash performance
const memoryStore: Record<string, string> = {
  [STORAGE_KEYS.PROFILE]: JSON.stringify(DEFAULT_PROFILE),
  [STORAGE_KEYS.VOCABULARY]: JSON.stringify([]),
  [STORAGE_KEYS.HISTORY]: JSON.stringify([]),
};
const memoryLessonPayloads: Record<string, PageAnalysisResponse> = {};

function sanitizeFileId(id: string): string {
  return (id || 'lesson').replace(/[^a-zA-Z0-9._-]/g, '_');
}

function getLessonFilePath(id: string): string {
  return `${LESSONS_DIR}${sanitizeFileId(id)}.json`;
}

function buildStubAnalysis(meta: SavedLessonMetadata): PageAnalysisResponse {
  return {
    task_title: meta.task_title,
    theme_explanation: meta.themeSnippet || '',
    vocabulary: [],
    how_to_answer: '',
    answer_template: '',
    voice_prompt_script: '',
  };
}

async function ensureDirectory(dirPath: string): Promise<void> {
  if (!DOC_ROOT) return;
  try {
    const info = await FileSystem.getInfoAsync(dirPath);
    if (!info.exists) {
      await FileSystem.makeDirectoryAsync(dirPath, { intermediates: true });
    }
  } catch {}
}

async function copyIfEphemeralUri(
  sourceUri: string | undefined,
  targetDir: string,
  targetFilename: string
): Promise<string | undefined> {
  if (!sourceUri || !DOC_ROOT) return sourceUri;
  if (
    sourceUri.startsWith('http://') ||
    sourceUri.startsWith('https://') ||
    sourceUri.startsWith('data:') ||
    sourceUri.startsWith(targetDir)
  ) {
    return sourceUri;
  }

  try {
    await ensureDirectory(targetDir);
    const extMatch = /\.([a-zA-Z0-9]{2,5})(?:\?.*)?$/.exec(sourceUri);
    const ext = extMatch ? extMatch[1].toLowerCase() : 'jpg';
    const destUri = `${targetDir}${targetFilename}.${ext}`;
    await FileSystem.copyAsync({ from: sourceUri, to: destUri });
    return destUri;
  } catch {
    return sourceUri;
  }
}

async function writeLessonPayloadToFile(id: string, analysis: PageAnalysisResponse): Promise<void> {
  memoryLessonPayloads[id] = analysis;
  if (!DOC_ROOT) return;
  try {
    await ensureDirectory(LESSONS_DIR);
    await FileSystem.writeAsStringAsync(getLessonFilePath(id), JSON.stringify(analysis));
  } catch (err) {
    console.warn('[StorageService] Failed writing lesson JSON file:', err);
  }
}

async function readLessonPayloadFromFile(id: string): Promise<PageAnalysisResponse | null> {
  if (memoryLessonPayloads[id]) {
    return memoryLessonPayloads[id];
  }
  if (!DOC_ROOT) return null;
  try {
    const path = getLessonFilePath(id);
    const info = await FileSystem.getInfoAsync(path);
    if (!info.exists) return null;
    const content = await FileSystem.readAsStringAsync(path);
    if (!content) return null;
    const parsed = JSON.parse(content) as PageAnalysisResponse;
    memoryLessonPayloads[id] = parsed;
    return parsed;
  } catch {
    return null;
  }
}

function getCurrentStudyDayStartMs(): number {
  const now = new Date();
  const boundary = new Date(now);
  boundary.setHours(3, 0, 0, 0);
  if (now.getHours() < 3) {
    boundary.setDate(boundary.getDate() - 1);
  }
  return boundary.getTime();
}

/**
 * Zero-PII Local-First Storage Service
 * Keeps all pupil settings, grade, preferences, and saved vocabulary strictly on-device.
 * Separates heavy lesson JSONs and avatars into FileSystem.documentDirectory.
 */
export const StorageService = {
  async persistAvatarImage(sourceUri: string): Promise<string> {
    if (!sourceUri || !DOC_ROOT) return sourceUri;
    if (sourceUri.startsWith(AVATARS_DIR)) return sourceUri;
    try {
      await ensureDirectory(AVATARS_DIR);
      const existing = await FileSystem.readDirectoryAsync(AVATARS_DIR);
      const copied = await copyIfEphemeralUri(
        sourceUri,
        AVATARS_DIR,
        `avatar_${Date.now()}`
      );
      if (copied && copied !== sourceUri) {
        for (const oldFile of existing) {
          const oldPath = `${AVATARS_DIR}${oldFile}`;
          if (oldPath !== copied) {
            await FileSystem.deleteAsync(oldPath, { idempotent: true });
          }
        }
        return copied;
      }
    } catch (e) {
      console.warn('[StorageService] Could not persist avatar to documentDirectory:', e);
    }
    return sourceUri;
  },

  async getProfile(): Promise<UserProfile> {
    try {
      const data = await AsyncStorage.getItem(STORAGE_KEYS.PROFILE);
      if (data) {
        memoryStore[STORAGE_KEYS.PROFILE] = data;
        const parsed = JSON.parse(data) as any;
        const tier = parsed.tier || getTierFromGrade(parsed.grade);
        parsed.tier = tier;

        const normalizedMap: Record<number, string[]> = {};
        if (parsed.interestsByGrade && typeof parsed.interestsByGrade === 'object') {
          for (const key of Object.keys(parsed.interestsByGrade)) {
            const numKey = Number(key);
            if (!isNaN(numKey) && Array.isArray(parsed.interestsByGrade[key])) {
              normalizedMap[numKey] = parsed.interestsByGrade[key].map((item: string) =>
                typeof item === 'string' ? item.replace(/спотр/gi, 'спорт') : item
              );
            }
          }
        }

        if (!parsed.interests || !Array.isArray(parsed.interests)) {
          parsed.interests = parsed.theme_interest
            ? [parsed.theme_interest]
            : (normalizedMap[parsed.grade] || getDefaultInterestsForTier(tier));
          parsed.hasCustomInterests = false;
        } else {
          parsed.interests = parsed.interests.map((item: string) =>
            typeof item === 'string' ? item.replace(/спотр/gi, 'спорт') : item
          );

          if (!parsed.hasCustomInterests) {
            if (tier !== 'primary' && !parsed.hasCustomInterests && isDefaultInterestsList(parsed.interests)) {
              parsed.interests = getDefaultInterestsForTier(tier);
            } else if (parsed.interests.length === 0) {
              parsed.interests = getDefaultInterestsForTier(tier);
            }
          }
        }

        if (parsed.interests && parsed.interests.length > 0) {
          normalizedMap[parsed.grade] = parsed.interests;
        }
        parsed.interestsByGrade = normalizedMap;

        return parsed as UserProfile;
      }
    } catch {
      // In-memory fallback
    }

    try {
      const fallback = memoryStore[STORAGE_KEYS.PROFILE];
      if (fallback) {
        return JSON.parse(fallback) as UserProfile;
      }
    } catch {}

    return DEFAULT_PROFILE;
  },

  async saveProfile(profile: UserProfile): Promise<void> {
    const grade = profile.grade || 3;
    const tier = profile.tier || getTierFromGrade(grade);
    let persistentAvatarUri = profile.avatarUri;
    if (persistentAvatarUri && DOC_ROOT && !persistentAvatarUri.startsWith(AVATARS_DIR)) {
      persistentAvatarUri = await this.persistAvatarImage(persistentAvatarUri);
    }
    const interestsByGrade: Record<number, string[]> = {
      ...(profile.interestsByGrade || {}),
      [grade]: profile.interests || [],
    };
    const payload: UserProfile = {
      ...profile,
      avatarUri: persistentAvatarUri,
      grade,
      tier,
      interestsByGrade,
    };
    const json = JSON.stringify(payload);
    memoryStore[STORAGE_KEYS.PROFILE] = json;

    try {
      await AsyncStorage.setItem(STORAGE_KEYS.PROFILE, json);
    } catch {
      // Non-blocking in-memory fallback
    }
  },

  async getProfileDraft(): Promise<Partial<UserProfile> | null> {
    try {
      const data = await AsyncStorage.getItem(STORAGE_KEYS.PROFILE_DRAFT);
      if (data) {
        return JSON.parse(data);
      }
    } catch {}
    try {
      const fallback = memoryStore[STORAGE_KEYS.PROFILE_DRAFT];
      if (fallback) {
        return JSON.parse(fallback);
      }
    } catch {}
    return null;
  },

  async saveProfileDraft(draft: Partial<UserProfile>): Promise<void> {
    try {
      const existing = (await this.getProfileDraft()) || {};
      const merged = { ...existing, ...draft };
      const json = JSON.stringify(merged);
      memoryStore[STORAGE_KEYS.PROFILE_DRAFT] = json;
      await AsyncStorage.setItem(STORAGE_KEYS.PROFILE_DRAFT, json);
    } catch {
      try {
        const fallback = memoryStore[STORAGE_KEYS.PROFILE_DRAFT]
          ? JSON.parse(memoryStore[STORAGE_KEYS.PROFILE_DRAFT])
          : {};
        memoryStore[STORAGE_KEYS.PROFILE_DRAFT] = JSON.stringify({ ...fallback, ...draft });
      } catch {}
    }
  },

  async clearProfileDraft(): Promise<void> {
    try {
      delete memoryStore[STORAGE_KEYS.PROFILE_DRAFT];
      await AsyncStorage.removeItem(STORAGE_KEYS.PROFILE_DRAFT);
    } catch {}
  },

  async getSavedVocabulary(): Promise<VocabularyItem[]> {
    try {
      const data = await AsyncStorage.getItem(STORAGE_KEYS.VOCABULARY);
      if (data) {
        memoryStore[STORAGE_KEYS.VOCABULARY] = data;
        return JSON.parse(data) as VocabularyItem[];
      }
    } catch {}

    try {
      const fallback = memoryStore[STORAGE_KEYS.VOCABULARY];
      if (fallback) {
        return JSON.parse(fallback) as VocabularyItem[];
      }
    } catch {}

    return [];
  },

  async saveVocabularyItem(item: VocabularyItem): Promise<void> {
    try {
      const current = await this.getSavedVocabulary();
      const existingIdx = current.findIndex(
        (v) => v.est.toLowerCase() === item.est.toLowerCase()
      );
      if (existingIdx === -1) {
        const updated = [item, ...current];
        const json = JSON.stringify(updated);
        memoryStore[STORAGE_KEYS.VOCABULARY] = json;
        try {
          await AsyncStorage.setItem(STORAGE_KEYS.VOCABULARY, json);
        } catch {}
      } else if (!current[existingIdx].topicTitle && item.topicTitle) {
        current[existingIdx] = { ...current[existingIdx], topicTitle: item.topicTitle };
        const json = JSON.stringify(current);
        memoryStore[STORAGE_KEYS.VOCABULARY] = json;
        try {
          await AsyncStorage.setItem(STORAGE_KEYS.VOCABULARY, json);
        } catch {}
      }
    } catch {}
  },

  async saveVocabularyItems(items: VocabularyItem[]): Promise<void> {
    if (!items || items.length === 0) return;
    try {
      const current = await this.getSavedVocabulary();
      const updated = [...current];
      for (const item of items) {
        const existingIdx = updated.findIndex((v) => v.est.toLowerCase() === item.est.toLowerCase());
        if (existingIdx === -1) {
          updated.push(item);
        } else if (!updated[existingIdx].topicTitle && item.topicTitle) {
          updated[existingIdx] = { ...updated[existingIdx], topicTitle: item.topicTitle };
        }
      }
      const json = JSON.stringify(updated);
      memoryStore[STORAGE_KEYS.VOCABULARY] = json;
      try {
        await AsyncStorage.setItem(STORAGE_KEYS.VOCABULARY, json);
      } catch {}
    } catch {}
  },

  async removeVocabularyItem(estTerm: string): Promise<void> {
    try {
      const current = await this.getSavedVocabulary();
      const updated = current.filter(
        (v) => v.est.toLowerCase() !== estTerm.toLowerCase()
      );
      const json = JSON.stringify(updated);
      memoryStore[STORAGE_KEYS.VOCABULARY] = json;
      try {
        await AsyncStorage.setItem(STORAGE_KEYS.VOCABULARY, json);
      } catch {}
    } catch {}
  },

  /**
   * Clears ONLY lesson history, lesson JSON files, saved vocabulary cards, and audio disk cache.
   * NEVER deletes @tarkapp_user_profile or @tarkapp_auth_token!
   */
  async clearLearningData(): Promise<void> {
    memoryStore[STORAGE_KEYS.VOCABULARY] = JSON.stringify([]);
    memoryStore[STORAGE_KEYS.HISTORY] = JSON.stringify([]);
    for (const k of Object.keys(memoryLessonPayloads)) {
      delete memoryLessonPayloads[k];
    }

    await Promise.allSettled([
      AsyncStorage.removeItem(STORAGE_KEYS.VOCABULARY),
      AsyncStorage.removeItem(STORAGE_KEYS.HISTORY),
      DOC_ROOT ? FileSystem.deleteAsync(LESSONS_DIR, { idempotent: true }) : Promise.resolve(),
      DOC_ROOT ? FileSystem.deleteAsync(LESSON_MEDIA_DIR, { idempotent: true }) : Promise.resolve(),
      AudioQueueManager.clearDiskCache(),
    ]);
  },

  /**
   * Full GDPR account & data deletion:
   * Deletes server-side PII / invoices associated with this Device ID and wipes all local
   * profile, auth token, history, lesson files, avatars, vocabulary, and audio cache.
   */
  async deleteAccountAndData(): Promise<{ serverDeleted: boolean }> {
    let serverDeleted = false;
    try {
      await deleteServerAccountData();
      serverDeleted = true;
    } catch (err) {
      console.warn('[StorageService] Server-side GDPR deletion warning:', err);
    }

    memoryStore[STORAGE_KEYS.PROFILE] = JSON.stringify(DEFAULT_PROFILE);
    memoryStore[STORAGE_KEYS.VOCABULARY] = JSON.stringify([]);
    memoryStore[STORAGE_KEYS.HISTORY] = JSON.stringify([]);
    delete memoryStore[STORAGE_KEYS.PROFILE_DRAFT];
    delete memoryStore[STORAGE_KEYS.AUTH_TOKEN];
    for (const k of Object.keys(memoryLessonPayloads)) {
      delete memoryLessonPayloads[k];
    }
    clearAuthSession();

    await Promise.allSettled([
      AsyncStorage.removeItem(STORAGE_KEYS.PROFILE),
      AsyncStorage.removeItem(STORAGE_KEYS.PROFILE_DRAFT),
      AsyncStorage.removeItem(STORAGE_KEYS.VOCABULARY),
      AsyncStorage.removeItem(STORAGE_KEYS.HISTORY),
      AsyncStorage.removeItem(STORAGE_KEYS.AUTH_TOKEN),
      DOC_ROOT ? FileSystem.deleteAsync(LESSONS_DIR, { idempotent: true }) : Promise.resolve(),
      DOC_ROOT ? FileSystem.deleteAsync(LESSON_MEDIA_DIR, { idempotent: true }) : Promise.resolve(),
      DOC_ROOT ? FileSystem.deleteAsync(AVATARS_DIR, { idempotent: true }) : Promise.resolve(),
      AudioQueueManager.clearDiskCache(),
    ]);

    return { serverDeleted };
  },

  /**
   * @deprecated Alias kept for backward compatibility; delegates to clearLearningData()
   * so existing callers never accidentally wipe the student's profile.
   */
  async clearAll(): Promise<void> {
    await this.clearLearningData();
  },

  async getAuthToken(): Promise<string | null> {
    try {
      const token = await AsyncStorage.getItem(STORAGE_KEYS.AUTH_TOKEN);
      if (token && token.trim()) {
        const clean = token.trim();
        memoryStore[STORAGE_KEYS.AUTH_TOKEN] = clean;
        return clean;
      }
    } catch {}
    return memoryStore[STORAGE_KEYS.AUTH_TOKEN] || null;
  },

  async saveAuthToken(token: string): Promise<void> {
    const clean = (token || '').trim();
    if (!clean) return;
    memoryStore[STORAGE_KEYS.AUTH_TOKEN] = clean;
    try {
      await AsyncStorage.setItem(STORAGE_KEYS.AUTH_TOKEN, clean);
    } catch {}
  },

  async removeAuthToken(): Promise<void> {
    delete memoryStore[STORAGE_KEYS.AUTH_TOKEN];
    try {
      await AsyncStorage.removeItem(STORAGE_KEYS.AUTH_TOKEN);
    } catch {}
  },

  async getFullLessonCard(card: SavedLessonCard): Promise<SavedLessonCard> {
    if (card.analysis && card.analysis.how_to_answer && card.analysis.vocabulary?.length > 0) {
      return card;
    }
    const diskAnalysis = await readLessonPayloadFromFile(card.id);
    if (diskAnalysis) {
      return { ...card, analysis: diskAnalysis };
    }
    return card;
  },

  async getHistory(): Promise<SavedLessonCard[]> {
    let rawItems: any[] = [];
    try {
      const data = await AsyncStorage.getItem(STORAGE_KEYS.HISTORY);
      if (data) {
        memoryStore[STORAGE_KEYS.HISTORY] = data;
        rawItems = JSON.parse(data) as any[];
      }
    } catch {
      try {
        const fallback = memoryStore[STORAGE_KEYS.HISTORY];
        if (fallback) {
          rawItems = JSON.parse(fallback) as any[];
        }
      } catch {}
    }

    if (!Array.isArray(rawItems) || rawItems.length === 0) {
      return [];
    }

    let needsLegacyMigration = false;
    const cleanMetadataList: SavedLessonMetadata[] = [];
    const studyDayStart = getCurrentStudyDayStartMs();
    const cards: SavedLessonCard[] = [];

    for (const entry of rawItems) {
      const hasEmbeddedFullAnalysis = Boolean(
        entry?.analysis &&
        typeof entry.analysis === 'object' &&
        (entry.analysis.how_to_answer || entry.analysis.answer_template || entry.analysis.vocabulary?.length)
      );

      const meta: SavedLessonMetadata = {
        id: entry.id,
        timestamp: entry.timestamp,
        dateFormatted: entry.dateFormatted,
        grade: entry.grade,
        tier: entry.tier,
        task_title: entry.task_title,
        task_type: entry.task_type,
        themeSnippet:
          entry.themeSnippet ??
          (typeof entry?.analysis?.theme_explanation === 'string'
            ? entry.analysis.theme_explanation.slice(0, 240)
            : ''),
        imageUri: entry.imageUri,
        imageUris: entry.imageUris,
      };
      cleanMetadataList.push(meta);

      if (hasEmbeddedFullAnalysis) {
        needsLegacyMigration = true;
        await writeLessonPayloadToFile(meta.id, entry.analysis as PageAnalysisResponse);
      }

      // Hydrate full JSON from disk immediately for today's active study session cards
      let resolvedAnalysis: PageAnalysisResponse | null = null;
      if (meta.timestamp >= studyDayStart) {
        resolvedAnalysis =
          (hasEmbeddedFullAnalysis ? (entry.analysis as PageAnalysisResponse) : null) ||
          (await readLessonPayloadFromFile(meta.id));
      }

      cards.push({
        id: meta.id,
        timestamp: meta.timestamp,
        dateFormatted: meta.dateFormatted,
        grade: meta.grade,
        tier: meta.tier,
        task_title: meta.task_title,
        task_type: meta.task_type,
        imageUri: meta.imageUri,
        imageUris: meta.imageUris,
        analysis: resolvedAnalysis || buildStubAnalysis(meta),
      });
    }

    if (needsLegacyMigration) {
      const migratedJson = JSON.stringify(cleanMetadataList);
      memoryStore[STORAGE_KEYS.HISTORY] = migratedJson;
      try {
        await AsyncStorage.setItem(STORAGE_KEYS.HISTORY, migratedJson);
      } catch {}
    }

    return cards;
  },

  async saveLessonToHistory(card: SavedLessonCard): Promise<void> {
    try {
      const safeId = sanitizeFileId(card.id);

      // Copy ephemeral cacheDirectory thumbnails/pages into permanent documentDirectory
      let persistedUris: string[] | undefined = undefined;
      if (card.imageUris && card.imageUris.length > 0) {
        persistedUris = [];
        for (let idx = 0; idx < card.imageUris.length; idx++) {
          const copied = await copyIfEphemeralUri(
            card.imageUris[idx],
            LESSON_MEDIA_DIR,
            `${safeId}_p${idx}`
          );
          if (copied) persistedUris.push(copied);
        }
      }
      const persistedFirstUri =
        persistedUris && persistedUris.length > 0
          ? persistedUris[0]
          : await copyIfEphemeralUri(card.imageUri, LESSON_MEDIA_DIR, `${safeId}_p0`);

      // 1. Write full lesson JSON to FileSystem.documentDirectory + 'lessons/' + id + '.json'
      await writeLessonPayloadToFile(card.id, card.analysis);

      // 2. Read existing lightweight metadata list and prepend new metadata (without fullAnalysis!)
      let existingMeta: SavedLessonMetadata[] = [];
      try {
        const raw = await AsyncStorage.getItem(STORAGE_KEYS.HISTORY);
        if (raw) {
          const parsed = JSON.parse(raw);
          if (Array.isArray(parsed)) {
            existingMeta = parsed.map((e: any) => ({
              id: e.id,
              timestamp: e.timestamp,
              dateFormatted: e.dateFormatted,
              grade: e.grade,
              tier: e.tier,
              task_title: e.task_title,
              task_type: e.task_type,
              themeSnippet:
                e.themeSnippet ??
                (typeof e?.analysis?.theme_explanation === 'string'
                  ? e.analysis.theme_explanation.slice(0, 240)
                  : ''),
              imageUri: e.imageUri,
              imageUris: e.imageUris,
            }));
          }
        }
      } catch {}

      const duplicates = existingMeta.filter(
        (c) => c.id === card.id || c.task_title === card.task_title
      );
      for (const dup of duplicates) {
        if (dup.id !== card.id && DOC_ROOT) {
          delete memoryLessonPayloads[dup.id];
          await FileSystem.deleteAsync(getLessonFilePath(dup.id), { idempotent: true });
        }
      }

      const filtered = existingMeta.filter(
        (c) => c.id !== card.id && c.task_title !== card.task_title
      );

      const newMeta: SavedLessonMetadata = {
        id: card.id,
        timestamp: card.timestamp,
        dateFormatted: card.dateFormatted,
        grade: card.grade,
        tier: card.tier,
        task_title: card.task_title,
        task_type: card.task_type,
        themeSnippet: (card.analysis?.theme_explanation || '').slice(0, 240),
        imageUri: persistedFirstUri,
        imageUris: persistedUris,
      };

      const updatedMeta = [newMeta, ...filtered];
      const json = JSON.stringify(updatedMeta);
      memoryStore[STORAGE_KEYS.HISTORY] = json;
      await AsyncStorage.setItem(STORAGE_KEYS.HISTORY, json);
    } catch (e) {
      console.warn('[StorageService] Failed saving lesson to history:', e);
    }
  },

  async deleteLessonFromHistory(id: string): Promise<void> {
    delete memoryLessonPayloads[id];
    try {
      if (DOC_ROOT) {
        await FileSystem.deleteAsync(getLessonFilePath(id), { idempotent: true });
      }
    } catch {}

    try {
      const raw = await AsyncStorage.getItem(STORAGE_KEYS.HISTORY);
      const list: SavedLessonMetadata[] = raw ? JSON.parse(raw) : [];
      const target = list.find((c) => c.id === id);
      if (target && DOC_ROOT) {
        const uris = target.imageUris?.length ? target.imageUris : target.imageUri ? [target.imageUri] : [];
        for (const u of uris) {
          if (u && u.startsWith(LESSON_MEDIA_DIR)) {
            await FileSystem.deleteAsync(u, { idempotent: true });
          }
        }
      }
      const updated = list.filter((c) => c.id !== id);
      const json = JSON.stringify(updated);
      memoryStore[STORAGE_KEYS.HISTORY] = json;
      await AsyncStorage.setItem(STORAGE_KEYS.HISTORY, json);
    } catch {}
  },

  async isLessonSaved(taskTitle: string): Promise<boolean> {
    try {
      const current = await this.getHistory();
      return current.some((c) => c.task_title === taskTitle);
    } catch {
      return false;
    }
  },
};
