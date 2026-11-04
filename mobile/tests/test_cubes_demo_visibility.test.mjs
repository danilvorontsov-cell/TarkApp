import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

test('Scenario 1: SHOW_CUBES_DEMO feature flag exists and is defaulted to false', () => {
  const featuresContent = fs.readFileSync('mobile/src/config/features.ts', 'utf-8');
  assert.match(
    featuresContent,
    /export\s+const\s+SHOW_CUBES_DEMO\s*=\s*false;/,
    'SHOW_CUBES_DEMO flag must be exported and set to false'
  );
});

test('Scenario 2: DrawerMenu gates the cubes demo menu item behind SHOW_CUBES_DEMO / showCubesDemo', () => {
  const drawerContent = fs.readFileSync('mobile/src/components/DrawerMenu.tsx', 'utf-8');

  // Verify import
  assert.match(
    drawerContent,
    /import\s*\{\s*SHOW_CUBES_DEMO\s*\}\s*from\s*['"]\.\.\/config\/features['"]/,
    'DrawerMenu must import SHOW_CUBES_DEMO from features config'
  );

  // Verify conditional rendering check
  assert.match(
    drawerContent,
    /\{\s*showCubesDemo\s*&&\s*onOpenDemoLesson\s*\?/,
    'DrawerMenu must guard the demo item with showCubesDemo && onOpenDemoLesson'
  );

  // Verify demo text is preserved in code
  assert.match(drawerContent, /Пример:\s*Кубики\s*\(3\s*\+\s*2\)/);
});

test('Scenario 3: HomeScreen quick demo button is conditionally hidden by SHOW_CUBES_DEMO', () => {
  const appContent = fs.readFileSync('mobile/App.tsx', 'utf-8');

  // Verify import
  assert.match(
    appContent,
    /import\s*\{[^}]*SHOW_CUBES_DEMO[^}]*\}\s*from\s*['"]\.\/src\/config\/features['"]/,
    'App.tsx must import SHOW_CUBES_DEMO from features config'
  );

  // Verify HomeScreen card button is wrapped
  assert.match(
    appContent,
    /\{SHOW_CUBES_DEMO\s*&&\s*\(\s*<TouchableOpacity[^>]*quickDemoLessonButton[\s\S]*?✨ Открыть пример: Сложение и перестановка \(3 \+ 2 = 5\)[\s\S]*?<\/TouchableOpacity>\s*\)\}/,
    'HomeScreen quick demo preview button must be conditionally rendered with SHOW_CUBES_DEMO'
  );
});

test('Scenario 4: LessonScreen top control bar demo switch button is hidden by SHOW_CUBES_DEMO', () => {
  const appContent = fs.readFileSync('mobile/App.tsx', 'utf-8');

  // Verify top bar demo switch button is wrapped
  assert.match(
    appContent,
    /\{SHOW_CUBES_DEMO\s*&&\s*\(\s*<TouchableOpacity[^>]*analysisDemoSwitchBtn[\s\S]*?✨ Пример: 3 \+ 2 = 5[\s\S]*?<\/TouchableOpacity>\s*\)\}/,
    'LessonScreen demo switch button in analysisTopControlBar must be conditionally rendered with SHOW_CUBES_DEMO'
  );
});

test('Scenario 5: TaskVisualizer block under voice hint is conditionally hidden by SHOW_CUBES_DEMO', () => {
  const appContent = fs.readFileSync('mobile/App.tsx', 'utf-8');

  // Verify TaskVisualizer is conditionally rendered
  assert.match(
    appContent,
    /\{SHOW_CUBES_DEMO\s*&&\s*profile\.grade\s*<=\s*6\s*&&\s*Boolean\(analysis\.visual\)\s*&&\s*\(\s*<TaskVisualizer/,
    'TaskVisualizer under voice hint must be conditioned on SHOW_CUBES_DEMO'
  );
});

test('Scenario 6: TaskVisualizer component code and animation logic are preserved intact', () => {
  assert.ok(fs.existsSync('mobile/src/components/TaskVisualizer.tsx'), 'TaskVisualizer.tsx must exist');
  const visualizerContent = fs.readFileSync('mobile/src/components/TaskVisualizer.tsx', 'utf-8');

  // Verify core visualization elements and styles exist
  assert.match(visualizerContent, /export const TaskVisualizer/);
  assert.match(visualizerContent, /RenderAutoMathBlocks/);
  assert.match(visualizerContent, /glossyCube/);
  assert.match(visualizerContent, /cubesRow/);
  assert.match(visualizerContent, /flightArena/);
  assert.match(visualizerContent, /Переместительный закон сложения/);
});
