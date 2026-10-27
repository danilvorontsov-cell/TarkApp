import React, { useState } from 'react';
import {
  StyleSheet,
  View,
  Text,
  TextInput,
  TouchableOpacity,
  ActivityIndicator,
  Alert,
  Keyboard,
  Platform,
} from 'react-native';
import * as Clipboard from 'expo-clipboard';
import * as ImagePicker from 'expo-image-picker';
import { Theme, darkTheme } from '../theme/colors';
import { quickTranslate, QuickTranslateResponse } from '../services/api';
import { StorageService } from '../services/storage';
import { playTts, stopTts } from '../services/audioPlayer';
import { VocabularyItem } from '../types';

interface QuickTranslatorScreenProps {
  onBackToStudy?: () => void;
  onVocabularySaved?: () => void;
}

export const QuickTranslatorScreen: React.FC<QuickTranslatorScreenProps> = ({
  onBackToStudy,
  onVocabularySaved,
}) => {
  const [inputText, setInputText] = useState('');
  const [sourceLang, setSourceLang] = useState<'et' | 'ru'>('et');
  const [targetLang, setTargetLang] = useState<'et' | 'ru'>('ru');
  const [isLoading, setIsLoading] = useState(false);
  const [result, setResult] = useState<QuickTranslateResponse | null>(null);
  const [isCopied, setIsCopied] = useState(false);
  const [isSavedToVocab, setIsSavedToVocab] = useState(false);
  const [isPlayingAudio, setIsPlayingAudio] = useState(false);

  // Переключение направления перевода
  const handleSwapLanguages = () => {
    const prevSource = sourceLang;
    const prevTarget = targetLang;
    setSourceLang(prevTarget);
    setTargetLang(prevSource);

    // Если есть текущий результат, меняем его местами для мгновенного обратного перевода
    if (result) {
      setInputText(result.translated_text);
      setResult(null);
      setIsSavedToVocab(false);
      setIsCopied(false);
    }
  };

  // Выполнение перевода
  const handleTranslate = async (textToTranslate?: string, imageBase64?: string) => {
    const query = (textToTranslate !== undefined ? textToTranslate : inputText).trim();
    if (!query && !imageBase64) {
      Alert.alert('Введите текст', 'Пожалуйста, введите слово, фразу или сделайте снимок текста учебника.');
      return;
    }

    Keyboard.dismiss();
    setIsLoading(true);
    setIsCopied(false);
    setIsSavedToVocab(false);

    try {
      const resp = await quickTranslate({
        text: query || undefined,
        image_base64: imageBase64 || undefined,
        source_lang: sourceLang,
        target_lang: targetLang,
      });

      setResult(resp);
      // Если перевод выполнен по фото, подставляем распознанный текст в поле
      if (imageBase64 && resp.original_text) {
        setInputText(resp.original_text);
      }
    } catch (err: any) {
      Alert.alert(
        'Ошибка перевода',
        err.message || 'Не удалось выполнить перевод. Проверьте соединение с сервером.'
      );
    } finally {
      setIsLoading(false);
    }
  };

  // Вставка из буфера обмена
  const handlePasteClipboard = async () => {
    try {
      const text = await Clipboard.getStringAsync();
      if (text) {
        setInputText(text);
      }
    } catch {
      // Игнорируем ошибку чтения буфера
    }
  };

  // Очистка поля
  const handleClear = () => {
    setInputText('');
    setResult(null);
    setIsSavedToVocab(false);
    setIsCopied(false);
    stopTts();
    setIsPlayingAudio(false);
  };

  // Снимок текста через камеру
  const handleCaptureCamera = async () => {
    try {
      const perm = await ImagePicker.requestCameraPermissionsAsync();
      if (!perm.granted) {
        Alert.alert(
          'Доступ к камере',
          'Разрешите приложению доступ к камере, чтобы фотографировать фрагменты учебника.'
        );
        return;
      }

      const photo = await ImagePicker.launchCameraAsync({
        mediaTypes: ['images'],
        allowsEditing: false,
        quality: 0.8,
        base64: true,
      });

      if (photo.canceled || !photo.assets || photo.assets.length === 0) {
        return;
      }

      const b64 = photo.assets[0].base64;
      if (b64) {
        await handleTranslate(undefined, b64);
      }
    } catch (err: any) {
      Alert.alert('Ошибка камеры', err.message || 'Не удалось сделать фото.');
    }
  };

  // Озвучивание
  const handleToggleVoice = async () => {
    if (isPlayingAudio) {
      stopTts();
      setIsPlayingAudio(false);
      return;
    }

    if (!result) return;

    // Озвучиваем эстонскую часть для тренировки произношения (если переводили на эстонский — перевод, если с эстонского — оригинал)
    const isEstonianResult = result.target_lang === 'et' || sourceLang === 'ru';
    const textToSpeak = isEstonianResult ? result.translated_text : result.original_text;
    const voiceLang = 'et';

    try {
      setIsPlayingAudio(true);
      await playTts(textToSpeak, voiceLang);
    } catch {
      // Ошибка воспроизведения
    } finally {
      setIsPlayingAudio(false);
    }
  };

  // Копирование перевода
  const handleCopyResult = async () => {
    if (!result) return;
    try {
      await Clipboard.setStringAsync(result.translated_text);
      setIsCopied(true);
      setTimeout(() => setIsCopied(false), 2500);
    } catch {
      // Игнорируем
    }
  };

  // Сохранение в «Мой словарик»
  const handleSaveToVocabulary = async () => {
    if (!result || isSavedToVocab) return;

    const isEstonianSource = result.source_lang === 'et' || sourceLang === 'et';
    const estWord = isEstonianSource ? result.original_text : result.translated_text;
    const ruWord = isEstonianSource ? result.translated_text : result.original_text;

    let exampleText = result.base_forms || '';
    if (result.context_note) {
      exampleText = exampleText
        ? `${exampleText} • ${result.context_note}`
        : result.context_note;
    }

    const item: VocabularyItem = {
      est: estWord.trim(),
      ru: ruWord.trim(),
      example: exampleText || 'Быстрый перевод (Kiirtõlge)',
    };

    await StorageService.saveVocabularyItem(item);
    setIsSavedToVocab(true);
    if (onVocabularySaved) {
      onVocabularySaved();
    }
  };

  return (
    <View style={styles.container}>
      {/* Top Banner / Breadcrumb */}
      <View style={styles.topBanner}>
        <View style={styles.titleRow}>
          <Text style={styles.bannerEmoji}>🌐</Text>
          <View>
            <Text style={styles.bannerTitle}>Быстрый школьный переводчик</Text>
            <Text style={styles.bannerSubtitle}>Kiirtõlge • адаптация терминов Эстонии</Text>
          </View>
        </View>
        {onBackToStudy && (
          <TouchableOpacity
            style={styles.backBtn}
            onPress={onBackToStudy}
            activeOpacity={0.7}
          >
            <Text style={styles.backBtnText}>✕</Text>
          </TouchableOpacity>
        )}
      </View>

      {/* Language Switcher Bar */}
      <View style={styles.langBar}>
        <View style={styles.langPill}>
          <Text style={styles.langFlag}>{sourceLang === 'et' ? '🇪🇪' : '🇷🇺'}</Text>
          <Text style={styles.langName}>{sourceLang === 'et' ? 'Эстонский' : 'Русский'}</Text>
        </View>

        <TouchableOpacity
          style={styles.swapBtn}
          onPress={handleSwapLanguages}
          activeOpacity={0.75}
          accessibilityLabel="Поменять языки местами"
        >
          <Text style={styles.swapIcon}>⇄</Text>
        </TouchableOpacity>

        <View style={styles.langPill}>
          <Text style={styles.langFlag}>{targetLang === 'et' ? '🇪🇪' : '🇷🇺'}</Text>
          <Text style={styles.langName}>{targetLang === 'et' ? 'Эстонский' : 'Русский'}</Text>
        </View>
      </View>

      {/* Text Input Card (Nordic Clean borderRadius: 20) */}
      <View style={styles.inputCard}>
        <TextInput
          style={styles.input}
          placeholder={
            sourceLang === 'et'
              ? 'Введите слово, правило или фразу на эстонском...'
              : 'Введите школьный термин или фразу на русском...'
          }
          placeholderTextColor={darkTheme.textMuted}
          value={inputText}
          onChangeText={setInputText}
          multiline
          returnKeyType="done"
          blurOnSubmit
          onSubmitEditing={() => handleTranslate()}
        />

        {/* Input Tools Row */}
        <View style={styles.inputToolsRow}>
          <View style={styles.toolsLeft}>
            {inputText.length > 0 && (
              <TouchableOpacity
                style={styles.toolChip}
                onPress={handleClear}
                activeOpacity={0.7}
              >
                <Text style={styles.toolChipText}>✕ Очистить</Text>
              </TouchableOpacity>
            )}

            <TouchableOpacity
              style={styles.toolChip}
              onPress={handlePasteClipboard}
              activeOpacity={0.7}
            >
              <Text style={styles.toolChipText}>📋 Вставить</Text>
            </TouchableOpacity>

            <TouchableOpacity
              style={styles.toolChipCamera}
              onPress={handleCaptureCamera}
              activeOpacity={0.75}
            >
              <Text style={styles.toolChipCameraText}>📷 Снять текст</Text>
            </TouchableOpacity>
          </View>

          {/* Action button: Translate */}
          <TouchableOpacity
            style={[
              styles.translateBtn,
              isLoading && styles.translateBtnDisabled,
            ]}
            onPress={() => handleTranslate()}
            disabled={isLoading}
            activeOpacity={0.85}
          >
            {isLoading ? (
              <ActivityIndicator size="small" color="#064E3B" />
            ) : (
              <Text style={styles.translateBtnText}>⚡ Перевести</Text>
            )}
          </TouchableOpacity>
        </View>
      </View>

      {/* Result Card (Card with Onsen accents) */}
      {result ? (
        <View style={styles.resultCard}>
          <View style={styles.resultHeader}>
            <View style={styles.resultBadge}>
              <Text style={styles.resultBadgeText}>
                {targetLang === 'et' ? 'TÕLGE (ЭСТОНСКИЙ)' : 'ПЕРЕВОД (РУССКИЙ)'}
              </Text>
            </View>

            {result.context_note ? (
              <View style={styles.contextBadge}>
                <Text style={styles.contextBadgeText}>🏷️ {result.context_note}</Text>
              </View>
            ) : null}
          </View>

          {/* Main Translated Text */}
          <Text style={styles.translatedText} selectable>
            {result.translated_text}
          </Text>

          {/* Base Forms (Algvormid) Pill */}
          {result.base_forms ? (
            <View style={styles.baseFormsBox}>
              <Text style={styles.baseFormsLabel}>📖 Словарные формы (algvormid):</Text>
              <Text style={styles.baseFormsValue} selectable>
                {result.base_forms}
              </Text>
            </View>
          ) : null}

          {/* Actions Row (Voice, Copy, Save to Vocab) */}
          <View style={styles.resultActionsRow}>
            {/* 🔊 Voice Button */}
            <TouchableOpacity
              style={[
                styles.actionBtn,
                isPlayingAudio && styles.actionBtnActive,
              ]}
              onPress={handleToggleVoice}
              activeOpacity={0.8}
            >
              <Text style={styles.actionBtnText}>
                {isPlayingAudio ? '⏹ Стоп' : '🔊 Озвучить'}
              </Text>
            </TouchableOpacity>

            {/* 📋 Copy Button */}
            <TouchableOpacity
              style={[
                styles.actionBtn,
                isCopied && styles.actionBtnSuccess,
              ]}
              onPress={handleCopyResult}
              activeOpacity={0.8}
            >
              <Text style={styles.actionBtnText}>
                {isCopied ? '✓ Скопировано' : '📋 Копировать'}
              </Text>
            </TouchableOpacity>

            {/* ⭐ In Dictionary Button */}
            <TouchableOpacity
              style={[
                styles.actionBtn,
                styles.actionBtnVocab,
                isSavedToVocab && styles.actionBtnVocabSaved,
              ]}
              onPress={handleSaveToVocabulary}
              disabled={isSavedToVocab}
              activeOpacity={0.8}
            >
              <Text
                style={[
                  styles.actionBtnText,
                  styles.actionBtnVocabText,
                  isSavedToVocab && styles.actionBtnVocabSavedText,
                ]}
              >
                {isSavedToVocab ? '✓ В словарике' : '⭐ В словарик'}
              </Text>
            </TouchableOpacity>
          </View>
        </View>
      ) : null}
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    paddingHorizontal: 16,
    paddingTop: 12,
    paddingBottom: 24,
    backgroundColor: darkTheme.background,
  },
  topBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: darkTheme.cardBackground,
    borderRadius: 20,
    paddingHorizontal: 16,
    paddingVertical: 14,
    marginBottom: 12,
    borderWidth: 1,
    borderColor: darkTheme.cardBorder,
    ...Theme.shadow.card,
  },
  titleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    flex: 1,
  },
  bannerEmoji: {
    fontSize: 28,
  },
  bannerTitle: {
    fontSize: 16,
    fontWeight: '700',
    color: darkTheme.textPrimary,
  },
  bannerSubtitle: {
    fontSize: 12,
    fontWeight: '500',
    color: darkTheme.textSecondary,
    marginTop: 1,
  },
  backBtn: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: darkTheme.badgeFreeBg,
    alignItems: 'center',
    justifyContent: 'center',
  },
  backBtnText: {
    fontSize: 14,
    fontWeight: '700',
    color: darkTheme.textSecondary,
  },
  langBar: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: darkTheme.cardBackground,
    borderRadius: 20,
    paddingHorizontal: 12,
    paddingVertical: 8,
    marginBottom: 12,
    borderWidth: 1,
    borderColor: darkTheme.cardBorder,
  },
  langPill: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 10,
    backgroundColor: Theme.colors.surfaceAlt,
  },
  langFlag: {
    fontSize: 16,
  },
  langName: {
    fontSize: 14,
    fontWeight: '700',
    color: darkTheme.textPrimary,
  },
  swapBtn: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: darkTheme.badgeFreeBg,
    borderWidth: 1,
    borderColor: darkTheme.cardBorder,
    alignItems: 'center',
    justifyContent: 'center',
  },
  swapIcon: {
    fontSize: 18,
    fontWeight: '800',
    color: darkTheme.badgeFreeText,
  },
  inputCard: {
    backgroundColor: darkTheme.cardBackground,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: darkTheme.cardBorder,
    padding: 14,
    marginBottom: 14,
    ...Theme.shadow.card,
  },
  input: {
    fontSize: 16,
    lineHeight: 22,
    color: darkTheme.textPrimary,
    minHeight: 88,
    textAlignVertical: 'top',
  },
  inputToolsRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginTop: 10,
    paddingTop: 10,
    borderTopWidth: 1,
    borderTopColor: darkTheme.cardBorder,
    flexWrap: 'wrap',
    gap: 8,
  },
  toolsLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    flexWrap: 'wrap',
  },
  toolChip: {
    backgroundColor: darkTheme.badgeFreeBg,
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 8,
  },
  toolChipText: {
    fontSize: 12,
    fontWeight: '600',
    color: darkTheme.textSecondary,
  },
  toolChipCamera: {
    backgroundColor: '#1E293B',
    borderWidth: 1,
    borderColor: '#3B82F6',
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 8,
  },
  toolChipCameraText: {
    fontSize: 12,
    fontWeight: '700',
    color: '#60A5FA',
  },
  translateBtn: {
    backgroundColor: darkTheme.accent,
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderRadius: 10,
    alignItems: 'center',
    justifyContent: 'center',
    minWidth: 110,
  },
  translateBtnDisabled: {
    opacity: 0.6,
  },
  translateBtnText: {
    fontSize: 13.5,
    fontWeight: '800',
    color: darkTheme.accentText,
  },
  resultCard: {
    backgroundColor: darkTheme.cardBackground,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: darkTheme.cardBorder,
    padding: 16,
    ...Theme.shadow.card,
  },
  resultHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 10,
    flexWrap: 'wrap',
    gap: 6,
  },
  resultBadge: {
    backgroundColor: darkTheme.badgeFreeBg,
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 6,
  },
  resultBadgeText: {
    fontSize: 10.5,
    fontWeight: '800',
    color: darkTheme.badgeFreeText,
    letterSpacing: 0.4,
  },
  contextBadge: {
    backgroundColor: darkTheme.badgeFreeBg,
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 6,
  },
  contextBadgeText: {
    fontSize: 11,
    fontWeight: '600',
    color: darkTheme.textSecondary,
  },
  translatedText: {
    fontSize: 20,
    lineHeight: 28,
    fontWeight: '700',
    color: darkTheme.textPrimary,
    marginBottom: 12,
  },
  baseFormsBox: {
    backgroundColor: Theme.colors.surfaceAlt,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: darkTheme.cardBorder,
    padding: 10,
    marginBottom: 14,
  },
  baseFormsLabel: {
    fontSize: 11,
    fontWeight: '700',
    color: darkTheme.textSecondary,
    marginBottom: 2,
    textTransform: 'uppercase',
  },
  baseFormsValue: {
    fontSize: 14,
    fontWeight: '600',
    color: darkTheme.textPrimary,
    fontStyle: 'italic',
  },
  resultActionsRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    flexWrap: 'wrap',
  },
  actionBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: darkTheme.badgeFreeBg,
    borderWidth: 1,
    borderColor: darkTheme.cardBorder,
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 7,
  },
  actionBtnActive: {
    backgroundColor: 'rgba(95, 237, 197, 0.2)',
    borderColor: darkTheme.accent,
  },
  actionBtnSuccess: {
    backgroundColor: '#14532D',
    borderColor: '#22C55E',
  },
  actionBtnText: {
    fontSize: 12.5,
    fontWeight: '700',
    color: darkTheme.textPrimary,
  },
  actionBtnVocab: {
    backgroundColor: '#382A17',
    borderColor: '#78350F',
  },
  actionBtnVocabSaved: {
    backgroundColor: darkTheme.badgeFreeBg,
    borderColor: darkTheme.accent,
  },
  actionBtnVocabText: {
    color: '#FBBF24',
  },
  actionBtnVocabSavedText: {
    color: darkTheme.badgeFreeText,
  },
});
