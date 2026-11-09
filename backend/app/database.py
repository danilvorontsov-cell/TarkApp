from contextlib import contextmanager
from pathlib import Path
from sqlalchemy import create_engine, text, event
from sqlalchemy.orm import Session, sessionmaker, declarative_base

from app.config import settings

# If using local SQLite file, ensure directory exists
if settings.DATABASE_URL.startswith("sqlite:///"):
    db_file_str = settings.DATABASE_URL.replace("sqlite:///", "")
    if db_file_str and db_file_str != ":memory:":
        db_file = Path(db_file_str)
        if db_file.is_absolute():
            db_file.parent.mkdir(parents=True, exist_ok=True)
        else:
            # relative to current working directory or backend root
            db_file.resolve().parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=(
        {"check_same_thread": False, "timeout": 15}
        if settings.DATABASE_URL.startswith("sqlite")
        else {}
    ),
)

# Enable WAL mode and synchronous=NORMAL for high-concurrency SQLite operations
if settings.DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA synchronous=NORMAL;")
        cursor.execute("PRAGMA busy_timeout=15000;")
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


@contextmanager
def transaction(self: Session):
    """
    Context manager for atomic database operations with immediate commit and rollback.
    Usage:
        with db.transaction():
            ...
    """
    if self.in_transaction():
        nested = self.begin_nested()
        try:
            yield self
            nested.commit()
        except Exception:
            nested.rollback()
            raise
    else:
        with self.begin():
            yield self


Session.transaction = transaction


def get_db():
    """FastAPI Dependency for database sessions."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Initializes database schema and tables."""
    # Import all models to ensure they are registered with Base.metadata
    from app.models.license import Device, AccessKey  # noqa: F401
    from app.models.tts_audit import TTSAuditLog  # noqa: F401
    Base.metadata.create_all(bind=engine)

    # Lightweight migration & WAL verification
    with engine.connect() as conn:
        try:
            if settings.DATABASE_URL.startswith("sqlite"):
                conn.execute(text("PRAGMA journal_mode=WAL;"))
                conn.execute(text("PRAGMA synchronous=NORMAL;"))
                conn.execute(text("PRAGMA busy_timeout=15000;"))
                conn.commit()

            result = conn.execute(text("PRAGMA table_info(devices)")).fetchall()
            col_names = [row[1] for row in result]
            if "free_reviews_left" not in col_names and "device_id" in col_names:
                conn.execute(text("ALTER TABLE devices ADD COLUMN free_reviews_left INTEGER DEFAULT 20 NOT NULL"))
                conn.commit()
            if "max_free_reviews" not in col_names and "device_id" in col_names:
                conn.execute(text("ALTER TABLE devices ADD COLUMN max_free_reviews INTEGER DEFAULT 20 NOT NULL"))
                conn.commit()
            if "last_review_date" not in col_names and "device_id" in col_names:
                conn.execute(text("ALTER TABLE devices ADD COLUMN last_review_date VARCHAR DEFAULT NULL"))
                conn.commit()
            if "total_reviews_used" not in col_names and "device_id" in col_names:
                conn.execute(text("ALTER TABLE devices ADD COLUMN total_reviews_used INTEGER DEFAULT 0 NOT NULL"))
                conn.commit()

            # Ensure all existing devices have valid max_free_reviews
            if "device_id" in col_names:
                conn.execute(text("UPDATE devices SET max_free_reviews = 20 WHERE max_free_reviews IS NULL"))
                conn.commit()

            # Schema migration and backfill for speech_text in lessons/analyses/history tables
            target_tables = ["lessons", "analyses", "lesson_sessions", "lesson_steps", "history"]
            for tbl in target_tables:
                try:
                    tbl_check = conn.execute(
                        text("SELECT name FROM sqlite_master WHERE type='table' AND name=:tbl"),
                        {"tbl": tbl}
                    ).fetchone()
                    if not tbl_check:
                        conn.execute(text(f"""
                            CREATE TABLE IF NOT EXISTS {tbl} (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                lesson_id TEXT,
                                text TEXT,
                                speech_text TEXT DEFAULT NULL,
                                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                            )
                        """))
                        conn.commit()
                    else:
                        t_cols = [r[1] for r in conn.execute(text(f"PRAGMA table_info({tbl})")).fetchall()]
                        if "speech_text" not in t_cols:
                            conn.execute(text(f"ALTER TABLE {tbl} ADD COLUMN speech_text TEXT DEFAULT NULL"))
                            conn.commit()
                        if "text" in t_cols:
                            conn.execute(text(f"UPDATE {tbl} SET speech_text = text WHERE speech_text IS NULL"))
                            conn.commit()
                        elif "prompt" in t_cols:
                            conn.execute(text(f"UPDATE {tbl} SET speech_text = prompt WHERE speech_text IS NULL"))
                            conn.commit()
                except Exception:
                    pass
        except Exception:
            pass

    # Revoke the 22 compromised repository keys (mark is_used = 1)
    try:
        from app.services.license_service import revoke_compromised_keys
        with SessionLocal() as db_sess:
            revoke_compromised_keys(db_sess)
    except Exception:
        pass

