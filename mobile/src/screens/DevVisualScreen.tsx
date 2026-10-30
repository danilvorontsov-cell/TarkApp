import React, { useState } from 'react';
import {
  StyleSheet,
  View,
  Text,
  TouchableOpacity,
  ScrollView,
  SafeAreaView,
} from 'react-native';
import { TaskVisualizer } from '../components/TaskVisualizer';
import {
  VisualData,
  MathBlocksVisual,
  MatchPairsVisual,
  StepSequenceVisual,
  BalanceScaleVisual,
  UniversalCardVisual,
} from '../types/visual';

interface DevVisualScreenProps {
  onBack: () => void;
}

type TemplateType = 'math_blocks' | 'match_pairs' | 'step_sequence' | 'balance_scale' | 'universal_card';

export const DevVisualScreen: React.FC<DevVisualScreenProps> = ({ onBack }) => {
  const [selectedGrade, setSelectedGrade] = useState<number>(2);
  const [selectedTemplate, setSelectedTemplate] = useState<TemplateType>('math_blocks');
  const [refreshKey, setRefreshKey] = useState<number>(0);

  // Sample data for all 5 templates
  const samples: Record<TemplateType, VisualData> = {
    math_blocks: {
      type: 'math_blocks',
      title: 'Сложение слагаемых (Liidetavad ja summa)',
      instruction: 'Нажимай на кубики, чтобы наглядно сложить группы предметов:',
      groups: [
        {
          label: 'Esimene liidetav (5)',
          count: 5,
          color: '#3B82F6',
          item_label: 'кубик',
          symbol: '🟦',
        },
        {
          label: 'Teine liidetav (3)',
          count: 3,
          color: '#10B981',
          item_label: 'кубик',
          symbol: '🟩',
        },
      ],
      operation: '+',
      target_count: 8,
    } as MathBlocksVisual,

    match_pairs: {
      type: 'match_pairs',
      title: 'Соедини эстонские и русские термины',
      instruction: 'Выбери слово слева, затем найди его перевод справа:',
      pairs: [
        { id: '1', left: 'liidetav', right: 'слагаемое' },
        { id: '2', left: 'summa', right: 'сумма' },
        { id: '3', left: 'arvutama', right: 'вычислять' },
        { id: '4', left: 'võrduma', right: 'равняться' },
      ],
    } as MatchPairsVisual,

    step_sequence: {
      type: 'step_sequence',
      title: 'Этапы фотосинтеза (Fotosünteesi etapid)',
      instruction: 'Отмечай шаги по порядку выполнения:',
      steps: [
        {
          step_number: 1,
          title: 'Valgusenergia neeldumine',
          description: 'Хлоропласты листа поглощают солнечную энергию',
          icon_or_badge: '☀️',
          is_highlighted: true,
        },
        {
          step_number: 2,
          title: 'Vee ja süsihappegaasi omastamine',
          description: 'Корни впитывают воду, а устьица листьев — углекислый газ',
          icon_or_badge: '💧',
        },
        {
          step_number: 3,
          title: 'Glükoosi ja hapniku teke',
          description: 'Образуется сахар для питания растения и выделяется кислород в воздух',
          icon_or_badge: '🌿',
        },
      ],
    } as StepSequenceVisual,

    balance_scale: {
      type: 'balance_scale',
      title: 'Интерактивные весы: Сравнение выражений',
      instruction: 'Сравни величины на чашах весов и определи знак:',
      left_side: {
        label: 'Чаша A: 4 + 4',
        value: '8',
      },
      right_side: {
        label: 'Чаша B: 6 + 3',
        value: '9',
      },
      comparison: '?',
      hint: '8 меньше 9, поэтому правая чаша тяжелее и опустится вниз.',
    } as BalanceScaleVisual,

    universal_card: {
      type: 'universal_card',
      title: 'Переместительный закон сложения',
      icon: '💡',
      badge: 'ПРАВИЛО МАТЕМАТИКИ',
      highlight_text: 'a + b = b + a',
      explanation: 'От перемены мест слагаемых значение суммы не меняется! (Liidetavate kohtade vahetamisel summa ei muutu).',
      accent_color: '#5FEDC5',
    } as UniversalCardVisual,
  };

  const handleReset = () => {
    setRefreshKey((k) => k + 1);
  };

  const currentVisual = samples[selectedTemplate];
  const isSeniorBlocked = selectedGrade >= 7;

  return (
    <SafeAreaView style={styles.safeRoot}>
      {/* Header */}
      <View style={styles.topBar}>
        <TouchableOpacity style={styles.backButton} onPress={onBack} activeOpacity={0.7}>
          <Text style={styles.backButtonText}>← Назад</Text>
        </TouchableOpacity>
        <Text style={styles.topBarTitle}>Интерактивные шаблоны</Text>
        <TouchableOpacity style={styles.reloadBtn} onPress={handleReset} activeOpacity={0.7}>
          <Text style={styles.reloadBtnText}>🔄</Text>
        </TouchableOpacity>
      </View>

      <ScrollView contentContainerStyle={styles.scrollContent} showsVerticalScrollIndicator={false}>
        {/* Section: Grade Selector */}
        <Text style={styles.sectionLabel}>ВЫБОР КЛАССА ОБУЧЕНИЯ (ПЕДАГОГИЧЕСКИЙ РЕЖИМ):</Text>
        <View style={styles.chipsRow}>
          {[
            { grade: 2, label: '2 класс', sub: '1–4 мл. (Junior)' },
            { grade: 5, label: '5 класс', sub: '5–6 ср. I (Инфографика)' },
            { grade: 8, label: '8 класс', sub: '7+ ст. (Отключено)' },
          ].map((item) => {
            const isSelected = selectedGrade === item.grade;
            return (
              <TouchableOpacity
                key={item.grade}
                style={[styles.gradeChip, isSelected && styles.gradeChipSelected]}
                onPress={() => setSelectedGrade(item.grade)}
                activeOpacity={0.8}
              >
                <Text style={[styles.gradeChipTitle, isSelected && styles.chipTextSelected]}>
                  {item.label}
                </Text>
                <Text style={[styles.gradeChipSub, isSelected && styles.chipSubSelected]}>
                  {item.sub}
                </Text>
              </TouchableOpacity>
            );
          })}
        </View>

        {/* Section: Template Selector */}
        <Text style={styles.sectionLabel}>ТИПЫ ИНТЕРАКТИВНЫХ ШАБЛОНОВ (UI-ПРИМИТИВЫ):</Text>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.templatesScroll}>
          {[
            { id: 'math_blocks', icon: '🧱', name: 'MathBlocks' },
            { id: 'match_pairs', icon: '🧩', name: 'MatchPairs' },
            { id: 'step_sequence', icon: '🚀', name: 'StepSequence' },
            { id: 'balance_scale', icon: '⚖️', name: 'BalanceScale' },
            { id: 'universal_card', icon: '💡', name: 'UniversalCard' },
          ].map((t) => {
            const isSelected = selectedTemplate === t.id;
            return (
              <TouchableOpacity
                key={t.id}
                style={[styles.templateChip, isSelected && styles.templateChipSelected]}
                onPress={() => setSelectedTemplate(t.id as TemplateType)}
                activeOpacity={0.8}
              >
                <Text style={styles.templateChipIcon}>{t.icon}</Text>
                <Text style={[styles.templateChipName, isSelected && styles.chipTextSelected]}>
                  {t.name}
                </Text>
              </TouchableOpacity>
            );
          })}
        </ScrollView>

        {/* Live Preview Area */}
        <View style={styles.previewContainer}>
          <View style={styles.previewHeader}>
            <Text style={styles.previewBadge}>ПРЕДПРОСМОТР В РЕАЛЬНОМ ВРЕМЕНИ</Text>
            <Text style={styles.previewGradeIndicator}>
              {selectedGrade <= 4 ? '🎨 Junior стиль' : selectedGrade <= 6 ? '📊 Инфографика' : '🚫 Отключено'}
            </Text>
          </View>

          {isSeniorBlocked ? (
            <View style={styles.blockedNoticeBox}>
              <Text style={styles.blockedIcon}>🛡️</Text>
              <Text style={styles.blockedTitle}>Шаблоны отключены для 7–12 классов</Text>
              <Text style={styles.blockedDesc}>
                Согласно педагогическому регламенту TarkApp, для учеников старшего звена (7–9 кл.)
                и гимназии (10–12 кл.) интерактивные визуальные шаблоны и анимации полностью
                отключаются — в разборе отображается только четкий структурированный конспект.
              </Text>
            </View>
          ) : (
            <TaskVisualizer
              key={`${selectedTemplate}_${selectedGrade}_${refreshKey}`}
              visual={currentVisual}
              grade={selectedGrade}
            />
          )}
        </View>

        {/* Pedagogical Description Note */}
        <View style={styles.pedagogicalCard}>
          <Text style={styles.pedagogicalTitle}>💡 Назначение шаблона в программе:</Text>
          <Text style={styles.pedagogicalText}>
            {selectedTemplate === 'math_blocks' &&
              'Счетные кубики и жетоны (1–4 классы). Помогают визуализировать арифметические действия (сложение, вычитание, группы умножения) и снимают страх абстрактных чисел.'}
            {selectedTemplate === 'match_pairs' &&
              'Сопоставление пар терминов (1–6 классы). Незаменимо для адаптации русскоязычных детей в эстонской школе: связывает эстонское академическое слово с понятным русским смыслом.'}
            {selectedTemplate === 'step_sequence' &&
              'Интерактивная цепочка шагов (1–6 классы). Обучает алгоритмическому мышлению, правильному порядку действий в математике и циклам в природоведении (loodusõpetus).'}
            {selectedTemplate === 'balance_scale' &&
              'Интерактивные весы (1–5 классы). Позволяют тактильно почувствовать знак равенства (=) и неравенства (<, >), подготавливая ребенка к уравнениям.'}
            {selectedTemplate === 'universal_card' &&
              'Фокусная карточка правила (1–6 классы). Акцентирует внимание на ключевом законе, формуле или правиле урока без перегрузки лишним текстом.'}
          </Text>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
};

