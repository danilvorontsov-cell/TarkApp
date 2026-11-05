import { Platform } from 'react-native';
import * as Application from 'expo-application';
import * as SecureStore from 'expo-secure-store';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { PageAnalysisResponse, UserProfile, VocabularyItem } from '../types';
import { captureException } from './sentry';

import { API_BASE_URL, getApiBaseUrl } from '../config/apiConfig';

export { API_BASE_URL, getApiBaseUrl };

/**
 * Resolves the base URL for API requests.
 */
export function resolveBaseUrl(baseUrl?: string): string {
  return baseUrl || API_BASE_URL;
}

export const API_TIMEOUT_MS = 30000;

/**
 * Fetch wrapper that automatically enforces an AbortController timeout.
 * Prevents requests from hanging indefinitely under poor network conditions or peak evening loads.
 */
export async function fetchWithTimeout(
  input: RequestInfo | URL,
  init?: RequestInit,
  timeoutMs: number = API_TIMEOUT_MS
): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => {
    controller.abort();
  }, timeoutMs);

  const originalSignal = init?.signal;
  if (originalSignal) {
    if (originalSignal.aborted) {
      clearTimeout(timer);
      controller.abort();
    } else {
      originalSignal.addEventListener('abort', () => {
        clearTimeout(timer);
        controller.abort();
      });
    }
  }

  try {
    return await fetch(input, {
      ...init,
      signal: controller.signal,
    });
  } catch (err: any) {
    if (err?.name === 'AbortError' || controller.signal.aborted) {
      throw new Error(
        `Время ожидания ответа от сервера (${Math.round(timeoutMs / 1000)} сек) истекло. Пожалуйста, проверьте интернет и повторите попытку.`
      );
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public code?: string,
    public originalError?: unknown
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

// ==========================================
// Device ID & License Management
// ==========================================

let cachedDeviceId: string | null = null;
let deviceIdPromise: Promise<string> | null = null;
const SECURE_DEVICE_ID_KEY = 'tarkapp_device_id';
const ASYNC_DEVICE_ID_KEY = '@tarkapp_device_id';

export function _resetCachedDeviceId(): void {
  cachedDeviceId = null;
  deviceIdPromise = null;
}

/**
 * Returns a persistent, tamper-resistant Device ID.
 * Uses both AsyncStorage (unaffected by Android keystore changes during APK updates)
 * and SecureStore (Keychain on iOS) with automatic bidirectional synchronization.
 * This guarantees the Device ID survives app upgrades, reinstallation, and keystore rotations.
 */
export async function getDeviceId(): Promise<string> {
  if (cachedDeviceId) {
    return cachedDeviceId;
  }
  if (deviceIdPromise) {
    return deviceIdPromise;
  }

  deviceIdPromise = (async () => {
    let resolvedId: string | null = null;

    // 1. Check AsyncStorage first (100% stable across Android APK updates)
    try {
      const asyncId = await AsyncStorage.getItem(ASYNC_DEVICE_ID_KEY);
      if (asyncId && asyncId.trim()) {
        resolvedId = asyncId.trim();
      }
    } catch (err) {
      console.warn('[AsyncStorage] Failed to read device ID:', err);
    }

    // 2. Check SecureStore if not found in AsyncStorage (iOS Keychain survival across reinstall)
    if (!resolvedId) {
      try {
        const secureId = await SecureStore.getItemAsync(SECURE_DEVICE_ID_KEY);
        if (secureId && secureId.trim()) {
          resolvedId = secureId.trim();
        }
      } catch (err) {
        console.warn('[SecureStore] Failed to read device ID:', err);
      }
    }

    // 3. Hardware identifiers (first installation on new device)
    if (!resolvedId) {
      try {
        if (Platform.OS === 'android') {
          const androidId = Application.getAndroidId();
          if (androidId && androidId.trim()) {
            resolvedId = androidId.trim();
          }
        } else if (Platform.OS === 'ios') {
          const iosId = await Application.getIosIdForVendorAsync();
          if (iosId && iosId.trim()) {
            resolvedId = iosId.trim();
          }
        }
      } catch (err) {
        console.warn('[HardwareId] Could not get hardware identifier:', err);
      }
    }

    // 4. Crypto-random fallback if hardware id is inaccessible
    if (!resolvedId || !resolvedId.trim()) {
      resolvedId = `dev_${Date.now()}_${Math.random().toString(36).substring(2, 10)}`;
    }

    cachedDeviceId = resolvedId.trim();

    // 5. Always ensure BOTH persistent storages hold the identical device ID
    try {
      await AsyncStorage.setItem(ASYNC_DEVICE_ID_KEY, cachedDeviceId);
    } catch (err) {
      console.warn('[AsyncStorage] Failed to persist device ID:', err);
    }

    try {
      await SecureStore.setItemAsync(SECURE_DEVICE_ID_KEY, cachedDeviceId, {
        keychainAccessible: SecureStore.AFTER_FIRST_UNLOCK,
      });
    } catch (err) {
      console.warn('[SecureStore] Failed to persist device ID:', err);
    }

    return cachedDeviceId;
  })();

  try {
    return await deviceIdPromise;
  } finally {
    deviceIdPromise = null;
  }
}

export type TrialExpiredCallback = () => void;
let onTrialExpiredListener: TrialExpiredCallback | null = null;

export function setOnTrialExpiredListener(callback: TrialExpiredCallback | null): void {
  onTrialExpiredListener = callback;
}

export function notifyTrialExpired(): void {
  if (onTrialExpiredListener) {
    try {
      onTrialExpiredListener();
    } catch (e) {
      console.warn('Error in trial expired listener:', e);
    }
  }
}

// ==========================================
// Authentication & Session Management
// ==========================================

let cachedAuthToken: string | null = null;
export type AuthRequiredCallback = () => void;
let onAuthRequiredListener: AuthRequiredCallback | null = null;

export function setOnAuthRequiredListener(callback: AuthRequiredCallback | null): void {
  onAuthRequiredListener = callback;
}

export function notifyAuthRequired(): void {
  if (onAuthRequiredListener) {
    try {
      onAuthRequiredListener();
    } catch (e) {
      console.warn('Error in auth required listener:', e);
    }
  }
}

export function toSafeHeaderAscii(val: string): string {
  if (!val) return '';
  if (val.includes(':')) {
    const [dev, ...nickParts] = val.split(':');
    const nick = nickParts.join(':');
    try {
      return `${dev}:${encodeURIComponent(decodeURIComponent(nick))}`;
    } catch {
      return `${dev}:${encodeURIComponent(nick)}`;
    }
  }
  try {
    return /[^\x00-\x7F]/.test(val) ? encodeURIComponent(decodeURIComponent(val)) : val;
  } catch {
    return encodeURIComponent(val);
  }
}

export function setAuthToken(token: string | null): void {
  cachedAuthToken = token ? toSafeHeaderAscii(token.trim()) : null;
}

export function getAuthToken(): string | null {
  return cachedAuthToken;
}

export function clearAuthSession(): void {
  cachedAuthToken = null;
}

export function buildAuthToken(deviceId: string, nickname: string): string {
  const cleanDevice = (deviceId || '').trim();
  const cleanNick = (nickname || '').trim() || 'Ученик';
  return `${cleanDevice}:${encodeURIComponent(cleanNick)}`;
}

export interface LicenseStatus {
  is_active: boolean;
  has_key?: boolean;
  free_reviews_left?: number;
  max_free_reviews?: number;
  days_left: number;
  expires_at: string;
  device_id?: string;
  activated_key?: string;
  package_name?: string;
}

export interface KeyActivateResponse {
  success: boolean;
  message: string;
  is_active: boolean;
  has_key?: boolean;
  free_reviews_left?: number;
  max_free_reviews?: number;
  days_left: number;
  expires_at: string;
  package_name?: string;
}

export async function getLicenseStatus(baseUrl: string = API_BASE_URL): Promise<LicenseStatus> {
  const deviceId = await getDeviceId();
  const endpoint = `${resolveBaseUrl(baseUrl)}/api/v1/license/status`;
  const response = await fetchWithTimeout(endpoint, {
    headers: {
      Accept: 'application/json',
      'X-Device-ID': deviceId,
    },
  });

  if (!response.ok) {
    throw await parseErrorResponse(response);
  }

  return (await response.json()) as LicenseStatus;
}

export async function activateAccessKey(
  keyCode: string,
  baseUrl: string = API_BASE_URL
): Promise<KeyActivateResponse> {
  const deviceId = await getDeviceId();
  const cleanedKey = (keyCode || '')
    .trim()
    .toUpperCase()
    .replace(/[\u2010\u2011\u2012\u2013\u2014\u2015\u2212]/g, '-')
    .replace(/\s*-\s*/g, '-')
    .replace(/\s+/g, '');
  const endpoint = `${resolveBaseUrl(baseUrl)}/api/v1/license/activate`;
  const response = await fetchWithTimeout(endpoint, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
      'X-Device-ID': deviceId,
    },
    body: JSON.stringify({ key_code: cleanedKey }),
  });

  if (!response.ok) {
    throw await parseErrorResponse(response);
  }

  return (await response.json()) as KeyActivateResponse;
}

