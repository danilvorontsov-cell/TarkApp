import test from 'node:test';
import assert from 'node:assert/strict';

// Mock Storage Engines for Unit Testing Migration Behavior
class MockStorageEngine {
  constructor() {
    this.store = new Map();
  }

  async getItem(key) {
    return this.store.get(key) || null;
  }

  async setItem(key, value) {
    this.store.set(key, String(value));
  }

  async removeItem(key) {
    this.store.delete(key);
  }

  clear() {
    this.store.clear();
  }
}

// Emulate the exact getDeviceId() algorithm from mobile/src/services/api.ts
async function createDeviceIdManager({ mockSecureStore, mockAsyncStorage, mockHardwareId = null }) {
  let cachedDeviceId = null;
  const SECURE_DEVICE_ID_KEY = 'tarkapp_device_id';

  function resetCache() {
    cachedDeviceId = null;
  }

  async function getDeviceId() {
    if (cachedDeviceId) {
      return cachedDeviceId;
    }

    // 1. Try reading from hardware-backed SecureStore (survives app reinstallation on iOS)
    try {
      const secureId = await mockSecureStore.getItem(SECURE_DEVICE_ID_KEY);
      if (secureId && secureId.trim()) {
        cachedDeviceId = secureId.trim();
        return cachedDeviceId;
      }
    } catch (err) {
      console.warn('[SecureStore] Failed to read device ID:', err);
    }

    // 2. Migration fallback: check AsyncStorage if upgrading from older build
    try {
      const saved = await mockAsyncStorage.getItem('@tarkapp_device_id');
      if (saved && saved.trim()) {
        cachedDeviceId = saved.trim();
        // Migrate forward to SecureStore
        try {
          await mockSecureStore.setItem(SECURE_DEVICE_ID_KEY, cachedDeviceId);
        } catch {}
        return cachedDeviceId;
      }
    } catch {}

    // 3. Hardware identifiers
    let hardwareId = mockHardwareId;

    // 4. Crypto-random fallback if hardware id is inaccessible
    if (!hardwareId || !hardwareId.trim()) {
      hardwareId = `dev_test_${Date.now()}`;
    }

    cachedDeviceId = hardwareId.trim();

    // Persist to both SecureStore and AsyncStorage
    try {
      await mockSecureStore.setItem(SECURE_DEVICE_ID_KEY, cachedDeviceId);
    } catch {}

    try {
      await mockAsyncStorage.setItem('@tarkapp_device_id', cachedDeviceId);
    } catch {}

    return cachedDeviceId;
  }

  return { getDeviceId, resetCache };
}

test('Scenario 1: Seamless migration from legacy AsyncStorage to SecureStore without ID loss', async () => {
  const mockSecureStore = new MockStorageEngine();
  const mockAsyncStorage = new MockStorageEngine();

  const legacyDeviceId = 'legacy-user-uuid-98765-abcde';

  // Pre-condition: Device ID exists ONLY in AsyncStorage (older app release)
  await mockAsyncStorage.setItem('@tarkapp_device_id', legacyDeviceId);
  assert.equal(await mockSecureStore.getItem('tarkapp_device_id'), null);

  const manager = await createDeviceIdManager({ mockSecureStore, mockAsyncStorage });

  // Act: Call getDeviceId()
  const retrievedId = await manager.getDeviceId();

  // Assert: Exact legacy ID is returned (no regeneration or mutation)
  assert.equal(retrievedId, legacyDeviceId);

  // Assert: Legacy ID was seamlessly migrated forward into SecureStore
  const migratedSecureId = await mockSecureStore.getItem('tarkapp_device_id');
  assert.equal(migratedSecureId, legacyDeviceId);
});

test('Scenario 2: Device ID persists in SecureStore across app data reset / reinstallation', async () => {
  const mockSecureStore = new MockStorageEngine();
  const mockAsyncStorage = new MockStorageEngine();

  const existingSecureId = 'secure-keychain-device-id-55555';

  // Pre-condition: iOS Keychain (SecureStore) retained ID, but AsyncStorage was wiped clean (app reinstalled)
  await mockSecureStore.setItem('tarkapp_device_id', existingSecureId);
  assert.equal(await mockAsyncStorage.getItem('@tarkapp_device_id'), null);

  const manager = await createDeviceIdManager({ mockSecureStore, mockAsyncStorage });

  const retrievedId = await manager.getDeviceId();

  // Assert: SecureStore ID takes priority, protecting user 5 free reviews quota from abuse
  assert.equal(retrievedId, existingSecureId);
});

test('Scenario 3: New device generation persists to both stores concurrently', async () => {
  const mockSecureStore = new MockStorageEngine();
  const mockAsyncStorage = new MockStorageEngine();

  // Pre-condition: Empty stores (brand new fresh install)
  const manager = await createDeviceIdManager({
    mockSecureStore,
    mockAsyncStorage,
    mockHardwareId: 'android-hw-id-112233',
  });

  const generatedId = await manager.getDeviceId();
  assert.equal(generatedId, 'android-hw-id-112233');

  // Both stores must now have the exact same ID
  assert.equal(await mockSecureStore.getItem('tarkapp_device_id'), 'android-hw-id-112233');
  assert.equal(await mockAsyncStorage.getItem('@tarkapp_device_id'), 'android-hw-id-112233');
});

test('Scenario 4: Idempotency - repeated and concurrent calls return consistent ID without duplicate keys', async () => {
  const mockSecureStore = new MockStorageEngine();
  const mockAsyncStorage = new MockStorageEngine();

  const manager = await createDeviceIdManager({
    mockSecureStore,
    mockAsyncStorage,
    mockHardwareId: 'consistent-id-777',
  });

  const [id1, id2, id3] = await Promise.all([
    manager.getDeviceId(),
    manager.getDeviceId(),
    manager.getDeviceId(),
  ]);

  assert.equal(id1, 'consistent-id-777');
  assert.equal(id2, 'consistent-id-777');
  assert.equal(id3, 'consistent-id-777');

  // Clear memory cache and re-read from storage
  manager.resetCache();
  const idAfterReset = await manager.getDeviceId();
  assert.equal(idAfterReset, 'consistent-id-777');
});
