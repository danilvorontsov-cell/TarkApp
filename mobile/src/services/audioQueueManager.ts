import { AppState } from 'react-native';
import * as FileSystem from 'expo-file-system/legacy';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { API_BASE_URL, getDeviceId, resolveBaseUrl } from './api';
import {
  playTts,
  stopTts,
  pauseTts,
  resumeTts,
  getPlaybackState,
  subscribePlaybackState,
  AudioPlaybackCallbacks,
  getCurrentPlayingId,
  PlaybackState,
  getFileHash,
} from './audioPlayer';
import { PageAnalysisResponse } from '../types';
import { getTierPolicy, getTierFromGrade, SchoolTier } from './gradePolicy';
import { sanitizeTextForTts } from '../utils/textSanitizer';

export { PlaybackState } from './audioPlayer';

export const AUDIO_CACHE_VERSION = 4;
const CACHE_VERSION_KEY = '@tarkapp_audio_cache_version';

export type AudioItemStatus = 'IDLE' | 'QUEUED' | 'LOADING' | 'READY' | 'ERROR';

export interface AudioQueueItem {
  id: string;
  text: string;
  speech_text?: string;
  lang: 'ru' | 'et';
  bilingual: boolean;
  priority: number; // 0 = urgent user click, 1 = prompt, 2 = theme, 3 = how_to_answer, 4 = vocabulary
  status: AudioItemStatus;
  localUri?: string;
  grade?: number;
  tier?: string;
  onReadyCallbacks: Array<(uri: string) => void>;
  onErrorCallbacks: Array<(err: any) => void>;
}

export type QueueListener = (state: {
  playingId: string | null;
  playbackState: PlaybackState;
  loadingAudioId: string | null;
  itemStatuses: Record<string, AudioItemStatus>;
}) => void;

class AudioQueueManagerClass {
  private queue: Map<string, AudioQueueItem> = new Map();
  private isProcessing: boolean = false;
  private queueGeneration: number = 0;
  private currentDownloadingId: string | null = null;
  private pendingUserPlayId: string | null = null;
  private currentlyPlayingId: string | null = null;
  private playbackState: PlaybackState = 'idle';
  private listeners: Set<QueueListener> = new Set();
  private cacheDir: string = `${FileSystem.cacheDirectory || ''}tarkapp_audio/`;
  private dirInitialized: boolean = false;
  private readonly MIN_AUDIO_BYTES: number = 800; // Minimum size for valid MP3 speech

  constructor() {
    this.ensureCacheDir();
    // Reactively sync with underlying AudioPlayer playback state
    subscribePlaybackState((state, playingId) => {
      this.playbackState = state;
      this.currentlyPlayingId = playingId;
      this.notify();
    });

    // Automatic background playback cleanup: force stop audio & wipe preload queue
    AppState.addEventListener('change', (nextState) => {
      if (nextState === 'background') {
        this.stopAndClear().catch((err) =>
          console.warn('[AudioQueue] Background cleanup error:', err)
        );
      }
    });
  }

  private async ensureCacheDir() {
    if (this.dirInitialized) return;
    try {
      const storedVersionStr = await AsyncStorage.getItem(CACHE_VERSION_KEY);
      const storedVersion = storedVersionStr ? parseInt(storedVersionStr, 10) : 0;
      const dirInfo = await FileSystem.getInfoAsync(this.cacheDir);

      if (storedVersion < AUDIO_CACHE_VERSION) {
        if (dirInfo.exists) {
          await FileSystem.deleteAsync(this.cacheDir, { idempotent: true });
        }
        await FileSystem.makeDirectoryAsync(this.cacheDir, { intermediates: true });
        await AsyncStorage.setItem(CACHE_VERSION_KEY, String(AUDIO_CACHE_VERSION));
      } else if (!dirInfo.exists) {
        await FileSystem.makeDirectoryAsync(this.cacheDir, { intermediates: true });
      } else {
        // Clean up any 0-byte or corrupted leftover files from previous network interruptions
        const files = await FileSystem.readDirectoryAsync(this.cacheDir);
        for (const file of files) {
          const filePath = `${this.cacheDir}${file}`;
          const info = await FileSystem.getInfoAsync(filePath);
          if (info.exists && typeof (info as any).size === 'number' && (info as any).size < this.MIN_AUDIO_BYTES) {
            await FileSystem.deleteAsync(filePath, { idempotent: true });
          }
        }
      }
      this.dirInitialized = true;
      // Фоновая гигиена и ротация дискового кэша (старше 7 дней или > 50 МБ)
      this.rotateCache().catch((err) => console.warn('Cache rotation error:', err));
    } catch (e) {
      console.warn('Failed to initialize audio cache directory:', e);
    }
  }

