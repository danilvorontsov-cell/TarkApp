import test from 'node:test';
import assert from 'node:assert/strict';

function normalizeApiUrl(rawUrl) {
  let url = (rawUrl || '').trim();
  while (url.endsWith('/')) {
    url = url.slice(0, -1);
  }
  return url;
}

test('normalizeApiUrl trims whitespace and trailing slashes', () => {
  assert.equal(normalizeApiUrl('http://10.253.79.137:8080/'), 'http://10.253.79.137:8080');
  assert.equal(normalizeApiUrl('  https://test.trycloudflare.com///  '), 'https://test.trycloudflare.com');
  assert.equal(normalizeApiUrl('http://192.168.1.50:8000'), 'http://192.168.1.50:8000');
});

test('resolveBaseUrl defaults to sync URL when default is passed', () => {
  const DEFAULT = 'http://10.253.79.137:8080';
  let inMemory = DEFAULT;

  function resolveBaseUrl(passed) {
    if (passed && passed !== DEFAULT) {
      return passed;
    }
    return inMemory;
  }

  // Without custom URL:
  assert.equal(resolveBaseUrl(DEFAULT), 'http://10.253.79.137:8080');

  // When user updates custom URL in app settings:
  inMemory = 'https://custom-tunnel.trycloudflare.com';
  assert.equal(resolveBaseUrl(DEFAULT), 'https://custom-tunnel.trycloudflare.com');
  assert.equal(resolveBaseUrl(undefined), 'https://custom-tunnel.trycloudflare.com');

  // Explicit override:
  assert.equal(resolveBaseUrl('http://other-host:9000'), 'http://other-host:9000');
});
