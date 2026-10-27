import React, { Component, ErrorInfo, ReactNode } from 'react';
import {
  StyleSheet,
  View,
  Text,
  TouchableOpacity,
  SafeAreaView,
  StatusBar,
} from 'react-native';
import { captureException } from '../services/sentry';

interface Props {
  children: ReactNode;
  onReset?: () => void;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  public state: State = {
    hasError: false,
    error: null,
  };

  public static getDerivedStateFromError(error: Error): State {
    return {
      hasError: true,
      error,
    };
  }

  public componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    console.error('[ErrorBoundary] Uncaught rendering exception:', error, errorInfo);
    captureException(error, {
      componentStack: errorInfo.componentStack,
    });
  }

  private handleReset = (): void => {
    this.setState({
      hasError: false,
      error: null,
    });
    if (this.props.onReset) {
      this.props.onReset();
    }
  };

  public render(): ReactNode {
    if (this.state.hasError) {
      return (
        <SafeAreaView style={styles.safeArea}>
          <StatusBar barStyle="dark-content" />
          <View style={styles.container}>
            <View style={styles.card}>
              <View style={styles.iconCircle}>
                <Text style={styles.iconText}>🛠️</Text>
              </View>

              <Text style={styles.title}>Что-то пошло не так</Text>

              <Text style={styles.description}>
                Мы уже сохранили отчет об ошибке. Нажмите кнопку, чтобы вернуться на главный экран.
              </Text>

              {__DEV__ && this.state.error?.message && (
                <View style={styles.devErrorBox}>
                  <Text style={styles.devErrorText} numberOfLines={3}>
                    {this.state.error.message}
                  </Text>
                </View>
              )}

              <TouchableOpacity
                style={styles.resetButton}
                activeOpacity={0.85}
                onPress={this.handleReset}
              >
                <Text style={styles.resetButtonText}>Перезапустить разбор</Text>
              </TouchableOpacity>
            </View>
          </View>
        </SafeAreaView>
      );
    }

    return this.props.children;
  }
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: '#F8FAFC',
  },
  container: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: 24,
    backgroundColor: '#F8FAFC',
  },
  card: {
    width: '100%',
    maxWidth: 420,
    backgroundColor: '#FFFFFF',
    borderRadius: 24,
    paddingVertical: 36,
    paddingHorizontal: 24,
    alignItems: 'center',
    shadowColor: '#0F172A',
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.08,
    shadowRadius: 18,
    elevation: 4,
    borderWidth: 1,
    borderColor: '#E2E8F0',
  },
  iconCircle: {
    width: 88,
    height: 88,
    borderRadius: 44,
    backgroundColor: '#EEF2FF',
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 20,
    borderWidth: 2,
    borderColor: '#E0E7FF',
  },
  iconText: {
    fontSize: 44,
  },
  title: {
    fontSize: 22,
    fontWeight: '800',
    color: '#1E293B',
    textAlign: 'center',
    marginBottom: 12,
  },
  description: {
    fontSize: 15,
    lineHeight: 22,
    color: '#64748B',
    textAlign: 'center',
    marginBottom: 26,
    paddingHorizontal: 12,
  },
  devErrorBox: {
    width: '100%',
    backgroundColor: '#FEF2F2',
    borderWidth: 1,
    borderColor: '#FECACA',
    borderRadius: 10,
    padding: 10,
    marginBottom: 20,
  },
  devErrorText: {
    fontSize: 12,
    color: '#DC2626',
    fontFamily: 'monospace',
    textAlign: 'center',
  },
  resetButton: {
    backgroundColor: '#059669',
    paddingVertical: 14,
    paddingHorizontal: 32,
    borderRadius: 14,
    width: '100%',
    alignItems: 'center',
    shadowColor: '#059669',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.25,
    shadowRadius: 8,
    elevation: 3,
  },
  resetButtonText: {
    color: '#FFFFFF',
    fontSize: 16,
    fontWeight: '700',
    letterSpacing: 0.3,
  },
});
