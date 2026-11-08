import React, { useState, useEffect } from 'react';
import {
  StyleSheet,
  View,
  Text,
  TouchableOpacity,
  TouchableWithoutFeedback,
  Dimensions,
  Animated,
  BackHandler,
} from 'react-native';
import { Theme } from '../theme/colors';

const { width: SCREEN_WIDTH } = Dimensions.get('window');
const ALERT_WIDTH = Math.min(SCREEN_WIDTH * 0.86, 340);

export interface ThemedAlertButton {
  text: string;
  onPress?: () => void;
  style?: 'default' | 'cancel' | 'destructive';
}

export interface ThemedAlertOptions {
  cancelable?: boolean;
  icon?: string;
  onDismiss?: () => void;
}

interface AlertState {
  visible: boolean;
  title: string;
  message?: string;
  buttons: ThemedAlertButton[];
  icon?: string;
  cancelable: boolean;
  onDismiss?: () => void;
}

type AlertListener = (state: AlertState) => void;

// Stack of mounted overlay hosts so alerts always appear on the topmost surface without native UIKit <Modal> deadlocks
const listenerStack: AlertListener[] = [];

/**
 * Static ThemedAlert API - drop-in replacement for React Native's Alert.alert.
 */
export const ThemedAlert = {
  alert(
    title: string,
    message?: string,
    buttons?: ThemedAlertButton[],
    options?: ThemedAlertOptions
  ) {
    const alertButtons: ThemedAlertButton[] =
      buttons && buttons.length > 0
        ? buttons
        : [{ text: 'Понятно', style: 'default' }];

    let icon = options?.icon;
    if (!icon) {
      const lower = `${title} ${message || ''}`.toLowerCase();
      if (lower.includes('ошибка') || lower.includes('не удалось') || lower.includes('сбой')) {
        icon = '❌';
      } else if (lower.includes('удалить') || lower.includes('выход') || lower.includes('выйти')) {
        icon = '⚠️';
      } else if (
        lower.includes('успеш') ||
        lower.includes('сохранен') ||
        lower.includes('спасибо') ||
        lower.includes('добро пожаловать') ||
        lower.includes('добавлен')
      ) {
        icon = '✅';
      } else if (lower.includes('камер') || lower.includes('фото') || lower.includes('галере') || lower.includes('снимок')) {
        icon = '📸';
      } else if (lower.includes('скопирован')) {
        icon = '📋';
      } else if (lower.includes('ключ') || lower.includes('профиль') || lower.includes('вошли') || lower.includes('имя')) {
        icon = '🧑‍🎓';
      } else if (lower.includes('доступ') || lower.includes('разреш')) {
        icon = '🔒';
      } else if (lower.includes('счёт') || lower.includes('email') || lower.includes('почт')) {
        icon = '📄';
      } else if (lower.includes('звук') || lower.includes('голос') || lower.includes('аудио')) {
        icon = '🔊';
      } else {
        icon = '💡';
      }
    }

    const activeListener =
      listenerStack.length > 0 ? listenerStack[listenerStack.length - 1] : null;

    if (activeListener) {
      activeListener({
        visible: true,
        title,
        message,
        buttons: alertButtons,
        icon,
        cancelable: options?.cancelable ?? true,
        onDismiss: options?.onDismiss,
      });
    } else {
      console.warn('[ThemedAlert] ThemedAlertContainer not mounted yet, alert skipped');
    }
  },

  _subscribe(listener: AlertListener) {
    listenerStack.push(listener);
    return () => {
      const idx = listenerStack.lastIndexOf(listener);
      if (idx !== -1) {
        listenerStack.splice(idx, 1);
      }
    };
  },
};

/**
 * Pure React Overlay Alert Container (No native <Modal>).
 * Eliminates iOS UIKit nested/sibling modal animation deadlocks.
 */
