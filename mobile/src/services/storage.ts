import AsyncStorage from '@react-native-async-storage/async-storage';
import { UserProfile, VocabularyItem, SavedLessonCard, getTierFromGrade } from '../types';

const STORAGE_KEYS = {
  PROFILE: '@tarkapp_user_profile',
  VOCABULARY: '@tarkapp_saved_vocabulary',
  HISTORY: '@tarkapp_saved_history',
};

const DEFAULT_PROFILE: UserProfile = {
  grade: 3,
  tier: 'primary',
  interests: ['Minecraft', 'LEGO', 'Roblox'],
  nickname: '',
};

// In-memory fallback cache to ensure instant, zero-crash performance
const memoryStore: Record<string, string> = {
  [STORAGE_KEYS.PROFILE]: JSON.stringify(DEFAULT_PROFILE),
  [STORAGE_KEYS.VOCABULARY]: JSON.stringify([]),
  [STORAGE_KEYS.HISTORY]: JSON.stringify([]),
};

/**
 * Zero-PII Local-First Storage Service
 * Keeps all pupil settings, grade, preferences, and saved vocabulary strictly on-device.
 * Includes graceful in-memory fallback so storage failures never crash the app.
 */
export const StorageService = {
  async getProfile(): Promise<UserProfile> {
    try {
      const data = await AsyncStorage.getItem(STORAGE_KEYS.PROFILE);
      if (data) {
        memoryStore[STORAGE_KEYS.PROFILE] = data;
        const parsed = JSON.parse(data) as any;
        parsed.tier = parsed.tier || getTierFromGrade(parsed.grade);
        if (!parsed.interests || !Array.isArray(parsed.interests)) {
          parsed.interests = parsed.theme_interest
            ? [parsed.theme_interest]
            : ['Minecraft', 'LEGO', 'Roblox'];
        } else {
          parsed.interests = parsed.interests.map((item: string) =>
            typeof item === 'string' ? item.replace(/спотр/gi, 'спорт') : item
          );
        }
        return parsed as UserProfile;
      }
    } catch (e) {
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
    const payload: UserProfile = {
      ...profile,
      tier: profile.tier || getTierFromGrade(profile.grade),
    };
    const json = JSON.stringify(payload);
    memoryStore[STORAGE_KEYS.PROFILE] = json;

    try {
      await AsyncStorage.setItem(STORAGE_KEYS.PROFILE, json);
    } catch (e) {
      // Non-blocking in-memory fallback - do not rethrow
    }
  },

  async getSavedVocabulary(): Promise<VocabularyItem[]> {
    try {
      const data = await AsyncStorage.getItem(STORAGE_KEYS.VOCABULARY);
      if (data) {
        memoryStore[STORAGE_KEYS.VOCABULARY] = data;
        return JSON.parse(data) as VocabularyItem[];
      }
    } catch (e) {
      // Fallback to memory
    }

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
      const exists = current.some(
        (v) => v.est.toLowerCase() === item.est.toLowerCase()
      );
      if (!exists) {
        const updated = [item, ...current];
        const json = JSON.stringify(updated);
        memoryStore[STORAGE_KEYS.VOCABULARY] = json;
        try {
          await AsyncStorage.setItem(STORAGE_KEYS.VOCABULARY, json);
        } catch {}
      }
    } catch (e) {
      // In-memory fallback
    }
  },

  async saveVocabularyItems(items: VocabularyItem[]): Promise<void> {
    if (!items || items.length === 0) return;
    try {
      const current = await this.getSavedVocabulary();
      const updated = [...current];
      for (const item of items) {
        if (!updated.some((v) => v.est.toLowerCase() === item.est.toLowerCase())) {
          updated.push(item);
        }
      }
      const json = JSON.stringify(updated);
      memoryStore[STORAGE_KEYS.VOCABULARY] = json;
      try {
        await AsyncStorage.setItem(STORAGE_KEYS.VOCABULARY, json);
      } catch {}
    } catch (e) {
      // In-memory fallback
    }
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
    } catch (e) {
      // In-memory fallback
    }
  },

  async clearAll(): Promise<void> {
    memoryStore[STORAGE_KEYS.PROFILE] = JSON.stringify(DEFAULT_PROFILE);
    memoryStore[STORAGE_KEYS.VOCABULARY] = JSON.stringify([]);
    memoryStore[STORAGE_KEYS.HISTORY] = JSON.stringify([]);
    try {
      await Promise.all([
        AsyncStorage.removeItem(STORAGE_KEYS.PROFILE),
        AsyncStorage.removeItem(STORAGE_KEYS.VOCABULARY),
        AsyncStorage.removeItem(STORAGE_KEYS.HISTORY),
      ]);
    } catch {}
  },

  async getHistory(): Promise<SavedLessonCard[]> {
    try {
      const data = await AsyncStorage.getItem(STORAGE_KEYS.HISTORY);
      if (data) {
        memoryStore[STORAGE_KEYS.HISTORY] = data;
        return JSON.parse(data) as SavedLessonCard[];
      }
    } catch (e) {
      // In-memory fallback
    }

    try {
      const fallback = memoryStore[STORAGE_KEYS.HISTORY];
      if (fallback) {
        return JSON.parse(fallback) as SavedLessonCard[];
      }
    } catch {}

    return [];
  },

  async saveLessonToHistory(card: SavedLessonCard): Promise<void> {
    try {
      const current = await this.getHistory();
      // Remove any existing card with the same title or id to prevent duplicates
      const filtered = current.filter(
        (c) => c.id !== card.id && c.task_title !== card.task_title
      );
      const updated = [card, ...filtered];
      const json = JSON.stringify(updated);
      memoryStore[STORAGE_KEYS.HISTORY] = json;
      try {
        await AsyncStorage.setItem(STORAGE_KEYS.HISTORY, json);
      } catch {}

      // Automatically accumulate lesson vocabulary in local dictionary
      if (card.analysis?.vocabulary) {
        await this.saveVocabularyItems(card.analysis.vocabulary);
      }
    } catch (e) {
      // In-memory fallback
    }
  },

  async deleteLessonFromHistory(id: string): Promise<void> {
    try {
      const current = await this.getHistory();
      const updated = current.filter((c) => c.id !== id);
      const json = JSON.stringify(updated);
      memoryStore[STORAGE_KEYS.HISTORY] = json;
      try {
        await AsyncStorage.setItem(STORAGE_KEYS.HISTORY, json);
      } catch {}
    } catch (e) {
      // In-memory fallback
    }
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
