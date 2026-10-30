import React, { useState, useEffect, useRef } from 'react';
import {
  StyleSheet,
  View,
  Text,
  TouchableOpacity,
  Animated,
  Dimensions,
} from 'react-native';
import {
  VisualData,
  MathBlocksVisual,
  MatchPairsVisual,
  StepSequenceVisual,
  BalanceScaleVisual,
  UniversalCardVisual,
} from '../types/visual';

const { width: SCREEN_WIDTH } = Dimensions.get('window');

interface TaskVisualizerProps {
  visual: VisualData | null | undefined;
  grade: number;
  onAction?: (action: string, payload?: any) => void;
}

export const TaskVisualizer: React.FC<TaskVisualizerProps> = ({ visual, grade, onAction }) => {
  // CRITICAL RULE: Grades 7–12 have visual templates STRICTLY DISABLED
  if (!visual || grade >= 7) {
    return null;
  }

  const isJunior = grade <= 4;

  return (
    <View style={[styles.rootContainer, isJunior ? styles.rootJunior : styles.rootMiddle]}>
      {visual.type === 'math_blocks' && (
        <RenderMathBlocks visual={visual} isJunior={isJunior} onAction={onAction} />
      )}
      {visual.type === 'match_pairs' && (
        <RenderMatchPairs visual={visual} isJunior={isJunior} onAction={onAction} />
      )}
      {visual.type === 'step_sequence' && (
        <RenderStepSequence visual={visual} isJunior={isJunior} onAction={onAction} />
      )}
      {visual.type === 'balance_scale' && (
        <RenderBalanceScale visual={visual} isJunior={isJunior} onAction={onAction} />
      )}
      {visual.type === 'universal_card' && (
        <RenderUniversalCard visual={visual} isJunior={isJunior} onAction={onAction} />
      )}
    </View>
  );
};

// =============================================================================
// 1. MATH BLOCKS (1–4 классы: счетные кубики / жетоны с анимацией тапа)
// =============================================================================

interface MathBlocksProps {
  visual: MathBlocksVisual;
  isJunior: boolean;
  onAction?: (action: string, payload?: any) => void;
}

const RenderMathBlocks: React.FC<MathBlocksProps> = ({ visual, isJunior, onAction }) => {
  // Keyed by groupIdx_itemIdx
  const [tappedMap, setTappedMap] = useState<Record<string, boolean>>({});
  const scalesRef = useRef<Record<string, Animated.Value>>({});

  const totalCubes = visual.groups.reduce((acc, g) => acc + g.count, 0);
  const countedCount = Object.values(tappedMap).filter(Boolean).length;

  const handleTapCube = (key: string) => {
    const isNowTapped = !tappedMap[key];
    setTappedMap((prev) => ({ ...prev, [key]: isNowTapped }));

    if (!scalesRef.current[key]) {
      scalesRef.current[key] = new Animated.Value(1);
    }
    const anim = scalesRef.current[key];
    Animated.sequence([
      Animated.timing(anim, { toValue: 1.25, duration: 90, useNativeDriver: true }),
      Animated.spring(anim, { toValue: 1, friction: 3, tension: 40, useNativeDriver: true }),
    ]).start();

    if (onAction) {
      onAction('tap_cube', { key, isNowTapped });
    }
  };

  const handleReset = () => {
    setTappedMap({});
    if (onAction) onAction('reset_math_blocks');
  };

  return (
    <View style={styles.cardContent}>
      {/* Header */}
      <View style={styles.headerRow}>
        <Text style={styles.templateIcon}>{isJunior ? '🧱' : '🔢'}</Text>
        <View style={{ flex: 1 }}>
          <Text style={[styles.templateTitle, isJunior && styles.titleJunior]}>
            {visual.title || (isJunior ? 'Считаем по кубикам' : 'Наглядный расчёт')}
          </Text>
          {visual.instruction ? (
            <Text style={styles.templateInstruction}>{visual.instruction}</Text>
          ) : null}
        </View>
        <View style={styles.counterBadge}>
          <Text style={styles.counterBadgeText}>
            {countedCount} / {totalCubes}
          </Text>
        </View>
      </View>

      {/* Groups Display */}
      <View style={styles.groupsContainer}>
        {visual.groups.map((group, gIdx) => {
          const groupColor = group.color || (gIdx === 0 ? '#3B82F6' : '#10B981');
          return (
            <View key={gIdx} style={styles.groupWrapper}>
              <View style={styles.groupLabelRow}>
                <View style={[styles.groupColorDot, { backgroundColor: groupColor }]} />
                <Text style={styles.groupLabelText}>{group.label}</Text>
                <Text style={styles.groupCountPill}>({group.count})</Text>
              </View>

              <View style={styles.cubesGrid}>
                {Array.from({ length: group.count }).map((_, cIdx) => {
                  const key = `${gIdx}_${cIdx}`;
                  if (!scalesRef.current[key]) {
                    scalesRef.current[key] = new Animated.Value(1);
                  }
                  const isTapped = Boolean(tappedMap[key]);
                  const scale = scalesRef.current[key];

                  return (
                    <TouchableOpacity
                      key={key}
                      onPress={() => handleTapCube(key)}
                      activeOpacity={0.8}
                      accessibilityLabel={`Кубик ${cIdx + 1} группы ${group.label}`}
                    >
                      <Animated.View
                        style={[
                          styles.cubeBox,
                          isJunior ? styles.cubeJunior : styles.cubeMiddle,
                          {
                            backgroundColor: isTapped ? groupColor : '#1E293B',
                            borderColor: groupColor,
                            transform: [{ scale }],
                          },
                        ]}
                      >
                        <Text style={styles.cubeSymbol}>
                          {isTapped ? '✓' : group.symbol || (isJunior ? '🟦' : '•')}
                        </Text>
                      </Animated.View>
                    </TouchableOpacity>
                  );
                })}
              </View>

              {/* Inter-group Operation Badge */}
              {gIdx < visual.groups.length - 1 && visual.operation ? (
                <View style={styles.operationDivider}>
                  <View style={styles.opCircle}>
                    <Text style={styles.opText}>{visual.operation}</Text>
                  </View>
                </View>
              ) : null}
            </View>
          );
        })}
      </View>

      {/* Footer result bar */}
      <View style={styles.blocksFooter}>
        <Text style={styles.footerResultText}>
          {countedCount === totalCubes ? (
            <Text style={{ color: '#10B981' }}>🎉 Все элементы посчитаны! Всего: {totalCubes}</Text>
          ) : (
            `Нажимай на элементы, чтобы посчитать их (${countedCount} из ${totalCubes})`
          )}
        </Text>
        {countedCount > 0 ? (
          <TouchableOpacity style={styles.resetBtn} onPress={handleReset}>
            <Text style={styles.resetBtnText}>Сбросить</Text>
          </TouchableOpacity>
        ) : null}
      </View>
    </View>
  );
};

