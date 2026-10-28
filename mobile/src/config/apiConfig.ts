import AsyncStorage from '@react-native-async-storage/async-storage';

/**
 * Storage key for runtime API URL overrides.
 */
export const CUSTOM_API_URL_STORAGE_KEY = '@tarkapp_custom_api_url';

/**
 * Default fallback API URL:
 * 1. Read from EXPO_PUBLIC_API_URL if configured during build/env
 * 2. Fallback to current host IP on mobile hotspot
 */
export const DEFAULT_API_BASE_URL =
  process.env.EXPO_PUBLIC_API_URL || 'http://10.253.79.137:8080';

let cachedApiUrl: string = DEFAULT_API_BASE_URL;
let isInitialized = false;

/**
 * Normalizes URL string: trims whitespace and strips trailing slashes.
 */
export function normalizeApiUrl(rawUrl: string): string {
  let url = (rawUrl || '').trim();
  while (url.endsWith('/')) {
    url = url.slice(0, -1);
  }
  return url;
}

/**
 * Initializes the API URL cache from AsyncStorage during app startup.
 */
export async function initApiBaseUrl(): Promise<string> {
  try {
    const saved = await AsyncStorage.getItem(CUSTOM_API_URL_STORAGE_KEY);
    if (saved && saved.trim()) {
      cachedApiUrl = normalizeApiUrl(saved);
    } else {
      cachedApiUrl = DEFAULT_API_BASE_URL;
    }
  } catch (e) {
    console.warn('[apiConfig] Failed to load custom API URL from storage:', e);
    cachedApiUrl = DEFAULT_API_BASE_URL;
  } finally {
    isInitialized = true;
  }
  return cachedApiUrl;
}

/**
 * Synchronous getter returning the active API Base URL.
 */
export function getSyncApiBaseUrl(): string {
  return cachedApiUrl;
}

/**
 * Asynchronous getter guaranteeing initialized storage before returning.
 */
export async function getApiBaseUrl(): Promise<string> {
  if (!isInitialized) {
    await initApiBaseUrl();
  }
  return cachedApiUrl;
}

/**
 * Saves a new custom API Base URL to AsyncStorage and updates memory cache.
 */
export async function setCustomApiBaseUrl(newUrl: string): Promise<string> {
  const normalized = normalizeApiUrl(newUrl);
  if (!normalized) {
    throw new Error('URL сервера не может быть пустым');
  }
  await AsyncStorage.setItem(CUSTOM_API_URL_STORAGE_KEY, normalized);
  cachedApiUrl = normalized;
  isInitialized = true;
  return normalized;
}

/**
 * Resets API Base URL to the default build/host configuration.
 */
export async function resetCustomApiBaseUrl(): Promise<void> {
  await AsyncStorage.removeItem(CUSTOM_API_URL_STORAGE_KEY);
  cachedApiUrl = DEFAULT_API_BASE_URL;
  isInitialized = true;
}

/**
 * Checks if a custom URL is currently configured in storage.
 */
export async function isCustomApiUrlActive(): Promise<boolean> {
  try {
    const saved = await AsyncStorage.getItem(CUSTOM_API_URL_STORAGE_KEY);
    return Boolean(saved && saved.trim() && saved.trim() !== DEFAULT_API_BASE_URL);
  } catch {
    return false;
  }
}

/**
 * Health check utility to test connectivity to a given server URL.
 */
export async function testServerConnection(
  targetUrl: string,
  timeoutMs: number = 4000
): Promise<{ ok: boolean; status?: number; error?: string }> {
  const normalized = normalizeApiUrl(targetUrl);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const res = await fetch(`${normalized}/health`, {
      method: 'GET',
      signal: controller.signal,
    });
    clearTimeout(timer);
    return { ok: res.ok, status: res.status };
  } catch (err: any) {
    clearTimeout(timer);
    const msg = err?.name === 'AbortError'
      ? 'Превышен таймаут ожидания (4 сек)'
      : err?.message || 'Ошибка соединения';
    return { ok: false, error: msg };
  }
}

/**
 * Backward compatibility export.
 */
export const API_BASE_URL = DEFAULT_API_BASE_URL;
