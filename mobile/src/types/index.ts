export type AgeTier = 'primary' | 'middle' | 'gymnasium';

export interface UserProfile {
  grade: number; // 1 - 12
  tier: AgeTier;
  interests: string[]; // Free-form list of student's hobbies and interests
  nickname: string;
}

export interface VocabularyItem {
  est: string;
  ru: string;
  example: string;
}

export interface PageAnalysisResponse {
  task_title: string;
  theme_explanation: string;
  vocabulary: VocabularyItem[];
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
  primary: ['Minecraft', 'Roblox', 'Brawl Stars', 'LEGO', 'Животные', 'Сладости'],
  middle: ['Футбол', 'Видеоигры', 'Музыка', 'Скейт', 'Мемы', 'Гаджеты'],
  gymnasium: ['IT и код', 'Сериалы', 'Стартапы', 'Фитнес', 'Путешествия', 'Кино'],
};
