import * as Sentry from '@sentry/react-native';

/**
 * Sentry integration for TarkApp Mobile (tark-systems).
 * Real-time crash reporting, native error handling, and performance monitoring.
 */

// Sentry DSN configuration for organization 'tark-systems', project 'tarkapp-mobile'
const DEFAULT_SENTRY_DSN =
  'https://e79b08bb210fb9906a3ebf8230bb4e80@o4512386157051904.ingest.de.sentry.io/4512386343043152';

export const SENTRY_DSN =
  process.env.EXPO_PUBLIC_SENTRY_DSN ||
  process.env.SENTRY_DSN ||
  DEFAULT_SENTRY_DSN;

export const SENTRY_ORG = 'tark-systems';
export const SENTRY_RUN_CODE = 'ea0bafc94d';

let isSentryInitialized = false;

/**
 * Masks sensitive query parameters (text, speech_text, device_id) in URLs to prevent PII leakage to Sentry.
 */
export function maskSensitiveUrl(url: string): string {
  if (!url || typeof url !== 'string') return url;
  return url.replace(
    /([?&](?:text|speech_text|speechText|device_id|deviceId|x-device-id)=)[^&#\s]*/gi,
    '$1[MASKED]'
  );
}

/**
 * Strips sensitive headers (Authorization, X-Device-ID, X-Admin-Secret) from HTTP events and breadcrumbs.
 */
export function sanitizeHeaders(headers: Record<string, any>): void {
  if (!headers || typeof headers !== 'object') return;
  const sensitiveKeys = ['authorization', 'x-device-id', 'x-admin-secret', 'cookie', 'set-cookie'];
  for (const key of Object.keys(headers)) {
    if (sensitiveKeys.includes(key.toLowerCase())) {
      delete headers[key];
    }
  }
}

/**
 * Sanitizes Sentry breadcrumbs before they are recorded.
 */
export function sanitizeBreadcrumb(breadcrumb: Sentry.Breadcrumb): Sentry.Breadcrumb | null {
  try {
    if (!breadcrumb) return breadcrumb;

    if (typeof breadcrumb.message === 'string') {
      breadcrumb.message = maskSensitiveUrl(breadcrumb.message);
    }

    if (breadcrumb.data && typeof breadcrumb.data === 'object') {
      if (typeof breadcrumb.data.url === 'string') {
        breadcrumb.data.url = maskSensitiveUrl(breadcrumb.data.url);
      }
      if (breadcrumb.data.headers) {
        sanitizeHeaders(breadcrumb.data.headers);
      }
      if (breadcrumb.data.request_headers) {
        sanitizeHeaders(breadcrumb.data.request_headers);
      }
      if (breadcrumb.data.response_headers) {
        sanitizeHeaders(breadcrumb.data.response_headers);
      }
    }
  } catch {
    // Fail-safe to avoid disrupting app telemetry
  }
  return breadcrumb;
}

/**
 * Sanitizes Sentry events before sending to Sentry servers.
 */
export function sanitizeEvent(event: any): any {
  try {
    if (!event) return event;

    // Tag events with organization metadata
    if (event.tags) {
      event.tags.org = SENTRY_ORG;
      event.tags.run_code = SENTRY_RUN_CODE;
      if (event.tags.device_id) {
        delete event.tags.device_id;
      }
    } else {
      event.tags = {
        org: SENTRY_ORG,
        run_code: SENTRY_RUN_CODE,
      };
    }

    if (typeof event.message === 'string') {
      event.message = maskSensitiveUrl(event.message);
    }

    // Sanitize HTTP request data if present
    if (event.request) {
      if (typeof event.request.url === 'string') {
        event.request.url = maskSensitiveUrl(event.request.url);
      }
      if (typeof event.request.query_string === 'string') {
        event.request.query_string = maskSensitiveUrl(event.request.query_string);
      }
      if (event.request.headers) {
        sanitizeHeaders(event.request.headers);
      }
    }

    // Sanitize breadcrumbs attached to the event
    if (Array.isArray(event.breadcrumbs)) {
      for (const b of event.breadcrumbs) {
        sanitizeBreadcrumb(b);
      }
    }
  } catch {
    // Fail-safe
  }
  return event;
}

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
    const isDev = typeof __DEV__ !== 'undefined' ? __DEV__ : false;

    Sentry.init({
      dsn: SENTRY_DSN,
      debug: false,
      sendDefaultPii: false,
      tracesSampleRate: isDev ? 1.0 : 0.2,
      enableAutoSessionTracking: true,
      enableNativeCrashHandling: true,
      environment: isDev ? 'development' : 'production',
      beforeBreadcrumb(breadcrumb) {
        return sanitizeBreadcrumb(breadcrumb);
      },
      beforeSend(event) {
        return sanitizeEvent(event);
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
    } else if (typeof __DEV__ !== 'undefined' && __DEV__) {
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
    } else if (typeof __DEV__ !== 'undefined' && __DEV__) {
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
