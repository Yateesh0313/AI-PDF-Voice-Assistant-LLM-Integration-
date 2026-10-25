"""
Centralized configuration for the AI PDF Voice Assistant.
All settings can be overridden via environment variables.
"""
import os
import logging
from pathlib import Path
from urllib.parse import quote_plus

logger = logging.getLogger(__name__)

# ── Paths ──────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR.mkdir(exist_ok=True)
STATIC_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)

# ── Database ───────────────────────────────────────────
# Priority:
#   1. DATABASE_URL env var (explicitly set — could be Render PostgreSQL, external DB, etc.)
#   2. RENDER env var set → use local SQLite (reliable, no expiry)
#   3. Local dev → MySQL
_raw_db_url = os.getenv("DATABASE_URL", "").strip()

if _raw_db_url:
    # Render's managed PostgreSQL uses postgres:// but SQLAlchemy needs postgresql://
    if _raw_db_url.startswith("postgres://"):
        _raw_db_url = _raw_db_url.replace("postgres://", "postgresql://", 1)
    DATABASE_URL = _raw_db_url
    logger.info("Using DATABASE_URL from environment: %s", DATABASE_URL.split("@")[-1] if "@" in DATABASE_URL else DATABASE_URL[:30])
elif os.getenv("RENDER"):
    # On Render without DATABASE_URL: use SQLite (no expiry, no external DB needed)
    DATABASE_URL = f"sqlite:///{DATA_DIR / 'app.db'}"
    logger.info("On Render without DATABASE_URL — using SQLite: %s", DATABASE_URL)
else:
    # Local dev: MySQL
    _DB_USER = "root"
    _DB_PASS = quote_plus("Yateesh@12")   # encodes @ → %40
    _DB_HOST = "localhost"
    _DB_PORT = "3306"
    _DB_NAME = "ai_pdf_assistant"
    DATABASE_URL = f"mysql+pymysql://{_DB_USER}:{_DB_PASS}@{_DB_HOST}:{_DB_PORT}/{_DB_NAME}"

# ── Database Engine Options (tuned per backend) ────────
DB_IS_SQLITE = DATABASE_URL.startswith("sqlite")
DB_IS_POSTGRES = DATABASE_URL.startswith("postgresql")

DB_ENGINE_OPTIONS = {}
if DB_IS_SQLITE:
    DB_ENGINE_OPTIONS["connect_args"] = {"check_same_thread": False}
elif DB_IS_POSTGRES:
    # Prevent stale connections from Render's idle-timeout and PG connection limits
    DB_ENGINE_OPTIONS.update({
        "pool_size": 3,            # small pool — free tier has few connections
        "max_overflow": 2,
        "pool_recycle": 300,       # recycle connections every 5 min
        "pool_pre_ping": True,     # test connection before use
        "pool_timeout": 10,
    })
else:
    # MySQL / other
    DB_ENGINE_OPTIONS.update({
        "pool_pre_ping": True,
        "pool_recycle": 1800,
    })

# ── JWT Auth ───────────────────────────────────────────
SECRET_KEY = os.getenv("SECRET_KEY", "super-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("TOKEN_EXPIRY", "1440"))  # 24 h

# ── LLM (Groq / OpenAI-compatible) ────────────────────
_raw_llm_base = (os.getenv("OPENAI_API_BASE") or os.getenv("GROQ_API_BASE") or "https://api.groq.com/openai/v1").strip().rstrip("/")
if "api.groq.com" in _raw_llm_base and not _raw_llm_base.endswith("/openai/v1"):
    LLM_BASE_URL = "https://api.groq.com/openai/v1"
else:
    LLM_BASE_URL = _raw_llm_base

LLM_API_KEY = (os.getenv("OPENAI_API_KEY") or os.getenv("GROQ_API_KEY") or "lm-studio").strip()
LLM_MODEL = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile").strip()
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.7"))
LLM_REQUEST_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "60"))  # seconds

# ── Embeddings (FastEmbed / ONNX — no PyTorch needed) ──
EMBEDDING_MODEL = os.getenv(
    "EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5"
)

# ── Whisper STT (via Groq API — no local model needed) ──
# Model is specified in stt.py, runs on Groq's servers

# ── Keep-alive interval (seconds) ─────────────────────
KEEP_ALIVE_INTERVAL = int(os.getenv("KEEP_ALIVE_INTERVAL", "300"))  # 5 min
