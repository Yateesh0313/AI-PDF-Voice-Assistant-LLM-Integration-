"""
SQLAlchemy database setup — supports SQLite (Render), MySQL (local), PostgreSQL.
Includes connection retry logic for cloud database resilience.
"""
import logging
import time
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base
from config import DATABASE_URL, DB_ENGINE_OPTIONS, DB_IS_SQLITE

logger = logging.getLogger(__name__)

# ── Create Engine with Retry ──────────────────────────
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds

engine = None
for attempt in range(1, MAX_RETRIES + 1):
    try:
        engine = create_engine(DATABASE_URL, **DB_ENGINE_OPTIONS)
        # Verify connection works (skip for SQLite — file-based, always works)
        if not DB_IS_SQLITE:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
                conn.commit()
        logger.info(
            "Database engine created (attempt %d): %s",
            attempt,
            DATABASE_URL.split("@")[-1] if "@" in DATABASE_URL else DATABASE_URL,
        )
        break
    except Exception as e:
        logger.warning("Database connection attempt %d/%d failed: %s", attempt, MAX_RETRIES, e)
        if attempt == MAX_RETRIES:
            logger.error("All database connection attempts failed. Using engine anyway (will retry on first query).")
            # Create engine without verification — it may recover later
            if engine is None:
                engine = create_engine(DATABASE_URL, **DB_ENGINE_OPTIONS)
        else:
            time.sleep(RETRY_DELAY * attempt)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """FastAPI dependency — yields a DB session, auto-closes on exit."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
