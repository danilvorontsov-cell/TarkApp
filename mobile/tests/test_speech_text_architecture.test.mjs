import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';

import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const mobileDir = path.resolve(__dirname, '..');

test('Scenario 1: AUDIO_CACHE_VERSION is bumped to 2 for cache invalidation', () => {
  const aqmPath = path.join(mobileDir, 'src', 'services', 'audioQueueManager.ts');
  const apPath = path.join(mobileDir, 'src', 'services', 'audioPlayer.ts');

  const aqmContent = fs.readFileSync(aqmPath, 'utf8');
  const apContent = fs.readFileSync(apPath, 'utf8');

  assert.match(
    aqmContent,
    /export\s+const\s+AUDIO_CACHE_VERSION\s*=\s*2;/,
    'AudioQueueManager must export AUDIO_CACHE_VERSION = 2'
  );
  assert.match(
    apContent,
    /export\s+const\s+AUDIO_CACHE_VERSION\s*=\s*2;/,
    'AudioPlayer must export AUDIO_CACHE_VERSION = 2'
  );
  assert.match(
    aqmContent,
    /storedVersion\s*<\s*AUDIO_CACHE_VERSION/,
    'AudioQueueManager must check stored cache version against AUDIO_CACHE_VERSION'
  );
  assert.match(
    aqmContent,
    /@tarkapp_audio_cache_version/,
    'AudioQueueManager must use @tarkapp_audio_cache_version key'
  );
});

test('Scenario 2: AudioQueueItem and AudioQueueManager route speech_text', () => {
  const aqmPath = path.join(mobileDir, 'src', 'services', 'audioQueueManager.ts');
  const aqmContent = fs.readFileSync(aqmPath, 'utf8');

  assert.match(
    aqmContent,
    /speech_text\?:/i,
    'AudioQueueItem must include optional speech_text field'
  );
  assert.match(
    aqmContent,
    /is_speech_text:/i,
    'downloadItem must send is_speech_text flag in request body'
  );
  assert.match(
    aqmContent,
    /is_speech_text=true/i,
    'downloadItem must pass is_speech_text query parameter on GET'
  );
});

test('Scenario 3: AudioPlayer playTts supports speechText and isSpeechText parameters', () => {
  const apPath = path.join(mobileDir, 'src', 'services', 'audioPlayer.ts');
  const apContent = fs.readFileSync(apPath, 'utf8');

  assert.match(
    apContent,
    /speechText\?:/i,
    'playTts must accept speechText parameter'
  );
  assert.match(
    apContent,
    /isSpeechText\?:/i,
    'playTts must accept isSpeechText parameter'
  );
  assert.match(
    apContent,
    /is_speech_text:\s*effectiveIsSpeech/i,
    'playTts must pass is_speech_text in POST body'
  );
});

test('Scenario 4: LessonCard step list strictly prunes empty and whitespace steps', () => {
  const lcPath = path.join(mobileDir, 'src', 'components', 'LessonCard.tsx');
  const lcContent = fs.readFileSync(lcPath, 'utf8');

  assert.match(
    lcContent,
    /validSteps\s*=\s*\(steps\s*\|\|\s*\[\]\)\.filter/,
    'LessonStepList must filter steps for non-empty text'
  );
  assert.match(
    lcContent,
    /step\.trim\(\)\.length\s*>\s*0/,
    'LessonStepList must filter string steps with trim().length > 0'
  );
  assert.match(
    lcContent,
    /speechText\?:/i,
    'StepCardProps must accept speechText'
  );
});

test('Scenario 5: App.tsx handles empty steps and passes speech_text to audio', () => {
  const appPath = path.join(mobileDir, 'App.tsx');
  const appContent = fs.readFileSync(appPath, 'utf8');

  assert.match(
    appContent,
    /handlePlayAudio\s*=\s*useCallback\s*\(\s*async\s*\([^)]*speech_text\?:/s,
    'handlePlayAudio must accept optional speech_text argument'
  );
  assert.match(
    appContent,
    /cleanEstTags\(step\)\.replace\(\/\^\\d\+\[\\\.\\\)\]\\s\*\//,
    'App.tsx worked_example steps formatting cleans ordinal prefixes'
  );
});

test('Scenario 6: Cache key differentiation by grade and tier, and vocabulary speech_text passing', () => {
  const aqmPath = path.join(mobileDir, 'src', 'services', 'audioQueueManager.ts');
  const aqmContent = fs.readFileSync(aqmPath, 'utf8');

  assert.match(
    aqmContent,
    /_g\$\{gKey\}_/,
    'getFilePath must incorporate grade in filename'
  );
  assert.match(
    aqmContent,
    /\$\{tKey\}_/,
    'getFilePath must incorporate tier in filename'
  );

  const appPath = path.join(mobileDir, 'App.tsx');
  const appContent = fs.readFileSync(appPath, 'utf8');

  assert.match(
    appContent,
    /handlePlayAudio\(cleanEstTags\(v\.est\),\s*'et',\s*`vocab_\$\{idx\}`, false,\s*cleanEstTags\(v\.est\)\)/,
    'App.tsx passes cleanEstTags as speech_text for v.est'
  );
  assert.match(
    appContent,
    /handlePlayAudio\(cleanEstTags\(v\.example\),\s*'et',\s*`vocab_ex_\$\{idx\}`, false,\s*cleanEstTags\(v\.example\)\)/,
    'App.tsx passes cleanEstTags as speech_text for v.example'
  );
});

test('Scenario 7: Dark theme step card styling and copy button suppression in Näidis', () => {
  const lcPath = path.join(mobileDir, 'src', 'components', 'LessonCard.tsx');
  const lcContent = fs.readFileSync(lcPath, 'utf8');

  // Verify dark theme styling for step rows and text
  assert.match(
    lcContent,
    /stepRow:\s*\{[^}]*backgroundColor:\s*['"]rgba\(255,\s*255,\s*255,\s*0\.05\)['"]/s,
    'stepRow must use dark transparent background'
  );
  assert.match(
    lcContent,
    /stepText:\s*\{[^}]*color:\s*['"]#F1F5F9['"]/s,
    'stepText must use light slate text #F1F5F9'
  );

  // Verify showCopy prop support
  assert.match(
    lcContent,
    /showCopy\?:/i,
    'StepCardProps must accept showCopy prop'
  );
  assert.match(
    lcContent,
    /canCopy\s*=\s*Boolean\(showCopy\s*&&\s*onCopyFormula\s*&&\s*isMath\)/,
    'StepCard only renders copy button when showCopy is true and onCopyFormula is provided'
  );

  // Verify App.tsx explicitly disables copy button in Näidis
  const appPath = path.join(mobileDir, 'App.tsx');
  const appContent = fs.readFileSync(appPath, 'utf8');

  assert.match(
    appContent,
    /audioPrefix="we_step"[\s\S]*?showCopy=\{false\}/,
    'App.tsx disables copy button in WorkedExample / Näidis'
  );
});
