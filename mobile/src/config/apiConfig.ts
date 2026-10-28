/**
 * Global API Configuration for TarkApp.
 * 
 * Clean, production-ready architecture:
 * The base URL is configured strictly via the EXPO_PUBLIC_API_URL environment variable
 * (set in mobile/.env, eas.json, or build pipeline) with a seamless default fallback.
 * 
 * Works out-of-the-box without any manual switches or user-facing configuration.
 */

export const DEFAULT_API_BASE_URL =
  process.env.EXPO_PUBLIC_API_URL || 'http://10.253.79.137:8080';

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
