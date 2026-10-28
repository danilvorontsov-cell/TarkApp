import {
  createAudioPlayer,
  setAudioModeAsync,
  AudioPlayer,
  AudioStatus,
} from 'expo-audio';
import { API_BASE_URL, resolveBaseUrl } from './api';

export type PlaybackState = 'idle' | 'playing' | 'paused';

let activePlayer: AudioPlayer | null = null;
let currentPlayingId: string | null = null;
let activeSubscription: { remove: () => void } | null = null;
let playbackState: PlaybackState = 'idle';
let currentCallbacks: AudioPlaybackCallbacks | null = null;
let currentPlayToken: number = 0;

export interface AudioPlaybackCallbacks {
  onStart?: () => void;
  onPause?: () => void;
  onResume?: () => void;
  onFinish?: () => void;
  onError?: (error: any) => void;
}

const stateListeners: Set<(state: PlaybackState, playingId: string | null) => void> = new Set();

function notifyStateListeners() {
  stateListeners.forEach((listener) => {
    try {
      listener(playbackState, currentPlayingId);
    } catch (e) {
      console.warn('Error in playback state listener:', e);
    }
  });
}

export function subscribePlaybackState(
  listener: (state: PlaybackState, playingId: string | null) => void
): () => void {
  stateListeners.add(listener);
  listener(playbackState, currentPlayingId);
  return () => {
    stateListeners.delete(listener);
  };
}

export function getPlaybackState(): PlaybackState {
  return playbackState;
}

export function getCurrentPlayingId(): string | null {
  return currentPlayingId;
}

export function getCurrentPlayToken(): number {
  return currentPlayToken;
}

/**
 * Configure audio mode for speech playback.
 */
async function ensureAudioMode() {
  try {
    await setAudioModeAsync({
      playsInSilentMode: true,
    });
  } catch (err) {
    console.warn('Failed to set audio mode in expo-audio:', err);
  }
}

/**
 * Pauses playback without unloading audio buffer from memory.
 */
export async function pauseTts(): Promise<void> {
  if (activePlayer && playbackState === 'playing') {
    try {
      if (typeof (activePlayer as any).pauseAsync === 'function') {
        await (activePlayer as any).pauseAsync();
      } else if (typeof activePlayer.pause === 'function') {
        activePlayer.pause();
      }
      playbackState = 'paused';
      notifyStateListeners();
      currentCallbacks?.onPause?.();
    } catch (e) {
      console.warn('Error pausing audio player:', e);
    }
  }
}
export const pause = pauseTts;

/**
 * Resumes playback from the saved position.
 */
export async function resumeTts(): Promise<void> {
  if (activePlayer && playbackState === 'paused') {
    try {
      if (typeof (activePlayer as any).playAsync === 'function') {
        await (activePlayer as any).playAsync();
      } else if (typeof activePlayer.play === 'function') {
        activePlayer.play();
      }
      playbackState = 'playing';
      notifyStateListeners();
      currentCallbacks?.onResume?.();
    } catch (e) {
      console.warn('Error resuming audio player:', e);
    }
  }
}
export const resume = resumeTts;

/**
 * Stops playback completely, seeks to position 0, and releases the audio player instance.
 * @param incrementToken Whether to increment currentPlayToken to invalidate in-flight playTts calls.
 */