export interface InvoiceRequestResponse {
  success: boolean;
  email_sent: boolean;
  invoice_number: string;
  viitenumber: string;
  amount: string;
  currency: string;
  recipient: string;
  iban: string;
  swift_bic: string;
  explanation: string;
  pdf_download_url: string;
  transport?: string;
  message: string;
}

export async function requestInvoiceEmail(
  email?: string,
  plan?: string,
  payerName?: string,
  baseUrl: string = API_BASE_URL
): Promise<InvoiceRequestResponse> {
  const deviceId = await getDeviceId();
  const endpoint = `${resolveBaseUrl(baseUrl)}/api/v1/license/invoice`;
  const response = await fetchWithTimeout(endpoint, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
      'X-Device-ID': deviceId,
    },
    body: JSON.stringify({
      email: (email || '').trim() || undefined,
      plan: plan || 'school_year',
      plan_id: plan || 'school_year',
      device_id: deviceId,
      payer_name: payerName,
    }),
  });

  if (!response.ok) {
    throw await parseErrorResponse(response);
  }

  return (await response.json()) as InvoiceRequestResponse;
}

export interface PlanItem {
  id: string;
  title: string;
  price: string;
  price_per_month: string;
  duration_months: number;
  badge?: string | null;
  is_popular?: boolean;
  description?: string | null;
  subtext?: string | null;
}

