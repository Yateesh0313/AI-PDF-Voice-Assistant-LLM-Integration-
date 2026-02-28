"""
Centralized configuration for the AI PDF Voice Assistant.
All settings can be overridden via environment variables.
"""
import os
from pathlib import Path
from urllib.parse import quote_plus

# ── Paths ──────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
STATIC_DIR = BASE_DIR / "static"
UPLOAD_DIR.mkdir(exist_ok=True)
STATIC_DIR.mkdir(exist_ok=True)

# ── Database ───────────────────────────────────────────
# Local: MySQL via PyMySQL
# Render: PostgreSQL via DATABASE_URL env var (provided by Render)
_DB_USER = "root"
_DB_PASS = quote_plus("Yateesh@12")   # encodes @ → %40
_DB_HOST = "localhost"
_DB_PORT = "3306"
_DB_NAME = "ai_pdf_assistant"

_raw_db_url = os.getenv("DATABASE_URL", "")

if _raw_db_url:
    # Render gives postgres:// but SQLAlchemy 2.x needs postgresql://
    if _raw_db_url.startswith("postgres://"):
        _raw_db_url = _raw_db_url.replace("postgres://", "postgresql://", 1)
    DATABASE_URL = _raw_db_url
else:
    DATABASE_URL = f"mysql+pymysql://{_DB_USER}:{_DB_PASS}@{_DB_HOST}:{_DB_PORT}/{_DB_NAME}"

# ── JWT Auth ───────────────────────────────────────────
SECRET_KEY = os.getenv("SECRET_KEY", "super-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("TOKEN_EXPIRY", "1440"))  # 24 h

# ── LM Studio / OpenAI-compatible LLM ─────────────────
LLM_BASE_URL = os.getenv("OPENAI_API_BASE", "http://localhost:1234/v1")
LLM_API_KEY = os.getenv("OPENAI_API_KEY", "lm-studio")
LLM_MODEL = os.getenv("LLM_MODEL", "tinyllama-1.1b-chat-v1.0")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.7"))

# ── Embeddings ─────────────────────────────────────────
EMBEDDING_MODEL = os.getenv(
    "EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
)

# ── Whisper STT ────────────────────────────────────────
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")
