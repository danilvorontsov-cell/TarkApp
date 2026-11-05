/**
 * Global API Configuration for TarkApp.
 * 
 * Configured backend URL: https://api.tarkapp.ee
 */

export const DEFAULT_API_BASE_URL =
  process.env.EXPO_PUBLIC_API_URL || 'https://api.tarkapp.ee';

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
