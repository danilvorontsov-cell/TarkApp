import React, { useState, useEffect, useMemo } from 'react';
import {
  StyleSheet,
  Text,
  View,
  TouchableOpacity,
  ActivityIndicator,
} from 'react-native';
import { VocabularyItem } from '../types';

interface PhraseBuilderProps {
  template: string;
  vocabulary: VocabularyItem[];
  isJunior: boolean;
  onPlayAudio: (text: string, lang: 'ru' | 'et', id: string) => void;
  playingId: string | null;
  loadingAudioId?: string | null;
}

interface SlotDef {
  slotId: number;
  expectedWord: string;
}

type Token =
  | { type: 'text'; text: string }
  | { type: 'slot'; slotId: number; expectedWord: string };

interface SentenceDef {
  sentenceIdx: number;
  tokens: Token[];
}

interface BankWord {
  id: string;
  word: string;
  isPlaced: boolean;
}

/**
 * Normalizes text for Estonian TTS synthesis:
 * - Extracts clean text / slot values
 * - Eliminates stray cross / multiplication marks (×, ✕, ✖, *)
 * - Eliminates brackets and placeholder markers
 * - Eliminates dots directly following integer numbers (e.g. "12." -> "12")
 *   so cardinal numbers (12 -> kaksteist) are NOT mistakenly read as ordinals (kahdestoistkümnes).
 * - Separates punctuation directly in contact with numbers
 * - Normalizes whitespace
 */
export const normalizeTextForTTS = (text: string): string => {
  if (!text) return '';

  let normalized = text;

  // 1. Remove multiplication and cross symbols (×, ✕, ✖, *)
  normalized = normalized.replace(/[\u00d7\u2715\u2716*]/g, ' ');

  // 2. Remove brackets, braces, parentheses
  normalized = normalized.replace(/[\[\]{}()]/g, ' ');

  // 3. Remove placeholder underscores
  normalized = normalized.replace(/_{2,}/g, ' ');

  // 4. Detach / remove dots directly after numbers so "12." is not synthesized as ordinal ("kaheteistkümnes")
  normalized = normalized.replace(/(\b\d+)\s*\.(?!\d)/g, '$1 ');

  // 5. Separate other punctuation directly in contact with numbers
  normalized = normalized.replace(/(\d+)([,!?;:])/g, '$1 $2');
  normalized = normalized.replace(/([,!?;:])(\d+)/g, '$1 $2');

  // 6. Separate hyphens/dashes attached to numbers
  normalized = normalized.replace(/(\d+)[-–—]+/g, '$1 ');
  normalized = normalized.replace(/[-–—]+(\d+)/g, ' $1');

  // 7. Collapse excess spaces
  return normalized.replace(/\s+/g, ' ').trim();
};

