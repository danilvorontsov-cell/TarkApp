import React, { useState, useEffect, useRef } from 'react';
import {
  StyleSheet,
  Text,
  View,
  ScrollView,
  TouchableOpacity,
  TextInput,
  ActivityIndicator,
  Alert,
  Image,
  Platform,
  StatusBar as RNStatusBar,
} from 'react-native';
import {
  SafeAreaProvider,
  useSafeAreaInsets,
} from 'react-native-safe-area-context';
import { StatusBar } from 'expo-status-bar';
import * as ImagePicker from 'expo-image-picker';
import {
  AgeTier,
  UserProfile,
  PageAnalysisResponse,
  SavedLessonCard,
  VocabularyItem,
  getTierFromGrade,
  AGE_SUGGESTIONS,
} from './src/types';
import { StorageService } from './src/services/storage';
import { playTts, stopTts } from './src/services/audioPlayer';
import { API_BASE_URL, analyzePage } from './src/services/api';
import { PhraseBuilder } from './src/components/PhraseBuilder';

type TabType = 'study' | 'dictionary' | 'settings';
type Tab2Mode = 'vocab' | 'history';

interface SessionLesson {
  id: string;
  title: string;
  analysis: PageAnalysisResponse;
  imageUri: string | null;
  timestamp: number;
}

