import React, { useState, useEffect, useMemo } from 'react';
import {
  StyleSheet,
  Text,
  View,
  TouchableOpacity,
} from 'react-native';
import { VocabularyItem } from '../types';

interface PhraseBuilderProps {
  template: string;
  vocabulary: VocabularyItem[];
  isJunior: boolean;
  onPlayAudio: (text: string, lang: 'ru' | 'et', id: string) => void;
  playingId: string | null;
}

interface BankItem {
  id: string;
  word: string;
}

export const PhraseBuilder: React.FC<PhraseBuilderProps> = ({
  template,
  vocabulary,
  isJunior,
  onPlayAudio,
  playingId,
}) => {
  // Split template by 2 or more underscores (e.g. ___, ____, etc.)
  const parts = useMemo(() => template.split(/_{2,}/), [template]);
  const numSlots = Math.max(0, parts.length - 1);

  const [slots, setSlots] = useState<(string | null)[]>([]);
  const [availableWords, setAvailableWords] = useState<BankItem[]>([]);

  // Initialize slots and word bank whenever template or vocabulary changes
  useEffect(() => {
    setSlots(new Array(numSlots).fill(null));

    // Gather candidate words from vocabulary
    const bank: BankItem[] = [];
    vocabulary.forEach((item, idx) => {
      const cleanTerm = item.est.trim();
      if (cleanTerm) {
        bank.push({ id: `vocab_${idx}`, word: cleanTerm });
      }
    });

    // If slots need more words, also extract words from vocabulary examples
    if (bank.length < numSlots + 2) {
      vocabulary.forEach((item, vIdx) => {
        const exampleWords = item.example
          .replace(/[«».,!?;:()]/g, '')
          .split(/\s+/)
          .filter((w) => w.length > 2 && !bank.some((b) => b.word.toLowerCase() === w.toLowerCase()));
        
        exampleWords.slice(0, 2).forEach((w, wIdx) => {
          if (bank.length < numSlots + 3) {
            bank.push({ id: `ex_${vIdx}_${wIdx}`, word: w });
          }
        });
      });
    }

    setAvailableWords(bank);
  }, [template, vocabulary, numSlots]);

  // If template has no blanks (numSlots === 0), render plain template with speaker
  if (numSlots === 0) {
    const isPlaying = playingId === 'answer_template';
    return (
      <View style={[styles.container, isJunior ? styles.containerJunior : styles.containerSenior]}>
        <View style={styles.headerRow}>
          <Text style={[styles.title, isJunior && styles.titleJunior]}>
            ✏️ Эстонский каркас ответа:
          </Text>
          <TouchableOpacity
            style={[styles.audioBtn, isPlaying && styles.audioBtnActive]}
            onPress={() => onPlayAudio(template, 'et', 'answer_template')}
          >
            <Text style={styles.audioBtnText}>
              {isPlaying ? '⏹ Стоп' : '🔊 Озвучить (et)'}
            </Text>
          </TouchableOpacity>
        </View>
        <Text style={[styles.plainText, isJunior && styles.plainTextJunior]}>
          {template}
        </Text>
      </View>
    );
  }

  const handleSelectWord = (item: BankItem) => {
    const firstEmptyIndex = slots.findIndex((s) => s === null);
    if (firstEmptyIndex === -1) return; // All slots already filled

    const updatedSlots = [...slots];
    updatedSlots[firstEmptyIndex] = item.word;
    setSlots(updatedSlots);
    setAvailableWords((prev) => prev.filter((w) => w.id !== item.id));
  };

  const handleRemoveFromSlot = (slotIdx: number) => {
    const word = slots[slotIdx];
    if (!word) return;

    const updatedSlots = [...slots];
    updatedSlots[slotIdx] = null;
    setSlots(updatedSlots);

    // Return word to the bank
    setAvailableWords((prev) => [
      ...prev,
      { id: `returned_${Date.now()}_${Math.random()}`, word },
    ]);
  };

  const handleResetSlots = () => {
    const filledWords = slots.filter((s): s is string => s !== null);
    const returnedItems = filledWords.map((word, i) => ({
      id: `reset_${i}_${Date.now()}`,
      word,
    }));
    setSlots(new Array(numSlots).fill(null));
    setAvailableWords((prev) => [...prev, ...returnedItems]);
  };

  const isComplete = numSlots > 0 && slots.every((s) => s !== null && s !== '');

  const getAssembledPhrase = (): string => {
    let result = '';
    for (let i = 0; i < parts.length; i++) {
      result += parts[i];
      if (i < slots.length) {
        result += slots[i] ? slots[i] : '___';
      }
    }
    return result;
  };

  const isCompletedPlaying = playingId === 'answer_template_completed';

  return (
    <View
      style={[
        styles.container,
        isJunior ? styles.containerJunior : styles.containerSenior,
        isComplete && styles.containerComplete,
      ]}
    >
      {/* Header */}
      <View style={styles.headerRow}>
        <Text style={[styles.title, isJunior && styles.titleJunior]}>
          ✏️ Собери ответ на эстонском:
        </Text>
        {slots.some((s) => s !== null) && (
          <TouchableOpacity style={styles.resetBtn} onPress={handleResetSlots}>
            <Text style={styles.resetBtnText}>↺ Сбросить</Text>
          </TouchableOpacity>
        )}
      </View>

      <Text style={styles.subtitleHint}>
        {isComplete
          ? '🎉 Отлично! Фраза собрана. Послушай правильное произношение:'
          : 'Нажимай на слова внизу, чтобы подставить их в пропуски:'}
      </Text>

      {/* Interactive Sentence with Slots */}
      <View style={styles.sentenceWrapper}>
        <View style={styles.sentenceRow}>
          {parts.map((segment, idx) => {
            const hasSlot = idx < numSlots;
            const slotWord = hasSlot ? slots[idx] : null;

            return (
              <React.Fragment key={idx}>
                {segment.trim().length > 0 && (
                  <Text style={[styles.sentenceText, isJunior && styles.sentenceTextJunior]}>
                    {segment}
                  </Text>
                )}
                {hasSlot && (
                  <TouchableOpacity
                    style={[
                      styles.slot,
                      isJunior && styles.slotJunior,
                      slotWord ? styles.slotFilled : styles.slotEmpty,
                      isComplete && styles.slotComplete,
                    ]}
                    onPress={() => handleRemoveFromSlot(idx)}
                    activeOpacity={slotWord ? 0.7 : 1}
                  >
                    <Text
                      style={[
                        styles.slotText,
                        isJunior && styles.slotTextJunior,
                        slotWord ? styles.slotTextFilled : styles.slotTextEmpty,
                      ]}
                    >
                      {slotWord ? `${slotWord} ✕` : `[ слот ${idx + 1} ]`}
                    </Text>
                  </TouchableOpacity>
                )}
              </React.Fragment>
            );
          })}
        </View>
      </View>

      {/* Word Bank / Chips */}
      <View style={styles.bankSection}>
        <Text style={styles.bankLabel}>📦 Банк слов для подстановки:</Text>
        {availableWords.length === 0 ? (
          <Text style={styles.bankEmptyText}>
            Все слова расставлены по слотам! Нажми на слово в фразе, если хочешь вернуть его обратно.
          </Text>
        ) : (
          <View style={styles.chipsRow}>
            {availableWords.map((item) => (
              <TouchableOpacity
                key={item.id}
                style={[styles.chip, isJunior && styles.chipJunior]}
                onPress={() => handleSelectWord(item)}
              >
                <Text style={[styles.chipText, isJunior && styles.chipTextJunior]}>
                  + {item.word}
                </Text>
              </TouchableOpacity>
            ))}
          </View>
        )}
      </View>

      {/* Celebration & Audio Button when complete */}
      {isComplete && (
        <View style={styles.completeActionBox}>
          <TouchableOpacity
            style={[
              styles.listenCompletedBtn,
              isJunior && styles.listenCompletedBtnJunior,
              isCompletedPlaying && styles.listenCompletedBtnActive,
            ]}
            onPress={() => onPlayAudio(getAssembledPhrase(), 'et', 'answer_template_completed')}
          >
            <Text style={styles.listenCompletedBtnText}>
              {isCompletedPlaying ? '⏹ Остановить' : '🔊 Послушать свой ответ'}
            </Text>
          </TouchableOpacity>
        </View>
      )}
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    borderRadius: 14,
    padding: 14,
    marginTop: 12,
    borderWidth: 1.5,
  },
  containerJunior: {
    backgroundColor: '#FFFBEB',
    borderColor: '#FDE68A',
    borderRadius: 18,
  },
  containerSenior: {
    backgroundColor: '#F8FAFC',
    borderColor: '#E2E8F0',
    borderRadius: 12,
  },
  containerComplete: {
    borderColor: '#10B981',
    backgroundColor: '#ECFDF5',
  },
  headerRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 4,
  },
  title: {
    fontSize: 13,
    fontWeight: '700',
    color: '#92400E',
  },
  titleJunior: {
    fontSize: 14.5,
    color: '#78350F',
  },
  resetBtn: {
    backgroundColor: '#FEF3C7',
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 8,
  },
  resetBtnText: {
    fontSize: 11,
    color: '#92400E',
    fontWeight: '600',
  },
  subtitleHint: {
    fontSize: 11.5,
    color: '#6B7280',
    marginBottom: 10,
  },
  plainText: {
    fontSize: 14,
    fontWeight: '600',
    color: '#78350F',
    lineHeight: 20,
  },
  plainTextJunior: {
    fontSize: 15.5,
  },
  audioBtn: {
    backgroundColor: '#FEF3C7',
    paddingHorizontal: 9,
    paddingVertical: 4,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: '#FDE68A',
  },
  audioBtnActive: {
    backgroundColor: '#FEE2E2',
    borderColor: '#FCA5A5',
  },
  audioBtnText: {
    fontSize: 12,
    fontWeight: '700',
    color: '#92400E',
  },
  sentenceWrapper: {
    backgroundColor: '#FFFFFF',
    borderRadius: 12,
    padding: 12,
    marginBottom: 12,
    borderWidth: 1,
    borderColor: '#F3F4F6',
  },
  sentenceRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    alignItems: 'center',
  },
  sentenceText: {
    fontSize: 14.5,
    color: '#1F2937',
    lineHeight: 28,
  },
  sentenceTextJunior: {
    fontSize: 16,
    lineHeight: 30,
    fontWeight: '500',
  },
  slot: {
    paddingHorizontal: 9,
    paddingVertical: 3,
    borderRadius: 8,
    marginHorizontal: 3,
    marginVertical: 2,
    borderWidth: 1.5,
  },
  slotJunior: {
    paddingHorizontal: 11,
    paddingVertical: 4,
    borderRadius: 10,
  },
  slotEmpty: {
    backgroundColor: '#F3F4F6',
    borderColor: '#9CA3AF',
    borderStyle: 'dashed',
  },
  slotFilled: {
    backgroundColor: '#EFF6FF',
    borderColor: '#3B82F6',
  },
  slotComplete: {
    backgroundColor: '#D1FAE5',
    borderColor: '#10B981',
  },
  slotText: {
    fontSize: 13,
    fontWeight: '700',
  },
  slotTextJunior: {
    fontSize: 14.5,
  },
  slotTextEmpty: {
    color: '#6B7280',
    fontStyle: 'italic',
  },
  slotTextFilled: {
    color: '#1D4ED8',
  },
  bankSection: {
    marginTop: 2,
  },
  bankLabel: {
    fontSize: 11.5,
    fontWeight: '700',
    color: '#4B5563',
    marginBottom: 6,
  },
  bankEmptyText: {
    fontSize: 12,
    color: '#059669',
    fontStyle: 'italic',
    paddingVertical: 4,
  },
  chipsRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 6,
  },
  chip: {
    backgroundColor: '#FFFFFF',
    borderWidth: 1.5,
    borderColor: '#3B82F6',
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 12,
    elevation: 1,
    shadowColor: '#000',
    shadowOpacity: 0.05,
    shadowRadius: 3,
  },
  chipJunior: {
    backgroundColor: '#ECFDF5',
    borderColor: '#059669',
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 14,
  },
  chipText: {
    fontSize: 13,
    fontWeight: '700',
    color: '#1D4ED8',
  },
  chipTextJunior: {
    fontSize: 14.5,
    color: '#065F46',
  },
  completeActionBox: {
    marginTop: 12,
    alignItems: 'center',
  },
  listenCompletedBtn: {
    backgroundColor: '#059669',
    paddingVertical: 12,
    paddingHorizontal: 20,
    borderRadius: 14,
    alignItems: 'center',
    width: '100%',
    shadowColor: '#059669',
    shadowOpacity: 0.35,
    shadowRadius: 6,
    elevation: 3,
  },
  listenCompletedBtnJunior: {
    paddingVertical: 14,
    borderRadius: 18,
  },
  listenCompletedBtnActive: {
    backgroundColor: '#DC2626',
    shadowColor: '#DC2626',
  },
  listenCompletedBtnText: {
    color: '#FFFFFF',
    fontSize: 15,
    fontWeight: 'bold',
  },
});