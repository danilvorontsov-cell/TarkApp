import React, { useState, useEffect } from 'react';
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
  Linking,
} from 'react-native';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';
import { StatusBar } from 'expo-status-bar';
import * as Clipboard from 'expo-clipboard';
import { LinearGradient } from 'expo-linear-gradient';
import { darkTheme, Theme } from '../theme/colors';
import {
  requestInvoiceEmail,
  getPlansCatalog,
  PlanItem,
  BankDetails,
  InvoiceRequestResponse,
  API_BASE_URL,
  resolveBaseUrl,
} from '../services/api';
import { DEFAULT_PLANS, DEFAULT_BANK_DETAILS } from '../utils/subscription';
import { ThemedAlert } from '../components/ThemedAlert';

export type SubscriptionPlan = 'year' | 'semester' | 'month' | 'full_year' | 'school_year' | 'month_1' | string;

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
  remainingFreeScans = 20,
  totalFreeScans = 20,
  hasPro = false,
}) => {
  const insets = useSafeAreaInsets();
  const [plans, setPlans] = useState<PlanItem[]>(DEFAULT_PLANS);
  const [bankDetails, setBankDetails] = useState<BankDetails>(DEFAULT_BANK_DETAILS);
  const [selectedPlanId, setSelectedPlanId] = useState<string>('school_year');
  const [isInvoiceModalVisible, setIsInvoiceModalVisible] = useState(false);
  const [invoiceData, setInvoiceData] = useState<InvoiceRequestResponse | null>(null);
  const [isLoadingInvoice, setIsLoadingInvoice] = useState(false);
  const [emailInput, setEmailInput] = useState('');
  const [isSendingInvoice, setIsSendingInvoice] = useState(false);
  const [invoiceStatus, setInvoiceStatus] = useState<{
    type: 'success' | 'warning' | 'error';
    text: string;
  } | null>(null);
  const [copiedField, setCopiedField] = useState<string | null>(null);

  useEffect(() => {
    let isMounted = true;
    async function loadCatalog() {
      try {
        const data = await getPlansCatalog();
        if (isMounted && data?.plans?.length) {
          setPlans(data.plans);
          if (data.bank_details) {
            setBankDetails(data.bank_details);
          }
          if (!data.plans.some((p) => p.id === selectedPlanId)) {
            const popular = data.plans.find((p) => p.is_popular);
            setSelectedPlanId(popular ? popular.id : data.plans[0].id);
          }
        }
      } catch (err) {
        // Fallback to DEFAULT_PLANS & DEFAULT_BANK_DETAILS
      }
    }
    if (visible) {
      loadCatalog();
    }
    return () => {
      isMounted = false;
    };
  }, [visible]);

  const activePlan =
    plans.find((p) => p.id === selectedPlanId) ||
    plans.find((p) => p.is_popular) ||
    plans[0] ||
    DEFAULT_PLANS[2];

  const ibanAccount = invoiceData?.iban || bankDetails.iban || DEFAULT_BANK_DETAILS.iban;
  const recipientName = invoiceData?.recipient || bankDetails.recipient_name || DEFAULT_BANK_DETAILS.recipient_name;
  const swiftBic = invoiceData?.swift_bic || bankDetails.swift_bic || DEFAULT_BANK_DETAILS.swift_bic;

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
    if (invoiceData && invoiceData.amount && invoiceData.amount !== activePlan.price) {
      setInvoiceData(null);
    }
    setInvoiceStatus(null);
    setIsInvoiceModalVisible(true);
  };

  const handleDownloadPdf = async () => {
    if (!invoiceData?.pdf_download_url) {
      ThemedAlert.alert('Формирование счёта', 'Пожалуйста, подождите завершения загрузки счёта...');
      return;
    }
    const fullUrl = `${resolveBaseUrl(API_BASE_URL)}${invoiceData.pdf_download_url}`;
    try {
      await Linking.openURL(fullUrl);
    } catch (err: any) {
      ThemedAlert.alert('Ошибка', 'Не удалось открыть PDF: ' + (err?.message || String(err)));
    }
  };

  const handleSendInvoiceRequest = async () => {
    const trimmedEmail = emailInput.trim();
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!trimmedEmail) {
      setInvoiceStatus({
        type: 'error',
        text: 'Пожалуйста, укажите адрес электронной почты. На него придёт счёт и ключ доступа.',
      });
      ThemedAlert.alert(
        'Укажите e-mail',
        'Поле e-mail обязательно для заполнения перед формированием счёта, чтобы системе было куда отправить ключ доступа.'
      );
      return;
    }
    if (!emailRegex.test(trimmedEmail)) {
      setInvoiceStatus({
        type: 'error',
        text: 'Пожалуйста, укажите корректный e-mail адрес (например, ivan.ivanov@mail.ee).',
      });
      ThemedAlert.alert(
        'Некорректный e-mail',
        'Пожалуйста, укажите верный адрес электронной почты для отправки PDF-счёта и ключа доступа.'
      );
      return;
    }

    setIsSendingInvoice(true);
    setInvoiceStatus(null);
    try {
      const res = await requestInvoiceEmail(trimmedEmail, activePlan.id);
      setInvoiceData(res);

      const invNum = res.invoice_number || invoiceData?.invoice_number || '';
      const successTitle = 'Счёт успешно сформирован';
      const successText =
        `Номер счёта: ${invNum}\n\nРеквизиты и Viitenumber отображены на экране. После подтверждения банковского перевода ключ активации будет автоматически отправлен на указанный email.`;

      setInvoiceStatus({
        type: 'success',
        text: `Номер счёта: ${invNum}\nРеквизиты и Viitenumber отображены на экране. После подтверждения банковского перевода ключ активации будет автоматически отправлен на указанный email.`,
      });

      ThemedAlert.alert(
        successTitle,
        successText
      );
    } catch (err: any) {
      let errMsg =
        err?.message ||
        'Не удалось сформировать счёт. Проверьте соединение с сервером или оплатите по реквизитам IBAN выше.';
      if (
        errMsg.includes('SMTP') ||
        errMsg.includes('Resend') ||
        errMsg.includes('.env')
      ) {
        errMsg = 'Счёт готов к оплате. Используйте реквизиты IBAN и Viitenumber ниже.';
      }
      setInvoiceStatus({
        type: 'error',
        text: errMsg,
      });
      ThemedAlert.alert('Ошибка формирования счёта', errMsg);
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

          {/* Closed Beta Info Banner */}
          <View style={styles.closedBetaBanner}>
            <View style={styles.closedBetaHeaderRow}>
              <Text style={styles.closedBetaIcon}>🔒</Text>
              <Text style={styles.closedBetaTitle}>Пилотный запуск (Closed Beta)</Text>
            </View>
            <Text style={styles.closedBetaText}>
              Доступ оформляется по безналичному счёту (Arve). Укажите ваш email — на него придёт счёт, а после поступления банковской оплаты система автоматически отправит ключ доступа на вашу почту.
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

            {/* Dynamic Plans (Server-Driven UI) */}
            {plans.map((plan) => {
              const isSelected = selectedPlanId === plan.id;
              const badgeLabel = plan.is_popular
                ? (plan.badge ? `${plan.badge.toUpperCase()} • РЕКОМЕНДУЕМЫЙ` : 'ХИТ • РЕКОМЕНДУЕМЫЙ')
                : (plan.badge ? plan.badge.toUpperCase() : null);

              return (
                <TouchableOpacity
                  key={plan.id}
                  style={[
                    styles.planCard,
                    isSelected && styles.planCardActive,
                  ]}
                  onPress={() => setSelectedPlanId(plan.id)}
                  activeOpacity={0.88}
                  accessibilityRole="radio"
                  accessibilityState={{ checked: isSelected }}
                >
                  {badgeLabel && (
                    <View style={styles.discountBadge}>
                      <Text style={styles.discountBadgeText}>{badgeLabel}</Text>
                    </View>
                  )}

                  <View style={styles.planCardHeaderRow}>
                    <View style={styles.planRadioOuter}>
                      {isSelected && <View style={styles.planRadioInner} />}
                    </View>

                    <View style={styles.planTitleBox}>
                      <Text style={styles.planName}>{plan.title}</Text>
                      {Boolean(plan.description) && (
                        <Text style={styles.planDescription}>{plan.description}</Text>
                      )}
                    </View>
                  </View>

                  <View style={styles.planPriceRow}>
                    <Text style={plan.duration_months === 1 ? styles.planPriceMedium : styles.planPriceBig}>
                      {plan.duration_months === 1 ? `${plan.price} € / мес` : `${plan.price} €`}
                    </Text>
                    {Boolean(plan.subtext) && (
                      <Text style={styles.planPriceSubtext}>{plan.subtext}</Text>
                    )}
                  </View>
                </TouchableOpacity>
              );
            })}
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
                  {activePlan.title.startsWith('Оформить') || activePlan.title.startsWith('Попробовать')
                    ? `${activePlan.title} — ${activePlan.price} €`
                    : `Оформить ${activePlan.title} — ${activePlan.price} €`}
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
                  {`Оплата: ${activePlan.title} (${activePlan.price} €)`}
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
                {!invoiceData ? (
                  <>
                    <View style={styles.modalInfoPill}>
                      <Text style={styles.modalInfoPillIcon}>🔒</Text>
                      <Text style={styles.modalInfoPillText}>
                        Доступ оформляется по безналичному счёту (Arve). Укажите ваш email — на него придёт счёт с персональным Viitenumber, а после поступления банковской оплаты система автоматически отправит ключ доступа на вашу почту.
                      </Text>
                    </View>

                    <Text style={styles.inputLabel}>Ваш e-mail для счёта и ключа доступа:</Text>
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
                            <Text style={styles.sendInvoiceButtonText}>Формирование...</Text>
                          </View>
                        ) : (
                          <Text style={styles.sendInvoiceButtonText}>Сформировать счёт</Text>
                        )}
                      </TouchableOpacity>
                    </View>
                  </>
                ) : (
                  <>
                    <View style={styles.invoiceCreatedBadge}>
                      <Text style={styles.invoiceCreatedBadgeTitle}>
                        {`✓ Счёт № ${invoiceData.invoice_number || ''} сформирован`}
                      </Text>
                      <Text style={styles.invoiceCreatedBadgeSubtitle}>
                        Реквизиты и Viitenumber отображены на экране. После подтверждения банковского перевода ключ активации будет автоматически отправлен на указанный email.
                      </Text>
                    </View>

                    {/* Bank transfer details */}
                    <Text style={styles.invoiceSubheading}>Реквизиты для оплаты (Эстония / SEPA):</Text>
                    <View style={styles.ibanDetailsBox}>
                      <View style={styles.ibanDetailRow}>
                        <Text style={styles.ibanDetailLabel}>Получатель:</Text>
                        <TouchableOpacity
                          onPress={() => copyToClipboard(recipientName, 'Получатель')}
                          style={styles.copyableRow}
                        >
                          <Text style={styles.ibanDetailValue}>{recipientName}</Text>
                          <Text style={styles.copyActionPill}>
                            {copiedField === 'Получатель' ? 'Скопировано ✓' : 'Копировать 📋'}
                          </Text>
                        </TouchableOpacity>
                      </View>

                      <View style={styles.ibanDetailRow}>
                        <Text style={styles.ibanDetailLabel}>IBAN (Coop Pank):</Text>
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
                        <TouchableOpacity
                          onPress={() => copyToClipboard(swiftBic, 'SWIFT')}
                          style={styles.copyableRow}
                        >
                          <Text style={styles.ibanDetailValue}>{swiftBic}</Text>
                          <Text style={styles.copyActionPill}>
                            {copiedField === 'SWIFT' ? 'Скопировано ✓' : 'Копировать 📋'}
                          </Text>
                        </TouchableOpacity>
                      </View>

                      <View style={styles.ibanDetailRow}>
                        <Text style={styles.ibanDetailLabel}>Сумма:</Text>
                        <Text style={styles.ibanDetailPrice}>
                          {`${invoiceData?.amount || activePlan.price} EUR`}
                        </Text>
                      </View>

                      {/* Viitenumber Highlighted Box */}
                      <View style={styles.viiteCard}>
                        <View style={styles.viiteHeaderRow}>
                          <Text style={styles.viiteLabel}>Номер ссылки / Viitenumber:</Text>
                          <TouchableOpacity
                            onPress={() => copyToClipboard(invoiceData?.viitenumber || '', 'Viitenumber')}
                            disabled={!invoiceData?.viitenumber}
                            hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
                          >
                            <Text style={styles.copyActionPill}>
                              {copiedField === 'Viitenumber' ? 'Скопировано ✓' : 'Копировать 📋'}
                            </Text>
                          </TouchableOpacity>
                        </View>
                        <Text style={styles.viiteValue}>
                          {invoiceData?.viitenumber}
                        </Text>
                        <View style={styles.viiteWarningBadge}>
                          <Text style={styles.viiteWarningBadgeText}>
                            ⚠️ Обязательно укажите viitenumber при переводе
                          </Text>
                        </View>
                      </View>

                      <View style={styles.ibanDetailRow}>
                        <Text style={styles.ibanDetailLabel}>Пояснение (Selgitus):</Text>
                        <TouchableOpacity
                          onPress={() =>
                            copyToClipboard(
                              invoiceData?.explanation ||
                                `Tarkapp, ${invoiceData?.invoice_number || 'INV-2026-1001'}`,
                              'Пояснение'
                            )
                          }
                          style={styles.copyableRow}
                        >
                          <Text style={[styles.ibanDetailValue, { flex: 1, paddingRight: 6 }]}>
                            {invoiceData?.explanation ||
                              `Tarkapp, ${invoiceData?.invoice_number || 'INV-2026-1001'}`}
                          </Text>
                          <Text style={styles.copyActionPill}>
                            {copiedField === 'Пояснение' ? 'Скопировано ✓' : 'Копировать 📋'}
                          </Text>
                        </TouchableOpacity>
                      </View>
                    </View>

                    {/* Button: Download PDF Invoice */}
                    <TouchableOpacity
                      style={[
                        styles.downloadPdfButton,
                        !invoiceData?.pdf_download_url && styles.downloadPdfButtonDisabled,
                      ]}
                      onPress={handleDownloadPdf}
                      disabled={!invoiceData?.pdf_download_url}
                      activeOpacity={0.85}
                    >
                      <Text style={styles.downloadPdfButtonText}>Скачать PDF-счет 📄</Text>
                    </TouchableOpacity>

                    <TouchableOpacity
                      style={styles.changeEmailRow}
                      onPress={() => setInvoiceData(null)}
                      activeOpacity={0.7}
                    >
                      <Text style={styles.changeEmailText}>
                        Оформить счёт на другой email? <Text style={styles.changeEmailLink}>Изменить</Text>
                      </Text>
                    </TouchableOpacity>
                  </>
                )}

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
  viiteCard: {
    backgroundColor: 'rgba(95, 237, 197, 0.08)',
    borderWidth: 1.5,
    borderColor: '#5FEDC5',
    borderRadius: 14,
    padding: 12,
    marginVertical: 4,
  },
  viiteHeaderRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 4,
  },
  viiteLabel: {
    fontSize: 12,
    fontWeight: '700',
    color: '#E2E8F0',
  },
  viiteValue: {
    fontSize: 18,
    fontWeight: '900',
    color: '#5FEDC5',
    letterSpacing: 1.2,
    marginVertical: 3,
  },
  viiteWarningBadge: {
    backgroundColor: 'rgba(245, 158, 11, 0.15)',
    borderWidth: 1,
    borderColor: 'rgba(245, 158, 11, 0.4)',
    borderRadius: 8,
    paddingHorizontal: 8,
    paddingVertical: 5,
    marginTop: 6,
  },
  viiteWarningBadgeText: {
    fontSize: 11,
    fontWeight: '700',
    color: '#FDE68A',
  },
  downloadPdfButton: {
    backgroundColor: '#1E252B',
    borderWidth: 1,
    borderColor: '#5FEDC5',
    borderRadius: 12,
    paddingVertical: 12,
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: 10,
    marginBottom: 6,
  },
  downloadPdfButtonDisabled: {
    opacity: 0.6,
  },
  downloadPdfButtonText: {
    color: '#5FEDC5',
    fontSize: 14,
    fontWeight: '800',
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
  closedBetaBanner: {
    backgroundColor: '#1E252B',
    borderRadius: 16,
    borderWidth: 1,
    borderColor: '#2C363F',
    padding: 16,
    marginBottom: 16,
  },
  closedBetaHeaderRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 6,
    gap: 8,
  },
  closedBetaIcon: {
    fontSize: 18,
  },
  closedBetaTitle: {
    fontSize: 15,
    fontWeight: '800',
    color: '#5FEDC5',
    letterSpacing: 0.2,
  },
  closedBetaText: {
    fontSize: 13,
    lineHeight: 19,
    color: '#CBD5E1',
    fontWeight: '500',
  },
  modalInfoPill: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    backgroundColor: 'rgba(95, 237, 197, 0.08)',
    borderWidth: 1,
    borderColor: 'rgba(95, 237, 197, 0.25)',
    borderRadius: 14,
    padding: 12,
    marginBottom: 16,
    gap: 10,
  },
  modalInfoPillIcon: {
    fontSize: 18,
    marginTop: 1,
  },
  modalInfoPillText: {
    flex: 1,
    fontSize: 13,
    lineHeight: 18,
    color: '#CBD5E1',
    fontWeight: '500',
  },
  inputLabel: {
    fontSize: 13,
    fontWeight: '700',
    color: '#E2E8F0',
    marginBottom: 8,
  },
  invoiceCreatedBadge: {
    backgroundColor: 'rgba(95, 237, 197, 0.12)',
    borderWidth: 1,
    borderColor: '#5FEDC5',
    borderRadius: 14,
    padding: 14,
    marginBottom: 14,
  },
  invoiceCreatedBadgeTitle: {
    fontSize: 15,
    fontWeight: '800',
    color: '#5FEDC5',
    marginBottom: 4,
  },
  invoiceCreatedBadgeSubtitle: {
    fontSize: 12.5,
    lineHeight: 18,
    color: '#CBD5E1',
    fontWeight: '500',
  },
  changeEmailRow: {
    alignItems: 'center',
    paddingVertical: 10,
    marginTop: 4,
  },
  changeEmailText: {
    fontSize: 13,
    color: '#94A3B8',
  },
  changeEmailLink: {
    color: '#5FEDC5',
    fontWeight: '700',
  },
});