  /**
   * Фоновая ротация аудиокэша: удаляет MP3 файлы старше 7 дней
   * или при превышении суммарного объема директории более 50 МБ (начиная с самых старых).
   */
  public async rotateCache(): Promise<void> {
    try {
      const dirInfo = await FileSystem.getInfoAsync(this.cacheDir);
      if (!dirInfo.exists) return;

      const files = await FileSystem.readDirectoryAsync(this.cacheDir);
      const nowSec = Date.now() / 1000;
      const MAX_AGE_SEC = 7 * 24 * 60 * 60; // 7 дней
      const MAX_TOTAL_BYTES = 50 * 1024 * 1024; // 50 МБ

      interface CacheFileEntry {
        path: string;
        size: number;
        modificationTime: number;
      }

      const validEntries: CacheFileEntry[] = [];
      let totalBytes = 0;

      for (const file of files) {
        if (!file.endsWith('.mp3')) continue;
        const filePath = `${this.cacheDir}${file}`;
        try {
          const info = await FileSystem.getInfoAsync(filePath);
          if (!info.exists || info.isDirectory) continue;

          // Удаляем поврежденные / урезанные файлы (< 800 байт)
          if (typeof info.size === 'number' && info.size < this.MIN_AUDIO_BYTES) {
            await FileSystem.deleteAsync(filePath, { idempotent: true });
            continue;
          }

          // 1. Удаляем файлы старше 7 дней
          if (info.modificationTime && nowSec - info.modificationTime > MAX_AGE_SEC) {
            await FileSystem.deleteAsync(filePath, { idempotent: true });
            continue;
          }

          const fileSize = typeof info.size === 'number' ? info.size : 0;
          validEntries.push({
            path: filePath,
            size: fileSize,
            modificationTime: info.modificationTime || nowSec,
          });
          totalBytes += fileSize;
        } catch {}
      }

      // 2. Если суммарный объем превышает 50 МБ, удаляем самые старые файлы
      if (totalBytes > MAX_TOTAL_BYTES) {
        validEntries.sort((a, b) => a.modificationTime - b.modificationTime);
        for (const entry of validEntries) {
          if (totalBytes <= MAX_TOTAL_BYTES) break;
          try {
            await FileSystem.deleteAsync(entry.path, { idempotent: true });
            totalBytes -= entry.size;
          } catch {}
        }
      }
    } catch (e) {
      console.warn('[AudioQueue] rotateCache error:', e);
    }
  }

  public normalizeText(str: string): string {
    if (!str) return '';
    return str.replace(/^[«"“„\s]+|[»"”\s]+$/g, '').trim();
  }

  public getFileHash(str: string): string {
    return getFileHash(str);
  }

  private getHash(str: string): string {
    return getFileHash(str);
  }

  public getFilePath(
    textOrItem: string | { text: string; speech_text?: string; grade?: number; tier?: string },
    lang: string,
    bilingual: boolean,
    grade?: number,
    tier?: string
  ): string {
    const raw = typeof textOrItem === 'string' ? textOrItem : (textOrItem.speech_text || textOrItem.text);
    const sanitized = sanitizeTextForTts(raw);
    const effGrade = grade !== undefined ? grade : (typeof textOrItem !== 'string' ? textOrItem.grade : undefined);
    const effTier = tier !== undefined ? tier : (typeof textOrItem !== 'string' ? textOrItem.tier : undefined);
    const gKey = effGrade || 1;
    const tKey = effTier || 'pri';
    const key = `${lang}_${bilingual ? 'bi' : 'mono'}_g${gKey}_${tKey}_${this.getFileHash(sanitized)}`;
    return `${this.cacheDir}${key}.mp3`;
  }

  private notify() {
    const itemStatuses: Record<string, AudioItemStatus> = {};
    this.queue.forEach((item, id) => {
      itemStatuses[id] = item.status;
    });

    const activePlayId = this.currentlyPlayingId || getCurrentPlayingId();
    const activePlaybackState = this.playbackState || getPlaybackState();

    const state = {
      playingId: activePlayId,
      playbackState: activePlaybackState,
      loadingAudioId: this.pendingUserPlayId,
      itemStatuses,
    };

    this.listeners.forEach((l) => {
      try {
        l(state);
      } catch (err) {
        console.warn('Error in AudioQueueManager listener:', err);
      }
    });
  }

  public subscribe(listener: QueueListener): () => void {
    this.listeners.add(listener);
    this.notify();
    return () => {
      this.listeners.delete(listener);
    };
  }