// =============================================================================
// 2. MATCH PAIRS (1–6 классы: сопоставление терминов и понятий)
// =============================================================================

interface MatchPairsProps {
  visual: MatchPairsVisual;
  isJunior: boolean;
  onAction?: (action: string, payload?: any) => void;
}

const RenderMatchPairs: React.FC<MatchPairsProps> = ({ visual, isJunior, onAction }) => {
  const [selectedLeft, setSelectedLeft] = useState<string | null>(null);
  const [matchedIds, setMatchedIds] = useState<string[]>([]);
  const [mismatchedId, setMismatchedId] = useState<string | null>(null);

  // Deterministically shuffle the right-hand column so it is an interactive match challenge
  const [shuffledRight, setShuffledRight] = useState<Array<{ id: string; right: string }>>([]);

  useEffect(() => {
    // Stable shuffle on initial mount or visual change
    const arr = visual.pairs.map((p) => ({ id: p.id, right: p.right }));
    for (let i = arr.length - 1; i > 0; i--) {
      const j = (i * 7 + 3) % (i + 1);
      [arr[i], arr[j]] = [arr[j], arr[i]];
    }
    setShuffledRight(arr);
    setMatchedIds([]);
    setSelectedLeft(null);
  }, [visual]);

  // Shake animation for mismatch
  const shakeAnim = useRef(new Animated.Value(0)).current;

  const triggerShake = () => {
    Animated.sequence([
      Animated.timing(shakeAnim, { toValue: 10, duration: 60, useNativeDriver: true }),
      Animated.timing(shakeAnim, { toValue: -10, duration: 60, useNativeDriver: true }),
      Animated.timing(shakeAnim, { toValue: 8, duration: 60, useNativeDriver: true }),
      Animated.timing(shakeAnim, { toValue: -8, duration: 60, useNativeDriver: true }),
      Animated.timing(shakeAnim, { toValue: 0, duration: 60, useNativeDriver: true }),
    ]).start();
  };

  const handleSelectLeft = (id: string) => {
    if (matchedIds.includes(id)) return;
    setSelectedLeft(id);
    setMismatchedId(null);
  };

  const handleSelectRight = (rightId: string) => {
    if (matchedIds.includes(rightId)) return;
    if (!selectedLeft) {
      return;
    }

    if (selectedLeft === rightId) {
      // Success match!
      const nextMatched = [...matchedIds, rightId];
      setMatchedIds(nextMatched);
      setSelectedLeft(null);
      setMismatchedId(null);
      if (onAction) onAction('pair_matched', { id: rightId });
    } else {
      // Mismatch
      setMismatchedId(rightId);
      triggerShake();
      setTimeout(() => {
        setMismatchedId(null);
        setSelectedLeft(null);
      }, 700);
      if (onAction) onAction('pair_mismatch', { left: selectedLeft, right: rightId });
    }
  };

  const isAllMatched = matchedIds.length > 0 && matchedIds.length === visual.pairs.length;

  const handleResetPairs = () => {
    setMatchedIds([]);
    setSelectedLeft(null);
    setMismatchedId(null);
    if (onAction) onAction('reset_pairs');
  };

  return (
    <View style={styles.cardContent}>
      {/* Header */}
      <View style={styles.headerRow}>
        <Text style={styles.templateIcon}>{isJunior ? '🧩' : '🔗'}</Text>
        <View style={{ flex: 1 }}>
          <Text style={[styles.templateTitle, isJunior && styles.titleJunior]}>
            {visual.title || (isJunior ? 'Соедини пары понятий' : 'Сопоставление терминов')}
          </Text>
          <Text style={styles.templateInstruction}>
            {visual.instruction || 'Выбери термин слева, затем его значение справа:'}
          </Text>
        </View>
        <View style={styles.counterBadge}>
          <Text style={styles.counterBadgeText}>
            {matchedIds.length} / {visual.pairs.length}
          </Text>
        </View>
      </View>

      {/* Two columns */}
      <View style={styles.pairsColumnsRow}>
        {/* Left Column (Estonian terms) */}
        <View style={styles.pairColumn}>
          <Text style={styles.columnHeader}>EESTI KEELES</Text>
          {visual.pairs.map((p) => {
            const isMatched = matchedIds.includes(p.id);
            const isSelected = selectedLeft === p.id;
            return (
              <TouchableOpacity
                key={`left_${p.id}`}
                style={[
                  styles.pairPill,
                  isJunior ? styles.pillJunior : styles.pillMiddle,
                  isSelected && styles.pillSelected,
                  isMatched && styles.pillMatched,
                ]}
                onPress={() => handleSelectLeft(p.id)}
                disabled={isMatched}
                activeOpacity={0.7}
              >
                <Text
                  style={[
                    styles.pairPillText,
                    isSelected && styles.pairPillTextSelected,
                    isMatched && styles.pairPillTextMatched,
                  ]}
                >
                  {p.left}
                </Text>
                {isMatched ? <Text style={styles.pairCheckIcon}>✓</Text> : null}
              </TouchableOpacity>
            );
          })}
        </View>

        {/* Right Column (Russian meanings) */}
        <Animated.View
          style={[
            styles.pairColumn,
            {
              transform: [{ translateX: shakeAnim }],
            },
          ]}
        >
          <Text style={styles.columnHeader}>ПО-РУССКИ</Text>
          {shuffledRight.map((r) => {
            const isMatched = matchedIds.includes(r.id);
            const isMismatched = mismatchedId === r.id;
            return (
              <TouchableOpacity
                key={`right_${r.id}`}
                style={[
                  styles.pairPill,
                  isJunior ? styles.pillJunior : styles.pillMiddle,
                  isMatched && styles.pillMatched,
                  isMismatched && styles.pillMismatched,
                ]}
                onPress={() => handleSelectRight(r.id)}
                disabled={isMatched}
                activeOpacity={0.7}
              >
                <Text
                  style={[
                    styles.pairPillText,
                    isMatched && styles.pairPillTextMatched,
                    isMismatched && styles.pairPillTextMismatched,
                  ]}
                >
                  {r.right}
                </Text>
                {isMatched ? <Text style={styles.pairCheckIcon}>✓</Text> : null}
              </TouchableOpacity>
            );
          })}
        </Animated.View>
      </View>

      {/* Completion Banner */}
      {isAllMatched ? (
        <View style={styles.allMatchedBanner}>
          <Text style={styles.allMatchedTitle}>🎉 Отлично! Все пары найдены!</Text>
          <TouchableOpacity style={styles.resetBtn} onPress={handleResetPairs}>
            <Text style={styles.resetBtnText}>Сыграть ещё раз</Text>
          </TouchableOpacity>
        </View>
      ) : null}
    </View>
  );
};

