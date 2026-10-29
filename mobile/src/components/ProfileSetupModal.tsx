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
import { UserProfile, SchoolTier, getTierFromGrade } from '../types';
import { Theme, darkTheme } from '../theme/colors';

const { width: SCREEN_WIDTH } = Dimensions.get('window');
const MODAL_WIDTH = Math.min(SCREEN_WIDTH * 0.9, 360);

const GRADES = [1, 2, 3, 4, 5, 6, 7, 8, 9];

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

                <ScrollView showsVerticalScrollIndicator={false} contentContainerStyle={styles.scrollContent}>
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
                    <Text style={styles.inputLabel}>Класс обучения ({selectedGrade} класс)</Text>
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

                  {/* Save Button */}
                  <TouchableOpacity
                    style={styles.saveBtn}
                    onPress={handleSave}
                    activeOpacity={0.85}
                  >
                    <Text style={styles.saveBtnText}>✓ Сохранить и продолжить</Text>
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
                </ScrollView>
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
    paddingHorizontal: 20,
    zIndex: 9990,
  },
  keyboardView: {
    width: '100%',
    alignItems: 'center',
    justifyContent: 'center',
  },
  card: {
    width: MODAL_WIDTH,
    maxHeight: '90%',
    backgroundColor: '#161B20',
    borderRadius: 24,
    borderWidth: 1,
    borderColor: '#2D3844',
    padding: 22,
    ...Theme.shadow.modal,
  },
  scrollContent: {
    alignItems: 'center',
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
  avatarCircle: {
    width: 68,
    height: 68,
    borderRadius: 34,
    backgroundColor: 'rgba(95, 237, 197, 0.14)',
    borderWidth: 2,
    borderColor: '#5FEDC5',
    justifyContent: 'center',
    alignItems: 'center',
    marginTop: 6,
    marginBottom: 12,
    position: 'relative',
    ...Theme.shadow.chip,
  },
  avatarImage: {
    width: 64,
    height: 64,
    borderRadius: 32,
  },
  avatarEmoji: {
    fontSize: 32,
  },
  avatarBadge: {
    position: 'absolute',
    bottom: -2,
    right: -2,
    width: 24,
    height: 24,
    borderRadius: 12,
    backgroundColor: '#1E252B',
    borderWidth: 1.5,
    borderColor: '#5FEDC5',
    justifyContent: 'center',
    alignItems: 'center',
  },
  avatarBadgeText: {
    fontSize: 11,
  },
  title: {
    fontSize: 20,
    fontWeight: '800',
    color: '#FFFFFF',
    textAlign: 'center',
    letterSpacing: -0.3,
    marginBottom: 6,
  },
  subtitle: {
    fontSize: 13,
    fontWeight: '500',
    color: '#94A3B8',
    textAlign: 'center',
    lineHeight: 18,
    marginBottom: 18,
    paddingHorizontal: 8,
  },
  inputSection: {
    width: '100%',
    marginBottom: 16,
  },
  inputLabel: {
    fontSize: 12.5,
    fontWeight: '700',
    color: '#CBD5E1',
    marginBottom: 8,
  },
  textInput: {
    width: '100%',
    backgroundColor: '#101418',
    borderWidth: 1,
    borderColor: '#2D3844',
    borderRadius: 14,
    paddingHorizontal: 14,
    paddingVertical: 12,
    color: '#FFFFFF',
    fontSize: 15,
    fontWeight: '600',
  },
  gradeSection: {
    width: '100%',
    marginBottom: 20,
  },
  gradeGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
    justifyContent: 'center',
  },
  gradeChip: {
    width: 32,
    height: 34,
    borderRadius: 10,
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
  saveBtn: {
    width: '100%',
    backgroundColor: '#5FEDC5',
    borderRadius: 16,
    paddingVertical: 14,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 8,
    ...Theme.shadow.button,
  },
  saveBtnText: {
    fontSize: 15,
    fontWeight: '800',
    color: '#064E3B',
  },
  skipBtn: {
    paddingVertical: 8,
  },
  skipBtnText: {
    fontSize: 13,
    fontWeight: '600',
    color: '#64748B',
  },
});