const styles = StyleSheet.create({
  safeRoot: {
    flex: 1,
    backgroundColor: '#0B0F17',
  },
  topBar: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: '#1E293B',
  },
  backButton: {
    backgroundColor: '#1E293B',
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 8,
  },
  backButtonText: {
    color: '#5FEDC5',
    fontSize: 14,
    fontWeight: '600',
  },
  topBarTitle: {
    color: '#F8FAFC',
    fontSize: 16,
    fontWeight: '700',
  },
  reloadBtn: {
    padding: 6,
  },
  reloadBtnText: {
    fontSize: 18,
  },
  scrollContent: {
    padding: 16,
    paddingBottom: 40,
  },
  sectionLabel: {
    fontSize: 11,
    fontWeight: '700',
    color: '#64748B',
    marginBottom: 8,
    marginTop: 10,
    letterSpacing: 0.5,
  },
  chipsRow: {
    flexDirection: 'row',
    gap: 8,
    marginBottom: 12,
  },
  gradeChip: {
    flex: 1,
    backgroundColor: '#161F30',
    borderWidth: 1.5,
    borderColor: '#2A354D',
    borderRadius: 12,
    padding: 10,
    alignItems: 'center',
  },
  gradeChipSelected: {
    borderColor: '#5FEDC5',
    backgroundColor: '#0F766E25',
  },
  gradeChipTitle: {
    color: '#E2E8F0',
    fontSize: 14,
    fontWeight: '700',
  },
  gradeChipSub: {
    color: '#94A3B8',
    fontSize: 10,
    marginTop: 2,
    textAlign: 'center',
  },
  chipTextSelected: {
    color: '#5FEDC5',
  },
  chipSubSelected: {
    color: '#A7F3D0',
  },
  templatesScroll: {
    flexDirection: 'row',
    marginBottom: 16,
  },
  templateChip: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#161F30',
    borderWidth: 1.5,
    borderColor: '#2A354D',
    borderRadius: 12,
    paddingHorizontal: 12,
    paddingVertical: 8,
    marginRight: 8,
  },
  templateChipSelected: {
    borderColor: '#3B82F6',
    backgroundColor: '#1E3A8A30',
  },
  templateChipIcon: {
    fontSize: 16,
    marginRight: 6,
  },
  templateChipName: {
    color: '#E2E8F0',
    fontSize: 13,
    fontWeight: '600',
  },
  previewContainer: {
    marginTop: 6,
    marginBottom: 16,
  },
  previewHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 6,
  },
  previewBadge: {
    color: '#64748B',
    fontSize: 10,
    fontWeight: '800',
    letterSpacing: 0.5,
  },
  previewGradeIndicator: {
    color: '#94A3B8',
    fontSize: 12,
    fontWeight: '600',
  },
  blockedNoticeBox: {
    backgroundColor: '#161F30',
    borderWidth: 1.5,
    borderColor: '#475569',
    borderRadius: 16,
    padding: 20,
    alignItems: 'center',
    marginVertical: 12,
  },
  blockedIcon: {
    fontSize: 36,
    marginBottom: 10,
  },
  blockedTitle: {
    color: '#F8FAFC',
    fontSize: 16,
    fontWeight: '700',
    marginBottom: 8,
    textAlign: 'center',
  },
  blockedDesc: {
    color: '#94A3B8',
    fontSize: 13,
    lineHeight: 19,
    textAlign: 'center',
  },
  pedagogicalCard: {
    backgroundColor: '#111827',
    borderWidth: 1,
    borderColor: '#1F2937',
    borderRadius: 12,
    padding: 14,
  },
  pedagogicalTitle: {
    color: '#F1F5F9',
    fontSize: 13,
    fontWeight: '700',
    marginBottom: 6,
  },
  pedagogicalText: {
    color: '#9CA3AF',
    fontSize: 12,
    lineHeight: 18,
  },
});
