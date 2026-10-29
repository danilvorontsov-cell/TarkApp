import React, { useState, useEffect } from 'react';
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
} from 'react-native';
import { UserProfile, SchoolTier, getTierFromGrade, getTierPolicy } from '../types';
import { Theme, darkTheme } from '../theme/colors';

const { width: SCREEN_WIDTH, height: SCREEN_HEIGHT } = Dimensions.get('window');
const MODAL_WIDTH = Math.min(SCREEN_WIDTH * 0.92, 400);

export const GRADES = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12];

interface ProfileSetupModalProps {
  visible: boolean;
  onClose: () => void;
  currentProfile: UserProfile;
  onSaveProfile: (updated: UserProfile) => void;
  onOpenAvatarPicker?: () => void;
}

export const ProfileSetupModal: React.FC<ProfileSetupModalProps> = ({
  visible,
  onClose,
  currentProfile,
  onSaveProfile,
  onOpenAvatarPicker,
}) => {
  const [name, setName] = useState(currentProfile.nickname || '');
  const [selectedGrade, setSelectedGrade] = useState(currentProfile.grade || 3);

  useEffect(() => {
    if (visible) {
      setName(currentProfile.nickname || '');
      setSelectedGrade(currentProfile.grade || 3);
    }
  }, [visible, currentProfile]);

  const tierPolicy = getTierPolicy(selectedGrade);
  const tierBadgeLabel = tierPolicy.name.split(' (')[0];

  const handleSave = () => {
    const trimmed = name.trim() || 'Ученик';
    const newTier = getTierFromGrade(selectedGrade);
    const updated: UserProfile = {
      ...currentProfile,
      nickname: trimmed,
      grade: selectedGrade,
      tier: newTier,
    };
    onClose();
    setTimeout(() => {
      onSaveProfile(updated);
    }, 120);
  };

  const handleDismiss = () => {
    // If nickname is completely empty on dismiss, ensure at least default 'Ученик' is set
    if (!currentProfile.nickname?.trim()) {
      const updated: UserProfile = {
        ...currentProfile,
        nickname: 'Ученик',
      };
      setTimeout(() => {
        onSaveProfile(updated);
      }, 120);
    }
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
      <TouchableWithoutFeedback onPress={handleDismiss}>
        <View style={styles.backdrop}>
          <KeyboardAvoidingView
            behavior={Platform.OS === 'ios' ? 'padding' : undefined}
            style={styles.keyboardView}
          >
            <TouchableWithoutFeedback>
              <View style={styles.card}>
                {/* Close Cross */}
                <TouchableOpacity
                  style={styles.closeBtn}
                  onPress={handleDismiss}
                  hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}
                >
                  <Text style={styles.closeBtnText}>✕</Text>
                </TouchableOpacity>

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
                    onPress={onOpenAvatarPicker}
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
                    {currentProfile.nickname?.trim() ? 'Профиль ученика' : 'Давай знакомиться!'}
                  </Text>
                  <Text style={styles.subtitle}>
                    Укажи имя и класс, чтобы TarkApp подстраивал объяснения под школьную программу
                  </Text>

                  {/* Name Input */}
                  <View style={styles.inputSection}>
                    <Text style={styles.inputLabel}>Имя или никнейм ученика</Text>
                    <TextInput
                      style={styles.textInput}
                      value={name}
                      onChangeText={setName}
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
                            onPress={() => setSelectedGrade(g)}
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
                </ScrollView>

                {/* Fixed Footer: Save & Continue Buttons */}
                <View style={styles.modalFooter}>
                  <TouchableOpacity
                    style={styles.saveBtn}
                    onPress={handleSave}
                    activeOpacity={0.85}
                  >
                    <Text style={styles.saveBtnText}>✓ Сохранить</Text>
                  </TouchableOpacity>

                  {!currentProfile.nickname?.trim() && (
                    <TouchableOpacity
                      style={styles.skipBtn}
                      onPress={handleDismiss}
                      activeOpacity={0.7}
                    >
                      <Text style={styles.skipBtnText}>Продолжить как Ученик</Text>
                    </TouchableOpacity>
                  )}
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
    maxHeight: Math.min(SCREEN_HEIGHT * 0.9, 680),
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
    paddingBottom: 4,
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
    marginBottom: 10,
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
    marginBottom: 14,
    paddingHorizontal: 8,
  },
  inputSection: {
    width: '100%',
    marginBottom: 14,
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
    height: 46,
    color: '#FFFFFF',
    fontSize: 15,
    fontWeight: '600',
  },
  gradeSection: {
    width: '100%',
    marginBottom: 14,
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
    height: 42,
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
});
