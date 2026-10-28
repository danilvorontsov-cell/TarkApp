export {
  SchoolTier,
  AgeTier,
  TierConfig,
  TIER_POLICIES,
  getTierFromGrade,
  getTierPolicy,
} from '../services/gradePolicy';
import { SchoolTier } from '../services/gradePolicy';

export interface UserProfile {
  grade: number; // 1 - 12
  tier: SchoolTier;
  interests: string[]; // Free-form list of student's hobbies and interests
  nickname: string;
  avatarUri?: string;
}

export interface VocabularyItem {
  est: string;
  ru: string;
  example: string;
}

export interface WorkedExample {
  title: string;
  given: string;
  steps: string[];
  note?: string;
}

export interface PageAnalysisResponse {
  task_title: string;
  theme_explanation: string;
  alternative_explanation?: string;
  vocabulary: VocabularyItem[];
  worked_example?: WorkedExample;
  how_to_answer: string;
  answer_template: string;
  voice_prompt_script: string;
  is_acceptable?: boolean;
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
