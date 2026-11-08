import React, { useCallback } from 'react';
import {
  StyleSheet,
  View,
  Text,
  TouchableOpacity,
  ActivityIndicator,
  FlatList,
  Platform,
} from 'react-native';
import * as Clipboard from 'expo-clipboard';
import { Theme } from '../theme/colors';
import { ThemedAlert } from './ThemedAlert';

export interface StepItemData {
  stepNumber: number;
  text: string;
  audioId?: string;
}

export interface StepCardProps {
  stepNumber: number;
  text: string;
  speechText?: string;
  audioId?: string;
  isPlaying?: boolean;
  isLoadingAudio?: boolean;
  onPlayAudio?: (text: string, id: string, speech_text?: string) => void;
  onCopyFormula?: (formula: string) => void;
  isFormula?: boolean;
  showCopy?: boolean;
}

function hasMathFormula(text: string): boolean {
  if (!text) return false;
  return (
    /[=+\-×÷*/^√≤≥≈]/.test(text) ||
    /\\(frac|sqrt|cdot|times|pm)/.test(text) ||
    /\d+\s*[+\-×÷*/=]\s*\d+/.test(text)
  );
}

function areStepPropsEqual(prev: StepCardProps, next: StepCardProps): boolean {
  return (
    prev.stepNumber === next.stepNumber &&
    prev.text === next.text &&
    prev.speechText === next.speechText &&
    prev.audioId === next.audioId &&
    prev.isPlaying === next.isPlaying &&
    prev.isLoadingAudio === next.isLoadingAudio &&
    prev.isFormula === next.isFormula &&
    prev.showCopy === next.showCopy
  );
}

/**
 * Heavy Step Card wrapped in React.memo with custom prop comparison.
 * Eliminates parasitic re-renders of all sibling cards when only one step changes audio state.
 */
export const StepCard = React.memo<StepCardProps>(
  ({
    stepNumber,
    text,
    speechText,
    audioId,
    isPlaying = false,
    isLoadingAudio = false,
    onPlayAudio,
    onCopyFormula,
    isFormula,
    showCopy = true,
  }) => {
    const isMath = isFormula !== undefined ? isFormula : hasMathFormula(text);
    const canCopy = Boolean(showCopy && onCopyFormula && isMath);

    const handleCopy = useCallback(async () => {
      try {
        if (onCopyFormula) {
          onCopyFormula(text);
        } else {
          await Clipboard.setStringAsync(text);
          ThemedAlert.alert('Формула скопирована', text);
        }
      } catch (err) {
        console.warn('Clipboard copy error:', err);
      }
    }, [text, onCopyFormula]);

    const handlePlay = useCallback(() => {
      if (onPlayAudio && audioId) {
        onPlayAudio(text, audioId, speechText || text);
      }
    }, [text, speechText, audioId, onPlayAudio]);

    return (
      <View style={styles.stepRow}>
        <View style={styles.stepNumberBadge}>
          <Text style={styles.stepNumberText}>{stepNumber}</Text>
        </View>

        <View style={styles.stepContentCol}>
          <Text style={styles.stepText}>{text}</Text>

          {(canCopy || Boolean(audioId && onPlayAudio)) && (
            <View style={styles.stepActionsRow}>
              {canCopy && (
                <TouchableOpacity
                  style={styles.actionPill}
                  onPress={handleCopy}
                  activeOpacity={0.7}
                  accessibilityLabel="Скопировать формулу или шаг"
                >
                  <Text style={styles.actionPillText}>📋 Копировать</Text>
                </TouchableOpacity>
              )}

              {audioId && onPlayAudio && (
                <TouchableOpacity
                  style={[
                    styles.audioPill,
                    isPlaying && styles.audioPillActive,
                  ]}
                  onPress={handlePlay}
                  activeOpacity={0.7}
                  accessibilityLabel="Озвучить шаг"
                >
                  {isLoadingAudio ? (
                    <ActivityIndicator size="small" color="#FFFFFF" style={{ marginRight: 4 }} />
                  ) : (
                    <Text style={styles.audioPillText}>
                      {isPlaying ? '⏸ Пауза' : '▶ Звук'}
                    </Text>
                  )}
                </TouchableOpacity>
              )}
            </View>
          )}
        </View>
      </View>
    );
  },
  areStepPropsEqual
);

export type StepData = string | { text: string; speech_text?: string };

export interface LessonStepListProps {
  steps: StepData[];
  activePlayingId?: string | null;
  loadingAudioId?: string | null;
  audioPrefix?: string;
  onPlayAudio?: (text: string, id: string, speech_text?: string) => void;
  onCopyFormula?: (formula: string) => void;
  showCopy?: boolean;
}

const STEP_ITEM_HEIGHT = 68;

/**
 * Optimized LessonStepList:
 * - Uses FlatList with getItemLayout & keyExtractor for large step sequences (> 6 steps / spread lessons)
 * - Renders direct memoized StepCards for short lists (<= 6 steps)
 * - Prevents UI freezes and frame drops during scrolling and audio toggles
 */
