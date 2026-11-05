import React from 'react';
import { View, Image, StyleSheet } from 'react-native';

interface BrandLogoProps {
  height?: number;
  style?: any;
  tintColor?: string;
}

/**
 * TarkApp Brand Logo Component.
 * Displays the authentic brand wordmark directly from the official brand identity.
 */
export const BrandLogo: React.FC<BrandLogoProps> = ({
  height = 25,
  style,
  tintColor = '#064E3B',
}) => {
  // Original asset aspect ratio: 250 / 60 = 4.1667
  const width = Math.round(height * (250 / 60));

  return (
    <View
      style={[styles.container, style]}
      accessible
      accessibilityRole="header"
      accessibilityLabel="TarkApp"
    >
      <Image
        source={require('../../assets/tarkapp_logo.png')}
        style={[{ width, height }, tintColor ? { tintColor } : null]}
        resizeMode="contain"
      />
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    justifyContent: 'center',
    alignItems: 'flex-start',
  },
});

export default BrandLogo;