// =============================================================================
// 3. STEP SEQUENCE (1–6 классы: алгоритмы, циклы, порядок действий)
// =============================================================================

interface StepSequenceProps {
  visual: StepSequenceVisual;
  isJunior: boolean;
  onAction?: (action: string, payload?: any) => void;
}

const RenderStepSequence: React.FC<StepSequenceProps> = ({ visual, isJunior, onAction }) => {
  const [completedSteps, setCompletedSteps] = useState<number[]>([]);

  const handleToggleStep = (stepNumber: number) => {
    const isNowDone = !completedSteps.includes(stepNumber);
    setCompletedSteps((prev) =>
      isNowDone ? [...prev, stepNumber] : prev.filter((s) => s !== stepNumber)
    );
    if (onAction) onAction('toggle_step', { stepNumber, isNowDone });
  };

  const progressPercent =
    visual.steps.length > 0 ? (completedSteps.length / visual.steps.length) * 100 : 0;

  return (
    <View style={styles.cardContent}>
      {/* Header */}
      <View style={styles.headerRow}>
        <Text style={styles.templateIcon}>{isJunior ? '🚀' : '📋'}</Text>
        <View style={{ flex: 1 }}>
          <Text style={[styles.templateTitle, isJunior && styles.titleJunior]}>
            {visual.title || (isJunior ? 'Шаги решения' : 'Последовательность этапов')}
          </Text>
          {visual.instruction ? (
            <Text style={styles.templateInstruction}>{visual.instruction}</Text>
          ) : null}
        </View>
      </View>

      {/* Progress Bar */}
      <View style={styles.progressBarTrack}>
        <View style={[styles.progressBarFill, { width: `${progressPercent}%` }]} />
      </View>

      {/* Steps List */}
      <View style={styles.stepsContainer}>
        {visual.steps.map((step, idx) => {
          const isDone = completedSteps.includes(step.step_number);
          const isLast = idx === visual.steps.length - 1;

          return (
            <View key={step.step_number} style={styles.stepRowWrapper}>
              {/* Left Timeline Indicator */}
              <View style={styles.timelineCol}>
                <TouchableOpacity
                  style={[
                    styles.stepBadge,
                    isDone && styles.stepBadgeDone,
                    step.is_highlighted && !isDone && styles.stepBadgeHighlighted,
                  ]}
                  onPress={() => handleToggleStep(step.step_number)}
                  activeOpacity={0.8}
                >
                  <Text style={styles.stepBadgeText}>
                    {isDone ? '✓' : step.icon_or_badge || String(step.step_number)}
                  </Text>
                </TouchableOpacity>
                {!isLast && (
                  <View style={[styles.timelineLine, isDone && styles.timelineLineDone]} />
                )}
              </View>

              {/* Step Card Content */}
              <TouchableOpacity
                style={[
                  styles.stepCard,
                  isJunior ? styles.stepCardJunior : styles.stepCardMiddle,
                  isDone && styles.stepCardDone,
                  step.is_highlighted && !isDone && styles.stepCardHighlighted,
                ]}
                onPress={() => handleToggleStep(step.step_number)}
                activeOpacity={0.8}
              >
                <View style={styles.stepCardHeader}>
                  <Text style={[styles.stepTitleText, isDone && styles.stepTitleDone]}>
                    {step.title}
                  </Text>
                  <Text style={styles.stepCheckboxIcon}>{isDone ? '✅' : '⚪️'}</Text>
                </View>
                {step.description ? (
                  <Text style={[styles.stepDescText, isDone && styles.stepDescDone]}>
                    {step.description}
                  </Text>
                ) : null}
              </TouchableOpacity>
            </View>
          );
        })}
      </View>
    </View>
  );
};

