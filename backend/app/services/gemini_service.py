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
    MoreExamplesResponse,
    PageAnalysisResponse,
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

        try:
            # Call Google GenAI SDK with structured response schema
            image_parts = [
                types.Part.from_bytes(data=ib, mime_type=mt)
                for ib, mt in img_list
            ]
            contents = [
                *image_parts,
                user_prompt,
            ]

            config = types.GenerateContentConfig(
                system_instruction=ESTONIAN_TUTOR_SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_schema=PageAnalysisResponse,
                temperature=0.2,
            )

            response = self.client.models.generate_content(
                model=self.model,
                contents=contents,
                config=config,
            )

            # Check if response.parsed was populated by the SDK
            if hasattr(response, "parsed") and isinstance(response.parsed, PageAnalysisResponse):
                return response.parsed

            # Otherwise parse response.text
            raw_text = response.text or ""
            return self._parse_json_response(raw_text)

        except APIError as e:
            logger.error(f"Gemini API error: {e}", exc_info=True)
            raise RuntimeError(f"Ошибка вызова Gemini API: {e.message}") from e
        except Exception as e:
            logger.error(f"Unexpected error in analyze_page: {e}", exc_info=True)
            raise

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
                answer_template="Esimene liidetav on ___, teine liidetav on ___, summa on ___.",
                voice_prompt_script=(
                    f"Привет, {nickname}! Не бойся задания. Мы разберем числа через {chosen_interest}. "
                    "Сложи числа и скажи: summa on, и назови свой ответ!"
                )
            )

        # 5-9 классы (Среднее звено - природоведение / биология / физика)
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
                answer_template="Fotosünteesi toimumiseks on vaja ___ ja ___, selle tulemusena tekivad ___ ja eraldub ___.",
                voice_prompt_script=(
                    f"Привет, {nickname}! Это параграф о фотосинтезе — частая тема на контрольной (kontrolltöö). "
                    "Главное запомни три вещи на входе: свет, вода и газ, и две на выходе: сахар и кислород. "
                    "Потренируй фразу по шаблону!"
                )
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
                answer_template="Tuginedes esitatud andmetele, saab järeldada, et ___, kuna ___. Seetõttu on oluline ___.",
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
            response = self.client.models.generate_content(
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
        elif tier == AgeTier.MIDDLE:
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

            response = self.client.models.generate_content(
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
