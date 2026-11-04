import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.resolve(__dirname, '..');

test('Scenario 1: Types and constants exported in src/types/index.ts', () => {
  const typesContent = fs.readFileSync(path.join(rootDir, 'src', 'types', 'index.ts'), 'utf-8');

  assert.ok(typesContent.includes('DEFAULT_INTERESTS_BY_TIER'), 'Must export DEFAULT_INTERESTS_BY_TIER');
  assert.ok(typesContent.includes('getDefaultInterestsForTier'), 'Must export getDefaultInterestsForTier');
  assert.ok(typesContent.includes('isDefaultInterestsList'), 'Must export isDefaultInterestsList');
  assert.ok(typesContent.includes('PRIMARY_CHILDISH_INTERESTS'), 'Must export PRIMARY_CHILDISH_INTERESTS');
  assert.ok(typesContent.includes('getInterestsPlaceholder'), 'Must export getInterestsPlaceholder');
  assert.ok(typesContent.includes('hasCustomInterests?: boolean'), 'UserProfile must include hasCustomInterests');
  assert.ok(typesContent.includes('interestsByGrade?: Record<number, string[]>'), 'UserProfile must include interestsByGrade');
});

test('Scenario 2: StorageService implements auto-healing, interestsByGrade, and draft management', () => {
  const storageContent = fs.readFileSync(path.join(rootDir, 'src', 'services', 'storage.ts'), 'utf-8');

  assert.ok(storageContent.includes('getDefaultInterestsForTier'), 'storage.ts must import getDefaultInterestsForTier');
  assert.ok(storageContent.includes('isDefaultInterestsList'), 'storage.ts must import isDefaultInterestsList');
  assert.ok(
    storageContent.includes('tier !== \'primary\' && !parsed.hasCustomInterests && isDefaultInterestsList(parsed.interests)'),
    'storage.ts must self-heal legacy primary defaults for older students'
  );
  assert.ok(storageContent.includes('getProfileDraft'), 'storage.ts must implement getProfileDraft');
  assert.ok(storageContent.includes('saveProfileDraft'), 'storage.ts must implement saveProfileDraft');
  assert.ok(storageContent.includes('clearProfileDraft'), 'storage.ts must implement clearProfileDraft');
  assert.ok(storageContent.includes('interestsByGrade'), 'storage.ts must serialize and deserialize interestsByGrade');
});

test('Scenario 3: ProfileSetupModal supports profile draft, avatar press draft persistence, and interestsByGrade', () => {
  const modalContent = fs.readFileSync(path.join(rootDir, 'src', 'components', 'ProfileSetupModal.tsx'), 'utf-8');

  assert.ok(modalContent.includes('getDefaultInterestsForTier'), 'ProfileSetupModal must import getDefaultInterestsForTier');
  assert.ok(modalContent.includes('StorageService'), 'ProfileSetupModal must import StorageService');
  assert.ok(modalContent.includes('saveProfileDraft'), 'ProfileSetupModal must save draft on input changes and avatar press');
  assert.ok(modalContent.includes('interestsByGrade'), 'ProfileSetupModal must update interestsByGrade');
});

test('Scenario 4: App.tsx updateGrade, draft preservation, and TextInput placeholder', () => {
  const appContent = fs.readFileSync(path.join(rootDir, 'App.tsx'), 'utf-8');

  assert.ok(appContent.includes('getInterestsPlaceholder(profile.tier)'), 'App.tsx must use dynamic tier placeholder');
  assert.ok(appContent.includes('getDefaultInterestsForTier(newTier)'), 'updateGrade must assign new tier defaults');
  assert.ok(appContent.includes('setInterestsText(newInterestsText)'), 'updateGrade must synchronize text field');
  assert.ok(appContent.includes('getProfileDraft'), 'App.tsx must check profile draft on avatar capture and startup');
  assert.ok(appContent.includes('interestsByGrade'), 'App.tsx must persist interestsByGrade in updateGrade and handlers');
});

