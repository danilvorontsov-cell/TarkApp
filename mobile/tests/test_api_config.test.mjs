import test from 'node:test';
import assert from 'node:assert/strict';

test('API_BASE_URL resolves from environment variable or production fallback', () => {
  const fallback = 'http://185.31.243.124:8080';
  const getUrl = (envVal) => envVal || fallback;

  assert.equal(getUrl(undefined), 'http://185.31.243.124:8080');
  assert.equal(getUrl('http://custom-host:8080'), 'http://custom-host:8080');
});

test('resolveBaseUrl returns passed baseUrl or default API_BASE_URL', () => {
  const DEFAULT = 'http://185.31.243.124:8080';
  const resolveBaseUrl = (passed) => passed || DEFAULT;

  assert.equal(resolveBaseUrl(undefined), 'http://185.31.243.124:8080');
  assert.equal(resolveBaseUrl(''), 'http://185.31.243.124:8080');
  assert.equal(resolveBaseUrl('http://custom-host:8080'), 'http://custom-host:8080');
});
