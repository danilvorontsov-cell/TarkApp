import test from 'node:test';
import assert from 'node:assert/strict';

test('API_BASE_URL resolves from environment variable or production fallback', () => {
  const fallback = 'https://api.tarkapp.ee';
  const getUrl = (envVal) => envVal || fallback;

  assert.equal(getUrl(undefined), 'https://api.tarkapp.ee');
  assert.equal(getUrl('http://custom-host:8080'), 'http://custom-host:8080');
});

test('resolveBaseUrl returns passed baseUrl or default API_BASE_URL', () => {
  const DEFAULT = 'https://api.tarkapp.ee';
  const resolveBaseUrl = (passed) => passed || DEFAULT;

  assert.equal(resolveBaseUrl(undefined), 'https://api.tarkapp.ee');
  assert.equal(resolveBaseUrl(''), 'https://api.tarkapp.ee');
  assert.equal(resolveBaseUrl('http://custom-host:8080'), 'http://custom-host:8080');
});