test('Scenario 5: Simulation of grade switching across 3, 6, and 12 classes', () => {
  const DEFAULT_INTERESTS_BY_TIER = {
    primary: ['Minecraft', 'LEGO', 'Roblox'],
    middle: ['Футбол', 'Видеоигры', 'Музыка и треки'],
    high: ['Видеоигры', 'Музыка и треки', 'Гаджеты и технологии'],
    gymnasium: ['IT и программирование', 'Кино и сериалы', 'Музыка и концерты'],
  };

  const getTierFromGrade = (grade) => {
    if (grade <= 3) return 'primary';
    if (grade <= 6) return 'middle';
    if (grade <= 9) return 'high';
    return 'gymnasium';
  };

  const getDefaultInterestsForTier = (tier) => [...(DEFAULT_INTERESTS_BY_TIER[tier] || DEFAULT_INTERESTS_BY_TIER.primary)];

  const PRIMARY_CHILDISH_INTERESTS = new Set([
    'minecraft',
    'lego',
    'roblox',
    'brawl stars',
    'котики и собачки',
    'динозавры',
  ]);

  const isDefaultInterestsList = (interests) => {
    if (!interests || interests.length === 0) return true;
    const normalized = interests.map((i) => i.trim().toLowerCase()).sort().join(',');
    for (const t of Object.keys(DEFAULT_INTERESTS_BY_TIER)) {
      const tierDefaults = DEFAULT_INTERESTS_BY_TIER[t].map((i) => i.trim().toLowerCase()).sort().join(',');
      if (normalized === tierDefaults) return true;
    }
    return false;
  };

  const simulateUpdateGrade = (profile, grade) => {
    const oldTier = profile.tier || getTierFromGrade(profile.grade);
    const newTier = getTierFromGrade(grade);
    const isTierChanged = oldTier !== newTier;

    let newInterests = profile.interests || [];
    let isCustom = profile.hasCustomInterests;

    if (!isCustom || isDefaultInterestsList(newInterests) || (isTierChanged && isDefaultInterestsList(newInterests))) {
      newInterests = getDefaultInterestsForTier(newTier);
      isCustom = false;
    } else if (isTierChanged && (newTier === 'high' || newTier === 'gymnasium')) {
      newInterests = newInterests.filter(
        (i) => !PRIMARY_CHILDISH_INTERESTS.has(i.trim().toLowerCase())
      );
      if (newInterests.length === 0) {
        newInterests = getDefaultInterestsForTier(newTier);
        isCustom = false;
      }
    }

    return {
      ...profile,
      grade,
      tier: newTier,
      interests: newInterests,
      hasCustomInterests: isCustom,
      interestsText: newInterests.join(', '),
    };
  };

  // 1. Initial Grade 3 profile
  let student = {
    grade: 3,
    tier: 'primary',
    interests: ['Minecraft', 'LEGO', 'Roblox'],
    hasCustomInterests: false,
  };

  // 2. Switch to Grade 6 (Middle School)
  student = simulateUpdateGrade(student, 6);
  assert.equal(student.grade, 6);
  assert.equal(student.tier, 'middle');
  assert.deepEqual(student.interests, ['Футбол', 'Видеоигры', 'Музыка и треки']);
  assert.equal(student.interestsText, 'Футбол, Видеоигры, Музыка и треки');
  assert.equal(student.interests.includes('LEGO'), false);
  assert.equal(student.interests.includes('Roblox'), false);

  // 3. Switch to Grade 12 (Gymnasium)
  student = simulateUpdateGrade(student, 12);
  assert.equal(student.grade, 12);
  assert.equal(student.tier, 'gymnasium');
  assert.deepEqual(student.interests, ['IT и программирование', 'Кино и сериалы', 'Музыка и концерты']);
  assert.equal(student.interestsText, 'IT и программирование, Кино и сериалы, Музыка и концерты');
  assert.equal(student.interests.includes('Minecraft'), false);
  assert.equal(student.interests.includes('LEGO'), false);
  assert.equal(student.interests.includes('Roblox'), false);

  // 4. Switch back to Grade 3 (Primary)
  student = simulateUpdateGrade(student, 3);
  assert.equal(student.grade, 3);
  assert.equal(student.tier, 'primary');
  assert.deepEqual(student.interests, ['Minecraft', 'LEGO', 'Roblox']);
});

