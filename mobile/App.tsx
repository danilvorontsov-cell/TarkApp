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
  PanResponder,
  StatusBar as RNStatusBar,
} from 'react-native';
import {
  SafeAreaProvider,
  useSafeAreaInsets,
} from 'react-native-safe-area-context';
import { StatusBar } from 'expo-status-bar';
import * as ImagePicker from 'expo-image-picker';
import {
  SchoolTier,
  AgeTier,
  TierConfig,
  TIER_POLICIES,
  getTierFromGrade,
  getTierPolicy,
  UserProfile,
  PageAnalysisResponse,
  SavedLessonCard,
  VocabularyItem,
  AGE_SUGGESTIONS,
} from './src/types';
import { StorageService } from './src/services/storage';
import { playTts, stopTts } from './src/services/audioPlayer';
import { AudioQueueManager, PlaybackState } from './src/services/audioQueueManager';
import {
  API_BASE_URL,
  analyzePage,
  analyzePageJson,
  analyzePagesJson,
  ImagePayload,
  formatFriendlyErrorMessage,
} from './src/services/api';
import { PhraseBuilder } from './src/components/PhraseBuilder';
import { ErrorBoundary } from './src/components/ErrorBoundary';
import { initSentry } from './src/services/sentry';
import { Theme } from './src/theme/colors';
import { DrawerMenu, DrawerTabType } from './src/components/DrawerMenu';
import { ComingSoonCard } from './src/components/ComingSoonCard';
import { AvatarPickerModal } from './src/components/AvatarPickerModal';
import { QuickTranslatorScreen } from './src/screens/QuickTranslatorScreen';

// Initialize Sentry stub/client once at entry
initSentry();

type TabType = 'study' | 'dictionary' | 'translator' | 'tests' | 'reading' | 'settings';
type Tab2Mode = 'vocab' | 'history';

interface SessionLesson {
  id: string;
  title: string;
  analysis: PageAnalysisResponse;
  imageUri: string | null;
  imageUris?: string[];
  timestamp: number;
}

interface CapturedPageItem {
  uri: string;
  base64?: string;
  mimeType?: string;
}

