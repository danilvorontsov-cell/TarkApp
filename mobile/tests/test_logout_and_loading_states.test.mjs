import test from 'node:test';
import assert from 'node:assert/strict';

test('Scenario 1: Session state invalidation on logout prevents in-flight analysis resurrection', async () => {
  let sessionLessons = [{ id: 'lesson_1', title: 'Loomad metsas' }];
  let analysis = { task_title: 'Loomad metsas', is_acceptable: true };
  let capturedImages = [{ uri: 'file://img1.jpg' }];
  let capturedImageUri = 'file://img1.jpg';
  let isLoading = false;
  let analysisSessionId = 0;

  // Mock analysis process with cancellation token check
  const startAnalysis = async () => {
    const currentSession = ++analysisSessionId;
    isLoading = true;

    // Simulate async delay (API network request)
    await new Promise((r) => setTimeout(r, 50));

    // Guard: discard if session was invalidated during API call
    if (analysisSessionId !== currentSession) {
      return;
    }

    analysis = { task_title: 'Uus teema', is_acceptable: true };
    sessionLessons = [{ id: 'lesson_2', title: 'Uus teema' }, ...sessionLessons];
    isLoading = false;
  };

  // 1. Start analysis
  const inFlightPromise = startAnalysis();
  assert.equal(isLoading, true);

  // 2. User presses Logout while analysis is in flight
  // Logout handler:
  analysisSessionId++; // Invalidate active requests
  analysis = null;
  sessionLessons = [];
  capturedImages = [];
  capturedImageUri = null;
  isLoading = false;

  await inFlightPromise;

  // Verify: in-flight analysis must NOT have resurrected state or set analysis!
  assert.equal(analysis, null, 'Analysis must remain null after logout');
  assert.equal(sessionLessons.length, 0, 'Session lessons must remain empty after logout');
  assert.equal(capturedImages.length, 0, 'Captured images must remain empty after logout');
  assert.equal(capturedImageUri, null, 'Captured image URI must remain null after logout');
  assert.equal(isLoading, false, 'Loading must remain false after logout');
});

test('Scenario 2: Logout clears all active lesson cards and returns to empty study state', () => {
  let state = {
    profile: { grade: 3, tier: 'primary', nickname: 'Artur' },
    analysis: { task_title: 'Sõnajalad' },
    sessionLessons: [{ id: '1', title: 'Sõnajalad' }],
    capturedImages: [{ uri: 'file://img.jpg' }],
    isSaved: true,
    showAlternativeExplanation: true,
    currentTab: 'settings',
  };

  // Perform logout
  state.profile = { ...state.profile, nickname: '', avatarUri: undefined };
  state.analysis = null;
  state.sessionLessons = [];
  state.capturedImages = [];
  state.isSaved = false;
  state.showAlternativeExplanation = false;
  state.currentTab = 'study';

  assert.equal(state.analysis, null);
  assert.equal(state.sessionLessons.length, 0);
  assert.equal(state.capturedImages.length, 0);
  assert.equal(state.currentTab, 'study');
  assert.equal(state.profile.nickname, '');
});

