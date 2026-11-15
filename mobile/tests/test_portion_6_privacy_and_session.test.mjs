import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.resolve(__dirname, '..');

test('Portion 6: sentry.ts sets sendDefaultPii: false and tracesSampleRate: __DEV__ ? 1.0 : 0.2', () => {
  const sentryPath = path.join(rootDir, 'src', 'services', 'sentry.ts');
  assert.ok(fs.existsSync(sentryPath), 'sentry.ts must exist');

  const content = fs.readFileSync(sentryPath, 'utf8');

  assert.match(
    content,
    /sendDefaultPii:\s*false/,
    'Sentry.init must configure sendDefaultPii: false'
  );

  assert.match(
    content,
    /tracesSampleRate:\s*(?:isDev|__DEV__|typeof\s*__DEV__\s*!==\s*['"]undefined['"]\s*&&\s*__DEV__)\s*\?\s*1\.0\s*:\s*0\.2/,
    'Sentry.init must set tracesSampleRate to 1.0 in dev and 0.2 in production'
  );

  assert.match(
    content,
    /beforeBreadcrumb\s*\(\s*breadcrumb\s*\)/,
    'Sentry.init must include beforeBreadcrumb hook'
  );

  assert.match(
    content,
    /beforeSend\s*\(\s*event\s*\)/,
    'Sentry.init must include beforeSend hook'
  );
});

test('Portion 6: sentry.ts defines maskSensitiveUrl and sanitizeHeaders', () => {
  const sentryPath = path.join(rootDir, 'src', 'services', 'sentry.ts');
  const content = fs.readFileSync(sentryPath, 'utf8');

  assert.match(
    content,
    /export\s+function\s+maskSensitiveUrl/,
    'sentry.ts must export maskSensitiveUrl'
  );

  assert.match(
    content,
    /export\s+function\s+sanitizeHeaders/,
    'sentry.ts must export sanitizeHeaders'
  );

  assert.match(
    content,
    /authorization/i,
    'sanitizeHeaders must check for authorization header'
  );

  assert.match(
    content,
    /x-device-id/i,
    'sanitizeHeaders must check for x-device-id header'
  );

  assert.match(
    content,
    /text|speech_text|device_id/i,
    'maskSensitiveUrl must mask text, speech_text and device_id query params'
  );
});

test('Portion 6: storage.ts deleteAccountAndData calls clearAuthToken()', () => {
  const storagePath = path.join(rootDir, 'src', 'services', 'storage.ts');
  assert.ok(fs.existsSync(storagePath), 'storage.ts must exist');

  const content = fs.readFileSync(storagePath, 'utf8');

  assert.match(
    content,
    /import\s*\{[^}]*clearAuthToken[^}]*\}\s*from\s*['"]\.\/api['"]/,
    'storage.ts must import clearAuthToken from ./api'
  );

  assert.match(
    content,
    /async\s+deleteAccountAndData\s*\(\s*\)[\s\S]*?clearAuthToken\(\)/,
    'deleteAccountAndData must invoke clearAuthToken()'
  );

  assert.match(
    content,
    /async\s+clearAuthToken\s*\(\s*\)/,
    'StorageService must provide a clearAuthToken method'
  );
});

test('Portion 6: api.ts exports clearAuthToken() and clears cached auth token', () => {
  const apiPath = path.join(rootDir, 'src', 'services', 'api.ts');
  const content = fs.readFileSync(apiPath, 'utf8');

  assert.match(
    content,
    /export\s+function\s+clearAuthToken\s*\(\s*\)/,
    'api.ts must export clearAuthToken()'
  );
});
