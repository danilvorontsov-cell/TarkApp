/**
 * TarkApp Nordic Clean Theme
 * Centralized design system tokens: Onsen (#5FEDC5) brand accent,
 * matte slate canvas, white modular cards, and high-contrast typography.
 */

export const Theme = {
  colors: {
    // Brand Accent (Nordic Onsen)
    primary: '#5FEDC5',          // Onsen mint: header, badges, accents
    primaryPressed: '#34D399',   // Button pressed state
    onPrimaryText: '#064E3B',    // High-contrast deep pine text over Onsen color (WCAG AAA)
    primaryTint: '#CFFAEE',      // Solid pastel mint highlight

    // Canvas & Cards
    background: '#F1F5F9',       // Soft matte slate canvas background
    surface: '#FFFFFF',          // Clean white card surface
    surfaceAlt: '#F8FAFC',       // Subtle off-white for secondary blocks
    border: '#E2E8F0',           // Fine card borders and divider lines
    borderDark: '#CBD5E1',       // Medium contrast border for inputs/empty slots

    // Typography
    textPrimary: '#0F172A',      // Deep graphite for titles and primary content
    textSecondary: '#64748B',    // Muted slate gray for hints, translations, meta
    textMuted: '#94A3B8',        // Faint gray for timestamps and versions

    // Functional & Interactive
    voiceButton: '#6366F1',      // Indigo/purple for 🔊 speaker audio button
    voiceButtonPressed: '#4F46E5',
    slotSuccessBg: '#CFFAEE',    // Solid 100% opaque pastel Onsen mint (eliminates Android elevation/alpha artifacts)
    slotSuccessBgJunior: '#FEF3C7', // Solid opaque pastel amber for junior
    slotSuccessText: '#065F46',  // Forest green text for solved slots
    slotSuccessBorder: '#34D399',// Solid border for correct answer
    slotErrorBg: '#FEE2E2',      // Coral red tint for wrong slot selection
    slotErrorText: '#991B1B',    // Dark red error text
    slotEmptyBorder: '#CBD5E1',  // Dashed border for unfilled slot
    slotEmptyBg: '#F8FAFC',      // Background for empty slot
    
    // Status & Utility
    badgeBg: '#CFFAEE',
    badgeText: '#064E3B',
    danger: '#EF4444',
    dangerBg: '#FEE2E2',
    overlay: 'rgba(15, 23, 42, 0.45)', // Drawer backdrop shadow
  },
  radius: {
    badge: 8,
    button: 12,
    card: 16,
    chip: 20,
    circle: 9999,
  },
  shadow: {
    card: {
      shadowColor: '#000',
      shadowOffset: { width: 0, height: 2 },
      shadowOpacity: 0.05,
      shadowRadius: 8,
      elevation: 2,
    },
    chip: {
      shadowColor: '#000',
      shadowOffset: { width: 0, height: 1 },
      shadowOpacity: 0.04,
      shadowRadius: 3,
      elevation: 1,
    },
    header: {
      shadowColor: '#064E3B',
      shadowOffset: { width: 0, height: 2 },
      shadowOpacity: 0.08,
      shadowRadius: 6,
      elevation: 3,
    },
    drawer: {
      shadowColor: '#0F172A',
      shadowOffset: { width: 6, height: 0 },
      shadowOpacity: 0.16,
      shadowRadius: 20,
      elevation: 16,
    },
  },
};

export type AppTheme = typeof Theme;
