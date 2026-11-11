/**
 * Text Preprocessing / Sanitization for Text-to-Speech (TTS).
 * Normalizes compound words with prefixes like "супер", "мега", "ультра", "экстра", "квази"
 * by inserting hyphens to ensure correct stress and pronunciation in neural TTS models.
 */

// Matches compound prefixes written solid without an existing hyphen followed by a letter.
// Uses negative lookbehind to avoid matching inside other words, and negative lookahead
// to avoid duplicating hyphens.
const COMPOUND_PREFIX_REGEX = /(?<![а-яёa-z0-9_-])(супер|мега|ультра|экстра|квази)(?!-)(?=[а-яёa-z])/gi;

/**
 * Sanitizes input text before sending it to speech synthesis.
 * E.g., "суперпрыжки" -> "супер-прыжки", "мегамозг" -> "мега-мозг".
 * If already hyphenated ("супер-прыжки"), leaves it unchanged.
 */
export function sanitizeTextForTts(text: string): string {
  if (!text) {
    return text;
  }
  return text.replace(COMPOUND_PREFIX_REGEX, (match) => `${match}-`);
}