function MainApp() {
  const insets = useSafeAreaInsets();
  const [currentTab, setCurrentTab] = useState<TabType>('study');
  const [tab2Mode, setTab2Mode] = useState<Tab2Mode>('vocab');

  const [profile, setProfile] = useState<UserProfile>({
    grade: 3,
    tier: 'primary',
    interests: ['Minecraft', 'LEGO', 'Roblox'],
    nickname: 'Алекс',
  });

  const [interestsText, setInterestsText] = useState('Minecraft, LEGO, Roblox');
  const [loading, setLoading] = useState(false);
  const [loadingStep, setLoadingStep] = useState('');
  const [capturedImageUri, setCapturedImageUri] = useState<string | null>(null);
  const [playingId, setPlayingId] = useState<string | null>(null);
  const [analysis, setAnalysis] = useState<PageAnalysisResponse | null>(null);
  const [sessionLessons, setSessionLessons] = useState<SessionLesson[]>([]);
  const [isSaved, setIsSaved] = useState(false);
  const [history, setHistory] = useState<SavedLessonCard[]>([]);
  const [savedVocab, setSavedVocab] = useState<VocabularyItem[]>([]);
  const [expandedWord, setExpandedWord] = useState<string | null>(null);

  const scrollViewRef = useRef<React.ElementRef<typeof ScrollView>>(null);
  const isJunior = profile.tier === 'primary';

  useEffect(() => {
    StorageService.getProfile().then((saved) => {
      setProfile(saved);
      if (saved.interests && saved.interests.length > 0) {
        setInterestsText(saved.interests.join(', '));
      }
    });

    StorageService.getHistory().then((h) => {
      setHistory(h);
      // Pre-fill today's session lessons from local history
      const startOfToday = new Date();
      startOfToday.setHours(0, 0, 0, 0);
      const todayItems: SessionLesson[] = h
        .filter((c) => c.timestamp >= startOfToday.getTime())
        .map((c) => ({
          id: c.id,
          title: c.task_title,
          analysis: c.analysis,
          imageUri: c.imageUri || null,
          timestamp: c.timestamp,
        }));

      if (todayItems.length > 0) {
        setSessionLessons(todayItems);
        // Load the latest one into current view
        setAnalysis(todayItems[0].analysis);
        setCapturedImageUri(todayItems[0].imageUri);
        setIsSaved(true);
      }
    });

    StorageService.getSavedVocabulary().then((v) => {
      setSavedVocab(v);
    });

    return () => {
      stopTts();
    };
  }, []);

  const scrollToTaskTop = () => {
    setTimeout(() => {
      scrollViewRef.current?.scrollTo({ y: 0, animated: true });
    }, 120);
  };

  const handlePlayAudio = async (text: string, lang: 'ru' | 'et', id: string) => {
    try {
      if (playingId === id) {
        await stopTts();
        setPlayingId(null);
        return;
      }

      await playTts(text, lang, id, {
        onStart: () => setPlayingId(id),
        onFinish: () => setPlayingId(null),
        onError: () => {
          setPlayingId(null);
          Alert.alert('Аудио', 'Не удалось воспроизвести аудиопоток. Проверьте подключение к бэкенду.');
        },
      });
    } catch (err: any) {
      setPlayingId(null);
      Alert.alert('Аудио', `Ошибка воспроизведения: ${err?.message || 'Сбой сети'}`);
    }
  };

  const updateGrade = (grade: number) => {
    const newTier = getTierFromGrade(grade);
    const updated = { ...profile, grade, tier: newTier };
    setProfile(updated);
    StorageService.saveProfile(updated);
  };

  const handleInterestsChange = (text: string) => {
    setInterestsText(text);
    const parsed = text
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean);
    const updated = { ...profile, interests: parsed };
    setProfile(updated);
    StorageService.saveProfile(updated);
  };

  const handleAddSuggestion = (item: string) => {
    const currentList = profile.interests || [];
    const exists = currentList.some(
      (i) => i.toLowerCase() === item.toLowerCase()
    );
    let newList: string[];
    if (exists) {
      newList = currentList.filter(
        (i) => i.toLowerCase() !== item.toLowerCase()
      );
    } else {
      newList = [...currentList, item];
    }
    const newText = newList.join(', ');
    setInterestsText(newText);
    const updated = { ...profile, interests: newList };
    setProfile(updated);
    StorageService.saveProfile(updated);
  };

  const updateNickname = (nickname: string) => {
    const updated = { ...profile, nickname };
    setProfile(updated);
    StorageService.saveProfile(updated);
  };

  // Helper to persist to history and update session lessons list
  const recordNewLesson = async (data: PageAnalysisResponse, imageUri: string | null) => {
    const now = new Date();
    const months = ['янв', 'фев', 'мар', 'апр', 'мая', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'];
    const dateFormatted = `${now.getDate()} ${months[now.getMonth()]}, ${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;

    let taskType = 'Koolitöö';
    const titleLower = data.task_title.toLowerCase();
    if (titleLower.startsWith('avastus:')) {
      taskType = 'Maailma Avastaja';
    } else if (titleLower.includes('loodus') || titleLower.includes('looma') || titleLower.includes('ilm')) {
      taskType = 'Loodusõpetus';
    }

    const newId = `card_${Date.now()}`;
    const card: SavedLessonCard = {
      id: newId,
      timestamp: Date.now(),
      dateFormatted,
      grade: profile.grade,
      tier: profile.tier,
      task_title: data.task_title,
      task_type: taskType,
      analysis: data,
      imageUri: imageUri || undefined,
    };

    // Auto-save to AsyncStorage
    await StorageService.saveLessonToHistory(card);
    setIsSaved(true);

    const updatedHistory = await StorageService.getHistory();
    setHistory(updatedHistory);
    const updatedVocab = await StorageService.getSavedVocabulary();
    setSavedVocab(updatedVocab);

    // Update today's session lessons list
    const newSessionItem: SessionLesson = {
      id: newId,
      title: data.task_title,
      analysis: data,
      imageUri,
      timestamp: Date.now(),
    };

    setSessionLessons((prev) => {
      const filtered = prev.filter((p) => p.title !== data.task_title);
      return [newSessionItem, ...filtered];
    });

    scrollToTaskTop();
  };

  const processImageAnalysis = async (asset: ImagePicker.ImagePickerAsset) => {
    setLoading(true);
    setLoadingStep('Разбираем материал...');
    try {
      let data: PageAnalysisResponse;

      if (asset.base64) {
        const res = await fetch(`${API_BASE_URL}/api/v1/analyze-page/json`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            image_base64: asset.base64,
            mime_type: asset.mimeType || 'image/jpeg',
            grade: profile.grade,
            tier: profile.tier,
            interests: profile.interests,
            nickname: profile.nickname,
          }),
        });

        if (!res.ok) {
          let errorMsg = `Статус ${res.status}`;
          try {
            const errData = await res.json();
            if (errData.detail) errorMsg = errData.detail;
          } catch {}
          throw new Error(errorMsg);
        }

        data = await res.json();
      } else {
        data = await analyzePage(asset.uri, profile, API_BASE_URL);
      }

      setAnalysis(data);
      await recordNewLesson(data, asset.uri);
    } catch (err: any) {
      Alert.alert(
        'Ошибка анализа страницы',
        `Не удалось разобрать изображение: ${err?.message || 'Ошибка сети'}\n\nПроверьте, что сервер запущен по адресу:\n${API_BASE_URL}`
      );
    } finally {
      setLoading(false);
      setLoadingStep('');
    }
  };

  const handleTakePhoto = async () => {
    try {
      const permission = await ImagePicker.requestCameraPermissionsAsync();
      if (!permission.granted) {
        Alert.alert(
          'Доступ к камере',
          'TarkApp требуется доступ к камере для фото учебников или тетрадей. Разрешите его в настройках устройства.'
        );
        return;
      }

      const result = await ImagePicker.launchCameraAsync({
        mediaTypes: ['images'],
        allowsEditing: true,
        quality: 0.8,
        base64: true,
      });

      if (result.canceled || !result.assets || result.assets.length === 0) {
        return;
      }

      const asset = result.assets[0];
      setCapturedImageUri(asset.uri);
      await processImageAnalysis(asset);
    } catch (err: any) {
      Alert.alert('Камера', `Не удалось запустить камеру: ${err?.message || 'Неизвестная ошибка'}`);
    }
  };

  const handlePickImage = async () => {
    try {
      const permission = await ImagePicker.requestMediaLibraryPermissionsAsync();
      if (!permission.granted) {
        Alert.alert(
          'Доступ к галерее',
          'TarkApp требуется доступ к галерее фото. Пожалуйста, разрешите его в настройках.'
        );
        return;
      }

      const result = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ['images'],
        allowsEditing: true,
        quality: 0.8,
        base64: true,
      });

      if (result.canceled || !result.assets || result.assets.length === 0) {
        return;
      }

      const asset = result.assets[0];
      setCapturedImageUri(asset.uri);
      await processImageAnalysis(asset);
    } catch (err: any) {
      Alert.alert('Галерея', `Не удалось открыть галерею: ${err?.message || 'Неизвестная ошибка'}`);
    }
  };

  const handleRunDemoAnalysis = async () => {
    setLoading(true);
    setLoadingStep('Генерируем демо-разбор...');
    try {
      const dummyBase64 =
        'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==';

      const res = await fetch(`${API_BASE_URL}/api/v1/analyze-page/json`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          image_base64: dummyBase64,
          mime_type: 'image/png',
          grade: profile.grade,
          tier: profile.tier,
          interests: profile.interests,
          nickname: profile.nickname,
        }),
      });

      if (!res.ok) {
        throw new Error(`Ошибка сервера: ${res.status}`);
      }

      const data: PageAnalysisResponse = await res.json();
      setAnalysis(data);
      await recordNewLesson(data, null);
    } catch (err: any) {
      Alert.alert(
        'TarkApp',
        `Подключение к бэкенду (${API_BASE_URL}): ${err.message || 'Ошибка сети'}. Убедитесь, что бэкенд запущен.`
      );
    } finally {
      setLoading(false);
      setLoadingStep('');
    }
  };

  const handleSaveCard = async () => {
    if (!analysis) return;
    try {
      const now = new Date();
      const months = ['янв', 'фев', 'мар', 'апр', 'мая', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'];
      const dateFormatted = `${now.getDate()} ${months[now.getMonth()]}, ${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;

      let taskType = 'Koolitöö';
      const titleLower = analysis.task_title.toLowerCase();
      if (titleLower.startsWith('avastus:')) {
        taskType = 'Maailma Avastaja';
      } else if (titleLower.includes('loodus') || titleLower.includes('looma') || titleLower.includes('ilm')) {
        taskType = 'Loodusõpetus';
      }

      const card: SavedLessonCard = {
        id: `card_${Date.now()}`,
        timestamp: Date.now(),
        dateFormatted,
        grade: profile.grade,
        tier: profile.tier,
        task_title: analysis.task_title,
        task_type: taskType,
        analysis,
        imageUri: capturedImageUri || undefined,
      };

      await StorageService.saveLessonToHistory(card);
      setIsSaved(true);
      const updatedHistory = await StorageService.getHistory();
      setHistory(updatedHistory);
      const updatedVocab = await StorageService.getSavedVocabulary();
      setSavedVocab(updatedVocab);
      Alert.alert(
        '⭐ Сохранено в историю!',
        'Разбор урока и все новые слова сохранены в историю и словарик устройства.'
      );
    } catch (err: any) {
      Alert.alert('Ошибка', 'Не удалось сохранить урок в историю.');
    }
  };

  const handleSelectSessionLesson = (item: SessionLesson) => {
    setAnalysis(item.analysis);
    setCapturedImageUri(item.imageUri);
    setIsSaved(true);
    scrollToTaskTop();
  };

  const handleOpenHistoryItem = (item: SavedLessonCard) => {
    setAnalysis(item.analysis);
    setCapturedImageUri(item.imageUri || null);
    setIsSaved(true);
    setCurrentTab('study');
    scrollToTaskTop();
  };

  const handleDeleteHistoryItem = async (id: string) => {
    await StorageService.deleteLessonFromHistory(id);
    const updated = await StorageService.getHistory();
    setHistory(updated);
    if (analysis) {
      const stillSaved = updated.some((h) => h.task_title === analysis.task_title);
      setIsSaved(stillSaved);
    }
  };

  const handleWordTap = (item: VocabularyItem) => {
    if (expandedWord === item.est) {
      setExpandedWord(null);
    } else {
      setExpandedWord(item.est);
      // Auto pronounce Estonian word with +20% volume
      handlePlayAudio(item.est, 'et', `saved_vocab_${item.est}`);
    }
  };

  const handleDeleteVocabWord = async (estTerm: string) => {
    await StorageService.removeVocabularyItem(estTerm);
    const updated = await StorageService.getSavedVocabulary();
    setSavedVocab(updated);
  };

  const handleClearAllData = () => {
    Alert.alert(
      'Очистить историю и словарь?',
      'Это действие удалит сохранённые уроки и словарь из памяти телефона. Настройки профиля сохранятся.',
      [
        { text: 'Отмена', style: 'cancel' },
        {
          text: 'Очистить',
          style: 'destructive',
          onPress: async () => {
            await StorageService.clearAll();
            setHistory([]);
            setSavedVocab([]);
            setSessionLessons([]);
            setAnalysis(null);
            setCapturedImageUri(null);
            setIsSaved(false);
            Alert.alert('Готово', 'История и словарик очищены.');
          },
        },
      ]
    );
  };

  const getTierBadgeText = (tier: AgeTier) => {
    switch (tier) {
      case 'primary':
        return 'Младшее звено (1–4 классы)';
      case 'middle':
        return 'Среднее звено (5–9 классы)';
      case 'gymnasium':
        return 'Гимназия (10–12 классы)';
    }
  };

  const currentSuggestions = AGE_SUGGESTIONS[profile.tier] || [];

  // ==========================================
  // TAB 1: STUDY (УЧЁБА)
  // ==========================================
  const renderStudyTab = () => (
    <View>
      {/* Header */}
      <View style={styles.header}>
        <View style={styles.headerTopRow}>
          <Text style={[styles.appTitle, isJunior && styles.appTitleJunior]}>
            {isJunior ? '✨ 🇪🇪 TarkApp' : '🇪🇪 TarkApp'}
          </Text>
          <TouchableOpacity
            style={[styles.pupilPill, isJunior && styles.pupilPillJunior]}
            onPress={() => setCurrentTab('settings')}
          >
            <Text style={[styles.pupilPillText, isJunior && styles.pupilPillTextJunior]}>
              👤 {profile.nickname || 'Ученик'} • {profile.grade} кл.
            </Text>
          </TouchableOpacity>
        </View>
        <Text style={[styles.subtitle, isJunior && styles.subtitleJunior]}>
          {isJunior
            ? 'Твой добрый помощник по эстонским урокам!'
            : 'Адаптационный тьютор по эстонской школьной программе'}
        </Text>
      </View>

      {/* Сегодняшний урок - Session Carousel Bar */}
      {sessionLessons.length > 0 && (
        <View style={[styles.todaySection, isJunior && styles.todaySectionJunior]}>
          <View style={styles.todayHeaderRow}>
            <Text style={[styles.todayTitle, isJunior && styles.todayTitleJunior]}>
              🎒 Сегодняшний урок ({sessionLessons.length})
            </Text>
            <Text style={styles.todaySubtitle}>Нажми на карточку, чтобы переключить задание</Text>
          </View>
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={styles.todayCarousel}
          >
            {sessionLessons.map((item, idx) => {
              const isActive = analysis?.task_title === item.title;
              return (
                <TouchableOpacity
                  key={item.id}
                  style={[
                    styles.todayCard,
                    isJunior && styles.todayCardJunior,
                    isActive && (isJunior ? styles.todayCardActiveJunior : styles.todayCardActiveSenior),
                  ]}
                  onPress={() => handleSelectSessionLesson(item)}
                  activeOpacity={0.8}
                >
                  {item.imageUri ? (
                    <Image source={{ uri: item.imageUri }} style={styles.todayThumbnail} resizeMode="cover" />
                  ) : (
                    <View style={styles.todayThumbPlaceholder}>
                      <Text style={styles.todayThumbPlaceholderText}>📖</Text>
                    </View>
                  )}
                  <View style={styles.todayCardInfo}>
                    <View style={styles.todayCardBadgeRow}>
                      <View style={[styles.todayBadge, isActive && styles.todayBadgeActive]}>
                        <Text style={[styles.todayBadgeText, isActive && styles.todayBadgeTextActive]}>
                          № {sessionLessons.length - idx}
                        </Text>
                      </View>
                      {isActive && (
                        <Text style={styles.todayActiveDot}>● Активно</Text>
                      )}
                    </View>
                    <Text
                      style={[
                        styles.todayCardTitle,
                        isJunior && styles.todayCardTitleJunior,
                        isActive && styles.todayCardTitleActive,
                      ]}
                      numberOfLines={2}
                    >
                      {item.title}
                    </Text>
                  </View>
                </TouchableOpacity>
              );
            })}
          </ScrollView>
        </View>
      )}

      {/* Welcome banner if no analysis yet */}
      {!analysis && !loading && sessionLessons.length === 0 && (
        <View style={[styles.welcomeCard, isJunior ? styles.welcomeCardJunior : styles.welcomeCardSenior]}>
          <Text style={styles.welcomeIcon}>📖 🇪🇪</Text>
          <Text style={[styles.welcomeTitle, isJunior && styles.welcomeTitleJunior]}>
            Готов учиться вместе?
          </Text>
          <Text style={styles.welcomeDesc}>
            Сфотографируй страницу учебника или тетради. TarkApp объяснит суть темы простыми словами, переведёт эстонские термины и поможет составить правильный ответ!
          </Text>
        </View>
      )}

      {/* Photo Preview Thumbnail if active task has an image */}
      {capturedImageUri && (
        <View style={[styles.previewCard, isJunior && styles.previewCardJunior]}>
          <Image source={{ uri: capturedImageUri }} style={styles.previewImage} resizeMode="cover" />
          <View style={styles.previewContent}>
            <Text style={styles.previewLabel}>📸 Снимок текущего материала</Text>
            <TouchableOpacity
              style={styles.retakeBtn}
              onPress={handleTakePhoto}
              disabled={loading}
            >
              <Text style={styles.retakeBtnText}>🔄 Переснять</Text>
            </TouchableOpacity>
          </View>
        </View>
      )}

      {/* Action Buttons Section */}
      <View style={styles.actionsContainer}>
        {/* Main Primary Button: Device Camera */}
        <TouchableOpacity
          style={[
            styles.actionButton,
            isJunior ? styles.actionButtonJunior : styles.actionButtonSenior,
          ]}
          onPress={handleTakePhoto}
          disabled={loading}
        >
          {loading ? (
            <View style={styles.loadingRow}>
              <ActivityIndicator color="#fff" size="small" />
              <Text
                style={[
                  styles.actionButtonText,
                  isJunior && styles.actionButtonTextJunior,
                  styles.loadingText,
                ]}
              >
                {loadingStep || 'Анализируем...'}
              </Text>
            </View>
          ) : (
            <Text
              style={[
                styles.actionButtonText,
                isJunior && styles.actionButtonTextJunior,
              ]}
            >
              {isJunior
                ? '📷 Сфотографировать страничку (Камера)'
                : '📷 Сфотографировать страницу (Камера)'}
            </Text>
          )}
        </TouchableOpacity>

        {/* Secondary Buttons Row: Gallery & Demo */}
        <View style={styles.secondaryRow}>
          <TouchableOpacity
            style={[
              styles.secondaryButton,
              isJunior && styles.secondaryButtonJunior,
            ]}
            onPress={handlePickImage}
            disabled={loading}
          >
            <Text
              style={[
                styles.secondaryButtonText,
                isJunior && styles.secondaryButtonTextJunior,
              ]}
            >
              🖼️ Из галереи
            </Text>
          </TouchableOpacity>

          <TouchableOpacity
            style={[
              styles.secondaryButton,
              isJunior && styles.secondaryButtonJunior,
            ]}
            onPress={handleRunDemoAnalysis}
            disabled={loading}
          >
            <Text
              style={[
                styles.secondaryButtonText,
                isJunior && styles.secondaryButtonTextJunior,
              ]}
            >
              ✨ Тестовое демо
            </Text>
          </TouchableOpacity>
        </View>
      </View>

      {/* Analysis Results View */}
      {analysis && (
        <View style={[styles.resultCard, isJunior ? styles.resultCardJunior : styles.resultCardSenior]}>
          <View style={styles.resultHeader}>
            <Text style={[styles.resultTitle, isJunior && styles.resultTitleJunior]}>
              {analysis.task_title}
            </Text>
            <Text style={styles.tierBadge}>
              {getTierBadgeText(profile.tier)}
            </Text>
          </View>

          {/* Accent Audio Box for Junior (1-4) at the TOP */}
          {isJunior && (
            <View style={styles.juniorVoiceHeroBox}>
              <View style={styles.voiceHeroHeader}>
                <Text style={styles.voiceHeroBadge}>🎧 ДЛЯ 1–4 КЛАССОВ</Text>
                <Text style={styles.voiceHeroTitle}>
                  {playingId === 'voice_prompt' ? '🔊 Воспроизведение...' : 'Послушай подсказку голосом:'}
                </Text>
              </View>
              <Text style={styles.voiceScriptJunior}>
                {analysis.voice_prompt_script}
              </Text>
              <TouchableOpacity
                style={[
                  styles.voiceBigPlayButton,
                  playingId === 'voice_prompt' && styles.voiceBigPlayButtonActive,
                ]}
                onPress={() =>
                  handlePlayAudio(analysis.voice_prompt_script, 'ru', 'voice_prompt')
                }
              >
                <Text style={styles.voiceBigPlayText}>
                  {playingId === 'voice_prompt' ? '⏹ ОСТАНОВИТЬ ОЗВУЧКУ' : '▶ СЛУШАТЬ ПОДСКАЗКУ'}
                </Text>
              </TouchableOpacity>
            </View>
          )}

          {/* Explanation */}
          <View style={styles.section}>
            <View style={styles.sectionHeaderRow}>
              <Text style={[styles.sectionHeader, isJunior && styles.sectionHeaderJunior]}>
                💡 Суть темы простыми словами
              </Text>
              <TouchableOpacity
                style={[
                  styles.sectionAudioBtn,
                  isJunior && styles.sectionAudioBtnJunior,
                  playingId === 'theme_explanation' && styles.sectionAudioBtnActive,
                ]}
                onPress={() =>
                  handlePlayAudio(analysis.theme_explanation, 'ru', 'theme_explanation')
                }
                accessibilityLabel="Озвучить суть темы"
              >
                <Text style={[styles.sectionAudioBtnText, isJunior && styles.sectionAudioBtnTextJunior]}>
                  {playingId === 'theme_explanation' ? '⏹ Стоп' : '🔊 Озвучить'}
                </Text>
              </TouchableOpacity>
            </View>
            <Text style={[styles.explanationText, isJunior && styles.explanationTextJunior]}>
              {analysis.theme_explanation}
            </Text>
          </View>

          {/* Vocabulary with Word and Example Pronunciation */}
          <View style={styles.section}>
            <Text style={[styles.sectionHeader, isJunior && styles.sectionHeaderJunior]}>
              📚 Словарь урока (Sõnastik)
            </Text>
            {analysis.vocabulary.map((v, idx) => {
              const isVocabPlaying = playingId === `vocab_${idx}`;
              const isExPlaying = playingId === `vocab_ex_${idx}`;
              return (
                <View key={idx} style={[styles.vocabItem, isJunior && styles.vocabItemJunior]}>
                  <View style={styles.vocabRow}>
                    <Text style={[styles.vocabEst, isJunior && styles.vocabEstJunior]}>
                      {v.est}
                    </Text>
                    {/* Speaker button for Estonian word */}
                    <TouchableOpacity
                      style={[
                        styles.vocabSpeakerBtn,
                        isVocabPlaying && styles.vocabSpeakerBtnActive,
                      ]}
                      onPress={() => handlePlayAudio(v.est, 'et', `vocab_${idx}`)}
                      accessibilityLabel={`Озвучить слово ${v.est}`}
                    >
                      <Text style={styles.vocabSpeakerIcon}>
                        {isVocabPlaying ? '⏹' : '🔊'}
                      </Text>
                    </TouchableOpacity>
                    <Text style={styles.vocabRu}>— {v.ru}</Text>
                  </View>

                  {/* Estonian Example sentence row with dedicated speaker button */}
                  <View style={styles.vocabExampleRow}>
                    <TouchableOpacity
                      style={[
                        styles.vocabExampleSpeakerBtn,
                        isExPlaying && styles.vocabSpeakerBtnActive,
                      ]}
                      onPress={() => handlePlayAudio(v.example, 'et', `vocab_ex_${idx}`)}
                      accessibilityLabel={`Озвучить пример предложения ${v.example}`}
                    >
                      <Text style={styles.vocabExampleSpeakerIcon}>
                        {isExPlaying ? '⏹' : '🔊'}
                      </Text>
                    </TouchableOpacity>
                    <Text style={[styles.vocabExample, isJunior && styles.vocabExampleJunior]}>
                      «{v.example}»
                    </Text>
                  </View>
                </View>
              );
            })}
          </View>

          {/* How to Answer */}
          <View style={styles.section}>
            <View style={styles.sectionHeaderRow}>
              <Text style={[styles.sectionHeader, isJunior && styles.sectionHeaderJunior]}>
                🎯 Как решить задание самому
              </Text>
              <TouchableOpacity
                style={[
                  styles.sectionAudioBtn,
                  isJunior && styles.sectionAudioBtnJunior,
                  playingId === 'how_to_answer' && styles.sectionAudioBtnActive,
                ]}
                onPress={() =>
                  handlePlayAudio(analysis.how_to_answer, 'ru', 'how_to_answer')
                }
                accessibilityLabel="Озвучить решение"
              >
                <Text style={[styles.sectionAudioBtnText, isJunior && styles.sectionAudioBtnTextJunior]}>
                  {playingId === 'how_to_answer' ? '⏹ Стоп' : '🔊 Озвучить'}
                </Text>
              </TouchableOpacity>
            </View>
            <Text style={[styles.instructionText, isJunior && styles.instructionTextJunior]}>
              {analysis.how_to_answer}
            </Text>
          </View>

          {/* Interactive Phrase Builder with Word Bank & Semantic Slot Matching */}
          <PhraseBuilder
            template={analysis.answer_template}
            vocabulary={analysis.vocabulary}
            isJunior={isJunior}
            onPlayAudio={handlePlayAudio}
            playingId={playingId}
          />

          {/* Compact Audio Button for Senior (5-12) */}
          {!isJunior && (
            <View style={styles.seniorVoiceBox}>
              <Text style={styles.seniorVoiceLabel}>
                {playingId === 'senior_voice' ? '🔊 Воспроизведение...' : '🔊 Аудио-подсказка к уроку:'}
              </Text>
              <Text style={styles.seniorVoiceScript}>{analysis.voice_prompt_script}</Text>
              <TouchableOpacity
                style={[
                  styles.seniorVoiceButton,
                  playingId === 'senior_voice' && styles.seniorVoiceButtonActive,
                ]}
                onPress={() =>
                  handlePlayAudio(analysis.voice_prompt_script, 'ru', 'senior_voice')
                }
              >
                <Text style={styles.seniorVoiceButtonText}>
                  {playingId === 'senior_voice' ? '⏹ Остановить' : '▶ Озвучить тезисы'}
                </Text>
              </TouchableOpacity>
            </View>
          )}

          {/* Save Card to History Button */}
          <TouchableOpacity
            style={[
              styles.saveCardButton,
              isJunior ? styles.saveCardButtonJunior : styles.saveCardButtonSenior,
              isSaved && styles.saveCardButtonSaved,
            ]}
            onPress={handleSaveCard}
            disabled={isSaved}
          >
            <Text
              style={[
                styles.saveCardButtonText,
                isJunior && styles.saveCardButtonTextJunior,
                isSaved && styles.saveCardButtonTextSaved,
              ]}
            >
              {isSaved ? '✓ Карточка сохранена в истории' : '⭐ Сохранить в историю'}
            </Text>
          </TouchableOpacity>

          {/* Next Task Camera Button */}
          <TouchableOpacity
            style={[
              styles.nextTaskButton,
              isJunior ? styles.nextTaskButtonJunior : styles.nextTaskButtonSenior,
            ]}
            onPress={handleTakePhoto}
            disabled={loading}
            activeOpacity={0.85}
          >
            {loading ? (
              <View style={styles.loadingRow}>
                <ActivityIndicator color="#fff" size="small" />
                <Text
                  style={[
                    styles.nextTaskButtonText,
                    isJunior && styles.nextTaskButtonTextJunior,
                    styles.loadingText,
                  ]}
                >
                  {loadingStep || 'Анализируем...'}
                </Text>
              </View>
            ) : (
              <Text
                style={[
                  styles.nextTaskButtonText,
                  isJunior && styles.nextTaskButtonTextJunior,
                ]}
              >
                📷 Разобрать следующее задание
              </Text>
            )}
          </TouchableOpacity>
        </View>
      )}
    </View>
  );

  // ==========================================
  // TAB 2: VOCABULARY & HISTORY (СЛОВАРЬ И ИСТОРИЯ)
  // ==========================================
  const renderDictionaryTab = () => (
    <View>
      {/* Header */}
      <View style={styles.header}>
        <Text style={[styles.appTitle, isJunior && styles.appTitleJunior]}>
          📚 База знаний
        </Text>
        <Text style={[styles.subtitle, isJunior && styles.subtitleJunior]}>
          Персональный словарик и архив разобранных уроков
        </Text>
      </View>

      {/* Segmented Switcher */}
      <View style={styles.segmentedControl}>
        <TouchableOpacity
          style={[
            styles.segmentBtn,
            tab2Mode === 'vocab' && (isJunior ? styles.segmentBtnActiveJunior : styles.segmentBtnActiveSenior),
          ]}
          onPress={() => setTab2Mode('vocab')}
        >
          <Text
            style={[
              styles.segmentBtnText,
              tab2Mode === 'vocab' && styles.segmentBtnTextActive,
            ]}
          >
            📚 Мой словарик ({savedVocab.length})
          </Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={[
            styles.segmentBtn,
            tab2Mode === 'history' && (isJunior ? styles.segmentBtnActiveJunior : styles.segmentBtnActiveSenior),
          ]}
          onPress={() => setTab2Mode('history')}
        >
          <Text
            style={[
              styles.segmentBtnText,
              tab2Mode === 'history' && styles.segmentBtnTextActive,
            ]}
          >
            🕒 История уроков ({history.length})
          </Text>
        </TouchableOpacity>
      </View>

      {/* Mode A: Vocabulary */}
      {tab2Mode === 'vocab' && (
        <View>
          {savedVocab.length === 0 ? (
            <View style={styles.emptyBox}>
              <Text style={styles.emptyIcon}>📖</Text>
              <Text style={styles.emptyTitle}>Словарик пока пуст</Text>
              <Text style={styles.emptyText}>
                Разбирай страницы учебников — все эстонские слова с переводом, примерами и озвучкой автоматически сохраняются здесь!
              </Text>
            </View>
          ) : (
            <View style={styles.vocabList}>
              <Text style={styles.listHint}>
                Нажми на слово, чтобы раскрыть пример предложения и послушать произношение:
              </Text>
              {savedVocab.map((item, idx) => {
                const isExpanded = expandedWord === item.est;
                const isPlaying = playingId === `saved_vocab_${item.est}`;
                const isExPlaying = playingId === `saved_ex_${item.est}`;

                return (
                  <TouchableOpacity
                    key={idx}
                    style={[
                      styles.vocabCard,
                      isJunior && styles.vocabCardJunior,
                      isExpanded && styles.vocabCardExpanded,
                    ]}
                    onPress={() => handleWordTap(item)}
                    activeOpacity={0.8}
                  >
                    <View style={styles.vocabCardTop}>
                      <View style={styles.vocabEstRow}>
                        <Text style={[styles.vocabCardEst, isJunior && styles.vocabCardEstJunior]}>
                          {item.est}
                        </Text>
                        <TouchableOpacity
                          style={[styles.vocabCardSpeaker, isPlaying && styles.vocabCardSpeakerActive]}
                          onPress={() => handlePlayAudio(item.est, 'et', `saved_vocab_${item.est}`)}
                        >
                          <Text style={styles.vocabCardSpeakerIcon}>
                            {isPlaying ? '⏹' : '🔊'}
                          </Text>
                        </TouchableOpacity>
                      </View>
                      <TouchableOpacity
                        style={styles.vocabCardDelete}
                        onPress={() => handleDeleteVocabWord(item.est)}
                      >
                        <Text style={styles.vocabCardDeleteText}>✕</Text>
                      </TouchableOpacity>
                    </View>

                    <Text style={styles.vocabCardRu}>{item.ru}</Text>

                    {isExpanded && item.example ? (
                      <View style={styles.vocabCardExampleBox}>
                        <View style={styles.vocabCardExampleHeader}>
                          <Text style={styles.vocabCardExampleLabel}>Пример в предложении:</Text>
                          <TouchableOpacity
                            style={[
                              styles.vocabExampleSpeakerBtn,
                              isExPlaying && styles.vocabSpeakerBtnActive,
                            ]}
                            onPress={() => handlePlayAudio(item.example, 'et', `saved_ex_${item.est}`)}
                          >
                            <Text style={styles.vocabExampleSpeakerIcon}>
                              {isExPlaying ? '⏹' : '🔊'}
                            </Text>
                          </TouchableOpacity>
                        </View>
                        <Text style={styles.vocabCardExampleText}>«{item.example}»</Text>
                      </View>
                    ) : null}
                  </TouchableOpacity>
                );
              })}
            </View>
          )}
        </View>
      )}

      {/* Mode B: History */}
      {tab2Mode === 'history' && (
        <View>
          {history.length === 0 ? (
            <View style={styles.emptyBox}>
              <Text style={styles.emptyIcon}>🕒</Text>
              <Text style={styles.emptyTitle}>История уроков пуста</Text>
              <Text style={styles.emptyText}>
                Когда ты сфотографируешь задание, разбор автоматически сохранится в историю для быстрого повторения!
              </Text>
            </View>
          ) : (
            <View style={styles.historyList}>
              {history.map((item) => (
                <View key={item.id} style={styles.historyItemCard}>
                  <View style={styles.historyItemHeader}>
                    <Text style={styles.historyItemDate}>{item.dateFormatted}</Text>
                    <View style={styles.historyBadgeRow}>
                      <View style={styles.historyTypeBadge}>
                        <Text style={styles.historyTypeBadgeText}>
                          {item.task_type || 'Koolitöö'}
                        </Text>
                      </View>
                      <View style={styles.historyItemBadge}>
                        <Text style={styles.historyItemBadgeText}>{item.grade} кл.</Text>
                      </View>
                    </View>
                  </View>

                  <Text style={styles.historyItemTitle}>{item.task_title}</Text>
                  <Text style={styles.historyItemSnippet} numberOfLines={2}>
                    {item.analysis.theme_explanation}
                  </Text>

                  <View style={styles.historyItemActions}>
                    <TouchableOpacity
                      style={styles.historyOpenBtn}
                      onPress={() => handleOpenHistoryItem(item)}
                    >
                      <Text style={styles.historyOpenBtnText}>▶ Открыть разбор</Text>
                    </TouchableOpacity>
                    <TouchableOpacity
                      style={styles.historyDeleteBtn}
                      onPress={() => handleDeleteHistoryItem(item.id)}
                    >
                      <Text style={styles.historyDeleteBtnText}>🗑️ Удалить</Text>
                    </TouchableOpacity>
                  </View>
                </View>
              ))}
            </View>
          )}
        </View>
      )}
    </View>
  );

  // ==========================================
  // TAB 3: SETTINGS (НАСТРОЙКИ ПРОФИЛЯ)
  // ==========================================
  const renderSettingsTab = () => (
    <View>
      {/* Header */}
      <View style={styles.header}>
        <Text style={[styles.appTitle, isJunior && styles.appTitleJunior]}>
          ⚙️ Профиль ученика
        </Text>
        <Text style={[styles.subtitle, isJunior && styles.subtitleJunior]}>
          Настройки адаптации и локальное хранилище (Zero-PII)
        </Text>
      </View>

      {/* Profile Card */}
      <View style={[styles.card, isJunior ? styles.cardJunior : styles.cardSenior]}>
        <View style={styles.cardHeaderRow}>
          <Text style={[styles.cardTitle, isJunior && styles.cardTitleJunior]}>
            👤 Имя и класс ученика
          </Text>
          <View style={[styles.tierTag, isJunior ? styles.tierTagJunior : styles.tierTagSenior]}>
            <Text style={[styles.tierTagText, isJunior && styles.tierTagTextJunior]}>
              {getTierBadgeText(profile.tier)}
            </Text>
          </View>
        </View>
        <Text style={styles.caption}>
          ИИ TarkApp адаптирует сложность объяснений и голос под класс ребёнка.
        </Text>

        <View style={styles.inputRow}>
          <Text style={[styles.label, isJunior && styles.labelJunior]}>
            Как называть ученика:
          </Text>
          <TextInput
            style={[styles.textInput, isJunior && styles.textInputJunior]}
            value={profile.nickname || ''}
            onChangeText={updateNickname}
            placeholder="Например: Алекс"
            placeholderTextColor="#9CA3AF"
          />
        </View>

        <Text style={[styles.label, isJunior && styles.labelJunior]}>
          Класс в эстонской школе: <Text style={styles.bold}>{profile.grade}</Text>
        </Text>
        <View style={styles.gradeGrid}>
          {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12].map((g) => {
            const isSelected = profile.grade === g;
            return (
              <TouchableOpacity
                key={g}
                style={[
                  styles.gradeChip,
                  isJunior && styles.gradeChipJunior,
                  isSelected && (isJunior ? styles.gradeChipActiveJunior : styles.gradeChipActiveSenior),
                ]}
                onPress={() => updateGrade(g)}
              >
                <Text
                  style={[
                    styles.gradeChipText,
                    isJunior && styles.gradeChipTextJunior,
                    isSelected && styles.gradeChipTextActive,
                  ]}
                >
                  {g}
                </Text>
              </TouchableOpacity>
            );
          })}
        </View>

        {/* Interests */}
        <View style={styles.interestsSection}>
          <Text style={[styles.label, isJunior && styles.labelJunior]}>
            Увлечения и интересы (для понятных примеров):
          </Text>
          <TextInput
            style={[styles.textInput, styles.interestsInput, isJunior && styles.textInputJunior]}
            value={interestsText}
            onChangeText={handleInterestsChange}
            placeholder="Minecraft, LEGO, футбол, котики..."
            placeholderTextColor="#9CA3AF"
            multiline
          />
          <Text style={[styles.interestsHint, isJunior && styles.interestsHintJunior]}>
            💡 Разделяй запятыми. ИИ объяснит абстрактные эстонские правила через аналогии с любимыми играми и хобби.
          </Text>

          <Text style={styles.suggestionsTitle}>Быстрые подсказки по возрасту:</Text>
          <View style={styles.suggestionsGrid}>
            {currentSuggestions.map((item, idx) => {
              const isSelected = (profile.interests || []).some(
                (i) => i.toLowerCase() === item.toLowerCase()
              );
              return (
                <TouchableOpacity
                  key={idx}
                  style={[
                    styles.suggestionChip,
                    isSelected && styles.suggestionChipSelected,
                  ]}
                  onPress={() => handleAddSuggestion(item)}
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
      </View>

      {/* Storage and Data Maintenance */}
      <View style={[styles.card, isJunior ? styles.cardJunior : styles.cardSenior]}>
        <Text style={[styles.cardTitle, isJunior && styles.cardTitleJunior]}>
          💾 Локальное хранилище
        </Text>
        <Text style={styles.storageStats}>
          • Сохранено уроков в истории: <Text style={styles.bold}>{history.length}</Text>
        </Text>
        <Text style={styles.storageStats}>
          • Терминов в личном словаре: <Text style={styles.bold}>{savedVocab.length}</Text>
        </Text>
        <Text style={styles.storageStats}>
          • Модель синтеза речи: <Text style={styles.bold}>Edge-TTS Neural (et-EE +20% / ru-RU)</Text>
        </Text>

        <TouchableOpacity style={styles.clearDataBtn} onPress={handleClearAllData}>
          <Text style={styles.clearDataBtnText}>🗑️ Очистить сохранённую историю и словарь</Text>
        </TouchableOpacity>
      </View>
    </View>
  );

  // Compute safe native insets across all phone models (Dynamic Island, camera punch-hole, 3-button nav)
  const topInset = Math.max(
    insets.top,
    Platform.OS === 'android' ? (RNStatusBar.currentHeight || 28) : 0,
    24
  );

  const bottomInset = Math.max(
    insets.bottom,
    Platform.OS === 'android' ? 16 : 10
  );

  return (
    <View
      style={[
        styles.safeArea,
        isJunior ? styles.safeAreaJunior : styles.safeAreaSenior,
        {
          paddingTop: topInset + 6,
          paddingLeft: insets.left,
          paddingRight: insets.right,
        },
      ]}
    >
      <StatusBar style="dark" />

      {/* Main Content Area */}
      <ScrollView
        ref={scrollViewRef}
        contentContainerStyle={[
          styles.container,
          {
            paddingBottom: 76 + bottomInset,
          },
        ]}
        showsVerticalScrollIndicator={false}
      >
        {currentTab === 'study' && renderStudyTab()}
        {currentTab === 'dictionary' && renderDictionaryTab()}
        {currentTab === 'settings' && renderSettingsTab()}
      </ScrollView>

      {/* Persistent Bottom Tab Bar with Dynamic Native Bottom Inset */}
      <View
        style={[
          styles.bottomTabBar,
          isJunior ? styles.bottomTabBarJunior : styles.bottomTabBarSenior,
          {
            paddingBottom: bottomInset,
            height: 58 + bottomInset,
          },
        ]}
      >
        <TouchableOpacity
          style={[styles.tabItem, currentTab === 'study' && styles.tabItemActive]}
          onPress={() => setCurrentTab('study')}
        >
          <Text style={styles.tabIcon}>📖</Text>
          <Text
            style={[
              styles.tabLabel,
              currentTab === 'study' && (isJunior ? styles.tabLabelActiveJunior : styles.tabLabelActiveSenior),
            ]}
          >
            Учёба
          </Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={[styles.tabItem, currentTab === 'dictionary' && styles.tabItemActive]}
          onPress={() => setCurrentTab('dictionary')}
        >
          <View style={styles.tabBadgeWrapper}>
            <Text style={styles.tabIcon}>📚</Text>
            {savedVocab.length > 0 && (
              <View style={styles.tabBadge}>
                <Text style={styles.tabBadgeText}>{savedVocab.length}</Text>
              </View>
            )}
          </View>
          <Text
            style={[
              styles.tabLabel,
              currentTab === 'dictionary' && (isJunior ? styles.tabLabelActiveJunior : styles.tabLabelActiveSenior),
            ]}
          >
            Словарь
          </Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={[styles.tabItem, currentTab === 'settings' && styles.tabItemActive]}
          onPress={() => setCurrentTab('settings')}
        >
          <Text style={styles.tabIcon}>⚙️</Text>
          <Text
            style={[
              styles.tabLabel,
              currentTab === 'settings' && (isJunior ? styles.tabLabelActiveJunior : styles.tabLabelActiveSenior),
            ]}
          >
            Настройки
          </Text>
        </TouchableOpacity>
      </View>
    </View>
  );
}

export default function App() {
  return (
    <SafeAreaProvider>
      <MainApp />
    </SafeAreaProvider>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
  },
  safeAreaJunior: {
    backgroundColor: '#F0FDF4',
  },
  safeAreaSenior: {
    backgroundColor: '#F8FAFC',
  },
  container: {
    padding: 16,
    paddingBottom: 90,
  },
  header: {
    marginBottom: 16,
    alignItems: 'center',
  },
  headerTopRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    width: '100%',
  },
  appTitle: {
    fontSize: 26,
    fontWeight: 'bold',
    color: '#1E3A8A',
  },
  appTitleJunior: {
    fontSize: 28,
    color: '#065F46',
  },
  subtitle: {
    fontSize: 13,
    color: '#4B5563',
    textAlign: 'center',
    marginTop: 4,
  },
  subtitleJunior: {
    fontSize: 15,
    color: '#047857',
    fontWeight: '500',
  },
  pupilPill: {
    backgroundColor: '#EFF6FF',
    borderWidth: 1,
    borderColor: '#BFDBFE',
    paddingHorizontal: 12,
    paddingVertical: 5,
    borderRadius: 16,
  },
  pupilPillJunior: {
    backgroundColor: '#ECFDF5',
    borderColor: '#A7F3D0',
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 18,
  },
  pupilPillText: {
    fontSize: 13,
    fontWeight: '700',
    color: '#1E40AF',
  },
  pupilPillTextJunior: {
    color: '#065F46',
  },

  // Today's Lesson Carousel Bar
  todaySection: {
    backgroundColor: '#FFFFFF',
    borderRadius: 16,
    padding: 12,
    marginBottom: 16,
    borderWidth: 1,
    borderColor: '#E2E8F0',
    shadowColor: '#000',
    shadowOpacity: 0.04,
    shadowRadius: 5,
    elevation: 2,
  },
  todaySectionJunior: {
    backgroundColor: '#F0FDF4',
    borderColor: '#A7F3D0',
    borderRadius: 18,
  },
  todayHeaderRow: {
    marginBottom: 10,
    paddingHorizontal: 4,
  },
  todayTitle: {
    fontSize: 16,
    fontWeight: 'bold',
    color: '#1E293B',
  },
  todayTitleJunior: {
    fontSize: 18,
    color: '#065F46',
  },
  todaySubtitle: {
    fontSize: 12,
    color: '#64748B',
    marginTop: 2,
  },
  todayCarousel: {
    flexDirection: 'row',
    gap: 10,
    paddingVertical: 2,
    paddingHorizontal: 2,
  },
  todayCard: {
    width: 210,
    backgroundColor: '#F8FAFC',
    borderRadius: 12,
    borderWidth: 1.5,
    borderColor: '#E2E8F0',
    padding: 8,
    flexDirection: 'row',
    alignItems: 'center',
  },
  todayCardJunior: {
    backgroundColor: '#FFFFFF',
    borderColor: '#D1FAE5',
    borderRadius: 14,
  },
  todayCardActiveJunior: {
    borderColor: '#059669',
    backgroundColor: '#ECFDF5',
    borderWidth: 2,
  },
  todayCardActiveSenior: {
    borderColor: '#2563EB',
    backgroundColor: '#EFF6FF',
    borderWidth: 2,
  },
  todayThumbnail: {
    width: 52,
    height: 52,
    borderRadius: 8,
    backgroundColor: '#E2E8F0',
  },
  todayThumbPlaceholder: {
    width: 52,
    height: 52,
    borderRadius: 8,
    backgroundColor: '#E2E8F0',
    alignItems: 'center',
    justifyContent: 'center',
  },
  todayThumbPlaceholderText: {
    fontSize: 22,
  },
  todayCardInfo: {
    flex: 1,
    marginLeft: 8,
    justifyContent: 'center',
  },
  todayCardBadgeRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 3,
  },
  todayBadge: {
    backgroundColor: '#E2E8F0',
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 6,
  },
  todayBadgeActive: {
    backgroundColor: '#059669',
  },
  todayBadgeText: {
    fontSize: 10,
    fontWeight: '700',
    color: '#475569',
  },
  todayBadgeTextActive: {
    color: '#FFFFFF',
  },
  todayActiveDot: {
    fontSize: 10,
    fontWeight: '700',
    color: '#059669',
  },
  todayCardTitle: {
    fontSize: 12,
    fontWeight: '600',
    color: '#334155',
    lineHeight: 16,
  },
  todayCardTitleJunior: {
    fontSize: 13,
    color: '#064E3B',
  },
  todayCardTitleActive: {
    fontWeight: 'bold',
    color: '#065F46',
  },

  welcomeCard: {
    backgroundColor: '#FFFFFF',
    borderRadius: 16,
    padding: 20,
    marginBottom: 16,
    alignItems: 'center',
    borderWidth: 1.5,
    borderColor: '#E2E8F0',
  },
  welcomeCardJunior: {
    borderColor: '#A7F3D0',
    backgroundColor: '#F0FDF4',
    borderRadius: 20,
  },
  welcomeCardSenior: {
    borderColor: '#CBD5E1',
  },
  welcomeIcon: {
    fontSize: 36,
    marginBottom: 8,
  },
  welcomeTitle: {
    fontSize: 18,
    fontWeight: 'bold',
    color: '#1E293B',
    marginBottom: 6,
  },
  welcomeTitleJunior: {
    fontSize: 20,
    color: '#065F46',
  },
  welcomeDesc: {
    fontSize: 13.5,
    color: '#4B5563',
    textAlign: 'center',
    lineHeight: 20,
  },
  card: {
    backgroundColor: '#FFFFFF',
    borderRadius: 16,
    padding: 16,
    marginBottom: 16,
    shadowColor: '#000',
    shadowOpacity: 0.06,
    shadowRadius: 8,
    elevation: 2,
  },
  cardJunior: {
    borderWidth: 2,
    borderColor: '#A7F3D0',
    borderRadius: 20,
  },
  cardSenior: {
    borderWidth: 1,
    borderColor: '#E2E8F0',
    borderRadius: 12,
  },
  cardHeaderRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  cardTitle: {
    fontSize: 17,
    fontWeight: '700',
    color: '#111827',
  },
  cardTitleJunior: {
    fontSize: 19,
    color: '#065F46',
  },
  tierTag: {
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 8,
  },
  tierTagJunior: {
    backgroundColor: '#DCFCE7',
  },
  tierTagSenior: {
    backgroundColor: '#F1F5F9',
  },
  tierTagText: {
    fontSize: 12,
    fontWeight: '700',
  },
  tierTagTextJunior: {
    color: '#15803D',
  },
  tierTagTextSenior: {
    color: '#475569',
  },
  caption: {
    fontSize: 12,
    color: '#6B7280',
    marginBottom: 12,
    marginTop: 2,
  },
  inputRow: {
    marginBottom: 12,
  },
  label: {
    fontSize: 13,
    fontWeight: '600',
    color: '#374151',
    marginBottom: 6,
  },
  labelJunior: {
    fontSize: 15,
    color: '#064E3B',
  },
  bold: {
    fontWeight: 'bold',
    color: '#1E40AF',
  },
  textInput: {
    borderWidth: 1,
    borderColor: '#D1D5DB',
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 8,
    fontSize: 14,
    backgroundColor: '#F9FAFB',
  },
  textInputJunior: {
    borderRadius: 12,
    fontSize: 16,
    paddingVertical: 10,
  },
  gradeGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 6,
    marginBottom: 14,
  },
  gradeChip: {
    width: 40,
    height: 36,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#E5E7EB',
    backgroundColor: '#F9FAFB',
    alignItems: 'center',
    justifyContent: 'center',
  },
  gradeChipJunior: {
    width: 44,
    height: 40,
    borderRadius: 10,
  },
  gradeChipActiveJunior: {
    backgroundColor: '#059669',
    borderColor: '#047857',
  },
  gradeChipActiveSenior: {
    backgroundColor: '#2563EB',
    borderColor: '#1D4ED8',
  },
  gradeChipText: {
    fontSize: 13,
    fontWeight: '600',
    color: '#374151',
  },
  gradeChipTextJunior: {
    fontSize: 15,
  },
  gradeChipTextActive: {
    color: '#FFFFFF',
    fontWeight: 'bold',
  },
  interestsSection: {
    marginTop: 4,
  },
  interestsInput: {
    minHeight: 46,
    textAlignVertical: 'top',
  },
  interestsHint: {
    fontSize: 12,
    color: '#4B5563',
    fontStyle: 'italic',
    lineHeight: 17,
    marginTop: 6,
    marginBottom: 10,
    backgroundColor: '#F3F4F6',
    padding: 8,
    borderRadius: 8,
  },
  interestsHintJunior: {
    backgroundColor: '#ECFDF5',
    color: '#065F46',
    fontSize: 12.5,
  },
  suggestionsTitle: {
    fontSize: 12,
    fontWeight: '600',
    color: '#6B7280',
    marginBottom: 6,
  },
  suggestionsGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 6,
  },
  suggestionChip: {
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 14,
    backgroundColor: '#F1F5F9',
    borderWidth: 1,
    borderColor: '#E2E8F0',
  },
  suggestionChipSelected: {
    backgroundColor: '#DBEAFE',
    borderColor: '#3B82F6',
  },
  suggestionText: {
    fontSize: 12,
    color: '#475569',
    fontWeight: '500',
  },
  suggestionTextSelected: {
    color: '#1E40AF',
    fontWeight: '700',
  },
  storageStats: {
    fontSize: 13.5,
    color: '#475569',
    marginBottom: 6,
  },
  clearDataBtn: {
    marginTop: 14,
    backgroundColor: '#FEE2E2',
    borderWidth: 1,
    borderColor: '#FCA5A5',
    paddingVertical: 10,
    borderRadius: 10,
    alignItems: 'center',
  },
  clearDataBtnText: {
    color: '#DC2626',
    fontWeight: '700',
    fontSize: 13,
  },
  actionsContainer: {
    marginBottom: 16,
  },
  actionButton: {
    borderRadius: 14,
    paddingVertical: 14,
    alignItems: 'center',
    marginBottom: 8,
    elevation: 3,
  },
  actionButtonJunior: {
    backgroundColor: '#059669',
    paddingVertical: 18,
    borderRadius: 18,
    shadowColor: '#059669',
    shadowOpacity: 0.35,
    shadowRadius: 8,
  },
  actionButtonSenior: {
    backgroundColor: '#1E40AF',
    paddingVertical: 13,
    borderRadius: 10,
  },
  actionButtonText: {
    color: '#FFFFFF',
    fontSize: 15,
    fontWeight: 'bold',
  },
  actionButtonTextJunior: {
    fontSize: 17,
  },
  loadingRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
  },
  loadingText: {
    marginLeft: 10,
  },
  secondaryRow: {
    flexDirection: 'row',
    gap: 10,
    marginTop: 4,
  },
  secondaryButton: {
    flex: 1,
    backgroundColor: '#FFFFFF',
    borderWidth: 1,
    borderColor: '#CBD5E1',
    borderRadius: 12,
    paddingVertical: 10,
    alignItems: 'center',
    justifyContent: 'center',
  },
  secondaryButtonJunior: {
    borderRadius: 14,
    borderColor: '#6EE7B7',
    backgroundColor: '#F0FDF4',
    paddingVertical: 12,
  },
  secondaryButtonText: {
    fontSize: 13,
    fontWeight: '600',
    color: '#334155',
  },
  secondaryButtonTextJunior: {
    fontSize: 14,
    color: '#065F46',
  },
  previewCard: {
    flexDirection: 'row',
    backgroundColor: '#FFFFFF',
    borderRadius: 14,
    padding: 10,
    marginBottom: 12,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: '#E2E8F0',
    shadowColor: '#000',
    shadowOpacity: 0.04,
    shadowRadius: 4,
    elevation: 1,
  },
  previewCardJunior: {
    borderColor: '#A7F3D0',
    backgroundColor: '#F0FDF4',
    borderRadius: 16,
  },
  previewImage: {
    width: 60,
    height: 60,
    borderRadius: 8,
    backgroundColor: '#E2E8F0',
  },
  previewContent: {
    flex: 1,
    marginLeft: 12,
  },
  previewLabel: {
    fontSize: 13,
    fontWeight: '600',
    color: '#1E293B',
    marginBottom: 4,
  },
  retakeBtn: {
    alignSelf: 'flex-start',
    backgroundColor: '#E0E7FF',
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: 8,
  },
  retakeBtnText: {
    fontSize: 12,
    color: '#3730A3',
    fontWeight: '600',
  },
  resultCard: {
    backgroundColor: '#FFFFFF',
    padding: 16,
    shadowColor: '#000',
    shadowOpacity: 0.08,
    shadowRadius: 10,
    elevation: 3,
  },
  resultCardJunior: {
    borderRadius: 20,
    borderWidth: 2,
    borderColor: '#A7F3D0',
  },
  resultCardSenior: {
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#CBD5E1',
  },
  resultHeader: {
    borderBottomWidth: 1,
    borderBottomColor: '#F3F4F6',
    paddingBottom: 10,
    marginBottom: 12,
  },
  resultTitle: {
    fontSize: 18,
    fontWeight: 'bold',
    color: '#111827',
  },
  resultTitleJunior: {
    fontSize: 21,
    color: '#064E3B',
  },
  tierBadge: {
    fontSize: 12,
    color: '#059669',
    fontWeight: '600',
    marginTop: 4,
  },
  juniorVoiceHeroBox: {
    backgroundColor: '#EDE9FE',
    borderRadius: 16,
    padding: 14,
    borderWidth: 2,
    borderColor: '#C4B5FD',
    marginBottom: 16,
  },
  voiceHeroHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 6,
  },
  voiceHeroBadge: {
    fontSize: 11,
    fontWeight: 'bold',
    backgroundColor: '#7C3AED',
    color: '#FFFFFF',
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 6,
  },
  voiceHeroTitle: {
    fontSize: 14,
    fontWeight: '700',
    color: '#5B21B6',
  },
  voiceScriptJunior: {
    fontSize: 15,
    lineHeight: 22,
    color: '#4C1D95',
    marginBottom: 12,
  },
  voiceBigPlayButton: {
    backgroundColor: '#7C3AED',
    paddingVertical: 12,
    borderRadius: 12,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: '#6D28D9',
  },
  voiceBigPlayButtonActive: {
    backgroundColor: '#DC2626',
    borderColor: '#B91C1C',
  },
  voiceBigPlayText: {
    color: '#FFFFFF',
    fontWeight: 'bold',
    fontSize: 14,
  },
  section: {
    marginBottom: 16,
  },
  sectionHeaderRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 6,
  },
  sectionHeader: {
    fontSize: 15,
    fontWeight: '700',
    color: '#1F2937',
  },
  sectionHeaderJunior: {
    fontSize: 17,
    color: '#065F46',
  },
  sectionAudioBtn: {
    backgroundColor: '#EFF6FF',
    borderWidth: 1,
    borderColor: '#BFDBFE',
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: 14,
  },
  sectionAudioBtnJunior: {
    backgroundColor: '#ECFDF5',
    borderColor: '#A7F3D0',
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 16,
  },
  sectionAudioBtnActive: {
    backgroundColor: '#FEE2E2',
    borderColor: '#FCA5A5',
  },
  sectionAudioBtnText: {
    fontSize: 12.5,
    fontWeight: '700',
    color: '#1D4ED8',
  },
  sectionAudioBtnTextJunior: {
    color: '#065F46',
    fontSize: 13.5,
  },
  explanationText: {
    fontSize: 14,
    lineHeight: 21,
    color: '#374151',
  },
  explanationTextJunior: {
    fontSize: 15.5,
    lineHeight: 23,
    color: '#1F2937',
  },
  vocabItem: {
    backgroundColor: '#F8FAFC',
    borderRadius: 10,
    padding: 10,
    marginBottom: 8,
    borderLeftWidth: 3,
    borderLeftColor: '#059669',
  },
  vocabItemJunior: {
    borderRadius: 12,
    padding: 12,
  },
  vocabRow: {
    flexDirection: 'row',
    alignItems: 'center',
    flexWrap: 'wrap',
    marginBottom: 4,
  },
  vocabEst: {
    fontSize: 15,
    fontWeight: 'bold',
    color: '#0F172A',
  },
  vocabEstJunior: {
    fontSize: 16,
    color: '#065F46',
  },
  vocabSpeakerBtn: {
    marginLeft: 8,
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 6,
    backgroundColor: '#E0E7FF',
    alignItems: 'center',
    justifyContent: 'center',
  },
  vocabSpeakerBtnActive: {
    backgroundColor: '#FEE2E2',
  },
  vocabSpeakerIcon: {
    fontSize: 13,
  },
  vocabRu: {
    fontSize: 13,
    color: '#4B5563',
    marginLeft: 8,
    flexShrink: 1,
  },
  vocabExampleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginTop: 4,
    backgroundColor: '#F1F5F9',
    paddingHorizontal: 8,
    paddingVertical: 5,
    borderRadius: 8,
  },
  vocabExampleSpeakerBtn: {
    backgroundColor: '#E0E7FF',
    paddingHorizontal: 6,
    paddingVertical: 3,
    borderRadius: 6,
    marginRight: 6,
    alignItems: 'center',
    justifyContent: 'center',
  },
  vocabExampleSpeakerIcon: {
    fontSize: 11,
  },
  vocabExample: {
    fontSize: 12.5,
    color: '#475569',
    fontStyle: 'italic',
    flex: 1,
  },
  vocabExampleJunior: {
    fontSize: 13.5,
    color: '#1E293B',
    lineHeight: 18,
  },
  instructionText: {
    fontSize: 14,
    lineHeight: 20,
    color: '#374151',
  },
  instructionTextJunior: {
    fontSize: 15,
    lineHeight: 22,
  },
  seniorVoiceBox: {
    backgroundColor: '#F8FAFC',
    borderRadius: 8,
    padding: 12,
    borderWidth: 1,
    borderColor: '#E2E8F0',
    marginTop: 12,
  },
  seniorVoiceLabel: {
    fontSize: 12,
    fontWeight: '600',
    color: '#475569',
    marginBottom: 4,
  },
  seniorVoiceScript: {
    fontSize: 13,
    color: '#334155',
    lineHeight: 18,
    marginBottom: 8,
  },
  seniorVoiceButton: {
    backgroundColor: '#3B82F6',
    paddingVertical: 7,
    paddingHorizontal: 12,
    borderRadius: 6,
    alignSelf: 'flex-start',
  },
  seniorVoiceButtonActive: {
    backgroundColor: '#DC2626',
  },
  seniorVoiceButtonText: {
    color: '#FFFFFF',
    fontWeight: '600',
    fontSize: 12,
  },
  saveCardButton: {
    backgroundColor: '#D97706',
    borderRadius: 14,
    paddingVertical: 14,
    alignItems: 'center',
    marginTop: 18,
    elevation: 3,
    shadowColor: '#D97706',
    shadowOpacity: 0.25,
    shadowRadius: 6,
  },
  saveCardButtonJunior: {
    backgroundColor: '#059669',
    paddingVertical: 16,
    borderRadius: 18,
    shadowColor: '#059669',
    shadowOpacity: 0.35,
    shadowRadius: 8,
  },
  saveCardButtonSenior: {
    backgroundColor: '#334155',
    paddingVertical: 12,
    borderRadius: 10,
  },
  saveCardButtonSaved: {
    backgroundColor: '#10B981',
    shadowColor: '#10B981',
    opacity: 0.9,
  },
  saveCardButtonText: {
    color: '#FFFFFF',
    fontSize: 15,
    fontWeight: 'bold',
  },
  saveCardButtonTextJunior: {
    fontSize: 16.5,
  },
  saveCardButtonTextSaved: {
    color: '#FFFFFF',
  },
  nextTaskButton: {
    borderRadius: 16,
    paddingVertical: 15,
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: 12,
    elevation: 3,
    shadowColor: '#000',
    shadowOpacity: 0.15,
    shadowRadius: 6,
  },
  nextTaskButtonJunior: {
    backgroundColor: '#059669',
    paddingVertical: 18,
    borderRadius: 20,
    shadowColor: '#059669',
    shadowOpacity: 0.35,
    shadowRadius: 8,
  },
  nextTaskButtonSenior: {
    backgroundColor: '#1E40AF',
    paddingVertical: 14,
    borderRadius: 12,
  },
  nextTaskButtonText: {
    color: '#FFFFFF',
    fontSize: 16,
    fontWeight: 'bold',
  },
  nextTaskButtonTextJunior: {
    fontSize: 17.5,
  },
  // Segmented control for Tab 2
  segmentedControl: {
    flexDirection: 'row',
    backgroundColor: '#E2E8F0',
    borderRadius: 12,
    padding: 3,
    marginBottom: 16,
  },
  segmentBtn: {
    flex: 1,
    paddingVertical: 9,
    alignItems: 'center',
    borderRadius: 10,
  },
  segmentBtnActiveJunior: {
    backgroundColor: '#059669',
  },
  segmentBtnActiveSenior: {
    backgroundColor: '#1E40AF',
  },
  segmentBtnText: {
    fontSize: 13,
    fontWeight: '600',
    color: '#475569',
  },
  segmentBtnTextActive: {
    color: '#FFFFFF',
    fontWeight: 'bold',
  },
  listHint: {
    fontSize: 12,
    color: '#6B7280',
    fontStyle: 'italic',
    marginBottom: 10,
  },
  vocabList: {
    gap: 8,
  },
  vocabCard: {
    backgroundColor: '#FFFFFF',
    borderRadius: 14,
    padding: 14,
    borderWidth: 1,
    borderColor: '#E2E8F0',
    marginBottom: 8,
    shadowColor: '#000',
    shadowOpacity: 0.03,
    shadowRadius: 4,
    elevation: 1,
  },
  vocabCardJunior: {
    borderColor: '#A7F3D0',
    borderRadius: 16,
  },
  vocabCardExpanded: {
    borderColor: '#3B82F6',
    backgroundColor: '#F8FAFC',
  },
  vocabCardTop: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 4,
  },
  vocabEstRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  vocabCardEst: {
    fontSize: 16,
    fontWeight: 'bold',
    color: '#0F172A',
  },
  vocabCardEstJunior: {
    fontSize: 18,
    color: '#065F46',
  },
  vocabCardSpeaker: {
    marginLeft: 8,
    backgroundColor: '#EEF2FF',
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 8,
  },
  vocabCardSpeakerActive: {
    backgroundColor: '#FEE2E2',
  },
  vocabCardSpeakerIcon: {
    fontSize: 13,
  },
  vocabCardDelete: {
    padding: 4,
  },
  vocabCardDeleteText: {
    color: '#94A3B8',
    fontSize: 15,
    fontWeight: 'bold',
  },
  vocabCardRu: {
    fontSize: 14,
    color: '#475569',
    marginTop: 2,
  },
  vocabCardExampleBox: {
    marginTop: 8,
    backgroundColor: '#F1F5F9',
    padding: 8,
    borderRadius: 8,
  },
  vocabCardExampleHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 4,
  },
  vocabCardExampleLabel: {
    fontSize: 11,
    fontWeight: '600',
    color: '#64748B',
  },
  vocabCardExampleText: {
    fontSize: 12.5,
    color: '#1E293B',
    fontStyle: 'italic',
  },
  emptyBox: {
    alignItems: 'center',
    justifyContent: 'center',
    padding: 30,
    marginTop: 40,
    backgroundColor: '#FFFFFF',
    borderRadius: 16,
    borderWidth: 1,
    borderColor: '#E2E8F0',
  },
  emptyIcon: {
    fontSize: 44,
    marginBottom: 12,
  },
  emptyTitle: {
    fontSize: 17,
    fontWeight: 'bold',
    color: '#1E293B',
    marginBottom: 6,
  },
  emptyText: {
    fontSize: 13.5,
    color: '#64748B',
    textAlign: 'center',
    lineHeight: 19,
  },
  historyList: {
    gap: 10,
  },
  historyItemCard: {
    backgroundColor: '#FFFFFF',
    borderRadius: 14,
    padding: 14,
    borderWidth: 1,
    borderColor: '#E2E8F0',
    shadowColor: '#000',
    shadowOpacity: 0.04,
    shadowRadius: 5,
    elevation: 2,
    marginBottom: 10,
  },
  historyItemHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 6,
  },
  historyItemDate: {
    fontSize: 12,
    color: '#94A3B8',
    fontWeight: '500',
  },
  historyBadgeRow: {
    flexDirection: 'row',
    gap: 6,
  },
  historyTypeBadge: {
    backgroundColor: '#EDE9FE',
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 6,
  },
  historyTypeBadgeText: {
    fontSize: 11,
    fontWeight: '700',
    color: '#6D28D9',
  },
  historyItemBadge: {
    backgroundColor: '#F1F5F9',
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 6,
  },
  historyItemBadgeText: {
    fontSize: 11,
    fontWeight: '600',
    color: '#475569',
  },
  historyItemTitle: {
    fontSize: 16,
    fontWeight: 'bold',
    color: '#0F172A',
    marginBottom: 4,
  },
  historyItemSnippet: {
    fontSize: 13,
    color: '#64748B',
    lineHeight: 18,
    marginBottom: 10,
  },
  historyItemActions: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    borderTopWidth: 1,
    borderTopColor: '#F1F5F9',
    paddingTop: 8,
  },
  historyOpenBtn: {
    backgroundColor: '#059669',
    paddingHorizontal: 14,
    paddingVertical: 7,
    borderRadius: 10,
  },
  historyOpenBtnText: {
    color: '#FFFFFF',
    fontSize: 13,
    fontWeight: '700',
  },
  historyDeleteBtn: {
    paddingHorizontal: 10,
    paddingVertical: 7,
  },
  historyDeleteBtnText: {
    color: '#EF4444',
    fontSize: 13,
    fontWeight: '600',
  },
  // Bottom Tab Bar
  bottomTabBar: {
    flexDirection: 'row',
    borderTopWidth: 1,
    alignItems: 'center',
    justifyContent: 'space-around',
    paddingHorizontal: 10,
    elevation: 10,
    shadowColor: '#000',
    shadowOpacity: 0.08,
    shadowRadius: 6,
  },
  bottomTabBarJunior: {
    backgroundColor: '#FFFFFF',
    borderTopColor: '#A7F3D0',
  },
  bottomTabBarSenior: {
    backgroundColor: '#FFFFFF',
    borderTopColor: '#E2E8F0',
  },
  tabItem: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 6,
  },
  tabItemActive: {
    opacity: 1,
  },
  tabIcon: {
    fontSize: 20,
    marginBottom: 2,
  },
  tabBadgeWrapper: {
    position: 'relative',
    alignItems: 'center',
  },
  tabBadge: {
    position: 'absolute',
    top: -4,
    right: -12,
    backgroundColor: '#059669',
    borderRadius: 10,
    paddingHorizontal: 5,
    paddingVertical: 1,
  },
  tabBadgeText: {
    color: '#FFFFFF',
    fontSize: 10,
    fontWeight: 'bold',
  },
  tabLabel: {
    fontSize: 12,
    fontWeight: '600',
    color: '#64748B',
  },
  tabLabelActiveJunior: {
    color: '#059669',
    fontWeight: 'bold',
  },
  tabLabelActiveSenior: {
    color: '#1E40AF',
    fontWeight: 'bold',
  },
});
