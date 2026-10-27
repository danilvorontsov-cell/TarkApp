import { manipulateAsync, SaveFormat, Action } from 'expo-image-manipulator';
import { Image } from 'react-native';

export interface OptimizedImageResult {
  uri: string;
  base64: string;
  width: number;
  height: number;
}

export const MAX_PAGE_DIMENSION = 1600;
export const PAGE_JPEG_QUALITY = 0.78;

/**
 * Retrieves natural width and height of an image from its URI if not provided.
 */
function getImageDimensions(uri: string): Promise<{ width: number; height: number }> {
  return new Promise((resolve, reject) => {
    Image.getSize(
      uri,
      (width, height) => resolve({ width, height }),
      (err) => reject(err)
    );
  });
}

/**
 * Optimizes a textbook/workbook image:
 * - Constrains maximum dimension (width or height) to 1600px while preserving aspect ratio.
 * - Compresses with JPEG quality 0.78 (optimal balance of OCR sharpness and small payload 300-450 KB).
 * - Produces base64 string and optimized local file URI.
 */
export async function optimizePageImage(
  uri: string,
  knownWidth?: number,
  knownHeight?: number
): Promise<OptimizedImageResult> {
  const actions: Action[] = [];

  let width = knownWidth;
  let height = knownHeight;

  if (!width || !height) {
    try {
      const dimensions = await getImageDimensions(uri);
      width = dimensions.width;
      height = dimensions.height;
    } catch {
      // Fallback: constraint width to MAX_PAGE_DIMENSION if dimensions cannot be inspected
      width = MAX_PAGE_DIMENSION + 1;
      height = 0;
    }
  }

  if (width && height) {
    if (width > MAX_PAGE_DIMENSION || height > MAX_PAGE_DIMENSION) {
      if (width >= height) {
        actions.push({ resize: { width: MAX_PAGE_DIMENSION } });
      } else {
        actions.push({ resize: { height: MAX_PAGE_DIMENSION } });
      }
    }
  } else {
    actions.push({ resize: { width: MAX_PAGE_DIMENSION } });
  }

  const result = await manipulateAsync(uri, actions, {
    compress: PAGE_JPEG_QUALITY,
    format: SaveFormat.JPEG,
    base64: true,
  });

  return {
    uri: result.uri,
    base64: result.base64 || '',
    width: result.width,
    height: result.height,
  };
}

/**
 * Batch-optimizes an array of assets/URIs.
 */
export async function optimizePageImages(
  items: Array<{ uri: string; width?: number; height?: number }>
): Promise<OptimizedImageResult[]> {
  return Promise.all(
    items.map((item) => optimizePageImage(item.uri, item.width, item.height))
  );
}
