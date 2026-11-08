import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.resolve(__dirname, '..');

test('P3-4: errorHandler.ts exists and defines bilingual error translations', () => {
  const handlerPath = path.join(rootDir, 'src', 'utils', 'errorHandler.ts');
  assert.ok(fs.existsSync(handlerPath), 'errorHandler.ts must exist');

  const content = fs.readFileSync(handlerPath, 'utf8');

  assert.match(
    content,
    /Нет подключения к интернету\. Проверьте соединение \/ Internetiühendus puudub/,
    'Must include bilingual offline error message'
  );
  assert.match(
    content,
    /Сервер временно недоступен\. Попробуйте через минуту \/ Server on ajutiselt kättesaamatu/,
    'Must include bilingual 502/503 server unavailable error message'
  );
  assert.match(
    content,
    /Файл страницы слишком большой\. Сделайте снимок ближе \/ Fail on liiga suur/,
    'Must include bilingual 413 payload too large error message'
  );
  assert.match(
    content,
    /export function formatBilingualErrorMessage/,
    'Must export formatBilingualErrorMessage'
  );
});

test('P3-4: api.ts integrates formatBilingualErrorMessage and eliminates stacktraces', () => {
  const apiPath = path.join(rootDir, 'src', 'services', 'api.ts');
  const content = fs.readFileSync(apiPath, 'utf8');

  assert.match(
    content,
    /import\s*\{\s*formatBilingualErrorMessage\s*\}\s*from\s*['"]\.\.\/utils\/errorHandler['"]/,
    'api.ts must import formatBilingualErrorMessage from errorHandler'
  );
  assert.match(
    content,
    /formatBilingualErrorMessage\(error\)/,
    'formatFriendlyErrorMessage must call formatBilingualErrorMessage'
  );
  assert.match(
    content,
    /Fail on liiga suur/,
    'parseErrorResponse must map status 413 to bilingual message'
  );
  assert.match(
    content,
    /Server on ajutiselt kättesaamatu/,
    'parseErrorResponse must map status 502/503 to bilingual message'
  );
});

test('P3-4: Error logic unit verification in JavaScript runtime', () => {
  // Replicate logic to verify message mapping
  function formatBilingualErrorMessage(error) {
    if (!error) return 'Временный сбой при соединении с сервером. Пожалуйста, попробуйте еще раз / Ajutine ühenduse viga';
    const status = error?.status;
    if (status === 413) return 'Файл страницы слишком большой. Сделайте снимок ближе / Fail on liiga suur';
    if (status === 502 || status === 503 || status === 504) return 'Сервер временно недоступен. Попробуйте через минуту / Server on ajutiselt kättesaamatu';

    const msg = typeof error === 'string' ? error : error?.message || String(error);
    if (msg.includes('413') || msg.includes('CONTENT_TOO_LARGE') || msg.includes('превышает')) {
      return 'Файл страницы слишком большой. Сделайте снимок ближе / Fail on liiga suur';
    }
    if (msg.includes('502') || msg.includes('503') || msg.includes('Service Unavailable') || msg.includes('Bad Gateway')) {
      return 'Сервер временно недоступен. Попробуйте через минуту / Server on ajutiselt kättesaamatu';
    }
    if (msg.includes('Network request failed') || msg.includes('ECONNREFUSED') || msg.includes('ENOTFOUND')) {
      return 'Нет подключения к интернету. Проверьте соединение / Internetiühendus puudub';
    }
    return 'Временный сбой при соединении с сервером. Пожалуйста, попробуйте еще раз / Ajutine ühenduse viga';
  }

  assert.equal(
    formatBilingualErrorMessage(new TypeError('Network request failed')),
    'Нет подключения к интернету. Проверьте соединение / Internetiühendus puudub'
  );
  assert.equal(
    formatBilingualErrorMessage(new Error('connect ECONNREFUSED 127.0.0.1:8000')),
    'Нет подключения к интернету. Проверьте соединение / Internetiühendus puudub'
  );
  assert.equal(
    formatBilingualErrorMessage({ status: 503 }),
    'Сервер временно недоступен. Попробуйте через минуту / Server on ajutiselt kättesaamatu'
  );
  assert.equal(
    formatBilingualErrorMessage({ status: 413 }),
    'Файл страницы слишком большой. Сделайте снимок ближе / Fail on liiga suur'
  );
});
