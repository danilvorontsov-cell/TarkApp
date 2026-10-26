import * as FileSystem from 'expo-file-system/legacy';
import { API_BASE_URL } from './api';
import { playTts, stopTts, AudioPlaybackCallbacks, getCurrentPlayingId } from './audioPlayer';
import { PageAnalysisResponse } from '../types';

export type AudioItemStatus = 'IDLE' | 'QUEUED' | 'LOADING' | 'READY' | 'ERROR';

export interface AudioQueueItem {
  id: string;
  text: string;
  lang: 'ru' | 'et';
  bilingual: boolean;
  priority: number; // 0 = urgent user click, 1 = prompt, 2 = theme, 3 = how_to_answer, 4 = vocabulary
  status: AudioItemStatus;
  localUri?: string;
  onReadyCallbacks: Array<(uri: string) => void>;
  onErrorCallbacks: Array<(err: any) => void>;
}

type QueueListener = (state: {
  playingId: string | null;
  loadingAudioId: string | null;
  itemStatuses: Record<string, AudioItemStatus>;
}) => void;

class AudioQueueManagerClass {
  private queue: Map<string, AudioQueueItem> = new Map();
  private isProcessing: boolean = false;
  private currentDownloadingId: string | null = null;
  private pendingUserPlayId: string | null = null;
  private listeners: Set<QueueListener> = new Set();
  private cacheDir: string = `${FileSystem.cacheDirectory || ''}tarkapp_audio/`;
  private dirInitialized: boolean = false;
  private readonly MIN_AUDIO_BYTES: number = 800; // Minimum size for valid MP3 speech

  constructor() {
    this.ensureCacheDir();
  }