function MainApp() {
  const insets = useSafeAreaInsets();
  const [currentTab, setCurrentTab] = useState<TabType>('study');
  const [tab2Mode, setTab2Mode] = useState<Tab2Mode>('vocab');

  const [profile, setProfile] = useState<UserProfile>({
    grade: 3,
    tier: 'primary',
    interests: ['Minecraft', 'LEGO', 'Roblox'],
    nickname: '',
  });

  const [interestsText, setInterestsText] = useState('Minecraft, LEGO, Roblox');
  const [loading, setLoading] = useState(false);
  const [loadingStep, setLoadingStep] = useState('');
  const [capturedImages, setCapturedImages] = useState<CapturedPageItem[]>([]);
  const [capturedImageUri, setCapturedImageUri] = useState<string | null>(null);
  const [playingId, setPlayingId] = useState<string | null>(null);
  const [playbackState, setPlaybackState] = useState<PlaybackState>('idle');
  const [loadingAudioId, setLoadingAudioId] = useState<string | null>(null);
  const [analysis, setAnalysis] = useState<PageAnalysisResponse | null>(null);
  const [showAlternativeExplanation, setShowAlternativeExplanation] = useState<boolean>(false);
  const [sessionLessons, setSessionLessons] = useState<SessionLesson[]>([]);
  const [isSaved, setIsSaved] = useState(false);
  const [history, setHistory] = useState<SavedLessonCard[]>([]);
  const [savedVocab, setSavedVocab] = useState<VocabularyItem[]>([]);
  const [expandedWord, setExpandedWord] = useState<string | null>(null);
  const [isDrawerOpen, setIsDrawerOpen] = useState<boolean>(false);
  const [isAvatarModalVisible, setIsAvatarModalVisible] = useState<boolean>(false);

  const edgePanResponder = useRef(
    PanResponder.create({
      onMoveShouldSetPanResponder: (_, gestureState) => {
        return (
          gestureState.x0 < 40 &&
          gestureState.dx > 18 &&
          Math.abs(gestureState.dy) < 30
        );
      },
      onPanResponderRelease: (_, gestureState) => {
        if (gestureState.dx > 35) {
          setIsDrawerOpen(true);
        }
      },
    })
  ).current;

  const scrollViewRef = useRef<React.ElementRef<typeof ScrollView>>(null);
  const tierPolicy = getTierPolicy(profile.grade || profile.tier);
  const isJunior = profile.tier === 'primary';
  const isFullAudioEnabled = tierPolicy.fullAudioEnabled;
  const isSentenceFrameEnabled = tierPolicy.sentenceFrameEnabled;

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
          imageUris: c.imageUris,
          timestamp: c.timestamp,
        }));

      if (todayItems.length > 0) {
        setSessionLessons(todayItems);
        // Load the latest one into current view
        setAnalysis(todayItems[0].analysis);
        setCapturedImageUri(todayItems[0].imageUri);
        const restoredImages = (todayItems[0].imageUris && todayItems[0].imageUris.length > 0)
          ? todayItems[0].imageUris.map((u) => ({ uri: u, mimeType: 'image/jpeg' }))
          : todayItems[0].imageUri
          ? [{ uri: todayItems[0].imageUri, mimeType: 'image/jpeg' }]
          : [];
        setCapturedImages(restoredImages);
        setIsSaved(true);
        // Start background prefetch for latest today lesson
        AudioQueueManager.prefetchLessonAudio(todayItems[0].analysis, API_BASE_URL, profile.grade);
      }
    });

    StorageService.getSavedVocabulary().then((v) => {
      setSavedVocab(v);
    });

    const unsubAudio = AudioQueueManager.subscribe((state) => {
      setPlayingId(state.playingId);
      setPlaybackState(state.playbackState);
      setLoadingAudioId(state.loadingAudioId);
    });

    return () => {
      unsubAudio();
      stopTts();
    };
  }, []);

  const scrollToTaskTop = () => {
    setTimeout(() => {
      scrollViewRef.current?.scrollTo({ y: 0, animated: true });
    }, 120);
  };

  const handlePlayAudio = async (
    text: string,
    lang: 'ru' | 'et',
    id: string,
    bilingual: boolean = false
  ) => {
    try {
      await AudioQueueManager.playOrEnqueue(
        id,
        text,
        lang,
        bilingual,
        {
          onError: () => {
            Alert.alert(
              'Аудио',
              'Не удалось загрузить аудиофайл. Проверьте подключение к бэкенду.'
            );
          },
        },
        API_BASE_URL
      );
    } catch (err: any) {
      Alert.alert('Аудио', formatFriendlyErrorMessage(err));
    }
  };

  const switchTab = (tab: TabType) => {
    AudioQueueManager.stop();
    setCurrentTab(tab);
  };

  const switchTab2Mode = (mode: Tab2Mode) => {
    AudioQueueManager.stop();
    setTab2Mode(mode);
  };

  const handleLogout = () => {
    setIsDrawerOpen(false);
    Alert.alert(
      'Выход из профиля',
      'Вы уверены, что хотите выйти из профиля и завершить сессию?',
      [
        { text: 'Отмена', style: 'cancel' },
        {
          text: 'Выйти',
          style: 'destructive',
          onPress: async () => {
            AudioQueueManager.stop();
            const cleared: UserProfile = {
              ...profile,
              nickname: '',
              avatarUri: undefined,
            };
            setProfile(cleared);
            await StorageService.saveProfile(cleared);
            setAnalysis(null);
            setCapturedImages([]);
            setCapturedImageUri(null);
            switchTab('settings');
          },
        },
      ]
    );
  };

  const handleSaveAndContinue = async () => {
    const trimmed = (profile.nickname || '').trim();
    if (!trimmed) {
      Alert.alert(
        'Укажите имя',
        'Пожалуйста, введите имя или никнейм ученика перед сохранением.'
      );
      return;
    }
    const updated: UserProfile = { ...profile, nickname: trimmed };
    setProfile(updated);
    await StorageService.saveProfile(updated);
    Alert.alert(
      'Добро пожаловать!',
      `Профиль активирован для: ${trimmed}. Все настройки и уроки сохранены!`,
      [{ text: 'Отлично', onPress: () => switchTab('study') }]
    );
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
  const recordNewLesson = async (data: PageAnalysisResponse, imagesList: CapturedPageItem[]) => {
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

    const firstUri = imagesList.length > 0 ? imagesList[0].uri : undefined;
    const allUris = imagesList.map((img) => img.uri);

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
      imageUri: firstUri,
      imageUris: allUris,
    };

    // Do not auto-save to history to prevent cluttering; user manually clicks "Сохранить в историю"
    const alreadySaved = await StorageService.isLessonSaved(data.task_title);
    setIsSaved(alreadySaved);

    // Update today's session lessons list
    const newSessionItem: SessionLesson = {
      id: newId,
      title: data.task_title,
      analysis: data,
      imageUri: firstUri || null,
      imageUris: allUris,
      timestamp: Date.now(),
    };

    setSessionLessons((prev) => {
      const filtered = prev.filter((p) => p.title !== data.task_title);
      return [newSessionItem, ...filtered];
    });

    // Start background sequential audio prefetching with priority queue
    AudioQueueManager.clearQueue();
    AudioQueueManager.prefetchLessonAudio(data, API_BASE_URL, profile.grade);

    scrollToTaskTop();
  };

  const processImagesAnalysis = async (imagesList: CapturedPageItem[]) => {
    if (!imagesList || imagesList.length === 0) return;
    setLoading(true);
    setLoadingStep(
      imagesList.length > 1
        ? `Анализируем ${imagesList.length} стр. материала...`
        : 'Разбираем материал...'
    );
    try {
      const payload: ImagePayload[] = imagesList.map((img) => ({
        base64: img.base64,
        uri: img.uri,
        mimeType: img.mimeType || 'image/jpeg',
      }));

      const data = await analyzePagesJson(payload, profile, API_BASE_URL);

      setAnalysis(data);
      setShowAlternativeExplanation(false);
      await recordNewLesson(data, imagesList);
    } catch (err: any) {
      Alert.alert(
        'Ошибка анализа страниц',
        formatFriendlyErrorMessage(err)
      );
    } finally {
      setLoading(false);
      setLoadingStep('');
    }
  };

  const handleTakePhoto = async (mode: 'replace' | 'append' = 'replace') => {
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

      AudioQueueManager.stop();

      const asset = result.assets[0];
      const newItem: CapturedPageItem = {
        uri: asset.uri,
        base64: asset.base64 || undefined,
        mimeType: asset.mimeType || 'image/jpeg',
      };

      const nextImages = mode === 'append' ? [...capturedImages, newItem] : [newItem];
      setCapturedImages(nextImages);
      setCapturedImageUri(nextImages[0]?.uri || null);
      await processImagesAnalysis(nextImages);
    } catch (err: any) {
      Alert.alert('Камера', `Не удалось запустить камеру: ${err?.message || 'Неизвестная ошибка'}`);
    }
  };

  const handlePickImage = async (mode: 'replace' | 'append' = 'replace') => {
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
        allowsEditing: false,
        allowsMultipleSelection: true,
        quality: 0.8,
        base64: true,
      });

      if (result.canceled || !result.assets || result.assets.length === 0) {
        return;
      }

      AudioQueueManager.stop();

      const newItems: CapturedPageItem[] = result.assets.map((asset) => ({
        uri: asset.uri,
        base64: asset.base64 || undefined,
        mimeType: asset.mimeType || 'image/jpeg',
      }));

      const nextImages = mode === 'append' ? [...capturedImages, ...newItems] : newItems;
      setCapturedImages(nextImages);
      setCapturedImageUri(nextImages[0]?.uri || null);
      await processImagesAnalysis(nextImages);
    } catch (err: any) {
      Alert.alert('Галерея', `Не удалось открыть галерею: ${err?.message || 'Неизвестная ошибка'}`);
    }
  };

  const handleAddPagePrompt = () => {
    Alert.alert(
      'Добавить страницу к уроку',
      'Если задание продолжается на другой странице или в тетради, добавьте фото для связного контекста:',
      [
        {
          text: '📷 Снять камерой',
          onPress: () => handleTakePhoto('append'),
        },
        {
          text: '🖼️ Выбрать из галереи',
          onPress: () => handlePickImage('append'),
        },
        {
          text: 'Отмена',
          style: 'cancel',
        },
      ]
    );
  };

  const handleRemovePage = async (index: number) => {
    if (capturedImages.length <= 1) return;
    const nextImages = capturedImages.filter((_, idx) => idx !== index);
    setCapturedImages(nextImages);
    setCapturedImageUri(nextImages[0]?.uri || null);
    await processImagesAnalysis(nextImages);
  };

  const handleRetakeAll = () => {
    Alert.alert(
      'Снять заново',
      'Вы хотите очистить все фото и сфотографировать материал заново?',
      [
        {
          text: 'Да, переснять',
          style: 'destructive',
          onPress: () => {
            AudioQueueManager.stop();
            setCapturedImages([]);
            setCapturedImageUri(null);
            setAnalysis(null);
            handleTakePhoto('replace');
          },
        },
        {
          text: 'Отмена',
          style: 'cancel',
        },
      ]
    );
  };

  const handleTakeAvatarPhoto = async () => {
    try {
      const permission = await ImagePicker.requestCameraPermissionsAsync();
      if (!permission.granted) {
        Alert.alert(
          'Доступ к камере',
          'TarkApp требуется доступ к камере, чтобы сделать снимок для аватарки.'
        );
        return;
      }

      const result = await ImagePicker.launchCameraAsync({
        mediaTypes: ['images'],
        allowsEditing: true,
        aspect: [1, 1],
        quality: 0.8,
      });

      if (result.canceled || !result.assets || result.assets.length === 0) {
        return;
      }

      const newUri = result.assets[0].uri;
      const updatedProfile: UserProfile = { ...profile, avatarUri: newUri };
      setProfile(updatedProfile);
      await StorageService.saveProfile(updatedProfile);
    } catch (err: any) {
      Alert.alert('Ошибка', `Не удалось сделать снимок: ${err?.message || 'Сбой камеры'}`);
    }
  };

  const handlePickAvatarFromGallery = async () => {
    try {
      const permission = await ImagePicker.requestMediaLibraryPermissionsAsync();
      if (!permission.granted) {
        Alert.alert(
          'Доступ к галерее',
          'TarkApp требуется доступ к галерее, чтобы выбрать фото для аватарки.'
        );
        return;
      }

      const result = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ['images'],
        allowsEditing: true,
        aspect: [1, 1],
        quality: 0.8,
      });

      if (result.canceled || !result.assets || result.assets.length === 0) {
        return;
      }

      const newUri = result.assets[0].uri;
      const updatedProfile: UserProfile = { ...profile, avatarUri: newUri };
      setProfile(updatedProfile);
      await StorageService.saveProfile(updatedProfile);
    } catch (err: any) {
      Alert.alert('Ошибка', `Не удалось выбрать фото: ${err?.message || 'Сбой галереи'}`);
    }
  };

  const handleRemoveAvatar = async () => {
    const updatedProfile: UserProfile = { ...profile, avatarUri: undefined };
    setProfile(updatedProfile);
    await StorageService.saveProfile(updatedProfile);
  };

  const handleSelectAvatarSource = () => {
    setIsAvatarModalVisible(true);
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
        imageUri: capturedImages[0]?.uri || undefined,
        imageUris: capturedImages.map((img) => img.uri),
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
    setShowAlternativeExplanation(false);
    const restored = (item.imageUris && item.imageUris.length > 0)
      ? item.imageUris.map((u) => ({ uri: u, mimeType: 'image/jpeg' }))
      : item.imageUri
      ? [{ uri: item.imageUri, mimeType: 'image/jpeg' }]
      : [];
    setCapturedImages(restored);
    setCapturedImageUri(restored[0]?.uri || null);
    StorageService.isLessonSaved(item.analysis.task_title).then(setIsSaved);
    AudioQueueManager.clearQueue();
    AudioQueueManager.prefetchLessonAudio(item.analysis, API_BASE_URL, profile.grade);
    scrollToTaskTop();
  };

  const handleOpenHistoryItem = (item: SavedLessonCard) => {
    setAnalysis(item.analysis);
    setShowAlternativeExplanation(false);
    const restored = (item.imageUris && item.imageUris.length > 0)
      ? item.imageUris.map((u) => ({ uri: u, mimeType: 'image/jpeg' }))
      : item.imageUri
      ? [{ uri: item.imageUri, mimeType: 'image/jpeg' }]
      : [];
    setCapturedImages(restored);
    setCapturedImageUri(restored[0]?.uri || null);
    setIsSaved(true);
    setCurrentTab('study');
    AudioQueueManager.clearQueue();
    AudioQueueManager.prefetchLessonAudio(item.analysis, API_BASE_URL, profile.grade);
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
            AudioQueueManager.clearQueue();
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

  const getTierBadgeText = (tier: SchoolTier) => {
    return TIER_POLICIES[tier]?.name || 'Ученик';
  };

  const currentSuggestions = AGE_SUGGESTIONS[profile.tier] || [];

  // ==========================================
  // TAB 1: STUDY (УЧЁБА)
  // ==========================================
  const renderStudyTab = () => (
    <View>
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

      {/* Photo Preview Gallery if active task has images */}
      {capturedImages.length > 0 && (
        <View style={[styles.previewCard, isJunior && styles.previewCardJunior]}>
          <View style={styles.previewHeaderRow}>
            <View style={styles.previewHeaderTitleBox}>
              <Text style={styles.previewLabel}>
                📸 Материалы урока ({capturedImages.length} {capturedImages.length === 1 ? 'страница' : 'стр.'})
              </Text>
              {capturedImages.length > 1 && (
                <Text style={styles.previewSubLabel}>Общий контекст {capturedImages.length} страниц</Text>
              )}
            </View>
            <TouchableOpacity
              style={styles.retakeAllBtn}
              onPress={handleRetakeAll}
              disabled={loading}
              hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
            >
              <Text style={styles.retakeBtnText}>🔄 Переснять</Text>
            </TouchableOpacity>
          </View>

          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={styles.thumbnailsScroll}
          >
            {capturedImages.map((img, idx) => (
              <View key={`${img.uri}_${idx}`} style={styles.thumbnailWrapper}>
                <Image source={{ uri: img.uri }} style={styles.thumbnailImage} resizeMode="cover" />
                <View style={styles.pageNumberBadge}>
                  <Text style={styles.pageNumberBadgeText}>Стр. {idx + 1}</Text>
                </View>
                {capturedImages.length > 1 && (
                  <TouchableOpacity
                    style={styles.thumbnailRemoveBtn}
                    onPress={() => handleRemovePage(idx)}
                    disabled={loading}
                    hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
                    accessibilityLabel={`Удалить страницу ${idx + 1}`}
                  >
                    <Text style={styles.thumbnailRemoveBtnText}>✕</Text>
                  </TouchableOpacity>
                )}
              </View>
            ))}

            {/* + Добавить страницу (Камера / Галерея) */}
            <TouchableOpacity
              style={[
                styles.addPageThumbnailBtn,
                isJunior && styles.addPageThumbnailBtnJunior,
              ]}
              onPress={handleAddPagePrompt}
              disabled={loading}
              activeOpacity={0.7}
              accessibilityLabel="Добавить страницу задания"
            >
              <Text style={styles.addPageIcon}>➕</Text>
              <Text style={styles.addPageText}>Добавить{'\n'}страницу</Text>
            </TouchableOpacity>
          </ScrollView>
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
          onPress={() => handleTakePhoto(capturedImages.length > 0 ? 'append' : 'replace')}
          disabled={loading}
        >
          {loading ? (
            <View style={styles.loadingRow}>
              <ActivityIndicator color={Theme.colors.onPrimaryText} size="small" />
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

        {/* Secondary Buttons Row: Gallery & Tier Badge */}
        <View style={styles.secondaryRow}>
          <TouchableOpacity
            style={[
              styles.secondaryButton,
              isJunior && styles.secondaryButtonJunior,
            ]}
            onPress={() => handlePickImage(capturedImages.length > 0 ? 'append' : 'replace')}
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

          {/* Плашка уровня образования перенесена наверх вместо «Тестовое демо» */}
          <View
            style={[
              styles.tierPillInActionRow,
              isJunior && styles.tierPillInActionRowJunior,
            ]}
          >
            <Text
              style={[
                styles.tierPillInActionRowText,
                isJunior && styles.tierPillInActionRowTextJunior,
              ]}
            >
              🎓 {getTierBadgeText(profile.tier)}
            </Text>
          </View>
        </View>
      </View>

      {/* Analysis Results View - Nordic Clean Modular Cards */}
      {analysis && (
        <View style={styles.analysisModularContainer}>
          {/* Card 1: Task Context / Title - растянуто на всё окно, с мягкой подсветкой фона */}
          <View style={[styles.modularCard, styles.topicTitleCard, isJunior && styles.topicTitleCardJunior]}>
            <Text style={[styles.resultTitle, isJunior && styles.resultTitleJunior]}>
              {analysis.task_title}
            </Text>
          </View>

          {/* Card 2: Audio Hint (Аудиоподсказка к уроку - только для 1–6 классов) */}
          {isFullAudioEnabled && (
            <View style={styles.modularCard}>
              <View style={styles.voiceHeroHeader}>
                <Text style={styles.voiceHeroBadge}>🎧 ПОДСКАЗКА К УРОКУ</Text>
                <Text style={styles.voiceHeroTitle}>
                  {loadingAudioId === 'voice_prompt' || loadingAudioId === 'senior_voice'
                    ? '⏳ Подготовка подсказки...'
                    : (playingId === 'voice_prompt' || playingId === 'senior_voice') && playbackState === 'playing'
                    ? '🔊 Воспроизведение...'
                    : (playingId === 'voice_prompt' || playingId === 'senior_voice') && playbackState === 'paused'
                    ? '⏸ На паузе'
                    : 'Послушай подсказку голосом:'}
                </Text>
              </View>
              <Text style={styles.voiceScriptText}>{analysis.voice_prompt_script}</Text>
              <TouchableOpacity
                style={[
                  styles.voiceHeroPlayButton,
                  (playingId === 'voice_prompt' || playingId === 'senior_voice') &&
                    (playbackState === 'playing'
                      ? styles.voiceHeroPlayButtonActive
                      : playbackState === 'paused'
                      ? styles.voiceHeroPlayButtonPaused
                      : null),
                ]}
                onPress={() =>
                  handlePlayAudio(
                    analysis.voice_prompt_script,
                    'ru',
                    isJunior ? 'voice_prompt' : 'senior_voice'
                  )
                }
                activeOpacity={0.85}
              >
                <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'center' }}>
                  {(loadingAudioId === 'voice_prompt' || loadingAudioId === 'senior_voice') && (
                    <ActivityIndicator color="#FFFFFF" size="small" style={{ marginRight: 8 }} />
                  )}
                  <Text style={styles.voiceHeroPlayText}>
                    {(loadingAudioId === 'voice_prompt' || loadingAudioId === 'senior_voice')
                      ? 'ЗАГРУЗКА ЗВУКА...'
                      : (playingId === 'voice_prompt' || playingId === 'senior_voice')
                      ? playbackState === 'playing'
                        ? '⏸ ПАУЗА'
                        : '▶ ПРОДОЛЖИТЬ'
                      : '▶ СЛУШАТЬ ПОДСКАЗКУ'}
                  </Text>
                </View>
              </TouchableOpacity>
            </View>
          )}

          {/* Card 3: Суть темы простыми словами */}
          <View style={styles.modularCard}>
            <Text style={styles.sectionHeader}>💡 Суть темы простыми словами</Text>

            {showAlternativeExplanation ? (
              <View style={styles.altExplanationBadge}>
                <Text style={styles.altExplanationBadgeText}>
                  💡 Запасное объяснение через другую бытовую аналогию
                </Text>
              </View>
            ) : null}

            {isFullAudioEnabled && (
              <View style={styles.sectionAudioCenteredContainer}>
                <TouchableOpacity
                  style={[
                    styles.sectionAudioBtn,
                    (showAlternativeExplanation
                      ? playingId === 'alt_explanation'
                      : playingId === 'theme_explanation') &&
                      (playbackState === 'playing'
                        ? styles.sectionAudioBtnActive
                        : playbackState === 'paused'
                        ? styles.sectionAudioBtnPaused
                        : null),
                  ]}
                  onPress={() => {
                    const targetText = showAlternativeExplanation
                      ? analysis.alternative_explanation!
                      : analysis.theme_explanation;
                    const targetId = showAlternativeExplanation ? 'alt_explanation' : 'theme_explanation';
                    handlePlayAudio(targetText, 'ru', targetId, true);
                  }}
                  activeOpacity={0.85}
                  accessibilityLabel="Озвучить суть темы"
                >
                  {(showAlternativeExplanation
                    ? loadingAudioId === 'alt_explanation'
                    : loadingAudioId === 'theme_explanation') ? (
                    <View style={{ flexDirection: 'row', alignItems: 'center' }}>
                      <ActivityIndicator size="small" color="#FFFFFF" />
                      <Text style={[styles.sectionAudioBtnText, { marginLeft: 6 }]}>Загрузка...</Text>
                    </View>
                  ) : (
                    <Text style={styles.sectionAudioBtnText}>
                      {(showAlternativeExplanation
                        ? playingId === 'alt_explanation'
                        : playingId === 'theme_explanation')
                        ? playbackState === 'playing'
                          ? '⏸ Пауза'
                          : '▶ Продолжить'
                        : '▶ Озвучить'}
                    </Text>
                  )}
                </TouchableOpacity>
              </View>
            )}
            <Text style={styles.explanationText}>
              {showAlternativeExplanation ? analysis.alternative_explanation : analysis.theme_explanation}
            </Text>

            {/* Кнопка «Объяснить по-другому» в правом нижнем углу карточки */}
            {analysis.alternative_explanation ? (
              <View style={styles.altExplanationActionRow}>
                <TouchableOpacity
                  style={[
                    styles.altToggleBtnBottom,
                    showAlternativeExplanation && styles.altToggleBtnBottomActive,
                  ]}
                  onPress={() => {
                    AudioQueueManager.stop();
                    setShowAlternativeExplanation((prev) => !prev);
                  }}
                  activeOpacity={0.8}
                  accessibilityLabel="Переключить объяснение темы"
                >
                  <Text
                    style={[
                      styles.altToggleBtnTextBottom,
                      showAlternativeExplanation && styles.altToggleBtnTextBottomActive,
                    ]}
                  >
                    {showAlternativeExplanation ? '🔄 Вернуть первое объяснение' : '🔄 Объяснить по-другому'}
                  </Text>
                </TouchableOpacity>
              </View>
            ) : null}
          </View>

          {/* Card 4: Словарь урока (Sõnastik) */}
          <View style={styles.modularCard}>
            <Text style={styles.sectionHeader}>📚 Словарь урока (Sõnastik)</Text>
            <View style={styles.vocabChipsContainer}>
              {analysis.vocabulary.map((v, idx) => {
                const isVocabPlaying = playingId === `vocab_${idx}`;
                const isVocabActive = isVocabPlaying && playbackState === 'playing';
                const isVocabPaused = isVocabPlaying && playbackState === 'paused';

                const isExPlaying = playingId === `vocab_ex_${idx}`;
                const isExActive = isExPlaying && playbackState === 'playing';
                const isExPaused = isExPlaying && playbackState === 'paused';
                return (
                  <View key={idx} style={styles.vocabItemCard}>
                    <View style={styles.vocabPillRow}>
                      <View style={styles.vocabEstChip}>
                        <Text style={styles.vocabEstText}>{v.est}</Text>
                        <TouchableOpacity
                          style={[
                            styles.vocabCircleSpeaker,
                            isVocabActive && styles.vocabCircleSpeakerActive,
                            isVocabPaused && styles.vocabCircleSpeakerPaused,
                          ]}
                          onPress={() => handlePlayAudio(v.est, 'et', `vocab_${idx}`)}
                          accessibilityLabel={`Озвучить слово ${v.est}`}
                        >
                          {loadingAudioId === `vocab_${idx}` ? (
                            <ActivityIndicator size="small" color="#FFFFFF" style={{ transform: [{ scale: 0.65 }] }} />
                          ) : (
                            <Text style={styles.vocabSpeakerIconWhite}>
                              {isVocabActive ? '⏸' : isVocabPaused ? '▶' : '🔊'}
                            </Text>
                          )}
                        </TouchableOpacity>
                      </View>
                      <Text style={styles.vocabRuText}>— {v.ru}</Text>
                    </View>

                    {v.example ? (
                      <View style={styles.vocabExampleBox}>
                        <TouchableOpacity
                          style={[
                            styles.vocabExampleCircleBtn,
                            isExActive && styles.vocabCircleSpeakerActive,
                            isExPaused && styles.vocabCircleSpeakerPaused,
                          ]}
                          onPress={() => handlePlayAudio(v.example, 'et', `vocab_ex_${idx}`)}
                          accessibilityLabel={`Озвучить пример ${v.example}`}
                        >
                          {loadingAudioId === `vocab_ex_${idx}` ? (
                            <ActivityIndicator size="small" color="#FFFFFF" style={{ transform: [{ scale: 0.6 }] }} />
                          ) : (
                            <Text style={styles.vocabExampleIconWhite}>
                              {isExActive ? '⏸' : isExPaused ? '▶' : '🔊'}
                            </Text>
                          )}
                        </TouchableOpacity>
                        <Text style={styles.vocabExampleText}>«{v.example}»</Text>
                      </View>
                    ) : null}
                  </View>
                );
              })}
            </View>
          </View>

          {/* Card: Пример-образец (Näidis) — строго между словарём и алгоритмом */}
          {analysis.worked_example ? (
            <View style={styles.modularCard}>
              <View style={styles.naidisHeaderRow}>
                <View style={styles.naidisBadge}>
                  <Text style={styles.naidisBadgeText}>Образец • Näidis</Text>
                </View>
                <Text style={styles.sectionHeader}>
                  📝 {analysis.worked_example.title || 'Пример решения (Näidis)'}
                </Text>
              </View>

              {isFullAudioEnabled && (
                <View style={styles.sectionAudioCenteredContainer}>
                  <TouchableOpacity
                    style={[
                      styles.sectionAudioBtn,
                      playingId === 'worked_example' &&
                        (playbackState === 'playing'
                          ? styles.sectionAudioBtnActive
                          : playbackState === 'paused'
                          ? styles.sectionAudioBtnPaused
                          : null),
                    ]}
                    onPress={() => {
                      const we = analysis.worked_example!;
                      const ORDINAL_STEP_WORDS: Record<number, string> = {
                        1: 'Первое',
                        2: 'Второе',
                        3: 'Третье',
                        4: 'Четвертое',
                        5: 'Пятое',
                        6: 'Шестое',
                        7: 'Седьмое',
                        8: 'Восьмое',
                        9: 'Девятое',
                        10: 'Десятое',
                      };
                      const formattedSteps = we.steps.map((step, sIdx) => {
                        const clean = step.replace(/^\d+[\.\)]\s*/, '').trim();
                        const prefix = ORDINAL_STEP_WORDS[sIdx + 1] || `${sIdx + 1}-е`;
                        return `${prefix}: ${clean}`;
                      });
                      const naidisAudioText = `${we.given}. Шаги решения: ${formattedSteps.join('. ')}. ${we.note || ''}`.trim();
                      handlePlayAudio(naidisAudioText, 'ru', 'worked_example', true);
                    }}
                    activeOpacity={0.85}
                    accessibilityLabel="Озвучить пример решения"
                  >
                    {loadingAudioId === 'worked_example' ? (
                      <View style={{ flexDirection: 'row', alignItems: 'center' }}>
                        <ActivityIndicator size="small" color="#FFFFFF" />
                        <Text style={[styles.sectionAudioBtnText, { marginLeft: 6 }]}>Загрузка...</Text>
                      </View>
                    ) : (
                      <Text style={styles.sectionAudioBtnText}>
                        {playingId === 'worked_example'
                          ? playbackState === 'playing'
                            ? '⏸ Пауза'
                            : '▶ Продолжить'
                          : '▶ Озвучить пример'}
                      </Text>
                    )}
                  </TouchableOpacity>
                </View>
              )}

              {/* Given condition / situation */}
              <View style={styles.naidisGivenBox}>
                <Text style={styles.naidisGivenLabel}>📋 УСЛОВИЕ / ДАНО:</Text>
                <Text style={styles.naidisGivenText}>{analysis.worked_example.given}</Text>
              </View>

              {/* Step by step breakdown */}
              <View style={styles.naidisStepsContainer}>
                <Text style={styles.naidisStepsHeader}>Пошаговые действия:</Text>
                {analysis.worked_example.steps.map((step, sIdx) => (
                  <View key={sIdx} style={styles.naidisStepRow}>
                    <View style={styles.naidisStepNumberBadge}>
                      <Text style={styles.naidisStepNumberText}>{sIdx + 1}</Text>
                    </View>
                    <Text style={styles.naidisStepText}>{step.replace(/^\d+[\.\)]\s*/, '')}</Text>
                  </View>
                ))}
              </View>

              {/* Concluding note / tip */}
              {analysis.worked_example.note ? (
                <View style={styles.naidisNoteBox}>
                  <Text style={styles.naidisNoteText}>
                    💡 <Text style={{ fontWeight: '700' }}>Совет:</Text> {analysis.worked_example.note}
                  </Text>
                </View>
              ) : null}
            </View>
          ) : null}

          {/* Card 5: Как решить задание самому */}
          <View style={styles.modularCard}>
            <Text style={styles.sectionHeader}>🎯 Как решить задание самому</Text>
            {isFullAudioEnabled && (
              <View style={styles.sectionAudioCenteredContainer}>
                <TouchableOpacity
                  style={[
                    styles.sectionAudioBtn,
                    playingId === 'how_to_answer' &&
                      (playbackState === 'playing'
                        ? styles.sectionAudioBtnActive
                        : playbackState === 'paused'
                        ? styles.sectionAudioBtnPaused
                        : null),
                  ]}
                  onPress={() =>
                    handlePlayAudio(analysis.how_to_answer, 'ru', 'how_to_answer', true)
                  }
                  activeOpacity={0.85}
                  accessibilityLabel="Озвучить решение"
                >
                  {loadingAudioId === 'how_to_answer' ? (
                    <View style={{ flexDirection: 'row', alignItems: 'center' }}>
                      <ActivityIndicator size="small" color="#FFFFFF" />
                      <Text style={[styles.sectionAudioBtnText, { marginLeft: 6 }]}>Загрузка...</Text>
                    </View>
                  ) : (
                    <Text style={styles.sectionAudioBtnText}>
                      {playingId === 'how_to_answer'
                        ? playbackState === 'playing'
                          ? '⏸ Пауза'
                          : '▶ Продолжить'
                        : '▶ Озвучить'}
                    </Text>
                  )}
                </TouchableOpacity>
              </View>
            )}
            <Text style={styles.instructionText}>{analysis.how_to_answer}</Text>
          </View>

          {/* Card 6: Собери ответ на эстонском (1–9 классы) / Формулировка для ответа (Гимназия 10–12) */}
          {isSentenceFrameEnabled ? (
            <PhraseBuilder
              template={analysis.answer_template}
              vocabulary={analysis.vocabulary}
              isJunior={isJunior}
              onPlayAudio={handlePlayAudio}
              playingId={playingId}
              playbackState={playbackState}
              loadingAudioId={loadingAudioId}
              taskTitle={analysis.task_title}
              themeExplanation={analysis.theme_explanation}
              grade={profile.grade}
              tier={profile.tier}
            />
          ) : (
            <View style={styles.modularCard}>
              <View style={styles.academicHeaderRow}>
                <View style={styles.academicBadge}>
                  <Text style={styles.academicBadgeText}>Гимназия • Gümnaasium</Text>
                </View>
                <Text style={styles.sectionHeader}>
                  📝 Формулировка для ответа (Näidissõnastus)
                </Text>
              </View>

              <View style={styles.academicAnswerBox}>
                <Text style={styles.academicAnswerText}>
                  {(analysis.answer_template || '').replace(/\[(.*?)\]/g, '$1')}
                </Text>
              </View>

              <Text style={styles.academicAnswerHint}>
                💡 Готовый академический образец формулировки для экзаменационного или устного ответа в эстонской гимназии.
              </Text>
            </View>
          )}

          {/* Card 7: Save Card Button */}
          <TouchableOpacity
            style={[
              styles.saveCardButton,
              isSaved && styles.saveCardButtonSaved,
            ]}
            onPress={handleSaveCard}
            disabled={isSaved}
            activeOpacity={0.85}
          >
            <Text
              style={[
                styles.saveCardButtonText,
                isSaved && styles.saveCardButtonTextSaved,
              ]}
            >
              {isSaved ? '✓ Карточка сохранена в истории' : '⭐ Сохранить в историю'}
            </Text>
          </TouchableOpacity>

          {/* Card 8: Next Task Camera Button */}
          <TouchableOpacity
            style={styles.nextTaskButton}
            onPress={() => handleTakePhoto('replace')}
            disabled={loading}
            activeOpacity={0.85}
          >
            {loading ? (
              <View style={styles.loadingRow}>
                <ActivityIndicator color={Theme.colors.onPrimaryText} size="small" />
                <Text style={[styles.nextTaskButtonText, styles.loadingText]}>
                  {loadingStep || 'Анализируем...'}
                </Text>
              </View>
            ) : (
              <Text style={styles.nextTaskButtonText}>
                📷 Разобрать следующее задание (Фото)
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
          onPress={() => switchTab2Mode('vocab')}
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
          onPress={() => switchTab2Mode('history')}
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
                const isItemActive = isPlaying && playbackState === 'playing';
                const isItemPaused = isPlaying && playbackState === 'paused';

                const isExPlaying = playingId === `saved_ex_${item.est}`;
                const isExActive = isExPlaying && playbackState === 'playing';
                const isExPaused = isExPlaying && playbackState === 'paused';

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
                          style={[
                            styles.vocabCardSpeaker,
                            isItemActive && styles.vocabCardSpeakerActive,
                            isItemPaused && styles.vocabCardSpeakerPaused,
                          ]}
                          onPress={() => handlePlayAudio(item.est, 'et', `saved_vocab_${item.est}`)}
                        >
                          {loadingAudioId === `saved_vocab_${item.est}` ? (
                            <ActivityIndicator size="small" color="#FFFFFF" style={{ transform: [{ scale: 0.7 }] }} />
                          ) : (
                            <Text style={styles.vocabCardSpeakerIcon}>
                              {isItemActive ? '⏸' : isItemPaused ? '▶' : '🔊'}
                            </Text>
                          )}
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
                              styles.vocabCardSpeaker,
                              isExActive && styles.vocabCardSpeakerActive,
                              isExPaused && styles.vocabCardSpeakerPaused,
                            ]}
                            onPress={() => handlePlayAudio(item.example, 'et', `saved_ex_${item.est}`)}
                          >
                            {loadingAudioId === `saved_ex_${item.est}` ? (
                              <ActivityIndicator size="small" color="#FFFFFF" style={{ transform: [{ scale: 0.7 }] }} />
                            ) : (
                              <Text style={styles.vocabCardSpeakerIcon}>
                                {isExActive ? '⏸' : isExPaused ? '▶' : '🔊'}
                              </Text>
                            )}
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
        <Text style={[styles.cardTitle, isJunior && styles.cardTitleJunior]}>
          👤 Имя и класс ученика
        </Text>
        <View style={[styles.tierTag, isJunior ? styles.tierTagJunior : styles.tierTagSenior]}>
          <Text style={[styles.tierTagText, isJunior && styles.tierTagTextJunior]}>
            {getTierBadgeText(profile.tier)}
          </Text>
        </View>
        <Text style={styles.caption}>
          ИИ TarkApp адаптирует сложность объяснений и голос под класс ребёнка.
        </Text>

        {/* Guest Onboarding Banner if Logged Out */}
        {!profile.nickname?.trim() && (
          <View style={styles.guestNoticeCard}>
            <Text style={styles.guestNoticeIcon}>👋</Text>
            <View style={styles.guestNoticeBody}>
              <Text style={styles.guestNoticeTitle}>Вход не выполнен</Text>
              <Text style={styles.guestNoticeText}>
                Введите имя ученика и класс ниже, затем нажмите кнопку «Сохранить и войти».
              </Text>
            </View>
          </View>
        )}

        {/* Avatar Settings Row */}
        <View style={styles.settingsAvatarRow}>
          <TouchableOpacity
            style={styles.settingsAvatarButton}
            onPress={handleSelectAvatarSource}
            activeOpacity={0.8}
            accessibilityLabel="Изменить аватарку"
          >
            <View style={styles.settingsAvatarCircle}>
              {profile.avatarUri ? (
                <Image source={{ uri: profile.avatarUri }} style={styles.settingsAvatarImage} />
              ) : (
                <Text style={styles.settingsAvatarEmoji}>🧑‍🎓</Text>
              )}
            </View>
            <View style={styles.settingsAvatarBadge}>
              <Text style={styles.settingsAvatarBadgeIcon}>📷</Text>
            </View>
          </TouchableOpacity>
          <View style={styles.settingsAvatarInfo}>
            <Text style={styles.settingsAvatarTitle}>Аватарка ученика</Text>
            <TouchableOpacity onPress={handleSelectAvatarSource} activeOpacity={0.7}>
              <Text style={styles.settingsAvatarActionText}>
                {profile.avatarUri ? '📸 Сменить фото' : '➕ Добавить фото'}
              </Text>
            </TouchableOpacity>
          </View>
        </View>

        <View style={styles.inputRow}>
          <Text style={[styles.label, isJunior && styles.labelJunior]}>
            Как называть ученика:
          </Text>
          <TextInput
            style={[styles.textInput, isJunior && styles.textInputJunior]}
            value={profile.nickname || ''}
            onChangeText={updateNickname}
            placeholder="Например: Алекс"
            placeholderTextColor={Theme.colors.textMuted}
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
            placeholderTextColor={Theme.colors.textMuted}
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

        {/* Primary Save / Continue Button */}
        <TouchableOpacity
          style={styles.saveProfileBtn}
          onPress={handleSaveAndContinue}
          activeOpacity={0.8}
          accessibilityRole="button"
        >
          <Text style={styles.saveProfileBtnText}>
            {profile.nickname?.trim() ? '✓ Сохранить настройки' : '🔑 Сохранить имя и войти'}
          </Text>
        </TouchableOpacity>

        {/* Logout Button if Logged In */}
        {Boolean(profile.nickname?.trim()) && (
          <TouchableOpacity
            style={styles.logoutBtn}
            onPress={handleLogout}
            activeOpacity={0.7}
            accessibilityRole="button"
          >
            <Text style={styles.logoutBtnText}>🚪 Выйти из профиля</Text>
          </TouchableOpacity>
        )}
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

        <TouchableOpacity style={styles.clearDataBtn} onPress={handleClearAllData}>
          <Text style={styles.clearDataBtnText}>🗑️ Очистить сохранённую историю и словарь</Text>
        </TouchableOpacity>
      </View>
    </View>
  );

  // Compute safe native insets across all phone models (Dynamic Island, camera punch-hole, 3-button nav)
  const headerTopPadding = Math.max(
    insets.top,
    Platform.OS === 'android' ? (RNStatusBar.currentHeight || 24) : 16
  );

  const bottomInset = Math.max(
    insets.bottom,
    Platform.OS === 'android' ? 14 : 10
  );

  return (
    <View
      style={[
        styles.safeArea,
        {
          paddingLeft: insets.left,
          paddingRight: insets.right,
        },
      ]}
      {...edgePanResponder.panHandlers}
    >
      <RNStatusBar barStyle="dark-content" />

      {/* Nordic Clean Persistent Onsen Header Bar */}
      <View style={[styles.headerBar, { paddingTop: headerTopPadding + 4 }]}>
        <TouchableOpacity
          style={styles.headerMenuBtn}
          onPress={() => setIsDrawerOpen(true)}
          accessibilityLabel="Открыть меню"
          hitSlop={{ top: 12, bottom: 12, left: 12, right: 12 }}
        >
          <Text style={styles.headerMenuIcon}>≡</Text>
        </TouchableOpacity>

        <View style={styles.headerTitleCenter}>
          <Text style={styles.headerBrandTitle}>TarkApp</Text>
        </View>

        <TouchableOpacity
          style={[
            styles.headerProfilePill,
            !profile.nickname?.trim() && styles.headerProfilePillGuest,
          ]}
          onPress={() => switchTab(currentTab === 'settings' ? 'study' : 'settings')}
          accessibilityLabel={
            profile.nickname?.trim()
              ? `Профиль: ${profile.nickname.trim()}`
              : 'Войти в профиль'
          }
          accessibilityRole="button"
          hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
          activeOpacity={0.75}
        >
          {profile.avatarUri ? (
            <Image source={{ uri: profile.avatarUri }} style={styles.headerProfileAvatar} />
          ) : (
            <Text style={styles.headerProfileEmoji}>
              {profile.nickname?.trim() ? '🧑‍🎓' : '👤'}
            </Text>
          )}
          <Text
            style={[
              styles.headerProfileText,
              !profile.nickname?.trim() && styles.headerProfileTextGuest,
            ]}
            numberOfLines={1}
          >
            {profile.nickname?.trim() ? profile.nickname.trim() : 'Войти'}
          </Text>
        </TouchableOpacity>
      </View>

      {/* Main Scrollable Content Area */}
      <ScrollView
        ref={scrollViewRef}
        contentContainerStyle={[
          styles.container,
          {
            paddingBottom: Math.max(bottomInset, 20) + 16,
          },
        ]}
        showsVerticalScrollIndicator={false}
        keyboardShouldPersistTaps="handled"
      >
        {currentTab === 'study' && renderStudyTab()}
        {currentTab === 'dictionary' && renderDictionaryTab()}
        {currentTab === 'translator' && (
          <QuickTranslatorScreen
            onBackToStudy={() => switchTab('study')}
            onVocabularySaved={async () => {
              const updated = await StorageService.getSavedVocabulary();
              setSavedVocab(updated);
            }}
          />
        )}
        {currentTab === 'tests' && (
          <ComingSoonCard
            icon="🎯"
            title="Подготовка к контрольным"
            subtitle="Интеллектуальный тренажёр типовых проверочных работ эстонской школы (Koolibri, Avita) с разбором частых ошибок."
            features={[
              {
                icon: '📝',
                title: 'Интерактивные проверочные',
                desc: 'Тематические тесты по эстонской школьной программе с мгновенной проверкой',
              },
              {
                icon: '🔍',
                title: 'Разбор частых ловушек',
                desc: 'Сложные падежи (Omastav, Osastav) и формы слов без стресса',
              },
              {
                icon: '⏱️',
                title: 'Тренировка на время',
                desc: 'Режим симуляции реального урока с подсказками',
              },
              {
                icon: '📊',
                title: 'Оценка готовности',
                desc: 'Наглядный прогноз балла перед реальной контрольной работой в школе',
              },
            ]}
            onBackToStudy={() => switchTab('study')}
          />
        )}
        {currentTab === 'reading' && (
          <ComingSoonCard
            icon="⚡"
            title="Помощь в чтении (Скорочтение)"
            subtitle="Тренажёр осознанного беглого чтения эстонских текстов с синхронной подсветкой и ударениями."
            features={[
              {
                icon: '📖',
                title: 'Сложные составные слова',
                desc: 'Разбор длинных liitsõnad на смысловые корни для понимания сути',
              },
              {
                icon: '🔊',
                title: 'Аудио-сопровождение',
                desc: 'Эталонное произношение диктора в комфортном темпе',
              },
              {
                icon: '🧠',
                title: 'Контроль понимания',
                desc: 'Мини-вопросы после каждого абзаца для проверки смысла',
              },
              {
                icon: '📈',
                title: 'Отслеживание прогресса',
                desc: 'Рост скорости чтения (слов/мин) и словарного запаса',
              },
            ]}
            onBackToStudy={() => switchTab('study')}
          />
        )}
        {currentTab === 'settings' && renderSettingsTab()}
      </ScrollView>

      {/* Navigation Drawer Component (No Bottom Tab Bar) */}
      <DrawerMenu
        isOpen={isDrawerOpen}
        onClose={() => setIsDrawerOpen(false)}
        activeTab={currentTab as DrawerTabType}
        onSelectTab={(tab) => switchTab(tab as TabType)}
        userNickname={profile.nickname || ''}
        userGrade={profile.grade || 3}
        avatarUri={profile.avatarUri}
        onChangeAvatar={handleSelectAvatarSource}
        vocabCount={savedVocab.length}
        onLogout={handleLogout}
      />

      {/* Attractive Centered Avatar Picker Modal */}
      <AvatarPickerModal
        visible={isAvatarModalVisible}
        onClose={() => setIsAvatarModalVisible(false)}
        onTakePhoto={handleTakeAvatarPhoto}
        onPickGallery={handlePickAvatarFromGallery}
        onRemovePhoto={handleRemoveAvatar}
        hasExistingPhoto={Boolean(profile.avatarUri)}
      />
    </View>
  );
}

export default function App() {
  return (
    <SafeAreaProvider>
      <ErrorBoundary>
        <MainApp />
      </ErrorBoundary>
    </SafeAreaProvider>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: Theme.colors.background,
  },
  safeAreaJunior: {
    backgroundColor: Theme.colors.background,
  },
  safeAreaSenior: {
    backgroundColor: Theme.colors.background,
  },
  headerBar: {
    backgroundColor: '#5FEDC5',
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingBottom: 10,
    ...Theme.shadow.header,
  },
  headerMenuBtn: {
    width: 40,
    height: 40,
    justifyContent: 'center',
    alignItems: 'center',
  },
  headerMenuIcon: {
    fontSize: 26,
    fontWeight: 'bold',
    color: '#064E3B',
    lineHeight: 30,
  },
  headerTitleCenter: {
    flex: 1,
    alignItems: 'center',
  },
  headerBrandTitle: {
    fontSize: 21,
    fontWeight: '800',
    color: '#064E3B',
    letterSpacing: -0.3,
  },
  headerProfileBtn: {
    width: 44,
    height: 40,
    justifyContent: 'center',
    alignItems: 'center',
  },
  headerProfileBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: 'rgba(6, 78, 59, 0.12)',
    paddingHorizontal: 8,
    paddingVertical: 5,
    borderRadius: 16,
    overflow: 'hidden',
  },
  headerProfilePill: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: 'rgba(6, 78, 59, 0.12)',
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: 18,
    maxWidth: 130,
  },
  headerProfilePillGuest: {
    backgroundColor: '#FFFFFF',
    borderWidth: 1.5,
    borderColor: '#064E3B',
    paddingHorizontal: 11,
    paddingVertical: 5,
  },
  headerProfileEmoji: {
    fontSize: 15,
    marginRight: 5,
  },
  headerProfileAvatar: {
    width: 22,
    height: 22,
    borderRadius: 11,
    marginRight: 5,
  },
  headerProfileText: {
    fontSize: 13,
    fontWeight: '700',
    color: '#064E3B',
  },
  headerProfileTextGuest: {
    fontWeight: '800',
    color: '#064E3B',
  },
  headerProfileIconText: {
    fontSize: 15,
  },
  guestNoticeCard: {
    flexDirection: 'row',
    backgroundColor: '#CFFAEE',
    borderWidth: 1.5,
    borderColor: '#5FEDC5',
    borderRadius: 14,
    padding: 12,
    marginBottom: 16,
    alignItems: 'center',
  },
  guestNoticeIcon: {
    fontSize: 26,
    marginRight: 10,
  },
  guestNoticeBody: {
    flex: 1,
  },
  guestNoticeTitle: {
    fontSize: 15,
    fontWeight: '800',
    color: '#064E3B',
    marginBottom: 2,
  },
  guestNoticeText: {
    fontSize: 13,
    color: '#065F46',
    lineHeight: 18,
  },
  saveProfileBtn: {
    backgroundColor: '#064E3B',
    paddingVertical: 14,
    borderRadius: 14,
    alignItems: 'center',
    marginTop: 18,
    ...Theme.shadow.button,
  },
  saveProfileBtnText: {
    fontSize: 15,
    fontWeight: '800',
    color: '#5FEDC5',
    letterSpacing: 0.2,
  },
  logoutBtn: {
    borderWidth: 1.5,
    borderColor: '#FCA5A5',
    backgroundColor: '#FEF2F2',
    paddingVertical: 12,
    borderRadius: 14,
    alignItems: 'center',
    marginTop: 12,
  },
  logoutBtnText: {
    fontSize: 14,
    fontWeight: '700',
    color: '#DC2626',
  },
  settingsAvatarRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 16,
    paddingVertical: 4,
  },
  settingsAvatarButton: {
    position: 'relative',
    marginRight: 14,
  },
  settingsAvatarCircle: {
    width: 58,
    height: 58,
    borderRadius: 29,
    backgroundColor: Theme.colors.surfaceAlt,
    borderWidth: 2,
    borderColor: '#5FEDC5',
    justifyContent: 'center',
    alignItems: 'center',
    overflow: 'hidden',
  },
  settingsAvatarImage: {
    width: '100%',
    height: '100%',
    borderRadius: 29,
  },
  settingsAvatarEmoji: {
    fontSize: 28,
  },
  settingsAvatarBadge: {
    position: 'absolute',
    bottom: -2,
    right: -2,
    width: 20,
    height: 20,
    borderRadius: 10,
    backgroundColor: '#064E3B',
    borderWidth: 1.5,
    borderColor: '#FFFFFF',
    justifyContent: 'center',
    alignItems: 'center',
  },
  settingsAvatarBadgeIcon: {
    fontSize: 10,
    color: '#FFFFFF',
  },
  settingsAvatarInfo: {
    flex: 1,
    justifyContent: 'center',
  },
  settingsAvatarTitle: {
    fontSize: 14.5,
    fontWeight: '700',
    color: '#0F172A',
    marginBottom: 3,
  },
  settingsAvatarActionText: {
    fontSize: 13,
    fontWeight: '700',
    color: '#065F46',
  },
  container: {
    padding: 16,
    paddingBottom: 24,
  },
  studySubHeader: {
    marginBottom: 12,
    alignItems: 'center',
  },
  studySubTitle: {
    fontSize: 13,
    fontWeight: '600',
    color: Theme.colors.textSecondary,
  },

  // Today's Lesson Carousel Bar
  todaySection: {
    backgroundColor: Theme.colors.surface,
    borderRadius: Theme.radius.card,
    padding: 14,
    marginBottom: 14,
    borderWidth: 1,
    borderColor: Theme.colors.border,
    ...Theme.shadow.card,
  },
  todaySectionJunior: {
    backgroundColor: Theme.colors.surface,
    borderColor: Theme.colors.border,
    borderRadius: Theme.radius.card,
  },
  todayHeaderRow: {
    marginBottom: 10,
    paddingHorizontal: 2,
  },
  todayTitle: {
    fontSize: 16,
    fontWeight: '800',
    color: Theme.colors.textPrimary,
  },
  todayTitleJunior: {
    fontSize: 16,
    fontWeight: '800',
    color: Theme.colors.textPrimary,
  },
  todaySubtitle: {
    fontSize: 12,
    color: Theme.colors.textSecondary,
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
    backgroundColor: Theme.colors.surfaceAlt,
    borderRadius: 12,
    borderWidth: 1.5,
    borderColor: Theme.colors.border,
    padding: 8,
    flexDirection: 'row',
    alignItems: 'center',
  },
  todayCardJunior: {
    backgroundColor: Theme.colors.surfaceAlt,
    borderColor: Theme.colors.border,
    borderRadius: 12,
  },
  todayCardActive: {
    borderColor: Theme.colors.primary,
    backgroundColor: '#CFFAEE',
    borderWidth: 2,
    elevation: 0,
    shadowOpacity: 0,
  },
  todayCardActiveJunior: {
    borderColor: '#F59E0B',
    backgroundColor: '#FEF3C7',
    borderWidth: 2,
    elevation: 0,
    shadowOpacity: 0,
  },
  todayCardActiveSenior: {
    borderColor: Theme.colors.primary,
    backgroundColor: '#CFFAEE',
    borderWidth: 2,
    elevation: 0,
    shadowOpacity: 0,
  },
  todayThumbnail: {
    width: 50,
    height: 50,
    borderRadius: 8,
    backgroundColor: Theme.colors.border,
  },
  todayThumbPlaceholder: {
    width: 50,
    height: 50,
    borderRadius: 8,
    backgroundColor: Theme.colors.border,
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
    backgroundColor: Theme.colors.border,
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 6,
  },
  todayBadgeActive: {
    backgroundColor: Theme.colors.primary,
  },
  todayBadgeText: {
    fontSize: 10,
    fontWeight: '700',
    color: Theme.colors.textSecondary,
  },
  todayBadgeTextActive: {
    color: Theme.colors.onPrimaryText,
  },
  todayActiveDot: {
    fontSize: 10,
    fontWeight: '700',
    color: Theme.colors.onPrimaryText,
  },
  todayCardTitle: {
    fontSize: 12,
    fontWeight: '600',
    color: Theme.colors.textPrimary,
    lineHeight: 16,
  },
  todayCardTitleJunior: {
    fontSize: 12,
    fontWeight: '600',
    color: Theme.colors.textPrimary,
  },
  todayCardTitleActive: {
    fontWeight: '800',
    color: Theme.colors.onPrimaryText,
  },

  welcomeCard: {
    backgroundColor: '#FFFFFF',
    borderRadius: 20,
    padding: 22,
    marginBottom: 16,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: '#E2E8F0',
    ...Theme.shadow.card,
  },
  welcomeCardJunior: {
    backgroundColor: '#FFFFFF',
    borderColor: '#E2E8F0',
    borderRadius: 20,
  },
  welcomeCardSenior: {
    backgroundColor: '#FFFFFF',
    borderColor: '#E2E8F0',
    borderRadius: 20,
  },
  welcomeIcon: {
    fontSize: 38,
    marginBottom: 10,
  },
  welcomeTitle: {
    fontSize: 19,
    fontWeight: '800',
    color: Theme.colors.textPrimary,
    marginBottom: 6,
    textAlign: 'center',
  },
  welcomeTitleJunior: {
    fontSize: 19,
    fontWeight: '800',
    color: Theme.colors.textPrimary,
  },
  welcomeDesc: {
    fontSize: 13.5,
    color: Theme.colors.textSecondary,
    textAlign: 'center',
    lineHeight: 20,
  },

  // Action Buttons Section
  actionsContainer: {
    marginBottom: 16,
  },
  actionButton: {
    backgroundColor: '#5FEDC5',
    borderRadius: 14,
    paddingVertical: 14,
    alignItems: 'center',
    marginBottom: 10,
    ...Theme.shadow.chip,
  },
  actionButtonJunior: {
    backgroundColor: '#5FEDC5',
    borderRadius: 14,
  },
  actionButtonSenior: {
    backgroundColor: '#5FEDC5',
    borderRadius: 14,
  },
  actionButtonText: {
    color: '#064E3B',
    fontSize: 15,
    fontWeight: '800',
    letterSpacing: 0.2,
  },
  actionButtonTextJunior: {
    fontSize: 16,
    fontWeight: '800',
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
  },
  secondaryButton: {
    flex: 1,
    backgroundColor: Theme.colors.surface,
    borderWidth: 1,
    borderColor: Theme.colors.border,
    borderRadius: Theme.radius.button,
    paddingVertical: 12,
    alignItems: 'center',
    justifyContent: 'center',
    ...Theme.shadow.card,
  },
  secondaryButtonJunior: {
    borderRadius: Theme.radius.button,
    borderColor: Theme.colors.border,
    backgroundColor: Theme.colors.surface,
  },
  secondaryButtonText: {
    fontSize: 13.5,
    fontWeight: '700',
    color: Theme.colors.textPrimary,
  },
  secondaryButtonTextJunior: {
    fontSize: 13.5,
    color: Theme.colors.textPrimary,
  },

  tierPillInActionRow: {
    flex: 1,
    backgroundColor: '#CFFAEE',
    borderWidth: 1.5,
    borderColor: '#5FEDC5',
    borderRadius: Theme.radius.button,
    paddingVertical: 12,
    paddingHorizontal: 8,
    alignItems: 'center',
    justifyContent: 'center',
    elevation: 0,
    shadowOpacity: 0,
  },
  tierPillInActionRowJunior: {
    backgroundColor: '#FEF3C7',
    borderColor: '#FCD34D',
    elevation: 0,
    shadowOpacity: 0,
  },
  tierPillInActionRowText: {
    fontSize: 12.5,
    fontWeight: '700',
    color: Theme.colors.onPrimaryText,
    textAlign: 'center',
    backgroundColor: 'transparent',
  },
  tierPillInActionRowTextJunior: {
    color: '#78350F',
    backgroundColor: 'transparent',
  },

  previewCard: {
    backgroundColor: '#FFFFFF',
    borderRadius: 20,
    padding: 16,
    marginBottom: 16,
    borderWidth: 1,
    borderColor: '#E2E8F0',
    ...Theme.shadow.card,
  },
  previewCardJunior: {
    borderColor: '#E2E8F0',
    backgroundColor: '#FFFFFF',
    borderRadius: 20,
  },
  previewHeaderRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 10,
  },
  previewHeaderTitleBox: {
    flex: 1,
  },
  previewLabel: {
    fontSize: 15.5,
    fontWeight: '800',
    color: '#0F172A',
  },
  previewSubLabel: {
    fontSize: 11,
    color: Theme.colors.textSecondary,
    marginTop: 1,
  },
  retakeAllBtn: {
    backgroundColor: Theme.colors.surfaceAlt,
    borderWidth: 1,
    borderColor: Theme.colors.border,
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: 8,
  },
  retakeBtn: {
    alignSelf: 'flex-start',
    backgroundColor: Theme.colors.surfaceAlt,
    borderWidth: 1,
    borderColor: Theme.colors.border,
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: 8,
  },
  retakeBtnText: {
    fontSize: 12,
    color: Theme.colors.textPrimary,
    fontWeight: '600',
  },
  thumbnailsScroll: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    paddingVertical: 2,
  },
  thumbnailWrapper: {
    position: 'relative',
    width: 68,
    height: 68,
    borderRadius: 10,
    backgroundColor: Theme.colors.border,
    borderWidth: 1,
    borderColor: Theme.colors.border,
    overflow: 'hidden',
  },
  thumbnailImage: {
    width: '100%',
    height: '100%',
  },
  pageNumberBadge: {
    position: 'absolute',
    bottom: 2,
    left: 2,
    backgroundColor: 'rgba(15, 23, 42, 0.75)',
    paddingHorizontal: 4,
    paddingVertical: 1,
    borderRadius: 4,
  },
  pageNumberBadgeText: {
    fontSize: 9.5,
    color: '#FFFFFF',
    fontWeight: '700',
  },
  thumbnailRemoveBtn: {
    position: 'absolute',
    top: 2,
    right: 2,
    backgroundColor: 'rgba(239, 68, 68, 0.9)',
    width: 18,
    height: 18,
    borderRadius: 9,
    alignItems: 'center',
    justifyContent: 'center',
  },
  thumbnailRemoveBtnText: {
    fontSize: 10,
    color: '#FFFFFF',
    fontWeight: 'bold',
    lineHeight: 12,
  },
  addPageThumbnailBtn: {
    width: 68,
    height: 68,
    borderRadius: 10,
    borderWidth: 1.5,
    borderStyle: 'dashed',
    borderColor: Theme.colors.primary,
    backgroundColor: '#F0FDF9',
    alignItems: 'center',
    justifyContent: 'center',
    padding: 2,
    elevation: 0,
    shadowOpacity: 0,
  },
  addPageThumbnailBtnJunior: {
    borderColor: '#F59E0B',
    backgroundColor: '#FEF9C3',
    elevation: 0,
    shadowOpacity: 0,
  },
  addPageIcon: {
    fontSize: 16,
    color: Theme.colors.onPrimaryText,
    marginBottom: 2,
  },
  addPageText: {
    fontSize: 9,
    fontWeight: '700',
    color: Theme.colors.onPrimaryText,
    textAlign: 'center',
    lineHeight: 11,
  },

  // Analysis Modular Cards
  analysisModularContainer: {
    marginTop: 2,
  },
  modularCard: {
    backgroundColor: '#FFFFFF',
    borderRadius: 20,
    padding: 18,
    marginBottom: 16,
    borderWidth: 1,
    borderColor: '#E2E8F0',
    ...Theme.shadow.card,
  },
  topicTitleCard: {
    backgroundColor: '#FFFFFF',
    borderColor: '#E2E8F0',
    borderWidth: 1,
    borderRadius: 20,
    paddingVertical: 18,
    paddingHorizontal: 18,
    marginBottom: 16,
    ...Theme.shadow.card,
  },
  topicTitleCardJunior: {
    backgroundColor: '#FFFFFF',
    borderColor: '#E2E8F0',
    borderWidth: 1,
    borderRadius: 20,
    paddingVertical: 18,
    paddingHorizontal: 18,
    marginBottom: 16,
    ...Theme.shadow.card,
  },
  resultHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
  },
  resultTitle: {
    fontSize: 17,
    fontWeight: '800',
    color: '#0F172A',
    width: '100%',
    lineHeight: 25,
    textAlign: 'left',
  },
  resultTitleJunior: {
    fontSize: 17,
    fontWeight: '800',
    color: '#0F172A',
    width: '100%',
    lineHeight: 25,
    textAlign: 'left',
  },
  tierBadgeBox: {
    backgroundColor: Theme.colors.slotSuccessBg,
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: Theme.radius.badge,
    borderWidth: 1,
    borderColor: Theme.colors.primary,
  },
  tierBadgeText: {
    fontSize: 11.5,
    fontWeight: '700',
    color: Theme.colors.onPrimaryText,
  },

  // Voice Hero (Аудиоподсказка)
  voiceHeroHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    flexWrap: 'wrap',
    gap: 8,
    marginBottom: 8,
  },
  voiceHeroBadge: {
    fontSize: 11,
    fontWeight: '800',
    backgroundColor: '#6366F1',
    color: '#FFFFFF',
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 8,
  },
  voiceHeroTitle: {
    fontSize: 15.5,
    fontWeight: '800',
    color: '#0F172A',
  },
  voiceScriptText: {
    fontSize: 14.5,
    lineHeight: 22,
    color: Theme.colors.textPrimary,
    marginBottom: 12,
  },
  voiceHeroPlayButton: {
    backgroundColor: Theme.colors.voiceButton,
    paddingVertical: 12,
    borderRadius: Theme.radius.button,
    alignItems: 'center',
  },
  voiceHeroPlayButtonActive: {
    backgroundColor: Theme.colors.voiceButtonPressed,
  },
  voiceHeroPlayButtonPaused: {
    backgroundColor: '#D97706',
  },
  voiceHeroPlayText: {
    color: '#FFFFFF',
    fontWeight: '700',
    fontSize: 14,
  },

  // Sections
  section: {
    marginBottom: 16,
  },
  sectionHeader: {
    fontSize: 16.5,
    fontWeight: '800',
    color: '#0F172A',
    marginBottom: 8,
  },
  sectionHeaderRowWithAction: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    flexWrap: 'wrap',
    gap: 8,
    marginBottom: 4,
  },
  altToggleBtn: {
    backgroundColor: Theme.colors.surfaceAlt,
    borderWidth: 1,
    borderColor: Theme.colors.borderDark,
    borderRadius: Theme.radius.chip,
    paddingHorizontal: 12,
    paddingVertical: 5,
    flexDirection: 'row',
    alignItems: 'center',
  },
  altToggleBtnActive: {
    backgroundColor: Theme.colors.primaryTint,
    borderColor: Theme.colors.primary,
  },
  altToggleBtnText: {
    fontSize: 12,
    fontWeight: '700',
    color: Theme.colors.textSecondary,
  },
  altToggleBtnTextActive: {
    color: Theme.colors.onPrimaryText,
  },
  altExplanationBadge: {
    backgroundColor: 'rgba(95, 237, 197, 0.22)',
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 4,
    alignSelf: 'flex-start',
    marginTop: 4,
    marginBottom: 8,
  },
  altExplanationBadgeText: {
    fontSize: 11.5,
    fontWeight: '700',
    color: '#064E3B',
  },
  altExplanationActionRow: {
    flexDirection: 'row',
    justifyContent: 'flex-end',
    marginTop: 12,
  },
  altToggleBtnBottom: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#F1F5F9',
    borderWidth: 1,
    borderColor: '#E2E8F0',
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 6,
    alignSelf: 'flex-end',
  },
  altToggleBtnBottomActive: {
    backgroundColor: '#CFFAEE',
    borderColor: '#5FEDC5',
  },
  altToggleBtnTextBottom: {
    fontSize: 12.5,
    fontWeight: '600',
    color: '#475569',
  },
  altToggleBtnTextBottomActive: {
    color: '#064E3B',
    fontWeight: '700',
  },

  // Näidis (Worked Example) Styles
  naidisHeaderRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    flexWrap: 'wrap',
    marginBottom: 4,
  },
  naidisBadge: {
    backgroundColor: 'rgba(95, 237, 197, 0.22)',
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 8,
  },
  naidisBadgeText: {
    fontSize: 11.5,
    fontWeight: '800',
    color: '#064E3B',
    letterSpacing: 0.5,
  },
  naidisGivenBox: {
    backgroundColor: Theme.colors.surfaceAlt,
    borderLeftWidth: 3.5,
    borderLeftColor: Theme.colors.voiceButton,
    borderRadius: 8,
    padding: 10,
    marginVertical: 8,
  },
  naidisGivenLabel: {
    fontSize: 11,
    fontWeight: '800',
    color: Theme.colors.textSecondary,
    marginBottom: 2,
    letterSpacing: 0.4,
  },
  naidisGivenText: {
    fontSize: 14,
    lineHeight: 20,
    fontWeight: '600',
    color: Theme.colors.textPrimary,
  },
  naidisStepsContainer: {
    marginVertical: 6,
    gap: 8,
  },
  naidisStepsHeader: {
    fontSize: 13,
    fontWeight: '700',
    color: Theme.colors.textSecondary,
    marginBottom: 2,
  },
  naidisStepRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    backgroundColor: '#FFFFFF',
    borderWidth: 1,
    borderColor: Theme.colors.border,
    borderRadius: 10,
    padding: 10,
    gap: 10,
  },
  naidisStepNumberBadge: {
    width: 24,
    height: 24,
    borderRadius: 12,
    backgroundColor: Theme.colors.primaryTint,
    borderWidth: 1,
    borderColor: Theme.colors.primary,
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: 1,
  },
  naidisStepNumberText: {
    fontSize: 12,
    fontWeight: '800',
    color: Theme.colors.onPrimaryText,
  },
  naidisStepText: {
    flex: 1,
    fontSize: 13.5,
    lineHeight: 20,
    color: Theme.colors.textPrimary,
  },
  naidisNoteBox: {
    backgroundColor: '#FEF3C7',
    borderWidth: 1,
    borderColor: '#FDE68A',
    borderRadius: 10,
    padding: 10,
    marginTop: 8,
  },
  naidisNoteText: {
    fontSize: 13,
    lineHeight: 18,
    color: '#92400E',
  },

  // Gymnasium Academic Answer Card Styles
  academicHeaderRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    flexWrap: 'wrap',
    marginBottom: 8,
  },
  academicBadge: {
    backgroundColor: 'rgba(6, 78, 59, 0.1)',
    borderWidth: 1,
    borderColor: 'rgba(6, 78, 59, 0.2)',
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 8,
  },
  academicBadgeText: {
    fontSize: 11.5,
    fontWeight: '800',
    color: '#064E3B',
    letterSpacing: 0.5,
  },
  academicAnswerBox: {
    backgroundColor: '#F8FAFC',
    borderWidth: 1.5,
    borderColor: '#E2E8F0',
    borderRadius: 14,
    padding: 16,
    marginVertical: 10,
  },
  academicAnswerText: {
    fontSize: 16,
    fontWeight: '700',
    color: '#0F172A',
    lineHeight: 24,
  },
  academicAnswerHint: {
    fontSize: 13,
    color: '#64748B',
    lineHeight: 18,
    marginTop: 4,
  },
  sectionHeaderJunior: {
    fontSize: 16,
    fontWeight: '800',
    color: Theme.colors.textPrimary,
  },
  sectionAudioCenteredContainer: {
    alignItems: 'center',
    marginVertical: 10,
  },
  sectionAudioBtn: {
    backgroundColor: Theme.colors.voiceButton,
    paddingHorizontal: 22,
    paddingVertical: 8,
    borderRadius: Theme.radius.chip,
    minWidth: 140,
    alignItems: 'center',
    justifyContent: 'center',
    ...Theme.shadow.chip,
  },
  sectionAudioBtnJunior: {
    backgroundColor: Theme.colors.voiceButton,
  },
  sectionAudioBtnActive: {
    backgroundColor: Theme.colors.voiceButtonPressed,
  },
  sectionAudioBtnPaused: {
    backgroundColor: '#D97706',
  },
  sectionAudioBtnText: {
    fontSize: 14,
    fontWeight: '700',
    color: '#FFFFFF',
  },
  sectionAudioBtnTextJunior: {
    fontSize: 14,
    fontWeight: '700',
    color: '#FFFFFF',
  },
  explanationText: {
    fontSize: 14.5,
    lineHeight: 22,
    color: Theme.colors.textPrimary,
  },
  explanationTextJunior: {
    fontSize: 14.5,
    lineHeight: 22,
    color: Theme.colors.textPrimary,
  },
  instructionText: {
    fontSize: 14.5,
    lineHeight: 22,
    color: Theme.colors.textPrimary,
  },
  instructionTextJunior: {
    fontSize: 14.5,
    lineHeight: 22,
    color: Theme.colors.textPrimary,
  },

  // Vocabulary Chips
  vocabChipsContainer: {
    marginTop: 8,
    gap: 10,
  },
  vocabItemCard: {
    backgroundColor: Theme.colors.surfaceAlt,
    borderRadius: 12,
    padding: 10,
    borderWidth: 1,
    borderColor: Theme.colors.border,
  },
  vocabPillRow: {
    flexDirection: 'row',
    alignItems: 'center',
    flexWrap: 'wrap',
  },
  vocabEstChip: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: Theme.colors.surface,
    borderWidth: 1,
    borderColor: Theme.colors.border,
    borderRadius: Theme.radius.chip,
    paddingHorizontal: 12,
    paddingVertical: 6,
    ...Theme.shadow.chip,
  },
  vocabEstText: {
    fontSize: 15,
    fontWeight: '800',
    color: Theme.colors.textPrimary,
  },
  vocabCircleSpeaker: {
    width: 26,
    height: 26,
    borderRadius: 13,
    backgroundColor: Theme.colors.voiceButton,
    justifyContent: 'center',
    alignItems: 'center',
    marginLeft: 8,
  },
  vocabCircleSpeakerActive: {
    backgroundColor: Theme.colors.voiceButtonPressed,
  },
  vocabCircleSpeakerPaused: {
    backgroundColor: '#D97706',
  },
  vocabSpeakerIconWhite: {
    fontSize: 12,
    color: '#FFFFFF',
  },
  vocabRuText: {
    fontSize: 13.5,
    color: Theme.colors.textSecondary,
    marginLeft: 10,
    flexShrink: 1,
  },
  vocabExampleBox: {
    flexDirection: 'row',
    alignItems: 'center',
    marginTop: 8,
    backgroundColor: Theme.colors.surface,
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: Theme.colors.border,
  },
  vocabExampleCircleBtn: {
    width: 22,
    height: 22,
    borderRadius: 11,
    backgroundColor: Theme.colors.voiceButton,
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 8,
  },
  vocabExampleIconWhite: {
    fontSize: 10,
    color: '#FFFFFF',
  },
  vocabExampleText: {
    fontSize: 12.5,
    color: Theme.colors.textSecondary,
    fontStyle: 'italic',
    flex: 1,
  },

  // Save & Next Action Buttons
  saveCardButton: {
    backgroundColor: Theme.colors.primary,
    borderRadius: Theme.radius.card,
    paddingVertical: 14,
    alignItems: 'center',
    marginTop: 14,
    ...Theme.shadow.card,
  },
  saveCardButtonJunior: {
    backgroundColor: Theme.colors.primary,
  },
  saveCardButtonSenior: {
    backgroundColor: Theme.colors.primary,
  },
  saveCardButtonSaved: {
    backgroundColor: '#CFFAEE',
    borderWidth: 1.5,
    borderColor: '#5FEDC5',
    elevation: 0,
    shadowOpacity: 0,
  },
  saveCardButtonText: {
    color: Theme.colors.onPrimaryText,
    fontSize: 15.5,
    fontWeight: '800',
    backgroundColor: 'transparent',
  },
  saveCardButtonTextJunior: {
    fontSize: 15.5,
    backgroundColor: 'transparent',
  },
  saveCardButtonTextSaved: {
    color: Theme.colors.onPrimaryText,
    backgroundColor: 'transparent',
  },
  nextTaskButton: {
    backgroundColor: Theme.colors.surface,
    borderWidth: 1.5,
    borderColor: Theme.colors.primary,
    borderRadius: Theme.radius.card,
    paddingVertical: 14,
    alignItems: 'center',
    marginTop: 10,
    ...Theme.shadow.card,
  },
  nextTaskButtonJunior: {
    backgroundColor: Theme.colors.surface,
  },
  nextTaskButtonSenior: {
    backgroundColor: Theme.colors.surface,
  },
  nextTaskButtonText: {
    color: Theme.colors.onPrimaryText,
    fontSize: 15,
    fontWeight: '700',
  },
  nextTaskButtonTextJunior: {
    fontSize: 15,
  },

  // Tab 2: Dictionary & History
  header: {
    marginBottom: 16,
    alignItems: 'center',
  },
  headerTopRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    width: '100%',
    marginBottom: 4,
  },
  pupilPill: {
    backgroundColor: '#CFFAEE',
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: Theme.radius.badge,
    borderWidth: 1,
    borderColor: '#5FEDC5',
    elevation: 0,
    shadowOpacity: 0,
  },
  pupilPillJunior: {
    backgroundColor: '#FEF3C7',
    borderColor: '#FCD34D',
    elevation: 0,
    shadowOpacity: 0,
  },
  pupilPillText: {
    fontSize: 12,
    fontWeight: '600',
    color: Theme.colors.onPrimaryText,
    backgroundColor: 'transparent',
  },
  pupilPillTextJunior: {
    color: '#78350F',
    backgroundColor: 'transparent',
  },
  appTitle: {
    fontSize: 24,
    fontWeight: '800',
    color: Theme.colors.textPrimary,
  },
  appTitleJunior: {
    fontSize: 24,
  },
  subtitle: {
    fontSize: 13,
    color: Theme.colors.textSecondary,
    textAlign: 'center',
    marginTop: 4,
  },
  subtitleJunior: {
    fontSize: 13,
  },
  segmentedControl: {
    flexDirection: 'row',
    backgroundColor: Theme.colors.surfaceAlt,
    borderRadius: 12,
    padding: 3,
    marginBottom: 16,
    borderWidth: 1,
    borderColor: Theme.colors.border,
  },
  segmentBtn: {
    flex: 1,
    paddingVertical: 9,
    alignItems: 'center',
    borderRadius: 10,
  },
  segmentBtnActiveJunior: {
    backgroundColor: Theme.colors.primary,
  },
  segmentBtnActiveSenior: {
    backgroundColor: Theme.colors.primary,
  },
  segmentBtnText: {
    fontSize: 13,
    fontWeight: '600',
    color: Theme.colors.textSecondary,
  },
  segmentBtnTextActive: {
    color: Theme.colors.onPrimaryText,
    fontWeight: '800',
  },
  listHint: {
    fontSize: 12,
    color: Theme.colors.textSecondary,
    fontStyle: 'italic',
    marginBottom: 10,
  },
  vocabList: {
    gap: 8,
  },
  vocabCard: {
    backgroundColor: Theme.colors.surface,
    borderRadius: Theme.radius.card,
    padding: 14,
    borderWidth: 1,
    borderColor: Theme.colors.border,
    marginBottom: 8,
    ...Theme.shadow.card,
  },
  vocabCardJunior: {
    borderRadius: Theme.radius.card,
  },
  vocabCardExpanded: {
    borderColor: Theme.colors.primary,
    backgroundColor: Theme.colors.surfaceAlt,
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
    fontWeight: '800',
    color: Theme.colors.textPrimary,
  },
  vocabCardEstJunior: {
    fontSize: 16,
  },
  vocabCardSpeaker: {
    marginLeft: 8,
    backgroundColor: Theme.colors.voiceButton,
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 8,
  },
  vocabCardSpeakerActive: {
    backgroundColor: Theme.colors.voiceButtonPressed,
  },
  vocabCardSpeakerPaused: {
    backgroundColor: '#D97706',
  },
  vocabCardSpeakerIcon: {
    fontSize: 12,
    color: '#FFFFFF',
  },
  vocabCardDelete: {
    padding: 4,
  },
  vocabCardDeleteText: {
    color: Theme.colors.textMuted,
    fontSize: 15,
    fontWeight: 'bold',
  },
  vocabCardRu: {
    fontSize: 14,
    color: Theme.colors.textSecondary,
    marginTop: 2,
  },
  vocabCardExampleBox: {
    marginTop: 8,
    backgroundColor: Theme.colors.surfaceAlt,
    padding: 8,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: Theme.colors.border,
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
    color: Theme.colors.textSecondary,
  },
  vocabCardExampleText: {
    fontSize: 12.5,
    color: Theme.colors.textPrimary,
    fontStyle: 'italic',
  },

  emptyBox: {
    alignItems: 'center',
    justifyContent: 'center',
    padding: 30,
    marginTop: 40,
    backgroundColor: Theme.colors.surface,
    borderRadius: Theme.radius.card,
    borderWidth: 1,
    borderColor: Theme.colors.border,
    ...Theme.shadow.card,
  },
  emptyIcon: {
    fontSize: 44,
    marginBottom: 12,
  },
  emptyTitle: {
    fontSize: 17,
    fontWeight: '800',
    color: Theme.colors.textPrimary,
    marginBottom: 6,
  },
  emptyText: {
    fontSize: 13.5,
    color: Theme.colors.textSecondary,
    textAlign: 'center',
    lineHeight: 19,
  },

  // History List
  historyList: {
    gap: 10,
  },
  historyItemCard: {
    backgroundColor: Theme.colors.surface,
    borderRadius: Theme.radius.card,
    padding: 14,
    borderWidth: 1,
    borderColor: Theme.colors.border,
    ...Theme.shadow.card,
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
    color: Theme.colors.textMuted,
    fontWeight: '500',
  },
  historyBadgeRow: {
    flexDirection: 'row',
    gap: 6,
  },
  historyTypeBadge: {
    backgroundColor: Theme.colors.slotSuccessBg,
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 6,
  },
  historyTypeBadgeText: {
    fontSize: 11,
    fontWeight: '700',
    color: Theme.colors.onPrimaryText,
  },
  historyItemBadge: {
    backgroundColor: Theme.colors.surfaceAlt,
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 6,
    borderWidth: 1,
    borderColor: Theme.colors.border,
  },
  historyItemBadgeText: {
    fontSize: 11,
    fontWeight: '600',
    color: Theme.colors.textSecondary,
  },
  historyItemTitle: {
    fontSize: 16,
    fontWeight: '800',
    color: Theme.colors.textPrimary,
    marginBottom: 4,
  },
  historyItemSnippet: {
    fontSize: 13,
    color: Theme.colors.textSecondary,
    lineHeight: 18,
    marginBottom: 10,
  },
  historyItemActions: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    borderTopWidth: 1,
    borderTopColor: Theme.colors.border,
    paddingTop: 8,
  },
  historyOpenBtn: {
    backgroundColor: Theme.colors.primary,
    paddingHorizontal: 14,
    paddingVertical: 7,
    borderRadius: 10,
  },
  historyOpenBtnText: {
    color: Theme.colors.onPrimaryText,
    fontSize: 13,
    fontWeight: '800',
  },
  historyDeleteBtn: {
    paddingHorizontal: 10,
    paddingVertical: 7,
  },
  historyDeleteBtnText: {
    color: Theme.colors.danger,
    fontSize: 13,
    fontWeight: '600',
  },

  // Tab 3: Settings
  card: {
    backgroundColor: '#FFFFFF',
    borderRadius: 20,
    padding: 18,
    marginBottom: 16,
    borderWidth: 1,
    borderColor: '#E2E8F0',
    ...Theme.shadow.card,
  },
  cardJunior: {
    borderRadius: 20,
  },
  cardSenior: {
    borderRadius: 20,
  },
  cardHeaderRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  cardTitle: {
    fontSize: 16.5,
    fontWeight: '800',
    color: '#0F172A',
  },
  cardTitleJunior: {
    fontSize: 16.5,
  },
  tierTag: {
    alignSelf: 'flex-start',
    marginTop: 6,
    marginBottom: 6,
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: Theme.radius.badge,
    backgroundColor: Theme.colors.slotSuccessBg,
    borderWidth: 1,
    borderColor: Theme.colors.primary,
  },
  tierTagJunior: {},
  tierTagSenior: {},
  tierTagText: {
    fontSize: 12,
    fontWeight: '700',
    color: Theme.colors.onPrimaryText,
  },
  tierTagTextJunior: {},
  tierTagTextSenior: {},
  caption: {
    fontSize: 12,
    color: Theme.colors.textSecondary,
    marginBottom: 12,
    marginTop: 2,
  },
  inputRow: {
    marginBottom: 12,
  },
  label: {
    fontSize: 13,
    fontWeight: '700',
    color: Theme.colors.textPrimary,
    marginBottom: 6,
  },
  labelJunior: {
    fontSize: 13,
  },
  bold: {
    fontWeight: '800',
    color: Theme.colors.onPrimaryText,
  },
  textInput: {
    borderWidth: 1,
    borderColor: Theme.colors.border,
    borderRadius: Theme.radius.button,
    paddingHorizontal: 12,
    paddingVertical: 10,
    fontSize: 14,
    backgroundColor: Theme.colors.surfaceAlt,
    color: Theme.colors.textPrimary,
  },
  textInputJunior: {
    borderRadius: Theme.radius.button,
  },
  gradeGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 6,
    marginBottom: 14,
  },
  gradeChip: {
    width: 42,
    height: 38,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: Theme.colors.border,
    backgroundColor: Theme.colors.surfaceAlt,
    alignItems: 'center',
    justifyContent: 'center',
  },
  gradeChipJunior: {
    width: 42,
    height: 38,
  },
  gradeChipActiveJunior: {
    backgroundColor: Theme.colors.primary,
    borderColor: Theme.colors.primary,
  },
  gradeChipActiveSenior: {
    backgroundColor: Theme.colors.primary,
    borderColor: Theme.colors.primary,
  },
  gradeChipText: {
    fontSize: 13,
    fontWeight: '600',
    color: Theme.colors.textPrimary,
  },
  gradeChipTextJunior: {
    fontSize: 13,
  },
  gradeChipTextActive: {
    color: Theme.colors.onPrimaryText,
    fontWeight: '800',
  },
  interestsSection: {
    marginTop: 4,
  },
  interestsInput: {
    minHeight: 50,
    textAlignVertical: 'top',
  },
  interestsHint: {
    fontSize: 12,
    color: Theme.colors.textSecondary,
    fontStyle: 'italic',
    lineHeight: 17,
    marginTop: 6,
    marginBottom: 10,
    backgroundColor: Theme.colors.surfaceAlt,
    padding: 8,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: Theme.colors.border,
  },
  interestsHintJunior: {},
  suggestionsTitle: {
    fontSize: 12,
    fontWeight: '700',
    color: Theme.colors.textSecondary,
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
    backgroundColor: Theme.colors.surfaceAlt,
    borderWidth: 1,
    borderColor: Theme.colors.border,
  },
  suggestionChipSelected: {
    backgroundColor: Theme.colors.slotSuccessBg,
    borderColor: Theme.colors.primary,
  },
  suggestionText: {
    fontSize: 12,
    color: Theme.colors.textSecondary,
    fontWeight: '500',
  },
  suggestionTextSelected: {
    color: Theme.colors.onPrimaryText,
    fontWeight: '800',
  },
  storageStats: {
    fontSize: 13.5,
    color: Theme.colors.textPrimary,
    marginBottom: 6,
  },
  clearDataBtn: {
    marginTop: 14,
    backgroundColor: Theme.colors.dangerBg,
    borderWidth: 1,
    borderColor: '#FCA5A5',
    paddingVertical: 10,
    borderRadius: 10,
    alignItems: 'center',
  },
  clearDataBtnText: {
    color: Theme.colors.danger,
    fontWeight: '700',
    fontSize: 13,
  },
});
