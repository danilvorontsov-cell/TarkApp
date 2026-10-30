/**
 * TarkApp Interactive Visual Templates (UI-primitives)
 * 
 * Target age groups:
 * - Grades 1–4: Junior style (vibrant colors, playful tokens, tactile feedback)
 * - Grades 5–6: Middle school I style (clean infographic, compact cards, sleek badges)
 * - Grades 7+: Strictly disabled (visual is null, returns null)
 */

export interface MathBlockGroup {
  label: string;
  count: number;
  color?: string;
  item_label?: string;
  symbol?: string;
}

export interface MathBlocksVisual {
  type: 'math_blocks';
  title?: string;
  instruction?: string;
  groups: MathBlockGroup[];
  operation?: '+' | '-' | '*' | '/' | '=' | string;
  target_count?: number;
}

export interface MatchPairItem {
  id: string;
  left: string;
  right: string;
  hint?: string;
}

export interface MatchPairsVisual {
  type: 'match_pairs';
  title?: string;
  instruction?: string;
  pairs: MatchPairItem[];
}

export interface StepSequenceItem {
  step_number: number;
  title: string;
  description?: string;
  icon_or_badge?: string;
  is_highlighted?: boolean;
}

export interface StepSequenceVisual {
  type: 'step_sequence';
  title?: string;
  instruction?: string;
  steps: StepSequenceItem[];
}

export interface BalanceScaleItem {
  label: string;
  count: number;
  color?: string;
}

export interface BalanceScaleSide {
  label: string;
  value: number | string;
  items?: BalanceScaleItem[];
}

export interface BalanceScaleVisual {
  type: 'balance_scale';
  title?: string;
  instruction?: string;
  left_side: BalanceScaleSide;
  right_side: BalanceScaleSide;
  comparison: '<' | '>' | '=' | '?';
  hint?: string;
}

export interface UniversalCardVisual {
  type: 'universal_card';
  title: string;
  icon: string;
  badge?: string;
  highlight_text: string;
  explanation?: string;
  accent_color?: string;
}

export type VisualData =
  | MathBlocksVisual
  | MatchPairsVisual
  | StepSequenceVisual
  | BalanceScaleVisual
  | UniversalCardVisual;