  private async ensureCacheDir() {
    if (this.dirInitialized) return;
    try {
      const dirInfo = await FileSystem.getInfoAsync(this.cacheDir);
      if (!dirInfo.exists) {
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
    } catch (e) {
      console.warn('Failed to initialize audio cache directory:', e);
    }
  }

  public normalizeText(str: string): string {
    if (!str) return '';
    return str.replace(/^[«"“„\s]+|[»"”\s]+$/g, '').trim();
  }

  private getHash(str: string): string {
    let hash = 0;
    const clean = this.normalizeText(str);
    for (let i = 0; i < clean.length; i++) {
      hash = (hash << 5) - hash + clean.charCodeAt(i);
      hash |= 0;
    }
    return Math.abs(hash).toString(36);
  }

  private getFilePath(text: string, lang: string, bilingual: boolean): string {
    const key = `${lang}_${bilingual ? 'bi' : 'mono'}_${this.getHash(text)}`;
    return `${this.cacheDir}${key}.mp3`;
  }

  private notify() {
    const itemStatuses: Record<string, AudioItemStatus> = {};
    this.queue.forEach((item, id) => {
      itemStatuses[id] = item.status;
    });

    const state = {
      playingId: getCurrentPlayingId(),
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

  /**
   * Enqueues all audio items from a parsed lesson according to sequential priority:
   * Priority 1 (Immediate): voice_prompt_script
   * Priority 2 (300-400ms pause): theme_explanation
   * Priority 3 (300-400ms pause): how_to_answer (bilingual)
   * Priority 4 (300ms pause each): vocabulary words & examples
   */
  public async prefetchLessonAudio(analysis: PageAnalysisResponse, baseUrl: string = API_BASE_URL) {
    await this.ensureCacheDir();

    // 1. Priority 1: Partner prompt (voice_prompt_script)
    if (analysis.voice_prompt_script && analysis.voice_prompt_script.trim()) {
      this.upsertItem({
        id: 'voice_prompt',
        text: analysis.voice_prompt_script,
        lang: 'ru',
        bilingual: false,
        priority: 1,
      });

      // Senior voice shares the exact same text
      this.upsertItem({
        id: 'senior_voice',
        text: analysis.voice_prompt_script,
        lang: 'ru',
        bilingual: false,
        priority: 1,
      });
    }

    // 2. Priority 2: Theme explanation (theme_explanation)
    if (analysis.theme_explanation && analysis.theme_explanation.trim()) {
      this.upsertItem({
        id: 'theme_explanation',
        text: analysis.theme_explanation,
        lang: 'ru',
        bilingual: false,
        priority: 2,
      });
    }

    // 3. Priority 3: How to answer (how_to_answer) with bilingual stitching
    if (analysis.how_to_answer && analysis.how_to_answer.trim()) {
      this.upsertItem({
        id: 'how_to_answer',
        text: analysis.how_to_answer,
        lang: 'ru',
        bilingual: true,
        priority: 3,
      });
    }

    // 4. Priority 4: Vocabulary terms and examples (one by one)
    if (analysis.vocabulary && analysis.vocabulary.length > 0) {
      analysis.vocabulary.forEach((item, idx) => {
        if (item.est && item.est.trim()) {
          this.upsertItem({
            id: `vocab_${idx}`,
            text: item.est,
            lang: 'et',
            bilingual: false,
            priority: 4,
          });
        }

        if (item.example && item.example.trim()) {
          this.upsertItem({
            id: `vocab_ex_${idx}`,
            text: item.example,
            lang: 'et',
            bilingual: false,
            priority: 4,
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
    lang: 'ru' | 'et';
    bilingual: boolean;
    priority: number;
  }) {
    const cleanText = this.normalizeText(params.text);
    const existing = this.queue.get(params.id);

    if (existing) {
      if (existing.text !== cleanText) {
        existing.text = cleanText;
        existing.status = 'QUEUED';
        existing.localUri = undefined;
      }
      existing.priority = Math.min(existing.priority, params.priority);
      return;
    }

    this.queue.set(params.id, {
      id: params.id,
      text: cleanText,
      lang: params.lang,
      bilingual: params.bilingual,
      priority: params.priority,
      status: 'QUEUED',
      localUri: undefined,
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
    const targetFile = this.getFilePath(item.text, item.lang, item.bilingual);
    this.currentDownloadingId = item.id;
    item.status = 'LOADING';
    this.notify();

    try {
      const info = await FileSystem.getInfoAsync(targetFile);
      if (info.exists && typeof (info as any).size === 'number' && (info as any).size >= this.MIN_AUDIO_BYTES) {
        item.status = 'READY';
        item.localUri = targetFile;
        this.currentDownloadingId = null;
        this.notify();
        this.flushCallbacks(item);
        return true;
      }

      if (info.exists) {
        await FileSystem.deleteAsync(targetFile, { idempotent: true });
      }

      const encodedText = encodeURIComponent(item.text);
      const bilingualParam = item.bilingual ? '&bilingual=true' : '';
      const downloadUrl = `${baseUrl}/api/v1/voice/tts?text=${encodedText}&lang=${item.lang}${bilingualParam}`;

      const result = await FileSystem.downloadAsync(downloadUrl, targetFile);
      const downloadedInfo = await FileSystem.getInfoAsync(targetFile);

      if (
        result.status === 200 &&
        downloadedInfo.exists &&
        typeof (downloadedInfo as any).size === 'number' &&
        (downloadedInfo as any).size >= this.MIN_AUDIO_BYTES
      ) {
        item.status = 'READY';
        item.localUri = targetFile;
        this.currentDownloadingId = null;
        this.notify();
        this.flushCallbacks(item);
        return true;
      } else {
        if (downloadedInfo.exists) {
          await FileSystem.deleteAsync(targetFile, { idempotent: true });
        }
        item.status = 'ERROR';
        this.currentDownloadingId = null;
        this.notify();
        this.flushErrorCallbacks(item, new Error('Download returned invalid audio size'));
        return false;
      }
    } catch (downloadErr: any) {
      console.warn(`[AudioQueue] Download failed for ${item.id}:`, downloadErr);
      try {
        await FileSystem.deleteAsync(targetFile, { idempotent: true });
      } catch {}
      item.status = 'ERROR';
      this.currentDownloadingId = null;
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

    try {
      while (true) {
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

        // Relaxed sequential delay between background items to prevent Edge-TTS socket congestion:
        // Priority 0 (urgent): 50ms
        // Priorities 1-3: 400ms
        // Priority 4 (vocabulary): 500ms
        const delayMs = bestItem.priority === 0 ? 50 : bestItem.priority === 4 ? 500 : 400;
        await new Promise((r) => setTimeout(r, delayMs));
      }
    } finally {
      this.isProcessing = false;
      this.currentDownloadingId = null;
      this.notify();
    }
  }

  /**
   * Handles user tapping an audio play button:
   * 1. If currently playing this id -> toggle stop.
   * 2. If already READY -> plays instantly from local cache.
   * 3. If LOADING or QUEUED -> elevates to top priority (0), shows spinner, triggers immediate download.
   * 4. If IDLE or ERROR -> enqueues at priority 0, starts immediate download.
   * 5. If local caching fails -> seamlessly falls back to direct live audio streaming (never shows error alert).
   */
  public async playOrEnqueue(
    id: string,
    text: string,
    lang: 'ru' | 'et',
    bilingual: boolean = false,
    callbacks?: AudioPlaybackCallbacks,
    baseUrl: string = API_BASE_URL
  ) {
    const cleanText = this.normalizeText(text);

    // 1. Toggle off if already playing this id
    if (getCurrentPlayingId() === id) {
      await stopTts();
      callbacks?.onFinish?.();
      this.notify();
      return;
    }

    // Stop whatever else was playing
    await stopTts();

    // Check existing item in queue
    let item = this.queue.get(id);
    const targetFile = this.getFilePath(cleanText, lang, bilingual);

    // Fast check: is it already on disk and non-empty?
    if (!item || item.status !== 'READY') {
      try {
        const info = await FileSystem.getInfoAsync(targetFile);
        if (info.exists && typeof (info as any).size === 'number' && (info as any).size >= this.MIN_AUDIO_BYTES) {
          if (!item) {
            this.upsertItem({ id, text: cleanText, lang, bilingual, priority: 0 });
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
      this.notify();

      await playTts(item.localUri, lang, id, {
        onStart: () => {
          this.notify();
          callbacks?.onStart?.();
        },
        onFinish: () => {
          this.notify();
          callbacks?.onFinish?.();
        },
        onError: (err) => {
          this.notify();
          callbacks?.onError?.(err);
        },
      }, baseUrl);
      return;
    }

    // CASE B: Item is not ready yet -> Elevate to urgent priority 0 & show spinner
    this.pendingUserPlayId = id;
    this.notify();

    if (!item) {
      this.upsertItem({ id, text: cleanText, lang, bilingual, priority: 0 });
      item = this.queue.get(id)!;
    } else {
      item.priority = 0; // Jump to the front of the queue
      if (item.status === 'ERROR' || item.status === 'IDLE') {
        item.status = 'QUEUED';
      }
    }

    // Register playback trigger when file is ready
    item.onReadyCallbacks.push(async (localUri: string) => {
      if (this.pendingUserPlayId !== id) {
        return;
      }
      this.pendingUserPlayId = null;
      this.notify();

      await playTts(localUri, lang, id, {
        onStart: () => {
          this.notify();
          callbacks?.onStart?.();
        },
        onFinish: () => {
          this.notify();
          callbacks?.onFinish?.();
        },
        onError: (err) => {
          this.notify();
          callbacks?.onError?.(err);
        },
      }, baseUrl);
    });

    // Fallback: If downloading to disk fails, stream live directly via playTts
    item.onErrorCallbacks.push(async (err) => {
      if (this.pendingUserPlayId === id) {
        console.warn(`[AudioQueue] Local download failed for ${id}, falling back to live direct stream:`, err);
        try {
          await playTts(cleanText, lang, id, {
            onStart: () => {
              this.pendingUserPlayId = null;
              this.notify();
              callbacks?.onStart?.();
            },
            onFinish: () => {
              this.pendingUserPlayId = null;
              this.notify();
              callbacks?.onFinish?.();
            },
            onError: (playErr) => {
              this.pendingUserPlayId = null;
              this.notify();
              callbacks?.onError?.(playErr);
            },
          }, baseUrl);
        } catch (streamingErr) {
          this.pendingUserPlayId = null;
          this.notify();
          callbacks?.onError?.(streamingErr);
        }
      }
    });

    // If not currently downloading this item, trigger immediate download
    if (this.currentDownloadingId !== id) {
      this.downloadItem(item, baseUrl);
    } else {
      this.processQueue(baseUrl);
    }
  }

  /**
   * Resets the queue when switching to a new lesson
   */
  public clearQueue() {
    this.queue.clear();
    this.pendingUserPlayId = null;
    this.isProcessing = false;
    this.currentDownloadingId = null;
    this.notify();
  }
}

export const AudioQueueManager = new AudioQueueManagerClass();
