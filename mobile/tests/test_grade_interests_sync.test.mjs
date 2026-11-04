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
});

test('Scenario 2: StorageService implements auto-healing in getProfile()', () => {
  const storageContent = fs.readFileSync(path.join(rootDir, 'src', 'services', 'storage.ts'), 'utf-8');

  assert.ok(storageContent.includes('getDefaultInterestsForTier'), 'storage.ts must import getDefaultInterestsForTier');
  assert.ok(storageContent.includes('isDefaultInterestsList'), 'storage.ts must import isDefaultInterestsList');
  assert.ok(
    storageContent.includes('tier !== \'primary\' && !parsed.hasCustomInterests && isDefaultInterestsList(parsed.interests)'),
    'storage.ts must self-heal legacy primary defaults for older students'
  );
});

test('Scenario 3: ProfileSetupModal synchronizes interests on save', () => {
  const modalContent = fs.readFileSync(path.join(rootDir, 'src', 'components', 'ProfileSetupModal.tsx'), 'utf-8');

  assert.ok(modalContent.includes('getDefaultInterestsForTier'), 'ProfileSetupModal must import getDefaultInterestsForTier');
  assert.ok(modalContent.includes('PRIMARY_CHILDISH_INTERESTS'), 'ProfileSetupModal must import PRIMARY_CHILDISH_INTERESTS');
  assert.ok(modalContent.includes('isTierChanged && isDefaultInterestsList'), 'ProfileSetupModal must check for tier changes and defaults');
});

test('Scenario 4: App.tsx updateGrade and TextInput placeholder', () => {
  const appContent = fs.readFileSync(path.join(rootDir, 'App.tsx'), 'utf-8');

  assert.ok(appContent.includes('getInterestsPlaceholder(profile.tier)'), 'App.tsx must use dynamic tier placeholder');
  assert.ok(appContent.includes('PRIMARY_CHILDISH_INTERESTS'), 'App.tsx must import PRIMARY_CHILDISH_INTERESTS');
  assert.ok(appContent.includes('getDefaultInterestsForTier(newTier)'), 'updateGrade must assign new tier defaults');
  assert.ok(appContent.includes('setInterestsText(newInterestsText)'), 'updateGrade must synchronize text field');
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
  const AGE_SUGGESTIONS = {
    primary: ['Minecraft', 'LEGO', 'Roblox', 'Brawl Stars', 'Динозавры'],
    middle: ['Футбол', 'Видеоигры', 'Музыка и треки', 'Мемы'],
    high: ['Видеоигры', 'Музыка и треки', 'CS:GO / Valorant'],
    gymnasium: ['IT и программирование', 'Кино и сериалы', 'Путешествия', 'Фитнес и тренировки'],
  };

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

    const validSuggestions = (AGE_SUGGESTIONS[newTier] || []).map((s) => s.trim().toLowerCase());
    const validForNewTier = newInterests.filter((i) =>
      validSuggestions.includes(i.trim().toLowerCase())
    );

    if (!isCustom || isDefaultInterestsList(newInterests) || (isTierChanged && isDefaultInterestsList(newInterests)) || validForNewTier.length === 0) {
      newInterests = [...DEFAULT_INTERESTS_BY_TIER[newTier]];
      isCustom = false;
    } else {
      newInterests = validForNewTier;
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

  // Student in Grade 3 has custom interests including Brawl Stars
  let pupil = {
    grade: 3,
    tier: 'primary',
    interests: ['Minecraft', 'LEGO', 'Roblox', 'Brawl Stars'],
    hasCustomInterests: true,
  };

  // Switch to Grade 12 (gymnasium)
  pupil = updateGradeWithIsolation(pupil, 12);
  assert.equal(pupil.grade, 12);
  assert.equal(pupil.tier, 'gymnasium');
  // Primary toys must be completely purged
  assert.equal(pupil.interests.includes('Minecraft'), false);
  assert.equal(pupil.interests.includes('LEGO'), false);
  assert.equal(pupil.interests.includes('Roblox'), false);
  assert.equal(pupil.interests.includes('Brawl Stars'), false);
  assert.deepEqual(pupil.interests, ['IT и программирование', 'Кино и сериалы', 'Музыка и концерты']);

  // Pupil adds gymnasium interests
  pupil.interests = ['IT и программирование', 'Путешествия', 'Фитнес и тренировки'];
  pupil.hasCustomInterests = true;

  // Switch back to Grade 3 (primary)
  pupil = updateGradeWithIsolation(pupil, 3);
  assert.equal(pupil.grade, 3);
  assert.equal(pupil.tier, 'primary');
  // Gymnasium interests must be completely purged
  assert.equal(pupil.interests.includes('Путешествия'), false);
  assert.equal(pupil.interests.includes('Фитнес и тренировки'), false);
  assert.deepEqual(pupil.interests, ['Minecraft', 'LEGO', 'Roblox']);
});