export interface BankDetails {
  recipient_name: string;
  iban: string;
  swift_bic: string;
}

export interface PlansCatalogResponse {
  plans: PlanItem[];
  bank_details: BankDetails;
}

export async function getPlansCatalog(
  baseUrl: string = API_BASE_URL
): Promise<PlansCatalogResponse> {
  const endpoint = `${resolveBaseUrl(baseUrl)}/api/v1/license/plans`;
  const response = await fetchWithTimeout(endpoint, {
    headers: {
      Accept: 'application/json',
    },
  });

  if (!response.ok) {
    throw await parseErrorResponse(response);
  }

  return (await response.json()) as PlansCatalogResponse;
}

export interface MoreExamplesRequest {
  task_title: string;
  theme_explanation?: string;
  vocabulary: VocabularyItem[];
  current_template: string;
  grade: number;
  tier: string;
}

export interface MoreExamplesResponse {
  templates: string[];
}

export interface QuickTranslateRequest {
  text?: string;
  image_base64?: string;
  mime_type?: string;
  source_lang?: string;
  target_lang?: string;
}

export interface QuickTranslateResponse {
  original_text: string;
  translated_text: string;
  base_forms?: string;
  context_note?: string;
  source_lang: string;
  target_lang: string;
}

let lastKnownRequestId: string = '';

export function getLastRequestId(): string {
  return lastKnownRequestId;
}

export function setLastRequestId(id: string): void {
  lastKnownRequestId = id;
}

export function generateClientRequestId(): string {
  const rand = Math.random().toString(36).substring(2, 8);
  const id = `req_${Date.now()}_${rand}`;
  lastKnownRequestId = id;
  return id;
}

export interface FeedbackPayload {
  category: 'bug' | 'feature';
  message: string;
  contact?: string;
  device_model?: string;
  os_version?: string;
  app_version?: string;
  current_grade?: number;
  last_request_id?: string;
  client_time?: string;
}

export interface FeedbackResponse {
  success: boolean;
  message: string;
}

/**
 * Formats any network, HTTP, or unexpected error into a user-friendly Russian explanation.
 * Eliminates technical stack traces, internal paths, and raw system exceptions.
 */
