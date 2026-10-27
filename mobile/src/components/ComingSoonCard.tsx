import React from 'react';
import { StyleSheet, View, Text, TouchableOpacity } from 'react-native';
import { Theme } from '../theme/colors';

interface ComingSoonCardProps {
  icon: string;
  title: string;
  subtitle: string;
  features: Array<{ icon: string; title: string; desc: string }>;
  onBackToStudy: () => void;
}

export const ComingSoonCard: React.FC<ComingSoonCardProps> = ({
  icon,
  title,
  subtitle,
  features,
  onBackToStudy,
}) => {
  return (
    <View style={styles.container}>
      <View style={styles.card}>
        {/* Onsen Mint Badge */}
        <View style={styles.badge}>
          <Text style={styles.badgeText}>В разработке • Скоро в TarkApp</Text>
        </View>

        {/* Feature Icon & Header */}
        <View style={styles.iconCircle}>
          <Text style={styles.icon}>{icon}</Text>
        </View>
        <Text style={styles.title}>{title}</Text>
        <Text style={styles.subtitle}>{subtitle}</Text>

        {/* Feature List */}
        <View style={styles.featureList}>
          {features.map((feat, idx) => (
            <View key={idx} style={styles.featureItem}>
              <View style={styles.featIconBox}>
                <Text style={styles.featIcon}>{feat.icon}</Text>
              </View>
              <View style={styles.featContent}>
                <Text style={styles.featTitle}>{feat.title}</Text>
                <Text style={styles.featDesc}>{feat.desc}</Text>
              </View>
            </View>
          ))}
        </View>

        {/* Back Button */}
        <TouchableOpacity
          style={styles.actionBtn}
          onPress={onBackToStudy}
          activeOpacity={0.8}
        >
          <Text style={styles.actionBtnText}>Вернуться к разбору заданий 📸</Text>
        </TouchableOpacity>
      </View>
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    padding: 16,
    alignItems: 'center',
    justifyContent: 'center',
  },
  card: {
    width: '100%',
    maxWidth: 480,
    backgroundColor: Theme.colors.surface,
    borderRadius: Theme.radius.card,
    padding: 24,
    borderWidth: 1,
    borderColor: Theme.colors.border,
    alignItems: 'center',
    ...Theme.shadow.card,
  },
  badge: {
    backgroundColor: Theme.colors.slotSuccessBg,
    paddingHorizontal: 14,
    paddingVertical: 5,
    borderRadius: Theme.radius.chip,
    marginBottom: 16,
    borderWidth: 1,
    borderColor: Theme.colors.primary,
  },
  badgeText: {
    color: Theme.colors.onPrimaryText,
    fontSize: 12,
    fontWeight: '700',
    letterSpacing: 0.2,
  },
  iconCircle: {
    width: 68,
    height: 68,
    borderRadius: 34,
    backgroundColor: Theme.colors.surfaceAlt,
    borderWidth: 1,
    borderColor: Theme.colors.border,
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 14,
  },
  icon: {
    fontSize: 34,
  },
  title: {
    fontSize: 20,
    fontWeight: '800',
    color: Theme.colors.textPrimary,
    textAlign: 'center',
    marginBottom: 6,
  },
  subtitle: {
    fontSize: 14,
    lineHeight: 20,
    color: Theme.colors.textSecondary,
    textAlign: 'center',
    marginBottom: 20,
    paddingHorizontal: 8,
  },
  featureList: {
    width: '100%',
    marginBottom: 22,
  },
  featureItem: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: Theme.colors.surfaceAlt,
    borderRadius: 12,
    padding: 12,
    marginBottom: 10,
    borderWidth: 1,
    borderColor: Theme.colors.border,
  },
  featIconBox: {
    width: 38,
    height: 38,
    borderRadius: 10,
    backgroundColor: '#FFFFFF',
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 12,
    borderWidth: 1,
    borderColor: Theme.colors.border,
  },
  featIcon: {
    fontSize: 18,
  },
  featContent: {
    flex: 1,
  },
  featTitle: {
    fontSize: 14,
    fontWeight: '700',
    color: Theme.colors.textPrimary,
    marginBottom: 2,
  },
  featDesc: {
    fontSize: 12,
    color: Theme.colors.textSecondary,
    lineHeight: 16,
  },
  actionBtn: {
    backgroundColor: Theme.colors.primary,
    paddingVertical: 13,
    paddingHorizontal: 20,
    borderRadius: Theme.radius.button,
    width: '100%',
    alignItems: 'center',
    ...Theme.shadow.card,
  },
  actionBtnText: {
    color: Theme.colors.onPrimaryText,
    fontSize: 15,
    fontWeight: '700',
  },
});
