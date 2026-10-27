"""
CLI script to generate access promo keys for TarkApp beta-testers.
Usage:
    python scripts/generate_keys.py --count 50 --days 30
"""
import argparse
import secrets
import string
import sys
from pathlib import Path
from datetime import datetime

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.database import SessionLocal, init_db
from app.models.license import AccessKey

# Unambiguous characters for readable promo codes
CHAR_SET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def generate_key_code(prefix: str = "TARK") -> str:
    part1 = "".join(secrets.choice(CHAR_SET) for _ in range(4))
    part2 = "".join(secrets.choice(CHAR_SET) for _ in range(4))
    return f"{prefix}-{part1}-{part2}"


def create_keys(count: int = 50, days: int = 30, prefix: str = "TARK", output_file: str = None) -> list:
    init_db()
    db = SessionLocal()
    created_keys = []

    try:
        attempts = 0
        max_attempts = count * 5

        while len(created_keys) < count and attempts < max_attempts:
            attempts += 1
            code = generate_key_code(prefix)

            # Check for uniqueness
            existing = db.query(AccessKey).filter(AccessKey.key_code == code).first()
            if existing:
                continue

            key_obj = AccessKey(
                key_code=code,
                duration_days=days,
                is_used=False,
                used_by_device=None,
                created_at=datetime.utcnow(),
                used_at=None,
            )
            db.add(key_obj)
            db.commit()
            created_keys.append(code)

        print(f"Успешно сгенерировано {len(created_keys)} ключей по {days} дней каждый.")

        if output_file:
            out_path = Path(output_file)
            out_path.write_text("\n".join(created_keys), encoding="utf-8")
            print(f"Ключи сохранены в файл: {out_path.resolve()}")

        return created_keys
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description="TarkApp Access Key Generator")
    parser.add_argument("--count", type=int, default=50, help="Количество ключей (по умолчанию 50)")
    parser.add_argument("--days", type=int, default=30, help="Срок действия в днях (по умолчанию 30)")
    parser.add_argument("--prefix", type=str, default="TARK", help="Префикс ключа (по умолчанию TARK)")
    parser.add_argument("--output", type=str, default=None, help="Путь к файлу для сохранения ключей")

    args = parser.parse_args()
    keys = create_keys(count=args.count, days=args.days, prefix=args.prefix, output_file=args.output)
    for idx, k in enumerate(keys[:10], start=1):
        print(f"  {idx}. {k} ({args.days} дн.)")
    if len(keys) > 10:
        print(f"  ... и еще {len(keys) - 10} ключей.")


if __name__ == "__main__":
    main()
