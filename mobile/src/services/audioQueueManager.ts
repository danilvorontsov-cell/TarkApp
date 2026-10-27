import * as FileSystem from 'expo-file-system/legacy';
import { API_BASE_URL } from './api';
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
} from './audioPlayer';
import { PageAnalysisResponse } from '../types';
import { getTierPolicy, SchoolTier } from './gradePolicy';

export { PlaybackState } from './audioPlayer';

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

export type QueueListener = (state: {
  playingId: string | null;
  playbackState: PlaybackState;
  loadingAudioId: string | null;
  itemStatuses: Record<string, AudioItemStatus>;
}) => void;

class AudioQueueManagerClass {
  private queue: Map<string, AudioQueueItem> = new Map();
  private isProcessing: boolean = false;
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

    const policy = gradeOrTier !== undefined ? getTierPolicy(gradeOrTier) : null;
    const isFullAudio = policy ? policy.fullAudioEnabled : true;
    const isVocabAudio = policy ? policy.vocabAudioEnabled : true;

    // 1. Priority 1: Partner prompt (voice_prompt_script)
    if (isFullAudio && analysis.voice_prompt_script && analysis.voice_prompt_script.trim()) {
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

    // 2. Priority 2: Theme explanation (theme_explanation) with bilingual stitching
    if (isFullAudio && analysis.theme_explanation && analysis.theme_explanation.trim()) {
      this.upsertItem({
        id: 'theme_explanation',
        text: analysis.theme_explanation,
        lang: 'ru',
        bilingual: true,
        priority: 2,
      });
    }

    // 2b. Priority 2: Alternative explanation (alt_explanation) with bilingual stitching
    if (isFullAudio && analysis.alternative_explanation && analysis.alternative_explanation.trim()) {
      this.upsertItem({
        id: 'alt_explanation',
        text: analysis.alternative_explanation,
        lang: 'ru',
        bilingual: true,
        priority: 2,
      });
    }

    // 3. Priority 3: How to answer (how_to_answer) with bilingual stitching
    if (isFullAudio && analysis.how_to_answer && analysis.how_to_answer.trim()) {
      this.upsertItem({
        id: 'how_to_answer',
        text: analysis.how_to_answer,
        lang: 'ru',
        bilingual: true,
        priority: 3,
      });
    }

    // 3b. Priority 3: Worked example (worked_example) with bilingual stitching
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
      const formattedSteps = we.steps.map((step, sIdx) => {
        const clean = step.replace(/^\d+[\.\)]\s*/, '').trim();
        const prefix = ORDINAL_STEP_WORDS[sIdx + 1] || `${sIdx + 1}-е`;
        return `${prefix}: ${clean}`;
      });
      const naidisAudioText = `${we.given}. Шаги решения: ${formattedSteps.join('. ')}. ${we.note || ''}`.trim();
      if (naidisAudioText.trim()) {
        this.upsertItem({
          id: 'worked_example',
          text: naidisAudioText,
          lang: 'ru',
          bilingual: true,
          priority: 3,
        });
      }
    }

    // 4. Priority 4: Vocabulary terms and examples (one by one)
    if (isVocabAudio && analysis.vocabulary && analysis.vocabulary.length > 0) {
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
        if (this.currentDownloadingId === item.id) {
          this.currentDownloadingId = null;
        }
        this.notify();
        this.flushCallbacks(item);
        return true;
      } else {
        const fileSize = (downloadedInfo.exists && typeof (downloadedInfo as any).size === 'number') ? (downloadedInfo as any).size : 0;
        console.warn(`[AudioQueue] Download invalid for ${item.id}: HTTP status ${result.status}, size: ${fileSize} bytes`);
        if (downloadedInfo.exists) {
          await FileSystem.deleteAsync(targetFile, { idempotent: true });
        }
        item.status = 'ERROR';
        if (this.currentDownloadingId === item.id) {
          this.currentDownloadingId = null;
        }
        this.notify();
        this.flushErrorCallbacks(item, new Error(`Download returned HTTP ${result.status}, size: ${fileSize}`));
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

        // Responsive sequential delay between background items
        // Priority 0 (urgent): 50ms
        // Priorities 1-3: 150ms
        // Priority 4 (vocabulary): 300ms
        const delayMs = bestItem.priority === 0 ? 50 : bestItem.priority === 4 ? 300 : 150;
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
    baseUrl: string = API_BASE_URL
  ) {
    const cleanText = this.normalizeText(text);

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
      this.currentlyPlayingId = id;
      this.notify(); // Immediately change UI to playing state

      await playTts(item.localUri, lang, id, {
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
          await playTts(cleanText, lang, id, {
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
          }, baseUrl, item?.bilingual ?? bilingual);
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

      await playTts(localUri, lang, id, {
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
      }, baseUrl);
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
          await playTts(cleanText, lang, id, {
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
          }, baseUrl, item?.bilingual ?? bilingual);
        } catch (streamingErr) {
          this.currentlyPlayingId = null;
          this.notify();
          callbacks?.onError?.(streamingErr);
        }
      }
    });

    // If item is not currently downloading, start download immediately
    if (this.currentDownloadingId !== id && item.status !== 'LOADING') {
      this.downloadItem(item, baseUrl);
    } else {
      this.processQueue(baseUrl);
    }
  }

  /**
   * Resets the queue and stops any playing audio when switching lessons
   */
  public clearQueue() {
    this.stop();
    this.queue.clear();
    this.pendingUserPlayId = null;
    this.currentlyPlayingId = null;
    this.isProcessing = false;
    this.currentDownloadingId = null;
    this.notify();
  }
}

export const AudioQueueManager = new AudioQueueManagerClass();
