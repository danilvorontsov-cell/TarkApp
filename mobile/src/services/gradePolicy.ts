export type SchoolTier = 'primary' | 'middle' | 'high' | 'gymnasium';
export type AgeTier = SchoolTier;

export interface TierConfig {
  name: string;
  grades: number[];
  fullAudioEnabled: boolean;       // Озвучивать ли длинные подсказки и суть урока
  vocabAudioEnabled: boolean;      // Озвучивать ли эстонские термины
  sentenceFrameEnabled: boolean;   // Показывать ли игровой тренажер 'Собери ответ'
  explanationStyle: 'playful' | 'structured' | 'academic';
}

export const TIER_POLICIES: Record<SchoolTier, TierConfig> = {
  // 1–3 классы (Младшая школа / Algkool)
  primary: {
    name: 'Младшие классы (1–3)',
    grades: [1, 2, 3],
    fullAudioEnabled: true,
    vocabAudioEnabled: true,
    sentenceFrameEnabled: true,
    explanationStyle: 'playful',
  },
  // 4–6 классы (Среднее звено I / Põhikool I)
  middle: {
    name: 'Средние классы (4–6)',
    grades: [4, 5, 6],
    fullAudioEnabled: true,
    vocabAudioEnabled: true,
    sentenceFrameEnabled: true,
    explanationStyle: 'structured',
  },
  // 7–9 классы (Старшее звено / Põhikool II)
  high: {
    name: 'Старшие классы (7–9)',
    grades: [7, 8, 9],
    fullAudioEnabled: false,        // ОТКЛЮЧЕНО: длинные русские тексты не озвучиваются
    vocabAudioEnabled: true,        // Только точечные эстонские слова
    sentenceFrameEnabled: true,
    explanationStyle: 'structured',
  },
  // 10–12 классы (Гимназия / Gümnaasium)
  gymnasium: {
    name: 'Гимназия (10–12)',
    grades: [10, 11, 12],
    fullAudioEnabled: false,        // ОТКЛЮЧЕНО
    vocabAudioEnabled: true,        // Только клик по эстонскому словарю
    sentenceFrameEnabled: false,    // Каркас 'Собери фразу' заменяется на академический образец ответа
    explanationStyle: 'academic',
  },
};

export function getTierFromGrade(grade: number): SchoolTier {
  if (grade >= 1 && grade <= 3) {
    return 'primary';
  }
  if (grade >= 4 && grade <= 6) {
    return 'middle';
  }
  if (grade >= 7 && grade <= 9) {
    return 'high';
  }
  return 'gymnasium';
}

export function getTierPolicy(tierOrGrade: SchoolTier | number): TierConfig {
  if (typeof tierOrGrade === 'number') {
    const tier = getTierFromGrade(tierOrGrade);
    return TIER_POLICIES[tier] || TIER_POLICIES.middle;
  }
  return TIER_POLICIES[tierOrGrade] || TIER_POLICIES.middle;
}
