import test from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.resolve(__dirname, '..');

test('P3-1: ANALYZE_TIMEOUT_MS is set to 25 seconds (25000ms) with AbortController', () => {
  const apiPath = path.join(rootDir, 'src', 'services', 'api.ts');
  const content = fs.readFileSync(apiPath, 'utf8');

  assert.match(
    content,
    /export\s+const\s+ANALYZE_TIMEOUT_MS\s*=\s*25000;/,
    'ANALYZE_TIMEOUT_MS must be 25000'
  );
  assert.match(
    content,
    /activeAnalyzeController/,
    'api.ts must manage activeAnalyzeController for duplicate cancellation'
  );
  assert.match(
    content,
    /cancelActiveAnalyze/,
    'api.ts must export cancelActiveAnalyze'
  );
  assert.match(
    content,
    /Сервер долго обрабатывает страницу\. Проверьте интернет и попробуйте еще раз/,
    'api.ts must provide friendly message on timeout'
  );
});

test('P2-3: AudioQueueManager stopAndClear releases sound resources and wipes queue on background transition', () => {
  const qManagerPath = path.join(rootDir, 'src', 'services', 'audioQueueManager.ts');
  const content = fs.readFileSync(qManagerPath, 'utf8');

  assert.match(
    content,
    /AppState\.addEventListener\('change'/,
    'audioQueueManager.ts must register AppState change listener'
  );
  assert.match(
    content,
    /stopAndClear/,
    'audioQueueManager.ts must implement stopAndClear method'
  );

  const playerPath = path.join(rootDir, 'src', 'services', 'audioPlayer.ts');
  const playerContent = fs.readFileSync(playerPath, 'utf8');

  assert.match(
    playerContent,
    /unloadAsync/,
    'audioPlayer.ts stopTts must invoke unloadAsync when available'
  );
});

test('P2-3: App.tsx cleans up hardware BackHandler, AppState listeners, timers, and aborts pending requests on unmount', () => {
  const appPath = path.join(rootDir, 'App.tsx');
  const content = fs.readFileSync(appPath, 'utf8');

  assert.match(
    content,
    /BackHandler\.addEventListener\('hardwareBackPress'/,
    'App.tsx must register Android hardware back listener'
  );
  assert.match(
    content,
    /backSub\.remove\(\)/,
    'App.tsx must clean up BackHandler listener on unmount'
  );
  assert.match(
    content,
    /appStateSub\.remove\(\)/,
    'App.tsx must clean up AppState listener on unmount'
  );
  assert.match(
    content,
    /isMountedRef\.current\s*=\s*false/,
    'App.tsx must set isMountedRef to false on unmount'
  );
  assert.match(
    content,
    /AudioQueueManager\.stopAndClear\(\)/,
    'App.tsx must call stopAndClear on background transition or unmount'
  );
  assert.match(
    content,
    /cancelActiveAnalyze\(\)/,
    'App.tsx must cancel active analyze requests on unmount'
  );
});

test('P2-4: LessonCard component provides React.memo StepCard and virtualized FlatList for large step lists (>6 steps)', () => {
  const lessonCardPath = path.join(rootDir, 'src', 'components', 'LessonCard.tsx');
  assert.ok(fs.existsSync(lessonCardPath), 'LessonCard.tsx must exist');

  const content = fs.readFileSync(lessonCardPath, 'utf8');

  assert.match(
    content,
    /React\.memo<StepCardProps>/,
    'StepCard must be wrapped in React.memo'
  );
  assert.match(
    content,
    /areStepPropsEqual/,
    'StepCard must use custom comparison function'
  );
  assert.match(
    content,
    /<FlatList/,
    'LessonStepList must render FlatList for large step counts'
  );
  assert.match(
    content,
    /getItemLayout=/,
    'FlatList must specify getItemLayout for high-performance layout computation'
  );
  assert.match(
    content,
    /keyExtractor=/,
    'FlatList must specify keyExtractor'
  );
  assert.match(
    content,
    /cleanSteps\.length\s*>\s*6/,
    'LessonStepList must virtualize when steps.length > 6'
  );
});