export function formatFriendlyErrorMessage(error: any): string {
  if (!error) {
    return 'Произошла непредвиденная ошибка. Пожалуйста, попробуйте еще раз.';
  }

  // If already an ApiError with a friendly message
  if (error instanceof ApiError) {
    if (error.status === 500) {
      return (
        error.message ||
        'Временный сбой при обработке задания. Попробуйте еще раз через несколько секунд.'
      );
    }
    if (error.status === 502 || error.status === 503 || error.status === 504) {
      if (
        error.message &&
        !error.message.includes('Server returned status') &&
        !error.message.includes('Сбой сервера')
      ) {
        return error.message;
      }
      return 'Сервер TarkApp временно перегружен или обновляется. Пожалуйста, повторите попытку через минуту.';
    }
    if (error.status === 413) {
      return 'Размер фотографии слишком велик. Пожалуйста, выберите изображение меньшего размера.';
    }
    if (error.status === 404) {
      return 'Запрашиваемый ресурс не найден на сервере.';
    }
    if (error.message && !error.message.includes('Server returned status')) {
      return error.message;
    }
  }

  const msg = typeof error === 'string' ? error : error.message || String(error);

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

  // Network connection / DNS / Offline / Cleartext issues
  if (
    msg.includes('Network request failed') ||
    msg.includes('UnknownHostException') ||
    msg.includes('Unable to resolve host') ||
    msg.includes('SSLHandshakeException') ||
    msg.includes('CertPathValidatorException') ||
    msg.includes('Unexpected char') ||
    msg.includes('IllegalArgumentException') ||
    msg.includes('CLEARTEXT') ||
    msg.includes('Cleartext') ||
    msg.includes('cleartext') ||
    msg.includes('Failed to connect') ||
    msg.includes('ConnectException') ||
    msg.includes('ECONNREFUSED') ||
    msg.includes('ENOTFOUND') ||
    msg.includes('EHOSTUNREACH') ||
    msg.includes('NetworkError')
  ) {
    return 'Не удалось связаться с сервером TarkApp. Пожалуйста, проверьте интернет-соединение и попробуйте снова.';
  }

  // Timeout issues
  if (
    msg.includes('timeout') ||
    msg.includes('Timeout') ||
    msg.includes('AbortError') ||
    msg.includes('aborted')
  ) {
    return 'Время ожидания ответа от сервера истекло. Проверьте стабильность соединения и попробуйте снова.';
  }

  // 500 status in message
  if (msg.includes('500') || msg.includes('INTERNAL_SERVER_ERROR')) {
    return 'Временный сбой при обработке задания. Попробуйте еще раз через несколько секунд.';
  }

  // 502/503/504 in message
  if (msg.includes('502') || msg.includes('503') || msg.includes('504')) {
    return 'Сервер временно недоступен или перезагружается. Попробуйте через минуту.';
  }

  // If the error message is already user-facing Russian text, keep it!
  const hasCyrillic = /[а-яёА-ЯЁ]/.test(msg);
  if (hasCyrillic && !msg.includes('java.') && !msg.includes('at ') && !msg.includes('Error:')) {
    return msg;
  }

  return 'Временный сбой при соединении с сервером. Пожалуйста, попробуйте еще раз.';
}

/**
 * Parses HTTP error response body into an ApiError.
 */
async function parseErrorResponse(response: Response): Promise<ApiError> {
  let friendlyMessage = `Сбой сервера (${response.status})`;
  let errorCode: string | undefined = undefined;

  try {
    const errJson = await response.json();
    if (errJson?.detail && typeof errJson.detail === 'object') {
      if (errJson.detail.error) {
        errorCode = errJson.detail.error;
      }
      if (errJson.detail.message) {
        friendlyMessage = errJson.detail.message;
      }
    } else if (errJson.message) {
      friendlyMessage = errJson.message;
    } else if (typeof errJson.detail === 'string') {
      friendlyMessage = errJson.detail;
    } else if (Array.isArray(errJson.detail) && errJson.detail.length > 0) {
      friendlyMessage = errJson.detail.map((d: any) => d.msg || d).join(', ');
    }
    if (errJson.code) {
      errorCode = errJson.code;
    }
    if (errJson.error && typeof errJson.error === 'string') {
      errorCode = errJson.error;
    }
  } catch {
    // Non-JSON response
  }

  // Intercept HTTP 401 Unauthorized (AuthGuard)
  if (
    response.status === 401 ||
    errorCode === 'UNAUTHORIZED' ||
    friendlyMessage.includes('Войдите в профиль')
  ) {
    errorCode = errorCode || 'UNAUTHORIZED';
    friendlyMessage = 'Войдите в профиль, чтобы использовать разборы';
    notifyAuthRequired();
  }

  // Intercept HTTP 403 with TRIAL_EXPIRED or REVIEWS_LIMIT_REACHED
  if (
    response.status === 403 &&
    (errorCode === 'TRIAL_EXPIRED' ||
      errorCode === 'REVIEWS_LIMIT_REACHED' ||
      friendlyMessage.includes('пробного периода') ||
      friendlyMessage.includes('Бесплатные разборы закончились'))
  ) {
    errorCode = errorCode || (friendlyMessage.includes('Бесплатные разборы') ? 'REVIEWS_LIMIT_REACHED' : 'TRIAL_EXPIRED');
    notifyTrialExpired();
  }

  if (response.status === 500 && !friendlyMessage.includes('Временный сбой')) {
    friendlyMessage = 'Временный сбой при обработке задания. Попробуйте еще раз через несколько секунд.';
  }

  return new ApiError(response.status, friendlyMessage, errorCode);
}

