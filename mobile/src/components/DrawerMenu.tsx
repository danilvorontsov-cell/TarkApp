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
import { Theme } from '../theme/colors';

const { width: SCREEN_WIDTH } = Dimensions.get('window');
const DRAWER_WIDTH = Math.min(SCREEN_WIDTH * 0.82, 320);

export type DrawerTabType = 'study' | 'dictionary' | 'translator' | 'tests' | 'reading' | 'settings';

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
        {/* Drawer Header (Solid Onsen #5FEDC5 with rounded bottom-right) */}
        <TouchableOpacity
          style={[styles.drawerHeader, { paddingTop: topPadding + 14 }]}
          onPress={() => {
            onSelectTab('settings');
            onClose();
          }}
          activeOpacity={0.85}
          accessibilityLabel="Профиль ученика"
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

        {/* Thin Divider Line */}
        <View style={styles.divider} />

        {/* Drawer Footer (Settings + Login/Logout) */}
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
              <Text style={[styles.menuItemText, { color: '#DC2626' }]}>Выйти из профиля</Text>
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
            <Text style={styles.versionText}>TarkApp • Nordic Onsen</Text>
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
    backgroundColor: '#FFFFFF',
    borderTopRightRadius: 28,
    borderBottomRightRadius: 28,
    ...Theme.shadow.drawer,
    flexDirection: 'column',
    overflow: 'hidden',
  },
  drawerHeader: {
    backgroundColor: '#5FEDC5',
    paddingHorizontal: 22,
    paddingBottom: 24,
    borderBottomRightRadius: 36,
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
    backgroundColor: '#FFFFFF',
    justifyContent: 'center',
    alignItems: 'center',
    borderWidth: 2,
    borderColor: '#FFFFFF',
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
    paddingVertical: 14,
    paddingHorizontal: 12,
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
    backgroundColor: 'rgba(95, 237, 197, 0.22)',
  },
  menuItemLogin: {
    backgroundColor: '#CFFAEE',
    borderWidth: 1,
    borderColor: '#5FEDC5',
  },
  menuItemLoginText: {
    fontSize: 15,
    fontWeight: '700',
    color: '#064E3B',
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
    color: '#0F172A',
    flex: 1,
  },
  menuItemTextActive: {
    color: '#064E3B',
    fontWeight: '700',
  },
  badgeBox: {
    paddingHorizontal: 10,
    paddingVertical: 3,
    borderRadius: 12,
  },
  badgeSoon: {
    backgroundColor: '#F1F5F9',
  },
  badgeSoonText: {
    fontSize: 12,
    fontWeight: '600',
    color: '#94A3B8',
  },
  badgeCount: {
    backgroundColor: 'rgba(95, 237, 197, 0.4)',
  },
  badgeCountText: {
    fontSize: 12,
    fontWeight: '700',
    color: '#064E3B',
  },
  divider: {
    height: 1,
    backgroundColor: '#E2E8F0',
    marginHorizontal: 18,
    marginVertical: 4,
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
    fontSize: 11,
    color: '#94A3B8',
    fontWeight: '500',
  },
});
