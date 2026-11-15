import React, { useState, useEffect, useRef } from 'react';
import {
  StyleSheet,
  View,
  Text,
  TextInput,
  TouchableOpacity,
  Modal,
  TouchableWithoutFeedback,
  Dimensions,
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  Image,
  Linking,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import {
  UserProfile,
  SchoolTier,
  getTierFromGrade,
  getTierPolicy,
  getDefaultInterestsForTier,
  isDefaultInterestsList,
  PRIMARY_CHILDISH_INTERESTS,
  AGE_SUGGESTIONS,
  getInterestsPlaceholder,
} from '../types';
import { StorageService } from '../services/storage';
import { Theme, darkTheme } from '../theme/colors';

const { width: SCREEN_WIDTH, height: SCREEN_HEIGHT } = Dimensions.get('window');
const MODAL_WIDTH = Math.min(SCREEN_WIDTH * 0.92, 420);

export const GRADES = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12];

interface ProfileSetupModalProps {
  visible: boolean;
  onClose: () => void;
  currentProfile: UserProfile;
  onSaveProfile: (updated: UserProfile) => void;
  onOpenAvatarPicker?: () => void;
  isOnboarding?: boolean;
}

export const ProfileSetupModal: React.FC<ProfileSetupModalProps> = ({
  visible,
  onClose,
  currentProfile,
  onSaveProfile,
  onOpenAvatarPicker,
  isOnboarding: propIsOnboarding,
}) => {
  const insets = useSafeAreaInsets();
  const isOnboarding = propIsOnboarding ?? !Boolean(currentProfile.nickname?.trim());

  const [name, setName] = useState(currentProfile.nickname || '');
  const [selectedGrade, setSelectedGrade] = useState(currentProfile.grade || 3);
  const [interestsText, setInterestsText] = useState('');
  const [hasCustomInterests, setHasCustomInterests] = useState(Boolean(currentProfile.hasCustomInterests));
  const wasVisibleRef = useRef(false);

  useEffect(() => {
    if (visible) {
      if (!wasVisibleRef.current) {
        wasVisibleRef.current = true;
        StorageService.getProfileDraft().then((draft) => {
          let initialNick = currentProfile.nickname || '';
          let initialGrade = currentProfile.grade || 3;
          let initialCustom = Boolean(currentProfile.hasCustomInterests);
          let initialInterests = currentProfile.interests || [];

          if (draft) {
            if (draft.nickname !== undefined) initialNick = draft.nickname;
            if (draft.grade !== undefined && draft.grade >= 1 && draft.grade <= 12) {
              initialGrade = draft.grade;
            }
            if (draft.hasCustomInterests !== undefined) {
              initialCustom = Boolean(draft.hasCustomInterests);
            }
            if (draft.interests !== undefined && Array.isArray(draft.interests)) {
              initialInterests = draft.interests;
            }
          }

          setName(initialNick);
          setSelectedGrade(initialGrade);
          setHasCustomInterests(initialCustom);

          if (initialInterests && initialInterests.length > 0) {
            const cleaned = initialInterests.map((i) =>
              typeof i === 'string' ? i.replace(/спотр/gi, 'спорт') : i
            );
            setInterestsText(cleaned.join(', '));
          } else {
            const gradeMap = currentProfile.interestsByGrade || {};
            const savedForGrade = gradeMap[initialGrade] || gradeMap[String(initialGrade) as any];
            if (savedForGrade && Array.isArray(savedForGrade) && savedForGrade.length > 0) {
              setInterestsText(savedForGrade.join(', '));
            } else {
              const tier = getTierFromGrade(initialGrade);
              setInterestsText(getDefaultInterestsForTier(tier).join(', '));
            }
          }
        });
      }
    } else {
      wasVisibleRef.current = false;
    }
  }, [visible, currentProfile]);

  const currentTier = getTierFromGrade(selectedGrade);
  const tierPolicy = getTierPolicy(selectedGrade);
  const tierBadgeLabel = tierPolicy.name.split(' (')[0];
  const currentSuggestions = AGE_SUGGESTIONS[currentTier] || AGE_SUGGESTIONS.primary;

  const handleNameChange = (text: string) => {
    setName(text);
    const parsed = interestsText.split(',').map((s) => s.trim()).filter(Boolean);
    StorageService.saveProfileDraft({
      nickname: text,
      grade: selectedGrade,
      interests: parsed,
      hasCustomInterests,
    });
  };

  const handleGradeChange = (g: number) => {
    setSelectedGrade(g);
    const newTier = getTierFromGrade(g);

    let nextInterestsText = interestsText;
    let nextInterestsList: string[];

    if (!hasCustomInterests) {
      const gradeMap = currentProfile.interestsByGrade || {};
      const savedForGrade = gradeMap[g] || gradeMap[String(g) as any];
      if (savedForGrade && Array.isArray(savedForGrade) && savedForGrade.length > 0) {
        nextInterestsList = savedForGrade;
      } else {
        nextInterestsList = getDefaultInterestsForTier(newTier);
      }
      nextInterestsText = nextInterestsList.join(', ');
      setInterestsText(nextInterestsText);
    } else {
      nextInterestsList = interestsText
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean);
    }

    StorageService.saveProfileDraft({
      nickname: name,
      grade: g,
      interests: nextInterestsList,
      hasCustomInterests,
    });
  };

  const handleInterestsChange = (text: string) => {
    const corrected = text.replace(/спотр/gi, 'спорт');
    setInterestsText(corrected);
    setHasCustomInterests(true);
    const items = corrected.split(',').map((s) => s.trim()).filter(Boolean);
    StorageService.saveProfileDraft({
      nickname: name,
      grade: selectedGrade,
      interests: items,
      hasCustomInterests: true,
    });
  };

  const handleAddSuggestion = (item: string) => {
    const currentList = interestsText
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean);
    const itemLower = item.trim().toLowerCase();
    const exists = currentList.some((s) => s.toLowerCase() === itemLower);

    let updatedList: string[];
    if (exists) {
      updatedList = currentList.filter((s) => s.toLowerCase() !== itemLower);
    } else {
      updatedList = [...currentList, item.trim()];
    }

    const newText = updatedList.join(', ');
    setInterestsText(newText);
    setHasCustomInterests(true);
    StorageService.saveProfileDraft({
      nickname: name,
      grade: selectedGrade,
      interests: updatedList,
      hasCustomInterests: true,
    });
  };

  const handleAvatarPress = async () => {
    const parsed = interestsText.split(',').map((s) => s.trim()).filter(Boolean);
    await StorageService.saveProfileDraft({
      nickname: name,
      grade: selectedGrade,
      interests: parsed,
      hasCustomInterests,
    });
    onClose();
    setTimeout(() => {
      onOpenAvatarPicker?.();
    }, 120);
  };

  const handleSave = async () => {
    const trimmed = name.trim() || 'Ученик';
    const newTier = getTierFromGrade(selectedGrade);

    // Retrieve interests for selectedGrade if previously stored
    const gradeMap: Record<number, string[]> = {
      ...(currentProfile.interestsByGrade || {}),
    };

    const parsedInterests = interestsText
      .split(',')
      .map((s) => s.trim().replace(/спотр/gi, 'спорт'))
      .filter(Boolean);

    let finalInterests: string[];
    let isCustom: boolean;

    if (parsedInterests.length > 0) {
      finalInterests = parsedInterests;
      isCustom = hasCustomInterests && !isDefaultInterestsList(finalInterests);
    } else {
      finalInterests = getDefaultInterestsForTier(newTier);
      isCustom = false;
    }

    gradeMap[selectedGrade] = finalInterests;

    const updated: UserProfile = {
      ...currentProfile,
      nickname: trimmed,
      grade: selectedGrade,
      tier: newTier,
      interests: finalInterests,
      hasCustomInterests: isCustom,
      interestsByGrade: gradeMap,
    };

    await StorageService.clearProfileDraft();
    onClose();
    setTimeout(() => {
      onSaveProfile(updated);
    }, 120);
  };

  const handleDismiss = async () => {
    await StorageService.clearProfileDraft();
    onClose();
  };

  return (
    <Modal
      visible={visible}
      transparent
      animationType="fade"
      onRequestClose={handleDismiss}
      statusBarTranslucent
    >
      <TouchableWithoutFeedback onPress={isOnboarding ? undefined : handleDismiss}>
        <View style={styles.backdrop}>
          <KeyboardAvoidingView
            behavior={Platform.OS === 'ios' ? 'padding' : undefined}
            style={styles.keyboardView}
          >
            <TouchableWithoutFeedback>
              <View style={styles.card}>
                {/* Close Cross - hidden during onboarding */}
                {!isOnboarding && (
                  <TouchableOpacity
                    style={styles.closeBtn}
                    onPress={handleDismiss}
                    hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}
                    accessibilityLabel="Закрыть"
                  >
                    <Text style={styles.closeBtnText}>✕</Text>
                  </TouchableOpacity>
                )}

                <ScrollView
                  style={styles.scrollView}
                  contentContainerStyle={styles.scrollContent}
                  showsVerticalScrollIndicator={false}
                  keyboardShouldPersistTaps="handled"
                  bounces={false}
                >
                  {/* Avatar Circle */}
                  <TouchableOpacity
                    style={styles.avatarCircle}
                    onPress={handleAvatarPress}
                    activeOpacity={0.8}
                  >
                    {currentProfile.avatarUri ? (
                      <Image source={{ uri: currentProfile.avatarUri }} style={styles.avatarImage} />
                    ) : (
                      <Text style={styles.avatarEmoji}>🧑‍🎓</Text>
                    )}
                    <View style={styles.avatarBadge}>
                      <Text style={styles.avatarBadgeText}>📷</Text>
                    </View>
                  </TouchableOpacity>

                  {/* Title & Subtitle */}
                  <Text style={styles.title}>
                    {isOnboarding ? 'Давай знакомиться!' : (currentProfile.nickname?.trim() ? 'Профиль ученика' : 'Давай знакомиться!')}
                  </Text>
                  <Text style={styles.subtitle}>
                    Укажи имя, класс и интересы, чтобы TarkApp подстраивал объяснения и примеры под тебя
                  </Text>

                  {/* Name Input */}
                  <View style={styles.inputSection}>
                    <Text style={styles.inputLabel}>Имя или никнейм ученика</Text>
                    <TextInput
                      style={styles.textInput}
                      value={name}
                      onChangeText={handleNameChange}
                      placeholder="Например, Даниил или София"
                      placeholderTextColor="#64748B"
                      autoCapitalize="words"
                      autoCorrect={false}
                      maxLength={24}
                    />
                  </View>

                  {/* Grade Selector */}
                  <View style={styles.gradeSection}>
                    <View style={styles.gradeHeaderRow}>
                      <Text style={styles.inputLabel}>
                        Класс обучения: <Text style={styles.gradeHighlight}>{selectedGrade} класс</Text>
                      </Text>
                      <View style={styles.tierBadge}>
                        <Text style={styles.tierBadgeText}>{tierBadgeLabel}</Text>
                      </View>
                    </View>
                    <View style={styles.gradeGrid}>
                      {GRADES.map((g) => {
                        const isSelected = selectedGrade === g;
                        return (
                          <TouchableOpacity
                            key={g}
                            style={[
                              styles.gradeChip,
                              isSelected && styles.gradeChipSelected,
                            ]}
                            onPress={() => handleGradeChange(g)}
                            activeOpacity={0.7}
                          >
                            <Text
                              style={[
                                styles.gradeChipText,
                                isSelected && styles.gradeChipTextSelected,
                              ]}
                            >
                              {g}
                            </Text>
                          </TouchableOpacity>
                        );
                      })}
                    </View>
                  </View>

                  {/* Interests & Age Suggestions */}
                  <View style={styles.interestsSection}>
                    <Text style={styles.inputLabel}>
                      Увлечения и интересы (для понятных примеров):
                    </Text>
                    <TextInput
                      style={[styles.textInput, styles.interestsInput]}
                      value={interestsText}
                      onChangeText={handleInterestsChange}
                      placeholder={getInterestsPlaceholder(currentTier)}
                      placeholderTextColor="#64748B"
                      multiline
                    />
                    <Text style={styles.interestsHint}>
                      💡 Тьютор объяснит грамматику и примеры через аналогии с любимыми играми и хобби!
                    </Text>

                    <Text style={styles.suggestionsTitle}>Быстрые подсказки по возрасту:</Text>
                    <View style={styles.suggestionsGrid}>
                      {currentSuggestions.map((item, idx) => {
                        const currentList = interestsText
                          .split(',')
                          .map((s) => s.trim().toLowerCase())
                          .filter(Boolean);
                        const isSelected = currentList.includes(item.trim().toLowerCase());
                        return (
                          <TouchableOpacity
                            key={idx}
                            style={[
                              styles.suggestionChip,
                              isSelected && styles.suggestionChipSelected,
                            ]}
                            onPress={() => handleAddSuggestion(item)}
                            activeOpacity={0.7}
                          >
                            <Text
                              style={[
                                styles.suggestionText,
                                isSelected && styles.suggestionTextSelected,
                              ]}
                            >
                              {isSelected ? '✓ ' : '+ '}
                              {item}
                            </Text>
                          </TouchableOpacity>
                        );
                      })}
                    </View>
                  </View>
                </ScrollView>

                {/* Fixed Sticky Footer: Save & Continue Buttons */}
                <View style={[styles.modalFooter, { paddingBottom: Math.max(insets.bottom, 12) }]}>
                  <TouchableOpacity
                    style={styles.saveBtn}
                    onPress={handleSave}
                    activeOpacity={0.85}
                  >
                    <Text style={styles.saveBtnText}>
                      {isOnboarding ? '🚀 Начать обучение' : '✓ Сохранить'}
                    </Text>
                  </TouchableOpacity>

                  {isOnboarding && (
                    <TouchableOpacity
                      style={styles.skipBtn}
                      onPress={handleSave}
                      activeOpacity={0.7}
                    >
                      <Text style={styles.skipBtnText}>Продолжить как Ученик</Text>
                    </TouchableOpacity>
                  )}

                  <TouchableOpacity
                    style={styles.privacyLinkBtn}
                    onPress={() => Linking.openURL('https://tarkapp.ee/privacy')}
                    activeOpacity={0.7}
                    accessibilityRole="link"
                  >
                    <Text style={styles.privacyLinkText}>🔒 Политика конфиденциальности</Text>
                  </TouchableOpacity>
                </View>
              </View>
            </TouchableWithoutFeedback>
          </KeyboardAvoidingView>
        </View>
      </TouchableWithoutFeedback>
    </Modal>
  );
};

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: 'rgba(5, 8, 11, 0.85)',
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: 16,
    zIndex: 9990,
  },
  keyboardView: {
    width: '100%',
    alignItems: 'center',
    justifyContent: 'center',
  },
  card: {
    width: MODAL_WIDTH,
    maxHeight: Math.min(SCREEN_HEIGHT * 0.92, 740),
    minHeight: Math.min(SCREEN_HEIGHT * 0.7, 520),
    backgroundColor: '#161B20',
    borderRadius: 24,
    borderWidth: 1,
    borderColor: '#2D3844',
    paddingTop: 18,
    paddingHorizontal: 20,
    paddingBottom: 16,
    ...Theme.shadow.modal,
  },
  closeBtn: {
    position: 'absolute',
    top: 14,
    right: 14,
    width: 30,
    height: 30,
    borderRadius: 15,
    backgroundColor: '#202830',
    justifyContent: 'center',
    alignItems: 'center',
    zIndex: 10,
  },
  closeBtnText: {
    color: '#94A3B8',
    fontSize: 14,
    fontWeight: '700',
  },
  scrollView: {
    width: '100%',
    flexGrow: 0,
    flexShrink: 1,
  },
  scrollContent: {
    alignItems: 'center',
    paddingBottom: 8,
  },
  avatarCircle: {
    width: 64,
    height: 64,
    borderRadius: 32,
    backgroundColor: 'rgba(95, 237, 197, 0.14)',
    borderWidth: 2,
    borderColor: '#5FEDC5',
    justifyContent: 'center',
    alignItems: 'center',
    marginTop: 2,
    marginBottom: 8,
    position: 'relative',
    ...Theme.shadow.chip,
  },
  avatarImage: {
    width: 60,
    height: 60,
    borderRadius: 30,
  },
  avatarEmoji: {
    fontSize: 30,
  },
  avatarBadge: {
    position: 'absolute',
    bottom: -2,
    right: -2,
    width: 22,
    height: 22,
    borderRadius: 11,
    backgroundColor: '#1E252B',
    borderWidth: 1.5,
    borderColor: '#5FEDC5',
    justifyContent: 'center',
    alignItems: 'center',
  },
  avatarBadgeText: {
    fontSize: 10,
  },
  title: {
    fontSize: 20,
    fontWeight: '800',
    color: '#FFFFFF',
    textAlign: 'center',
    letterSpacing: -0.3,
    marginBottom: 4,
  },
  subtitle: {
    fontSize: 12.5,
    fontWeight: '500',
    color: '#94A3B8',
    textAlign: 'center',
    lineHeight: 17,
    marginBottom: 12,
    paddingHorizontal: 8,
  },
  inputSection: {
    width: '100%',
    marginBottom: 12,
  },
  inputLabel: {
    fontSize: 12.5,
    fontWeight: '700',
    color: '#CBD5E1',
  },
  textInput: {
    width: '100%',
    backgroundColor: '#101418',
    borderWidth: 1,
    borderColor: '#2D3844',
    borderRadius: 14,
    paddingHorizontal: 14,
    paddingVertical: 10,
    marginTop: 6,
    height: 44,
    color: '#FFFFFF',
    fontSize: 14.5,
    fontWeight: '600',
  },
  gradeSection: {
    width: '100%',
    marginBottom: 12,
  },
  gradeHeaderRow: {
    width: '100%',
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 8,
  },
  gradeHighlight: {
    color: '#5FEDC5',
    fontWeight: '800',
  },
  tierBadge: {
    backgroundColor: 'rgba(95, 237, 197, 0.12)',
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: 'rgba(95, 237, 197, 0.3)',
  },
  tierBadgeText: {
    fontSize: 11,
    fontWeight: '700',
    color: '#5FEDC5',
  },
  gradeGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    justifyContent: 'space-between',
    rowGap: 8,
    width: '100%',
  },
  gradeChip: {
    width: '14.8%',
    height: 40,
    borderRadius: 12,
    backgroundColor: '#202830',
    borderWidth: 1,
    borderColor: '#334155',
    justifyContent: 'center',
    alignItems: 'center',
  },
  gradeChipSelected: {
    backgroundColor: '#5FEDC5',
    borderColor: '#5FEDC5',
    ...Theme.shadow.chip,
  },
  gradeChipText: {
    fontSize: 14,
    fontWeight: '700',
    color: '#CBD5E1',
  },
  gradeChipTextSelected: {
    color: '#064E3B',
    fontWeight: '900',
  },
  interestsSection: {
    width: '100%',
    marginBottom: 12,
  },
  interestsInput: {
    minHeight: 52,
    maxHeight: 76,
    textAlignVertical: 'top',
    paddingTop: 8,
    fontSize: 13.5,
    lineHeight: 18,
  },
  interestsHint: {
    fontSize: 11,
    color: '#94A3B8',
    marginTop: 4,
    lineHeight: 15,
  },
  suggestionsTitle: {
    fontSize: 12,
    fontWeight: '700',
    color: '#94A3B8',
    marginTop: 10,
    marginBottom: 6,
    alignSelf: 'flex-start',
  },
  suggestionsGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 6,
    width: '100%',
  },
  suggestionChip: {
    backgroundColor: '#1E252B',
    borderRadius: 14,
    borderWidth: 1,
    borderColor: '#334155',
    paddingHorizontal: 10,
    paddingVertical: 5,
  },
  suggestionChipSelected: {
    backgroundColor: 'rgba(95, 237, 197, 0.15)',
    borderColor: '#5FEDC5',
  },
  suggestionText: {
    fontSize: 12,
    color: '#94A3B8',
    fontWeight: '600',
  },
  suggestionTextSelected: {
    color: '#5FEDC5',
    fontWeight: '700',
  },
  modalFooter: {
    width: '100%',
    paddingTop: 8,
    alignItems: 'center',
  },
  saveBtn: {
    width: '100%',
    backgroundColor: '#5FEDC5',
    borderRadius: 16,
    height: 48,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 4,
    ...Theme.shadow.button,
  },
  saveBtnText: {
    fontSize: 15,
    fontWeight: '800',
    color: '#064E3B',
    letterSpacing: 0.2,
  },
  skipBtn: {
    paddingVertical: 6,
  },
  skipBtnText: {
    fontSize: 13,
    fontWeight: '600',
    color: '#64748B',
  },
  privacyLinkBtn: {
    paddingVertical: 6,
    marginTop: 2,
  },
  privacyLinkText: {
    fontSize: 12,
    fontWeight: '600',
    color: '#5FEDC5',
    textDecorationLine: 'underline',
  },
});
