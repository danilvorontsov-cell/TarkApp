import os
import sys
import json
import requests
from pydantic import ValidationError

from app.models.page_analysis import PageAnalysisResponse

# Force UTF-8 stdout
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

SERVER_URL = "http://127.0.0.1:8080/api/v1/analyze-page"
TESTS_DIR = os.path.join(os.path.dirname(__file__), "tests")


def find_screenshots(directory: str):
    supported_exts = (".jpg", ".jpeg", ".png")
    found = []
    for file in os.listdir(directory):
        if file.lower().endswith(supported_exts):
            found.append(os.path.join(directory, file))
    return sorted(found)


def test_screenshot(image_path: str):
    filename = os.path.basename(image_path)
    print(f"\n==================================================================")
    print(f"ТЕСТИРОВАНИЕ СКРИНШОТА: {filename}")
    print(f"==================================================================")

    with open(image_path, "rb") as f:
        files = {
            "file": (filename, f, "image/jpeg" if filename.lower().endswith((".jpg", ".jpeg")) else "image/png"),
        }
        data = {
            "grade": "3",
            "interests": "Minecraft, LEGO, Brawl Stars",
            "nickname": "Алекс",
        }

        print(f"Отправка POST-запроса на {SERVER_URL} ...")
        response = requests.post(SERVER_URL, files=files, data=data, timeout=60)

    print(f"HTTP Status Code: {response.status_code}")

    if response.status_code != 200:
        print(f"Ошибка ответа сервера: {response.text}")
        sys.exit(1)

    result_json = response.json()

    # 1. Валидация строго по Pydantic-схеме PageAnalysisResponse
    try:
        parsed_model = PageAnalysisResponse.model_validate(result_json)
        print(" Успешная валидация по схеме PageAnalysisResponse!")
    except ValidationError as e:
        print(f"❌ Ошибка валидации схемы: {e}")
        sys.exit(1)

    # 2. Проверка метафоры Minecraft в theme_explanation
    explanation = parsed_model.theme_explanation.lower()
    has_minecraft = "minecraft" in explanation or "майнкрафт" in explanation or "блок" in explanation or "крафт" in explanation
    if has_minecraft:
        print(" Метафора Minecraft успешно обнаружена в поле theme_explanation!")
    else:
        print("⚠️ Предупреждение: Ключевое слово Minecraft не найдено явно в theme_explanation.")

    # 3. Вывод полного отформатированного JSON-ответа
    print("\n--- ПОЛНЫЙ ОТФОРМАТИРОВАННЫЙ JSON-ОТВЕТ ОТ СЕРВИСА GEMINI ---")
    print(json.dumps(result_json, ensure_ascii=False, indent=2))
    print("------------------------------------------------------------------\n")
    return parsed_model


def main():
    screenshots = find_screenshots(TESTS_DIR)
    if not screenshots:
        print(f"❌ Скриншоты не найдены в директории {TESTS_DIR}")
        sys.exit(1)

    print(f"Обнаружено скриншотов в {TESTS_DIR}: {len(screenshots)}")
    for s in screenshots:
        print(f" - {os.path.basename(s)}")

    # Тестируем скриншоты
    for s in screenshots:
        test_screenshot(s)


if __name__ == "__main__":
    main()
