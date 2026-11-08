const { withAndroidManifest } = require('@expo/config-plugins');

/**
 * Expo Config Plugin to control android:usesCleartextTraffic on <application>.
 *
 * Strictly enables cleartext HTTP ONLY when EAS_BUILD_PROFILE === 'development'
 * (for local LAN debugging). All preview/production builds enforce HTTPS-only.
 */
module.exports = function withCleartextTraffic(config) {
  const isDevelopmentProfile = process.env.EAS_BUILD_PROFILE === 'development';

  return withAndroidManifest(config, (modConfig) => {
    const androidManifest = modConfig.modResults;
    if (androidManifest?.manifest?.application?.[0]) {
      androidManifest.manifest.application[0].$['android:usesCleartextTraffic'] =
        isDevelopmentProfile ? 'true' : 'false';
    }
    return modConfig;
  });
};