// =============================================================================
// 4. BALANCE SCALE (1–5 классы: наглядные весы для сравнения величин)
// =============================================================================

interface BalanceScaleProps {
  visual: BalanceScaleVisual;
  isJunior: boolean;
  onAction?: (action: string, payload?: any) => void;
}

const RenderBalanceScale: React.FC<BalanceScaleProps> = ({ visual, isJunior, onAction }) => {
  const [userGuess, setUserGuess] = useState<'<' | '>' | '=' | null>(null);

  // Parse numerical or string value to compare
  const parseVal = (v: number | string): number => {
    if (typeof v === 'number') return v;
    const num = parseFloat(String(v).replace(',', '.'));
    return isNaN(num) ? 0 : num;
  };

  const leftNum = parseVal(visual.left_side.value);
  const rightNum = parseVal(visual.right_side.value);

  // Compute true comparison
  const trueComp: '<' | '>' | '=' =
    leftNum > rightNum ? '>' : leftNum < rightNum ? '<' : '=';

  const activeComp = visual.comparison === '?' ? userGuess || '?' : visual.comparison;

  // Animated beam tilt angle
  const tiltAnim = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    let targetDegree = 0;
    if (activeComp === '>') {
      // Left heavier -> tilts down on left (-8 deg)
      targetDegree = -8;
    } else if (activeComp === '<') {
      // Right heavier -> tilts down on right (+8 deg)
      targetDegree = 8;
    } else if (activeComp === '=') {
      targetDegree = 0;
    }

    Animated.spring(tiltAnim, {
      toValue: targetDegree,
      friction: 5,
      tension: 40,
      useNativeDriver: true,
    }).start();
  }, [activeComp]);

  const rotateInterpolation = tiltAnim.interpolate({
    inputRange: [-10, 0, 10],
    outputRange: ['-10deg', '0deg', '10deg'],
  });

  const handleGuess = (guess: '<' | '>' | '=') => {
    setUserGuess(guess);
    if (onAction) onAction('balance_guess', { guess, isCorrect: guess === trueComp });
  };

  const isGuessMode = visual.comparison === '?';
  const isCorrect = userGuess !== null && userGuess === trueComp;

  return (
    <View style={styles.cardContent}>
      {/* Header */}
      <View style={styles.headerRow}>
        <Text style={styles.templateIcon}>⚖️</Text>
        <View style={{ flex: 1 }}>
          <Text style={[styles.templateTitle, isJunior && styles.titleJunior]}>
            {visual.title || (isJunior ? 'Интерактивные весы' : 'Сравнение на весах')}
          </Text>
          <Text style={styles.templateInstruction}>
            {visual.instruction ||
              (isGuessMode
                ? 'Какая чаша перевесит? Нажми знак для проверки:'
                : 'Сравни левую и правую чашу весов:')}
          </Text>
        </View>
      </View>

      {/* Visual Balance Scale Graphic */}
      <View style={styles.scaleContainer}>
        {/* Central Stand Fulcrum */}
        <View style={styles.scaleFulcrumTop} />
        <View style={styles.scaleFulcrumPillar} />
        <View style={styles.scaleFulcrumBase} />

        {/* Animated Beam with suspended pans */}
        <Animated.View
          style={[
            styles.scaleBeam,
            {
              transform: [{ rotate: rotateInterpolation }],
            },
          ]}
        >
          {/* Left Pan */}
          <View style={styles.leftPanAssembly}>
            <View style={styles.scaleChain} />
            <View style={[styles.panPlate, isJunior ? styles.panJunior : styles.panMiddle]}>
              <Text style={styles.panValueText}>{visual.left_side.value}</Text>
              <Text style={styles.panLabelText}>{visual.left_side.label}</Text>
            </View>
          </View>

          {/* Center Pivot Indicator */}
          <View style={styles.centerPivotDot} />

          {/* Right Pan */}
          <View style={styles.rightPanAssembly}>
            <View style={styles.scaleChain} />
            <View style={[styles.panPlate, isJunior ? styles.panJunior : styles.panMiddle]}>
              <Text style={styles.panValueText}>{visual.right_side.value}</Text>
              <Text style={styles.panLabelText}>{visual.right_side.label}</Text>
            </View>
          </View>
        </Animated.View>
      </View>

      {/* Comparison Buttons / Result Bar */}
      {isGuessMode ? (
        <View style={styles.guessButtonsRow}>
          <TouchableOpacity
            style={[
              styles.guessBtn,
              userGuess === '<' && (isCorrect ? styles.guessBtnCorrect : styles.guessBtnSelected),
            ]}
            onPress={() => handleGuess('<')}
            activeOpacity={0.8}
          >
            <Text style={styles.guessBtnText}>&lt;</Text>
            <Text style={styles.guessBtnSub}>Правая тяжелее</Text>
          </TouchableOpacity>

          <TouchableOpacity
            style={[
              styles.guessBtn,
              userGuess === '=' && (isCorrect ? styles.guessBtnCorrect : styles.guessBtnSelected),
            ]}
            onPress={() => handleGuess('=')}
            activeOpacity={0.8}
          >
            <Text style={styles.guessBtnText}>=</Text>
            <Text style={styles.guessBtnSub}>Равновесие</Text>
          </TouchableOpacity>

          <TouchableOpacity
            style={[
              styles.guessBtn,
              userGuess === '>' && (isCorrect ? styles.guessBtnCorrect : styles.guessBtnSelected),
            ]}
            onPress={() => handleGuess('>')}
            activeOpacity={0.8}
          >
            <Text style={styles.guessBtnText}>&gt;</Text>
            <Text style={styles.guessBtnSub}>Левая тяжелее</Text>
          </TouchableOpacity>
        </View>
      ) : (
        <View style={styles.scaleResultBanner}>
          <Text style={styles.scaleResultSymbol}>{activeComp}</Text>
          <Text style={styles.scaleResultExplanation}>
            {visual.hint ||
              (activeComp === '='
                ? 'Обе чаши равны — идеальный баланс!'
                : activeComp === '>'
                ? 'Левая сторона больше, поэтому она перевесила.'
                : 'Правая сторона больше, поэтому она перевесила.')}
          </Text>
        </View>
      )}

      {userGuess !== null ? (
        <View style={styles.feedbackBox}>
          <Text style={styles.feedbackText}>
            {isCorrect
              ? '🎉 Точно! Ты правильно определил соотношение!'
              : 'Попробуй еще раз: обрати внимание на величины на чашах.'}
          </Text>
        </View>
      ) : null}
    </View>
  );
};