export const LessonStepList: React.FC<LessonStepListProps> = ({
  steps,
  activePlayingId,
  loadingAudioId,
  audioPrefix = 'step',
  onPlayAudio,
  onCopyFormula,
  showCopy = true,
}) => {
  const validSteps = (steps || []).filter(
    (step) => step && (typeof step === 'string' ? step.trim().length > 0 : Boolean(step.text && step.text.trim().length > 0))
  );
  const cleanSteps = validSteps;

  const getStepText = (item: StepData) => (typeof item === 'string' ? item.trim() : item.text.trim());
  const getStepSpeechText = (item: StepData) =>
    typeof item === 'string' ? item.trim() : (item.speech_text ? item.speech_text.trim() : item.text.trim());

  const keyExtractor = useCallback(
    (item: StepData, index: number) => {
      const txt = typeof item === 'string' ? item : item.text;
      return `${audioPrefix}_${index}_${txt.slice(0, 16)}`;
    },
    [audioPrefix]
  );

  const getItemLayout = useCallback(
    (_: any, index: number) => ({
      length: STEP_ITEM_HEIGHT,
      offset: STEP_ITEM_HEIGHT * index,
      index,
    }),
    []
  );

  const renderItem = useCallback(
    ({ item, index }: { item: StepData; index: number }) => {
      const stepNumber = index + 1;
      const audioId = `${audioPrefix}_${index}`;
      const isPlaying = activePlayingId === audioId;
      const isLoadingAudio = loadingAudioId === audioId;
      const stepText = getStepText(item);
      const stepSpeech = getStepSpeechText(item);

      return (
        <StepCard
          stepNumber={stepNumber}
          text={stepText}
          speechText={stepSpeech}
          audioId={onPlayAudio ? audioId : undefined}
          isPlaying={isPlaying}
          isLoadingAudio={isLoadingAudio}
          onPlayAudio={onPlayAudio}
          onCopyFormula={onCopyFormula}
          showCopy={showCopy}
        />
      );
    },
    [audioPrefix, activePlayingId, loadingAudioId, onPlayAudio, onCopyFormula, showCopy]
  );

  if (cleanSteps.length === 0) {
    return null;
  }

  // Virtualized rendering for long lessons / spreads (> 6 steps)
  if (cleanSteps.length > 6) {
    return (
      <FlatList
        data={cleanSteps}
        renderItem={renderItem}
        keyExtractor={keyExtractor}
        getItemLayout={getItemLayout}
        initialNumToRender={6}
        maxToRenderPerBatch={8}
        windowSize={5}
        removeClippedSubviews={Platform.OS === 'android'}
        scrollEnabled={false}
      />
    );
  }

  // Direct memoized list for standard compact step sequences (<= 6 steps)
  return (
    <View style={styles.listContainer}>
      {validSteps.map((stepItem, idx) => {
        const stepNumber = idx + 1;
        const audioId = `${audioPrefix}_${idx}`;
        const isPlaying = activePlayingId === audioId;
        const isLoadingAudio = loadingAudioId === audioId;
        const stepText = getStepText(stepItem);
        const stepSpeech = getStepSpeechText(stepItem);

        return (
          <StepCard
            key={`${audioPrefix}_${idx}`}
            stepNumber={stepNumber}
            text={stepText}
            speechText={stepSpeech}
            audioId={onPlayAudio ? audioId : undefined}
            isPlaying={isPlaying}
            isLoadingAudio={isLoadingAudio}
            onPlayAudio={onPlayAudio}
            onCopyFormula={onCopyFormula}
            showCopy={showCopy}
          />
        );
      })}
    </View>
  );
};

const styles = StyleSheet.create({
  listContainer: {
    width: '100%',
  },
  stepRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    marginBottom: 12,
    backgroundColor: 'rgba(255, 255, 255, 0.05)',
    borderRadius: 12,
    padding: 10,
    borderWidth: 1,
    borderColor: 'rgba(255, 255, 255, 0.1)',
  },
  stepNumberBadge: {
    width: 28,
    height: 28,
    borderRadius: 14,
    backgroundColor: Theme.colors.primary,
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 10,
    marginTop: 2,
  },
  stepNumberText: {
    color: '#064E3B',
    fontWeight: '700',
    fontSize: 14,
  },
  stepContentCol: {
    flex: 1,
  },
  stepText: {
    fontSize: 15,
    lineHeight: 22,
    color: '#F1F5F9',
    fontWeight: '500',
  },
  stepActionsRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginTop: 8,
    gap: 8,
  },
  actionPill: {
    backgroundColor: 'rgba(56, 189, 248, 0.15)',
    paddingVertical: 4,
    paddingHorizontal: 8,
    borderRadius: 6,
    alignSelf: 'flex-start',
    borderWidth: 1,
    borderColor: 'rgba(56, 189, 248, 0.3)',
  },
  actionPillText: {
    color: '#38BDF8',
    fontSize: 12,
    fontWeight: '600',
  },
  audioPill: {
    backgroundColor: 'rgba(95, 237, 197, 0.15)',
    paddingVertical: 4,
    paddingHorizontal: 8,
    borderRadius: 6,
    alignSelf: 'flex-start',
    flexDirection: 'row',
    alignItems: 'center',
    borderWidth: 1,
    borderColor: 'rgba(95, 237, 197, 0.3)',
  },
  audioPillActive: {
    backgroundColor: 'rgba(239, 68, 68, 0.2)',
    borderColor: 'rgba(239, 68, 68, 0.4)',
  },
  audioPillText: {
    color: '#5FEDC5',
    fontSize: 12,
    fontWeight: '600',
  },
});
