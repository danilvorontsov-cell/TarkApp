from pathlib import Path
from sqlalchemy import create_engine, text
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
    connect_args={"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {},
)

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

    # Lightweight migration: ensure free_reviews_left column exists in devices table
    with engine.connect() as conn:
        try:
            result = conn.execute(text("PRAGMA table_info(devices)")).fetchall()
            col_names = [row[1] for row in result]
            if "free_reviews_left" not in col_names and "device_id" in col_names:
                conn.execute(text("ALTER TABLE devices ADD COLUMN free_reviews_left INTEGER DEFAULT 5 NOT NULL"))
                conn.commit()
        except Exception:
            pass

