import test from 'node:test';
import assert from 'node:assert/strict';

function cleanEstTags(text) {
  if (!text) return '';
  return text.replace(/<\s*\/?\s*est(?:\s+[^>]*)?>/gi, '');
}

test('cleanEstTags removes <est> and </est> tags from strings', () => {
  const input = 'Клавиатура (<est>klaviatuur</est>) состоит из клавиш (<est>klahvid</est>).';
  const expected = 'Клавиатура (klaviatuur) состоит из клавиш (klahvid).';
  assert.equal(cleanEstTags(input), expected);
});

test('cleanEstTags handles uppercase or spaced tags', () => {
  const input = 'Игра в <EST>Minecrafti mäng</EST> и <est >sõna</est >.';
  const expected = 'Игра в Minecrafti mäng и sõna.';
  assert.equal(cleanEstTags(input), expected);
});

test('cleanEstTags handles text without tags', () => {
  const input = 'Minecraft и Roblox запускаются на компьютере.';
  assert.equal(cleanEstTags(input), input);
});

test('cleanEstTags handles empty or null input', () => {
  assert.equal(cleanEstTags(null), '');
  assert.equal(cleanEstTags(undefined), '');
  assert.equal(cleanEstTags(''), '');
});
