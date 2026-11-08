/**
 * Bilingual Error Handler (RU / ET)
 * Maps system exceptions, network failures, and HTTP status codes
 * to user-friendly bilingual messages without technical stacktraces.
 */

export const ERROR_MESSAGES = {
  NO_NETWORK: 'Нет подключения к интернету. Проверьте соединение / Internetiühendus puudub',
  SERVER_UNAVAILABLE: 'Сервер временно недоступен. Попробуйте через минуту / Server on ajutiselt kättesaamatu',
  FILE_TOO_LARGE: 'Файл страницы слишком большой. Сделайте снимок ближе / Fail on liiga suur',
  TIMEOUT: 'Сервер долго обрабатывает страницу. Проверьте интернет и попробуйте еще раз',
  SERVER_ERROR: 'Временный сбой при обработке задания. Попробуйте еще раз / Ajutine tõrge ülesande töötlemisel',
  GENERIC_ERROR: 'Временный сбой при соединении с сервером. Пожалуйста, попробуйте еще раз / Ajutine ühenduse viga',
} as const;

export function formatBilingualErrorMessage(error: unknown): string {
  if (!error) {
    return ERROR_MESSAGES.GENERIC_ERROR;
  }

  // If error is an object with status code
  const status = (error as any)?.status;
  if (status === 413) {
    return ERROR_MESSAGES.FILE_TOO_LARGE;
  }
  if (status === 502 || status === 503 || status === 504) {
    return ERROR_MESSAGES.SERVER_UNAVAILABLE;
  }

  const rawMsg =
    typeof error === 'string'
      ? error
      : (error as any)?.message || (error as any)?.detail || String(error);
  const msg = String(rawMsg);

  // Eliminate any technical backend env or mail server parameters from user view
  if (
    msg.includes('SMTP') ||
    msg.includes('RESEND') ||
    msg.includes('Resend') ||
    msg.includes('.env') ||
    msg.includes('SMTP_HOST') ||
    msg.includes('SMTP_USER')
  ) {
    return 'Счёт готов к оплате. Используйте реквизиты IBAN и Viitenumber ниже.';
  }

  // 1. Payload too large (413)
  if (
    msg.includes('413') ||
    msg.includes('CONTENT_TOO_LARGE') ||
    msg.includes('REQUEST_ENTITY_TOO_LARGE') ||
    msg.includes('превышает допустимый лимит') ||
    msg.includes('слишком большой') ||
    msg.includes('Fail on liiga suur')
  ) {
    return ERROR_MESSAGES.FILE_TOO_LARGE;
  }

  // 2. Server temporarily unavailable (502, 503, 504)
  if (
    msg.includes('502') ||
    msg.includes('503') ||
    msg.includes('504') ||
    msg.includes('Service Unavailable') ||
    msg.includes('Bad Gateway') ||
    msg.includes('Gateway Timeout') ||
    msg.includes('Server on ajutiselt kättesaamatu')
  ) {
    return ERROR_MESSAGES.SERVER_UNAVAILABLE;
  }

  // 3. Network connection / DNS / Offline / Socket issues
  if (
    msg.includes('Network request failed') ||
    msg.includes('NetworkError') ||
    msg.includes('ECONNREFUSED') ||
    msg.includes('ENOTFOUND') ||
    msg.includes('EHOSTUNREACH') ||
    msg.includes('Failed to connect') ||
    msg.includes('ConnectException') ||
    msg.includes('UnknownHostException') ||
    msg.includes('Unable to resolve host') ||
    msg.includes('SSLHandshakeException') ||
    msg.includes('CertPathValidatorException') ||
    msg.includes('CLEARTEXT') ||
    msg.includes('Cleartext') ||
    msg.includes('cleartext') ||
    msg.includes('TypeError: Network request failed') ||
    msg.includes('Internetiühendus puudub')
  ) {
    return ERROR_MESSAGES.NO_NETWORK;
  }

  // 4. Timeout issues
  if (
    msg.includes('долго обрабатывает') ||
    msg.includes('timeout') ||
    msg.includes('Timeout') ||
    msg.includes('AbortError') ||
    msg.includes('aborted')
  ) {
    return ERROR_MESSAGES.TIMEOUT;
  }

  // 5. 500 Internal Server Error
  if (msg.includes('500') || msg.includes('INTERNAL_SERVER_ERROR')) {
    return ERROR_MESSAGES.SERVER_ERROR;
  }

  // If already clean user-facing text without tech traces, preserve it
  const hasCyrillic = /[а-яёА-ЯЁ]/.test(msg);
  if (
    hasCyrillic &&
    !msg.includes('java.') &&
    !msg.includes('at ') &&
    !msg.includes('TypeError') &&
    !msg.includes('Error:')
  ) {
    return msg;
  }

  return ERROR_MESSAGES.GENERIC_ERROR;
}