// =============================================================================
// 5. UNIVERSAL CARD (1–6 классы: фокусная карточка с правилом или акцентом)
// =============================================================================

interface UniversalCardProps {
  visual: UniversalCardVisual;
  isJunior: boolean;
  onAction?: (action: string, payload?: any) => void;
}

const RenderUniversalCard: React.FC<UniversalCardProps> = ({ visual, isJunior, onAction }) => {
  const scaleAnim = useRef(new Animated.Value(1)).current;

  const handleTapCard = () => {
    Animated.sequence([
      Animated.timing(scaleAnim, { toValue: 1.03, duration: 120, useNativeDriver: true }),
      Animated.spring(scaleAnim, { toValue: 1, friction: 4, useNativeDriver: true }),
    ]).start();
    if (onAction) onAction('tap_universal_card', { title: visual.title });
  };

  const accentColor = visual.accent_color || '#5FEDC5';

  return (
    <TouchableOpacity activeOpacity={0.9} onPress={handleTapCard}>
      <Animated.View
        style={[
          styles.universalCardRoot,
          isJunior ? styles.universalJunior : styles.universalMiddle,
          {
            borderColor: accentColor,
            transform: [{ scale: scaleAnim }],
          },
        ]}
      >
        <View style={styles.universalHeaderRow}>
          <View style={[styles.universalIconCircle, { backgroundColor: `${accentColor}25` }]}>
            <Text style={styles.universalIcon}>{visual.icon || '💡'}</Text>
          </View>
          <View style={{ flex: 1, marginLeft: 12 }}>
            {visual.badge ? (
              <View style={[styles.universalBadge, { backgroundColor: accentColor }]}>
                <Text style={styles.universalBadgeText}>{visual.badge}</Text>
              </View>
            ) : null}
            <Text style={[styles.universalTitle, isJunior && styles.titleJunior]}>
              {visual.title}
            </Text>
          </View>
        </View>

        {/* Focal Highlight Text Box */}
        <View style={[styles.highlightBox, { borderColor: `${accentColor}60` }]}>
          <Text style={[styles.highlightText, { color: accentColor }]}>
            {visual.highlight_text}
          </Text>
        </View>

        {visual.explanation ? (
          <Text style={styles.universalExplanation}>{visual.explanation}</Text>
        ) : null}
      </Animated.View>
    </TouchableOpacity>
  );
};

