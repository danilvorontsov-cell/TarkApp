import React, { useState } from 'react';
import {
  StyleSheet,
  View,
  Text,
  TouchableOpacity,
  ScrollView,
  Modal,
  TextInput,
  ActivityIndicator,
  Platform,
} from 'react-native';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';
import { StatusBar } from 'expo-status-bar';
import * as Clipboard from 'expo-clipboard';
import { LinearGradient } from 'expo-linear-gradient';
import { darkTheme, Theme } from '../theme/colors';
import { requestInvoiceEmail } from '../services/api';
import { ThemedAlert } from '../components/ThemedAlert';

export type SubscriptionPlan = 'year' | 'semester' | 'month' | 'full_year';

interface PaywallScreenProps {
  visible: boolean;
  onClose: () => void;
  onOpenKeyActivation: () => void;
  canClose?: boolean;
  remainingFreeScans?: number;
  totalFreeScans?: number;
  hasPro?: boolean;
}

export const PaywallScreen: React.FC<PaywallScreenProps> = ({
  visible,
  onClose,
  onOpenKeyActivation,
  canClose = true,
  remainingFreeScans = 5,
  totalFreeScans = 5,
  hasPro = false,
}) => {
  const insets = useSafeAreaInsets();
  const [selectedPlan, setSelectedPlan] = useState<SubscriptionPlan>('year');
  const [isInvoiceModalVisible, setIsInvoiceModalVisible] = useState(false);
  const [emailInput, setEmailInput] = useState('');
  const [isSendingInvoice, setIsSendingInvoice] = useState(false);
  const [invoiceStatus, setInvoiceStatus] = useState<{
    type: 'success' | 'warning' | 'error';
    text: string;
  } | null>(null);
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
      ThemedAlert.alert('Скопировано', text);
    }
  };

  const handleCtaPress = () => {
    // Открываем модальное окно выбора способа оплаты / реквизитов IBAN
    setIsInvoiceModalVisible(true);
  };

  const handleSendInvoiceRequest = async () => {
    const trimmedEmail = emailInput.trim();
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!trimmedEmail || !emailRegex.test(trimmedEmail)) {
      setInvoiceStatus({
        type: 'error',
        text: 'Пожалуйста, укажите корректный e-mail адрес (например, ivan.ivanov@mail.ee).',
      });
      ThemedAlert.alert(
        'Некорректный e-mail',
        'Пожалуйста, укажите верный адрес электронной почты для отправки PDF-счёта.'
      );
      return;
    }

    setIsSendingInvoice(true);
    setInvoiceStatus(null);
    try {
      const res = await requestInvoiceEmail(trimmedEmail, selectedPlan);

      if (res.email_sent) {
        setInvoiceStatus({
          type: 'success',
          text: res.message,
        });
        ThemedAlert.alert(
          'Счёт отправлен! ✅',
          res.message,
          [
            {
              text: 'Отлично',
              onPress: () => {
                setEmailInput('');
                setInvoiceStatus(null);
                setIsInvoiceModalVisible(false);
              },
            },
          ]
        );
      } else {
        setInvoiceStatus({
          type: 'warning',
          text: res.message,
        });
        ThemedAlert.alert(
          'Требуется настройка почты (SMTP / Resend)',
          res.message
        );
      }
    } catch (err: any) {
      const errMsg =
        err?.message ||
        'Не удалось отправить счёт. Проверьте соединение с сервером или оплатите по реквизитам IBAN выше.';
      setInvoiceStatus({
        type: 'error',
        text: errMsg,
      });
      ThemedAlert.alert('Ошибка отправки счёта', errMsg);
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
      <LinearGradient
        colors={['#1A2026', '#0D1115']}
        start={{ x: 0, y: 0 }}
        end={{ x: 0, y: 1 }}
        style={{ flex: 1 }}
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

          {/* Section B: Pricing Cards (1 Free + 4 Paid Tiers ordered by duration & price) */}
          <View style={styles.plansContainer}>
            {/* Tier 1: Free Start (0 €) — Non-selectable informational card */}
            <View style={styles.freePlanCard}>
              <View style={styles.freePlanHeaderRow}>
                <View style={styles.planTitleBox}>
                  <Text style={styles.planName}>Бесплатный старт (Free)</Text>
                  <Text style={styles.planDescription}>Базовое знакомство с TarkApp</Text>
                </View>

                <View style={styles.freeCurrentBadge}>
                  <Text style={styles.freeCurrentBadgeText}>
                    {hasPro ? 'БАЗОВЫЙ' : 'ТЕКУЩИЙ ТАРИФ'}
                  </Text>
                </View>
              </View>

              <View style={styles.freeCounterBox}>
                <Text style={styles.freeCounterText}>
                  🎁 Осталось разборов:{' '}
                  <Text style={styles.freeCounterHighlight}>{remainingFreeScans}</Text> из{' '}
                  <Text style={styles.freeCounterHighlight}>{totalFreeScans}</Text>
                </Text>
              </View>

              <View style={styles.freeFooterRow}>
                <Text style={styles.freePriceLabel}>0 €</Text>
                <View style={styles.freeDefaultInfoPill}>
                  <Text style={styles.freeDefaultInfoText}>✓ Включён по умолчанию</Text>
                </View>
              </View>
            </View>

            {/* Tier 2: 1 Month Flexible (9.99 €) */}
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
                  <Text style={styles.planName}>1 месяц (Гибкий)</Text>
                  <Text style={styles.planDescription}>Для разовой помощи или подготовки к четверти</Text>
                </View>
              </View>

              <View style={styles.planPriceRow}>
                <Text style={styles.planPriceMedium}>9.99 € / мес</Text>
                <Text style={styles.planPriceSubtext}>Продление каждый месяц, отмена в любой момент</Text>
              </View>
            </TouchableOpacity>

            {/* Tier 3: Semester (5 months — 44.90 €) */}
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
                  <Text style={styles.planName}>Семестр (5 месяцев)</Text>
                  <Text style={styles.planDescription}>Уверенная учёба на один семестр</Text>
                </View>
              </View>

              <View style={styles.planPriceRow}>
                <Text style={styles.planPriceBig}>44.90 €</Text>
                <Text style={styles.planPriceSubtext}>
                  ~8.99 € / мес (разовая оплата)
                </Text>
              </View>
            </TouchableOpacity>

            {/* Tier 4: Full School Year (9 months — 71.90 €) - Recommended */}
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
                <Text style={styles.discountBadgeText}>ХИТ • РЕКОМЕНДУЕМЫЙ</Text>
              </View>

              <View style={styles.planCardHeaderRow}>
                <View style={styles.planRadioOuter}>
                  {selectedPlan === 'year' && <View style={styles.planRadioInner} />}
                </View>

                <View style={styles.planTitleBox}>
                  <Text style={styles.planName}>Учебный год (9 месяцев)</Text>
                  <Text style={styles.planDescription}>Сентябрь — Май (все 9 учебных месяцев)</Text>
                </View>
              </View>

              <View style={styles.planPriceRow}>
                <Text style={styles.planPriceBig}>71.90 €</Text>
                <Text style={styles.planPriceSubtext}>
                  ~7.99 € / мес (разовый платёж на все 9 месяцев учёбы)
                </Text>
              </View>
            </TouchableOpacity>

            {/* Tier 5: Full Year with Vacations (12 months — 89.90 €) */}
            <TouchableOpacity
              style={[
                styles.planCard,
                selectedPlan === 'full_year' && styles.planCardActive,
              ]}
              onPress={() => setSelectedPlan('full_year')}
              activeOpacity={0.88}
              accessibilityRole="radio"
              accessibilityState={{ checked: selectedPlan === 'full_year' }}
            >
              <View style={styles.planCardHeaderRow}>
                <View style={styles.planRadioOuter}>
                  {selectedPlan === 'full_year' && <View style={styles.planRadioInner} />}
                </View>

                <View style={styles.planTitleBox}>
                  <Text style={styles.planName}>Полный год (12 месяцев с каникулами)</Text>
                  <Text style={styles.planDescription}>Учебный год + 3 месяца лета для закрепления языка</Text>
                </View>
              </View>

              <View style={styles.planPriceRow}>
                <Text style={styles.planPriceBig}>89.90 €</Text>
                <Text style={styles.planPriceSubtext}>
                  ~7.49 € / мес (9 мес учёбы + 3 мес лета)
                </Text>
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

          {/* Section D: CTA Button (Vertical Gradient ['#66F6CF', '#42DCA3']) */}
          <View style={styles.ctaContainer}>
            <TouchableOpacity
              style={styles.ctaButtonWrapper}
              onPress={handleCtaPress}
              activeOpacity={0.85}
              accessibilityRole="button"
            >
              <LinearGradient
                colors={['#66F6CF', '#42DCA3']}
                start={{ x: 0, y: 0 }}
                end={{ x: 0, y: 1 }}
                style={styles.ctaButton}
              >
                <Text style={styles.ctaButtonText}>
                  {selectedPlan === 'year'
                    ? 'Оформить учебный год — 71.90 €'
                    : selectedPlan === 'semester'
                    ? 'Оформить семестр — 44.90 €'
                    : selectedPlan === 'month'
                    ? 'Попробовать 1 месяц — 9.99 €'
                    : 'Оформить год с каникулами — 89.90 €'}
                </Text>
              </LinearGradient>
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
                    ? 'Оплата: Учебный год (71.90 €)'
                    : selectedPlan === 'semester'
                    ? 'Оплата: Семестр (44.90 €)'
                    : selectedPlan === 'month'
                    ? 'Оплата: 1 месяц (9.99 €)'
                    : 'Оплата: Год с каникулами (89.90 €)'}
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
                        ? '71.90 EUR'
                        : selectedPlan === 'semester'
                        ? '44.90 EUR'
                        : selectedPlan === 'month'
                        ? '9.99 EUR'
                        : '89.90 EUR'}
                    </Text>
                  </View>

                  <View style={styles.ibanDetailRow}>
                    <Text style={styles.ibanDetailLabel}>Пояснение (Selgitus):</Text>
                    <Text style={styles.ibanDetailValue}>
                      TarkApp PRO {selectedPlan === 'year' ? 'Aasta 9k' : selectedPlan === 'semester' ? 'Semester 5k' : selectedPlan === 'month' ? 'Kuu 1k' : 'Aasta 12k'}
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
                    placeholderTextColor="#94A3B8"
                    value={emailInput}
                    onChangeText={(val) => {
                      setEmailInput(val);
                      if (invoiceStatus) setInvoiceStatus(null);
                    }}
                    keyboardType="email-address"
                    autoCapitalize="none"
                    autoCorrect={false}
                    autoComplete="off"
                    importantForAutofill="no"
                    selectionColor="#5FEDC5"
                    cursorColor="#5FEDC5"
                    editable={!isSendingInvoice}
                  />
                  <TouchableOpacity
                    style={[
                      styles.sendInvoiceButton,
                      isSendingInvoice && styles.sendInvoiceButtonDisabled,
                    ]}
                    onPress={handleSendInvoiceRequest}
                    disabled={isSendingInvoice}
                    activeOpacity={0.85}
                  >
                    {isSendingInvoice ? (
                      <View style={styles.sendInvoiceLoadingRow}>
                        <ActivityIndicator size="small" color="#064E3B" />
                        <Text style={styles.sendInvoiceButtonText}>Отправка...</Text>
                      </View>
                    ) : (
                      <Text style={styles.sendInvoiceButtonText}>Выслать счёт</Text>
                    )}
                  </TouchableOpacity>
                </View>

                {invoiceStatus && (
                  <View
                    style={[
                      styles.invoiceStatusBanner,
                      invoiceStatus.type === 'success'
                        ? styles.invoiceStatusSuccess
                        : invoiceStatus.type === 'warning'
                        ? styles.invoiceStatusWarning
                        : styles.invoiceStatusError,
                    ]}
                  >
                    <Text
                      style={[
                        styles.invoiceStatusText,
                        invoiceStatus.type === 'success'
                          ? styles.invoiceStatusTextSuccess
                          : invoiceStatus.type === 'warning'
                          ? styles.invoiceStatusTextWarning
                          : styles.invoiceStatusTextError,
                      ]}
                    >
                      {invoiceStatus.text}
                    </Text>
                  </View>
                )}

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
    </LinearGradient>
  </Modal>
  );
};

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: 'transparent',
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
  freePlanCard: {
    backgroundColor: darkTheme.cardBackground, // #1E252B
    borderWidth: 1,
    borderColor: '#5FEDC5',
    borderRadius: 20,
    padding: 18,
    position: 'relative',
    ...Theme.shadow.card,
  },
  freePlanHeaderRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    justifyContent: 'space-between',
    gap: 10,
    marginBottom: 12,
  },
  freeCurrentBadge: {
    backgroundColor: 'rgba(95, 237, 197, 0.14)',
    borderWidth: 1,
    borderColor: '#5FEDC5',
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 10,
  },
  freeCurrentBadgeText: {
    color: '#5FEDC5',
    fontSize: 11,
    fontWeight: '800',
    letterSpacing: 0.4,
  },
  freeCounterBox: {
    backgroundColor: 'rgba(95, 237, 197, 0.1)',
    borderWidth: 1,
    borderColor: 'rgba(95, 237, 197, 0.35)',
    borderRadius: 12,
    paddingVertical: 10,
    paddingHorizontal: 14,
    marginBottom: 12,
  },
  freeCounterText: {
    fontSize: 14,
    fontWeight: '700',
    color: '#F8FAFC',
  },
  freeCounterHighlight: {
    color: '#5FEDC5',
    fontWeight: '900',
  },
  freeFooterRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingTop: 10,
    borderTopWidth: 1,
    borderTopColor: 'rgba(44, 54, 63, 0.6)',
  },
  freePriceLabel: {
    fontSize: 22,
    fontWeight: '900',
    color: '#F8FAFC',
  },
  freeDefaultInfoPill: {
    backgroundColor: 'rgba(148, 163, 184, 0.12)',
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 6,
  },
  freeDefaultInfoText: {
    fontSize: 12.5,
    fontWeight: '700',
    color: '#CBD5E1',
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
  ctaButtonWrapper: {
    width: '100%',
    borderRadius: 16,
    overflow: 'hidden',
    ...Theme.shadow.card,
  },
  ctaButton: {
    height: 54,
    borderRadius: 16,
    width: '100%',
    justifyContent: 'center',
    alignItems: 'center',
  },
  ctaButtonText: {
    color: '#064E3B', // Dark contrast pine text
    fontSize: 17,
    fontWeight: '800',
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
    height: 46,
    backgroundColor: '#1E252B',
    borderWidth: 1,
    borderColor: '#5FEDC5',
    borderRadius: 12,
    paddingHorizontal: 14,
    color: '#FFFFFF',
    fontSize: 14.5,
    fontWeight: '600',
  },
  sendInvoiceButton: {
    backgroundColor: '#5FEDC5',
    borderRadius: 12,
    paddingHorizontal: 14,
    justifyContent: 'center',
    alignItems: 'center',
    height: 46,
  },
  sendInvoiceButtonDisabled: {
    opacity: 0.75,
  },
  sendInvoiceLoadingRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  sendInvoiceButtonText: {
    color: '#064E3B',
    fontSize: 13.5,
    fontWeight: '800',
  },
  invoiceStatusBanner: {
    marginTop: 10,
    paddingVertical: 10,
    paddingHorizontal: 12,
    borderRadius: 12,
    borderWidth: 1,
  },
  invoiceStatusSuccess: {
    backgroundColor: 'rgba(95, 237, 197, 0.14)',
    borderColor: '#5FEDC5',
  },
  invoiceStatusWarning: {
    backgroundColor: 'rgba(251, 191, 36, 0.12)',
    borderColor: '#F59E0B',
  },
  invoiceStatusError: {
    backgroundColor: '#3F1E24',
    borderColor: '#EF4444',
  },
  invoiceStatusText: {
    fontSize: 12.5,
    lineHeight: 17,
    fontWeight: '600',
  },
  invoiceStatusTextSuccess: {
    color: '#5FEDC5',
  },
  invoiceStatusTextWarning: {
    color: '#FDE68A',
  },
  invoiceStatusTextError: {
    color: '#FCA5A5',
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