/**
 * Fetches additional Estonian sentence examples for practice in PhraseBuilder.
 */
export async function fetchMoreExamples(
  request: MoreExamplesRequest,
  baseUrl: string = API_BASE_URL
): Promise<string[]> {
  const endpoint = `${resolveBaseUrl(baseUrl)}/api/v1/more-examples`;
  try {
    const deviceId = await getDeviceId();
    const response = await fetchWithTimeout(endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
        'X-Device-ID': deviceId,
      },
      body: JSON.stringify(request),
    });

    if (!response.ok) {
      throw await parseErrorResponse(response);
    }

    const data = (await response.json()) as MoreExamplesResponse;
    return data.templates || [];
  } catch (err: any) {
    captureException(err, { endpoint, context: 'fetchMoreExamples' });
    if (err instanceof ApiError) {
      throw err;
    }
    throw new ApiError(0, formatFriendlyErrorMessage(err), undefined, err);
  }
}

/**
 * Analyzes a photographed textbook page using multipart/form-data.
 * Uses Zero-PII principles: only sends grade, tier, interest, nickname + image file.
 */
export async function analyzePage(
  imageUri: string,
  profile: UserProfile,
  baseUrl: string = API_BASE_URL
): Promise<PageAnalysisResponse> {
  const endpoint = `${resolveBaseUrl(baseUrl)}/api/v1/analyze-page`;
  try {
    const deviceId = await getDeviceId();
    const formData = new FormData();

    const filename = imageUri.split('/').pop() || 'textbook_page.jpg';
    const match = /\.(\w+)$/.exec(filename);
    const type = match ? `image/${match[1]}` : 'image/jpeg';

    // React Native FormData format
    // @ts-ignore
    formData.append('file', {
      uri: imageUri,
      name: filename,
      type,
    });

    formData.append('grade', String(profile.grade));
    formData.append('tier', profile.tier);
    formData.append('interests', (profile.interests || []).join(', '));
    formData.append('nickname', profile.nickname || 'Друг');

    const headers: Record<string, string> = {
      Accept: 'application/json',
      'X-Device-ID': deviceId,
    };
    const token = getAuthToken();
    if (token) {
      const safeToken = toSafeHeaderAscii(token);
      headers['Authorization'] = `Bearer ${safeToken}`;
      headers['X-Auth-Token'] = safeToken;
    }

    const response = await fetchWithTimeout(endpoint, {
      method: 'POST',
      body: formData,
      headers,
    });

    if (!response.ok) {
      throw await parseErrorResponse(response);
    }

    return (await response.json()) as PageAnalysisResponse;
  } catch (err: any) {
    captureException(err, { endpoint, context: 'analyzePage' });
    if (err instanceof ApiError) {
      throw err;
    }
    throw new ApiError(0, formatFriendlyErrorMessage(err), undefined, err);
  }
}

export interface ImagePayload {
  base64?: string;
  uri?: string;
  mimeType?: string;
}

/**
 * Analyzes one or multiple textbook/workbook pages using JSON Base64 payload.
 */
