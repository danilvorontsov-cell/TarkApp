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

  private getHash(str: string): string {
    let hash = 0;
    for (let i = 0; i < str.length; i++) {
      hash = (hash << 5) - hash + str.charCodeAt(i);
      hash |= 0;
    }
    return Math.abs(hash).toString(36);
  }

  private getFilePath(text: string, lang: string, bilingual: boolean): string {
    const key = `${lang}_${bilingual ? 'bi' : 'mono'}_${this.getHash(text.trim())}`;
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
    const existing = this.queue.get(params.id);
    const targetFile = this.getFilePath(params.text, params.lang, params.bilingual);

    if (existing) {
      // If text changed, update text and reset status
      if (existing.text !== params.text) {
        existing.text = params.text;
        existing.status = 'QUEUED';
        existing.localUri = undefined;
      }
      existing.priority = Math.min(existing.priority, params.priority);
      return;
    }

    this.queue.set(params.id, {
      id: params.id,
      text: params.text,
      lang: params.lang,
      bilingual: params.bilingual,
      priority: params.priority,
      status: 'QUEUED',
      localUri: undefined,
      onReadyCallbacks: [],
      onErrorCallbacks: [],
    });
  }

  /**
   * Main sequential processing loop
   */
  private async processQueue(baseUrl: string = API_BASE_URL) {
    if (this.isProcessing) return;
    this.isProcessing = true;

    try {
      while (true) {
        // Find next eligible item by priority (0 first, then 1, 2, 3, 4)
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

        const currentItem = bestItem;
        this.currentDownloadingId = currentItem.id;
        currentItem.status = 'LOADING';
        this.notify();

        const targetFile = this.getFilePath(currentItem.text, currentItem.lang, currentItem.bilingual);

        try {
          // Check if valid non-empty audio file is already cached on disk
          const info = await FileSystem.getInfoAsync(targetFile);
          if (info.exists && typeof (info as any).size === 'number' && (info as any).size >= this.MIN_AUDIO_BYTES) {
            currentItem.status = 'READY';
            currentItem.localUri = targetFile;
          } else {
            if (info.exists) {
              await FileSystem.deleteAsync(targetFile, { idempotent: true });
            }

            // Build TTS API endpoint URL
            const encodedText = encodeURIComponent(currentItem.text.trim());
            const bilingualParam = currentItem.bilingual ? '&bilingual=true' : '';
            const downloadUrl = `${baseUrl}/api/v1/voice/tts?text=${encodedText}&lang=${currentItem.lang}${bilingualParam}`;

            const result = await FileSystem.downloadAsync(downloadUrl, targetFile);
            const downloadedInfo = await FileSystem.getInfoAsync(targetFile);

            if (
              result.status === 200 &&
              downloadedInfo.exists &&
              typeof (downloadedInfo as any).size === 'number' &&
              (downloadedInfo as any).size >= this.MIN_AUDIO_BYTES
            ) {
              currentItem.status = 'READY';
              currentItem.localUri = targetFile;
            } else {
              if (downloadedInfo.exists) {
                await FileSystem.deleteAsync(targetFile, { idempotent: true });
              }
              currentItem.status = 'ERROR';
            }
          }
        } catch (downloadErr) {
          console.warn(`[AudioQueue] Background prefetch failed silently for ${currentItem.id}:`, downloadErr);
          try {
            await FileSystem.deleteAsync(targetFile, { idempotent: true });
          } catch {}
          currentItem.status = 'ERROR';
        }

        // Notify callbacks if user was waiting for this item
        if (currentItem.status === 'READY' && currentItem.localUri) {
          const callbacks = [...currentItem.onReadyCallbacks];
          currentItem.onReadyCallbacks = [];
          callbacks.forEach((cb) => {
            try {
              cb(currentItem.localUri!);
            } catch (err) {
              console.warn('Error in onReadyCallback:', err);
            }
          });
        } else if (currentItem.status === 'ERROR') {
          const errCallbacks = [...currentItem.onErrorCallbacks];
          currentItem.onErrorCallbacks = [];
          errCallbacks.forEach((cb) => {
            try {
              cb(new Error(`Failed to download audio for ${currentItem.id}`));
            } catch (err) {
              console.warn('Error in onErrorCallback:', err);
            }
          });
        }

        this.currentDownloadingId = null;
        this.notify();

        // Sequential delay:
        // Priorities 1, 2, 3: 350ms delay
        // Priority 4: 300ms delay
        // Urgent user request (priority 0): no extra delay
        const delayMs = currentItem.priority === 4 ? 300 : currentItem.priority > 0 ? 350 : 50;
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
   * 3. If LOADING or QUEUED -> elevates to top priority (0), shows spinner, plays as soon as bytes arrive.
   * 4. If IDLE or ERROR -> enqueues at priority 0, starts immediate download & play without duplicates.
   */
  public async playOrEnqueue(
    id: string,
    text: string,
    lang: 'ru' | 'et',
    bilingual: boolean = false,
    callbacks?: AudioPlaybackCallbacks,
    baseUrl: string = API_BASE_URL
  ) {
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
    const targetFile = this.getFilePath(text, lang, bilingual);

    // Fast check: is it already on disk and non-empty?
    if (!item || item.status !== 'READY') {
      try {
        const info = await FileSystem.getInfoAsync(targetFile);
        if (info.exists && typeof (info as any).size === 'number' && (info as any).size >= this.MIN_AUDIO_BYTES) {
          if (!item) {
            this.upsertItem({ id, text, lang, bilingual, priority: 0 });
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
      this.upsertItem({ id, text, lang, bilingual, priority: 0 });
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
        // User clicked something else in the meantime
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

    item.onErrorCallbacks.push((err) => {
      if (this.pendingUserPlayId === id) {
        this.pendingUserPlayId = null;
        this.notify();
        callbacks?.onError?.(err);
      }
    });

    // Kick processing loop immediately
    this.processQueue(baseUrl);
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
