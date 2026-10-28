import React from 'react';
import {
  StyleSheet,
  View,
  Text,
  TouchableOpacity,
  Modal,
  TouchableWithoutFeedback,
  Dimensions,
} from 'react-native';
import { Theme, darkTheme } from '../theme/colors';

const { width: SCREEN_WIDTH } = Dimensions.get('window');
const MODAL_WIDTH = Math.min(SCREEN_WIDTH * 0.88, 340);

interface AvatarPickerModalProps {
  visible: boolean;
  onClose: () => void;
  onTakePhoto: () => void;
  onPickGallery: () => void;
  onRemovePhoto?: () => void;
  hasExistingPhoto?: boolean;
}

export const AvatarPickerModal: React.FC<AvatarPickerModalProps> = ({
  visible,
  onClose,
  onTakePhoto,
  onPickGallery,
  onRemovePhoto,
  hasExistingPhoto = false,
}) => {
  return (
    <Modal
      visible={visible}
      transparent
      animationType="fade"
      onRequestClose={onClose}
    >
      <TouchableWithoutFeedback onPress={onClose}>
        <View style={styles.backdrop}>
          <TouchableWithoutFeedback>
            <View style={styles.card}>
              {/* Close Cross Button in Corner */}
              <TouchableOpacity
                style={styles.closeBtn}
                onPress={onClose}
                hitSlop={{ top: 12, bottom: 12, left: 12, right: 12 }}
                accessibilityLabel="Закрыть"
              >
                <Text style={styles.closeBtnText}>✕</Text>
              </TouchableOpacity>

              {/* Decorative Centered Camera Icon */}
              <View style={styles.iconCircle}>
                <Text style={styles.iconEmoji}>📷</Text>
              </View>

              {/* Centered Title */}
              <Text style={styles.title}>Фото профиля</Text>

              {/* Centered Subtitle */}
              <Text style={styles.subtitle}>
                Выбери способ обновления аватарки:
              </Text>

              {/* Buttons Container (Centered) */}
              <View style={styles.buttonsContainer}>
                {/* 1. Camera Button (Solid Onsen Green) */}
                <TouchableOpacity
                  style={[styles.actionBtn, styles.btnPrimary]}
                  onPress={() => {
                    onClose();
                    onTakePhoto();
                  }}
                  activeOpacity={0.85}
                >
                  <Text style={styles.btnPrimaryText}>📸  Сделать снимок</Text>
                </TouchableOpacity>

                {/* 2. Gallery Button (Mint Tint Green) */}
                <TouchableOpacity
                  style={[styles.actionBtn, styles.btnSecondary]}
                  onPress={() => {
                    onClose();
                    onPickGallery();
                  }}
                  activeOpacity={0.85}
                >
                  <Text style={styles.btnSecondaryText}>🖼️  Выбрать из галереи</Text>
                </TouchableOpacity>

                {/* 3. Delete Photo Button (Optional) */}
                {hasExistingPhoto && onRemovePhoto && (
                  <TouchableOpacity
                    style={[styles.actionBtn, styles.btnDanger]}
                    onPress={() => {
                      onClose();
                      onRemovePhoto();
                    }}
                    activeOpacity={0.85}
                  >
                    <Text style={styles.btnDangerText}>🗑️  Удалить фото</Text>
                  </TouchableOpacity>
                )}

                {/* 4. Cancel Button */}
                <TouchableOpacity
                  style={styles.cancelBtn}
                  onPress={onClose}
                  activeOpacity={0.7}
                >
                  <Text style={styles.cancelBtnText}>Отмена</Text>
                </TouchableOpacity>
              </View>
            </View>
          </TouchableWithoutFeedback>
        </View>
      </TouchableWithoutFeedback>
    </Modal>
  );
};

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: 'rgba(15, 23, 42, 0.48)',
    justifyContent: 'center',
    alignItems: 'center',
    padding: 20,
  },
  card: {
    width: MODAL_WIDTH,
    backgroundColor: darkTheme.cardBackground,
    borderRadius: 20,
    paddingHorizontal: 22,
    paddingTop: 24,
    paddingBottom: 18,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: darkTheme.cardBorder,
    position: 'relative',
    ...Theme.shadow.modal,
  },
  closeBtn: {
    position: 'absolute',
    top: 14,
    right: 14,
    width: 30,
    height: 30,
    borderRadius: 15,
    backgroundColor: darkTheme.badgeFreeBg,
    justifyContent: 'center',
    alignItems: 'center',
  },
  closeBtnText: {
    fontSize: 14,
    fontWeight: '700',
    color: darkTheme.textSecondary,
  },
  iconCircle: {
    width: 60,
    height: 60,
    borderRadius: 30,
    backgroundColor: darkTheme.accent,
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 12,
    borderWidth: 2,
    borderColor: darkTheme.cardBorder,
    ...Theme.shadow.chip,
  },
  iconEmoji: {
    fontSize: 28,
  },
  title: {
    fontSize: 20,
    fontWeight: '800',
    color: darkTheme.textPrimary,
    textAlign: 'center',
    letterSpacing: -0.3,
  },
  subtitle: {
    fontSize: 13.5,
    fontWeight: '500',
    color: darkTheme.textSecondary,
    textAlign: 'center',
    marginTop: 4,
    marginBottom: 20,
  },
  buttonsContainer: {
    width: '100%',
    alignItems: 'center',
  },
  actionBtn: {
    width: '100%',
    paddingVertical: 13,
    paddingHorizontal: 16,
    borderRadius: 16,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 10,
  },
  btnPrimary: {
    backgroundColor: '#5FEDC5',
    ...Theme.shadow.button,
  },
  btnPrimaryText: {
    fontSize: 15,
    fontWeight: '800',
    color: '#064E3B',
  },
  btnSecondary: {
    backgroundColor: 'rgba(95, 237, 197, 0.14)',
    borderWidth: 1.5,
    borderColor: '#5FEDC5',
  },
  btnSecondaryText: {
    fontSize: 15,
    fontWeight: '700',
    color: '#5FEDC5',
  },
  btnDanger: {
    backgroundColor: Theme.colors.dangerBg,
    borderWidth: 1,
    borderColor: '#EF4444',
  },
  btnDangerText: {
    fontSize: 14,
    fontWeight: '700',
    color: '#FCA5A5',
  },
  cancelBtn: {
    paddingVertical: 8,
    paddingHorizontal: 16,
    marginTop: 2,
    alignItems: 'center',
    justifyContent: 'center',
  },
  cancelBtnText: {
    fontSize: 14,
    fontWeight: '600',
    color: '#94A3B8',
  },
});