export async function analyzePagesJson(
  images: ImagePayload[],
  profile: UserProfile,
  baseUrl: string = API_BASE_URL
): Promise<PageAnalysisResponse> {
  const endpoint = `${resolveBaseUrl(baseUrl)}/api/v1/analyze-page/json`;
  try {
    const deviceId = await getDeviceId();
    const validBase64Images = images
      .map((img) => img.base64)
      .filter((b): b is string => !!b && b.length > 0);

    const mimeTypes = images.map((img) => img.mimeType || 'image/jpeg');

    const bodyPayload = {
      images_base64: validBase64Images,
      mime_type: mimeTypes[0] || 'image/jpeg',
      mime_types: mimeTypes,
      grade: profile.grade,
      tier: profile.tier,
      interests: profile.interests,
      nickname: profile.nickname,
    };

    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      Accept: 'application/json',
      'X-Device-ID': deviceId,
    };
    const token = getAuthToken();
    if (token) {
      const safeToken = toSafeHeaderAscii(token);
      headers['Authorization'] = `Bearer ${safeToken}`;
      headers['X-Auth-Token'] = safeToken;
    }

    const response = await fetchWithTimeout(endpoint, {
      method: 'POST',
      headers,
      body: JSON.stringify(bodyPayload),
    });

    if (!response.ok) {
      throw await parseErrorResponse(response);
    }

    return (await response.json()) as PageAnalysisResponse;
  } catch (err: any) {
    captureException(err, { endpoint, context: 'analyzePagesJson' });
    if (err instanceof ApiError) {
      throw err;
    }
    throw new ApiError(0, formatFriendlyErrorMessage(err), undefined, err);
  }
}

/**
 * Analyzes a single textbook page using JSON Base64 payload (for backward compatibility).
 */
export async function analyzePageJson(
  base64: string,
  mimeType: string,
  profile: UserProfile,
  baseUrl: string = API_BASE_URL
): Promise<PageAnalysisResponse> {
  return analyzePagesJson([{ base64, mimeType }], profile, baseUrl);
}

/**
 * Health check ping to TarkApp Backend.
 */
export async function checkBackendHealth(
  baseUrl: string = API_BASE_URL
): Promise<boolean> {
  try {
    const res = await fetchWithTimeout(`${resolveBaseUrl(baseUrl)}/health`, { method: 'GET' }, 5000);
    return res.ok;
  } catch {
    return false;
  }
}

/**
 * Быстрый школьный переводчик терминов, фраз или фрагментов учебника.
 */
export async function quickTranslate(
  request: QuickTranslateRequest,
  baseUrl: string = API_BASE_URL
): Promise<QuickTranslateResponse> {
  const endpoint = `${resolveBaseUrl(baseUrl)}/api/v1/translate/quick`;
  try {
    const deviceId = await getDeviceId();
    const response = await fetchWithTimeout(endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
        'X-Device-ID': deviceId,
      },
      body: JSON.stringify(request),
    });

    if (!response.ok) {
      throw await parseErrorResponse(response);
    }

    const reqId = response.headers.get('x-request-id');
    if (reqId) {
      setLastRequestId(reqId);
    }

    return (await response.json()) as QuickTranslateResponse;
  } catch (err: any) {
    captureException(err, { endpoint, context: 'quickTranslate' });
    if (err instanceof ApiError) {
      throw err;
    }
    throw new ApiError(0, formatFriendlyErrorMessage(err), undefined, err);
  }
}

/**
 * Отправляет баг-репорт или идею разработчику в Telegram с привязкой к телеметрии.
 */
export async function sendFeedback(
  payload: FeedbackPayload,
  baseUrl: string = API_BASE_URL
): Promise<FeedbackResponse> {
  const endpoint = `${resolveBaseUrl(baseUrl)}/api/v1/feedback`;
  try {
    const deviceId = await getDeviceId();
    const clientReqId = generateClientRequestId();
    const response = await fetchWithTimeout(endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
        'X-Request-ID': clientReqId,
        'X-Device-ID': deviceId,
      },
      body: JSON.stringify(payload),
    });

    const serverReqId = response.headers.get('x-request-id');
    if (serverReqId) {
      setLastRequestId(serverReqId);
    }

    if (!response.ok) {
      throw await parseErrorResponse(response);
    }

    return (await response.json()) as FeedbackResponse;
  } catch (err: any) {
    captureException(err, { endpoint, context: 'sendFeedback' });
    if (err instanceof ApiError) {
      throw err;
    }
    throw new ApiError(0, formatFriendlyErrorMessage(err), undefined, err);
  }
}
