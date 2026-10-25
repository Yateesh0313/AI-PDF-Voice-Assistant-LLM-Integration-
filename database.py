"""
SQLAlchemy database setup — supports SQLite (Render), MySQL (local), PostgreSQL.
Includes connection retry logic and automatic SQLite fallback for 24/7 cloud resilience.
"""
import logging
import time
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base
from config import DATABASE_URL, DB_ENGINE_OPTIONS, DB_IS_SQLITE, DATA_DIR

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds


def _create_initial_engine():
    """Attempt to connect to configured DATABASE_URL; fallback to SQLite if unreachable."""
    target_url = DATABASE_URL
    target_options = DB_ENGINE_OPTIONS

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            eng = create_engine(target_url, **target_options)
            if not target_url.startswith("sqlite"):
                with eng.connect() as conn:
                    conn.execute(text("SELECT 1"))
                    conn.commit()
            logger.info(
                "Database engine connected (attempt %d): %s",
                attempt,
                target_url.split("@")[-1] if "@" in target_url else target_url,
            )
            return eng
        except Exception as e:
            logger.warning(
                "Database connection attempt %d/%d failed for %s: %s",
                attempt,
                MAX_RETRIES,
                target_url.split("@")[-1] if "@" in target_url else target_url,
                e,
            )
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY * attempt)

    # If non-SQLite database failed, automatically fall back to SQLite
    if not target_url.startswith("sqlite"):
        sqlite_url = f"sqlite:///{DATA_DIR / 'app.db'}"
        logger.error(
            "Primary database unreachable. Automatically falling back to local SQLite (%s) for 24/7 reliability.",
            sqlite_url,
        )
        return create_engine(sqlite_url, connect_args={"check_same_thread": False})

    return create_engine(target_url, **target_options)


engine = _create_initial_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def init_db():
    """
    Create all tables. Imports models first so all models are registered in Base.metadata.
    If the primary engine fails to create tables, falls back to SQLite and retries.
    """
    global engine, SessionLocal
    import models  # CRITICAL: registers User, ChatSession, Message, PDFDocument

    try:
        Base.metadata.create_all(bind=engine)
        logger.info(
            "Database tables initialized successfully on %s",
            str(engine.url).split("@")[-1] if "@" in str(engine.url) else str(engine.url),
        )
    except Exception as e:
        logger.error("Failed to initialize database tables on %s: %s", str(engine.url), e)
        if not str(engine.url).startswith("sqlite"):
            logger.warning("Attempting automatic fallback to local SQLite for table creation...")
            sqlite_url = f"sqlite:///{DATA_DIR / 'app.db'}"
            engine = create_engine(sqlite_url, connect_args={"check_same_thread": False})
            SessionLocal.configure(bind=engine)
            Base.metadata.create_all(bind=engine)
            logger.info("Successfully initialized all tables on fallback SQLite.")


def get_db():
    """FastAPI dependency — yields a DB session, handles rollbacks on error, auto-closes on exit."""
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# Ensure tables exist immediately on import
try:
    init_db()
except Exception as _init_err:
    logger.warning("Immediate init_db on import encountered error (will retry during lifespan): %s", _init_err)

