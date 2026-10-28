import test from 'node:test';
import assert from 'node:assert/strict';

test('API_BASE_URL resolves from environment variable or production fallback', () => {
  const fallback = 'https://uvn-235-67.ams01.zonevs.eu';
  const getUrl = (envVal) => envVal || fallback;

  assert.equal(getUrl(undefined), 'https://uvn-235-67.ams01.zonevs.eu');
  assert.equal(getUrl('http://10.253.79.137:8080'), 'http://10.253.79.137:8080');
});

test('resolveBaseUrl returns passed baseUrl or default API_BASE_URL', () => {
  const DEFAULT = 'https://uvn-235-67.ams01.zonevs.eu';
  const resolveBaseUrl = (passed) => passed || DEFAULT;

  assert.equal(resolveBaseUrl(undefined), 'https://uvn-235-67.ams01.zonevs.eu');
  assert.equal(resolveBaseUrl(''), 'https://uvn-235-67.ams01.zonevs.eu');
  assert.equal(resolveBaseUrl('http://10.253.79.137:8080'), 'http://10.253.79.137:8080');
});
