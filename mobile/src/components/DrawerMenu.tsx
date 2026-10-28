import React, { useEffect, useRef } from 'react';
import {
  StyleSheet,
  View,
  Text,
  TouchableOpacity,
  Animated,
  Dimensions,
  TouchableWithoutFeedback,
  PanResponder,
  Image,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { LinearGradient } from 'expo-linear-gradient';
import { Theme, darkTheme } from '../theme/colors';

const { width: SCREEN_WIDTH } = Dimensions.get('window');
const DRAWER_WIDTH = Math.min(SCREEN_WIDTH * 0.82, 320);

export type DrawerTabType = 'study' | 'dictionary' | 'translator' | 'tests' | 'reading' | 'settings' | 'feedback';

interface DrawerMenuProps {
  isOpen: boolean;
  onClose: () => void;
  activeTab: DrawerTabType;
  onSelectTab: (tab: DrawerTabType) => void;
  userNickname?: string;
  userGrade?: number;
  avatarUri?: string;
  onChangeAvatar?: () => void;
  vocabCount?: number;
  onLogout?: () => void;
  onOpenPaywall?: () => void;
  hasPro?: boolean;
}

interface MenuItemDef {
  id: DrawerTabType;
  icon: string;
  title: string;
  badge?: string;
}

export const DrawerMenu: React.FC<DrawerMenuProps> = ({
  isOpen,
  onClose,
  activeTab,
  onSelectTab,
  userNickname = '',
  userGrade = 3,
  avatarUri,
  onChangeAvatar,
  vocabCount = 0,
  onLogout,
  onOpenPaywall,
  hasPro = false,
}) => {
  const insets = useSafeAreaInsets();
  const animProgress = useRef(new Animated.Value(0)).current;
  const hasUser = Boolean(userNickname && userNickname.trim().length > 0);
  const displayName = hasUser ? userNickname.trim() : '';

  useEffect(() => {
    Animated.timing(animProgress, {
      toValue: isOpen ? 1 : 0,
      duration: 250,
      useNativeDriver: true,
    }).start();
  }, [isOpen]);

  const panResponder = useRef(
    PanResponder.create({
      onMoveShouldSetPanResponder: (_, gestureState) => {
        return Math.abs(gestureState.dx) > 10;
      },
      onPanResponderRelease: (_, gestureState) => {
        if (gestureState.dx < -50 || gestureState.vx < -0.5) {
          onClose();
        }
      },
    })
  ).current;

  const translateX = animProgress.interpolate({
    inputRange: [0, 1],
    outputRange: [-DRAWER_WIDTH - 20, 0],
  });

  const backdropOpacity = animProgress.interpolate({
    inputRange: [0, 1],
    outputRange: [0, 1],
  });

  const menuItems: MenuItemDef[] = [
    {
      id: 'study',
      icon: '📸',
      title: 'Разбор заданий',
    },
    {
      id: 'dictionary',
      icon: '📖',
      title: 'Мой словарик',
      badge: vocabCount > 0 ? String(vocabCount) : undefined,
    },
    {
      id: 'translator',
      icon: '🌐',
      title: 'Быстрый переводчик',
    },
    // Пункты «Подготовка к контрольным» и «Помощь в чтении» сохранены в коде без визуального отображения:
    // {
    //   id: 'tests',
    //   icon: '🎯',
    //   title: 'Подготовка к контрольным',
    //   badge: 'Скоро',
    // },
    // {
    //   id: 'reading',
    //   icon: '⚡',
    //   title: 'Помощь в чтении',
    //   badge: 'Скоро',
    // },
  ];

  if (!isOpen && (animProgress as any)._value === 0) {
    return null;
  }

  const topPadding = Math.max(insets.top, 20);
  const bottomPadding = Math.max(insets.bottom, 16);

  return (
    <View style={StyleSheet.absoluteFill} pointerEvents={isOpen ? 'auto' : 'none'}>
      {/* Dimmed Backdrop */}
      <TouchableWithoutFeedback onPress={onClose}>
        <Animated.View
          style={[
            styles.backdrop,
            {
              opacity: backdropOpacity,
            },
          ]}
        />
      </TouchableWithoutFeedback>

      {/* Smooth Sliding Drawer Panel */}
      <Animated.View
        style={[
          styles.drawerContainer,
          {
            paddingBottom: bottomPadding,
            transform: [{ translateX }],
          },
        ]}
        {...panResponder.panHandlers}
      >
        {/* Drawer Header (Vertical Gradient ['#66F6CF', '#42DCA3'] with rounded bottom corners) */}
        <TouchableOpacity
          onPress={() => {
            onSelectTab('settings');
            onClose();
          }}
          activeOpacity={0.85}
          accessibilityLabel="Профиль ученика"
        >
          <LinearGradient
            colors={['#66F6CF', '#42DCA3']}
            start={{ x: 0, y: 0 }}
            end={{ x: 0, y: 1 }}
            style={[styles.drawerHeader, { paddingTop: topPadding + 14 }]}
          >
            {/* Avatar (Interactive: Tap to take photo or choose from gallery) */}
            <TouchableOpacity
              style={styles.avatarButton}
              onPress={onChangeAvatar}
              activeOpacity={0.8}
              accessibilityLabel="Изменить аватарку"
              accessibilityRole="button"
            >
              <View style={styles.avatarCircle}>
                {avatarUri ? (
                  <Image source={{ uri: avatarUri }} style={styles.avatarImage} />
                ) : (
                  <Text style={styles.avatarEmoji}>{hasUser ? '🧑‍🎓' : '👤'}</Text>
                )}
              </View>
              <View style={styles.avatarEditBadge}>
                <Text style={styles.avatarEditBadgeIcon}>📷</Text>
              </View>
            </TouchableOpacity>

            {/* User Nickname & Grade */}
            <Text style={styles.headerSubtitle}>
              {hasUser ? `${displayName} • ${userGrade} кл.` : 'Гость • Вход не выполнен'}
            </Text>

            {/* Greeting Title */}
            <Text style={styles.headerGreeting}>
              {hasUser ? `Привет, ${displayName}!` : 'Нажмите, чтобы войти'}
            </Text>
          </LinearGradient>
        </TouchableOpacity>

        {/* Navigation Sections */}
        <View style={styles.menuList}>
          {menuItems.map((item) => {
            const isActive = activeTab === item.id;
            return (
              <TouchableOpacity
                key={item.id}
                style={[styles.menuItem, isActive && styles.menuItemActive]}
                onPress={() => {
                  onSelectTab(item.id);
                  onClose();
                }}
                activeOpacity={0.7}
              >
                <Text style={styles.menuItemIcon}>{item.icon}</Text>
                <Text style={[styles.menuItemText, isActive && styles.menuItemTextActive]}>
                  {item.title}
                </Text>

                {item.badge && (
                  <View
                    style={[
                      styles.badgeBox,
                      item.badge === 'Скоро' ? styles.badgeSoon : styles.badgeCount,
                    ]}
                  >
                    <Text
                      style={
                        item.badge === 'Скоро' ? styles.badgeSoonText : styles.badgeCountText
                      }
                    >
                      {item.badge}
                    </Text>
                  </View>
                )}
              </TouchableOpacity>
            );
          })}
        </View>

        {/* PRO Subscription Banner */}
        <TouchableOpacity
          style={styles.proDrawerCard}
          onPress={() => {
            onClose();
            if (onOpenPaywall) onOpenPaywall();
          }}
          activeOpacity={0.8}
        >
          <Text style={styles.proDrawerIcon}>{hasPro ? '👑' : '💎'}</Text>
          <View style={{ flex: 1 }}>
            <Text style={styles.proDrawerTitle}>
              {hasPro ? 'Подписка активна' : 'Тарифы TarkApp PRO'}
            </Text>
            <Text style={styles.proDrawerSub}>
              {hasPro ? 'Безлимитный доступ' : 'От 8.88 € / месяц'}
            </Text>
          </View>
          {hasPro ? (
            <View style={[styles.proDrawerBadge, styles.proDrawerBadgeActive]}>
              <Text style={[styles.proDrawerBadgeText, styles.proDrawerBadgeTextActive]}>PRO</Text>
            </View>
          ) : (
            <LinearGradient
              colors={['#66F6CF', '#42DCA3']}
              start={{ x: 0, y: 0 }}
              end={{ x: 0, y: 1 }}
              style={styles.proDrawerBadge}
            >
              <Text style={styles.proDrawerBadgeText}>Выбрать</Text>
            </LinearGradient>
          )}
        </TouchableOpacity>

        {/* Thin Divider Line */}
        <View style={styles.divider} />

        {/* Drawer Footer (Settings + Feedback + Login/Logout) */}
        <View style={styles.drawerFooter}>
          {/* Settings & Profile Item */}
          <TouchableOpacity
            style={[styles.menuItem, activeTab === 'settings' && styles.menuItemActive]}
            onPress={() => {
              onSelectTab('settings');
              onClose();
            }}
            activeOpacity={0.7}
          >
            <Text style={styles.menuItemIcon}>⚙️</Text>
            <Text
              style={[
                styles.menuItemText,
                activeTab === 'settings' && styles.menuItemTextActive,
              ]}
            >
              Профиль и настройки
            </Text>
          </TouchableOpacity>

          {/* Feedback Item */}
          <TouchableOpacity
            style={[styles.menuItem, activeTab === 'feedback' && styles.menuItemActive]}
            onPress={() => {
              onSelectTab('feedback');
              onClose();
            }}
            activeOpacity={0.7}
          >
            <Text style={styles.menuItemIcon}>💬</Text>
            <Text
              style={[
                styles.menuItemText,
                activeTab === 'feedback' && styles.menuItemTextActive,
              ]}
            >
              Связь с разработчиком
            </Text>
          </TouchableOpacity>

          {/* Dynamic Login / Logout Item */}
          {hasUser ? (
            <TouchableOpacity
              style={styles.menuItem}
              onPress={() => {
                onClose();
                if (onLogout) {
                  onLogout();
                }
              }}
              activeOpacity={0.7}
            >
              <Text style={styles.menuItemIcon}>🚪</Text>
              <Text style={[styles.menuItemText, { color: '#EF4444' }]}>Выйти из профиля</Text>
            </TouchableOpacity>
          ) : (
            <TouchableOpacity
              style={[styles.menuItem, styles.menuItemLogin]}
              onPress={() => {
                onClose();
                onSelectTab('settings');
              }}
              activeOpacity={0.7}
            >
              <Text style={styles.menuItemIcon}>🔑</Text>
              <Text style={styles.menuItemLoginText}>Войти / Задать имя</Text>
            </TouchableOpacity>
          )}

          <View style={styles.versionContainer}>
            <Text style={styles.versionText}>TarkApp • v1.0.0 • Tark Systems</Text>
          </View>
        </View>
      </Animated.View>
    </View>
  );
};

const styles = StyleSheet.create({
  backdrop: {
    ...StyleSheet.absoluteFill,
    backgroundColor: 'rgba(15, 23, 42, 0.45)',
  },
  drawerContainer: {
    position: 'absolute',
    top: 0,
    bottom: 0,
    left: 0,
    width: DRAWER_WIDTH,
    backgroundColor: darkTheme.cardBackground,
    borderTopRightRadius: 28,
    borderBottomRightRadius: 28,
    borderRightWidth: 1,
    borderRightColor: darkTheme.cardBorder,
    ...Theme.shadow.drawer,
    flexDirection: 'column',
    overflow: 'hidden',
  },
  drawerHeader: {
    paddingHorizontal: 22,
    paddingBottom: 34,
    borderBottomLeftRadius: 0,
    borderBottomRightRadius: 0,
  },
  avatarButton: {
    alignSelf: 'flex-start',
    position: 'relative',
    marginBottom: 8,
  },
  avatarCircle: {
    width: 58,
    height: 58,
    borderRadius: 29,
    backgroundColor: darkTheme.cardBackground,
    justifyContent: 'center',
    alignItems: 'center',
    borderWidth: 2,
    borderColor: darkTheme.cardBorder,
    overflow: 'hidden',
    ...Theme.shadow.chip,
  },
  avatarImage: {
    width: '100%',
    height: '100%',
    borderRadius: 29,
  },
  avatarEmoji: {
    fontSize: 28,
  },
  avatarEditBadge: {
    position: 'absolute',
    bottom: -2,
    right: -2,
    width: 22,
    height: 22,
    borderRadius: 11,
    backgroundColor: '#064E3B',
    borderWidth: 1.5,
    borderColor: '#FFFFFF',
    justifyContent: 'center',
    alignItems: 'center',
  },
  avatarEditBadgeIcon: {
    fontSize: 10,
    color: '#FFFFFF',
  },
  headerSubtitle: {
    fontSize: 14,
    fontWeight: '600',
    color: '#064E3B',
    marginTop: 4,
  },
  headerGreeting: {
    fontSize: 24,
    fontWeight: '800',
    color: '#064E3B',
    letterSpacing: -0.3,
    marginTop: 2,
  },
  menuList: {
    flex: 1,
    marginTop: -18,
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
    backgroundColor: darkTheme.cardBackground,
    paddingTop: 16,
    paddingBottom: 14,
    paddingHorizontal: 12,
    zIndex: 2,
    elevation: 3,
  },
  menuItem: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 12,
    paddingHorizontal: 14,
    borderRadius: 14,
    marginBottom: 4,
  },
  menuItemActive: {
    backgroundColor: 'rgba(95, 237, 197, 0.16)',
  },
  menuItemLogin: {
    backgroundColor: darkTheme.badgeFreeBg,
    borderWidth: 1,
    borderColor: darkTheme.accent,
  },
  menuItemLoginText: {
    fontSize: 15,
    fontWeight: '700',
    color: darkTheme.badgeFreeText,
    flex: 1,
  },
  menuItemIcon: {
    fontSize: 20,
    marginRight: 14,
    width: 26,
    textAlign: 'center',
  },
  menuItemText: {
    fontSize: 15,
    fontWeight: '600',
    color: darkTheme.textPrimary,
    flex: 1,
  },
  menuItemTextActive: {
    color: darkTheme.accent,
    fontWeight: '700',
  },
  badgeBox: {
    paddingHorizontal: 10,
    paddingVertical: 3,
    borderRadius: 12,
  },
  badgeSoon: {
    backgroundColor: darkTheme.badgeFreeBg,
  },
  badgeSoonText: {
    fontSize: 12,
    fontWeight: '600',
    color: darkTheme.textMuted,
  },
  badgeCount: {
    backgroundColor: 'rgba(95, 237, 197, 0.25)',
  },
  badgeCountText: {
    fontSize: 12,
    fontWeight: '700',
    color: darkTheme.badgeFreeText,
  },
  divider: {
    height: 1,
    backgroundColor: darkTheme.cardBorder,
    marginHorizontal: 18,
    marginVertical: 4,
  },
  proDrawerCard: {
    flexDirection: 'row',
    alignItems: 'center',
    marginHorizontal: 12,
    marginBottom: 6,
    padding: 12,
    borderRadius: 16,
    backgroundColor: '#1E292F',
    borderWidth: 1,
    borderColor: darkTheme.accent,
  },
  proDrawerIcon: {
    fontSize: 22,
    marginRight: 10,
  },
  proDrawerTitle: {
    fontSize: 14,
    fontWeight: '800',
    color: darkTheme.textPrimary,
  },
  proDrawerSub: {
    fontSize: 11.5,
    color: darkTheme.textSecondary,
    marginTop: 1,
  },
  proDrawerBadge: {
    backgroundColor: darkTheme.accent,
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 10,
  },
  proDrawerBadgeActive: {
    backgroundColor: 'rgba(95, 237, 197, 0.2)',
  },
  proDrawerBadgeText: {
    color: darkTheme.accentText,
    fontSize: 11,
    fontWeight: '800',
  },
  proDrawerBadgeTextActive: {
    color: darkTheme.accent,
  },
  drawerFooter: {
    paddingHorizontal: 12,
    paddingTop: 8,
  },
  versionContainer: {
    paddingHorizontal: 14,
    paddingTop: 10,
    paddingBottom: 2,
  },
  versionText: {
    fontSize: 12,
    color: darkTheme.textMuted,
    fontWeight: '500',
  },
});
