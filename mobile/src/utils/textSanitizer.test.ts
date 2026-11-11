import { sanitizeTextForTts } from './textSanitizer';

interface TestCase {
  input: string;
  expected: string;
  description: string;
}

const testCases: TestCase[] = [
  {
    description: 'Lowercase solid compound: суперпрыжки',
    input: 'суперпрыжки',
    expected: 'супер-прыжки',
  },
  {
    description: 'Capitalized solid compound: Суперпрыжки',
    input: 'Суперпрыжки',
    expected: 'Супер-прыжки',
  },
  {
    description: 'UPPERCASE solid compound: СУПЕРПРЫЖКИ',
    input: 'СУПЕРПРЫЖКИ',
    expected: 'СУПЕР-ПРЫЖКИ',
  },
  {
    description: 'Already hyphenated: супер-прыжки (should not add second hyphen)',
    input: 'супер-прыжки',
    expected: 'супер-прыжки',
  },
  {
    description: 'Already hyphenated with capital: Супер-прыжок',
    input: 'Супер-прыжок',
    expected: 'Супер-прыжок',
  },
  {
    description: 'Compound with мега: мегамозг',
    input: 'мегамозг',
    expected: 'мега-мозг',
  },
  {
    description: 'Compound with ультра: ультразвук',
    input: 'ультразвук',
    expected: 'ультра-звук',
  },
  {
    description: 'Compound with экстра: экстракласс',
    input: 'экстракласс',
    expected: 'экстра-класс',
  },
  {
    description: 'Compound with квази: квазичастица',
    input: 'квазичастица',
    expected: 'квази-частица',
  },
  {
    description: 'Standalone word: обычный супер и все',
    input: 'обычный супер и все',
    expected: 'обычный супер и все',
  },
  {
    description: 'Full sentence from TarkApp lesson prompt',
    input: 'Привет, исследователь Дан! Посмотри, как стопа пружинит и делает суперпрыжки!',
    expected: 'Привет, исследователь Дан! Посмотри, как стопа пружинит и делает супер-прыжки!',
  },
  {
    description: 'Already hyphenated prefix with non-prefix word: не-суперпрыжки',
    input: 'не-суперпрыжки',
    expected: 'не-суперпрыжки',
  },
  {
    description: 'Empty string / whitespace',
    input: '   ',
    expected: '   ',
  },
];

export function runTests(): boolean {
  console.log('--- Running textSanitizer Test Suite ---');
  let passedCount = 0;
  for (const tc of testCases) {
    const result = sanitizeTextForTts(tc.input);
    const passed = result === tc.expected;
    if (passed) {
      console.log(`[PASS] ${tc.description}: "${tc.input}" => "${result}"`);
      passedCount++;
    } else {
      console.error(`[FAIL] ${tc.description}: expected "${tc.expected}", got "${result}"`);
    }
  }

  const allPassed = passedCount === testCases.length;
  console.log(`--- Test Suite Finished: ${passedCount}/${testCases.length} Passed (All OK: ${allPassed}) ---`);
  return allPassed;
}

