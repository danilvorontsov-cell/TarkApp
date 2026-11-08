import { LicenseStatus, PlanItem, BankDetails } from '../services/api';

export const DEFAULT_MAX_FREE_REVIEWS = 20;
export const DEFAULT_TRIAL_DAYS = 14;

/**
 * Feature flag controlling direct SEPA/IBAN invoicing UI inside the mobile app.
 * Defaults to true for Closed Beta; set EXPO_PUBLIC_ENABLE_DIRECT_INVOICE="false" for App Store / Google Play builds.
 */
export const ENABLE_DIRECT_INVOICE: boolean =
  typeof process !== 'undefined' &&
  process.env?.EXPO_PUBLIC_ENABLE_DIRECT_INVOICE !== undefined
    ? process.env.EXPO_PUBLIC_ENABLE_DIRECT_INVOICE.toLowerCase() !== 'false'
    : true;

export const DEFAULT_BANK_DETAILS: BankDetails = {
  recipient_name: 'Tark Systems OÜ',
  iban: (typeof process !== 'undefined' && process.env?.EXPO_PUBLIC_BANK_IBAN) || '',
  swift_bic: (typeof process !== 'undefined' && process.env?.EXPO_PUBLIC_BANK_SWIFT) || 'CPNKEE2X',
};

export const DEFAULT_PLANS: PlanItem[] = [
  {
    id: 'month_1',
    title: 'Попробовать 1 месяц',
    price: '9.99',
    price_per_month: '9.99',
    duration_months: 1,
    badge: null,
    is_popular: false,
    description: 'Для разовой помощи или подготовки к четверти',
    subtext: 'Продление каждый месяц, отмена в любой момент',
  },
  {
    id: 'semester',
    title: 'Оформить семестр',
    price: '44.90',
    price_per_month: '8.99',
    duration_months: 5,
    badge: '-10%',
    is_popular: false,
    description: 'Уверенная учёба на один семестр (5 месяцев)',
    subtext: '~8.99 € / мес (разовая оплата)',
  },
  {
    id: 'school_year',
    title: 'Учебный год',
    price: '71.90',
    price_per_month: '7.99',
    duration_months: 9,
    badge: 'Хит',
    is_popular: true,
    description: 'Сентябрь — Май (все 9 учебных месяцев)',
    subtext: '~7.99 € / мес (разовый платёж на все 9 месяцев учёбы)',
  },
  {
    id: 'full_year',
    title: 'Год с каникулами',
    price: '89.90',
    price_per_month: '7.49',
    duration_months: 12,
    badge: 'Выгодно',
    is_popular: false,
    description: 'Учебный год + 3 месяца лета для закрепления языка',
    subtext: '~7.49 € / мес (9 мес учёбы + 3 мес лета)',
  },
];

export interface SubscriptionInfo {
  isPro: boolean;
  hasKey: boolean;
  packageName: string | null;
  remainingReviews: number;
  maxReviews: number;
  reviewCounterText: string; // e.g. "20/20" or "19/20"
  fullReviewText: string;    // e.g. "20 из 20 на сегодня"
  daysLeft: number;
  statusLabel: string;
}

/**
 * Single Source of Truth for subscription and review limits across all screens and widgets.
 * Guaranteed to return 20/20 for fresh installs and free trial users.
 */
export function getSubscriptionInfo(status?: LicenseStatus | null): SubscriptionInfo {
  const hasKey = Boolean(status?.has_key);
  const packageName = status?.package_name || null;
  // A user is PRO ONLY IF has_key is true and package_name is present
  const isPro = Boolean(hasKey && packageName);

  // Dynamic server denominator with 20 fallback
  const maxReviews = status?.max_free_reviews ?? DEFAULT_MAX_FREE_REVIEWS;
  const remainingReviews = Math.max(
    0,
    status?.free_reviews_left ?? DEFAULT_MAX_FREE_REVIEWS
  );

  const daysLeft = status?.days_left ?? DEFAULT_TRIAL_DAYS;

  const reviewCounterText = `${remainingReviews}/${maxReviews}`;
  const fullReviewText = `${remainingReviews} из ${maxReviews} на сегодня`;

  let statusLabel = 'Бесплатный режим';
  if (isPro) {
    statusLabel = packageName ? `TarkApp PRO (${packageName})` : 'TarkApp PRO активен';
  }

  return {
    isPro,
    hasKey,
    packageName,
    remainingReviews,
    maxReviews,
    reviewCounterText,
    fullReviewText,
    daysLeft,
    statusLabel,
  };
}

/**
 * Sanitizes and auto-masks a license key / promo code input.
 * - Auto-appends hyphen after 4th and 8th characters when typing.
 * - Converts all characters to uppercase.
 * - Normalizes unicode hyphens/dashes (—, –, −) to standard ASCII minus (-).
 * - Strips whitespace and non-alphanumeric characters.
 */
export function applyKeyMask(currentText: string, prevText: string = ''): string {
  if (!currentText) return '';

  let sanitized = currentText
    .toUpperCase()
    .replace(/[\u2010\u2011\u2012\u2013\u2014\u2015\u2212]/g, '-')
    .replace(/\s+/g, '');

  const isDeleting = currentText.length < prevText.length;
  const rawAlnum = sanitized.replace(/[^A-Z0-9]/g, '').slice(0, 16);

  if (!rawAlnum) return '';

  const chunks: string[] = [];
  for (let i = 0; i < rawAlnum.length; i += 4) {
    chunks.push(rawAlnum.slice(i, i + 4));
  }

  let formatted = chunks.join('-');

  // If user typed a single character and just hit 4 or 8 characters, auto-append hyphen
  if (!isDeleting && (currentText.length - prevText.length === 1) && (rawAlnum.length === 4 || rawAlnum.length === 8)) {
    formatted += '-';
  }

  return formatted;
}

/**
 * Normalizes a key code before submitting to API.
 */
export function sanitizeKeyCode(keyCode: string): string {
  return (keyCode || '')
    .toUpperCase()
    .replace(/[\u2010\u2011\u2012\u2013\u2014\u2015\u2212]/g, '-')
    .replace(/\s*-\s*/g, '-')
    .replace(/\s+/g, '')
    .trim();
}