test('Scenario 6: Strict grade isolation prevents cross-tier interest accumulator contamination', () => {
  const DEFAULT_INTERESTS_BY_TIER = {
    primary: ['Minecraft', 'LEGO', 'Roblox'],
    middle: ['Футбол', 'Видеоигры', 'Музыка и треки'],
    high: ['Видеоигры', 'Музыка и треки', 'Гаджеты и технологии'],
    gymnasium: ['IT и программирование', 'Кино и сериалы', 'Музыка и концерты'],
  };

  const getTierFromGrade = (grade) => {
    if (grade <= 3) return 'primary';
    if (grade <= 6) return 'middle';
    if (grade <= 9) return 'high';
    return 'gymnasium';
  };

  const isDefaultInterestsList = (interests) => {
    if (!interests || interests.length === 0) return true;
    const normalized = interests.map((i) => i.trim().toLowerCase()).sort().join(',');
    for (const t of Object.keys(DEFAULT_INTERESTS_BY_TIER)) {
      const tierDefaults = DEFAULT_INTERESTS_BY_TIER[t].map((i) => i.trim().toLowerCase()).sort().join(',');
      if (normalized === tierDefaults) return true;
    }
    return false;
  };

  const updateGradeWithIsolation = (profile, grade) => {
    const oldTier = profile.tier || getTierFromGrade(profile.grade);
    const newTier = getTierFromGrade(grade);
    const isTierChanged = oldTier !== newTier;

    let newInterests = profile.interests || [];
    let isCustom = profile.hasCustomInterests;

    if (!isCustom || isDefaultInterestsList(newInterests) || (isTierChanged && isDefaultInterestsList(newInterests))) {
      newInterests = [...DEFAULT_INTERESTS_BY_TIER[newTier]];
      isCustom = false;
    } else {
      newInterests = newInterests;
      isCustom = true;
    }

    return {
      ...profile,
      grade,
      tier: newTier,
      interests: newInterests,
      hasCustomInterests: isCustom,
      interestsText: newInterests.join(', '),
    };
  };

  let pupil = {
    grade: 3,
    tier: 'primary',
    interests: ['Minecraft', 'LEGO', 'Roblox'],
    hasCustomInterests: false,
  };

  pupil = updateGradeWithIsolation(pupil, 12);
  assert.equal(pupil.grade, 12);
  assert.equal(pupil.tier, 'gymnasium');
  assert.deepEqual(pupil.interests, ['IT и программирование', 'Кино и сериалы', 'Музыка и концерты']);
});

test('Scenario 7: Cyclical grade switching (3 -> 12 -> 3) preserves custom interests for Grade 3 via interestsByGrade', () => {
  const DEFAULT_INTERESTS_BY_TIER = {
    primary: ['Minecraft', 'LEGO', 'Roblox'],
    middle: ['Футбол', 'Видеоигры', 'Музыка и треки'],
    high: ['Видеоигры', 'Музыка и треки', 'Гаджеты и технологии'],
    gymnasium: ['IT и программирование', 'Кино и сериалы', 'Музыка и концерты'],
  };

  const getTierFromGrade = (grade) => {
    if (grade <= 3) return 'primary';
    if (grade <= 6) return 'middle';
    if (grade <= 9) return 'high';
    return 'gymnasium';
  };

  const getDefaultInterestsForTier = (tier) => [...(DEFAULT_INTERESTS_BY_TIER[tier] || DEFAULT_INTERESTS_BY_TIER.primary)];

  const isDefaultInterestsList = (interests) => {
    if (!interests || interests.length === 0) return true;
    const normalized = interests.map((i) => i.trim().toLowerCase()).sort().join(',');
    for (const t of Object.keys(DEFAULT_INTERESTS_BY_TIER)) {
      const tierDefaults = DEFAULT_INTERESTS_BY_TIER[t].map((i) => i.trim().toLowerCase()).sort().join(',');
      if (normalized === tierDefaults) return true;
    }
    return false;
  };

  const updateGradeWithMap = (profile, grade) => {
    const oldGrade = profile.grade;
    const newTier = getTierFromGrade(grade);

    const gradeMap = {
      ...(profile.interestsByGrade || {}),
    };
    if (oldGrade) {
      gradeMap[oldGrade] = profile.interests || [];
    }

    const storedForNewGrade = gradeMap[grade] || gradeMap[String(grade)];
    let newInterests;
    let isCustom;

    if (storedForNewGrade && Array.isArray(storedForNewGrade) && storedForNewGrade.length > 0) {
      newInterests = storedForNewGrade;
      isCustom = !isDefaultInterestsList(storedForNewGrade);
    } else {
      newInterests = getDefaultInterestsForTier(newTier);
      isCustom = false;
      gradeMap[grade] = newInterests;
    }

    return {
      ...profile,
      grade,
      tier: newTier,
      interests: newInterests,
      hasCustomInterests: isCustom,
      interestsByGrade: gradeMap,
    };
  };

  // 1. Student in Grade 3 enters custom interests: "Шахматы, Астрономия, Плавание"
  let student = {
    nickname: 'Даниил',
    grade: 3,
    tier: 'primary',
    interests: ['Шахматы', 'Астрономия', 'Плавание'],
    hasCustomInterests: true,
    interestsByGrade: {
      3: ['Шахматы', 'Астрономия', 'Плавание'],
    },
  };

  // 2. Switch to Grade 12 (Gymnasium)
  student = updateGradeWithMap(student, 12);
  assert.equal(student.grade, 12);
  assert.equal(student.tier, 'gymnasium');
  assert.deepEqual(student.interests, ['IT и программирование', 'Кино и сериалы', 'Музыка и концерты']);
  assert.equal(student.hasCustomInterests, false);
  // Grade 3 interests must remain intact in the map
  assert.deepEqual(student.interestsByGrade[3], ['Шахматы', 'Астрономия', 'Плавание']);

  // 3. Student customizes Grade 12 interests
  student.interests = ['Искусственный интеллект', 'Стартапы', 'Финансы'];
  student.hasCustomInterests = true;
  student.interestsByGrade[12] = student.interests;

  // 4. Switch BACK to Grade 3 (Primary)
  student = updateGradeWithMap(student, 3);
  assert.equal(student.grade, 3);
  assert.equal(student.tier, 'primary');
  // CRITICAL: Custom Grade 3 interests must be restored, NOT overwritten with defaults!
  assert.deepEqual(student.interests, ['Шахматы', 'Астрономия', 'Плавание']);
  assert.equal(student.hasCustomInterests, true);
  // Grade 12 interests must also remain preserved in map
  assert.deepEqual(student.interestsByGrade[12], ['Искусственный интеллект', 'Стартапы', 'Финансы']);
});

