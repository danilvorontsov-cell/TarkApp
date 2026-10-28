import React, { useState } from 'react';
import {
  StyleSheet,
  View,
  Text,
  Modal,
  TextInput,
  TouchableOpacity,
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  TouchableWithoutFeedback,
} from 'react-native';
import { Theme, darkTheme } from '../theme/colors';
import { activateAccessKey, LicenseStatus } from '../services/api';

interface LicenseActivationModalProps {
  visible: boolean;
  onClose: () => void;
  onActivated: (status: LicenseStatus) => void;
  isBlocking?: boolean;
  reason?: 'trial_expired' | 'reviews_limit_reached' | null;
}

export const LicenseActivationModal: React.FC<LicenseActivationModalProps> = ({
  visible,
  onClose,
  onActivated,
  isBlocking = false,
  reason = null,
}) => {
  const [keyCode, setKeyCode] = useState('');
  const [loading, setLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  const handleActivate = async () => {
    const trimmed = keyCode.trim().toUpperCase();
    if (!trimmed) {
      setErrorMessage('Пожалуйста, введите ключ доступа.');
      return;
    }

    setLoading(true);
    setErrorMessage(null);
    setSuccessMessage(null);

    try {
      const res = await activateAccessKey(trimmed);
      setSuccessMessage(res.message || 'Ключ успешно активирован!');
      setTimeout(() => {
        onActivated({
          is_active: res.is_active,
          has_key: res.has_key ?? true,
          free_reviews_left: res.free_reviews_left,
          max_free_reviews: res.max_free_reviews,
          days_left: res.days_left,
          expires_at: res.expires_at,
          activated_key: trimmed,
          package_name: res.package_name,
        });
        setKeyCode('');
        setSuccessMessage(null);
        onClose();
      }, 1200);
    } catch (err: any) {
      const msg = err?.message || 'Не удалось активировать ключ. Проверьте правильность кода.';
      setErrorMessage(msg);
    } finally {
      setLoading(false);
    }
  };

  const handleDismiss = () => {
    if (!isBlocking && !loading) {
      setErrorMessage(null);
      setSuccessMessage(null);
      onClose();
    }
  };

  const modalTitle =
    reason === 'reviews_limit_reached'
      ? 'Бесплатные разборы закончились'
      : isBlocking
      ? 'Пробный период завершен'
      : 'Ввод ключа доступа';

  const modalSubtitle =
    reason === 'reviews_limit_reached'
      ? 'Вы использовали все 5 бесплатных разборов страниц. Введите ключ доступа для безлимитной помощи с уроками.'
      : isBlocking
      ? '14 дней бесплатного пробного периода истекли. Введите промокод или ключ бета-тестера для возобновления доступа.'
      : 'Введите ключ доступа для продления периода работы TarkApp.';

  return (
    <Modal
      visible={visible}
      transparent
      animationType="fade"
      onRequestClose={handleDismiss}
    >
      <TouchableWithoutFeedback onPress={handleDismiss}>
        <View style={styles.backdrop}>
          <KeyboardAvoidingView
            behavior={Platform.OS === 'ios' ? 'padding' : undefined}
            style={styles.keyboardAvoid}
          >
            <TouchableWithoutFeedback>
              <View style={styles.modalCard}>
                {/* Header Icon & Title */}
                <View style={styles.headerRow}>
                  <View style={[styles.iconCircle, isBlocking && styles.iconCircleBlocking]}>
                    <Text style={styles.icon}>{isBlocking ? '🔒' : '🔑'}</Text>
                  </View>
                  {!isBlocking && (
                    <TouchableOpacity
                      style={styles.closeBtn}
                      onPress={handleDismiss}
                      hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}
                    >
                      <Text style={styles.closeBtnText}>✕</Text>
                    </TouchableOpacity>
                  )}
                </View>

                <Text style={styles.title}>{modalTitle}</Text>
                <Text style={styles.subtitle}>{modalSubtitle}</Text>

                {/* Input Field */}
                <View style={styles.inputContainer}>
                  <Text style={styles.inputLabel}>Код ключа:</Text>
                  <TextInput
                    style={styles.input}
                    value={keyCode}
                    onChangeText={(val) => {
                      setKeyCode(val.toUpperCase());
                      if (errorMessage) setErrorMessage(null);
                    }}
                    placeholder="TARK-XXXX-XXXX"
                    placeholderTextColor={darkTheme.textMuted}
                    autoCapitalize="characters"
                    autoCorrect={false}
                    editable={!loading && !successMessage}
                  />
                </View>

                {/* Error Banner */}
                {Boolean(errorMessage) && (
                  <View style={styles.errorBox}>
                    <Text style={styles.errorIcon}>⚠️</Text>
                    <Text style={styles.errorText}>{errorMessage}</Text>
                  </View>
                )}

                {/* Success Banner */}
                {Boolean(successMessage) && (
                  <View style={styles.successBox}>
                    <Text style={styles.successIcon}>✓</Text>
                    <Text style={styles.successText}>{successMessage}</Text>
                  </View>
                )}

                {/* Submit Action Button */}
                <TouchableOpacity
                  style={[
                    styles.actionBtn,
                    loading && styles.actionBtnDisabled,
                    Boolean(successMessage) && styles.actionBtnSuccess,
                  ]}
                  onPress={handleActivate}
                  disabled={loading || Boolean(successMessage)}
                  activeOpacity={0.85}
                >
                  {loading ? (
                    <View style={styles.loadingRow}>
                      <ActivityIndicator size="small" color="#064E3B" />
                      <Text style={styles.actionBtnText}>Проверка ключа...</Text>
                    </View>
                  ) : (
                    <Text style={styles.actionBtnText}>
                      {successMessage ? 'Успешно активировано!' : 'Активировать доступ'}
                    </Text>
                  )}
                </TouchableOpacity>

                {/* Dismiss option if blocking but user wants to browse settings */}
                {isBlocking && (
                  <TouchableOpacity
                    style={styles.cancelLink}
                    onPress={onClose}
                    activeOpacity={0.7}
                  >
                    <Text style={styles.cancelLinkText}>Закрыть</Text>
                  </TouchableOpacity>
                )}
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
    backgroundColor: 'rgba(15, 23, 42, 0.65)',
    justifyContent: 'center',
    alignItems: 'center',
    padding: 20,
  },
  keyboardAvoid: {
    width: '100%',
    alignItems: 'center',
  },
  modalCard: {
    width: '100%',
    maxWidth: 380,
    backgroundColor: darkTheme.cardBackground,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: darkTheme.cardBorder,
    padding: 22,
    ...Theme.shadow.modal,
  },
  headerRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 14,
  },
  iconCircle: {
    width: 48,
    height: 48,
    borderRadius: 24,
    backgroundColor: darkTheme.badgeFreeBg,
    alignItems: 'center',
    justifyContent: 'center',
  },
  iconCircleBlocking: {
    backgroundColor: '#3F1E24',
  },
  icon: {
    fontSize: 24,
  },
  closeBtn: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: darkTheme.badgeFreeBg,
    alignItems: 'center',
    justifyContent: 'center',
  },
  closeBtnText: {
    fontSize: 14,
    fontWeight: '700',
    color: darkTheme.textSecondary,
  },
  title: {
    fontSize: 20,
    fontWeight: '800',
    color: darkTheme.textPrimary,
    marginBottom: 6,
  },
  subtitle: {
    fontSize: 13.5,
    lineHeight: 19,
    color: darkTheme.textSecondary,
    marginBottom: 18,
  },
  inputContainer: {
    marginBottom: 14,
  },
  inputLabel: {
    fontSize: 13,
    fontWeight: '700',
    color: darkTheme.textSecondary,
    marginBottom: 6,
  },
  input: {
    backgroundColor: Theme.colors.surfaceAlt,
    borderWidth: 1,
    borderColor: darkTheme.cardBorder,
    borderRadius: 14,
    paddingHorizontal: 16,
    paddingVertical: 12,
    fontSize: 16,
    fontWeight: '700',
    color: darkTheme.textPrimary,
    letterSpacing: 1.5,
  },
  errorBox: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#3F1E24',
    borderWidth: 1,
    borderColor: '#EF4444',
    borderRadius: 12,
    padding: 10,
    marginBottom: 14,
    gap: 8,
  },
  errorIcon: {
    fontSize: 16,
  },
  errorText: {
    flex: 1,
    fontSize: 12.5,
    color: '#FCA5A5',
    fontWeight: '600',
  },
  successBox: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: 'rgba(95, 237, 197, 0.14)',
    borderWidth: 1,
    borderColor: '#5FEDC5',
    borderRadius: 12,
    padding: 10,
    marginBottom: 14,
    gap: 8,
  },
  successIcon: {
    fontSize: 16,
    color: '#5FEDC5',
    fontWeight: 'bold',
  },
  successText: {
    flex: 1,
    fontSize: 13,
    color: '#5FEDC5',
    fontWeight: '700',
  },
  actionBtn: {
    backgroundColor: '#5FEDC5',
    paddingVertical: 14,
    borderRadius: 14,
    alignItems: 'center',
    justifyContent: 'center',
    ...Theme.shadow.button,
  },
  actionBtnDisabled: {
    opacity: 0.7,
  },
  actionBtnSuccess: {
    backgroundColor: '#34D399',
  },
  actionBtnText: {
    fontSize: 15,
    fontWeight: '800',
    color: '#064E3B',
  },
  loadingRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  cancelLink: {
    marginTop: 14,
    alignItems: 'center',
  },
  cancelLinkText: {
    fontSize: 13.5,
    fontWeight: '600',
    color: '#94A3B8',
  },
});