  public getItemStatus(id: string): AudioItemStatus {
    return this.queue.get(id)?.status || 'IDLE';
  }

  public getPendingPlayId(): string | null {
    return this.pendingUserPlayId;
  }

  public getPlaybackState(): PlaybackState {
    return this.playbackState || getPlaybackState();
  }

  public async pause(): Promise<void> {
    await pauseTts();
  }

  public async resume(): Promise<void> {
    await resumeTts();
  }

  public async stop(): Promise<void> {
    await stopTts();
    this.currentlyPlayingId = null;
    this.pendingUserPlayId = null;
    this.notify();
  }

  /**
   * Enqueues all audio items from a parsed lesson according to sequential priority:
   * Priority 1 (Immediate): voice_prompt_script
   * Priority 2 (150ms pause): theme_explanation (bilingual)
   * Priority 3 (150ms pause): how_to_answer (bilingual)
   * Priority 4 (300ms pause each): vocabulary words & examples
   */
  public async prefetchLessonAudio(
    analysis: PageAnalysisResponse,
    baseUrl: string = API_BASE_URL,
    gradeOrTier?: number | SchoolTier
  ) {
    await this.ensureCacheDir();

    let resolvedGrade: number | undefined;
    let resolvedTier: string | undefined;

    if (typeof gradeOrTier === 'number') {
      resolvedGrade = gradeOrTier;
      resolvedTier = getTierFromGrade(gradeOrTier);
    } else if (typeof gradeOrTier === 'string') {
      resolvedTier = gradeOrTier;
    }

    if (resolvedGrade === undefined || resolvedTier === undefined) {
      try {
        const raw = await AsyncStorage.getItem('@tarkapp_user_profile');
        if (raw) {
          const parsed = JSON.parse(raw);
          if (resolvedGrade === undefined) resolvedGrade = Number(parsed.grade) || 1;
          if (resolvedTier === undefined) resolvedTier = typeof parsed.tier === 'string' && parsed.tier ? parsed.tier : 'primary';
        }
      } catch {}
    }

    const policy = gradeOrTier !== undefined ? getTierPolicy(gradeOrTier) : null;
    const isFullAudio = policy ? policy.fullAudioEnabled : true;
    const isVocabAudio = policy ? policy.vocabAudioEnabled : true;

    // 1. Priority 1: Partner prompt (voice_prompt_script) — synchronized bilingual: true
    const promptVisual = analysis.voice_prompt_script;
    const promptSpeech = analysis.speech_layer?.voice_prompt_script || analysis.voice_prompt_script_speech || promptVisual;
    if (isFullAudio && promptVisual && promptVisual.trim()) {
      this.upsertItem({
        id: 'voice_prompt',
        text: promptVisual,
        speech_text: promptSpeech,
        lang: 'ru',
        bilingual: true,
        priority: 1,
        grade: resolvedGrade,
        tier: resolvedTier,
      });
    }

    // 2. Priority 2: Theme explanation (theme_explanation) with bilingual stitching
    const themeVisual = analysis.theme_explanation;
    const themeSpeech = analysis.speech_layer?.theme_explanation || analysis.theme_explanation_speech || themeVisual;
    if (isFullAudio && themeVisual && themeVisual.trim()) {
      this.upsertItem({
        id: 'theme_explanation',
        text: themeVisual,
        speech_text: themeSpeech,
        lang: 'ru',
        bilingual: true,
        priority: 2,
        grade: resolvedGrade,
        tier: resolvedTier,
      });
    }

    // 2b. Priority 2: Alternative explanation (alt_explanation) with bilingual stitching
    const altVisual = analysis.alternative_explanation;
    const altSpeech = analysis.speech_layer?.alternative_explanation || analysis.alternative_explanation_speech || altVisual;
    if (isFullAudio && altVisual && altVisual.trim()) {
      this.upsertItem({
        id: 'alt_explanation',
        text: altVisual,
        speech_text: altSpeech,
        lang: 'ru',
        bilingual: true,
        priority: 2,
        grade: resolvedGrade,
        tier: resolvedTier,
      });
    }

    // 3. Priority 3: How to answer (how_to_answer) with bilingual stitching
    const howVisual = analysis.how_to_answer;
    const howSpeech = analysis.speech_layer?.how_to_answer || analysis.how_to_answer_speech || howVisual;
    if (isFullAudio && howVisual && howVisual.trim()) {
      this.upsertItem({
        id: 'how_to_answer',
        text: howVisual,
        speech_text: howSpeech,
        lang: 'ru',
        bilingual: true,
        priority: 3,
        grade: resolvedGrade,
        tier: resolvedTier,
      });
    }

    // 3b. Priority 3: Worked example (worked_example) with bilingual stitching
    const workedSpeech = analysis.speech_layer?.worked_example || analysis.worked_example_speech;
    if (isFullAudio && analysis.worked_example) {
      const we = analysis.worked_example;
      const ORDINAL_STEP_WORDS: Record<number, string> = {
        1: 'Первое',
        2: 'Второе',
        3: 'Третье',
        4: 'Четвертое',
        5: 'Пятое',
        6: 'Шестое',
        7: 'Седьмое',
        8: 'Восьмое',
        9: 'Девятое',
        10: 'Десятое',
      };
      const formattedSteps = (we.steps || [])
        .filter((s) => Boolean(s && s.trim()))
        .map((step, sIdx) => {
          const clean = step.replace(/^\d+[\.\)]\s*/, '').trim();
          const prefix = ORDINAL_STEP_WORDS[sIdx + 1] || `${sIdx + 1}-е`;
          return `${prefix}: ${clean}`;
        });
      const naidisVisualText = `${we.given}. Шаги решения: ${formattedSteps.join('. ')}. ${we.note || ''}`.trim();
      const naidisAudioText = (workedSpeech && workedSpeech.trim()) ? workedSpeech : naidisVisualText;

      if (naidisVisualText.trim()) {
        this.upsertItem({
          id: 'worked_example',
          text: naidisVisualText,
          speech_text: naidisAudioText,
          lang: 'ru',
          bilingual: true,
          priority: 3,
          grade: resolvedGrade,
          tier: resolvedTier,
        });
      }
    } else if (isFullAudio && workedSpeech && workedSpeech.trim()) {
      this.upsertItem({
        id: 'worked_example',
        text: workedSpeech,
        speech_text: workedSpeech,
        lang: 'ru',
        bilingual: true,
        priority: 3,
        grade: resolvedGrade,
        tier: resolvedTier,
      });
    }

