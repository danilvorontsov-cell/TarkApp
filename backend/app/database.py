from pathlib import Path
from sqlalchemy import create_engine, text, event
from sqlalchemy.orm import sessionmaker, declarative_base

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

            # Ensure all existing devices have max_free_reviews = 20
            if "device_id" in col_names:
                conn.execute(text("UPDATE devices SET max_free_reviews = 20 WHERE max_free_reviews IS NULL OR max_free_reviews < 20"))
                conn.commit()
        except Exception:
            pass

