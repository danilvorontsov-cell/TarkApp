import { PageAnalysisResponse, UserProfile } from '../types';

// Default API base URL for mobile Hotspot connection
export const API_BASE_URL =
  process.env.EXPO_PUBLIC_API_URL || 'http://10.253.79.137:8080';

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = 'ApiError';
  }
}

/**
 * Analyzes a photographed textbook page using the TarkApp Backend.
 * Uses Zero-PII principles: only sends grade, tier, interest, nickname + image file.
 */
export async function analyzePage(
  imageUri: string,
  profile: UserProfile,
  baseUrl: string = API_BASE_URL
): Promise<PageAnalysisResponse> {
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

  const endpoint = `${baseUrl}/api/v1/analyze-page`;

  const response = await fetch(endpoint, {
    method: 'POST',
    body: formData,
    headers: {
      Accept: 'application/json',
      // Note: Do not set Content-Type manually with FormData so boundaries are generated
    },
  });

  if (!response.ok) {
    let errorDetail = `Server returned status ${response.status}`;
    try {
      const errJson = await response.json();
      if (errJson.detail) {
        errorDetail = errJson.detail;
      }
    } catch {
      // fallback
    }
    throw new ApiError(response.status, errorDetail);
  }

  const result = (await response.json()) as PageAnalysisResponse;
  return result;
}

/**
 * Health check ping to TarkApp Backend.
 */
export async function checkBackendHealth(
  baseUrl: string = API_BASE_URL
): Promise<boolean> {
  try {
    const res = await fetch(`${baseUrl}/health`, { method: 'GET' });
    return res.ok;
  } catch {
    return false;
  }
}