export async function stopTts(incrementToken: boolean = true): Promise<void> {
  if (incrementToken) {
    currentPlayToken++; // Invalidate any pending in-flight playback invocations
  }
  const prevCallbacks = currentCallbacks;
  currentCallbacks = null;
  currentPlayingId = null;
  playbackState = 'idle';
  notifyStateListeners();

  if (activeSubscription) {
    try {
      activeSubscription.remove();
    } catch {
      // ignore
    }
    activeSubscription = null;
  }

  if (activePlayer) {
    try {
      if (typeof (activePlayer as any).pauseAsync === 'function') {
        await (activePlayer as any).pauseAsync();
      } else if (typeof activePlayer.pause === 'function') {
        activePlayer.pause();
      }

      if (typeof activePlayer.seekTo === 'function') {
        try {
          await activePlayer.seekTo(0);
        } catch {
          // ignore
        }
      } else if (typeof (activePlayer as any).setPositionAsync === 'function') {
        try {
          await (activePlayer as any).setPositionAsync(0);
        } catch {
          // ignore
        }
      }

      if (typeof activePlayer.release === 'function') {
        activePlayer.release();
      }
    } catch (e) {
      console.warn('Error releasing audio player:', e);
    }
    activePlayer = null;
  }

  prevCallbacks?.onFinish?.();
}
export const stop = stopTts;

/**
 * Streams and plays TTS audio in memory via TarkApp Backend /api/v1/voice/tts
 * @param text The text to synthesize
 * @param lang 'ru' for Russian tutor prompts, 'et' for Estonian vocabulary pronunciation
 * @param playbackId Unique ID (e.g. 'prompt' or word id) to track what is currently playing
 * @param callbacks Lifecycle callbacks (onStart, onPause, onResume, onFinish, onError)
 * @param baseUrl Optional override for backend URL
 * @param bilingual Whether to stitch bilingual Estonian quotes
 */
export async function playTts(
  text: string,
  lang: 'ru' | 'et' = 'ru',
  playbackId: string = 'prompt',
  callbacks?: AudioPlaybackCallbacks,
  baseUrl: string = API_BASE_URL,
  bilingual: boolean = false
): Promise<AudioPlayer | null> {
  // If already active on this ID:
  if (activePlayer && currentPlayingId === playbackId) {
    if (playbackState === 'playing') {
      await pauseTts();
      return activePlayer;
    } else if (playbackState === 'paused') {
      await resumeTts();
      return activePlayer;
    }
  }

  // Assign fresh play token to prevent race conditions on rapid multi-clicks
  const thisToken = ++currentPlayToken;

  // Stop any previous audio without self-invalidating thisToken
  await stopTts(false);

  // If another playTts or external stopTts was called while waiting, cancel immediately
  if (thisToken !== currentPlayToken) {
    return null;
  }

  if (!text || !text.trim()) {
    return null;
  }

  await ensureAudioMode();

  if (thisToken !== currentPlayToken) {
    return null;
  }

  const isDirectUri =
    text.startsWith('file://') ||
    text.startsWith('http://') ||
    text.startsWith('https://');

  const activeBaseUrl = resolveBaseUrl(baseUrl);
  const bilingualParam = bilingual ? '&bilingual=true' : '';
  const url = isDirectUri
    ? text
    : `${activeBaseUrl}/api/v1/voice/tts?text=${encodeURIComponent(text.trim())}&lang=${lang}${bilingualParam}`;

  try {
    if (thisToken !== currentPlayToken) {
      return null;
    }

    currentPlayingId = playbackId;
    currentCallbacks = callbacks || null;

    const player = createAudioPlayer(url);

    // If another sound was triggered during player creation, release and bail
    if (thisToken !== currentPlayToken) {
      try {
        if (typeof player.release === 'function') player.release();
      } catch {}
      return null;
    }

    activePlayer = player;
    playbackState = 'playing';
    notifyStateListeners();

    callbacks?.onStart?.();

    activeSubscription = player.addListener('playbackStatusUpdate', (status: AudioStatus) => {
      if (thisToken !== currentPlayToken) return;
      if (status.didJustFinish) {
        stopTts();
      }
    });

    player.play();
    return player;
  } catch (error) {
    if (thisToken === currentPlayToken) {
      console.error('Failed to load or play TTS stream via expo-audio:', error);
      currentPlayingId = null;
      playbackState = 'idle';
      activePlayer = null;
      currentCallbacks = null;
      notifyStateListeners();
      callbacks?.onError?.(error);
    }
    return null;
  }
}
