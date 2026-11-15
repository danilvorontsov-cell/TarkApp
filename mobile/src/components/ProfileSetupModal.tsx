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
  useWindowDimensions,
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
  const { width: windowWidth, height: windowHeight } = useWindowDimensions();
  const isOnboarding = propIsOnboarding ?? !Boolean(currentProfile.nickname?.trim());

  // Dynamic responsive sizing adapting to any smartphone screen:
  const headerTopPadding = insets.top || (Platform.OS === 'android' ? 24 : 44);
  const visibleHeaderHeight = headerTopPadding + 54;
  const darkZoneHeight = windowHeight - visibleHeaderHeight;
  const verticalMargin = Math.max(insets.bottom, 16);
  // Keep the same generous window size, centered in the dark zone without bumping into the header
  const cardHeight = Math.max(darkZoneHeight - verticalMargin * 2, 520);
  const cardWidth = Math.min(windowWidth - 24, 460);

  const scrollViewRef = useRef<any>(null);
  const wasVisibleRef = useRef(false);

  const [name, setName] = useState(currentProfile.nickname || '');
  const [selectedGrade, setSelectedGrade] = useState(currentProfile.grade || 3);
  const [interestsText, setInterestsText] = useState('');
  const [hasCustomInterests, setHasCustomInterests] = useState(Boolean(currentProfile.hasCustomInterests));
  const [interestsByGrade, setInterestsByGrade] = useState<Record<number, string[]>>(
    currentProfile.interestsByGrade || {}
  );
  const [canScrollDown, setCanScrollDown] = useState(true);

  useEffect(() => {
    if (visible) {
      if (!wasVisibleRef.current) {
        wasVisibleRef.current = true;
        setCanScrollDown(true);

        StorageService.getProfileDraft().then((draft) => {
          let initialNick = currentProfile.nickname || '';
          let initialGrade = currentProfile.grade || 3;
          let initialMap: Record<number, string[]> = {
            ...(currentProfile.interestsByGrade || {}),
          };

          if (draft) {
            if (draft.nickname !== undefined) initialNick = draft.nickname;
            if (draft.grade !== undefined && draft.grade >= 1 && draft.grade <= 12) {
              initialGrade = draft.grade;
            }
            if (draft.interestsByGrade && typeof draft.interestsByGrade === 'object') {
              initialMap = { ...initialMap, ...draft.interestsByGrade };
            }
          }

          setName(initialNick);
          setSelectedGrade(initialGrade);

          // Resolve interests for initialGrade with strict grade-isolation
          const stored = initialMap[initialGrade] || initialMap[String(initialGrade) as any];
          let list: string[];
          let isCustom: boolean;

          if (stored && Array.isArray(stored) && stored.length > 0) {
            list = stored.map((i) => (typeof i === 'string' ? i.replace(/спотр/gi, 'спорт') : i));
            isCustom = !isDefaultInterestsList(list);
          } else if (draft?.interests && Array.isArray(draft.interests) && draft.interests.length > 0) {
            list = draft.interests.map((i) => (typeof i === 'string' ? i.replace(/спотр/gi, 'спорт') : i));
            isCustom = !isDefaultInterestsList(list);
            initialMap[initialGrade] = list;
          } else if (
            currentProfile.interests &&
            currentProfile.interests.length > 0 &&
            initialGrade === currentProfile.grade
          ) {
            list = currentProfile.interests.map((i) =>
              typeof i === 'string' ? i.replace(/спотр/gi, 'спорт') : i
            );
            isCustom = Boolean(currentProfile.hasCustomInterests);
            initialMap[initialGrade] = list;
          } else {
            const tier = getTierFromGrade(initialGrade);
            list = getDefaultInterestsForTier(tier);
            isCustom = false;
            initialMap[initialGrade] = list;
          }

          setInterestsByGrade(initialMap);
          setInterestsText(list.join(', '));
          setHasCustomInterests(isCustom);
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

  const handleScroll = (event: any) => {
    const { layoutMeasurement, contentOffset, contentSize } = event.nativeEvent;
    const isCloseToBottom = layoutMeasurement.height + contentOffset.y >= contentSize.height - 24;
    setCanScrollDown(!isCloseToBottom);
  };

  const handleScrollDown = () => {
    scrollViewRef.current?.scrollToEnd({ animated: true });
  };

  const handleContentSizeChange = (_contentWidth: number, contentHeight: number) => {
    if (contentHeight <= cardHeight - 80) {
      setCanScrollDown(false);
    }
  };

  const handleNameChange = (text: string) => {
    setName(text);
    const parsed = interestsText
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean);
    StorageService.saveProfileDraft({
      nickname: text,
      grade: selectedGrade,
      interests: parsed,
      hasCustomInterests,
      interestsByGrade,
    });
  };

  const handleGradeChange = (g: number) => {
    const oldGrade = selectedGrade;
    const newTier = getTierFromGrade(g);

    // Save current active interests under oldGrade
    const currentItems = interestsText
      .split(',')
      .map((s) => s.trim().replace(/спотр/gi, 'спорт'))
      .filter(Boolean);

    const updatedMap: Record<number, string[]> = {
      ...interestsByGrade,
      [oldGrade]: currentItems,
    };

    // Load or initialize interests for new grade
    const storedForNew = updatedMap[g] || updatedMap[String(g) as any];
    let nextList: string[];
    let nextIsCustom: boolean;

    if (storedForNew && Array.isArray(storedForNew) && storedForNew.length > 0) {
      nextList = storedForNew;
      nextIsCustom = !isDefaultInterestsList(storedForNew);
    } else {
      nextList = getDefaultInterestsForTier(newTier);
      nextIsCustom = false;
      updatedMap[g] = nextList;
    }

    const nextText = nextList.join(', ');
    setSelectedGrade(g);
    setInterestsByGrade(updatedMap);
    setInterestsText(nextText);
    setHasCustomInterests(nextIsCustom);

    StorageService.saveProfileDraft({
      nickname: name,
      grade: g,
      interests: nextList,
      hasCustomInterests: nextIsCustom,
      interestsByGrade: updatedMap,
    });
  };

  const handleInterestsChange = (text: string) => {
    const corrected = text.replace(/спотр/gi, 'спорт');
    setInterestsText(corrected);
    const items = corrected.split(',').map((s) => s.trim()).filter(Boolean);
    const isCustom = !isDefaultInterestsList(items);
    setHasCustomInterests(isCustom);

    const updatedMap: Record<number, string[]> = {
      ...interestsByGrade,
      [selectedGrade]: items,
    };
    setInterestsByGrade(updatedMap);

    StorageService.saveProfileDraft({
      nickname: name,
      grade: selectedGrade,
      interests: items,
      hasCustomInterests: isCustom,
      interestsByGrade: updatedMap,
    });
  };

  const handleAddSuggestion = (item: string) => {
    const currentList = interestsText
      .split(',')
      .map((s) => s.trim().replace(/спотр/gi, 'спорт'))
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
    const isCustom = !isDefaultInterestsList(updatedList);
    setHasCustomInterests(isCustom);

    const updatedMap: Record<number, string[]> = {
      ...interestsByGrade,
      [selectedGrade]: updatedList,
    };
    setInterestsByGrade(updatedMap);

    StorageService.saveProfileDraft({
      nickname: name,
      grade: selectedGrade,
      interests: updatedList,
      hasCustomInterests: isCustom,
      interestsByGrade: updatedMap,
    });
  };

  const handleAvatarPress = async () => {
    const parsed = interestsText
      .split(',')
      .map((s) => s.trim().replace(/спотр/gi, 'спорт'))
      .filter(Boolean);
    const updatedMap: Record<number, string[]> = {
      ...interestsByGrade,
      [selectedGrade]: parsed,
    };
    await StorageService.saveProfileDraft({
      nickname: name,
      grade: selectedGrade,
      interests: parsed,
      hasCustomInterests: !isDefaultInterestsList(parsed),
      interestsByGrade: updatedMap,
    });
    onClose();
    setTimeout(() => {
      onOpenAvatarPicker?.();
    }, 120);
  };

  const handleSave = async () => {
    const trimmed = name.trim() || 'Ученик';
    const newTier = getTierFromGrade(selectedGrade);

    const parsedInterests = interestsText
      .split(',')
      .map((s) => s.trim().replace(/спотр/gi, 'спорт'))
      .filter(Boolean);

    let finalInterests: string[];
    let isCustom: boolean;

    if (parsedInterests.length > 0) {
      finalInterests = parsedInterests;
      isCustom = !isDefaultInterestsList(finalInterests);
    } else {
      finalInterests = getDefaultInterestsForTier(newTier);
      isCustom = false;
    }

    const updatedMap: Record<number, string[]> = {
      ...interestsByGrade,
      [selectedGrade]: finalInterests,
    };

    const updated: UserProfile = {
      ...currentProfile,
      nickname: trimmed,
      grade: selectedGrade,
      tier: newTier,
      interests: finalInterests,
      hasCustomInterests: isCustom,
      interestsByGrade: updatedMap,
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
      <View style={styles.backdrop}>
        {!isOnboarding && (
          <TouchableWithoutFeedback onPress={handleDismiss}>
            <View style={StyleSheet.absoluteFill} />
          </TouchableWithoutFeedback>
        )}

        {/* Header spacer: allows the authentic mint TarkApp header in App.tsx to shine through */}
        <View
          style={{ height: visibleHeaderHeight, width: '100%', backgroundColor: 'transparent' }}
          pointerEvents="none"
        />

        <View style={styles.scrimContainer}>
          <KeyboardAvoidingView
            behavior={Platform.OS === 'ios' ? 'padding' : undefined}
            style={styles.keyboardView}
          >
            <View
              style={[
                styles.card,
                {
                  width: cardWidth,
                  height: cardHeight,
                  maxHeight: cardHeight,
                },
              ]}
            >
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
                ref={scrollViewRef}
                style={styles.scrollView}
                contentContainerStyle={styles.scrollContent}
                showsVerticalScrollIndicator={true}
                keyboardShouldPersistTaps="handled"
                keyboardDismissMode="on-drag"
                nestedScrollEnabled={true}
                bounces={false}
                onScroll={handleScroll}
                scrollEventThrottle={16}
                onContentSizeChange={handleContentSizeChange}
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
                {isOnboarding
                  ? 'Давай знакомиться!'
                  : currentProfile.nickname?.trim()
                  ? 'Профиль ученика'
                  : 'Давай знакомиться!'}
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
                  placeholder="Впиши свои увлечения вручную через запятую..."
                  placeholderTextColor="#64748B"
                  multiline
                  scrollEnabled={false}
                />
                <Text style={styles.interestsHint}>
                  💡 Впиши свои увлечения вручную (через запятую) или выбери готовые плашки. Тьютор объяснит правила и примеры через аналогии с твоими любимыми играми и хобби!
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
            <View style={styles.modalFooter}>
              {/* Active Scroll Down Indicator Button */}
              {canScrollDown && (
                <TouchableOpacity
                  style={styles.scrollDownBtn}
                  onPress={handleScrollDown}
                  activeOpacity={0.75}
                  hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
                  accessibilityRole="button"
                  accessibilityLabel="Прокрутить список вниз к подсказкам"
                >
                  <Text style={styles.scrollDownIcon}>↓</Text>
                </TouchableOpacity>
              )}

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
        </KeyboardAvoidingView>
      </View>
    </View>
  </Modal>
  );
};

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: 'transparent',
    zIndex: 9990,
  },
  scrimContainer: {
    flex: 1,
    width: '100%',
    backgroundColor: 'rgba(5, 8, 11, 0.82)',
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 12,
  },
  keyboardView: {
    width: '100%',
    flex: 1,
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
    paddingTop: 16,
    paddingHorizontal: 18,
    paddingBottom: 8,
    flexDirection: 'column',
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
    flex: 1,
  },
  scrollContent: {
    alignItems: 'center',
    paddingBottom: 32,
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
    paddingTop: 6,
    paddingBottom: 4,
    alignItems: 'center',
    position: 'relative',
  },
  scrollDownBtn: {
    position: 'absolute',
    right: 4,
    top: -36,
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: '#202830',
    borderWidth: 1,
    borderColor: '#334155',
    justifyContent: 'center',
    alignItems: 'center',
    zIndex: 20,
    ...Theme.shadow.chip,
  },
  scrollDownIcon: {
    color: '#94A3B8',
    fontSize: 16,
    fontWeight: '800',
    marginTop: -2,
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
