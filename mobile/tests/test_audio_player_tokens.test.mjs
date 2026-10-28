import test from 'node:test';
import assert from 'node:assert/strict';

/**
 * Unit tests for audioPlayer token concurrency and PhraseBuilder Estonian TTS normalization.
 * Mirrors the exact token and lifecycle state machine in mobile/src/services/audioPlayer.ts
 * and normalizeTextForTTS in mobile/src/components/PhraseBuilder.tsx.
 */
function createTestableAudioPlayerController() {
  let activePlayer = null;
  let currentPlayingId = null;
  let playbackState = 'idle';
  let currentCallbacks = null;
  let currentPlayToken = 0;
  const createdPlayers = [];

  async function stopTts(incrementToken = true) {
    if (incrementToken) {
      currentPlayToken++;
    }
    const prevCallbacks = currentCallbacks;
    currentCallbacks = null;
    currentPlayingId = null;
    playbackState = 'idle';

    if (activePlayer) {
      await Promise.resolve(); // Simulate async native pause/seek
      activePlayer.released = true;
      activePlayer = null;
    }
    prevCallbacks?.onFinish?.();
  }

  async function playTts(text, lang = 'et', playbackId = 'word', callbacks = {}) {
    const thisToken = ++currentPlayToken;

    // Must NOT invalidate thisToken during internal cleanup!
    await stopTts(false);

    if (thisToken !== currentPlayToken) {
      return null;
    }

    if (!text || !text.trim()) {
      return null;
    }

    // Simulate async ensureAudioMode()
    await Promise.resolve();

    if (thisToken !== currentPlayToken) {
      return null;
    }

    currentPlayingId = playbackId;
    currentCallbacks = callbacks;

    const player = {
      text,
      lang,
      playbackId,
      playing: false,
      released: false,
      play() {
        this.playing = true;
      },
      release() {
        this.released = true;
      },
    };
    createdPlayers.push(player);

    activePlayer = player;
    playbackState = 'playing';
    callbacks?.onStart?.();
    player.play();
    return player;
  }

  return {
    playTts,
    stopTts,
    getState: () => ({
      playbackState,
      currentPlayingId,
      currentPlayToken,
      activePlayer,
      createdPlayers,
    }),
  };
}

function normalizeTextForTTS(text) {
  if (!text) return '';
  let normalized = text;
  normalized = normalized.replace(/[\u00d7\u2715\u2716*]/g, ' ');
  normalized = normalized.replace(/[\[\]{}()]/g, ' ');
  normalized = normalized.replace(/_{2,}/g, ' ');
  normalized = normalized.replace(/(\b\d+)\s*\.(?!\d)/g, '$1 ');
  normalized = normalized.replace(/(\d+)([,!?;:])/g, '$1 $2');
  normalized = normalized.replace(/([,!?;:])(\d+)/g, '$1 $2');
  normalized = normalized.replace(/(\d+)[-–—]+(?=(?:ga|ni|st|le|lt|sse|s|l|ks|na|ta)\b)/gi, '$1-');
  normalized = normalized.replace(/(\d+)[-–—]+(?!(?:ga|ni|st|le|lt|sse|s|l|ks|na|ta)\b)/gi, '$1 ');
  normalized = normalized.replace(/[-–—]+(\d+)/g, ' $1');
  return normalized.replace(/\s+/g, ' ').trim();
}

test('AudioPlayer Scenario 1: Single playTts() call does not self-cancel on stopTts(false)', async () => {
  const controller = createTestableAudioPlayerController();
  let started = false;

  const player = await controller.playTts('liidetav', 'et', 'vocab_0', {
    onStart: () => {
      started = true;
    },
  });

  assert.notEqual(player, null, 'playTts must return a valid player instance, not null');
  assert.equal(started, true);
  assert.equal(player.playing, true);
  assert.equal(controller.getState().playbackState, 'playing');
  assert.equal(controller.getState().currentPlayingId, 'vocab_0');
  assert.equal(controller.getState().currentPlayToken, 1);
});

test('AudioPlayer Scenario 2: Rapid multi-clicks cancel earlier tokens and only play the last word', async () => {
  const controller = createTestableAudioPlayerController();

  // Fire 3 rapid clicks concurrently without awaiting each one first
  const [p1, p2, p3] = await Promise.all([
    controller.playTts('esimene', 'et', 'vocab_1'),
    controller.playTts('teine', 'et', 'vocab_2'),
    controller.playTts('kolmas', 'et', 'vocab_3'),
  ]);

  assert.equal(p1, null, 'First click must be superseded and return null');
  assert.equal(p2, null, 'Second click must be superseded and return null');
  assert.notEqual(p3, null, 'Third (latest) click must succeed');
  assert.equal(p3.text, 'kolmas');
  assert.equal(controller.getState().currentPlayingId, 'vocab_3');
  assert.equal(controller.getState().createdPlayers.length, 1);
});

test('AudioPlayer Scenario 3: Explicit stopTts() invalidates in-flight playTts() call', async () => {
  const controller = createTestableAudioPlayerController();

  const playPromise = controller.playTts('summa', 'et', 'vocab_summa');
  // Immediately call explicit stopTts() while playTts is awaiting cleanup
  await controller.stopTts(true);

  const player = await playPromise;
  assert.equal(player, null, 'In-flight playTts must abort when explicit stopTts() is called');
  assert.equal(controller.getState().playbackState, 'idle');
});

test('PhraseBuilder normalizeTextForTTS preserves hyphens in Estonian numeral case endings', () => {
  assert.equal(normalizeTextForTTS('Korruta [5-ga] ja loenda [10-ni]'), 'Korruta 5-ga ja loenda 10-ni');
  assert.equal(normalizeTextForTTS('Lahuta 3-st ning liida 2-le.'), 'Lahuta 3-st ning liida 2-le.');
  assert.equal(normalizeTextForTTS('Vastus on [12].'), 'Vastus on 12');
  assert.equal(normalizeTextForTTS('12-ne'), '12 ne');
});
