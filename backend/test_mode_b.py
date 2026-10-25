import os
import sys
import json
import requests
from pydantic import ValidationError

from app.models.page_analysis import PageAnalysisResponse

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

SERVER_URL = "http://127.0.0.1:8080/api/v1/analyze-page"


def run_test_object(image_path: str, interests: str = "Minecraft, LEGO, котики"):
    filename = os.path.basename(image_path)
    print("\n" + "=" * 70)
    print(f"ТЕСТИРОВАНИЕ РЕЖИМА B (Maailma Avastaja): {filename}")
    print("=" * 70)

    with open(image_path, "rb") as f:
        files = {
            "file": (filename, f, "image/jpeg"),
        }
        data = {
            "grade": "3",
            "interests": interests,
            "nickname": "Алекс",
        }
        print(f"Отправка запроса на {SERVER_URL} ...")
        response = requests.post(SERVER_URL, files=files, data=data, timeout=60)

    print(f"HTTP Status: {response.status_code}")
    if response.status_code != 200:
        print(f"Ошибка ответа: {response.text}")
        sys.exit(1)

    result_json = response.json()

    # Валидация по схеме PageAnalysisResponse
    try:
        model = PageAnalysisResponse.model_validate(result_json)
        print(" Успешная валидация схемы PageAnalysisResponse!")
    except ValidationError as e:
        print(f"❌ Ошибка валидации: {e}")
        sys.exit(1)

    # Проверка формата task_title для Режима B
    title = model.task_title
    print(f"Заголовок: {title}")
    if "avastus" in title.lower():
        print(" Заголовок соответствует формату 'Avastus: [Объект] ([Перевод])'!")
    else:
        print(f"⚠️ Заголовок '{title}' не содержит префикса 'Avastus:'.")

    print(f"Словарь ({len(model.vocabulary)} терминов):")
    for v in model.vocabulary:
        print(f"  - {v.est}: {v.ru} (Пример: {v.example})")

    print("\n--- ПОЛНЫЙ JSON-ОТВЕТ ОТ GEMINI ---")
    print(json.dumps(result_json, ensure_ascii=False, indent=2))
    print("-" * 70)
    return model


def main():
    cat_path = os.path.join(os.path.dirname(__file__), "tests", "cat_photo.jpg")
    mug_path = os.path.join(os.path.dirname(__file__), "tests", "coffee_mug.jpg")

    if os.path.exists(cat_path):
        run_test_object(cat_path, interests="Minecraft, котики, игры")

    if os.path.exists(mug_path):
        run_test_object(mug_path, interests="LEGO, чай, Minecraft")


if __name__ == "__main__":
    main()
