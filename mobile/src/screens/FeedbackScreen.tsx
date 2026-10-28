import React, { useState } from 'react';
import {
  StyleSheet,
  View,
  Text,
  TextInput,
  TouchableOpacity,
  ActivityIndicator,
  Alert,
  Platform,
} from 'react-native';
import * as Device from 'expo-device';
import * as Application from 'expo-application';
import { LinearGradient } from 'expo-linear-gradient';
import { Theme, darkTheme } from '../theme/colors';
import { sendFeedback, getLastRequestId } from '../services/api';

interface FeedbackScreenProps {
  onBack: () => void;
  currentGrade?: number;
}

type FeedbackCategory = 'bug' | 'feature';

export const FeedbackScreen: React.FC<FeedbackScreenProps> = ({
  onBack,
  currentGrade,
}) => {
  const [category, setCategory] = useState<FeedbackCategory>('bug');
  const [message, setMessage] = useState('');
  const [contact, setContact] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async () => {
    const trimmedMessage = message.trim();
    if (!trimmedMessage) {
      Alert.alert('Пустое сообщение', 'Пожалуйста, опишите проблему или вашу идею.');
      return;
    }

    setIsSubmitting(true);

    try {
      // Сбор расширенной телеметрии для привязки к логам
      const deviceModel =
        [Device.manufacturer, Device.modelName].filter(Boolean).join(' ') ||
        (Platform.OS === 'android' ? 'Android Device' : Platform.OS === 'ios' ? 'Apple Device' : 'Unknown');

      const osVersion = `${Platform.OS} ${Device.osVersion || Platform.Version || ''}`.trim();
      const appVersion = Application.nativeApplicationVersion || '1.0.0';
      const lastReqId = getLastRequestId() || undefined;
      const clientTime = new Date().toISOString();

      await sendFeedback({
        category,
        message: trimmedMessage,
        contact: contact.trim() || undefined,
        device_model: deviceModel,
        os_version: osVersion,
        app_version: appVersion,
        current_grade: currentGrade,
        last_request_id: lastReqId,
        client_time: clientTime,
      });

      Alert.alert(
        'Спасибо!',
        'Сообщение передано разработчику. Мы обязательно изучим ваш отзыв и логи!',
        [
          {
            text: 'OK',
            onPress: onBack,
          },
        ]
      );
    } catch (err: any) {
      Alert.alert(
        'Не удалось отправить',
        err?.message || 'Проверьте соединение с интернетом и попробуйте снова.'
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <View style={styles.container}>
      {/* Top Header Card */}
      <View style={styles.headerCard}>
        <View style={styles.headerTopRow}>
          <TouchableOpacity
            style={styles.backButton}
            onPress={onBack}
            activeOpacity={0.7}
            accessibilityLabel="Назад"
          >
            <Text style={styles.backButtonText}>← Назад</Text>
          </TouchableOpacity>
          <View style={styles.badgeBox}>
            <Text style={styles.badgeText}>Прямая связь</Text>
          </View>
        </View>

        <Text style={styles.title}>💬 Связь с разработчиком</Text>
        <Text style={styles.subtitle}>
          Помогите сделать TarkApp лучше! Отправьте отчёт об ошибке или предложите идею для уроков.
        </Text>
      </View>

      {/* Main Form Card */}
      <View style={styles.formCard}>
        {/* Category Tabs (Segmented Control) */}
        <Text style={styles.fieldLabel}>Тема сообщения:</Text>
        <View style={styles.categoryRow}>
          <TouchableOpacity
            style={[
              styles.categoryTab,
              category === 'bug' && styles.categoryTabActive,
            ]}
            onPress={() => setCategory('bug')}
            activeOpacity={0.8}
          >
            <Text
              style={[
                styles.categoryTabText,
                category === 'bug' && styles.categoryTabTextActive,
              ]}
            >
              🐞 Сообщить об ошибке
            </Text>
          </TouchableOpacity>

          <TouchableOpacity
            style={[
              styles.categoryTab,
              category === 'feature' && styles.categoryTabActive,
            ]}
            onPress={() => setCategory('feature')}
            activeOpacity={0.8}
          >
            <Text
              style={[
                styles.categoryTabText,
                category === 'feature' && styles.categoryTabTextActive,
              ]}
            >
              💡 Пожелание / идея
            </Text>
          </TouchableOpacity>
        </View>

        {/* Message Input */}
        <Text style={styles.fieldLabel}>
          {category === 'bug' ? 'Что пошло не так:' : 'Ваша идея или пожелание:'}
        </Text>
        <TextInput
          style={styles.messageInput}
          value={message}
          onChangeText={setMessage}
          placeholder={
            category === 'bug'
              ? 'Опишите проблему: какая страница учебника, какое слово или кнопка сработала не так...'
              : 'Опишите, какую функцию или тему вы хотели бы видеть в TarkApp...'
          }
          placeholderTextColor={darkTheme.textMuted}
          multiline
          numberOfLines={6}
          textAlignVertical="top"
        />

        {/* Contact Input (Optional) */}
        <Text style={styles.fieldLabel}>
          Контакт для связи <Text style={styles.optionalLabel}>(необязательно):</Text>
        </Text>
        <TextInput
          style={styles.contactInput}
          value={contact}
          onChangeText={setContact}
          placeholder="Email или Telegram (если хотите получить ответ)"
          placeholderTextColor={darkTheme.textMuted}
          autoCapitalize="none"
          autoCorrect={false}
        />

        {/* Hint info */}
        <View style={styles.infoBox}>
          <Text style={styles.infoBoxIcon}>🛡️</Text>
          <Text style={styles.infoBoxText}>
            К сообщению автоматически прикрепятся модель устройства, класс и ID сессии для мгновенного поиска в логах сервера. Никакие личные данные не передаются.
          </Text>
        </View>

        {/* Submit Button (Vertical Gradient ['#66F6CF', '#42DCA3']) */}
        <TouchableOpacity
          style={[styles.submitButton, isSubmitting && styles.submitButtonDisabled]}
          onPress={handleSubmit}
          disabled={isSubmitting}
          activeOpacity={0.85}
        >
          <LinearGradient
            colors={['#66F6CF', '#42DCA3']}
            start={{ x: 0, y: 0 }}
            end={{ x: 0, y: 1 }}
            style={styles.submitButtonGradient}
          >
            {isSubmitting ? (
              <View style={styles.loadingRow}>
                <ActivityIndicator size="small" color="#064E3B" />
                <Text style={styles.submitButtonText}>Отправка разработчику...</Text>
              </View>
            ) : (
              <Text style={styles.submitButtonText}>✓ Отправить разработчику</Text>
            )}
          </LinearGradient>
        </TouchableOpacity>
      </View>
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    width: '100%',
    paddingBottom: 24,
    backgroundColor: 'transparent',
  },
  headerCard: {
    backgroundColor: darkTheme.cardBackground,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: darkTheme.cardBorder,
    padding: 18,
    marginBottom: 14,
    ...Theme.shadow.card,
  },
  headerTopRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 12,
  },
  backButton: {
    paddingVertical: 6,
    paddingHorizontal: 10,
    borderRadius: 10,
    backgroundColor: darkTheme.badgeFreeBg,
  },
  backButtonText: {
    fontSize: 13,
    fontWeight: '700',
    color: darkTheme.textSecondary,
  },
  badgeBox: {
    backgroundColor: darkTheme.badgeFreeBg,
    borderWidth: 1,
    borderColor: darkTheme.cardBorder,
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 12,
  },
  badgeText: {
    fontSize: 12,
    fontWeight: '800',
    color: darkTheme.badgeFreeText,
  },
  title: {
    fontSize: 20,
    fontWeight: '800',
    color: darkTheme.textPrimary,
    marginBottom: 6,
    letterSpacing: -0.2,
  },
  subtitle: {
    fontSize: 13.5,
    lineHeight: 19,
    color: darkTheme.textSecondary,
  },
  formCard: {
    backgroundColor: darkTheme.cardBackground,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: darkTheme.cardBorder,
    padding: 18,
    ...Theme.shadow.card,
  },
  fieldLabel: {
    fontSize: 13.5,
    fontWeight: '700',
    color: darkTheme.textPrimary,
    marginBottom: 8,
    marginTop: 6,
  },
  optionalLabel: {
    fontSize: 12,
    fontWeight: '400',
    color: darkTheme.textSecondary,
  },
  categoryRow: {
    flexDirection: 'row',
    gap: 10,
    marginBottom: 14,
  },
  categoryTab: {
    flex: 1,
    paddingVertical: 12,
    paddingHorizontal: 8,
    borderRadius: 14,
    backgroundColor: Theme.colors.surfaceAlt,
    borderWidth: 1,
    borderColor: darkTheme.cardBorder,
    alignItems: 'center',
    justifyContent: 'center',
  },
  categoryTabActive: {
    backgroundColor: darkTheme.badgeFreeBg,
    borderColor: darkTheme.accent,
  },
  categoryTabText: {
    fontSize: 13,
    fontWeight: '600',
    color: darkTheme.textSecondary,
    textAlign: 'center',
  },
  categoryTabTextActive: {
    fontWeight: '800',
    color: darkTheme.badgeFreeText,
  },
  messageInput: {
    backgroundColor: Theme.colors.surfaceAlt,
    borderWidth: 1,
    borderColor: darkTheme.cardBorder,
    borderRadius: 16,
    padding: 14,
    fontSize: 14,
    lineHeight: 20,
    color: darkTheme.textPrimary,
    minHeight: 130,
    marginBottom: 14,
  },
  contactInput: {
    backgroundColor: Theme.colors.surfaceAlt,
    borderWidth: 1,
    borderColor: darkTheme.cardBorder,
    borderRadius: 14,
    paddingHorizontal: 14,
    paddingVertical: 12,
    fontSize: 14,
    color: darkTheme.textPrimary,
    marginBottom: 14,
  },
  infoBox: {
    flexDirection: 'row',
    backgroundColor: Theme.colors.surfaceAlt,
    borderWidth: 1,
    borderColor: darkTheme.cardBorder,
    borderRadius: 12,
    padding: 12,
    alignItems: 'flex-start',
    marginBottom: 18,
  },
  infoBoxIcon: {
    fontSize: 18,
    marginRight: 10,
    marginTop: 1,
  },
  infoBoxText: {
    flex: 1,
    fontSize: 12,
    lineHeight: 17,
    color: darkTheme.textSecondary,
  },
  submitButton: {
    borderRadius: 14,
    overflow: 'hidden',
    ...Theme.shadow.button,
  },
  submitButtonGradient: {
    paddingVertical: 15,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: 14,
  },
  submitButtonDisabled: {
    opacity: 0.7,
  },
  loadingRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  submitButtonText: {
    fontSize: 15,
    fontWeight: '800',
    color: darkTheme.accentText,
    letterSpacing: 0.2,
  },
});
