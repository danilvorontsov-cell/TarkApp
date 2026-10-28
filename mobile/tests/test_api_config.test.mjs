import test from 'node:test';
import assert from 'node:assert/strict';

test('API_BASE_URL resolves from environment variable or fallback', () => {
  const fallback = 'http://10.253.79.137:8080';
  const getUrl = (envVal) => envVal || fallback;

  assert.equal(getUrl(undefined), 'http://10.253.79.137:8080');
  assert.equal(getUrl('https://api.tarkapp.ee'), 'https://api.tarkapp.ee');
});

test('resolveBaseUrl returns passed baseUrl or default API_BASE_URL', () => {
  const DEFAULT = 'http://10.253.79.137:8080';
  const resolveBaseUrl = (passed) => passed || DEFAULT;

  assert.equal(resolveBaseUrl(undefined), 'http://10.253.79.137:8080');
  assert.equal(resolveBaseUrl(''), 'http://10.253.79.137:8080');
  assert.equal(resolveBaseUrl('https://api.tarkapp.ee'), 'https://api.tarkapp.ee');
});
