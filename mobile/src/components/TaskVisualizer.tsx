import React, { useState, useEffect, useRef } from 'react';
import {
  StyleSheet,
  View,
  Text,
  TouchableOpacity,
  Animated,
  Easing,
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
        <RenderAutoMathBlocks visual={visual} isJunior={isJunior} onAction={onAction} />
      )}
      {visual.type === 'match_pairs' && (
        <RenderAutoMatchPairs visual={visual} isJunior={isJunior} onAction={onAction} />
      )}
      {visual.type === 'step_sequence' && (
        <RenderAutoStepSequence visual={visual} isJunior={isJunior} onAction={onAction} />
      )}
      {visual.type === 'balance_scale' && (
        <RenderAutoBalanceScale visual={visual} isJunior={isJunior} onAction={onAction} />
      )}
      {visual.type === 'universal_card' && (
        <RenderAutoUniversalCard visual={visual} isJunior={isJunior} onAction={onAction} />
      )}
    </View>
  );
};

// =============================================================================
// 1. MATH BLOCKS: АВТОМАТИЧЕСКАЯ ФИЗИЧЕСКАЯ АНИМАЦИЯ ПЕРЕЛЕТА КУБИКОВ
// Демонстрация переместительного закона слагаемых: 3 + 2 <-> 2 + 3 = 5
// =============================================================================

interface MathBlocksProps {
  visual: MathBlocksVisual;
  isJunior: boolean;
  onAction?: (action: string, payload?: any) => void;
}

type SwapPhase = 'initial' | 'flying_forward' | 'swapped' | 'flying_back';

