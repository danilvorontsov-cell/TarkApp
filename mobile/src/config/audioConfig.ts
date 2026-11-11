/**
 * Audio TTS Configuration for TarkApp.
 * Routes audio through backend TTS pipeline (Silero v5 for Russian + Microsoft Neural for Estonian).
 */

export type TTSProvider = 'silero' | 'backend';

/**
 * Active TTS Provider.
 * All audio synthesis routes through TarkApp backend (Silero v5 + Microsoft ET).
 */
export const ACTIVE_TTS_PROVIDER: TTSProvider = 'silero';
