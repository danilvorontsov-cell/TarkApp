const { withAndroidManifest } = require('@expo/config-plugins');

/**
 * Expo Config Plugin to ensure android:usesCleartextTraffic="true"
 * is set on the AndroidManifest.xml <application> tag.
 * 
 * This allows the APK to communicate with local development servers
 * over plain HTTP (e.g. http://10.253.79.137:8080 or http://192.168.x.x:8080)
 * without being blocked by Android 9+ default cleartext restrictions.
 */
module.exports = function withCleartextTraffic(config) {
  return withAndroidManifest(config, (modConfig) => {
    const androidManifest = modConfig.modResults;
    if (androidManifest?.manifest?.application?.[0]) {
      androidManifest.manifest.application[0].$['android:usesCleartextTraffic'] = 'true';
    }
    return modConfig;
  });
};
