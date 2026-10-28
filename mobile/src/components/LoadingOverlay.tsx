import React, { useEffect, useRef } from 'react';
import {
  StyleSheet,
  View,
  Text,
  Modal,
  ActivityIndicator,
  Animated,
  Easing,
  Dimensions,
} from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { darkTheme, Theme } from '../theme/colors';

const { width: SCREEN_WIDTH } = Dimensions.get('window');

interface LoadingOverlayProps {
  visible: boolean;
  title?: string;
  subtitle?: string;
  stepText?: string;
}

export const LoadingOverlay: React.FC<LoadingOverlayProps> = ({
  visible,
  title = 'TarkApp анализирует страницу...',
  subtitle = 'Переводим термины и готовим подсказку',
  stepText,
}) => {
  const pulseAnim = useRef(new Animated.Value(1)).current;
  const scanLineAnim = useRef(new Animated.Value(0)).current;
  const glowAnim = useRef(new Animated.Value(0.4)).current;

  useEffect(() => {
    if (!visible) return;

    // Pulse animation for outer scanner frame
    const pulseLoop = Animated.loop(
      Animated.sequence([
        Animated.timing(pulseAnim, {
          toValue: 1.05,
          duration: 900,
          easing: Easing.inOut(Easing.ease),
          useNativeDriver: true,
        }),
        Animated.timing(pulseAnim, {
          toValue: 0.98,
          duration: 900,
          easing: Easing.inOut(Easing.ease),
          useNativeDriver: true,
        }),
      ])
    );

    // Glowing opacity oscillation
    const glowLoop = Animated.loop(
      Animated.sequence([
        Animated.timing(glowAnim, {
          toValue: 0.9,
          duration: 1000,
          easing: Easing.inOut(Easing.ease),
          useNativeDriver: true,
        }),
        Animated.timing(glowAnim, {
          toValue: 0.35,
          duration: 1000,
          easing: Easing.inOut(Easing.ease),
          useNativeDriver: true,
        }),
      ])
    );

    // Vertical scan line sweeping across the document icon
    const scanLoop = Animated.loop(
      Animated.sequence([
        Animated.timing(scanLineAnim, {
          toValue: 1,
          duration: 1400,
          easing: Easing.inOut(Easing.cubic),
          useNativeDriver: true,
        }),
        Animated.timing(scanLineAnim, {
          toValue: 0,
          duration: 1400,
          easing: Easing.inOut(Easing.cubic),
          useNativeDriver: true,
        }),
      ])
    );

    pulseLoop.start();
    glowLoop.start();
    scanLoop.start();

    return () => {
      pulseLoop.stop();
      glowLoop.stop();
      scanLoop.stop();
    };
  }, [visible]);

  if (!visible) return null;

  const scanTranslateY = scanLineAnim.interpolate({
    inputRange: [0, 1],
    outputRange: [-24, 28],
  });

  return (
    <Modal
      transparent
      visible={visible}
      statusBarTranslucent
      animationType="fade"
      onRequestClose={() => {
        // Prevent dismissal while loading is active
      }}
    >
      <View style={styles.overlayBackdrop} pointerEvents="auto">
        <View style={styles.cardContainer}>
          {/* Outer Pulsing Glow Box */}
          <Animated.View
            style={[
              styles.glowBox,
              {
                opacity: glowAnim,
                transform: [{ scale: pulseAnim }],
              },
            ]}
          />

          {/* Main Dark Nordic Loading Card */}
          <View style={styles.modalCard}>
            {/* Scanner Frame with Document & Sweep Line */}
            <View style={styles.scannerFrame}>
              <View style={styles.scannerDocument}>
                <Text style={styles.scannerDocEmoji}>📖</Text>
                {/* Laser scan line sweeping across */}
                <Animated.View
                  style={[
                    styles.scanLaserLine,
                    {
                      transform: [{ translateY: scanTranslateY }],
                    },
                  ]}
                />
              </View>

              {/* Mint Spinner #66F6CF */}
              <View style={styles.spinnerWrapper}>
                <ActivityIndicator size="large" color="#66F6CF" />
              </View>
            </View>

            {/* Clear, High-Contrast Typography */}
            <Text style={styles.loadingTitle}>{title}</Text>
            <Text style={styles.loadingSubtitle}>{subtitle}</Text>

            {/* Optional dynamic step text badge */}
            {Boolean(stepText && stepText.trim().length > 0) && (
              <View style={styles.stepBadge}>
                <Text style={styles.stepBadgeText}>⚡ {stepText}</Text>
              </View>
            )}

            {/* Micro feature pills footer */}
            <View style={styles.featuresRow}>
              <View style={styles.featurePill}>
                <Text style={styles.featurePillText}>🇪🇪 Эстонский контекст</Text>
              </View>
              <View style={styles.featurePill}>
                <Text style={styles.featurePillText}>💡 Пошаговые подсказки</Text>
              </View>
            </View>
          </View>
        </View>
      </View>
    </Modal>
  );
};

