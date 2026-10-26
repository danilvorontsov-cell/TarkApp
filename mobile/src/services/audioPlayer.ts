import {
  createAudioPlayer,
  setAudioModeAsync,
  AudioPlayer,
  AudioStatus,
} from 'expo-audio';
import { API_BASE_URL } from './api';

let activePlayer: AudioPlayer | null = null;
let currentPlayingId: string | null = null;
let activeSubscription: { remove: () => void } | null = null;

export interface AudioPlaybackCallbacks {
  onStart?: () => void;
  onFinish?: () => void;
  onError?: (error: any) => void;
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
 * Stops and releases any currently playing audio player.
 */
export async function stopTts(): Promise<void> {
  currentPlayingId = null;

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
      activePlayer.pause();
      if (typeof activePlayer.release === 'function') {
        activePlayer.release();
      }
    } catch (e) {
      console.warn('Error releasing audio player:', e);
    }
    activePlayer = null;
  }
}

/**
 * Streams and plays TTS audio in memory via TarkApp Backend /api/v1/voice/tts
 * @param text The text to synthesize
 * @param lang 'ru' for Russian tutor prompts, 'et' for Estonian vocabulary pronunciation
 * @param playbackId Unique ID (e.g. 'prompt' or word id) to track what is currently playing
 * @param callbacks Lifecycle callbacks (onStart, onFinish, onError)
 * @param baseUrl Optional override for backend URL
 */
export async function playTts(
  text: string,
  lang: 'ru' | 'et' = 'ru',
  playbackId: string = 'prompt',
  callbacks?: AudioPlaybackCallbacks,
  baseUrl: string = API_BASE_URL
): Promise<AudioPlayer | null> {
  // Toggle off if currently playing this item
  if (activePlayer && currentPlayingId === playbackId) {
    await stopTts();
    callbacks?.onFinish?.();
    return null;
  }

  // Stop any previous audio
  await stopTts();

  if (!text || !text.trim()) {
    return null;
  }

  await ensureAudioMode();

  const isDirectUri =
    text.startsWith('file://') ||
    text.startsWith('http://') ||
    text.startsWith('https://');

  const url = isDirectUri
    ? text
    : `${baseUrl}/api/v1/voice/tts?text=${encodeURIComponent(text.trim())}&lang=${lang}`;

  try {
    currentPlayingId = playbackId;

    const player = createAudioPlayer(url);
    activePlayer = player;

    callbacks?.onStart?.();

    activeSubscription = player.addListener('playbackStatusUpdate', (status: AudioStatus) => {
      if (status.didJustFinish) {
        stopTts();
        callbacks?.onFinish?.();
      }
    });

    player.play();
    return player;
  } catch (error) {
    console.error('Failed to load or play TTS stream via expo-audio:', error);
    currentPlayingId = null;
    activePlayer = null;
    callbacks?.onError?.(error);
    return null;
  }
}

export function getCurrentPlayingId(): string | null {
  return currentPlayingId;
}
