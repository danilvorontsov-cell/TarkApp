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
import { Theme } from '../theme/colors';
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
          placeholderTextColor="#94A3B8"
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
          placeholderTextColor="#94A3B8"
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

        {/* Submit Button */}
        <TouchableOpacity
          style={[styles.submitButton, isSubmitting && styles.submitButtonDisabled]}
          onPress={handleSubmit}
          disabled={isSubmitting}
          activeOpacity={0.85}
        >
          {isSubmitting ? (
            <View style={styles.loadingRow}>
              <ActivityIndicator size="small" color="#064E3B" />
              <Text style={styles.submitButtonText}>Отправка разработчику...</Text>
            </View>
          ) : (
            <Text style={styles.submitButtonText}>✓ Отправить разработчику</Text>
          )}
        </TouchableOpacity>
      </View>
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    width: '100%',
    paddingBottom: 24,
  },
  headerCard: {
    backgroundColor: '#FFFFFF',
    borderRadius: 20,
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
    backgroundColor: '#F1F5F9',
  },
  backButtonText: {
    fontSize: 13,
    fontWeight: '700',
    color: '#334155',
  },
  badgeBox: {
    backgroundColor: '#CFFAEE',
    borderWidth: 1,
    borderColor: '#5FEDC5',
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 12,
  },
  badgeText: {
    fontSize: 12,
    fontWeight: '800',
    color: '#064E3B',
  },
  title: {
    fontSize: 20,
    fontWeight: '800',
    color: '#0F172A',
    marginBottom: 6,
    letterSpacing: -0.2,
  },
  subtitle: {
    fontSize: 13.5,
    lineHeight: 19,
    color: '#64748B',
  },
  formCard: {
    backgroundColor: '#FFFFFF',
    borderRadius: 20,
    padding: 18,
    ...Theme.shadow.card,
  },
  fieldLabel: {
    fontSize: 13.5,
    fontWeight: '700',
    color: '#0F172A',
    marginBottom: 8,
    marginTop: 6,
  },
  optionalLabel: {
    fontSize: 12,
    fontWeight: '400',
    color: '#64748B',
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
    backgroundColor: '#F1F5F9',
    borderWidth: 1.5,
    borderColor: 'transparent',
    alignItems: 'center',
    justifyContent: 'center',
  },
  categoryTabActive: {
    backgroundColor: '#CFFAEE',
    borderColor: '#5FEDC5',
  },
  categoryTabText: {
    fontSize: 13,
    fontWeight: '600',
    color: '#475569',
    textAlign: 'center',
  },
  categoryTabTextActive: {
    fontWeight: '800',
    color: '#064E3B',
  },
  messageInput: {
    backgroundColor: '#F8FAFC',
    borderWidth: 1.5,
    borderColor: '#E2E8F0',
    borderRadius: 16,
    padding: 14,
    fontSize: 14,
    lineHeight: 20,
    color: '#0F172A',
    minHeight: 130,
    marginBottom: 14,
  },
  contactInput: {
    backgroundColor: '#F8FAFC',
    borderWidth: 1.5,
    borderColor: '#E2E8F0',
    borderRadius: 14,
    paddingHorizontal: 14,
    paddingVertical: 12,
    fontSize: 14,
    color: '#0F172A',
    marginBottom: 14,
  },
  infoBox: {
    flexDirection: 'row',
    backgroundColor: '#F8FAFC',
    borderWidth: 1,
    borderColor: '#E2E8F0',
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
    color: '#64748B',
  },
  submitButton: {
    backgroundColor: '#5FEDC5',
    paddingVertical: 15,
    borderRadius: 14,
    alignItems: 'center',
    justifyContent: 'center',
    ...Theme.shadow.button,
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
    color: '#064E3B',
    letterSpacing: 0.2,
  },
});
