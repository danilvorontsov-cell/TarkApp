export type AgeTier = 'primary' | 'middle' | 'gymnasium';

export interface UserProfile {
  grade: number; // 1 - 12
  tier: AgeTier;
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
}

export interface SavedLessonCard {
  id: string;
  timestamp: number;
  dateFormatted: string;
  grade: number;
  tier: AgeTier;
  task_title: string;
  task_type?: 'Koolitöö' | 'Loodusõpetus' | 'Maailma Avastaja' | string;
  analysis: PageAnalysisResponse;
  imageUri?: string;
  imageUris?: string[];
}

export function getTierFromGrade(grade: number): AgeTier {
  if (grade >= 1 && grade <= 4) {
    return 'primary';
  }
  if (grade >= 5 && grade <= 9) {
    return 'middle';
  }
  return 'gymnasium';
}

// Popular suggested interests by age tier for quick addition
export const AGE_SUGGESTIONS: Record<AgeTier, string[]> = {
  primary: [
    'Minecraft',
    'Roblox',
    'LEGO',
    'Brawl Stars',
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
  middle: [
    'Футбол',
    'Баскетбол',
    'Видеоигры',
    'CS:GO / Valorant',
    'Minecraft / Roblox',
    'Музыка и треки',
    'Мемы и TikTok',
    'Скейт и трюки',
    'Гаджеты и технологии',
    'Аниме и манга',
    'Кино и сериалы',
    'Блогинг и YouTube',
    'Плавание и спорт',
    'Настолки с друзьями',
    'Графика и дизайн',
  ],
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
