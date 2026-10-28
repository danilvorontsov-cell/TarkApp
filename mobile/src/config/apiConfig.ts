/**
 * Global API Configuration for TarkApp.
 * 
 * Clean, production-ready environment separation:
 * - Production / EAS APK: https://uvn-235-67.ams01.zonevs.eu (Zone VPS)
 * - Local Dev (npm start): http://10.253.79.137:8080 (via mobile/.env.development / .env.local)
 */

export const DEFAULT_API_BASE_URL =
  process.env.EXPO_PUBLIC_API_URL || 'https://uvn-235-67.ams01.zonevs.eu';

export const API_BASE_URL = DEFAULT_API_BASE_URL;

/**
 * Returns the configured API base URL.
 */
export function getApiBaseUrl(): string {
  return API_BASE_URL;
}

/**
 * Synchronously returns the configured API base URL.
 */
export function getSyncApiBaseUrl(): string {
  return API_BASE_URL;
}
