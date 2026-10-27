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
  Platform,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Theme } from '../theme/colors';

const { width: SCREEN_WIDTH } = Dimensions.get('window');
const DRAWER_WIDTH = Math.min(SCREEN_WIDTH * 0.8, 320);

export type DrawerTabType = 'study' | 'dictionary' | 'tests' | 'reading' | 'settings';

interface DrawerMenuProps {
  isOpen: boolean;
  onClose: () => void;
  activeTab: DrawerTabType;
  onSelectTab: (tab: DrawerTabType) => void;
  userNickname?: string;
  userGrade?: number;
  vocabCount?: number;
}

interface MenuItemDef {
  id: DrawerTabType;
  icon: string;
  title: string;
  badge?: string;
  isBadgePrimary?: boolean;
}

export const DrawerMenu: React.FC<DrawerMenuProps> = ({
  isOpen,
  onClose,
  activeTab,
  onSelectTab,
  userNickname = 'Ученик',
  userGrade = 3,
  vocabCount = 0,
}) => {
  const insets = useSafeAreaInsets();
  const animProgress = useRef(new Animated.Value(0)).current;

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
      id: 'tests',
      icon: '🎯',
      title: 'Подготовка к контрольным',
      badge: 'Скоро',
      isBadgePrimary: true,
    },
    {
      id: 'reading',
      icon: '⚡',
      title: 'Помощь в чтении',
      badge: 'Скоро',
      isBadgePrimary: true,
    },
  ];

  if (!isOpen && (animProgress as any)._value === 0) {
    return null;
  }

  return (
    <View style={StyleSheet.absoluteFill} pointerEvents={isOpen ? 'auto' : 'none'}>
      {/* Backdrop */}
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

      {/* Drawer Panel */}
      <Animated.View
        style={[
          styles.drawerContainer,
          {
            paddingTop: insets.top,
            paddingBottom: Math.max(insets.bottom, 16),
            transform: [{ translateX }],
          },
        ]}
        {...panResponder.panHandlers}
      >
        {/* Drawer Header (Onsen Mint Theme) */}
        <View style={styles.drawerHeader}>
          <View style={styles.brandRow}>
            <View style={styles.brandIconBox}>
              <Text style={styles.brandIconText}>🇪🇪</Text>
            </View>
            <View style={styles.brandTextCol}>
              <Text style={styles.brandTitle}>TarkApp</Text>
              <Text style={styles.brandTagline}>Твой помощник в эстонской школе</Text>
            </View>
          </View>

          {/* User Profile Pill in Drawer Header */}
          <View style={styles.profilePill}>
            <Text style={styles.profilePillText}>
              👤 {userNickname} • {userGrade} класс
            </Text>
          </View>
        </View>

        {/* Navigation Items */}
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
                      item.isBadgePrimary ? styles.badgePrimary : styles.badgeDefault,
                    ]}
                  >
                    <Text
                      style={[
                        styles.badgeText,
                        item.isBadgePrimary ? styles.badgeTextPrimary : styles.badgeTextDefault,
                      ]}
                    >
                      {item.badge}
                    </Text>
                  </View>
                )}
              </TouchableOpacity>
            );
          })}
        </View>

        {/* Drawer Footer */}
        <View style={styles.drawerFooter}>
          <TouchableOpacity
            style={[styles.footerItem, activeTab === 'settings' && styles.menuItemActive]}
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
              Настройки
            </Text>
          </TouchableOpacity>

          <View style={styles.versionContainer}>
            <Text style={styles.versionText}>v1.0.0-beta • Nordic Clean</Text>
          </View>
        </View>
      </Animated.View>
    </View>
  );
};

const styles = StyleSheet.create({
  backdrop: {
    ...StyleSheet.absoluteFill,
    backgroundColor: Theme.colors.overlay,
  },
  drawerContainer: {
    position: 'absolute',
    top: 0,
    bottom: 0,
    left: 0,
    width: DRAWER_WIDTH,
    backgroundColor: Theme.colors.surface,
    ...Theme.shadow.drawer,
    flexDirection: 'column',
    justifyContent: 'space-between',
  },
  drawerHeader: {
    backgroundColor: Theme.colors.primary,
    paddingHorizontal: 20,
    paddingTop: 16,
    paddingBottom: 20,
    borderBottomWidth: 1,
    borderBottomColor: 'rgba(6, 78, 59, 0.12)',
  },
  brandRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 14,
  },
  brandIconBox: {
    width: 44,
    height: 44,
    borderRadius: 12,
    backgroundColor: '#FFFFFF',
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 12,
    ...Theme.shadow.card,
  },
  brandIconText: {
    fontSize: 22,
  },
  brandTextCol: {
    flex: 1,
  },
  brandTitle: {
    fontSize: 22,
    fontWeight: '800',
    color: Theme.colors.onPrimaryText,
    letterSpacing: -0.3,
  },
  brandTagline: {
    fontSize: 12,
    color: Theme.colors.onPrimaryText,
    opacity: 0.85,
    marginTop: 2,
    fontWeight: '500',
  },
  profilePill: {
    backgroundColor: 'rgba(255, 255, 255, 0.75)',
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: Theme.radius.chip,
    alignSelf: 'flex-start',
    borderWidth: 1,
    borderColor: 'rgba(6, 78, 59, 0.15)',
  },
  profilePillText: {
    fontSize: 12.5,
    fontWeight: '700',
    color: Theme.colors.onPrimaryText,
  },
  menuList: {
    flex: 1,
    paddingVertical: 12,
  },
  menuItem: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 14,
    paddingHorizontal: 18,
    borderLeftWidth: 4,
    borderLeftColor: 'transparent',
  },
  menuItemActive: {
    backgroundColor: Theme.colors.slotSuccessBg,
    borderLeftWidth: 4,
    borderLeftColor: Theme.colors.primary,
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
    color: Theme.colors.textPrimary,
    flex: 1,
  },
  menuItemTextActive: {
    color: Theme.colors.onPrimaryText,
    fontWeight: '800',
  },
  badgeBox: {
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: Theme.radius.badge,
  },
  badgePrimary: {
    backgroundColor: Theme.colors.primary,
  },
  badgeDefault: {
    backgroundColor: Theme.colors.border,
  },
  badgeText: {
    fontSize: 11,
    fontWeight: '700',
  },
  badgeTextPrimary: {
    color: Theme.colors.onPrimaryText,
  },
  badgeTextDefault: {
    color: Theme.colors.textSecondary,
  },
  drawerFooter: {
    borderTopWidth: 1,
    borderTopColor: Theme.colors.border,
    paddingTop: 8,
  },
  footerItem: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 12,
    paddingHorizontal: 18,
    borderLeftWidth: 4,
    borderLeftColor: 'transparent',
  },
  versionContainer: {
    paddingHorizontal: 20,
    paddingTop: 10,
    paddingBottom: 4,
  },
  versionText: {
    fontSize: 11,
    color: Theme.colors.textMuted,
    fontWeight: '500',
  },
});