export const PhraseBuilder: React.FC<PhraseBuilderProps> = ({
  template,
  vocabulary,
  isJunior,
  onPlayAudio,
  playingId,
  loadingAudioId,
}) => {
  const [selectedSlotId, setSelectedSlotId] = useState<number | null>(null);
  const [slotsFilled, setSlotsFilled] = useState<Record<number, string>>({});
  const [bankWords, setBankWords] = useState<BankWord[]>([]);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Parse template into sentences and tokens
  const { sentences, allSlots } = useMemo(() => {
    let globalSlotCounter = 0;
    const slotsList: SlotDef[] = [];
    const sentenceList: SentenceDef[] = [];

    // Split template into distinct sentences by . ! ? or newline
    const rawSentences = template
      .split(/(?<=[.!?])\s+|\n+/)
      .filter((s) => s.trim().length > 0);

    const hasBrackets = /\[(.*?)\]/.test(template);

    rawSentences.forEach((rawSent, sIdx) => {
      const tokens: Token[] = [];

      if (hasBrackets) {
        // Parse [word]
        const parts = rawSent.split(/(\[.*?\])/);
        parts.forEach((p) => {
          if (!p) return;
          const match = p.match(/^\[(.*?)\]$/);
          if (match) {
            const expectedWord = match[1].trim();
            const slotId = globalSlotCounter++;
            slotsList.push({ slotId, expectedWord });
            tokens.push({ type: 'slot', slotId, expectedWord });
          } else {
            tokens.push({ type: 'text', text: p });
          }
        });
      } else {
        // Fallback: parse ___
        const parts = rawSent.split(/(_{2,})/);
        parts.forEach((p) => {
          if (!p) return;
          if (/^_{2,}$/.test(p)) {
            const slotId = globalSlotCounter++;
            // Map to vocabulary item if available
            const expectedWord =
              vocabulary[slotId % Math.max(1, vocabulary.length)]?.est.trim() || 'sõna';
            slotsList.push({ slotId, expectedWord });
            tokens.push({ type: 'slot', slotId, expectedWord });
          } else {
            tokens.push({ type: 'text', text: p });
          }
        });
      }

      sentenceList.push({ sentenceIdx: sIdx, tokens });
    });

    return { sentences: sentenceList, allSlots: slotsList };
  }, [template, vocabulary]);

  // Initialize or reset slots and bank words
  useEffect(() => {
    setSlotsFilled({});
    setSelectedSlotId(allSlots.length > 0 ? allSlots[0].slotId : null);
    setErrorMessage(null);

    // Build the Word Bank
    const bank: BankWord[] = [];

    // 1. Add all expected words
    allSlots.forEach((slot, i) => {
      bank.push({
        id: `expected_${slot.slotId}_${i}`,
        word: slot.expectedWord,
        isPlaced: false,
      });
    });

    // 2. Add 1-2 distractor words from vocabulary that are NOT already in expected words
    const expectedLower = new Set(allSlots.map((s) => s.expectedWord.toLowerCase()));
    let distractorsAdded = 0;

    for (let i = 0; i < vocabulary.length && distractorsAdded < 2; i++) {
      const vWord = vocabulary[i].est.trim();
      if (vWord && !expectedLower.has(vWord.toLowerCase())) {
        bank.push({
          id: `distractor_${i}`,
          word: vWord,
          isPlaced: false,
        });
        distractorsAdded++;
      }
    }

    // 3. Shuffle the word bank so words aren't in trivial slot order
    const shuffled = [...bank].sort(() => Math.random() - 0.5);
    setBankWords(shuffled);
  }, [template, vocabulary, allSlots]);

  // If no slots exist, render plain template
  if (allSlots.length === 0) {
    const isPlaying = playingId === 'answer_template';
    const isLoading = loadingAudioId === 'answer_template';
    return (
      <View style={[styles.container, isJunior ? styles.containerJunior : styles.containerSenior]}>
        <View style={styles.headerRow}>
          <Text style={[styles.title, isJunior && styles.titleJunior]}>
            ✏️ Эстонский каркас ответа:
          </Text>
          <TouchableOpacity
            style={[styles.audioBtn, isPlaying && styles.audioBtnActive]}
            onPress={() => onPlayAudio(normalizeTextForTTS(template), 'et', 'answer_template')}
            disabled={isLoading}
          >
            <View style={{ flexDirection: 'row', alignItems: 'center' }}>
              {isLoading && (
                <ActivityIndicator size="small" color="#92400E" style={{ marginRight: 6 }} />
              )}
              <Text style={styles.audioBtnText}>
                {isLoading ? 'Загрузка...' : isPlaying ? '⏹ Стоп' : '🔊 Озвучить (et)'}
              </Text>
            </View>
          </TouchableOpacity>
        </View>
        <Text style={[styles.plainText, isJunior && styles.plainTextJunior]}>
          {template.replace(/\[|\]/g, '')}
        </Text>
      </View>
    );
  }

  // Handle word selection from the Bank with strict pedagogical validation
  const handleSelectWord = (item: BankWord) => {
    setErrorMessage(null);

    // Determine target slot:
    // If a slot is explicitly selected and empty:
    let targetSlot = allSlots.find((s) => s.slotId === selectedSlotId && !slotsFilled[s.slotId]);

    // If no slot is selected or the selected one is already filled, check first empty slot that expects this word
    if (!targetSlot) {
      targetSlot = allSlots.find(
        (s) => !slotsFilled[s.slotId] && s.expectedWord.toLowerCase() === item.word.toLowerCase()
      );
    }

    // If still none, check the first unfilled slot overall
    if (!targetSlot) {
      targetSlot = allSlots.find((s) => !slotsFilled[s.slotId]);
    }

    if (!targetSlot) {
      return; // All slots already filled
    }

    // Validation check: Does this word match the target slot?
    const isMatch = targetSlot.expectedWord.toLowerCase() === item.word.toLowerCase();

    if (!isMatch) {
      // Reject placement: word does not fit here by grammar/meaning!
      setErrorMessage(`❌ Слово «${item.word}» не подходит сюда по смыслу. Попробуй другое!`);
      // Auto-clear error after 3 seconds
      setTimeout(() => setErrorMessage(null), 3000);
      return;
    }

    // Successful placement!
    setSlotsFilled((prev) => ({
      ...prev,
      [targetSlot!.slotId]: item.word,
    }));

    // Mark word as placed in the bank
    setBankWords((prev) =>
      prev.map((bw) => (bw.id === item.id ? { ...bw, isPlaced: true } : bw))
    );

    // Auto-advance selection to next empty slot
    const nextEmpty = allSlots.find(
      (s) => s.slotId !== targetSlot!.slotId && !slotsFilled[s.slotId]
    );
    setSelectedSlotId(nextEmpty ? nextEmpty.slotId : null);
  };

  // Remove word from slot and return it to the bank
  const handleRemoveFromSlot = (slotId: number) => {
    const placedWord = slotsFilled[slotId];
    if (!placedWord) {
      setSelectedSlotId(slotId);
      return;
    }

    setErrorMessage(null);

    // Free the slot
    setSlotsFilled((prev) => {
      const updated = { ...prev };
      delete updated[slotId];
      return updated;
    });

    // Return the word to available bank
    setBankWords((prev) => {
      let returned = false;
      return prev.map((bw) => {
        if (!returned && bw.isPlaced && bw.word.toLowerCase() === placedWord.toLowerCase()) {
          returned = true;
          return { ...bw, isPlaced: false };
        }
        return bw;
      });
    });

    setSelectedSlotId(slotId);
  };

  const handleResetSlots = () => {
    setSlotsFilled({});
    setBankWords((prev) => prev.map((bw) => ({ ...bw, isPlaced: false })));
    setSelectedSlotId(allSlots.length > 0 ? allSlots[0].slotId : null);
    setErrorMessage(null);
  };

  const isComplete =
    allSlots.length > 0 && allSlots.every((s) => !!slotsFilled[s.slotId]);

  // Build the complete phrase for audio pronunciation
  const getAssembledPhrase = (): string => {
    let result = '';
    sentences.forEach((sentence) => {
      sentence.tokens.forEach((token) => {
        if (token.type === 'text') {
          // Use clean pure text value without stray symbols or brackets
          const cleanText = (token.text || '').replace(/[\u00d7\u2715\u2716*\[\]{}]/g, ' ');
          result += cleanText;
        } else {
          // Use clean pure slot value without stray symbols or brackets
          const slotVal = (slotsFilled[token.slotId] || token.expectedWord || '')
            .replace(/[\u00d7\u2715\u2716*\[\]{}]/g, ' ')
            .trim();
          result += ` ${slotVal} `;
        }
      });
      result += ' ';
    });
    return normalizeTextForTTS(result);
  };

  const isCompletedPlaying = playingId === 'answer_template_completed';
  const isCompletedLoading = loadingAudioId === 'answer_template_completed';
  const availableBank = bankWords.filter((bw) => !bw.isPlaced);

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
        {Object.keys(slotsFilled).length > 0 && (
          <TouchableOpacity style={styles.resetBtn} onPress={handleResetSlots}>
            <Text style={styles.resetBtnText}>↺ Сбросить</Text>
          </TouchableOpacity>
        )}
      </View>

      <Text style={styles.subtitleHint}>
        {isComplete
          ? '🎉 Отлично! Все слова подобраны верно. Послушай правильное произношение:'
          : 'Подбирай подходящие по смыслу слова для каждого пропуска:'}
      </Text>

      {/* Sentences Container with Fixed-Line Layout (No Jumping) */}
      <View style={styles.sentencesCard}>
        {sentences.map((sent) => (
          <View key={sent.sentenceIdx} style={styles.sentenceLineBlock}>
            <View style={styles.sentenceRow}>
              {sent.tokens.map((token, tIdx) => {
                if (token.type === 'text') {
                  const cleanText = token.text;
                  if (!cleanText) return null;
                  return (
                    <Text
                      key={`t_${tIdx}`}
                      style={[styles.sentenceText, isJunior && styles.sentenceTextJunior]}
                    >
                      {cleanText}
                    </Text>
                  );
                }

                // Slot token
                const isFilled = !!slotsFilled[token.slotId];
                const filledWord = slotsFilled[token.slotId];
                const isSelected = selectedSlotId === token.slotId;

                return (
                  <TouchableOpacity
                    key={`slot_${token.slotId}`}
                    style={[
                      styles.slotBox,
                      isJunior && styles.slotBoxJunior,
                      isFilled ? styles.slotFilled : styles.slotEmpty,
                      isSelected && !isFilled && styles.slotSelected,
                      isComplete && styles.slotComplete,
                    ]}
                    onPress={() => {
                      if (!isFilled) {
                        setSelectedSlotId(token.slotId);
                      }
                    }}
                    disabled={isFilled}
                    activeOpacity={isFilled ? 1 : 0.7}
                  >
                    <Text
                      style={[
                        styles.slotText,
                        isJunior && styles.slotTextJunior,
                        isFilled ? styles.slotTextFilled : styles.slotTextEmpty,
                      ]}
                      numberOfLines={1}
                    >
                      {isFilled ? filledWord : `[ пропуск ${token.slotId + 1} ]`}
                    </Text>
                  </TouchableOpacity>
                );
              })}
            </View>
          </View>
        ))}
      </View>

      {/* Semantic Validation Error Feedback */}
      {errorMessage && (
        <View style={styles.errorBanner}>
          <Text style={styles.errorBannerText}>{errorMessage}</Text>
        </View>
      )}

      {/* Word Bank / Chips */}
      <View style={styles.bankSection}>
        <Text style={styles.bankLabel}>📦 Банк слов (выбери подходящее):</Text>
        {availableBank.length === 0 ? (
          <Text style={styles.bankEmptyText}>
            ✓ Все слова расставлены по местам!
          </Text>
        ) : (
          <View style={styles.chipsRow}>
            {availableBank.map((item) => (
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

      {/* Audio Playback Button when Complete */}
      {isComplete && (
        <View style={styles.completeActionBox}>
          <TouchableOpacity
            style={[
              styles.listenCompletedBtn,
              isJunior && styles.listenCompletedBtnJunior,
              isCompletedPlaying && styles.listenCompletedBtnActive,
            ]}
            onPress={() => onPlayAudio(getAssembledPhrase(), 'et', 'answer_template_completed')}
            disabled={isCompletedLoading}
            activeOpacity={0.8}
          >
            <View style={styles.listenBtnContent}>
              {isCompletedLoading ? (
                <>
                  <ActivityIndicator color="#FFFFFF" size="small" style={{ marginRight: 8 }} />
                  <Text style={styles.listenCompletedBtnText}>Загрузка аудио...</Text>
                </>
              ) : (
                <Text style={styles.listenCompletedBtnText}>
                  {isCompletedPlaying ? '⏹ Остановить' : '🔊 Послушать свой ответ'}
                </Text>
              )}
            </View>
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
    fontSize: 13.5,
    fontWeight: '700',
    color: '#92400E',
  },
  titleJunior: {
    fontSize: 15,
    color: '#78350F',
  },
  resetBtn: {
    backgroundColor: '#FEF3C7',
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 8,
  },
  resetBtnText: {
    fontSize: 11.5,
    color: '#92400E',
    fontWeight: '600',
  },
  subtitleHint: {
    fontSize: 12,
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
  // Sentences Layout - fixed line per sentence to avoid jumping
  sentencesCard: {
    backgroundColor: '#FFFFFF',
    borderRadius: 12,
    padding: 12,
    marginBottom: 10,
    borderWidth: 1,
    borderColor: '#F3F4F6',
  },
  sentenceLineBlock: {
    marginBottom: 8,
  },
  sentenceRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    alignItems: 'center',
  },
  sentenceText: {
    fontSize: 14.5,
    color: '#1F2937',
    lineHeight: 32,
    marginRight: 4,
  },
  sentenceTextJunior: {
    fontSize: 16,
    lineHeight: 34,
    fontWeight: '500',
  },
  // Stable slot box with min dimensions
  slotBox: {
    minWidth: 86,
    minHeight: 32,
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 8,
    marginHorizontal: 3,
    marginVertical: 2,
    borderWidth: 1.5,
    justifyContent: 'center',
    alignItems: 'center',
  },
  slotBoxJunior: {
    minWidth: 92,
    minHeight: 36,
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 10,
  },
  slotEmpty: {
    backgroundColor: '#F3F4F6',
    borderColor: '#9CA3AF',
    borderStyle: 'dashed',
  },
  slotSelected: {
    borderColor: '#3B82F6',
    backgroundColor: '#EFF6FF',
    borderStyle: 'solid',
  },
  slotFilled: {
    backgroundColor: '#EFF6FF',
    borderColor: '#3B82F6',
    borderStyle: 'solid',
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
  // Error Banner
  errorBanner: {
    backgroundColor: '#FEE2E2',
    borderWidth: 1,
    borderColor: '#FCA5A5',
    borderRadius: 10,
    paddingHorizontal: 10,
    paddingVertical: 6,
    marginBottom: 8,
  },
  errorBannerText: {
    fontSize: 12.5,
    color: '#B91C1C',
    fontWeight: '600',
    textAlign: 'center',
  },
  // Word Bank
  bankSection: {
    marginTop: 2,
  },
  bankLabel: {
    fontSize: 12,
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
  // Complete Button
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
  listenBtnContent: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
  },
});