    // 4. Priority 4: Vocabulary terms and examples (one by one)
    if (isVocabAudio && analysis.vocabulary && analysis.vocabulary.length > 0) {
      analysis.vocabulary.forEach((item, idx) => {
        if (item.est && item.est.trim()) {
          this.upsertItem({
            id: `vocab_${idx}`,
            text: item.est,
            speech_text: item.est,
            lang: 'et',
            bilingual: false,
            priority: 4,
            grade: resolvedGrade,
            tier: resolvedTier,
          });
        }

        if (item.example && item.example.trim()) {
          this.upsertItem({
            id: `vocab_ex_${idx}`,
            text: item.example,
            speech_text: item.example,
            lang: 'et',
            bilingual: false,
            priority: 4,
            grade: resolvedGrade,
            tier: resolvedTier,
          });
        }
      });
    }

    // Start background sequential processing
    this.processQueue(baseUrl);
  }

  private upsertItem(params: {
    id: string;
    text: string;
    speech_text?: string;
    lang: 'ru' | 'et';
    bilingual: boolean;
    priority: number;
    grade?: number;
    tier?: string;
  }) {
    const cleanText = this.normalizeText(params.text);
    const speechText = params.speech_text ? this.normalizeText(params.speech_text) : cleanText;
    const existing = this.queue.get(params.id);

    if (existing) {
      if (
        existing.text !== cleanText ||
        existing.speech_text !== speechText ||
        existing.bilingual !== params.bilingual
      ) {
        existing.text = cleanText;
        existing.speech_text = speechText;
        existing.bilingual = params.bilingual;
        existing.status = 'QUEUED';
        existing.localUri = undefined;
      }
      existing.priority = Math.min(existing.priority, params.priority);
      if (params.grade !== undefined) existing.grade = params.grade;
      if (params.tier !== undefined) existing.tier = params.tier;
      return;
    }

    this.queue.set(params.id, {
      id: params.id,
      text: cleanText,
      speech_text: speechText,
      lang: params.lang,
      bilingual: params.bilingual,
      priority: params.priority,
      status: 'QUEUED',
      localUri: undefined,
      grade: params.grade,
      tier: params.tier,
      onReadyCallbacks: [],
      onErrorCallbacks: [],
    });
  }

  private flushCallbacks(item: AudioQueueItem) {
    if (item.status === 'READY' && item.localUri) {
      const callbacks = [...item.onReadyCallbacks];
      item.onReadyCallbacks = [];
      callbacks.forEach((cb) => {
        try {
          cb(item.localUri!);
        } catch (err) {
          console.warn('Error in onReadyCallback:', err);
        }
      });
    }
  }

  private flushErrorCallbacks(item: AudioQueueItem, err: any) {
    const errCallbacks = [...item.onErrorCallbacks];
    item.onErrorCallbacks = [];
    errCallbacks.forEach((cb) => {
      try {
        cb(err);
      } catch (e) {
        console.warn('Error in onErrorCallback:', e);
      }
    });
  }

  /**
   * Downloads a single audio item to disk cache.
   * Notifies onReadyCallbacks on success, onErrorCallbacks on failure.
   */
  public async downloadItem(item: AudioQueueItem, baseUrl: string = API_BASE_URL): Promise<boolean> {
    const textToSynthesize = (item.speech_text && item.speech_text.trim()) ? item.speech_text.trim() : item.text;
    const isSpeechText = Boolean(item.speech_text && item.speech_text.trim());

    let grade = item.grade;
    let tier = item.tier;
    if (grade === undefined || tier === undefined) {
      try {
        const raw = await AsyncStorage.getItem('@tarkapp_user_profile');
        if (raw) {
          const parsed = JSON.parse(raw);
          if (grade === undefined) grade = Number(parsed.grade) || 1;
          if (tier === undefined) tier = typeof parsed.tier === 'string' && parsed.tier ? parsed.tier : 'primary';
        }
      } catch {}
      if (grade === undefined) grade = 1;
      if (tier === undefined) tier = 'primary';
      item.grade = grade;
      item.tier = tier;
    }

    const targetFile = this.getFilePath(textToSynthesize, item.lang, item.bilingual, item.grade, item.tier);
    this.currentDownloadingId = item.id;
    item.status = 'LOADING';
    this.notify();

    try {
      const info = await FileSystem.getInfoAsync(targetFile);
      if (info.exists && typeof (info as any).size === 'number' && (info as any).size >= this.MIN_AUDIO_BYTES) {
        item.status = 'READY';
        item.localUri = targetFile;
        if (this.currentDownloadingId === item.id) {
          this.currentDownloadingId = null;
        }
        this.notify();
        this.flushCallbacks(item);
        return true;
      }

      if (info.exists) {
        await FileSystem.deleteAsync(targetFile, { idempotent: true });
      }

      let httpStatus = 200;

      let deviceId = '';
      try {
        deviceId = await getDeviceId();
      } catch {
        deviceId = '';
      }

      const activeBaseUrl = resolveBaseUrl(baseUrl);
      const sanitizedText = sanitizeTextForTts(textToSynthesize);

      if (sanitizedText.length > 200) {
        // Отправка POST запроса для фраз длиннее 200 символов
        const postUrl = `${activeBaseUrl}/api/v1/voice/tts`;
        const postHeaders: Record<string, string> = {
          'Content-Type': 'application/json',
          ...(deviceId ? { 'X-Device-ID': deviceId } : {}),
        };
        const response = await fetch(postUrl, {
          method: 'POST',
          headers: postHeaders,
          body: JSON.stringify({
            text: sanitizedText,
            lang: item.lang,
            bilingual: item.bilingual,
            grade,
            tier,
            is_speech_text: isSpeechText,
          }),
        });

        httpStatus = response.status;
        if (!response.ok) {
          console.warn(`[AudioQueue] Download POST failed for ${item.id}: HTTP ${response.status}`);
          item.status = 'ERROR';
          if (this.currentDownloadingId === item.id) {
            this.currentDownloadingId = null;
          }
          this.notify();
          this.flushErrorCallbacks(item, new Error(`Download POST returned HTTP ${response.status}`));
          return false;
        }

        const blob = await response.blob();
        const base64Data = await new Promise<string>((resolve, reject) => {
          const reader = new FileReader();
          reader.onloadend = () => {
            const res = reader.result as string;
            const b64 = res.indexOf(',') >= 0 ? res.split(',')[1] : res;
            resolve(b64);
          };
          reader.onerror = reject;
          reader.readAsDataURL(blob);
        });

        await FileSystem.writeAsStringAsync(targetFile, base64Data, {
          encoding: FileSystem.EncodingType.Base64,
        });
      } else {
        const encodedText = encodeURIComponent(sanitizedText);
        const bilingualParam = item.bilingual ? '&bilingual=true' : '';
        const deviceParam = deviceId ? `&device_id=${encodeURIComponent(deviceId)}` : '';
        const gradeParam = grade ? `&grade=${grade}` : '';
        const tierParam = tier ? `&tier=${encodeURIComponent(tier)}` : '';
        const speechParam = isSpeechText ? '&is_speech_text=true' : '';
        const downloadUrl = `${activeBaseUrl}/api/v1/voice/tts?text=${encodedText}&lang=${item.lang}${bilingualParam}${deviceParam}${gradeParam}${tierParam}${speechParam}`;

        const result = await FileSystem.downloadAsync(
          downloadUrl,
          targetFile,
          deviceId ? { headers: { 'X-Device-ID': deviceId } } : undefined
        );
        httpStatus = result.status;

        if (result.status !== 200) {
          console.warn(`[AudioQueue] Download GET failed for ${item.id}: HTTP ${result.status}`);
          if (info.exists) {
            await FileSystem.deleteAsync(targetFile, { idempotent: true });
          }
          item.status = 'ERROR';
          if (this.currentDownloadingId === item.id) {
            this.currentDownloadingId = null;
          }
          this.notify();
          this.flushErrorCallbacks(item, new Error(`Download GET returned HTTP ${result.status}`));
          return false;
        }
      }

      const downloadedInfo = await FileSystem.getInfoAsync(targetFile);

      if (
        downloadedInfo.exists &&
        typeof (downloadedInfo as any).size === 'number' &&
        (downloadedInfo as any).size >= this.MIN_AUDIO_BYTES
      ) {
        item.status = 'READY';
        item.localUri = targetFile;
        if (this.currentDownloadingId === item.id) {
          this.currentDownloadingId = null;
        }
        this.notify();
        this.flushCallbacks(item);
        return true;
      } else {
        const fileSize = (downloadedInfo.exists && typeof (downloadedInfo as any).size === 'number') ? (downloadedInfo as any).size : 0;
        console.warn(`[AudioQueue] Download invalid for ${item.id}: HTTP status ${httpStatus}, size: ${fileSize} bytes`);
        if (downloadedInfo.exists) {
          await FileSystem.deleteAsync(targetFile, { idempotent: true });
        }
        item.status = 'ERROR';
        if (this.currentDownloadingId === item.id) {
          this.currentDownloadingId = null;
        }
        this.notify();
        this.flushErrorCallbacks(item, new Error(`Download returned HTTP ${httpStatus}, size: ${fileSize}`));
        return false;
      }
    } catch (downloadErr: any) {
      console.warn(`[AudioQueue] Download failed for ${item.id}:`, downloadErr);
      try {
        await FileSystem.deleteAsync(targetFile, { idempotent: true });
      } catch {}
      item.status = 'ERROR';
      if (this.currentDownloadingId === item.id) {
        this.currentDownloadingId = null;
      }
      this.notify();
      this.flushErrorCallbacks(item, downloadErr);
      return false;
    }
  }

  /**
   * Main sequential background processing loop
   */
  private async processQueue(baseUrl: string = API_BASE_URL) {
    if (this.isProcessing) return;
    this.isProcessing = true;
    const activeGen = this.queueGeneration;

    try {
      while (activeGen === this.queueGeneration) {
        // Find next eligible queued item by priority (0 first, then 1, 2, 3, 4)
        let bestItem: AudioQueueItem | null = null;
        for (const item of this.queue.values()) {
          if (item.status === 'QUEUED') {
            if (!bestItem || item.priority < bestItem.priority) {
              bestItem = item;
            }
          }
        }

        if (!bestItem) {
          // No more queued items
          break;
        }

        await this.downloadItem(bestItem, baseUrl);
        if (activeGen !== this.queueGeneration) {
          break;
        }

        // Responsive sequential delay between background items
        // Priority 0 (urgent): 50ms
        // Priorities 1-3: 150ms
        // Priority 4 (vocabulary): 300ms
        const delayMs = bestItem.priority === 0 ? 50 : bestItem.priority === 4 ? 300 : 150;
        await new Promise((r) => setTimeout(r, delayMs));
      }
    } finally {
      if (activeGen === this.queueGeneration) {
        this.isProcessing = false;
        this.currentDownloadingId = null;
        this.notify();
      }
    }
  }

  /**
   * Handles user tapping an audio play button:
   * 1. If currently playing this id -> pauses audio without unloading buffer.
   * 2. If currently paused on this id -> resumes audio from saved position.
   * 3. If user taps during LOADING state -> cancels waiting/loading state.
   * 4. If playing a different id -> stops previous track completely (seek to 0).
   * 5. If READY on disk -> plays instantly from local cache.
   * 6. If QUEUED / LOADING -> elevates to top priority (0), shows spinner.
   * 7. Fast Streaming Fallback: If local file download hasn't finished in 3.5 seconds,
   *    switches seamlessly to live audio streaming without stalling.
   */
  public async playOrEnqueue(
    id: string,
    text: string,
    lang: 'ru' | 'et',
    bilingual: boolean = false,
    callbacks?: AudioPlaybackCallbacks,
    baseUrl: string = API_BASE_URL,
    grade?: number,
    tier?: string,
    speech_text?: string
  ) {
    const cleanText = this.normalizeText(text);
    const speechText = speech_text ? this.normalizeText(speech_text) : cleanText;

    // 1. Toggle pause/resume if user taps currently active id
    if (this.currentlyPlayingId === id || getCurrentPlayingId() === id) {
      if (this.playbackState === 'playing') {
        await this.pause();
        return;
      } else if (this.playbackState === 'paused') {
        await this.resume();
        return;
      }
    }

    // 2. Toggle off if user taps while this item is currently waiting/loading
    if (this.pendingUserPlayId === id) {
      this.pendingUserPlayId = null;
      const item = this.queue.get(id);
      if (item) {
        item.onReadyCallbacks = [];
        item.onErrorCallbacks = [];
      }
      this.notify();
      return;
    }

    // 3. Stop whatever else was playing/paused when switching to another phrase
    await this.stop();
    this.currentlyPlayingId = null;

    // Check existing item in queue
    let item = this.queue.get(id);
    const targetFile = this.getFilePath(speechText, lang, bilingual, grade, tier);

    // Fast check: is it already on disk and non-empty?
    if (!item || item.status !== 'READY') {
      try {
        const info = await FileSystem.getInfoAsync(targetFile);
        if (info.exists && typeof (info as any).size === 'number' && (info as any).size >= this.MIN_AUDIO_BYTES) {
          if (!item) {
            this.upsertItem({ id, text: cleanText, speech_text: speechText, lang, bilingual, priority: 0, grade, tier });
            item = this.queue.get(id);
          }
          if (item) {
            item.status = 'READY';
            item.localUri = targetFile;
          }
        } else if (info.exists) {
          await FileSystem.deleteAsync(targetFile, { idempotent: true });
        }
      } catch {}
    }

    // CASE A: Item is READY on disk -> Instant audio playback!
    if (item && item.status === 'READY' && item.localUri) {
      this.pendingUserPlayId = null;
      this.currentlyPlayingId = id;
      this.notify(); // Immediately change UI to playing state

      await playTts(
        item.localUri,
        lang,
        id,
        {
          onStart: () => {
            this.currentlyPlayingId = id;
            this.pendingUserPlayId = null;
            this.notify();
            callbacks?.onStart?.();
          },
          onPause: () => {
            callbacks?.onPause?.();
          },
          onResume: () => {
            callbacks?.onResume?.();
          },
          onFinish: () => {
            this.currentlyPlayingId = null;
            this.notify();
            callbacks?.onFinish?.();
          },
          onError: (err) => {
            this.currentlyPlayingId = null;
            this.notify();
            callbacks?.onError?.(err);
          },
        },
        baseUrl,
        item?.bilingual ?? bilingual,
        grade,
        tier
      );
      return;
    }

    // CASE B: Item is not ready yet -> Elevate to urgent priority 0 & show spinner
    this.pendingUserPlayId = id;
    this.notify();

    if (!item) {
      this.upsertItem({ id, text: cleanText, speech_text: speechText, lang, bilingual, priority: 0, grade, tier });
      item = this.queue.get(id)!;
    } else {
      item.priority = 0; // Jump to the front of the queue
      if (speech_text) item.speech_text = speechText;
      if (grade !== undefined) item.grade = grade;
      if (tier !== undefined) item.tier = tier;
      if (item.status === 'ERROR' || item.status === 'IDLE') {
        item.status = 'QUEUED';
      }
    }

    // Reset previous callbacks so we don't stack up obsolete handlers
    item.onReadyCallbacks = [];
    item.onErrorCallbacks = [];

    let fallbackTriggered = false;

    // Fast streaming fallback: If disk download hasn't finished in 3.5 seconds, start live stream directly
    const fallbackTimer = setTimeout(async () => {
      if (this.pendingUserPlayId === id && (!item?.localUri || item?.status !== 'READY')) {
        fallbackTriggered = true;
        console.log(`[AudioQueue] Download taking >3.5s for ${id}, switching to direct streaming...`);
        this.currentlyPlayingId = id;
        this.pendingUserPlayId = null;
        this.notify();

        try {
          await playTts(
            cleanText,
            lang,
            id,
            {
              onStart: () => {
                this.currentlyPlayingId = id;
                this.pendingUserPlayId = null;
                this.notify();
                callbacks?.onStart?.();
              },
              onPause: () => {
                callbacks?.onPause?.();
              },
              onResume: () => {
                callbacks?.onResume?.();
              },
              onFinish: () => {
                this.currentlyPlayingId = null;
                this.notify();
                callbacks?.onFinish?.();
              },
              onError: (playErr) => {
                this.currentlyPlayingId = null;
                this.notify();
                callbacks?.onError?.(playErr);
              },
            },
            baseUrl,
            item?.bilingual ?? bilingual,
            grade,
            tier,
            speechText,
            Boolean(speech_text && speech_text.trim())
          );
        } catch (streamingErr) {
          this.currentlyPlayingId = null;
          this.notify();
          callbacks?.onError?.(streamingErr);
        }
      }
    }, 3500);

    // Register callback for when disk file becomes ready
    item.onReadyCallbacks.push(async (localUri: string) => {
      clearTimeout(fallbackTimer);
      if (fallbackTriggered) {
        return;
      }
      if (this.pendingUserPlayId !== id) {
        return;
      }
      this.currentlyPlayingId = id;
      this.pendingUserPlayId = null;
      this.notify(); // Immediately change UI to playing state

      await playTts(
        localUri,
        lang,
        id,
        {
          onStart: () => {
            this.currentlyPlayingId = id;
            this.pendingUserPlayId = null;
            this.notify();
            callbacks?.onStart?.();
          },
          onPause: () => {
            callbacks?.onPause?.();
          },
          onResume: () => {
            callbacks?.onResume?.();
          },
          onFinish: () => {
            this.currentlyPlayingId = null;
            this.notify();
            callbacks?.onFinish?.();
          },
          onError: (err) => {
            this.currentlyPlayingId = null;
            this.notify();
            callbacks?.onError?.(err);
          },
        },
        baseUrl,
        item?.bilingual ?? bilingual,
        grade,
        tier
      );
    });

    // Fallback: If downloading to disk fails, stream live directly via playTts
    item.onErrorCallbacks.push(async (err) => {
      clearTimeout(fallbackTimer);
      if (fallbackTriggered) {
        return;
      }
      if (this.pendingUserPlayId === id) {
        console.warn(`[AudioQueue] Local download failed for ${id}, falling back to direct stream:`, err);
        this.currentlyPlayingId = id;
        this.pendingUserPlayId = null;
        this.notify();

        try {
          await playTts(
            cleanText,
            lang,
            id,
            {
              onStart: () => {
                this.currentlyPlayingId = id;
                this.pendingUserPlayId = null;
                this.notify();
                callbacks?.onStart?.();
              },
              onPause: () => {
                callbacks?.onPause?.();
              },
              onResume: () => {
                callbacks?.onResume?.();
              },
              onFinish: () => {
                this.currentlyPlayingId = null;
                this.notify();
                callbacks?.onFinish?.();
              },
              onError: (playErr) => {
                this.currentlyPlayingId = null;
                this.notify();
                callbacks?.onError?.(playErr);
              },
            },
            baseUrl,
            item?.bilingual ?? bilingual,
            grade,
            tier
          );
        } catch (streamingErr) {
          this.currentlyPlayingId = null;
          this.notify();
          callbacks?.onError?.(streamingErr);
        }
      }
    });

    // Ensure background queue processor picks up priority 0 item Next without launching parallel downloads
    if (!this.isProcessing) {
      this.processQueue(baseUrl);
    }
  }

  /**
   * Resets the queue and stops any playing audio when switching lessons
   */
  public clearQueue() {
    this.queueGeneration++;
    this.stop();
    this.queue.clear();
    this.pendingUserPlayId = null;
    this.currentlyPlayingId = null;
    this.isProcessing = false;
    this.currentDownloadingId = null;
    this.notify();
  }

  /**
   * Forces complete playback termination, releases audio player via unloadAsync/release,
   * and clears the preload queue when transitioning to background or leaving a lesson screen.
   */
  public async stopAndClear(): Promise<void> {
    this.queueGeneration++;
    try {
      await this.stop();
    } catch {}
    this.queue.clear();
    this.pendingUserPlayId = null;
    this.currentlyPlayingId = null;
    this.isProcessing = false;
    this.currentDownloadingId = null;
    this.notify();
  }

  /**
   * Clears both in-memory queue and cached MP3 files on disk.
   */
  public async clearDiskCache(): Promise<void> {
    this.clearQueue();
    try {
      await FileSystem.deleteAsync(this.cacheDir, { idempotent: true });
      this.dirInitialized = false;
      await this.ensureCacheDir();
    } catch (e) {
      console.warn('[AudioQueue] Failed clearing disk cache:', e);
    }
  }
}

export const AudioQueueManager = new AudioQueueManagerClass();
