import {
  createAudioPlayer,
  setAudioModeAsync,
  AudioPlayer,
  AudioStatus,
} from 'expo-audio';
import * as FileSystem from 'expo-file-system/legacy';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { API_BASE_URL, getDeviceId, resolveBaseUrl } from './api';
import { sanitizeTextForTts } from '../utils/textSanitizer';

export const AUDIO_CACHE_VERSION = 2;
const CACHE_VERSION_KEY = '@tarkapp_audio_cache_version';

export async function ensureAudioCacheDir(cacheDir: string): Promise<void> {
  try {
    const storedVersionStr = await AsyncStorage.getItem(CACHE_VERSION_KEY);
    const storedVersion = storedVersionStr ? parseInt(storedVersionStr, 10) : 0;
    const dirInfo = await FileSystem.getInfoAsync(cacheDir);

    if (storedVersion < AUDIO_CACHE_VERSION) {
      if (dirInfo.exists) {
        await FileSystem.deleteAsync(cacheDir, { idempotent: true });
      }
      await FileSystem.makeDirectoryAsync(cacheDir, { intermediates: true });
      await AsyncStorage.setItem(CACHE_VERSION_KEY, String(AUDIO_CACHE_VERSION));
    } else if (!dirInfo.exists) {
      await FileSystem.makeDirectoryAsync(cacheDir, { intermediates: true });
    }
  } catch (err) {
    console.warn('Error in ensureAudioCacheDir:', err);
  }
}

/**
 * 64-bit FNV-1a hash with string length concatenation to eliminate collisions.
 */
export function getFileHash(str: string): string {
  const clean = (str || '').replace(/^[«"“„\s]+|[»"”\s]+$/g, '').trim().toLowerCase();
  const len = clean.length;
  let hash = 14695981039346656037n;
  const prime = 1099511628211n;
  const mask = 0xffffffffffffffffn;

  for (let i = 0; i < len; i++) {
    hash ^= BigInt(clean.charCodeAt(i));
    hash = (hash * prime) & mask;
  }
  return `${hash.toString(16)}_${len}`;
}

async function getStoredProfile(): Promise<{ grade: number; tier: string }> {
  try {
    const raw = await AsyncStorage.getItem('@tarkapp_user_profile');
    if (raw) {
      const parsed = JSON.parse(raw);
      return {
        grade: Number(parsed.grade) || 1,
        tier: typeof parsed.tier === 'string' && parsed.tier ? parsed.tier : 'primary',
      };
    }
  } catch {}
  return { grade: 1, tier: 'primary' };
}

export type PlaybackState = 'idle' | 'playing' | 'paused';

export const InterruptionModeIOS = {
  DoNotMix: 'doNotMix' as const,
};

export const InterruptionModeAndroid = {
  DoNotMix: 'doNotMix' as const,
};

let activePlayer: AudioPlayer | null = null;
let currentPlayingId: string | null = null;
let activeSubscription: { remove: () => void } | null = null;
let playbackState: PlaybackState = 'idle';
let currentCallbacks: AudioPlaybackCallbacks | null = null;
let currentPlayToken: number = 0;
let internalActionInProgress: boolean = false;

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
 * Configure audio mode for speech playback with exclusive transient focus (DoNotMix)
 * so OS audio interruptions (phone calls, headphone unplugging) deliver status updates.
 */
