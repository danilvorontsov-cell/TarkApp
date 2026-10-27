import React, { useState } from 'react';
import {
  StyleSheet,
  View,
  Text,
  TouchableOpacity,
  ScrollView,
  Modal,
  Alert,
  TextInput,
  ActivityIndicator,
  Platform,
} from 'react-native';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';
import { StatusBar } from 'expo-status-bar';
import * as Clipboard from 'expo-clipboard';
import { darkTheme, Theme } from '../theme/colors';
import { getDeviceId, sendFeedback } from '../services/api';

export type SubscriptionPlan = 'year' | 'semester' | 'month';

interface PaywallScreenProps {
  visible: boolean;
  onClose: () => void;
  onOpenKeyActivation: () => void;
  canClose?: boolean;
}

export const PaywallScreen: React.FC<PaywallScreenProps> = ({
  visible,
  onClose,
  onOpenKeyActivation,
  canClose = true,
}) => {
  const insets = useSafeAreaInsets();
  const [selectedPlan, setSelectedPlan] = useState<SubscriptionPlan>('year');
  const [isInvoiceModalVisible, setIsInvoiceModalVisible] = useState(false);
  const [emailInput, setEmailInput] = useState('');
  const [isSendingInvoice, setIsSendingInvoice] = useState(false);
  const [copiedField, setCopiedField] = useState<string | null>(null);

  const ibanAccount = 'EE129900001234567890';
  const recipientName = 'TarkApp OÜ (Reg: 16987456)';
  const swiftBic = 'LHVBEE22';

  const copyToClipboard = async (text: string, label: string) => {
    try {
      await Clipboard.setStringAsync(text);
      setCopiedField(label);
      setTimeout(() => setCopiedField(null), 2000);
    } catch {
      Alert.alert('Скопировано', text);
    }
  };

  const handleCtaPress = () => {
    // Открываем модальное окно выбора способа оплаты / реквизитов IBAN
    setIsInvoiceModalVisible(true);
  };

  const handleSendInvoiceRequest = async () => {
    const trimmedEmail = emailInput.trim();
    if (!trimmedEmail || !trimmedEmail.includes('@')) {
      Alert.alert('Некорректный e-mail', 'Пожалуйста, укажите верный адрес электронной почты для отправки счёта.');
      return;
    }

    setIsSendingInvoice(true);
    try {
      const deviceId = await getDeviceId();
      const planName =
        selectedPlan === 'year'
          ? 'Учебный год (9 мес) — 79.90 €'
          : selectedPlan === 'semester'
          ? 'Полгода (Семестр, 4.5 мес) — 44.90 €'
          : '1 месяц — 9.99 €';

      const planLabel =
        selectedPlan === 'year'
          ? 'Полный учебный год'
          : selectedPlan === 'semester'
          ? 'Полгода (Семестр)'
          : '1 месяц';

      await sendFeedback({
        category: 'feature',
        message: `📄 ЗАПРОС СЧЁТА НА ПОДПИСКУ PRO\nТариф: ${planName}\nEmail: ${trimmedEmail}\nDevice ID: ${deviceId}\nКлиент ожидает счёт (e-arve / PDF) для оплаты в эстонском банке.`,
        contact: trimmedEmail,
        client_time: new Date().toISOString(),
      });

      Alert.alert(
        'Заявка принята!',
        `Счёт на тариф «${planLabel}» будет отправлен на ${trimmedEmail} в течение 15 минут. Вы также можете оплатить прямо сейчас по реквизитам IBAN.`,
        [
          {
            text: 'Понятно',
            onPress: () => {
              setEmailInput('');
              setIsInvoiceModalVisible(false);
            },
          },
        ]
      );
    } catch (err: any) {
      Alert.alert(
        'Ошибка отправки',
        'Не удалось отправить заявку автоматически. Пожалуйста, напишите нам на support@tarkapp.ee или используйте реквизиты ниже.'
      );
    } finally {
      setIsSendingInvoice(false);
    }
  };

  return (
    <Modal
      visible={visible}
      animationType="slide"
      presentationStyle="fullScreen"
      onRequestClose={() => {
        if (canClose) onClose();
      }}
    >
      <SafeAreaView style={styles.safeArea} edges={['top', 'bottom', 'left', 'right']}>
        <StatusBar style="light" />

        {/* Header Action Bar */}
        <View style={styles.topBar}>
          <View style={styles.topBarSpacer} />
          {canClose && (
            <TouchableOpacity
              style={styles.closeButton}
              onPress={onClose}
              activeOpacity={0.7}
              accessibilityLabel="Закрыть экран тарифов"
              accessibilityRole="button"
            >
              <Text style={styles.closeButtonText}>✕</Text>
            </TouchableOpacity>
          )}
        </View>

        <ScrollView
          style={styles.scrollView}
          contentContainerStyle={[
            styles.scrollContent,
            { paddingBottom: Math.max(insets.bottom, 24) + 24 },
          ]}
          showsVerticalScrollIndicator={false}
        >
          {/* Section A: Header */}
          <View style={styles.headerSection}>
            <View style={styles.badgeIconCircle}>
              <Text style={styles.badgeIconEmoji}>🎓</Text>
            </View>

            <Text style={styles.headlineTitle}>Учитесь без стресса и репетиторов</Text>

            <Text style={styles.headlineSubtitle}>
              Объясняем задания на понятном русском языке, переводим школьные термины и учим ребёнка справляться с уроками без помощи родителей.
            </Text>
          </View>

          {/* Section B: Pricing Cards Radio Group (3 Tiers) */}
          <View style={styles.plansContainer}>
            {/* Plan 1: Full School Year (9 months) - Recommended */}
            <TouchableOpacity
              style={[
                styles.planCard,
                selectedPlan === 'year' && styles.planCardActive,
              ]}
              onPress={() => setSelectedPlan('year')}
              activeOpacity={0.88}
              accessibilityRole="radio"
              accessibilityState={{ checked: selectedPlan === 'year' }}
            >
              <View style={styles.discountBadge}>
                <Text style={styles.discountBadgeText}>ВЫГОДНО • 1 МЕСЯЦ В ПОДАРОК</Text>
              </View>

              <View style={styles.planCardHeaderRow}>
                <View style={styles.planRadioOuter}>
                  {selectedPlan === 'year' && <View style={styles.planRadioInner} />}
                </View>

                <View style={styles.planTitleBox}>
                  <Text style={styles.planName}>Полный учебный год</Text>
                  <Text style={styles.planDescription}>Сентябрь — Май (все 9 учебных месяцев)</Text>
                </View>
              </View>

              <View style={styles.planPriceRow}>
                <Text style={styles.planPriceBig}>79.90 €</Text>
                <Text style={styles.planPriceSubtext}>
                  ~8.88 € / месяц (разовый платёж на весь учебный год)
                </Text>
              </View>
            </TouchableOpacity>

            {/* Plan 2: Semester / Half-year (4.5 months) */}
            <TouchableOpacity
              style={[
                styles.planCard,
                selectedPlan === 'semester' && styles.planCardActive,
              ]}
              onPress={() => setSelectedPlan('semester')}
              activeOpacity={0.88}
              accessibilityRole="radio"
              accessibilityState={{ checked: selectedPlan === 'semester' }}
            >
              <View style={styles.planCardHeaderRow}>
                <View style={styles.planRadioOuter}>
                  {selectedPlan === 'semester' && <View style={styles.planRadioInner} />}
                </View>

                <View style={styles.planTitleBox}>
                  <Text style={styles.planName}>Полгода (Семестр)</Text>
                  <Text style={styles.planDescription}>Уверенная учёба на два учебных периода</Text>
                </View>
              </View>

              <View style={styles.planPriceRow}>
                <Text style={styles.planPriceBig}>44.90 €</Text>
                <Text style={styles.planPriceSubtext}>
                  ~9.97 € / месяц (разовая оплата)
                </Text>
              </View>
            </TouchableOpacity>

            {/* Plan 3: 1 Month Flexible */}
            <TouchableOpacity
              style={[
                styles.planCard,
                selectedPlan === 'month' && styles.planCardActive,
              ]}
              onPress={() => setSelectedPlan('month')}
              activeOpacity={0.88}
              accessibilityRole="radio"
              accessibilityState={{ checked: selectedPlan === 'month' }}
            >
              <View style={styles.planCardHeaderRow}>
                <View style={styles.planRadioOuter}>
                  {selectedPlan === 'month' && <View style={styles.planRadioInner} />}
                </View>

                <View style={styles.planTitleBox}>
                  <Text style={styles.planName}>1 месяц</Text>
                  <Text style={styles.planDescription}>Для подготовки к четверти или разовой помощи</Text>
                </View>
              </View>

              <View style={styles.planPriceRow}>
                <Text style={styles.planPriceMedium}>9.99 € / мес</Text>
                <Text style={styles.planPriceSubtext}>Продление каждый месяц, отмена в любой момент</Text>
              </View>
            </TouchableOpacity>
          </View>

          {/* Section C: Key PRO Features Bullet Block */}
          <View style={styles.featuresCard}>
            <View style={styles.featureItem}>
              <View style={styles.featureCheckCircle}>
                <Text style={styles.featureCheckIcon}>✔</Text>
              </View>
              <Text style={styles.featureItemText}>
                <Text style={styles.featureItemBold}>Безлимитный умный разбор</Text> любых предметов
                (Loodusõpetus, Matemaatika, Ajalugu и др.).
              </Text>
            </View>

            <View style={styles.featureItem}>
              <View style={styles.featureCheckCircle}>
                <Text style={styles.featureCheckIcon}>✔</Text>
              </View>
              <Text style={styles.featureItemText}>
                <Text style={styles.featureItemBold}>Пошаговые подсказки</Text> вместо списывания — ребенок
                действительно понимает суть.
              </Text>
            </View>

            <View style={styles.featureItem}>
              <View style={styles.featureCheckCircle}>
                <Text style={styles.featureCheckIcon}>✔</Text>
              </View>
              <Text style={styles.featureItemText}>
                <Text style={styles.featureItemBold}>Озвучка эстонских терминов</Text> с правильным акцентом
                и контекстным словариком.
              </Text>
            </View>
          </View>

          {/* Section D: CTA Button */}
          <View style={styles.ctaContainer}>
            <TouchableOpacity
              style={styles.ctaButton}
              onPress={handleCtaPress}
              activeOpacity={0.85}
              accessibilityRole="button"
            >
              <Text style={styles.ctaButtonText}>
                {selectedPlan === 'year'
                  ? 'Оформить учебный год — 79.90 €'
                  : selectedPlan === 'semester'
                  ? 'Оформить на полгода — 44.90 €'
                  : 'Попробовать 1 месяц — 9.99 €'}
              </Text>
            </TouchableOpacity>

            <Text style={styles.ctaGuaranteeText}>
              Безопасная оплата. Никаких скрытых списаний во время летних каникул
            </Text>
          </View>

          {/* Section E: Footer (Promo code / School invoice) */}
          <View style={styles.footerSection}>
            <View style={styles.footerDivider} />

            <TouchableOpacity
              style={styles.keyActivationLinkBox}
              onPress={() => {
                onClose();
                onOpenKeyActivation();
              }}
              activeOpacity={0.7}
            >
              <Text style={styles.keyActivationPrompt}>
                Есть ключ доступа или счёт для школы/фирмы?{' '}
                <Text style={styles.keyActivationLink}>[Активировать]</Text>
              </Text>
            </TouchableOpacity>
          </View>
        </ScrollView>

        {/* Modal: Payment Options & IBAN Invoice Details */}
        <Modal
          visible={isInvoiceModalVisible}
          transparent
          animationType="fade"
          onRequestClose={() => setIsInvoiceModalVisible(false)}
        >
          <View style={styles.invoiceModalOverlay}>
            <View style={styles.invoiceModalCard}>
              <View style={styles.invoiceModalHeader}>
                <Text style={styles.invoiceModalTitle}>
                  {selectedPlan === 'year'
                    ? 'Оплата: Учебный год (79.90 €)'
                    : selectedPlan === 'semester'
                    ? 'Оплата: Полгода (44.90 €)'
                    : 'Оплата: 1 месяц (9.99 €)'}
                </Text>
                <TouchableOpacity
                  onPress={() => setIsInvoiceModalVisible(false)}
                  style={styles.invoiceModalClose}
                  hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}
                >
                  <Text style={styles.invoiceModalCloseText}>✕</Text>
                </TouchableOpacity>
              </View>

              <ScrollView
                showsVerticalScrollIndicator={false}
                contentContainerStyle={{ paddingBottom: 10 }}
              >
                {/* Method 1: Instant IBAN bank transfer */}
                <Text style={styles.invoiceSubheading}>1. Банковский перевод (Эстония / SEPA):</Text>
                <View style={styles.ibanDetailsBox}>
                  <View style={styles.ibanDetailRow}>
                    <Text style={styles.ibanDetailLabel}>Получатель:</Text>
                    <Text style={styles.ibanDetailValue}>{recipientName}</Text>
                  </View>

                  <View style={styles.ibanDetailRow}>
                    <Text style={styles.ibanDetailLabel}>IBAN (LHV Pank):</Text>
                    <TouchableOpacity
                      onPress={() => copyToClipboard(ibanAccount, 'IBAN')}
                      style={styles.copyableRow}
                    >
                      <Text style={styles.ibanDetailCode}>{ibanAccount}</Text>
                      <Text style={styles.copyActionPill}>
                        {copiedField === 'IBAN' ? 'Скопировано ✓' : 'Копировать 📋'}
                      </Text>
                    </TouchableOpacity>
                  </View>

                  <View style={styles.ibanDetailRow}>
                    <Text style={styles.ibanDetailLabel}>SWIFT / BIC:</Text>
                    <Text style={styles.ibanDetailValue}>{swiftBic}</Text>
                  </View>

                  <View style={styles.ibanDetailRow}>
                    <Text style={styles.ibanDetailLabel}>Сумма:</Text>
                    <Text style={styles.ibanDetailPrice}>
                      {selectedPlan === 'year'
                        ? '79.90 EUR'
                        : selectedPlan === 'semester'
                        ? '44.90 EUR'
                        : '9.99 EUR'}
                    </Text>
                  </View>

                  <View style={styles.ibanDetailRow}>
                    <Text style={styles.ibanDetailLabel}>Пояснение (Selgitus):</Text>
                    <Text style={styles.ibanDetailValue}>
                      TarkApp PRO {selectedPlan === 'year' ? 'Aasta' : selectedPlan === 'semester' ? 'Poolaasta' : 'Kuu'}
                    </Text>
                  </View>
                </View>

                {/* Method 2: Request e-invoice by email */}
                <Text style={[styles.invoiceSubheading, { marginTop: 14 }]}>
                  2. Получить официальный e-счёт (PDF) на email:
                </Text>
                <View style={styles.emailInputBox}>
                  <TextInput
                    style={styles.emailTextInput}
                    placeholder="ivan.ivanov@mail.ee"
                    placeholderTextColor={darkTheme.textMuted}
                    value={emailInput}
                    onChangeText={setEmailInput}
                    keyboardType="email-address"
                    autoCapitalize="none"
                    autoCorrect={false}
                  />
                  <TouchableOpacity
                    style={[
                      styles.sendInvoiceButton,
                      isSendingInvoice && styles.sendInvoiceButtonDisabled,
                    ]}
                    onPress={handleSendInvoiceRequest}
                    disabled={isSendingInvoice}
                  >
                    {isSendingInvoice ? (
                      <ActivityIndicator size="small" color="#064E3B" />
                    ) : (
                      <Text style={styles.sendInvoiceButtonText}>Выслать счёт</Text>
                    )}
                  </TouchableOpacity>
                </View>

                {/* Method 3: Key activation */}
                <TouchableOpacity
                  style={styles.keyPromptRow}
                  onPress={() => {
                    setIsInvoiceModalVisible(false);
                    onClose();
                    onOpenKeyActivation();
                  }}
                >
                  <Text style={styles.keyPromptRowText}>
                    Уже оплатили или есть ключ? <Text style={{ color: darkTheme.accent, fontWeight: '700' }}>Активировать ключ</Text>
                  </Text>
                </TouchableOpacity>
              </ScrollView>
            </View>
          </View>
        </Modal>
      </SafeAreaView>
    </Modal>
  );
};

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: darkTheme.background, // #12161A Deep Slate Anthracite
  },
  topBar: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 20,
    paddingTop: 8,
    paddingBottom: 4,
  },
  topBarSpacer: {
    width: 36,
  },
  closeButton: {
    width: 38,
    height: 38,
    borderRadius: 19,
    backgroundColor: darkTheme.cardBackground, // #1E252B
    borderWidth: 1,
    borderColor: darkTheme.cardBorder, // #2C363F
    justifyContent: 'center',
    alignItems: 'center',
  },
  closeButtonText: {
    fontSize: 18,
    color: darkTheme.textSecondary,
    fontWeight: '600',
    lineHeight: 20,
  },
  scrollView: {
    flex: 1,
  },
  scrollContent: {
    paddingHorizontal: 20,
    paddingTop: 4,
  },

  // Section A: Header
  headerSection: {
    alignItems: 'center',
    marginBottom: 24,
  },
  badgeIconCircle: {
    width: 64,
    height: 64,
    borderRadius: 32,
    backgroundColor: '#1E292F',
    borderWidth: 2,
    borderColor: darkTheme.accent,
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 16,
    ...Theme.shadow.chip,
  },
  badgeIconEmoji: {
    fontSize: 32,
  },
  headlineTitle: {
    fontSize: 24,
    fontWeight: '800',
    color: darkTheme.textPrimary, // #F8FAFC
    textAlign: 'center',
    letterSpacing: -0.4,
    marginBottom: 10,
    lineHeight: 30,
  },
  headlineSubtitle: {
    fontSize: 14.5,
    lineHeight: 21,
    color: darkTheme.textSecondary, // #94A3B8
    textAlign: 'center',
    paddingHorizontal: 8,
  },

  // Section B: Plan Cards
  plansContainer: {
    gap: 14,
    marginBottom: 20,
  },
  planCard: {
    backgroundColor: darkTheme.cardBackground, // #1E252B
    borderWidth: 1,
    borderColor: darkTheme.cardBorder, // #2C363F
    borderRadius: 20,
    padding: 18,
    position: 'relative',
    ...Theme.shadow.card,
  },
  planCardActive: {
    borderColor: darkTheme.accent, // #5FEDC5 Onsen Green 2px
    borderWidth: 2,
    backgroundColor: '#1E292F', // slightly elevated emerald-anthracite
  },
  discountBadge: {
    position: 'absolute',
    top: -12,
    right: 18,
    backgroundColor: '#064E3B', // deep pine
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: darkTheme.accent,
  },
  discountBadgeText: {
    color: darkTheme.accent, // #5FEDC5
    fontSize: 11,
    fontWeight: '800',
    letterSpacing: 0.4,
  },
  planCardHeaderRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    marginBottom: 12,
  },
  planRadioOuter: {
    width: 22,
    height: 22,
    borderRadius: 11,
    borderWidth: 2,
    borderColor: darkTheme.cardBorder,
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 12,
    marginTop: 2,
  },
  planRadioInner: {
    width: 12,
    height: 12,
    borderRadius: 6,
    backgroundColor: darkTheme.accent,
  },
  planTitleBox: {
    flex: 1,
  },
  planName: {
    fontSize: 18,
    fontWeight: '800',
    color: darkTheme.textPrimary, // #F8FAFC
    marginBottom: 3,
  },
  planDescription: {
    fontSize: 13,
    color: darkTheme.textSecondary, // #94A3B8
    lineHeight: 18,
  },
  planPriceRow: {
    marginTop: 2,
    paddingTop: 10,
    borderTopWidth: 1,
    borderTopColor: 'rgba(44, 54, 63, 0.6)',
  },
  planPriceBig: {
    fontSize: 28,
    fontWeight: '900',
    color: darkTheme.textPrimary,
    letterSpacing: -0.5,
    marginBottom: 4,
  },
  planPriceMedium: {
    fontSize: 22,
    fontWeight: '800',
    color: darkTheme.textPrimary,
    letterSpacing: -0.3,
    marginBottom: 4,
  },
  planPriceSubtext: {
    fontSize: 12.5,
    color: darkTheme.textSecondary,
    lineHeight: 17,
  },

  // Section C: Features List
  featuresCard: {
    backgroundColor: darkTheme.cardBackground,
    borderWidth: 1,
    borderColor: darkTheme.cardBorder,
    borderRadius: 18,
    padding: 16,
    marginBottom: 22,
    gap: 12,
  },
  featureItem: {
    flexDirection: 'row',
    alignItems: 'flex-start',
  },
  featureCheckCircle: {
    width: 22,
    height: 22,
    borderRadius: 11,
    backgroundColor: 'rgba(95, 237, 197, 0.15)',
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 12,
    marginTop: 1,
  },
  featureCheckIcon: {
    color: darkTheme.accent,
    fontSize: 12,
    fontWeight: '900',
  },
  featureItemText: {
    flex: 1,
    fontSize: 13.5,
    color: darkTheme.textSecondary,
    lineHeight: 19,
  },
  featureItemBold: {
    color: darkTheme.textPrimary,
    fontWeight: '700',
  },

  // Section D: CTA Button
  ctaContainer: {
    marginBottom: 20,
    alignItems: 'center',
  },
  ctaButton: {
    backgroundColor: darkTheme.accent, // #5FEDC5
    height: 54,
    borderRadius: 16,
    width: '100%',
    justifyContent: 'center',
    alignItems: 'center',
    ...Theme.shadow.card,
  },
  ctaButtonText: {
    color: darkTheme.accentText, // #064E3B
    fontSize: 17,
    fontWeight: '700',
    letterSpacing: -0.2,
  },
  ctaGuaranteeText: {
    marginTop: 10,
    fontSize: 12,
    color: darkTheme.textMuted, // #64748B
    textAlign: 'center',
    paddingHorizontal: 12,
    lineHeight: 16,
  },

  // Section E: Footer Promo & School Invoice
  footerSection: {
    alignItems: 'center',
    marginTop: 4,
  },
  footerDivider: {
    height: 1,
    backgroundColor: darkTheme.cardBorder,
    width: '100%',
    marginBottom: 16,
  },
  keyActivationLinkBox: {
    paddingVertical: 8,
    paddingHorizontal: 12,
  },
  keyActivationPrompt: {
    fontSize: 13.5,
    color: darkTheme.textSecondary,
    textAlign: 'center',
  },
  keyActivationLink: {
    color: darkTheme.accent,
    fontWeight: '700',
  },

  // Modal: Invoice & IBAN
  invoiceModalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.8)',
    justifyContent: 'center',
    alignItems: 'center',
    padding: 18,
  },
  invoiceModalCard: {
    backgroundColor: darkTheme.cardBackground,
    borderWidth: 1,
    borderColor: darkTheme.cardBorder,
    borderRadius: 22,
    padding: 20,
    width: '100%',
    maxHeight: '85%',
    ...Theme.shadow.card,
  },
  invoiceModalHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 14,
    borderBottomWidth: 1,
    borderBottomColor: darkTheme.cardBorder,
    paddingBottom: 10,
  },
  invoiceModalTitle: {
    fontSize: 16.5,
    fontWeight: '800',
    color: darkTheme.textPrimary,
    flex: 1,
  },
  invoiceModalClose: {
    padding: 6,
  },
  invoiceModalCloseText: {
    color: darkTheme.textSecondary,
    fontSize: 18,
    fontWeight: '700',
  },
  invoiceSubheading: {
    fontSize: 13.5,
    fontWeight: '700',
    color: darkTheme.textPrimary,
    marginBottom: 8,
  },
  ibanDetailsBox: {
    backgroundColor: Theme.colors.surfaceAlt,
    borderWidth: 1,
    borderColor: darkTheme.cardBorder,
    borderRadius: 14,
    padding: 12,
    gap: 8,
  },
  ibanDetailRow: {
    marginBottom: 2,
  },
  ibanDetailLabel: {
    fontSize: 11.5,
    color: darkTheme.textMuted,
    marginBottom: 2,
  },
  ibanDetailValue: {
    fontSize: 13.5,
    color: darkTheme.textPrimary,
    fontWeight: '600',
  },
  copyableRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginTop: 2,
  },
  ibanDetailCode: {
    fontSize: 14,
    fontWeight: '800',
    color: darkTheme.accent,
    letterSpacing: 0.5,
  },
  copyActionPill: {
    fontSize: 11.5,
    color: darkTheme.accent,
    backgroundColor: 'rgba(95, 237, 197, 0.12)',
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 8,
    fontWeight: '700',
  },
  ibanDetailPrice: {
    fontSize: 16,
    fontWeight: '800',
    color: '#F8FAFC',
  },
  emailInputBox: {
    flexDirection: 'row',
    gap: 8,
    marginTop: 4,
  },
  emailTextInput: {
    flex: 1,
    height: 44,
    backgroundColor: Theme.colors.surfaceAlt,
    borderWidth: 1,
    borderColor: darkTheme.cardBorder,
    borderRadius: 12,
    paddingHorizontal: 12,
    color: darkTheme.textPrimary,
    fontSize: 14,
  },
  sendInvoiceButton: {
    backgroundColor: darkTheme.accent,
    borderRadius: 12,
    paddingHorizontal: 14,
    justifyContent: 'center',
    alignItems: 'center',
    height: 44,
  },
  sendInvoiceButtonDisabled: {
    opacity: 0.6,
  },
  sendInvoiceButtonText: {
    color: darkTheme.accentText,
    fontSize: 13.5,
    fontWeight: '700',
  },
  keyPromptRow: {
    marginTop: 18,
    alignItems: 'center',
    paddingVertical: 6,
  },
  keyPromptRowText: {
    fontSize: 13,
    color: darkTheme.textSecondary,
  },
});