const styles = StyleSheet.create({
  overlayBackdrop: {
    flex: 1,
    backgroundColor: 'rgba(10, 14, 18, 0.88)',
    justifyContent: 'center',
    alignItems: 'center',
    padding: 20,
    zIndex: 9999,
  },
  cardContainer: {
    width: Math.min(SCREEN_WIDTH * 0.88, 340),
    alignItems: 'center',
    justifyContent: 'center',
    position: 'relative',
  },
  glowBox: {
    position: 'absolute',
    top: -10,
    left: -10,
    right: -10,
    bottom: -10,
    borderRadius: 30,
    backgroundColor: 'rgba(102, 246, 207, 0.16)',
    borderWidth: 2,
    borderColor: '#66F6CF',
  },
  modalCard: {
    width: '100%',
    backgroundColor: darkTheme.cardBackground, // #1E252B
    borderRadius: 24,
    borderWidth: 1.5,
    borderColor: darkTheme.cardBorder, // #2C363F
    paddingVertical: 28,
    paddingHorizontal: 22,
    alignItems: 'center',
    ...Theme.shadow.card,
  },
  scannerFrame: {
    width: 90,
    height: 90,
    borderRadius: 22,
    backgroundColor: 'rgba(26, 32, 38, 0.9)',
    borderWidth: 1.5,
    borderColor: '#36434E',
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 20,
    position: 'relative',
    overflow: 'hidden',
  },
  scannerDocument: {
    justifyContent: 'center',
    alignItems: 'center',
    position: 'relative',
    width: '100%',
    height: '100%',
  },
  scannerDocEmoji: {
    fontSize: 34,
  },
  scanLaserLine: {
    position: 'absolute',
    left: 8,
    right: 8,
    height: 2.5,
    backgroundColor: '#66F6CF',
    borderRadius: 2,
    shadowColor: '#66F6CF',
    shadowOffset: { width: 0, height: 0 },
    shadowOpacity: 0.9,
    shadowRadius: 5,
    elevation: 4,
  },
  spinnerWrapper: {
    position: 'absolute',
    bottom: -2,
    right: -2,
    backgroundColor: '#1E252B',
    borderRadius: 14,
    padding: 2,
  },
  loadingTitle: {
    fontSize: 18,
    fontWeight: '800',
    color: darkTheme.textPrimary, // #F8FAFC
    textAlign: 'center',
    letterSpacing: -0.3,
    marginBottom: 6,
  },
  loadingSubtitle: {
    fontSize: 13.5,
    fontWeight: '500',
    color: darkTheme.textSecondary, // #94A3B8
    textAlign: 'center',
    lineHeight: 19,
    paddingHorizontal: 6,
  },
  stepBadge: {
    marginTop: 14,
    backgroundColor: 'rgba(95, 237, 197, 0.12)',
    borderWidth: 1,
    borderColor: 'rgba(95, 237, 197, 0.35)',
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 12,
  },
  stepBadgeText: {
    fontSize: 12,
    fontWeight: '700',
    color: '#5FEDC5',
    textAlign: 'center',
  },
  featuresRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    justifyContent: 'center',
    gap: 8,
    marginTop: 18,
    paddingTop: 16,
    borderTopWidth: 1,
    borderTopColor: 'rgba(44, 54, 63, 0.6)',
    width: '100%',
  },
  featurePill: {
    backgroundColor: '#161C22',
    paddingHorizontal: 9,
    paddingVertical: 4,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#2C363F',
  },
  featurePillText: {
    fontSize: 11,
    fontWeight: '600',
    color: darkTheme.textMuted,
  },
});
