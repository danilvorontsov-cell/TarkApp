import json
import logging
import re
from typing import List, Optional, Tuple

from google import genai
from google.genai import types
from google.genai.errors import APIError

from app.config import settings
from app.models.page_analysis import (
    AgeTier,
    AGE_TIER_DEFAULT_INTERESTS,
    MathBlockGroup,
    MathBlocksVisual,
    MoreExamplesResponse,
    PageAnalysisResponse,
    StepSequenceItem,
    StepSequenceVisual,
    UserProfile,
    VocabularyItem,
    WorkedExample,
)
from app.models.translate import QuickTranslateResponse
from app.prompts.tutor_prompt import (
    ESTONIAN_TUTOR_SYSTEM_PROMPT,
    build_tutor_user_prompt,
)

logger = logging.getLogger(__name__)


class GeminiTutorService:
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.model = model or settings.GEMINI_MODEL
        self._client: Optional[genai.Client] = None

    @property
    def client(self) -> Optional[genai.Client]:
        if self._client is None and self._is_valid_key(self.api_key):
            try:
                self._client = genai.Client(api_key=self.api_key)
                logger.info(f"Initialized Google GenAI client with model: {self.model}")
            except Exception as e:
                logger.warning(f"Failed to initialize GenAI client: {e}. Will use mock mode.")
        return self._client

    @staticmethod
    def _is_valid_key(key: Optional[str]) -> bool:
        if not key:
            return False
        clean = key.strip()
        if clean in ("", "your_gemini_api_key_here", "mock", "test", "none"):
            return False
        return len(clean) >= 10

    async def analyze_page(
        self,
        image_bytes: Optional[bytes] = None,
        mime_type: str = "image/jpeg",
        profile: UserProfile = None,
        images: Optional[List[Tuple[bytes, str]]] = None,
    ) -> PageAnalysisResponse:
        """Analyzes one or multiple textbook/workbook page images using Gemini Vision and adapts it to the student."""
        # Use mock mode if client is not configured
        if not self.client:
            logger.info("Using pedagogical fallback generator (mock mode)")
            return self._generate_mock_adaptation(profile)

        img_list: List[Tuple[bytes, str]] = []
        if images and len(images) > 0:
            img_list = images
        elif image_bytes:
            img_list = [(image_bytes, mime_type)]
        else:
            raise ValueError("No images provided for analysis")

        user_prompt = build_tutor_user_prompt(profile)
        if len(img_list) > 1:
            user_prompt += (
                f"\n\n[ВАЖНО ДЛЯ АНАЛИЗА: Ученик прикрепил {len(img_list)} страницы/фото учебных материалов "
                f"(например, разворот учебника или теорию и тетрадь с упражнением). "
                f"Объедини их общий контекст, найди связь между теорией и заданиями, "
                f"выдели главную тему урока и разбери задания со всех страниц!]"
            )

        # Call Google GenAI SDK with structured response schema and 1 automatic retry
        image_parts = [
            types.Part.from_bytes(data=ib, mime_type=mt)
            for ib, mt in img_list
        ]
        contents = [
            *image_parts,
            user_prompt,
        ]

        last_err: Optional[Exception] = None
        for attempt in range(2):
            try:
                config = types.GenerateContentConfig(
                    system_instruction=ESTONIAN_TUTOR_SYSTEM_PROMPT,
                    response_mime_type="application/json",
                    response_schema=PageAnalysisResponse,
                    temperature=0.2 if attempt == 0 else 0.1,
                )

                response = await self.client.aio.models.generate_content(
                    model=self.model,
                    contents=contents,
                    config=config,
                )

                # Check if response.parsed was populated by the SDK
                if hasattr(response, "parsed") and isinstance(response.parsed, PageAnalysisResponse):
                    result = response.parsed
                else:
                    # Otherwise parse response.text
                    raw_text = response.text or ""
                    result = self._parse_json_response(raw_text)

                # Strict rule: for grades 7+, visual templates and animations are completely disabled
                if profile and profile.grade >= 7:
                    result.visual = None
                return result

            except APIError as e:
                logger.error(f"Gemini API error (attempt {attempt + 1}): {e}", exc_info=True)
                last_err = e
                if attempt == 0:
                    continue
                return self._generate_emergency_fallback(profile)

            except (ValueError, json.JSONDecodeError, Exception) as e:
                logger.warning(f"Error parsing Gemini response (attempt {attempt + 1}): {e}")
                last_err = e
                if attempt == 0:
                    continue
                logger.error(f"Both attempts failed in analyze_page: {last_err}. Using emergency fallback.")
                return self._generate_emergency_fallback(profile)

        return self._generate_emergency_fallback(profile)

    def _generate_emergency_fallback(self, profile: UserProfile) -> PageAnalysisResponse:
        """Safe emergency fallback when Gemini returns malformed response or API breaks."""
        nickname = profile.nickname or "Друг"
        return PageAnalysisResponse(
            task_title="Разбор учебного материала (Märge)",
            theme_explanation=(
                f"Привет, {nickname}! Мы получили твою фотографию, но из-за бликов или угла съёмки "
                "нейросеть не смогла надёжно распознать весь текст задания. "
                "Пожалуйста, сделай повторный снимок строго параллельно странице при хорошем освещении!"
            ),
            alternative_explanation=(
                "Совет: держи камеру ровно над учебником, чтобы все буквы и формулы были чёткими."
            ),
            vocabulary=[
                VocabularyItem(
                    est="õppima",
                    ru="учиться / изучать",
                    example="Me õpime iga päev midagi uut."
                ),
                VocabularyItem(
                    est="ülesanne",
                    ru="задание / упражнение",
                    example="Loe ülesande tekst hoolega läbi."
                ),
            ],
            worked_example=WorkedExample(
                title="Памятка по фотосъёмке учебника",
                given="Если страница получилась размытой",
                steps=[
                    "1. Включи хорошее освещение в комнате",
                    "2. Держи телефон ровно над страницей без наклона",
                    "3. Нажми кнопку 'Попробовать снова'"
                ],
                note="Чёткий снимок помогает разобрать урок за 2 секунды!"
            ),
            how_to_answer="Сделай чёткое фото страницы учебника при хорошем освещении и нажми кнопку 'Попробовать снова'.",
            answer_template="Ma loen [ülesannet] ja õpin [hoolega].",
            voice_prompt_script=f"Привет, {nickname}! Сфотографируй страницу ещё раз поровнее, и мы сразу разберём задание!",
            is_acceptable=False,
        )

    def _parse_json_response(self, text: str) -> PageAnalysisResponse:
        """Cleans and parses raw JSON response text into PageAnalysisResponse."""
        cleaned = text.strip()
        # Remove markdown code fences if present (```json ... ```)
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
            cleaned = cleaned.strip()

        try:
            return PageAnalysisResponse.model_validate_json(cleaned)
        except Exception as err:
            logger.error(f"Failed to parse JSON response: {cleaned}")
            # Try parsing with standard json and lenient key extraction
            try:
                data = json.loads(cleaned)
                return PageAnalysisResponse.model_validate(data)
            except Exception:
                raise ValueError(f"Ответ модели не соответствует схеме PageAnalysisResponse: {err}")

    def _generate_mock_adaptation(self, profile: UserProfile) -> PageAnalysisResponse:
        """Returns realistic Estonian school adaptation when running without live API key."""
        nickname = profile.nickname or "Друг"
        tier = profile.tier or AgeTier.from_grade(profile.grade)
        
        # Выбираем тему: из списка ученика (70%) либо из возрастного пула (30% / fallback)
        tier_pool = AGE_TIER_DEFAULT_INTERESTS.get(tier, ["LEGO", "игры"])
        if profile.interests:
            chosen_interest = profile.interests[0]
        else:
            chosen_interest = tier_pool[0]

        chosen_lower = chosen_interest.lower()

        # 1-4 классы (Младшее звено - математика / сложение)
        if tier == AgeTier.PRIMARY:
            if "minecraft" in chosen_lower:
                theme_expl = (
                    f"Привет, {nickname}! Представь, что мы крафтим факелы в Minecraft. "
                    "У тебя в одном слоте 9 палок, а в другом — 7 кусков угля. "
                    "В эстонском учебнике числа, которые мы складываем, называются 'liidetavad' (слагаемые). "
                    "Когда мы соединяем их на верстаке, получается общее количество — 'summa' (сумма)!"
                )
            elif "roblox" in chosen_lower:
                theme_expl = (
                    f"Привет, {nickname}! Представь, что ты проходишь обби в Roblox. "
                    "На первом чекпоинте ты собрал 9 звезд, а на втором — еще 7. "
                    "Каждое собранное число эстонцы называют 'liidetav'. "
                    "А все звезды вместе на твоем счетчике — это 'summa'!"
                )
            elif "спорт" in chosen_lower or "футбол" in chosen_lower or "sport" in chosen_lower:
                theme_expl = (
                    f"Привет, {nickname}! В первом тайме футбольного матча команда забила 2 мяча, "
                    "а во втором тайме — еще 3. Эти числа — слагаемые ('liidetavad'), "
                    "а финальный счет игры — это сумма ('summa')!"
                )
            elif "lego" in chosen_lower:
                theme_expl = (
                    f"Привет, {nickname}! Представь, что ты строишь замок из LEGO. "
                    "У тебя есть 9 синих деталей и 7 красных. "
                    "Каждую кучку деталей в эстонской школе называют 'liidetav' (слагаемое), "
                    "а вся твоя постройка целиком — это 'summa' (сумма)!"
                )
            else:
                theme_expl = (
                    f"Привет, {nickname}! Давай разберем это задание через твою любимую тему — {chosen_interest}! "
                    "Числа, которые мы соединяем вместе, в эстонской школе называют 'liidetav' (слагаемое), "
                    "а то, что получилось в итоге — 'summa' (сумма)."
                )

            return PageAnalysisResponse(
                task_title="Liitmine ja tehete komponendid (Сложение и компоненты действий)",
                theme_explanation=theme_expl,
                alternative_explanation=(
                    f"Или представь, что ты строишь замок из LEGO: "
                    "соединяешь 9 синих деталей и 7 красных. "
                    "Каждая кучка деталей — это 'liidetav' (слагаемое), а вся постройка целиком — это 'summa' (сумма)!"
                ),
                vocabulary=[
                    VocabularyItem(
                        est="liidetav",
                        ru="слагаемое (число, которое мы складываем)",
                        example="9 on esimene liidetav ja 7 on teine liidetav."
                    ),
                    VocabularyItem(
                        est="summa",
                        ru="сумма (результат сложения)",
                        example="Nende arvude summa on 16."
                    ),
                    VocabularyItem(
                        est="arvutama",
                        ru="вычислять / считать",
                        example="Arvuta tehete vastused."
                    ),
                    VocabularyItem(
                        est="võrduma",
                        ru="равняться / быть равным",
                        example="9 pluss 7 võrdub 16."
                    ),
                ],
                worked_example=WorkedExample(
                    title="Пример решения (Näidis)",
                    given="Например, в учебнике пример: 9 + 7 = ?",
                    steps=[
                        "1. Первое слагаемое: 9 (esimene liidetav)",
                        "2. Второе слагаемое: 7 (teine liidetav)",
                        "3. Складываем вместе: 9 + 7 = 16",
                        "4. Вывод: Сумма равна 16 (summa on 16)"
                    ],
                    note="По этому же образцу найди слагаемые и реши остальные примеры на странице!"
                ),
                how_to_answer=(
                    "1. Найди в примере первое число (esimene liidetav).\n"
                    "2. Прибавь к нему второе число (teine liidetav).\n"
                    "3. Запиши результат после знака равенства — это и будет summa.\n"
                    "4. Ответь учителю по эстонскому шаблону ниже."
                ),
                answer_template="Esimene liidetav on [liidetav], teine liidetav on [liidetav], summa on [summa].",
                voice_prompt_script=(
                    f"Привет, {nickname}! Не бойся задания. Мы разберем числа через {chosen_interest}. "
                    "Сложи числа и скажи: summa on, и назови свой ответ!"
                ),
                visual=MathBlocksVisual(
                    title="Сложение слагаемых (Liidetavad)",
                    instruction="Нажимай на кубики, чтобы наглядно сложить группы",
                    groups=[
                        MathBlockGroup(
                            label="Esimene liidetav (9)",
                            count=9,
                            color="#3B82F6",
                            item_label="кубик",
                            symbol="🟦"
                        ),
                        MathBlockGroup(
                            label="Teine liidetav (7)",
                            count=7,
                            color="#10B981",
                            item_label="кубик",
                            symbol="🟩"
                        ),
                    ],
                    operation="+",
                    target_count=16,
                )
            )

        # 4-6 классы (Среднее звено I - природоведение / биология)
        elif tier == AgeTier.MIDDLE:
            return PageAnalysisResponse(
                task_title="Fotosüntees ja taime toitumine (Фотосинтез и питание растений)",
                theme_explanation=(
                    f"Привет, {nickname}! Вспомни, как в {chosen_interest} работают источники питания или генераторы. "
                    "Лист растения — это природная фабрика! "
                    "Зеленые хлоропласты ловят солнечный свет (päikesevalgus), забирают воду (vesi) и углекислый газ (süsihappegaas), "
                    "а на выходе производят кислород (hapnik) и сахар для энергии (glükoos)."
                ),
                alternative_explanation=(
                    "Если провести аналогию со смартфоном: солнечный свет — это зарядное устройство (valgusenergia), "
                    "а лист растения — аккумулятор. Растение заряжается энергией, очищает воздух и производит кислород (hapnik)."
                ),
                vocabulary=[
                    VocabularyItem(
                        est="fotosüntees",
                        ru="фотосинтез (процесс образования органических веществ на свету)",
                        example="Fotosüntees toimub taime rohelistes osades."
                    ),
                    VocabularyItem(
                        est="kloroplast",
                        ru="хлоропласт (зеленая органелла клетки листа)",
                        example="Kloroplastides asub roheline pigment klorofüll."
                    ),
                    VocabularyItem(
                        est="süsihappegaas",
                        ru="углекислый газ (CO2)",
                        example="Taim omastab süsihappegaasi õhust lehtede kaudu."
                    ),
                    VocabularyItem(
                        est="hapnik",
                        ru="кислород (выделяемый растением газ)",
                        example="Fotosünteesi käigus eraldub keskkonda hapnik."
                    ),
                    VocabularyItem(
                        est="valgusenergia",
                        ru="световая энергия Солнца",
                        example="Protsessi käivitamiseks on vaja valgusenergiat."
                    ),
                ],
                worked_example=WorkedExample(
                    title="Пример ответа на уроке (Näidis)",
                    given="Вопрос в задании: 'Kuidas toimub fotosüntees ja mis selle käigus tekib?'",
                    steps=[
                        "1. Что поступает в растение: Taim vajab vett ja süsihappegaasi.",
                        "2. Источник энергии: Protsess toimub päikesevalguse abil kloroplastides.",
                        "3. Что выделяется: Tekivad glükoos ja hapnik."
                    ],
                    note="Используй эти три предложения, чтобы ответить учителю или записать в тетрадь!"
                ),
                how_to_answer=(
                    "1. Посмотри на схему растения в учебнике.\n"
                    "2. Определи, какие 2 вещества поступают в лист (vesi ja süsihappegaas).\n"
                    "3. Определи, какой источник энергии запускает реакцию (päikesevalgus).\n"
                    "4. Сформулируй вывод о продуктах фотосинтеза, используя грамматический каркас."
                ),
                answer_template="Fotosünteesi toimumiseks on vaja [valgusenergiat] ja [süsihappegaasi], selle tulemusena tekivad [glükoos] ja eraldub [hapnik].",
                voice_prompt_script=(
                    f"Привет, {nickname}! Это параграф о фотосинтезе — частая тема на контрольной (kontrolltöö). "
                    "Главное запомни три вещи на входе: свет, вода и газ, и две на выходе: сахар и кислород. "
                    "Потренируй фразу по шаблону!"
                ),
                visual=StepSequenceVisual(
                    title="Этапы фотосинтеза (Fotosünteesi etapid)",
                    instruction="Изучи пошаговый порядок природного процесса",
                    steps=[
                        StepSequenceItem(
                            step_number=1,
                            title="Valgusenergia neeldumine",
                            description="Хлоропласты листа поглощают солнечную энергию",
                            icon_or_badge="☀️",
                            is_highlighted=True
                        ),
                        StepSequenceItem(
                            step_number=2,
                            title="Vee ja süsihappegaasi omastamine",
                            description="Корни поглощают воду, а устьица листьев — углекислый газ",
                            icon_or_badge="💧"
                        ),
                        StepSequenceItem(
                            step_number=3,
                            title="Glükoosi ja hapniku teke",
                            description="Образуется питательная глюкоза и выделяется кислород",
                            icon_or_badge="🌿"
                        ),
                    ]
                )
            )

        # 7-9 классы (Старшее звено - физика / химия / биология, строгий стиль, visual=None)
        elif tier == AgeTier.HIGH:
            return PageAnalysisResponse(
                task_title="Fotosüntees ja rakuhingamine (Фотосинтез и клеточное дыхание)",
                theme_explanation=(
                    f"Здравствуй, {nickname}! В 7–9 классах тема фотосинтеза рассматривается на уровне биохимических реакций. "
                    "Хлоропласты осуществляют световые и темновые фазы синтеза органических соединений из CO2 и H2O."
                ),
                alternative_explanation=(
                    "Химическое уравнение баланса: 6 CO2 + 6 H2O + свет -> C6H12O6 + 6 O2. "
                    "Это реакция запасания энергии химических связей в молекулах глюкозы."
                ),
                vocabulary=[
                    VocabularyItem(
                        est="fotosüntees",
                        ru="фотосинтез (эндотермический процесс синтеза органики)",
                        example="Fotosüntees toimub kloroplastide tülakoidides ja stroomas."
                    ),
                    VocabularyItem(
                        est="kloroplast",
                        ru="хлоропласт (двумембранная органелла растительной клетки)",
                        example="Kloroplastides paikneb roheline pigment klorofüll."
                    ),
                    VocabularyItem(
                        est="süsihappegaas",
                        ru="углекислый газ (CO2)",
                        example="CO2 seotakse Calvini tsükli käigus."
                    ),
                    VocabularyItem(
                        est="hapnik",
                        ru="кислород (побочный продукт фотолиза воды)",
                        example="Vee fotolüüsil eraldub molekulaarne hapnik."
                    ),
                ],
                worked_example=WorkedExample(
                    title="Пример анализа биохимической схемы (Näidis)",
                    given="Задание: 'Selgita, millist rolli mängib valgusenergia fotosünteesi esimeses etapis.'",
                    steps=[
                        "1. Начало реакции: Valgusenergia ergastab klorofülli molekulid.",
                        "2. Фотолиз воды: Toimub vee fotolüüs ja vabanevad prootonid ning hapnik.",
                        "3. Синтез АТФ: Toodetakse keemilist energiat (ATP ja NADPH)."
                    ],
                    note="Зафиксируй тезисы для ответа у доски или в контрольной работе."
                ),
                how_to_answer=(
                    "1. Выдели ключевые реагенты реакции (lähteained) и продукты (saadused).\n"
                    "2. Укажи локализацию процесса в клетке растения.\n"
                    "3. Сформулируй аргументированный вывод научным стилем."
                ),
                answer_template="Fotosünteesi käigus muundatakse [valgusenergia] keemiliseks energiaks, mille tulemusena tekib [glükoos] ja eraldub [hapnik].",
                voice_prompt_script="",
                visual=None
            )

        # 10-12 классы (Гимназия - аналитическое эссе / обществознание / физика)
        else:
            return PageAnalysisResponse(
                task_title="Teaduslik argumentatsioon ja hüpotees (Научная аргументация и гипотеза)",
                theme_explanation=(
                    f"Приветствую, {nickname}! Академический текст требует строгой структуры рассуждения (arutlus). "
                    "Тезис подкрепляется фактами из исследования, после чего формулируется вывод (järeldus). "
                    "В эстонской гимназической программе критически важно связывать причину и следствие с помощью "
                    "союзов 'kuna', 'seetõttu' и 'järelikult'."
                ),
                alternative_explanation=(
                    "Аналогично логике доказательств в юриспруденции или IT-архитектуре: "
                    "исходная посылка проверяется на верифицируемость, после чего формулируется безапелляционное резюме."
                ),
                vocabulary=[
                    VocabularyItem(
                        est="hüpotees",
                        ru="гипотеза (научное предположение)",
                        example="Uurimuse alguses püstitati hüpotees."
                    ),
                    VocabularyItem(
                        est="põhjendus",
                        ru="обоснование / аргумент",
                        example="Iga väide vajab teaduslikku põhjendust."
                    ),
                    VocabularyItem(
                        est="järeldus",
                        ru="умозаключение / вывод",
                        example="Tulemuste põhjal tehti oluline järeldus."
                    ),
                    VocabularyItem(
                        est="seaduspärasus",
                        ru="закономерность",
                        example="Katse kinnitas füüsikalist seaduspärasust."
                    ),
                ],
                worked_example=WorkedExample(
                    title="Пример аргументации (Näidis)",
                    given="Тезис для анализа: 'Tehnoloogia areng muudab noorte õppimisharjumusi.'",
                    steps=[
                        "1. Väide (Тезис): Digivahendid võimaldavad kiiremat juurdepääsu haridusressurssidele.",
                        "2. Põhjendus (Обоснование): Kuna õpilased saavad infot reaalajas analüüsida, suureneb iseseisvus.",
                        "3. Järeldus (Вывод): Seetõttu toetab e-õpe kaasaegsete oskuste kujunemist."
                    ],
                    note="Используйте эту триаду (тезис -> аргумент -> вывод) при написании академического эссе."
                ),
                how_to_answer=(
                    "1. Выделите ключевой вопрос или проблему параграфа.\n"
                    "2. Сформулируйте свою позицию (seisukoht).\n"
                    "3. Приведите минимум 2 аргумента с опорой на термины параграфа.\n"
                    "4. Запишите итоговый вывод по гимназическому шаблону."
                ),
                answer_template="Tuginedes esitatud andmetele, saab järeldada, et [hüpotees], kuna [põhjendus]. Seetõttu on oluline [järeldus].",
                voice_prompt_script=(
                    f"Здравствуйте, {nickname}! Для подготовки к государственному экзамену обратите внимание на логическую связку: "
                    "тезис, обоснование и вывод. Используйте формулировки из шаблона для аргументации."
                )
            )

    async def generate_more_examples(
        self,
        task_title: str,
        theme_explanation: str,
        vocabulary: list,
        current_template: str,
        grade: int = 3,
        tier: Optional[AgeTier] = None,
    ) -> list:
        resolved_tier = tier or AgeTier.from_grade(grade)
        if not self.client:
            logger.info("Generating mock practice examples")
            return self._generate_mock_more_examples(task_title, vocabulary, current_template, resolved_tier)

        vocab_lines = "\n".join(f"- {getattr(v, 'est', str(v))}: {getattr(v, 'ru', '')}" for v in vocabulary)
        prompt = f"""Ты — TarkApp, адаптационный тьютор эстонского языка для русскоязычных школьников в Эстонии.
Ученик ({grade} класс, {resolved_tier.value}) выполняет интерактивное упражнение «Собери ответ на эстонском».
Тема урока: {task_title}
Словарь урока:
{vocab_lines}
Текущий пример: {current_template}

Задача: сгенерируй 2-3 новых разнообразных эстонских примера предложений для закрепления материала и отработки лексики.
ПРАВИЛА:
1. Предложения должны быть на грамотном, естественном эстонском языке, соответствующем {grade} классу.
2. Пропуски для интерактивной вставки слов ОБЯЗАТЕЛЬНО оформляй в квадратных скобках [слово].
   Например: "See on [kass], ta on väga [pehme]." или "Looduses on [taimed] ja [loomad]."
3. Слова в скобках [слово] должны быть точными словами, которые ученик вставит в пропуск (словарные термины урока или ключевые слова).
4. Каждое предложение должно содержать от 1 до 3 пропусков [слово].
5. Предложения не должны повторять текущий пример.

Верни строго JSON объект структуры:
{{
  "templates": [
    "первый новый пример с [пропусками]",
    "второй новый пример с [пропусками]"
  ]
}}
Никакого лишнего текста вне JSON."""

        try:
            config = types.GenerateContentConfig(
                system_instruction=ESTONIAN_TUTOR_SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_schema=MoreExamplesResponse,
                temperature=0.3,
            )
            response = await self.client.aio.models.generate_content(
                model=self.model,
                contents=[prompt],
                config=config,
            )
            if hasattr(response, "parsed") and isinstance(response.parsed, MoreExamplesResponse):
                return response.parsed.templates

            raw_text = response.text or ""
            cleaned = raw_text.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
                cleaned = re.sub(r"\s*```$", "", cleaned)
                cleaned = cleaned.strip()
            data = json.loads(cleaned)
            return data.get("templates", [])
        except Exception as e:
            logger.warning(f"Error calling Gemini for more examples: {e}. Using fallback.")
            return self._generate_mock_more_examples(task_title, vocabulary, current_template, resolved_tier)

    def _generate_mock_more_examples(
        self,
        task_title: str,
        vocabulary: list,
        current_template: str,
        tier: AgeTier,
    ) -> list:
        words = [getattr(v, 'est', str(v)).strip() for v in vocabulary if getattr(v, 'est', str(v)).strip()]
        if not words:
            words = ["õige", "vastus", "sõna"]

        w1 = words[0]
        w2 = words[1] if len(words) > 1 else words[0]
        w3 = words[2] if len(words) > 2 else words[-1]

        title_lower = task_title.lower()
        if "liit" in title_lower or "arv" in title_lower or "summa" in title_lower or "math" in title_lower:
            return [
                f"Liidame kokku [{w1}] ja [{w2}], et leida õige lahendus.",
                f"Kui tehe on valmis, siis [{w1}] on võrdne vastusega.",
                f"Tunnis arvutame hoolega: vastus on [{w3}].",
            ]
        elif "foto" in title_lower or "taim" in title_lower or "loodus" in title_lower or "bio" in title_lower:
            return [
                f"Looduses vajab taim eluks [{w1}] ja päikest.",
                f"Uurime lähemalt: protsessi käigus tekib [{w2}].",
                f"Rohelises lehes toimub oluline muutus, kus osaleb [{w3}].",
            ]
        elif tier == AgeTier.PRIMARY:
            return [
                f"Mina tean, et see on [{w1}].",
                f"Meie koolitunnis uurime sõna [{w2}].",
                f"See on väga tore ja [{w3}].",
            ]
        elif tier in (AgeTier.MIDDLE, AgeTier.HIGH):
            return [
                f"Tunni teema selgitab, kuidas toimib [{w1}].",
                f"Ülesande lahendamiseks on vaja tunda mõistet [{w2}].",
                f"Õige vastuse aluseks on [{w3}].",
            ]
        else:
            return [
                f"Tuginedes analüüsile, saab esile tuua mõiste [{w1}].",
                f"Uurimistöö käigus kinnitati, et oluline tegur on [{w2}].",
                f"Järeldusena võib väita, et süsteemi aluseks on [{w3}].",
            ]

    async def quick_translate(
        self,
        text: Optional[str] = None,
        image_bytes: Optional[bytes] = None,
        mime_type: str = "image/jpeg",
        source_lang: str = "auto",
        target_lang: str = "ru",
    ) -> QuickTranslateResponse:
        """
        Быстрый перевод школьного текста или фотографии фрагмента учебника.
        Адаптирован под учебную программу Эстонии (термины, 3 основные формы algvormid).
        """
        clean_text = (text or "").strip()
        if not clean_text and not image_bytes:
            raise ValueError("Не передан текст или изображение для перевода")

        # Если клиент не настроен (напр. оффлайн или юнит-тесты) — используем школьный словарь-генератор
        if not self.client:
            logger.info("Using school dictionary fallback for quick translation (mock mode)")
            return self._generate_mock_translation(clean_text, source_lang, target_lang)

        contents = []
        if image_bytes:
            contents.append(types.Part.from_bytes(data=image_bytes, mime_type=mime_type))

        prompt_instructions = (
            f"Переведи учебный материал для эстонской школы. "
            f"Исходный язык: {source_lang}. Целевой язык: {target_lang}."
        )
        if clean_text:
            prompt_instructions += f"\n\nТекст для перевода:\n\"\"\"{clean_text}\"\"\""
        else:
            prompt_instructions += "\n\nРаспознай ключевое слово или фразу на прикрепленном фото учебника/тетради и переведи его."

        contents.append(prompt_instructions)

        system_instruction = (
            "Ты — точный переводчик учебных материалов для эстонской школы. "
            "Переведи текст между эстонским и русским языками с учетом терминологии школьных учебников Эстонии "
            "(математика, природоведение, история, физика, химия, обществознание). "
            "Если на входе одно эстонское слово или перевод состоит из одного эстонского слова, "
            "обязательно укажи его 3 основные формы (algvormid: nimetav, omastav, osastav) в поле base_forms. "
            "В поле context_note укажи учебный контекст или школьный предмет (напр. 'Математика / Действия', 'Природоведение'). "
            "Верни результат строго в формате JSON, соответствующем схеме QuickTranslateResponse."
        )

        try:
            config = types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json",
                response_schema=QuickTranslateResponse,
                temperature=0.1,
            )

            response = await self.client.aio.models.generate_content(
                model=self.model,
                contents=contents,
                config=config,
            )

            if hasattr(response, "parsed") and isinstance(response.parsed, QuickTranslateResponse):
                return response.parsed

            raw_text = response.text or ""
            cleaned = raw_text.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
                cleaned = re.sub(r"\s*```$", "", cleaned)
                cleaned = cleaned.strip()

            data = json.loads(cleaned)
            return QuickTranslateResponse.model_validate(data)
        except Exception as e:
            logger.warning(f"Error calling Gemini for quick translate: {e}. Using fallback.")
            return self._generate_mock_translation(clean_text, source_lang, target_lang)

    def _generate_mock_translation(
        self,
        text: str,
        source_lang: str = "auto",
        target_lang: str = "ru",
    ) -> QuickTranslateResponse:
        """Реалистичный словарный генератор для работы без внешнего API и в тестах."""
        t_clean = text.strip() if text else "Näidis"
        t_lower = t_clean.lower()

        # База ключевых терминов эстонской школьной программы
        est_dict = {
            "liitmine ja lahutamine": ("Сложение и вычитание", "liitmine, liitmise, liitmist", "Математическое действие", "et", "ru"),
            "liitmine": ("Сложение", "liitmine, liitmise, liitmist", "Математика / Арифметика", "et", "ru"),
            "lahutamine": ("Вычитание", "lahutamine, lahutamise, lahutamist", "Математика / Арифметика", "et", "ru"),
            "korrutamine": ("Умножение", "korrutamine, korrutamise, korrutamist", "Математика", "et", "ru"),
            "jagamine": ("Деление", "jagamine, jagamise, jagamist", "Математика", "et", "ru"),
            "summa": ("Сумма", "summa, summa, summat", "Математика / Результат сложения", "et", "ru"),
            "liidetav": ("Слагаемое", "liidetav, liidetava, liidetavat", "Математика / Компонент сложения", "et", "ru"),
            "kolmnurk": ("Треугольник", "kolmnurk, kolmnurga, kolmnurka", "Геометрия", "et", "ru"),
            "ruut": ("Квадрат", "ruut, ruudu, ruutu", "Геометрия", "et", "ru"),
            "ring": ("Круг", "ring, ringi, ringi", "Геометрия", "et", "ru"),
            "fotosüntees": ("Фотосинтез", "fotosüntees, fotosünteesi, fotosünteesi", "Природоведение / Биология", "et", "ru"),
            "kloroplast": ("Хлоропласт", "kloroplast, kloroplasti, kloroplasti", "Биология клетки", "et", "ru"),
            "hapnik": ("Кислород", "hapnik, hapniku, hapnikku", "Химия / Природоведение", "et", "ru"),
            "süsihappegaas": ("Углекислый газ (CO2)", "süsihappegaas, süsihappegaasi, süsihappegaasi", "Химия / Природоведение", "et", "ru"),
            "koolikott": ("Школьный ранец / рюкзак", "koolikott, koolikoti, koolikotti", "Школьные принадлежности", "et", "ru"),
            "põhikool": ("Основная школа", "põhikool, põhikooli, põhikooli", "Система образования Эстонии", "et", "ru"),
            "gümnaasium": ("Гимназия (10-12 классы)", "gümnaasium, gümnaasiumi, gümnaasiumi", "Система образования Эстонии", "et", "ru"),
            "õpik": ("Учебник", "õpik, õpiku, õpikut", "Учебные материалы", "et", "ru"),
            "töövihik": ("Рабочая тетрадь", "töövihik, töövihiku, töövihikut", "Учебные материалы", "et", "ru"),
            "loodusõpetus": ("Природоведение", "loodusõpetus, loodusõpetuse, loodusõpetust", "Школьный предмет", "et", "ru"),
        }

        # Проверка прямого совпадения (эстонский -> русский)
        if t_lower in est_dict:
            res_trans, res_base, res_ctx, s_lang, t_lang = est_dict[t_lower]
            return QuickTranslateResponse(
                original_text=t_clean,
                translated_text=res_trans,
                base_forms=res_base,
                context_note=res_ctx,
                source_lang=s_lang,
                target_lang=t_lang,
            )

        # Обратное совпадение (русский -> эстонский)
        for est_k, (ru_val, base_f, ctx_n, _, _) in est_dict.items():
            if ru_val.lower() == t_lower or t_lower in ru_val.lower():
                return QuickTranslateResponse(
                    original_text=t_clean,
                    translated_text=est_k.capitalize(),
                    base_forms=base_f,
                    context_note=ctx_n,
                    source_lang="ru",
                    target_lang="et",
                )

        # Детекция языка по алфавиту для общих фраз
        has_cyrillic = bool(re.search(r'[а-яА-ЯёЁ]', t_clean))
        s_lang = "ru" if has_cyrillic else "et"
        t_lang = "et" if has_cyrillic else "ru"

        if s_lang == "et":
            return QuickTranslateResponse(
                original_text=t_clean,
                translated_text=f"Перевод: {t_clean}",
                base_forms=f"{t_lower}, {t_lower}i, {t_lower}it" if " " not in t_clean else None,
                context_note="Школьный термин",
                source_lang=s_lang,
                target_lang=t_lang,
            )
        else:
            return QuickTranslateResponse(
                original_text=t_clean,
                translated_text=f"Tõlge: {t_clean}",
                base_forms=None,
                context_note="Учебный контекст",
                source_lang=s_lang,
                target_lang=t_lang,
            )


# Singleton instance
gemini_tutor_service = GeminiTutorService()
