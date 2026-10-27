#!/usr/bin/env python3
"""
CLI tool for TarkApp access keys and promo codes management.

Commands:
    python scripts/manage_keys.py gen --count 20 --days 30 --prefix TARK
    python scripts/manage_keys.py list [--filter active|free|expired]
"""
import argparse
import sys
from pathlib import Path

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

# Ensure UTF-8 stdout encoding on Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from app.database import init_db
from app.services.license_service import (
    generate_access_keys,
    list_access_keys,
    get_keys_stats,
)


def cmd_gen(args: argparse.Namespace) -> int:
    """Generates unique access keys and saves them to DB and file."""
    init_db()

    count = max(1, args.count)
    days = max(1, args.days)
    prefix = (args.prefix or "TARK").strip().upper()

    print(f"\n🔑 Генерация {count} ключей (срок: {days} дн., префикс: {prefix})...")
    keys = generate_access_keys(count=count, days=days, prefix=prefix)

    # Output to console
    print("\n" + "=" * 40)
    for idx, k in enumerate(keys, start=1):
        print(f"  {idx:2d}. {k}")
    print("=" * 40)

    # Save batch to file
    out_path = Path(args.output) if args.output else backend_dir / "generated_keys.txt"
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("\n".join(keys) + "\n", encoding="utf-8")
        print(f"\n✅ Успешно сгенерировано {len(keys)} ключей.")
        print(f"📄 Пачка сохранена в файл: {out_path.resolve()}\n")
    except Exception as e:
        print(f"⚠️ Ошибка при записи в файл {out_path}: {e}")

    return 0


def cmd_list(args: argparse.Namespace) -> int:
    """Lists access keys formatted in a clean table with status filtering."""
    init_db()

    filter_val = (args.filter or "all").strip().lower()
    items = list_access_keys(filter_status=filter_val)
    stats = get_keys_stats()

    print(f"\n📋 Список ключей доступа (Фильтр: {filter_val}):\n")

    if not items:
        print("  (Записей не найдено)")
    else:
        # Table column definitions: (Title, key, width, alignment)
        col_key = 18
        col_days = 6
        col_status = 10
        col_dev = 28
        col_used = 18
        col_exp = 18

        header = (
            f"| {'Ключ':<{col_key}} "
            f"| {'Дней':<{col_days}} "
            f"| {'Статус':<{col_status}} "
            f"| {'Устройство':<{col_dev}} "
            f"| {'Активирован':<{col_used}} "
            f"| {'Истекает':<{col_exp}} |"
        )
        separator = "-" * len(header)

        print(separator)
        print(header)
        print(separator)

        for it in items:
            key_str = it["key_code"][:col_key]
            days_str = str(it["duration_days"])
            status_str = it["status_label"]
            dev_raw = it["device_id"]
            dev_str = (dev_raw[:col_dev - 3] + "...") if len(dev_raw) > col_dev else dev_raw
            used_str = it["used_at"]
            exp_str = it["expires_at"]

            row = (
                f"| {key_str:<{col_key}} "
                f"| {days_str:<{col_days}} "
                f"| {status_str:<{col_status}} "
                f"| {dev_str:<{col_dev}} "
                f"| {used_str:<{col_used}} "
                f"| {exp_str:<{col_exp}} |"
            )
            print(row)

        print(separator)

    print(f"\n📊 Сводка:")
    print(f"   • Выведено в таблице: {len(items)} шт.")
    print(
        f"   • Всего в базе: {stats['total_keys']} ключей "
        f"(🟢 Свободных: {stats['free_keys']}, "
        f"🔵 Активных: {stats['active_keys']}, "
        f"🔴 Просроченных: {stats['expired_keys']})"
    )
    print(f"   • Зарегистрировано устройств: {stats['total_devices']}\n")

    return 0


def main():
    parser = argparse.ArgumentParser(
        description="TarkApp Access Keys & Promo Codes Management CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="Команда для выполнения")

    # Command: gen
    p_gen = subparsers.add_parser("gen", help="Генерация новой партии ключей доступа")
    p_gen.add_argument(
        "--count",
        type=int,
        default=20,
        help="Количество ключей для генерации (по умолчанию 20)",
    )
    p_gen.add_argument(
        "--days",
        type=int,
        default=30,
        help="Срок действия ключа в днях (по умолчанию 30)",
    )
    p_gen.add_argument(
        "--prefix",
        type=str,
        default="TARK",
        help="Префикс ключа (по умолчанию TARK)",
    )
    p_gen.add_argument(
        "--output",
        type=str,
        default=None,
        help="Путь к файлу для сохранения (по умолчанию backend/generated_keys.txt)",
    )

    # Command: list
    p_list = subparsers.add_parser("list", help="Просмотр существующих ключей")
    p_list.add_argument(
        "--filter",
        type=str,
        choices=["all", "active", "free", "expired"],
        default="all",
        help="Фильтрация: active, free, expired или all (по умолчанию all)",
    )

    args = parser.parse_args()

    if args.command == "gen":
        sys.exit(cmd_gen(args))
    elif args.command == "list":
        sys.exit(cmd_list(args))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
