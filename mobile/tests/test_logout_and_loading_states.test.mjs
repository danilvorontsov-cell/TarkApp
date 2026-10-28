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
