import React, { useState, useEffect } from 'react';
import {
  Modal,
  View,
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  ActivityIndicator,
  Alert,
  KeyboardAvoidingView,
  Platform,
  ScrollView,
} from 'react-native';
import {
  getApiBaseUrl,
  setCustomApiBaseUrl,
  resetCustomApiBaseUrl,
  isCustomApiUrlActive,
  testServerConnection,
  DEFAULT_API_BASE_URL,
} from '../config/apiConfig';
import { Theme, darkTheme } from '../theme/colors';

interface ServerConfigModalProps {
  visible: boolean;
  onClose: () => void;
  onSaved?: (newUrl: string) => void;
}

export const ServerConfigModal: React.FC<ServerConfigModalProps> = ({
  visible,
  onClose,
  onSaved,
}) => {
  const [urlInput, setUrlInput] = useState<string>('');
  const [currentUrl, setCurrentUrl] = useState<string>('');
  const [isCustom, setIsCustom] = useState<boolean>(false);
  const [isTesting, setIsTesting] = useState<boolean>(false);
  const [testResult, setTestResult] = useState<{
    tested: boolean;
    ok: boolean;
    message: string;
  }>({ tested: false, ok: false, message: '' });

  useEffect(() => {
    if (visible) {
      loadCurrentConfig();
    }
  }, [visible]);

  const loadCurrentConfig = async () => {
    const active = await getApiBaseUrl();
    const hasCustom = await isCustomApiUrlActive();
    setCurrentUrl(active);
    setUrlInput(active);
    setIsCustom(hasCustom);
    setTestResult({ tested: false, ok: false, message: '' });
  };

  const handleTestConnection = async () => {
    const trimmed = urlInput.trim();
    if (!trimmed) {
      Alert.alert('Ошибка', 'Введите адрес сервера для проверки');
      return;
    }

    setIsTesting(true);
    setTestResult({ tested: false, ok: false, message: '' });

    const res = await testServerConnection(trimmed, 5000);
    setIsTesting(false);

    if (res.ok) {
      setTestResult({
        tested: true,
        ok: true,
        message: 'Сервер доступен (HTTP 200). Связь установлена!',
      });
    } else {
      setTestResult({
        tested: true,
        ok: false,
        message: `Не удалось связаться: ${res.error || 'Ошибка сети'}. Проверьте адрес и работу бэкенда.`,
      });
    }
  };

  const handleSave = async () => {
    const trimmed = urlInput.trim();
    if (!trimmed) {
      Alert.alert('Ошибка', 'Адрес сервера не может быть пустым');
      return;
    }

    try {
      const savedUrl = await setCustomApiBaseUrl(trimmed);
      setCurrentUrl(savedUrl);
      setIsCustom(true);
      if (onSaved) {
        onSaved(savedUrl);
      }
      Alert.alert('Готово', `Адрес сервера обновлен:\n${savedUrl}`);
      onClose();
    } catch (e: any) {
      Alert.alert('Ошибка сохранения', e?.message || 'Не удалось сохранить адрес');
    }
  };

  const handleReset = async () => {
    Alert.alert(
      'Сбросить настройки?',
      `Вернуть стандартный адрес сервера:\n${DEFAULT_API_BASE_URL}`,
      [
        { text: 'Отмена', style: 'cancel' },
        {
          text: 'Сбросить',
          style: 'destructive',
          onPress: async () => {
            await resetCustomApiBaseUrl();
            const defUrl = await getApiBaseUrl();
            setCurrentUrl(defUrl);
            setUrlInput(defUrl);
            setIsCustom(false);
            setTestResult({ tested: false, ok: false, message: '' });
            if (onSaved) {
              onSaved(defUrl);
            }
          },
        },
      ]
    );
  };

  const setPreset = (presetUrl: string) => {
    setUrlInput(presetUrl);
    setTestResult({ tested: false, ok: false, message: '' });
  };

  return (
    <Modal
      visible={visible}
      animationType="slide"
      transparent={true}
      onRequestClose={onClose}
    >
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        style={styles.overlay}
      >
        <View style={styles.card}>
          <ScrollView showsVerticalScrollIndicator={false}>
            {/* Header */}
            <View style={styles.header}>
              <View style={styles.headerTitleRow}>
                <Text style={styles.headerIcon}>🔌</Text>
                <Text style={styles.headerTitle}>Адрес сервера (API)</Text>
              </View>
              <TouchableOpacity
                onPress={onClose}
                style={styles.closeBtn}
                hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}
              >
                <Text style={styles.closeBtnText}>✕</Text>
              </TouchableOpacity>
            </View>

            {/* Current Active Status */}
            <View style={styles.statusBox}>
              <View style={styles.statusRow}>
                <Text style={styles.statusLabel}>Текущий активный адрес:</Text>
                <View
                  style={[
                    styles.statusBadge,
                    isCustom ? styles.badgeCustom : styles.badgeDefault,
                  ]}
                >
                  <Text
                    style={[
                      styles.statusBadgeText,
                      isCustom ? styles.badgeCustomText : styles.badgeDefaultText,
                    ]}
                  >
                    {isCustom ? 'Пользовательский' : 'По умолчанию'}
                  </Text>
                </View>
              </View>
              <Text style={styles.currentUrlText} numberOfLines={2}>
                {currentUrl || DEFAULT_API_BASE_URL}
              </Text>
            </View>

            {/* URL Input */}
            <Text style={styles.inputLabel}>Укажите IP или адрес туннеля:</Text>
            <TextInput
              style={styles.input}
              value={urlInput}
              onChangeText={setUrlInput}
              placeholder="http://10.253.79.137:8080 или https://..."
              placeholderTextColor="#64748B"
              autoCapitalize="none"
              autoCorrect={false}
              keyboardType="url"
            />

            {/* Quick Presets */}
            <Text style={styles.presetsLabel}>Быстрые пресеты:</Text>
            <View style={styles.presetsRow}>
              <TouchableOpacity
                style={styles.presetChip}
                onPress={() => setPreset('http://10.253.79.137:8080')}
              >
                <Text style={styles.presetChipText}>📱 Hotspot (10.253.79.137)</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={styles.presetChip}
                onPress={() => setPreset('http://10.0.2.2:8080')}
              >
                <Text style={styles.presetChipText}>💻 Эмулятор (10.0.2.2)</Text>
              </TouchableOpacity>
            </View>

            {/* Test Connection Button */}
            <TouchableOpacity
              style={styles.testBtn}
              onPress={handleTestConnection}
              disabled={isTesting}
              activeOpacity={0.7}
            >
              {isTesting ? (
                <ActivityIndicator size="small" color="#5FEDC5" />
              ) : (
                <Text style={styles.testBtnText}>⚡ Проверить связь с сервером</Text>
              )}
            </TouchableOpacity>

            {/* Test Result Feedback */}
            {testResult.tested && (
              <View
                style={[
                  styles.resultBox,
                  testResult.ok ? styles.resultBoxOk : styles.resultBoxFail,
                ]}
              >
                <Text
                  style={[
                    styles.resultText,
                    testResult.ok ? styles.resultTextOk : styles.resultTextFail,
                  ]}
                >
                  {testResult.message}
                </Text>
              </View>
            )}

            {/* Hint Box */}
            <View style={styles.hintBox}>
              <Text style={styles.hintTitle}>💡 Тестирование через 4G / удалённо:</Text>
              <Text style={styles.hintText}>
                Если телефон не в одной Wi-Fi сети с ПК, запустите на компьютере Cloudflare Tunnel:
              </Text>
              <Text style={styles.hintCode}>cloudflared tunnel --url http://localhost:8080</Text>
              <Text style={styles.hintText}>
                и вставьте полученный HTTPS-адрес (https://xxx.trycloudflare.com) в поле выше.
              </Text>
            </View>

            {/* Action Buttons */}
            <View style={styles.actionRow}>
              <TouchableOpacity
                style={styles.saveBtn}
                onPress={handleSave}
                activeOpacity={0.8}
              >
                <Text style={styles.saveBtnText}>Сохранить</Text>
              </TouchableOpacity>

              {isCustom && (
                <TouchableOpacity
                  style={styles.resetBtn}
                  onPress={handleReset}
                  activeOpacity={0.7}
                >
                  <Text style={styles.resetBtnText}>Сбросить</Text>
                </TouchableOpacity>
              )}
            </View>
          </ScrollView>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
};

const styles = StyleSheet.create({
  overlay: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.75)',
    justifyContent: 'center',
    alignItems: 'center',
    padding: 20,
  },
  card: {
    width: '100%',
    maxHeight: '90%',
    backgroundColor: '#161B20',
    borderRadius: 24,
    borderWidth: 1,
    borderColor: '#242F38',
    padding: 20,
    ...Theme.shadow.modal,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 16,
  },
  headerTitleRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  headerIcon: {
    fontSize: 20,
    marginRight: 8,
  },
  headerTitle: {
    fontSize: 18,
    fontWeight: '800',
    color: '#FFFFFF',
  },
  closeBtn: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: '#202830',
    alignItems: 'center',
    justifyContent: 'center',
  },
  closeBtnText: {
    color: '#94A3B8',
    fontSize: 16,
    fontWeight: '700',
  },
  statusBox: {
    backgroundColor: '#1E252D',
    borderRadius: 14,
    padding: 12,
    marginBottom: 16,
    borderWidth: 1,
    borderColor: '#2A3642',
  },
  statusRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 6,
  },
  statusLabel: {
    fontSize: 12,
    color: '#94A3B8',
    fontWeight: '600',
  },
  statusBadge: {
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 6,
  },
  statusBadgeText: {
    fontSize: 11,
    fontWeight: '700',
  },
  badgeDefault: {
    backgroundColor: 'rgba(148, 163, 184, 0.15)',
  },
  badgeDefaultText: {
    color: '#94A3B8',
    fontSize: 11,
    fontWeight: '700',
  },
  badgeCustom: {
    backgroundColor: 'rgba(95, 237, 197, 0.16)',
  },
  badgeCustomText: {
    color: '#5FEDC5',
    fontSize: 11,
    fontWeight: '700',
  },
  currentUrlText: {
    color: '#FFFFFF',
    fontSize: 13,
    fontWeight: '600',
    fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace',
  },
  inputLabel: {
    fontSize: 13,
    fontWeight: '700',
    color: '#CBD5E1',
    marginBottom: 8,
  },
  input: {
    backgroundColor: '#101418',
    borderWidth: 1,
    borderColor: '#2D3844',
    borderRadius: 14,
    color: '#FFFFFF',
    fontSize: 14,
    fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace',
    paddingHorizontal: 14,
    paddingVertical: 12,
    marginBottom: 12,
  },
  presetsLabel: {
    fontSize: 12,
    fontWeight: '600',
    color: '#94A3B8',
    marginBottom: 6,
  },
  presetsRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
    marginBottom: 14,
  },
  presetChip: {
    backgroundColor: '#202832',
    borderWidth: 1,
    borderColor: '#2D3945',
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 10,
  },
  presetChipText: {
    color: '#CBD5E1',
    fontSize: 11,
    fontWeight: '600',
  },
  testBtn: {
    backgroundColor: 'rgba(95, 237, 197, 0.12)',
    borderWidth: 1,
    borderColor: '#5FEDC5',
    borderRadius: 14,
    paddingVertical: 12,
    alignItems: 'center',
    marginBottom: 12,
  },
  testBtnText: {
    color: '#5FEDC5',
    fontSize: 13,
    fontWeight: '700',
  },
  resultBox: {
    borderRadius: 12,
    padding: 10,
    marginBottom: 14,
    borderWidth: 1,
  },
  resultBoxOk: {
    backgroundColor: 'rgba(95, 237, 197, 0.12)',
    borderColor: 'rgba(95, 237, 197, 0.4)',
  },
  resultBoxFail: {
    backgroundColor: 'rgba(239, 68, 68, 0.12)',
    borderColor: 'rgba(239, 68, 68, 0.4)',
  },
  resultText: {
    fontSize: 12,
    lineHeight: 16,
    fontWeight: '600',
  },
  resultTextOk: {
    color: '#5FEDC5',
  },
  resultTextFail: {
    color: '#F87171',
  },
  hintBox: {
    backgroundColor: '#11161B',
    borderRadius: 12,
    padding: 12,
    borderWidth: 1,
    borderColor: '#222B34',
    marginBottom: 16,
  },
  hintTitle: {
    color: '#FCD34D',
    fontSize: 12,
    fontWeight: '700',
    marginBottom: 4,
  },
  hintText: {
    color: '#94A3B8',
    fontSize: 11,
    lineHeight: 15,
  },
  hintCode: {
    color: '#5FEDC5',
    fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace',
    fontSize: 11,
    marginVertical: 4,
    backgroundColor: '#182026',
    paddingHorizontal: 6,
    paddingVertical: 3,
    borderRadius: 6,
  },
  actionRow: {
    flexDirection: 'row',
    gap: 10,
  },
  saveBtn: {
    flex: 1,
    backgroundColor: '#5FEDC5',
    borderRadius: 14,
    paddingVertical: 13,
    alignItems: 'center',
    ...Theme.shadow.chip,
  },
  saveBtnText: {
    color: '#0D1115',
    fontSize: 14,
    fontWeight: '800',
  },
  resetBtn: {
    backgroundColor: '#202830',
    borderWidth: 1,
    borderColor: '#334155',
    borderRadius: 14,
    paddingHorizontal: 16,
    paddingVertical: 13,
    alignItems: 'center',
  },
  resetBtnText: {
    color: '#94A3B8',
    fontSize: 13,
    fontWeight: '700',
  },
});
