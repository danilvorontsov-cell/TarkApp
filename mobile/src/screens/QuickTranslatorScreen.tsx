import React, { useState, useEffect } from 'react';
import {
  StyleSheet,
  View,
  Text,
  TextInput,
  TouchableOpacity,
  ActivityIndicator,
  Keyboard,
  Platform,
} from 'react-native';
import * as Clipboard from 'expo-clipboard';
import * as ImagePicker from 'expo-image-picker';
import { LinearGradient } from 'expo-linear-gradient';
import { Theme, darkTheme } from '../theme/colors';
import { quickTranslate, QuickTranslateResponse } from '../services/api';
import { optimizePageImage } from '../services/imageOptimizer';
import { StorageService } from '../services/storage';
import {
  playTts,
  stopTts,
  pauseTts,
  resumeTts,
  subscribePlaybackState,
  PlaybackState,
} from '../services/audioPlayer';
import { normalizeTextForTTS } from '../components/PhraseBuilder';
import { VocabularyItem } from '../types';
import { ThemedAlert } from '../components/ThemedAlert';

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
  const [audioPlaybackState, setAudioPlaybackState] = useState<PlaybackState>('idle');

  useEffect(() => {
    const unsubscribe = subscribePlaybackState((state, playingId) => {
      if (playingId === 'quick_translator') {
        setAudioPlaybackState(state);
      } else {
        setAudioPlaybackState('idle');
      }
    });
    return () => {
      unsubscribe();
    };
  }, []);

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
      ThemedAlert.alert('Введите текст', 'Пожалуйста, введите слово, фразу или сделайте снимок текста учебника.');
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
      ThemedAlert.alert(
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
    setAudioPlaybackState('idle');
  };

  // Снимок текста через камеру
  const handleCaptureCamera = async () => {
    try {
      const perm = await ImagePicker.requestCameraPermissionsAsync();
      if (!perm.granted) {
        ThemedAlert.alert(
          'Доступ к камере',
          'Разрешите приложению доступ к камере, чтобы фотографировать фрагменты учебника.'
        );
        return;
      }

      const photo = await ImagePicker.launchCameraAsync({
        mediaTypes: ['images'],
        allowsEditing: true,
        quality: 1,
      });

      if (photo.canceled || !photo.assets || photo.assets.length === 0) {
        return;
      }

      const asset = photo.assets[0];
      const opt = await optimizePageImage(asset.uri, asset.width, asset.height);
      if (opt.base64) {
        await handleTranslate(undefined, opt.base64);
      }
    } catch (err: any) {
      ThemedAlert.alert('Ошибка камеры', err.message || 'Не удалось сделать фото.');
    }
  };

  // Определяем, какой из текстов является эстонским, а какой русским
  const getLanguagePairs = (res: QuickTranslateResponse) => {
    // 1. По явному определению языка от сервера
    if (res.source_lang === 'et') {
      return { estText: res.original_text, ruText: res.translated_text };
    }
    if (res.target_lang === 'et') {
      return { estText: res.translated_text, ruText: res.original_text };
    }
    // 2. Эвристика по алфавиту: если один текст на кириллице, а второй нет
    const origHasCyrillic = /[а-яА-ЯёЁ]/.test(res.original_text);
    const transHasCyrillic = /[а-яА-ЯёЁ]/.test(res.translated_text);
    if (!origHasCyrillic && transHasCyrillic) {
      return { estText: res.original_text, ruText: res.translated_text };
    }
    if (origHasCyrillic && !transHasCyrillic) {
      return { estText: res.translated_text, ruText: res.original_text };
    }
    // 3. Fallback по выбранному направлению перевода
    if (sourceLang === 'et') {
      return { estText: res.original_text, ruText: res.translated_text };
    }
    return { estText: res.translated_text, ruText: res.original_text };
  };

  // Озвучивание (с поддержкой паузы/продолжения и внешних системных прерываний)
  const handleToggleVoice = async () => {
    if (audioPlaybackState === 'playing') {
      await pauseTts();
      return;
    }
    if (audioPlaybackState === 'paused') {
      await resumeTts();
      return;
    }

    if (!result) return;

    // Озвучиваем эстонское слово для тренировки произношения (kiirhääldus)
    const { estText } = getLanguagePairs(result);
    const cleanEstText = normalizeTextForTTS(
      (estText || '').replace(/<\/?[^>]+(>|$)/g, '').trim()
    );
    if (!cleanEstText) return;

    try {
      const player = await playTts(cleanEstText, 'et', 'quick_translator', {
        onFinish: () => setAudioPlaybackState('idle'),
        onError: () => setAudioPlaybackState('idle'),
      });
      if (!player) {
        setAudioPlaybackState('idle');
      }
    } catch {
      setAudioPlaybackState('idle');
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

    const { estText, ruText } = getLanguagePairs(result);
    const cleanEst = (estText || '').replace(/<\/?[^>]+(>|$)/g, '').trim();
    const cleanRu = (ruText || '').replace(/<\/?[^>]+(>|$)/g, '').trim();

    let exampleText = result.base_forms || '';
    if (result.context_note) {
      exampleText = exampleText
        ? `${exampleText} • ${result.context_note}`
        : result.context_note;
    }

    const item: VocabularyItem = {
      est: cleanEst,
      ru: cleanRu,
      example: exampleText || 'Быстрый перевод (Kiirtõlge)',
      topicTitle: 'Быстрый переводчик',
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
          <View style={{ flex: 1 }}>
            <Text style={styles.bannerTitle}>Быстрый школьный переводчик</Text>
            <Text style={styles.bannerSubtitle}>Kiirtõlge • адаптация терминов Эстонии</Text>
          </View>
        </View>
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
        {inputText.length > 0 && (
          <View style={styles.inputHeaderRow}>
            <TouchableOpacity onPress={handleClear} activeOpacity={0.7} hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}>
              <Text style={styles.clearInputText}>✕ Очистить поле</Text>
            </TouchableOpacity>
          </View>
        )}

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

        {/* Input Tools Row: Вставить и Снять текст (flex: 1 каждая, зазор строго по центру) */}
        <View style={styles.toolsRowHalf}>
          <TouchableOpacity
            style={styles.toolChipHalf}
            onPress={handlePasteClipboard}
            activeOpacity={0.75}
          >
            <Text style={styles.toolChipHalfText}>📋 Вставить</Text>
          </TouchableOpacity>

          <TouchableOpacity
            style={styles.toolChipHalfCamera}
            onPress={handleCaptureCamera}
            activeOpacity={0.75}
          >
            <Text style={styles.toolChipHalfCameraText}>📷 Снять текст</Text>
          </TouchableOpacity>
        </View>

        {/* Action button: Translate (100% ширины от левого края до правого с вертикальным градиентом) */}
        <TouchableOpacity
          style={[
            styles.translateBtnFull,
            isLoading && styles.translateBtnDisabled,
          ]}
          onPress={() => handleTranslate()}
          disabled={isLoading}
          activeOpacity={0.85}
        >
          <LinearGradient
            colors={['#66F6CF', '#42DCA3']}
            start={{ x: 0, y: 0 }}
            end={{ x: 0, y: 1 }}
            style={styles.translateGradient}
          >
            {isLoading ? (
              <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8 }}>
                <ActivityIndicator size="small" color="#064E3B" />
                <Text style={styles.translateBtnFullText}>Переводим...</Text>
              </View>
            ) : (
              <Text style={styles.translateBtnFullText}>⚡ Перевести</Text>
            )}
          </LinearGradient>
        </TouchableOpacity>
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

          {/* Unified Full-Width Audio Button at Top of Card */}
          <TouchableOpacity
            style={[
              styles.unifiedAudioBtn,
              audioPlaybackState === 'playing' && styles.unifiedAudioBtnActive,
              audioPlaybackState === 'paused' && styles.unifiedAudioBtnPaused,
            ]}
            onPress={handleToggleVoice}
            activeOpacity={0.85}
            accessibilityLabel="Озвучить перевод на эстонском"
          >
            <Text style={styles.unifiedAudioBtnText}>
              {audioPlaybackState === 'playing'
                ? '⏸ ПАУЗА'
                : audioPlaybackState === 'paused'
                ? '▶ ПРОДОЛЖИТЬ'
                : '▶ ОЗВУЧИТЬ'}
            </Text>
          </TouchableOpacity>

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

          {/* Actions Row (Copy, Save to Vocab) */}
          <View style={styles.resultActionsRow}>
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

      {/* Bottom Full-Width Close Button */}
      {onBackToStudy && (
        <TouchableOpacity
          style={styles.bottomCloseButton}
          onPress={onBackToStudy}
          activeOpacity={0.8}
        >
          <Text style={styles.bottomCloseButtonText}>Закрыть</Text>
        </TouchableOpacity>
      )}
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    paddingHorizontal: 16,
    paddingTop: 12,
    paddingBottom: 24,
    backgroundColor: 'transparent',
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
  inputHeaderRow: {
    flexDirection: 'row',
    justifyContent: 'flex-end',
    marginBottom: 6,
  },
  clearInputText: {
    fontSize: 12,
    fontWeight: '600',
    color: darkTheme.textMuted,
  },
  toolsRowHalf: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    marginTop: 10,
    paddingTop: 10,
    borderTopWidth: 1,
    borderTopColor: darkTheme.cardBorder,
  },
  toolChipHalf: {
    flex: 1,
    height: 44,
    backgroundColor: '#1E252B',
    borderRadius: 12,
    borderWidth: 1,
    borderColor: darkTheme.cardBorder,
    alignItems: 'center',
    justifyContent: 'center',
  },
  toolChipHalfText: {
    fontSize: 13,
    fontWeight: '700',
    color: '#CBD5E1',
  },
  toolChipHalfCamera: {
    flex: 1,
    height: 44,
    backgroundColor: 'rgba(59, 130, 246, 0.12)',
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#3B82F6',
    alignItems: 'center',
    justifyContent: 'center',
  },
  toolChipHalfCameraText: {
    fontSize: 13,
    fontWeight: '700',
    color: '#60A5FA',
  },
  translateBtnFull: {
    width: '100%',
    height: 48,
    borderRadius: 14,
    overflow: 'hidden',
    marginTop: 10,
    ...Theme.shadow.chip,
  },
  translateGradient: {
    width: '100%',
    height: '100%',
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: 14,
  },
  translateBtnFullText: {
    fontSize: 16,
    fontWeight: '800',
    color: '#064E3B',
  },
  translateBtnDisabled: {
    opacity: 0.6,
  },
  bottomCloseButton: {
    width: '100%',
    backgroundColor: darkTheme.cardBackground,
    borderWidth: 1,
    borderColor: darkTheme.cardBorder,
    borderRadius: 16,
    paddingVertical: 14,
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: 16,
    marginBottom: 8,
    ...Theme.shadow.card,
  },
  bottomCloseButtonText: {
    fontSize: 15,
    fontWeight: '700',
    color: '#CBD5E1',
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
  unifiedAudioBtn: {
    width: '100%',
    paddingVertical: 12,
    paddingHorizontal: 16,
    borderRadius: Theme.radius.button,
    backgroundColor: Theme.colors.voiceButton,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 12,
    ...Theme.shadow.chip,
  },
  unifiedAudioBtnActive: {
    backgroundColor: Theme.colors.voiceButtonPressed,
  },
  unifiedAudioBtnPaused: {
    backgroundColor: '#D97706',
  },
  unifiedAudioBtnText: {
    color: '#FFFFFF',
    fontWeight: '700',
    fontSize: 14,
    letterSpacing: 0.3,
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