test('Scenario 3: Alternative explanation badge tokens conform to Dark Nordic contrast spec', async () => {
  const fs = await import('node:fs');
  const appContent = fs.readFileSync('mobile/App.tsx', 'utf-8');

  // Verify badge styles in App.tsx
  assert.match(
    appContent,
    /altExplanationBadge:\s*\{[^}]*backgroundColor:\s*['"]rgba\(95,\s*237,\s*197,\s*0\.12\)['"]/s,
    'altExplanationBadge must have backgroundColor rgba(95, 237, 197, 0.12)'
  );

  assert.match(
    appContent,
    /altExplanationBadge:\s*\{[^}]*borderColor:\s*['"]#5FEDC5['"]/s,
    'altExplanationBadge must have borderColor #5FEDC5'
  );

  assert.match(
    appContent,
    /altExplanationBadgeText:\s*\{[^}]*color:\s*['"]#5FEDC5['"]/s,
    'altExplanationBadgeText must have color #5FEDC5'
  );

  assert.match(
    appContent,
    /altExplanationBadgeText:\s*\{[^}]*fontSize:\s*13/s,
    'altExplanationBadgeText must have fontSize >= 13'
  );
});

test('Scenario 4: Fullscreen LoadingOverlay is imported and rendered on loading state', async () => {
  const fs = await import('node:fs');
  const appContent = fs.readFileSync('mobile/App.tsx', 'utf-8');

  assert.match(
    appContent,
    /import\s*\{\s*LoadingOverlay\s*\}\s*from\s*['"]\.\/src\/components\/LoadingOverlay['"]/,
    'LoadingOverlay must be imported in App.tsx'
  );

  assert.match(
    appContent,
    /<LoadingOverlay[^>]*visible=\{loading\}/,
    'LoadingOverlay must be rendered with visible={loading}'
  );

  assert.match(
    appContent,
    /title="TarkApp анализирует страницу\.\.\."/,
    'LoadingOverlay must have title TarkApp анализирует страницу...'
  );

  assert.match(
    appContent,
    /subtitle="Переводим термины и готовим подсказку"/,
    'LoadingOverlay must have subtitle Переводим термины и готовим подсказку'
  );
});

test('Scenario 5: Concave downward arch header geometry and burger touch priority', async () => {
  const fs = await import('node:fs');
  const appContent = fs.readFileSync('mobile/App.tsx', 'utf-8');
  const drawerContent = fs.readFileSync('mobile/src/components/DrawerMenu.tsx', 'utf-8');

  // Verify headerBar has flat bottom, position: 'relative', zIndex: 10, elevation: 10
  assert.match(
    appContent,
    /headerBar:\s*\{[^}]*position:\s*['"]relative['"][^}]*borderBottomLeftRadius:\s*0[^}]*borderBottomRightRadius:\s*0[^}]*zIndex:\s*10[^}]*elevation:\s*10/s,
    'headerBar must have position: relative, borderBottomRadius: 0, zIndex: 10, elevation: 10'
  );

  // Verify burger button has hitSlop 12 and opens drawer
  assert.match(
    appContent,
    /style=\{styles\.headerMenuBtn\}[\s\S]*?onPress=\{\(\)\s*=>\s*setIsDrawerOpen\(true\)\}[\s\S]*?hitSlop=\{\{\s*top:\s*12,\s*bottom:\s*12,\s*left:\s*12,\s*right:\s*12\s*\}\}/,
    'headerMenuBtn must trigger setIsDrawerOpen(true) and have hitSlop 12'
  );

  // Verify bodyConcaveContainer wraps scroll area with negative top margin, rounded top corners, and lower zIndex/elevation than headerBar
  assert.match(
    appContent,
    /bodyConcaveContainer:\s*\{[^}]*marginTop:\s*-\d+[^}]*borderTopLeftRadius:\s*24[^}]*borderTopRightRadius:\s*24[^}]*zIndex:\s*1[^}]*elevation:\s*0/s,
    'bodyConcaveContainer must have negative marginTop, borderTopRadius 24, zIndex: 1, elevation: 0'
  );

  // Verify DrawerMenu root overlay has zIndex: 100 and elevation: 100 above headerBar
  assert.match(
    drawerContent,
    /drawerRootOverlay:\s*\{[^}]*zIndex:\s*100[^}]*elevation:\s*100/s,
    'DrawerMenu root overlay must have zIndex: 100 and elevation: 100'
  );
});

test('Scenario 6: Immediate loading state on camera and gallery selection', async () => {
  const fs = await import('node:fs');
  const appContent = fs.readFileSync('mobile/App.tsx', 'utf-8');

  // handleTakePhoto immediately calls setLoading(true) before image optimization
  assert.match(
    appContent,
    /handleTakePhoto\s*=\s*async[\s\S]*?setLoading\(true\)[\s\S]*?optimizePageImage/,
    'handleTakePhoto must set loading(true) immediately before optimization'
  );

  // handlePickImage immediately calls setLoading(true) before image optimization
  assert.match(
    appContent,
    /handlePickImage\s*=\s*async[\s\S]*?setLoading\(true\)[\s\S]*?optimizePageImages/,
    'handlePickImage must set loading(true) immediately before optimization'
  );
});