const RenderAutoMathBlocks: React.FC<MathBlocksProps> = ({ visual, isJunior, onAction }) => {
  const [phase, setPhase] = useState<SwapPhase>('initial');
  const [containerWidth, setContainerWidth] = useState<number>(SCREEN_WIDTH - 64);
  const flightAnim = useRef(new Animated.Value(0)).current;
  const timerRef = useRef<NodeJS.Timeout | null>(null);
  const isMountedRef = useRef(true);

  // Group 1: defaults to 3 blue cubes, Group 2: defaults to 2 green cubes
  const countA = visual.groups[0]?.count || 3;
  const countB = visual.groups[1]?.count || 2;
  const colorA = visual.groups[0]?.color || '#3B82F6';
  const colorB = visual.groups[1]?.color || '#10B981';
  const totalSum = visual.target_count || countA + countB;

  // The flight distance depends on available container width
  const swapDistance = Math.min(Math.max(containerWidth * 0.45, 110), 150);

  const startAnimationCycle = () => {
    if (timerRef.current) clearTimeout(timerRef.current);
    if (!isMountedRef.current) return;

    // Шаг 1: Показываем исходное состояние 1.5 секунды
    setPhase('initial');
    flightAnim.setValue(0);

    timerRef.current = setTimeout(() => {
      if (!isMountedRef.current) return;

      // Шаг 2: Кубики плавно взлетают и летят навстречу друг другу
      setPhase('flying_forward');
      Animated.timing(flightAnim, {
        toValue: 1,
        duration: 1200,
        easing: Easing.bezier(0.4, 0, 0.2, 1),
        useNativeDriver: true,
      }).start(({ finished }) => {
        if (!finished || !isMountedRef.current) return;

        // Шаг 3: Приземлились в новом порядке [ 2 зеленых ] + [ 3 синих ] = 5
        setPhase('swapped');
        if (onAction) onAction('math_swapped');

        // Шаг 4: Пауза 2.5 секунды, затем возвращение обратно в цикле
        timerRef.current = setTimeout(() => {
          if (!isMountedRef.current) return;

          setPhase('flying_back');
          Animated.timing(flightAnim, {
            toValue: 0,
            duration: 1200,
            easing: Easing.bezier(0.4, 0, 0.2, 1),
            useNativeDriver: true,
          }).start(({ finished: retFinished }) => {
            if (!retFinished || !isMountedRef.current) return;

            // Зацикливаем показ с паузой в 2 секунды
            timerRef.current = setTimeout(() => {
              startAnimationCycle();
            }, 2000);
          });
        }, 2500);
      });
    }, 1500);
  };

  useEffect(() => {
    isMountedRef.current = true;
    startAnimationCycle();

    return () => {
      isMountedRef.current = false;
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [visual, containerWidth]);

  // Interpolations for Group A (Blue cubes)
  // Flies from left to right (+swapDistance), soaring up (-42px) in an arc
  const transX_A = flightAnim.interpolate({
    inputRange: [0, 1],
    outputRange: [0, swapDistance],
  });
  const transY_A = flightAnim.interpolate({
    inputRange: [0, 0.45, 1],
    outputRange: [0, -42, 0],
  });
  const scale_A = flightAnim.interpolate({
    inputRange: [0, 0.45, 1],
    outputRange: [1, 1.15, 1],
  });
  const rotate_A = flightAnim.interpolate({
    inputRange: [0, 0.45, 1],
    outputRange: ['0deg', '5deg', '0deg'],
  });

  // Interpolations for Group B (Green cubes)
  // Flies from right to left (-swapDistance), soaring up (-48px) slightly higher
  const transX_B = flightAnim.interpolate({
    inputRange: [0, 1],
    outputRange: [0, -swapDistance],
  });
  const transY_B = flightAnim.interpolate({
    inputRange: [0, 0.55, 1],
    outputRange: [0, -48, 0],
  });
  const scale_B = flightAnim.interpolate({
    inputRange: [0, 0.55, 1],
    outputRange: [1, 1.15, 1],
  });
  const rotate_B = flightAnim.interpolate({
    inputRange: [0, 0.55, 1],
    outputRange: ['0deg', '-5deg', '0deg'],
  });

  const isSwappedState = phase === 'swapped';
  const isFlying = phase === 'flying_forward' || phase === 'flying_back';

  return (
    <View
      style={styles.cardContent}
      onLayout={(e) => {
        const w = e.nativeEvent.layout.width;
        if (w > 0 && Math.abs(w - containerWidth) > 10) {
          setContainerWidth(w);
        }
      }}
    >
      {/* Header with Title and Automatic Tag */}
      <View style={styles.autoHeaderRow}>
        <View style={styles.autoHeaderLeft}>
          <Text style={styles.autoHeaderIcon}>✨</Text>
          <Text style={[styles.autoHeaderTitle, isJunior && styles.titleJunior]}>
            {visual.title || 'Переместительный закон сложения'}
          </Text>
        </View>
        <View style={styles.autoPlayBadge}>
          <Text style={styles.autoPlayBadgeText}>АВТОМАТИЧЕСКИЙ ПОКАЗ</Text>
        </View>
      </View>

      {/* Narrative Subtitle / Stage Badge */}
      <View style={styles.stageBanner}>
        <Text style={styles.stageBannerText}>
          {phase === 'initial' && `Шаг 1: Было [ ${countA} синих ] + [ ${countB} зеленых ] = ${totalSum}`}
          {isFlying && `✈️ Меняем слагаемые местами...`}
          {isSwappedState && `Шаг 2: Стало [ ${countB} зеленых ] + [ ${countA} синих ] = ${totalSum}`}
        </Text>
      </View>

      {/* Flight Stage / Arena */}
      <View style={styles.flightArena}>
        {/* Group A (Blue cubes) */}
        <Animated.View
          style={[
            styles.cubeGroupPlate,
            {
              transform: [
                { translateX: transX_A },
                { translateY: transY_A },
                { scale: scale_A },
                { rotate: rotate_A },
              ],
              zIndex: phase === 'flying_forward' ? 5 : 10,
            },
          ]}
        >
          <View style={styles.cubesRow}>
            {Array.from({ length: countA }).map((_, i) => (
              <View key={`a_${i}`} style={[styles.glossyCube, { backgroundColor: colorA }]}>
                <View style={styles.cubePip} />
              </View>
            ))}
          </View>
          <View style={[styles.groupNumberBadge, { backgroundColor: `${colorA}30`, borderColor: colorA }]}>
            <Text style={[styles.groupNumberText, { color: '#93C5FD' }]}>
              {countA}
            </Text>
          </View>
        </Animated.View>

        {/* Math Plus Operator in center */}
        <View style={styles.centerOpCircle}>
          <Text style={styles.centerOpText}>+</Text>
        </View>

        {/* Group B (Green cubes) */}
        <Animated.View
          style={[
            styles.cubeGroupPlate,
            {
              transform: [
                { translateX: transX_B },
                { translateY: transY_B },
                { scale: scale_B },
                { rotate: rotate_B },
              ],
              zIndex: phase === 'flying_forward' ? 10 : 5,
            },
          ]}
        >
          <View style={styles.cubesRow}>
            {Array.from({ length: countB }).map((_, i) => (
              <View key={`b_${i}`} style={[styles.glossyCube, { backgroundColor: colorB }]}>
                <View style={styles.cubePip} />
              </View>
            ))}
          </View>
          <View style={[styles.groupNumberBadge, { backgroundColor: `${colorB}30`, borderColor: colorB }]}>
            <Text style={[styles.groupNumberText, { color: '#6EE7B7' }]}>
              {countB}
            </Text>
          </View>
        </Animated.View>

        {/* Equals Sign and Result */}
        <View style={styles.equalsGroup}>
          <Text style={styles.equalsSign}>=</Text>
          <View style={styles.resultBadge}>
            <Text style={styles.resultBadgeText}>{totalSum}</Text>
          </View>
        </View>
      </View>

      {/* Dynamic Equation Bar */}
      <View style={styles.equationBar}>
        <Text style={styles.equationFormula}>
          {isSwappedState ? (
            <Text>
              <Text style={{ color: '#10B981', fontWeight: '800' }}>{countB}</Text>
              {' + '}
              <Text style={{ color: '#3B82F6', fontWeight: '800' }}>{countA}</Text>
              {' = '}
              <Text style={{ color: '#5FEDC5', fontWeight: '800' }}>{totalSum}</Text>
            </Text>
          ) : (
            <Text>
              <Text style={{ color: '#3B82F6', fontWeight: '800' }}>{countA}</Text>
              {' + '}
              <Text style={{ color: '#10B981', fontWeight: '800' }}>{countB}</Text>
              {' = '}
              <Text style={{ color: '#5FEDC5', fontWeight: '800' }}>{totalSum}</Text>
            </Text>
          )}
        </Text>
      </View>

      {/* Explanatory Conclusion Footer */}
      <View style={styles.autoFooterRow}>
        <View style={styles.conclusionBox}>
          <Text style={styles.conclusionText}>
            💡 <Text style={{ fontWeight: '700', color: '#F8FAFC' }}>Правило:</Text> От перемены мест слагаемых сумма не меняется! (Summa ei muutu).
          </Text>
        </View>

        {/* Quick Replay Button */}
        <TouchableOpacity
          style={styles.replayButton}
          onPress={() => startAnimationCycle()}
          activeOpacity={0.7}
          accessibilityLabel="Повторить показ анимации"
        >
          <Text style={styles.replayButtonIcon}>↺</Text>
          <Text style={styles.replayButtonText}>Повторить показ</Text>
        </TouchableOpacity>
      </View>
    </View>
  );
};

// =============================================================================
// 2. BALANCE SCALE: АВТОМАТИЧЕСКОЕ КОЛЕБАНИЕ И НАКЛОН ЧАШ
// =============================================================================

interface BalanceScaleProps {
  visual: BalanceScaleVisual;
  isJunior: boolean;
  onAction?: (action: string, payload?: any) => void;
}

const RenderAutoBalanceScale: React.FC<BalanceScaleProps> = ({ visual, isJunior }) => {
  const tiltAnim = useRef(new Animated.Value(0)).current;

  const parseVal = (v: number | string): number => {
    if (typeof v === 'number') return v;
    const num = parseFloat(String(v).replace(',', '.'));
    return isNaN(num) ? 0 : num;
  };

  const leftNum = parseVal(visual.left_side.value);
  const rightNum = parseVal(visual.right_side.value);
  const targetDegree = leftNum > rightNum ? -8 : leftNum < rightNum ? 8 : 0;

  useEffect(() => {
    // Damped physical oscillation: tilts past target, bounces, and settles
    Animated.sequence([
      Animated.timing(tiltAnim, { toValue: targetDegree * 1.3, duration: 600, useNativeDriver: true }),
      Animated.timing(tiltAnim, { toValue: targetDegree * 0.8, duration: 400, useNativeDriver: true }),
      Animated.timing(tiltAnim, { toValue: targetDegree, duration: 300, useNativeDriver: true }),
    ]).start();
  }, [visual]);

  const rotateInterpolation = tiltAnim.interpolate({
    inputRange: [-12, 0, 12],
    outputRange: ['-12deg', '0deg', '12deg'],
  });

  return (
    <View style={styles.cardContent}>
      <View style={styles.autoHeaderRow}>
        <View style={styles.autoHeaderLeft}>
          <Text style={styles.autoHeaderIcon}>⚖️</Text>
          <Text style={[styles.autoHeaderTitle, isJunior && styles.titleJunior]}>
            {visual.title || 'Сравнение на весах'}
          </Text>
        </View>
      </View>

      <View style={styles.scaleContainer}>
        <View style={styles.scaleFulcrumTop} />
        <View style={styles.scaleFulcrumPillar} />
        <View style={styles.scaleFulcrumBase} />

        <Animated.View
          style={[
            styles.scaleBeam,
            { transform: [{ rotate: rotateInterpolation }] },
          ]}
        >
          <View style={styles.leftPanAssembly}>
            <View style={styles.scaleChain} />
            <View style={styles.panPlate}>
              <Text style={styles.panValueText}>{visual.left_side.value}</Text>
              <Text style={styles.panLabelText}>{visual.left_side.label}</Text>
            </View>
          </View>

          <View style={styles.centerPivotDot} />

          <View style={styles.rightPanAssembly}>
            <View style={styles.scaleChain} />
            <View style={styles.panPlate}>
              <Text style={styles.panValueText}>{visual.right_side.value}</Text>
              <Text style={styles.panLabelText}>{visual.right_side.label}</Text>
            </View>
          </View>
        </Animated.View>
      </View>

      <View style={styles.conclusionBox}>
        <Text style={styles.conclusionText}>
          {targetDegree === 0
            ? '⚖️ Обе чаши равны: равновесие (=)!'
            : targetDegree > 0
            ? '⚖️ Правая чаша тяжелее и опустилась вниз (<).'
            : '⚖️ Левая чаша тяжелее и опустилась вниз (>).'}
        </Text>
      </View>
    </View>
  );
};

// =============================================================================
// 3. STEP SEQUENCE: АВТОМАТИЧЕСКАЯ ПОСЛЕДОВАТЕЛЬНОСТЬ ЭТАПОВ
// =============================================================================

interface StepSequenceProps {
  visual: StepSequenceVisual;
  isJunior: boolean;
  onAction?: (action: string, payload?: any) => void;
}

const RenderAutoStepSequence: React.FC<StepSequenceProps> = ({ visual, isJunior }) => {
  const [activeStepIdx, setActiveStepIdx] = useState(0);

  useEffect(() => {
    if (!visual.steps || visual.steps.length === 0) return;
    const interval = setInterval(() => {
      setActiveStepIdx((prev) => (prev + 1) % visual.steps.length);
    }, 2000);
    return () => clearInterval(interval);
  }, [visual]);

  return (
    <View style={styles.cardContent}>
      <View style={styles.autoHeaderRow}>
        <View style={styles.autoHeaderLeft}>
          <Text style={styles.autoHeaderIcon}>🚀</Text>
          <Text style={[styles.autoHeaderTitle, isJunior && styles.titleJunior]}>
            {visual.title || 'Порядок действий'}
          </Text>
        </View>
      </View>

      <View style={styles.stepsContainer}>
        {visual.steps.map((step, idx) => {
          const isActive = idx === activeStepIdx;
          return (
            <View
              key={step.step_number}
              style={[styles.stepItemCard, isActive && styles.stepItemActive]}
            >
              <View style={[styles.stepBadge, isActive && styles.stepBadgeActive]}>
                <Text style={styles.stepBadgeText}>
                  {step.icon_or_badge || String(step.step_number)}
                </Text>
              </View>
              <View style={{ flex: 1, marginLeft: 10 }}>
                <Text style={[styles.stepTitleText, isActive && styles.stepTitleActive]}>
                  {step.title}
                </Text>
                {step.description ? (
                  <Text style={styles.stepDescText}>{step.description}</Text>
                ) : null}
              </View>
            </View>
          );
        })}
      </View>
    </View>
  );
};

// =============================================================================
// 4. MATCH PAIRS & 5. UNIVERSAL CARD
// =============================================================================

const RenderAutoMatchPairs: React.FC<{ visual: MatchPairsVisual; isJunior: boolean; onAction?: any }> = ({ visual, isJunior }) => {
  return (
    <View style={styles.cardContent}>
      <View style={styles.autoHeaderRow}>
        <View style={styles.autoHeaderLeft}>
          <Text style={styles.autoHeaderIcon}>🧩</Text>
          <Text style={[styles.autoHeaderTitle, isJunior && styles.titleJunior]}>
            {visual.title || 'Сопоставление терминов'}
          </Text>
        </View>
      </View>
      <View style={styles.pairsList}>
        {visual.pairs.map((p) => (
          <View key={p.id} style={styles.pairLinkedRow}>
            <View style={styles.pairLeftChip}>
              <Text style={styles.pairLeftText}>{p.left}</Text>
            </View>
            <Text style={styles.pairLinkArrow}>⇄</Text>
            <View style={styles.pairRightChip}>
              <Text style={styles.pairRightText}>{p.right}</Text>
            </View>
          </View>
        ))}
      </View>
    </View>
  );
};

const RenderAutoUniversalCard: React.FC<{ visual: UniversalCardVisual; isJunior: boolean; onAction?: any }> = ({ visual, isJunior }) => {
  const accentColor = visual.accent_color || '#5FEDC5';
  return (
    <View style={[styles.universalCardRoot, { borderColor: accentColor }]}>
      <View style={styles.autoHeaderRow}>
        <View style={styles.autoHeaderLeft}>
          <Text style={styles.autoHeaderIcon}>{visual.icon || '💡'}</Text>
          <Text style={[styles.autoHeaderTitle, isJunior && styles.titleJunior]}>
            {visual.title}
          </Text>
        </View>
        {visual.badge ? (
          <View style={[styles.universalBadge, { backgroundColor: accentColor }]}>
            <Text style={styles.universalBadgeText}>{visual.badge}</Text>
          </View>
        ) : null}
      </View>
      <View style={[styles.highlightBox, { borderColor: `${accentColor}60` }]}>
        <Text style={[styles.highlightText, { color: accentColor }]}>
          {visual.highlight_text}
        </Text>
      </View>
      {visual.explanation ? (
        <Text style={styles.universalExplanation}>{visual.explanation}</Text>
      ) : null}
    </View>
  );
};

// =============================================================================
// STYLES
// =============================================================================

const styles = StyleSheet.create({
  rootContainer: {
    marginVertical: 10,
    backgroundColor: '#161F30',
    overflow: 'hidden',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.3,
    shadowRadius: 10,
    elevation: 4,
  },
  rootJunior: {
    borderRadius: 20,
    borderWidth: 2,
    borderColor: '#3B82F6',
    padding: 14,
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
  autoHeaderRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 10,
  },
  autoHeaderLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    flex: 1,
  },
  autoHeaderIcon: {
    fontSize: 20,
    marginRight: 8,
  },
  autoHeaderTitle: {
    fontSize: 15,
    fontWeight: '700',
    color: '#F8FAFC',
  },
  titleJunior: {
    fontSize: 16,
    color: '#60A5FA',
  },
  autoPlayBadge: {
    backgroundColor: '#0F766E30',
    borderWidth: 1,
    borderColor: '#14B8A6',
    borderRadius: 8,
    paddingHorizontal: 8,
    paddingVertical: 3,
  },
  autoPlayBadgeText: {
    color: '#5FEDC5',
    fontSize: 9,
    fontWeight: '800',
    letterSpacing: 0.5,
  },
  stageBanner: {
    backgroundColor: '#0F172A',
    borderRadius: 10,
    paddingVertical: 6,
    paddingHorizontal: 10,
    marginBottom: 14,
    borderWidth: 1,
    borderColor: '#1E293B',
    alignItems: 'center',
  },
  stageBannerText: {
    color: '#94A3B8',
    fontSize: 12,
    fontWeight: '600',
  },

  // Flight Arena
  flightArena: {
    height: 110,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 6,
    position: 'relative',
    marginVertical: 4,
  },
  cubeGroupPlate: {
    alignItems: 'center',
    padding: 6,
    borderRadius: 14,
    backgroundColor: '#1E293B90',
    borderWidth: 1,
    borderColor: '#334155',
    minWidth: 80,
  },
  cubesRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  glossyCube: {
    width: 34,
    height: 34,
    borderRadius: 8,
    borderTopWidth: 2,
    borderTopColor: '#FFFFFF60',
    borderBottomWidth: 2,
    borderBottomColor: '#00000040',
    justifyContent: 'center',
    alignItems: 'center',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 3 },
    shadowOpacity: 0.4,
    shadowRadius: 4,
    elevation: 3,
  },
  cubePip: {
    width: 10,
    height: 10,
    borderRadius: 5,
    backgroundColor: '#FFFFFF50',
  },
  groupNumberBadge: {
    marginTop: 6,
    paddingHorizontal: 8,
    paddingVertical: 1,
    borderRadius: 6,
    borderWidth: 1,
  },
  groupNumberText: {
    fontSize: 12,
    fontWeight: '800',
  },
  centerOpCircle: {
    width: 28,
    height: 28,
    borderRadius: 14,
    backgroundColor: '#0F172A',
    borderWidth: 1.5,
    borderColor: '#475569',
    justifyContent: 'center',
    alignItems: 'center',
    marginHorizontal: 12,
    zIndex: 1,
  },
  centerOpText: {
    color: '#F8FAFC',
    fontSize: 16,
    fontWeight: '800',
  },
  equalsGroup: {
    flexDirection: 'row',
    alignItems: 'center',
    marginLeft: 10,
  },
  equalsSign: {
    color: '#94A3B8',
    fontSize: 20,
    fontWeight: '800',
    marginRight: 8,
  },
  resultBadge: {
    width: 36,
    height: 36,
    borderRadius: 10,
    backgroundColor: '#064E3B',
    borderWidth: 2,
    borderColor: '#10B981',
    justifyContent: 'center',
    alignItems: 'center',
    shadowColor: '#10B981',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.5,
    shadowRadius: 6,
  },
  resultBadgeText: {
    color: '#FFFFFF',
    fontSize: 18,
    fontWeight: '900',
  },

  // Equation Bar
  equationBar: {
    backgroundColor: '#0B0F17',
    borderRadius: 10,
    paddingVertical: 8,
    alignItems: 'center',
    marginVertical: 8,
    borderWidth: 1,
    borderColor: '#1E293B',
  },
  equationFormula: {
    fontSize: 18,
    fontWeight: '700',
    color: '#F1F5F9',
    letterSpacing: 1,
  },

  // Footer & Replay
  autoFooterRow: {
    marginTop: 6,
    gap: 8,
  },
  conclusionBox: {
    backgroundColor: '#1E293B',
    borderRadius: 10,
    padding: 10,
    borderLeftWidth: 3,
    borderLeftColor: '#5FEDC5',
  },
  conclusionText: {
    color: '#CBD5E1',
    fontSize: 12,
    lineHeight: 17,
  },
  replayButton: {
    alignSelf: 'center',
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#1E293B',
    borderWidth: 1,
    borderColor: '#475569',
    borderRadius: 12,
    paddingHorizontal: 12,
    paddingVertical: 6,
  },
  replayButtonIcon: {
    color: '#5FEDC5',
    fontSize: 14,
    fontWeight: '800',
    marginRight: 6,
  },
  replayButtonText: {
    color: '#E2E8F0',
    fontSize: 12,
    fontWeight: '600',
  },

  // Scale Styles
  scaleContainer: {
    height: 140,
    alignItems: 'center',
    justifyContent: 'center',
    marginVertical: 8,
  },
  scaleFulcrumTop: {
    width: 12,
    height: 12,
    borderRadius: 6,
    backgroundColor: '#94A3B8',
    zIndex: 10,
  },
  scaleFulcrumPillar: {
    width: 6,
    height: 50,
    backgroundColor: '#475569',
  },
  scaleFulcrumBase: {
    width: 50,
    height: 6,
    borderRadius: 3,
    backgroundColor: '#64748B',
  },
  scaleBeam: {
    position: 'absolute',
    top: 45,
    width: 250,
    height: 6,
    backgroundColor: '#CBD5E1',
    borderRadius: 3,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  centerPivotDot: {
    width: 10,
    height: 10,
    borderRadius: 5,
    backgroundColor: '#0F172A',
    borderWidth: 2,
    borderColor: '#5FEDC5',
  },
  leftPanAssembly: {
    position: 'absolute',
    left: -8,
    top: 3,
    alignItems: 'center',
  },
  rightPanAssembly: {
    position: 'absolute',
    right: -8,
    top: 3,
    alignItems: 'center',
  },
  scaleChain: {
    width: 1.5,
    height: 30,
    backgroundColor: '#94A3B8',
  },
  panPlate: {
    backgroundColor: '#1E293B',
    borderWidth: 1.5,
    borderColor: '#3B82F6',
    borderRadius: 8,
    paddingVertical: 5,
    paddingHorizontal: 8,
    alignItems: 'center',
    minWidth: 80,
  },
  panValueText: {
    color: '#F8FAFC',
    fontSize: 15,
    fontWeight: '800',
  },
  panLabelText: {
    color: '#94A3B8',
    fontSize: 10,
  },

  // Step Sequence Styles
  stepsContainer: {
    gap: 8,
    marginVertical: 4,
  },
  stepItemCard: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#1E293B',
    borderRadius: 10,
    padding: 10,
    borderWidth: 1,
    borderColor: '#334155',
  },
  stepItemActive: {
    borderColor: '#5FEDC5',
    backgroundColor: '#132E3A',
  },
  stepBadge: {
    width: 28,
    height: 28,
    borderRadius: 14,
    backgroundColor: '#334155',
    justifyContent: 'center',
    alignItems: 'center',
  },
  stepBadgeActive: {
    backgroundColor: '#0F766E',
  },
  stepBadgeText: {
    color: '#F8FAFC',
    fontSize: 12,
    fontWeight: '700',
  },
  stepTitleText: {
    color: '#E2E8F0',
    fontSize: 13,
    fontWeight: '600',
  },
  stepTitleActive: {
    color: '#5FEDC5',
    fontWeight: '700',
  },
  stepDescText: {
    color: '#94A3B8',
    fontSize: 11,
    marginTop: 2,
  },

  // Match Pairs Styles
  pairsList: {
    gap: 6,
    marginVertical: 6,
  },
  pairLinkedRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: '#1E293B',
    borderRadius: 10,
    padding: 8,
    borderWidth: 1,
    borderColor: '#334155',
  },
  pairLeftChip: {
    flex: 1,
    backgroundColor: '#1E3A8A30',
    padding: 8,
    borderRadius: 8,
  },
  pairLeftText: {
    color: '#93C5FD',
    fontSize: 13,
    fontWeight: '700',
    textAlign: 'center',
  },
  pairLinkArrow: {
    color: '#5FEDC5',
    fontSize: 16,
    marginHorizontal: 8,
    fontWeight: '700',
  },
  pairRightChip: {
    flex: 1,
    backgroundColor: '#064E3B30',
    padding: 8,
    borderRadius: 8,
  },
  pairRightText: {
    color: '#6EE7B7',
    fontSize: 13,
    fontWeight: '700',
    textAlign: 'center',
  },

  // Universal Card Styles
  universalCardRoot: {
    backgroundColor: '#1E293B',
    borderWidth: 1.5,
    borderRadius: 16,
    padding: 14,
  },
  universalBadge: {
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 6,
  },
  universalBadgeText: {
    color: '#0B0F17',
    fontSize: 10,
    fontWeight: '800',
  },
  highlightBox: {
    backgroundColor: '#0B0F1760',
    borderRadius: 10,
    borderWidth: 1,
    padding: 12,
    alignItems: 'center',
    marginVertical: 8,
  },
  highlightText: {
    fontSize: 16,
    fontWeight: '800',
    textAlign: 'center',
  },
  universalExplanation: {
    color: '#94A3B8',
    fontSize: 12,
    lineHeight: 16,
  },
});
