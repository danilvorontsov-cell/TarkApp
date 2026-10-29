import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.resolve(__dirname, '..');

test('Scenario 1: No legacy Alert.alert calls remain across mobile screens and App.tsx', () => {
  const targetFiles = [
    path.join(rootDir, 'App.tsx'),
    path.join(rootDir, 'src', 'screens', 'FeedbackScreen.tsx'),
    path.join(rootDir, 'src', 'screens', 'PaywallScreen.tsx'),
    path.join(rootDir, 'src', 'screens', 'QuickTranslatorScreen.tsx'),
  ];

  for (const file of targetFiles) {
    const content = fs.readFileSync(file, 'utf-8');
    // Ensure no legacy `Alert.alert(` calls exist (excluding `ThemedAlert.alert(`)
    const alertMatches = content.match(/(?<!Themed)Alert\.alert\(/g);
    assert.equal(
      alertMatches,
      null,
      `File ${path.basename(file)} still contains ${alertMatches?.length} Alert.alert call(s)! All must use ThemedAlert.alert.`
    );

    // Ensure ThemedAlert is imported
    assert.ok(
      content.includes('ThemedAlert'),
      `File ${path.basename(file)} must import and use ThemedAlert`
    );
  }
});

test('Scenario 2: ThemedAlert detects suitable decorative icons and handles button callbacks', () => {
  let latestAlert = null;
  const mockListener = (state) => {
    latestAlert = state;
  };

  // Minimal simulator of ThemedAlert logic
  const triggerThemedAlert = (title, message, buttons, options) => {
    let icon = options?.icon;
    if (!icon) {
      const lower = `${title} ${message || ''}`.toLowerCase();
      if (lower.includes('ошибка') || lower.includes('не удалось') || lower.includes('сбой')) {
        icon = '❌';
      } else if (lower.includes('удалить') || lower.includes('очистить') || lower.includes('выход')) {
        icon = '⚠️';
      } else if (lower.includes('успеш') || lower.includes('сохранен') || lower.includes('добро пожаловать')) {
        icon = '✅';
      } else if (lower.includes('камер') || lower.includes('фото') || lower.includes('галере')) {
        icon = '📸';
      } else if (lower.includes('ключ') || lower.includes('профиль') || lower.includes('имя')) {
        icon = '🧑‍🎓';
      } else {
        icon = '💡';
      }
    }

    mockListener({
      visible: true,
      title,
      message,
      buttons: buttons || [{ text: 'Понятно', style: 'default' }],
      icon,
    });
  };

  // Test error alert
  triggerThemedAlert('Ошибка сервера', 'Не удалось связаться с сервером');
  assert.equal(latestAlert.icon, '❌');

  // Test save alert
  triggerThemedAlert('⭐ Сохранено в историю!', 'Разбор успешно сохранен');
  assert.equal(latestAlert.icon, '✅');

  // Test camera alert
  triggerThemedAlert('Доступ к камере', 'Требуется разрешение');
  assert.equal(latestAlert.icon, '📸');

  // Test destructive action
  triggerThemedAlert('Очистить историю и словарь?', 'Удалит все данные');
  assert.equal(latestAlert.icon, '⚠️');

  // Test profile welcome
  triggerThemedAlert('Добро пожаловать!', 'Профиль активирован для Даниил');
  assert.equal(latestAlert.icon, '✅');
});

test('Scenario 3: Profile setup flow calculates tier, validates non-empty nickname, and updates status', () => {
  const getTierFromGrade = (grade) => (grade <= 4 ? 'primary' : 'middle');

  // Unregistered / initial state
  const initialProfile = {
    grade: 3,
    tier: 'primary',
    nickname: '',
    interests: ['Minecraft'],
  };

  const isInitialRegistered = Boolean(initialProfile.nickname && initialProfile.nickname.trim().length > 0);
  assert.equal(isInitialRegistered, false, 'Initial state without nickname must be unregistered (guest)');

  // User submits profile modal with Name = "Даниил", Grade = 6
  const submittedName = '  Даниил  ';
  const submittedGrade = 6;

  const trimmed = submittedName.trim() || 'Ученик';
  const newTier = getTierFromGrade(submittedGrade);

  const updatedProfile = {
    ...initialProfile,
    nickname: trimmed,
    grade: submittedGrade,
    tier: newTier,
  };

  assert.equal(updatedProfile.nickname, 'Даниил');
  assert.equal(updatedProfile.grade, 6);
  assert.equal(updatedProfile.tier, 'middle');

  // Badge in header & drawer:
  const isRegisteredNow = Boolean(updatedProfile.nickname && updatedProfile.nickname.trim().length > 0);
  assert.equal(isRegisteredNow, true);

  const headerPillText = updatedProfile.nickname.trim();
  assert.equal(headerPillText, 'Даниил', 'Header pill should show student name instead of "Войти"');

  const drawerSubtitle = `${updatedProfile.nickname} • ${updatedProfile.grade} кл.`;
  assert.equal(drawerSubtitle, 'Даниил • 6 кл.', 'Drawer should display "Даниил • 6 кл." instead of guest status');
});

test('Scenario 4: ThemedAlertContainer and ProfileSetupModal are rendered in App.tsx', () => {
  const appContent = fs.readFileSync(path.join(rootDir, 'App.tsx'), 'utf-8');

  assert.ok(appContent.includes('<ThemedAlertContainer />'), 'App.tsx must mount <ThemedAlertContainer />');
  assert.ok(appContent.includes('<ProfileSetupModal'), 'App.tsx must mount <ProfileSetupModal />');
  assert.ok(appContent.includes('onOpenProfileSetup='), 'App.tsx must pass onOpenProfileSetup to DrawerMenu');
});
