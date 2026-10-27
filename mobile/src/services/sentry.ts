/**
 * Safe Sentry integration stub for TarkApp Mobile.
 * Prepares the application for Sentry crash reporting without hard dependencies.
 * Activated only when EXPO_PUBLIC_SENTRY_DSN or SENTRY_DSN is configured.
 */

const SENTRY_DSN =
  process.env.EXPO_PUBLIC_SENTRY_DSN ||
  process.env.SENTRY_DSN ||
  '';

let isSentryInitialized = false;

/**
 * Initialize Sentry if DSN is set and the package is installed.
 */
export function initSentry(): void {
  if (!SENTRY_DSN) {
    // Sentry DSN not provided - keep stub mode active
    return;
  }

  try {
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const Sentry = require('@sentry/react-native');
    if (Sentry && typeof Sentry.init === 'function') {
      Sentry.init({
        dsn: SENTRY_DSN,
        enableInExpoDevelopment: false,
        debug: false,
      });
      isSentryInitialized = true;
      console.log('[Sentry] Successfully initialized with DSN');
    }
  } catch (err) {
    console.warn('[Sentry] @sentry/react-native not available or failed to initialize:', err);
  }
}

/**
 * Safely capture an exception to Sentry or log it.
 */
export function captureException(
  error: unknown,
  context?: Record<string, unknown>
): void {
  if (!isSentryInitialized) {
    if (__DEV__) {
      console.log('[Sentry Stub] Handled exception:', error, context);
    }
    return;
  }

  try {
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const Sentry = require('@sentry/react-native');
    if (Sentry && typeof Sentry.captureException === 'function') {
      Sentry.captureException(error, { extra: context });
    }
  } catch (err) {
    console.warn('[Sentry] Failed to capture exception:', err);
  }
}

/**
 * Safely capture an informational or warning message to Sentry.
 */
export function captureMessage(message: string): void {
  if (!isSentryInitialized) {
    if (__DEV__) {
      console.log('[Sentry Stub] Message:', message);
    }
    return;
  }

  try {
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const Sentry = require('@sentry/react-native');
    if (Sentry && typeof Sentry.captureMessage === 'function') {
      Sentry.captureMessage(message);
    }
  } catch (err) {
    console.warn('[Sentry] Failed to capture message:', err);
  }
}
