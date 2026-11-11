export {
  SchoolTier,
  AgeTier,
  TierConfig,
  TIER_POLICIES,
  getTierFromGrade,
  getTierPolicy,
} from '../services/gradePolicy';
import { SchoolTier, getTierFromGrade } from '../services/gradePolicy';
import { VisualData } from './visual';

export * from './visual';

export interface UserProfile {
  grade: number; // 1 - 12
  tier: SchoolTier;
  interests: string[]; // Free-form list of student's hobbies and interests
  interestsByGrade?: Record<number, string[]>;
  hasCustomInterests?: boolean; // Whether interests were manually entered/edited by user
  nickname: string;
  avatarUri?: string;
}

export interface VocabularyItem {
  est: string;
  ru: string;
  example: string;
  topicTitle?: string;
}

export interface StepItem {
  text: string;
  speech_text?: string;
  step_number?: number;
  is_formula?: boolean;
}

export interface SelfSolveStep {
  text: string;
  speech_text?: string;
  hint?: string;
}

export interface LessonCard {
  id?: string;
  title?: string;
  text: string;
  speech_text?: string;
}

export interface BilingualCard {
  est: string;
  ru?: string;
  text?: string;
  speech_text?: string;
}

export interface WorkedExample {
  title: string;
  given: string;
  steps: string[];
  note?: string;
  speech_text?: string;
}

export interface LessonSpeechLayer {
  voice_prompt_script: string;
  theme_explanation: string;
  alternative_explanation?: string | null;
  how_to_answer: string;
  worked_example?: string | null;
}

export interface PageAnalysisResponse {
  lesson_id?: string;
  task_title: string;
  theme_explanation: string;
  alternative_explanation?: string;
  vocabulary: VocabularyItem[];
  worked_example?: WorkedExample;
  visual?: VisualData | null;
  how_to_solve?: string[];
  how_to_answer: string;
  answer_template: string;
  voice_prompt_script: string;
  is_acceptable?: boolean;
  speech_layer?: LessonSpeechLayer;
  voice_prompt_script_speech?: string;
  theme_explanation_speech?: string;
  alternative_explanation_speech?: string;
  how_to_answer_speech?: string;
  worked_example_speech?: string;
  speech_text?: string;
}

export interface SavedLessonCard {
  id: string;
  timestamp: number;
  dateFormatted: string;
  grade: number;
  tier: SchoolTier;
  task_title: string;
  task_type?: 'Koolitöö' | 'Loodusõpetus' | 'Maailma Avastaja' | string;
  analysis: PageAnalysisResponse;
  imageUri?: string;
  imageUris?: string[];
}

// Popular suggested interests by age tier for quick addition
export const AGE_SUGGESTIONS: Record<SchoolTier, string[]> = {
  // 1–3 классы (Младшая школа / Algkool)
  primary: [
    'Minecraft',
    'Roblox',
    'LEGO',
    'Brawl Stars',
    'Спорт и игры',
    'Котики и собачки',
    'Динозавры',
    'Космос и ракеты',
    'Сладости и мороженое',
    'Рисование и комиксы',
    'Супергерои',
    'Головоломки',
    'Мультфильмы',
    'Магия и волшебство',
    'Самокаты и велики',
    'Покемоны',
  ],
  // 4–6 классы (Среднее звено I / Põhikool I)
  middle: [
    'Minecraft',
    'Roblox',
    'Brawl Stars',
    'Футбол',
    'Баскетбол',
    'Видеоигры',
    'Музыка и треки',
    'Мемы',
    'Скейт и трюки',
    'Гаджеты',
    'LEGO конструирование',
    'Комиксы и манга',
    'Настолки с друзьями',
    'Плавание и спорт',
    'Роботы и техника',
  ],
  // 7–9 классы (Старшее звено / Põhikool II)
  high: [
    'Футбол',
    'Баскетбол',
    'Видеоигры',
    'CS:GO / Valorant',
    'Музыка и треки',
    'Мемы и TikTok',
    'Скейт и самокаты',
    'Гаджеты и технологии',
    'Аниме и манга',
    'Кино и сериалы',
    'Блогинг и YouTube',
    'Плавание и фитнес',
    'Настолки с друзьями',
    'Графика и дизайн',
    'Мода и стиль',
  ],
  // 10–12 классы (Гимназия / Gümnaasium)
  gymnasium: [
    'IT и программирование',
    'Нейросети и AI',
    'Стартапы и бизнес',
    'Финансы и крипта',
    'Кино и сериалы',
    'Музыка и концерты',
    'Фитнес и тренировки',
    'Путешествия',
    'Психология и саморазвитие',
    'Киберспорт',
    'Наука и космос',
    'Фотография и видео',
    'Медиа и дизайн',
    'Автомобили',
    'Языки и культуры',
  ],
};

// Default selected interests per school tier (used when switching grade without custom user edits)
export const DEFAULT_INTERESTS_BY_TIER: Record<SchoolTier, string[]> = {
  primary: ['Minecraft', 'LEGO', 'Roblox'],
  middle: ['Футбол', 'Видеоигры', 'Музыка и треки'],
  high: ['Видеоигры', 'Музыка и треки', 'Гаджеты и технологии'],
  gymnasium: ['IT и программирование', 'Кино и сериалы', 'Музыка и концерты'],
};

export function getDefaultInterestsForTier(tier: SchoolTier): string[] {
  return [...(DEFAULT_INTERESTS_BY_TIER[tier] || DEFAULT_INTERESTS_BY_TIER.primary)];
}

export function getDefaultInterestsForGrade(grade: number): string[] {
  const tier = getTierFromGrade(grade);
  return getDefaultInterestsForTier(tier);
}

// Childish primary school interests that should never be automatically carried to high school / gymnasium
export const PRIMARY_CHILDISH_INTERESTS = new Set([
  'minecraft',
  'lego',
  'roblox',
  'brawl stars',
  'котики и собачки',
  'динозавры',
  'мультфильмы',
  'сладости и мороженое',
  'покемоны',
  'магия и волшебство',
]);

/**
 * Checks if a given list of interests matches any known default tier list or legacy primary defaults.
 */
export function isDefaultInterestsList(interests: string[] | undefined): boolean {
  if (!interests || interests.length === 0) return true;
  const normalized = interests.map((i) => i.trim().toLowerCase()).sort().join(',');
  for (const t of Object.keys(DEFAULT_INTERESTS_BY_TIER) as SchoolTier[]) {
    const tierDefaults = DEFAULT_INTERESTS_BY_TIER[t]
      .map((i) => i.trim().toLowerCase())
      .sort()
      .join(',');
    if (normalized === tierDefaults) return true;
  }
  // Legacy default check: ['minecraft', 'lego', 'roblox'] in any order
  const legacyPrimary = ['minecraft', 'lego', 'roblox'].sort().join(',');
  if (normalized === legacyPrimary) return true;
  return false;
}

export function getInterestsPlaceholder(tier?: SchoolTier): string {
  return 'Впиши свои увлечения вручную через запятую...';
}
