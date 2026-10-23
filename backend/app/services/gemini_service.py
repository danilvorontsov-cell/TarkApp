import json
import logging
import re
from typing import Optional

from google import genai
from google.genai import types
from google.genai.errors import APIError

from app.config import settings
from app.models.page_analysis import (
    AgeTier,
    AGE_TIER_DEFAULT_INTERESTS,
    PageAnalysisResponse,
    UserProfile,
    VocabularyItem,
)
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

        if self._is_valid_key(self.api_key):
            try:
                self._client = genai.Client(api_key=self.api_key)
                logger.info(f"Initialized Google GenAI client with model: {self.model}")
            except Exception as e:
                logger.warning(f"Failed to initialize GenAI client: {e}. Will use mock mode.")
        else:
            logger.info("No valid GEMINI_API_KEY provided. Running in pedagogical mock mode.")

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
        image_bytes: bytes,
        mime_type: str,
        profile: UserProfile,
    ) -> PageAnalysisResponse:
        """Analyzes a textbook/workbook page image using Gemini Vision and adapts it to the student."""
        # Use mock mode if client is not configured
        if not self._client:
            logger.info("Using pedagogical fallback generator (mock mode)")
            return self._generate_mock_adaptation(profile)

        user_prompt = build_tutor_user_prompt(profile)

        try:
            # Call Google GenAI SDK with structured response schema
            contents = [
                types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                user_prompt,
            ]

            config = types.GenerateContentConfig(
                system_instruction=ESTONIAN_TUTOR_SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_schema=PageAnalysisResponse,
                temperature=0.2,
            )

            response = self._client.models.generate_content(
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


# Singleton instance
gemini_tutor_service = GeminiTutorService()
