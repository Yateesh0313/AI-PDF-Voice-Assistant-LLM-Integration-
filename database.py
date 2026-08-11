"""
SQLAlchemy database setup — supports SQLite (Render), MySQL (local), PostgreSQL.
"""
import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from config import DATABASE_URL

logger = logging.getLogger(__name__)

# SQLite needs connect_args for thread safety in FastAPI
_connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    _connect_args = {"check_same_thread": False}

try:
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        connect_args=_connect_args,
    )
    logger.info("Database engine created: %s", DATABASE_URL.split("@")[-1] if "@" in DATABASE_URL else DATABASE_URL)
except Exception as e:
    logger.error("Failed to create database engine: %s", e)
    raise

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """FastAPI dependency — yields a DB session, auto-closes on exit."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