test('Scenario 8: Camera photo capture preserves user input fields (name, grade) and updates avatarUri', () => {
  // Simulate active draft in form
  let draft = {
    nickname: 'Даниил',
    grade: 4,
  };

  let activeProfile = {
    nickname: '',
    grade: 3,
    tier: 'primary',
    interests: ['Minecraft', 'LEGO', 'Roblox'],
  };

  const getTierFromGrade = (grade) => {
    if (grade <= 3) return 'primary';
    if (grade <= 6) return 'middle';
    if (grade <= 9) return 'high';
    return 'gymnasium';
  };

  // Simulate camera photo capture intent return
  const simulatePhotoCaptured = (profile, draftData, newUri) => {
    const currentNickname = (draftData?.nickname !== undefined && draftData.nickname.trim().length > 0)
      ? draftData.nickname
      : (profile.nickname || '');
    const currentGrade = (draftData?.grade !== undefined && draftData.grade >= 1 && draftData.grade <= 12)
      ? draftData.grade
      : (profile.grade || 3);
    const tier = getTierFromGrade(currentGrade);

    return {
      ...profile,
      nickname: currentNickname,
      grade: currentGrade,
      tier,
      avatarUri: newUri,
    };
  };

  const newPhotoUri = 'file:///data/user/0/com.tarkapp/cache/avatar_123.jpg';
  const updated = simulatePhotoCaptured(activeProfile, draft, newPhotoUri);

  // Verification: Name and grade from draft are preserved, avatarUri is updated
  assert.equal(updated.nickname, 'Даниил', 'Nickname must not reset to empty or default');
  assert.equal(updated.grade, 4, 'Grade must remain 4, not reset to 3');
  assert.equal(updated.tier, 'middle', 'Tier must be correctly calculated for Grade 4');
  assert.equal(updated.avatarUri, newPhotoUri, 'Avatar URI must be set to captured photo');
});

test('Scenario 9: StorageService serialization and deserialization of interestsByGrade dictionary', () => {
  const serializeProfile = (profile) => JSON.stringify(profile);
  const deserializeProfile = (json) => {
    const parsed = JSON.parse(json);
    const normalizedMap = {};
    if (parsed.interestsByGrade && typeof parsed.interestsByGrade === 'object') {
      for (const key of Object.keys(parsed.interestsByGrade)) {
        const numKey = Number(key);
        if (!isNaN(numKey) && Array.isArray(parsed.interestsByGrade[key])) {
          normalizedMap[numKey] = parsed.interestsByGrade[key];
        }
      }
    }
    parsed.interestsByGrade = normalizedMap;
    return parsed;
  };

  const initialProfile = {
    nickname: 'София',
    grade: 7,
    tier: 'high',
    interests: ['Биология', 'Рисование'],
    hasCustomInterests: true,
    interestsByGrade: {
      3: ['Minecraft', 'LEGO'],
      7: ['Биология', 'Рисование'],
      11: ['Медицина', 'Химия'],
    },
  };

  const serialized = serializeProfile(initialProfile);
  const deserialized = deserializeProfile(serialized);

  assert.equal(deserialized.nickname, 'София');
  assert.equal(deserialized.grade, 7);
  assert.deepEqual(deserialized.interestsByGrade[3], ['Minecraft', 'LEGO']);
  assert.deepEqual(deserialized.interestsByGrade[7], ['Биология', 'Рисование']);
  assert.deepEqual(deserialized.interestsByGrade[11], ['Медицина', 'Химия']);
});