async function ensureAudioMode() {
  try {
    await setAudioModeAsync({
      playsInSilentMode: true,
      interruptionMode: InterruptionModeIOS.DoNotMix,
      interruptionModeAndroid: InterruptionModeAndroid.DoNotMix,
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
    internalActionInProgress = true;
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
    } finally {
      internalActionInProgress = false;
    }
  }
}
export const pause = pauseTts;

/**
 * Resumes playback from the saved position.
 */
export async function resumeTts(): Promise<void> {
  if (activePlayer && playbackState === 'paused') {
    internalActionInProgress = true;
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
    } finally {
      internalActionInProgress = false;
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

      if (typeof (activePlayer as any).unloadAsync === 'function') {
        try {
          await (activePlayer as any).unloadAsync();
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
 * @param text The text to synthesize (or local file:// URI)
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
  bilingual: boolean = false,
  grade?: number,
  tier?: string,
  speechText?: string,
  isSpeechText?: boolean
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

  let deviceId = '';
  if (!isDirectUri) {
    try {
      deviceId = await getDeviceId();
    } catch {
      deviceId = '';
    }
    if (thisToken !== currentPlayToken) {
      return null;
    }
  }

  const activeBaseUrl = resolveBaseUrl(baseUrl);
  let effectiveUri: string = text;

  if (!isDirectUri) {
    const cleanText = text.trim();
    const synthText = (speechText && speechText.trim()) ? speechText.trim() : cleanText;
    const effectiveIsSpeech = isSpeechText ?? Boolean(speechText && speechText.trim());

    let effectiveGrade = grade;
    let effectiveTier = tier;
    if (effectiveGrade === undefined || effectiveTier === undefined) {
      const stored = await getStoredProfile();
      if (effectiveGrade === undefined) effectiveGrade = stored.grade;
      if (effectiveTier === undefined) effectiveTier = stored.tier;
    }

    if (thisToken !== currentPlayToken) {
      return null;
    }

    const sanitizedSynthText = sanitizeTextForTts(synthText);

    if (sanitizedSynthText.length > 200) {
      // POST запрос для фраз длиннее 200 символов
      const postUrl = `${activeBaseUrl}/api/v1/voice/tts`;
      const response = await fetch(postUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(deviceId ? { 'X-Device-ID': deviceId } : {}),
        },
        body: JSON.stringify({
          text: sanitizedSynthText,
          lang,
          bilingual,
          grade: effectiveGrade,
          tier: effectiveTier,
          is_speech_text: effectiveIsSpeech,
        }),
      });

      if (!response.ok) {
        throw new Error(`TTS POST returned HTTP ${response.status}`);
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

      if (thisToken !== currentPlayToken) {
        return null;
      }

      const cacheDir = `${FileSystem.cacheDirectory || ''}tarkapp_audio/`;
      await ensureAudioCacheDir(cacheDir);

      const hashStr = getFileHash(sanitizedSynthText);
      const localFilePath = `${cacheDir}${lang}_${bilingual ? 'bi' : 'mono'}_g${effectiveGrade || 1}_${effectiveTier || 'pri'}_${hashStr}.mp3`;
      await FileSystem.writeAsStringAsync(localFilePath, base64Data, {
        encoding: FileSystem.EncodingType.Base64,
      });
      effectiveUri = localFilePath;
    } else {
      const bilingualParam = bilingual ? '&bilingual=true' : '';
      const deviceParam = deviceId ? `&device_id=${encodeURIComponent(deviceId)}` : '';
      const gradeParam = effectiveGrade ? `&grade=${effectiveGrade}` : '';
      const tierParam = effectiveTier ? `&tier=${encodeURIComponent(effectiveTier)}` : '';
      const speechParam = effectiveIsSpeech ? '&is_speech_text=true' : '';
      effectiveUri = `${activeBaseUrl}/api/v1/voice/tts?text=${encodeURIComponent(sanitizedSynthText)}&lang=${lang}${bilingualParam}${deviceParam}${gradeParam}${tierParam}${speechParam}`;
    }
  }

  const source = effectiveUri.startsWith('file://')
    ? effectiveUri
    : {
        uri: effectiveUri,
        headers: deviceId ? { 'X-Device-ID': deviceId } : undefined,
      };

  try {
    if (thisToken !== currentPlayToken) {
      return null;
    }

    currentPlayingId = playbackId;
    currentCallbacks = callbacks || null;

    const player = createAudioPlayer(source);

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

    let hasStartedPlaying = false;

    activeSubscription = player.addListener('playbackStatusUpdate', (status: AudioStatus) => {
      if (thisToken !== currentPlayToken) return;

      if (status.playing) {
        hasStartedPlaying = true;
        if (playbackState !== 'playing' && !internalActionInProgress) {
          playbackState = 'playing';
          notifyStateListeners();
          currentCallbacks?.onResume?.();
        }
        return;
      }

      if (status.didJustFinish) {
        stopTts();
        return;
      }

      // External OS audio interruption (e.g. incoming call, headphones unplugged, audio focus lost):
      // Synchronize UI state back to paused (ready-to-resume) so button never freezes in playing state.
      if (
        hasStartedPlaying &&
        !status.playing &&
        !status.isBuffering &&
        playbackState === 'playing' &&
        !internalActionInProgress
      ) {
        playbackState = 'paused';
        notifyStateListeners();
        currentCallbacks?.onPause?.();
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