// =============================================================================
// STYLES
// =============================================================================

const styles = StyleSheet.create({
  rootContainer: {
    marginVertical: 12,
    backgroundColor: '#161F30',
    overflow: 'hidden',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.25,
    shadowRadius: 8,
    elevation: 4,
  },
  rootJunior: {
    borderRadius: 22,
    borderWidth: 2,
    borderColor: '#3B82F6',
    padding: 16,
  },
  rootMiddle: {
    borderRadius: 14,
    borderWidth: 1.5,
    borderColor: '#2A354D',
    padding: 12,
  },
  cardContent: {
    width: '100%',
  },
  headerRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 14,
  },
  templateIcon: {
    fontSize: 28,
    marginRight: 10,
  },
  templateTitle: {
    fontSize: 16,
    fontWeight: '700',
    color: '#F8FAFC',
  },
  titleJunior: {
    fontSize: 18,
    color: '#60A5FA',
  },
  templateInstruction: {
    fontSize: 13,
    color: '#94A3B8',
    marginTop: 2,
  },
  counterBadge: {
    backgroundColor: '#1E293B',
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#334155',
  },
  counterBadgeText: {
    color: '#5FEDC5',
    fontWeight: '700',
    fontSize: 13,
  },

  // Math Blocks Styles
  groupsContainer: {
    marginVertical: 8,
  },
  groupWrapper: {
    marginBottom: 12,
  },
  groupLabelRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 8,
  },
  groupColorDot: {
    width: 10,
    height: 10,
    borderRadius: 5,
    marginRight: 6,
  },
  groupLabelText: {
    color: '#E2E8F0',
    fontSize: 14,
    fontWeight: '600',
  },
  groupCountPill: {
    color: '#94A3B8',
    fontSize: 12,
    marginLeft: 6,
  },
  cubesGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  cubeBox: {
    justifyContent: 'center',
    alignItems: 'center',
  },
  cubeJunior: {
    width: 44,
    height: 44,
    borderRadius: 12,
    borderWidth: 2,
  },
  cubeMiddle: {
    width: 36,
    height: 36,
    borderRadius: 8,
    borderWidth: 1.5,
  },
  cubeSymbol: {
    color: '#FFFFFF',
    fontWeight: '700',
    fontSize: 16,
  },
  operationDivider: {
    alignItems: 'center',
    marginVertical: 6,
  },
  opCircle: {
    width: 28,
    height: 28,
    borderRadius: 14,
    backgroundColor: '#1E293B',
    borderWidth: 1,
    borderColor: '#475569',
    justifyContent: 'center',
    alignItems: 'center',
  },
  opText: {
    color: '#5FEDC5',
    fontSize: 16,
    fontWeight: '700',
  },
  blocksFooter: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginTop: 10,
    paddingTop: 10,
    borderTopWidth: 1,
    borderTopColor: '#1E293B',
  },
  footerResultText: {
    fontSize: 13,
    color: '#94A3B8',
    flex: 1,
  },
  resetBtn: {
    backgroundColor: '#334155',
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 10,
    marginLeft: 8,
  },
  resetBtnText: {
    color: '#F8FAFC',
    fontSize: 12,
    fontWeight: '600',
  },

  // Match Pairs Styles
  pairsColumnsRow: {
    flexDirection: 'row',
    gap: 12,
  },
  pairColumn: {
    flex: 1,
  },
  columnHeader: {
    fontSize: 11,
    fontWeight: '700',
    color: '#64748B',
    marginBottom: 8,
    letterSpacing: 0.5,
  },
  pairPill: {
    backgroundColor: '#1E293B',
    borderWidth: 1.5,
    borderColor: '#334155',
    marginBottom: 8,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  pillJunior: {
    paddingVertical: 12,
    paddingHorizontal: 14,
    borderRadius: 16,
  },
  pillMiddle: {
    paddingVertical: 9,
    paddingHorizontal: 11,
    borderRadius: 10,
  },
  pillSelected: {
    borderColor: '#60A5FA',
    backgroundColor: '#1E3A8A40',
  },
  pillMatched: {
    borderColor: '#10B981',
    backgroundColor: '#064E3B40',
    opacity: 0.85,
  },
  pillMismatched: {
    borderColor: '#EF4444',
    backgroundColor: '#7F1D1D40',
  },
  pairPillText: {
    color: '#E2E8F0',
    fontSize: 14,
    fontWeight: '600',
    flex: 1,
  },
  pairPillTextSelected: {
    color: '#93C5FD',
  },
  pairPillTextMatched: {
    color: '#6EE7B7',
    textDecorationLine: 'line-through',
  },
  pairPillTextMismatched: {
    color: '#FCA5A5',
  },
  pairCheckIcon: {
    color: '#10B981',
    fontSize: 14,
    fontWeight: '700',
    marginLeft: 6,
  },
  allMatchedBanner: {
    marginTop: 12,
    backgroundColor: '#064E3B40',
    borderWidth: 1.5,
    borderColor: '#10B981',
    borderRadius: 14,
    padding: 12,
    alignItems: 'center',
    flexDirection: 'row',
    justifyContent: 'space-between',
  },
  allMatchedTitle: {
    color: '#6EE7B7',
    fontWeight: '700',
    fontSize: 14,
  },

  // Step Sequence Styles
  progressBarTrack: {
    height: 4,
    backgroundColor: '#1E293B',
    borderRadius: 2,
    marginBottom: 14,
    overflow: 'hidden',
  },
  progressBarFill: {
    height: '100%',
    backgroundColor: '#5FEDC5',
  },
  stepsContainer: {
    marginTop: 4,
  },
  stepRowWrapper: {
    flexDirection: 'row',
    marginBottom: 10,
  },
  timelineCol: {
    alignItems: 'center',
    width: 36,
    marginRight: 10,
  },
  stepBadge: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: '#1E293B',
    borderWidth: 1.5,
    borderColor: '#475569',
    justifyContent: 'center',
    alignItems: 'center',
    zIndex: 2,
  },
  stepBadgeHighlighted: {
    borderColor: '#5FEDC5',
    backgroundColor: '#0F766E40',
  },
  stepBadgeDone: {
    borderColor: '#10B981',
    backgroundColor: '#10B981',
  },
  stepBadgeText: {
    color: '#F8FAFC',
    fontSize: 13,
    fontWeight: '700',
  },
  timelineLine: {
    flex: 1,
    width: 2,
    backgroundColor: '#334155',
    marginVertical: 4,
  },
  timelineLineDone: {
    backgroundColor: '#10B981',
  },
  stepCard: {
    flex: 1,
    backgroundColor: '#1E293B',
    borderWidth: 1,
    borderColor: '#334155',
  },
  stepCardJunior: {
    borderRadius: 16,
    padding: 12,
  },
  stepCardMiddle: {
    borderRadius: 10,
    padding: 10,
  },
  stepCardHighlighted: {
    borderColor: '#5FEDC5',
    backgroundColor: '#132E3A',
  },
  stepCardDone: {
    borderColor: '#065F46',
    backgroundColor: '#064E3B20',
  },
  stepCardHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  stepTitleText: {
    fontSize: 14,
    fontWeight: '700',
    color: '#F1F5F9',
    flex: 1,
  },
  stepTitleDone: {
    color: '#94A3B8',
    textDecorationLine: 'line-through',
  },
  stepCheckboxIcon: {
    fontSize: 14,
    marginLeft: 6,
  },
  stepDescText: {
    fontSize: 12,
    color: '#94A3B8',
    marginTop: 4,
    lineHeight: 17,
  },
  stepDescDone: {
    color: '#64748B',
  },

  // Balance Scale Styles
  scaleContainer: {
    height: 160,
    alignItems: 'center',
    justifyContent: 'center',
    marginVertical: 10,
  },
  scaleFulcrumTop: {
    width: 14,
    height: 14,
    borderRadius: 7,
    backgroundColor: '#94A3B8',
    zIndex: 10,
  },
  scaleFulcrumPillar: {
    width: 6,
    height: 60,
    backgroundColor: '#475569',
  },
  scaleFulcrumBase: {
    width: 60,
    height: 8,
    borderRadius: 4,
    backgroundColor: '#64748B',
  },
  scaleBeam: {
    position: 'absolute',
    top: 50,
    width: SCREEN_WIDTH > 400 ? 300 : 260,
    height: 8,
    backgroundColor: '#CBD5E1',
    borderRadius: 4,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  centerPivotDot: {
    width: 12,
    height: 12,
    borderRadius: 6,
    backgroundColor: '#0F172A',
    borderWidth: 2,
    borderColor: '#5FEDC5',
  },
  leftPanAssembly: {
    position: 'absolute',
    left: -10,
    top: 4,
    alignItems: 'center',
  },
  rightPanAssembly: {
    position: 'absolute',
    right: -10,
    top: 4,
    alignItems: 'center',
  },
  scaleChain: {
    width: 2,
    height: 35,
    backgroundColor: '#94A3B8',
  },
  panPlate: {
    backgroundColor: '#1E293B',
    borderWidth: 1.5,
    borderColor: '#3B82F6',
    alignItems: 'center',
    minWidth: 90,
  },
  panJunior: {
    borderRadius: 14,
    paddingVertical: 8,
    paddingHorizontal: 10,
  },
  panMiddle: {
    borderRadius: 8,
    paddingVertical: 6,
    paddingHorizontal: 8,
  },
  panValueText: {
    color: '#F8FAFC',
    fontSize: 16,
    fontWeight: '800',
  },
  panLabelText: {
    color: '#94A3B8',
    fontSize: 11,
    marginTop: 2,
  },
  guessButtonsRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    gap: 8,
    marginTop: 10,
  },
  guessBtn: {
    flex: 1,
    backgroundColor: '#1E293B',
    borderWidth: 1.5,
    borderColor: '#334155',
    borderRadius: 12,
    paddingVertical: 10,
    alignItems: 'center',
  },
  guessBtnSelected: {
    borderColor: '#3B82F6',
    backgroundColor: '#1E3A8A30',
  },
  guessBtnCorrect: {
    borderColor: '#10B981',
    backgroundColor: '#064E3B40',
  },
  guessBtnText: {
    color: '#F8FAFC',
    fontSize: 18,
    fontWeight: '800',
  },
  guessBtnSub: {
    color: '#94A3B8',
    fontSize: 10,
    marginTop: 2,
  },
  scaleResultBanner: {
    marginTop: 12,
    backgroundColor: '#1E293B',
    borderRadius: 12,
    padding: 12,
    flexDirection: 'row',
    alignItems: 'center',
  },
  scaleResultSymbol: {
    color: '#5FEDC5',
    fontSize: 22,
    fontWeight: '800',
    marginRight: 10,
  },
  scaleResultExplanation: {
    color: '#E2E8F0',
    fontSize: 13,
    flex: 1,
  },
  feedbackBox: {
    marginTop: 10,
    padding: 8,
    borderRadius: 10,
    backgroundColor: '#064E3B30',
    alignItems: 'center',
  },
  feedbackText: {
    color: '#6EE7B7',
    fontSize: 13,
    fontWeight: '600',
  },

  // Universal Card Styles
  universalCardRoot: {
    backgroundColor: '#1E293B',
    borderWidth: 2,
  },
  universalJunior: {
    borderRadius: 20,
    padding: 16,
  },
  universalMiddle: {
    borderRadius: 14,
    padding: 14,
  },
  universalHeaderRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 12,
  },
  universalIconCircle: {
    width: 44,
    height: 44,
    borderRadius: 22,
    justifyContent: 'center',
    alignItems: 'center',
  },
  universalIcon: {
    fontSize: 24,
  },
  universalBadge: {
    alignSelf: 'flex-start',
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 6,
    marginBottom: 4,
  },
  universalBadgeText: {
    color: '#0B0F17',
    fontSize: 10,
    fontWeight: '800',
    letterSpacing: 0.5,
  },
  universalTitle: {
    color: '#F8FAFC',
    fontSize: 15,
    fontWeight: '700',
  },
  highlightBox: {
    backgroundColor: '#0B0F1760',
    borderRadius: 12,
    borderWidth: 1,
    padding: 14,
    alignItems: 'center',
    marginVertical: 8,
  },
  highlightText: {
    fontSize: 18,
    fontWeight: '800',
    textAlign: 'center',
    letterSpacing: 0.5,
  },
  universalExplanation: {
    color: '#94A3B8',
    fontSize: 13,
    lineHeight: 18,
    marginTop: 4,
  },
});
