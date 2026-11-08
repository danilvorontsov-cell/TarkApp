"""
Database migration CLI script for TarkApp.
Applies init_db() lightweight migrations and verifies table schema and speech_text backfill.
"""
import sys
from sqlalchemy import text
from app.database import init_db, engine


def run_migrations():
    print("[MIGRATION] Applying init_db() migrations...")
    init_db()
    print("[MIGRATION] init_db() completed successfully.")

    target_tables = ["lessons", "analyses", "lesson_sessions", "lesson_steps", "history"]
    with engine.connect() as conn:
        for tbl in target_tables:
            info = conn.execute(text(f"PRAGMA table_info({tbl})")).fetchall()
            col_names = [row[1] for row in info]
            if "speech_text" not in col_names:
                print(f"[ERROR] Table '{tbl}' is missing 'speech_text' column!")
                sys.exit(1)

            # Check backfill
            null_count = conn.execute(
                text(f"SELECT COUNT(*) FROM {tbl} WHERE speech_text IS NULL AND text IS NOT NULL")
            ).scalar()
            if null_count > 0:
                print(f"[ERROR] Table '{tbl}' has {null_count} rows with speech_text IS NULL!")
                sys.exit(1)

            print(f"[VERIFIED] Table '{tbl}': speech_text column present, backfill verified (0 unmigrated rows).")

    print("[SUCCESS] All database migrations verified successfully.")


if __name__ == "__main__":
    run_migrations()
