#!/usr/bin/env python3
"""
Migration script to ensure max_free_reviews column exists and all devices have max_free_reviews = 20.
"""
import sys
from pathlib import Path

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from sqlalchemy import text
from app.database import engine, init_db

def run_migration():
    print("[MIGRATION] Initializing database schema...")
    init_db()

    with engine.connect() as conn:
        # 1. Check existing columns
        pragma_res = conn.execute(text("PRAGMA table_info(devices)")).fetchall()
        col_names = [r[1] for r in pragma_res]
        print(f"[MIGRATION] Current columns in 'devices': {col_names}")

        # 2. Add max_free_reviews column if missing
        if "max_free_reviews" not in col_names:
            print("[MIGRATION] Adding 'max_free_reviews' column...")
            conn.execute(text("ALTER TABLE devices ADD COLUMN max_free_reviews INTEGER DEFAULT 20 NOT NULL"))
            conn.commit()
            print("[MIGRATION] Column 'max_free_reviews' added.")

        # 3. Update existing records where max_free_reviews < 20 or NULL
        update_res = conn.execute(text("UPDATE devices SET max_free_reviews = 20 WHERE max_free_reviews IS NULL OR max_free_reviews < 20"))
        conn.commit()
        print(f"[MIGRATION] Updated {update_res.rowcount} devices with max_free_reviews = 20.")

        # 4. Print current status of all devices
        rows = conn.execute(text("SELECT device_id, free_reviews_left, max_free_reviews, last_review_date FROM devices")).fetchall()
        print("\n[MIGRATION] Current devices in database:")
        print("-" * 80)
        print(f"{'Device ID':<36} | {'Left':<5} | {'Max':<5} | {'Last Review Date'}")
        print("-" * 80)
        for r in rows:
            print(f"{str(r[0]):<36} | {str(r[1]):<5} | {str(r[2]):<5} | {str(r[3])}")
        print("-" * 80)
        print(f"[MIGRATION] Total devices: {len(rows)}\n")

if __name__ == "__main__":
    run_migration()