export const ThemedAlertContainer: React.FC = () => {
  const [alertState, setAlertState] = useState<AlertState>({
    visible: false,
    title: '',
    message: '',
    buttons: [],
    cancelable: true,
  });

  const scaleAnim = React.useRef(new Animated.Value(0.9)).current;
  const opacityAnim = React.useRef(new Animated.Value(0)).current;

  useEffect(() => {
    return ThemedAlert._subscribe((state) => {
      setAlertState(state);
      if (state.visible) {
        scaleAnim.setValue(0.9);
        opacityAnim.setValue(0);
        Animated.parallel([
          Animated.spring(scaleAnim, {
            toValue: 1,
            friction: 8,
            tension: 65,
            useNativeDriver: true,
          }),
          Animated.timing(opacityAnim, {
            toValue: 1,
            duration: 180,
            useNativeDriver: true,
          }),
        ]).start();
      }
    });
  }, [scaleAnim, opacityAnim]);

  const handleClose = React.useCallback(
    (callback?: () => void) => {
      Animated.parallel([
        Animated.timing(scaleAnim, {
          toValue: 0.95,
          duration: 140,
          useNativeDriver: true,
        }),
        Animated.timing(opacityAnim, {
          toValue: 0,
          duration: 140,
          useNativeDriver: true,
        }),
      ]).start(() => {
        setAlertState((prev) => ({ ...prev, visible: false }));
        if (alertState.onDismiss) {
          alertState.onDismiss();
        }
        if (callback) {
          callback();
        }
      });
    },
    [scaleAnim, opacityAnim, alertState.onDismiss]
  );

  const handleBackdropPress = React.useCallback(() => {
    if (!alertState.cancelable) return;
    const cancelBtn = alertState.buttons.find((b) => b.style === 'cancel');
    handleClose(cancelBtn?.onPress);
  }, [alertState.cancelable, alertState.buttons, handleClose]);

  useEffect(() => {
    if (!alertState.visible) return;
    const sub = BackHandler.addEventListener('hardwareBackPress', () => {
      if (alertState.cancelable) {
        handleBackdropPress();
      }
      return true;
    });
    return () => sub.remove();
  }, [alertState.visible, alertState.cancelable, handleBackdropPress]);

  if (!alertState.visible) {
    return null;
  }

  const isMultiButton = alertState.buttons.length > 1;
  const isDestructive = alertState.buttons.some((b) => b.style === 'destructive');

  return (
    <View style={styles.overlayRoot} pointerEvents="auto">
      <TouchableWithoutFeedback onPress={handleBackdropPress}>
        <Animated.View style={[styles.backdrop, { opacity: opacityAnim }]}>
          <TouchableWithoutFeedback>
            <Animated.View
              style={[
                styles.card,
                {
                  opacity: opacityAnim,
                  transform: [{ scale: scaleAnim }],
                },
              ]}
            >
              {alertState.icon && (
                <View
                  style={[
                    styles.iconCircle,
                    isDestructive && styles.iconCircleDestructive,
                  ]}
                >
                  <Text style={styles.iconEmoji}>{alertState.icon}</Text>
                </View>
              )}

              <Text style={styles.title}>{alertState.title}</Text>

              {Boolean(alertState.message) && (
                <Text style={styles.message}>{alertState.message}</Text>
              )}

              <View
                style={[
                  styles.buttonsContainer,
                  isMultiButton && alertState.buttons.length === 2 && styles.buttonsRow,
                ]}
              >
                {alertState.buttons.map((btn, index) => {
                  const isCancel = btn.style === 'cancel';
                  const isDestruct = btn.style === 'destructive';
                  const isPrimary = !isCancel && !isDestruct;

                  return (
                    <TouchableOpacity
                      key={index}
                      style={[
                        styles.btnBase,
                        isMultiButton && alertState.buttons.length === 2 && styles.btnHalf,
                        isPrimary && styles.btnPrimary,
                        isCancel && styles.btnCancel,
                        isDestruct && styles.btnDestructive,
                      ]}
                      onPress={() => handleClose(btn.onPress)}
                      activeOpacity={0.8}
                    >
                      <Text
                        style={[
                          styles.btnTextBase,
                          isPrimary && styles.btnPrimaryText,
                          isCancel && styles.btnCancelText,
                          isDestruct && styles.btnDestructiveText,
                        ]}
                      >
                        {btn.text}
                      </Text>
                    </TouchableOpacity>
                  );
                })}
              </View>
            </Animated.View>
          </TouchableWithoutFeedback>
        </Animated.View>
      </TouchableWithoutFeedback>
    </View>
  );
};

export const ThemedAlertModal = ThemedAlertContainer;

const styles = StyleSheet.create({
  overlayRoot: {
    ...StyleSheet.absoluteFill,
    zIndex: 99999,
    elevation: 99999,
  },
  backdrop: {
    ...StyleSheet.absoluteFill,
    backgroundColor: 'rgba(5, 8, 11, 0.82)',
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: 20,
    zIndex: 99999,
  },
  card: {
    width: ALERT_WIDTH,
    backgroundColor: '#161B20',
    borderRadius: 24,
    borderWidth: 1,
    borderColor: '#2D3844',
    paddingTop: 24,
    paddingBottom: 20,
    paddingHorizontal: 20,
    alignItems: 'center',
    ...Theme.shadow.modal,
  },
  iconCircle: {
    width: 56,
    height: 56,
    borderRadius: 28,
    backgroundColor: 'rgba(95, 237, 197, 0.14)',
    borderWidth: 1.5,
    borderColor: '#5FEDC5',
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 14,
    ...Theme.shadow.chip,
  },
  iconCircleDestructive: {
    backgroundColor: 'rgba(239, 68, 68, 0.14)',
    borderColor: '#EF4444',
  },
  iconEmoji: {
    fontSize: 26,
  },
  title: {
    fontSize: 18,
    fontWeight: '800',
    color: '#FFFFFF',
    textAlign: 'center',
    letterSpacing: -0.3,
    marginBottom: 6,
  },
  message: {
    fontSize: 13.5,
    fontWeight: '500',
    color: '#CBD5E1',
    textAlign: 'center',
    lineHeight: 19,
    marginBottom: 18,
    paddingHorizontal: 4,
  },
  buttonsContainer: {
    width: '100%',
    marginTop: 4,
  },
  buttonsRow: {
    flexDirection: 'row',
    gap: 10,
  },
  btnBase: {
    width: '100%',
    paddingVertical: 12.5,
    paddingHorizontal: 14,
    borderRadius: 14,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 8,
  },
  btnHalf: {
    flex: 1,
    width: 'auto',
    marginBottom: 0,
  },
  btnPrimary: {
    backgroundColor: '#5FEDC5',
    ...Theme.shadow.button,
  },
  btnPrimaryText: {
    fontSize: 14.5,
    fontWeight: '800',
    color: '#064E3B',
  },
  btnCancel: {
    backgroundColor: '#202830',
    borderWidth: 1,
    borderColor: '#334155',
  },
  btnCancelText: {
    fontSize: 14,
    fontWeight: '700',
    color: '#94A3B8',
  },
  btnDestructive: {
    backgroundColor: 'rgba(239, 68, 68, 0.15)',
    borderWidth: 1,
    borderColor: 'rgba(239, 68, 68, 0.4)',
  },
  btnDestructiveText: {
    fontSize: 14,
    fontWeight: '700',
    color: '#F87171',
  },
  btnTextBase: {
    fontSize: 14,
    textAlign: 'center',
  },
});
