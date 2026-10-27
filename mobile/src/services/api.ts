import { PageAnalysisResponse, UserProfile, VocabularyItem } from '../types';
import { captureException } from './sentry';

// Default API base URL for mobile Hotspot connection
export const API_BASE_URL =
  process.env.EXPO_PUBLIC_API_URL || 'http://10.253.79.137:8080';

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

  // Network connection / DNS / Offline issues
  if (
    msg.includes('Network request failed') ||
    msg.includes('Failed to connect') ||
    msg.includes('ConnectException') ||
    msg.includes('ECONNREFUSED') ||
    msg.includes('ENOTFOUND') ||
    msg.includes('EHOSTUNREACH') ||
    msg.includes('NetworkError')
  ) {
    return 'Не удалось связаться с сервером TarkApp. Проверьте подключение к Wi-Fi / интернету и убедитесь, что сервер запущен.';
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
    if (errJson.message) {
      friendlyMessage = errJson.message;
    } else if (typeof errJson.detail === 'string') {
      friendlyMessage = errJson.detail;
    } else if (Array.isArray(errJson.detail) && errJson.detail.length > 0) {
      friendlyMessage = errJson.detail.map((d: any) => d.msg || d).join(', ');
    }
    if (errJson.code) {
      errorCode = errJson.code;
    }
  } catch {
    // Non-JSON response
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
  const endpoint = `${baseUrl}/api/v1/more-examples`;
  try {
    const response = await fetch(endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
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
  const endpoint = `${baseUrl}/api/v1/analyze-page`;
  try {
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

    const response = await fetch(endpoint, {
      method: 'POST',
      body: formData,
      headers: {
        Accept: 'application/json',
      },
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
  const endpoint = `${baseUrl}/api/v1/analyze-page/json`;
  try {
    const validBase64Images = images
      .map((img) => img.base64)
      .filter((b): b is string => !!b && b.length > 0);

    const mimeTypes = images.map((img) => img.mimeType || 'image/jpeg');

    const bodyPayload = {
      image_base64: validBase64Images[0] || '',
      images_base64: validBase64Images,
      mime_type: mimeTypes[0] || 'image/jpeg',
      mime_types: mimeTypes,
      grade: profile.grade,
      tier: profile.tier,
      interests: profile.interests,
      nickname: profile.nickname,
    };

    const response = await fetch(endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
      },
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
    const res = await fetch(`${baseUrl}/health`, { method: 'GET' });
    return res.ok;
  } catch {
    return false;
  }
}