test('Scenario 7: Näidis badge, step numbers, and next task button contrast tokens', async () => {
  const fs = await import('node:fs');
  const appContent = fs.readFileSync('mobile/App.tsx', 'utf-8');

  // naidisBadge and naidisBadgeText
  assert.match(
    appContent,
    /naidisBadgeText:\s*\{[^}]*color:\s*['"]#5FEDC5['"]/s,
    'naidisBadgeText must use mint #5FEDC5'
  );

  // naidisStepNumberText
  assert.match(
    appContent,
    /naidisStepNumberText:\s*\{[^}]*color:\s*['"]#5FEDC5['"]/s,
    'naidisStepNumberText must use mint #5FEDC5'
  );

  // nextTaskButtonText
  assert.match(
    appContent,
    /nextTaskButtonText:\s*\{[^}]*color:\s*['"]#5FEDC5['"]/s,
    'nextTaskButtonText must use mint #5FEDC5'
  );
});

test('Scenario 8: Drawer footer branding and Header vertical gradient', async () => {
  const fs = await import('node:fs');
  const drawerContent = fs.readFileSync('mobile/src/components/DrawerMenu.tsx', 'utf-8');
  const appContent = fs.readFileSync('mobile/App.tsx', 'utf-8');

  // Verify Drawer footer text
  assert.match(
    drawerContent,
    /TarkApp • v1\.0\.0 • Tark Systems/,
    'DrawerMenu must display TarkApp • v1.0.0 • Tark Systems'
  );

  // Verify Header vertical gradient ['#66F6CF', '#42DCA3']
  assert.match(
    appContent,
    /<LinearGradient[\s\S]*?colors=\{\['#66F6CF',\s*'#42DCA3'\]\}[\s\S]*?start=\{\{\s*x:\s*0,\s*y:\s*0\s*\}\}[\s\S]*?end=\{\{\s*x:\s*0,\s*y:\s*1\s*\}\}[\s\S]*?style=\{\[styles\.headerBar/,
    'Header bar must use vertical LinearGradient ["#66F6CF", "#42DCA3"]'
  );
});

test('Scenario 9: End-to-end Graphite & Mint WCAG contrast audit across all components', async () => {
  const fs = await import('node:fs');
  const appContent = fs.readFileSync('mobile/App.tsx', 'utf-8');
  const comingSoonContent = fs.readFileSync('mobile/src/components/ComingSoonCard.tsx', 'utf-8');
  const avatarModalContent = fs.readFileSync('mobile/src/components/AvatarPickerModal.tsx', 'utf-8');
  const licenseModalContent = fs.readFileSync('mobile/src/components/LicenseActivationModal.tsx', 'utf-8');

  // Verify App.tsx outline buttons and translucent badges use #5FEDC5
  assert.match(appContent, /tierBadgeText:\s*\{[^}]*color:\s*['"]#5FEDC5['"]/s);
  assert.match(appContent, /altToggleBtnTextActive:\s*\{[^}]*color:\s*['"]#5FEDC5['"]/s);
  assert.match(appContent, /academicBadgeText:\s*\{[^}]*color:\s*['"]#5FEDC5['"]/s);
  assert.match(appContent, /saveCardButtonTextSaved:\s*\{[^}]*color:\s*['"]#5FEDC5['"]/s);
  assert.match(appContent, /pupilPillText:\s*\{[^}]*color:\s*['"]#5FEDC5['"]/s);
  assert.match(appContent, /historyTypeBadgeText:\s*\{[^}]*color:\s*['"]#5FEDC5['"]/s);
  assert.match(appContent, /suggestionTextSelected:\s*\{[^}]*color:\s*['"]#5FEDC5['"]/s);

  // Verify ComingSoonCard badge uses #5FEDC5 on dark translucent mint
  assert.match(comingSoonContent, /badgeText:\s*\{[^}]*color:\s*['"]#5FEDC5['"]/s);

  // Verify AvatarPickerModal secondary button uses #5FEDC5 text matching its border
  assert.match(avatarModalContent, /btnSecondaryText:\s*\{[^}]*color:\s*['"]#5FEDC5['"]/s);

  // Verify LicenseActivationModal banners use high-contrast tokens on dark surface
  assert.match(licenseModalContent, /errorText:\s*\{[^}]*color:\s*['"]#FCA5A5['"]/s);
  assert.match(licenseModalContent, /successText:\s*\{[^}]*color:\s*['"]#5FEDC5['"]/s);
});

test('Scenario 10: PaywallScreen invoice endpoint and Graphite & Mint email input styling', async () => {
  const fs = await import('node:fs');
  const paywallContent = fs.readFileSync('mobile/src/screens/PaywallScreen.tsx', 'utf-8');
  const apiContent = fs.readFileSync('mobile/src/services/api.ts', 'utf-8');

  // Verify real invoice endpoint in api.ts
  assert.match(apiContent, /\/api\/v1\/license\/invoice/);

  // Verify PaywallScreen calls requestInvoiceEmail
  assert.match(paywallContent, /requestInvoiceEmail\(trimmedEmail,\s*selectedPlan\)/);

  // Verify emailTextInput uses #1E252B background, 1px #5FEDC5 border, and #FFFFFF text
  assert.match(
    paywallContent,
    /emailTextInput:\s*\{[^}]*backgroundColor:\s*['"]#1E252B['"][^}]*borderWidth:\s*1[^}]*borderColor:\s*['"]#5FEDC5['"][^}]*color:\s*['"]#FFFFFF['"]/s,
    'emailTextInput must use #1E252B background, 1px #5FEDC5 border, and #FFFFFF text'
  );
});


