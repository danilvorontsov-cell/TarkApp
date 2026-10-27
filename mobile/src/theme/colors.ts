/**
 * TarkApp Slate Anthracite Dark Theme
 * Deep anthracite (#12161A) canvas with contrasting graphite cards (#1E252B),
 * crisp borders (#2C363F), high-contrast text (#F8FAFC, #94A3B8),
 * and Nordic Onsen (#5FEDC5) brand accents.
 */

export const darkTheme = {
  // Фоны
  background: '#12161A',        // Глубокий антрацит (Slate Black) — общий фон всех экранов
  cardBackground: '#1E252B',    // Темно-серый графит для карточек, полей ввода и окошек
  cardBorder: '#2C363F',        // Границы карточек (border: 1px) для четкого контура

  // Акценты
  accent: '#5FEDC5',            // Onsen Green — кнопки, тумблеры, активные табы
  accentText: '#064E3B',        // Темный хвойный цвет текста внутри зеленых кнопок

  // Типографика
  textPrimary: '#F8FAFC',       // Основной текст, заголовки
  textSecondary: '#94A3B8',     // Пояснения, даты, второстепенные подсказки
  textMuted: '#64748B',         // Плейсхолдеры в полях ввода

  // Статусы
  badgeFreeBg: '#2A343D',       // Подложка бейджа бесплатных попыток
  badgeFreeText: '#5FEDC5',     // Текст счетчика попыток
};

export const Theme = {
  colors: {
    // Brand Accent (Nordic Onsen)
    primary: darkTheme.accent,             // #5FEDC5 Onsen mint
    primaryPressed: '#34D399',             // Button pressed state
    onPrimaryText: darkTheme.accentText,   // #064E3B High-contrast deep pine text over Onsen green (WCAG AAA)
    primaryTint: 'rgba(95, 237, 197, 0.16)', // Subtle mint highlight on dark graphite

    // Canvas & Cards (Slate Anthracite)
    background: darkTheme.background,      // #12161A Deep slate black canvas background
    surface: darkTheme.cardBackground,     // #1E252B Dark graphite card surface
    surfaceAlt: '#181E24',                 // Secondary deep slate for nested blocks & inputs
    border: darkTheme.cardBorder,          // #2C363F Fine card borders (1px)
    borderDark: '#36434E',                 // Medium contrast border for focused inputs

    // Typography
    textPrimary: darkTheme.textPrimary,    // #F8FAFC Crisp white-slate for titles and primary content
    textSecondary: darkTheme.textSecondary,// #94A3B8 Muted slate gray for hints, translations, meta
    textMuted: darkTheme.textMuted,        // #64748B Faint gray for placeholders, timestamps and versions

    // Functional & Interactive
    voiceButton: '#6366F1',                // Indigo/purple for 🔊 speaker audio button
    voiceButtonPressed: '#4F46E5',
    slotSuccessBg: '#18382E',              // Dark mint tint for solved slot
    slotSuccessBgJunior: '#2F2618',        // Amber tint for junior
    slotSuccessText: '#5FEDC5',            // Bright Onsen mint text for solved slots
    slotSuccessBorder: '#34D399',          // Solid border for correct answer
    slotErrorBg: '#3F1E24',                // Deep coral/red tint for wrong slot selection
    slotErrorText: '#FCA5A5',              // Pastel red error text
    slotEmptyBorder: darkTheme.cardBorder, // #2C363F Dashed border for unfilled slot
    slotEmptyBg: '#181E24',                // Background for empty slot

    // Status & Utility
    badgeBg: darkTheme.badgeFreeBg,        // #2A343D
    badgeText: darkTheme.badgeFreeText,    // #5FEDC5
    badgeFreeBg: darkTheme.badgeFreeBg,    // #2A343D
    badgeFreeText: darkTheme.badgeFreeText,// #5FEDC5
    danger: '#EF4444',
    dangerBg: '#3B181C',
    overlay: 'rgba(0, 0, 0, 0.72)',        // Modal & drawer backdrop shadow
    drawerPillBg: 'rgba(95, 237, 197, 0.16)',
  },
  radius: {
    badge: 8,
    button: 14,
    card: 20,
    chip: 20,
    circle: 9999,
  },
  shadow: {
    card: {
      shadowColor: '#000',
      shadowOffset: { width: 0, height: 2 },
      shadowOpacity: 0.35,
      shadowRadius: 8,
      elevation: 3,
    },
    chip: {
      shadowColor: '#000',
      shadowOffset: { width: 0, height: 1 },
      shadowOpacity: 0.25,
      shadowRadius: 3,
      elevation: 2,
    },
    header: {
      shadowColor: '#000',
      shadowOffset: { width: 0, height: 2 },
      shadowOpacity: 0.25,
      shadowRadius: 6,
      elevation: 4,
    },
    drawer: {
      shadowColor: '#000',
      shadowOffset: { width: 6, height: 0 },
      shadowOpacity: 0.45,
      shadowRadius: 24,
      elevation: 16,
    },
    modal: {
      shadowColor: '#000',
      shadowOffset: { width: 0, height: 10 },
      shadowOpacity: 0.5,
      shadowRadius: 24,
      elevation: 12,
    },
    button: {
      shadowColor: '#000',
      shadowOffset: { width: 0, height: 2 },
      shadowOpacity: 0.25,
      shadowRadius: 4,
      elevation: 2,
    },
  },
};

export type AppTheme = typeof Theme;
