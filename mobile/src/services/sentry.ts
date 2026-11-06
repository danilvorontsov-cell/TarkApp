import * as Sentry from '@sentry/react-native';

/**
 * Sentry integration for TarkApp Mobile (tark-systems).
 * Real-time crash reporting, native error handling, and performance monitoring.
 */

// Sentry DSN configuration for organization 'tark-systems'
// Run code: ea0bafc94d
const DEFAULT_SENTRY_DSN =
  'https://ea0bafc94d@o4508900000000000.ingest.de.sentry.io/4508900000000000';

export const SENTRY_DSN =
  process.env.EXPO_PUBLIC_SENTRY_DSN ||
  process.env.SENTRY_DSN ||
  DEFAULT_SENTRY_DSN;

export const SENTRY_ORG = 'tark-systems';
export const SENTRY_RUN_CODE = 'ea0bafc94d';

let isSentryInitialized = false;

/**
 * Initialize Sentry SDK for React Native / Expo.
 * Configures crash handlers, JS error capturing, and auto session tracking.
 */
export function initSentry(): void {
  if (isSentryInitialized) {
    return;
  }

  if (!SENTRY_DSN) {
    console.log('[Sentry] No DSN configured, skipping initialization');
    return;
  }

  try {
    Sentry.init({
      dsn: SENTRY_DSN,
      debug: false,
      tracesSampleRate: 1.0,
      enableAutoSessionTracking: true,
      enableNativeCrashHandling: true,
      environment: __DEV__ ? 'development' : 'production',
      beforeSend(event) {
        // Tag events with organization metadata
        if (event.tags) {
          event.tags.org = SENTRY_ORG;
          event.tags.run_code = SENTRY_RUN_CODE;
        } else {
          event.tags = {
            org: SENTRY_ORG,
            run_code: SENTRY_RUN_CODE,
          };
        }
        return event;
      },
    });

    isSentryInitialized = true;
    console.log(`[Sentry] Initialized for ${SENTRY_ORG} [${SENTRY_RUN_CODE}]`);
  } catch (err) {
    console.warn('[Sentry] Failed to initialize @sentry/react-native:', err);
  }
}

/**
 * Safely capture an exception to Sentry.
 */
export function captureException(
  error: unknown,
  context?: Record<string, unknown>
): void {
  try {
    if (isSentryInitialized) {
      Sentry.captureException(error, { extra: context });
    } else if (__DEV__) {
      console.log('[Sentry Dev] Captured exception:', error, context);
    }
  } catch (err) {
    console.warn('[Sentry] Failed to capture exception:', err);
  }
}

/**
 * Safely capture an informational or warning message to Sentry.
 */
export function captureMessage(
  message: string,
  level: Sentry.SeverityLevel = 'info'
): void {
  try {
    if (isSentryInitialized) {
      Sentry.captureMessage(message, level);
    } else if (__DEV__) {
      console.log(`[Sentry Dev] Captured message [${level}]:`, message);
    }
  } catch (err) {
    console.warn('[Sentry] Failed to capture message:', err);
  }
}

/**
 * Triggers a test diagnostic event in Sentry to verify delivery to sentry.io.
 */
export function sendTestSentryEvent(): void {
  try {
    console.log('[Sentry] Dispatching test event for tark-systems...');
    captureMessage(
      `TarkApp Diagnostic Test Event — org: ${SENTRY_ORG}, run: ${SENTRY_RUN_CODE}`,
      'info'
    );
  } catch (err) {
    console.warn('[Sentry] Error dispatching test event:', err);
  }
}

export { Sentry };
