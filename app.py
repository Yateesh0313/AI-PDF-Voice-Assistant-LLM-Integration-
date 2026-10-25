"""
AI PDF Voice Assistant — FastAPI entry point.
Wires up all routers, middleware, and serves the SPA frontend.
"""
from contextlib import asynccontextmanager
import asyncio
import glob, os, logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import httpx

from config import STATIC_DIR, UPLOAD_DIR, DATABASE_URL, KEEP_ALIVE_INTERVAL

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ── Startup / shutdown ────────────────────────────────
def _cleanup_temp_files():
    for f in glob.glob("static/response_*.mp3"):
        try: os.remove(f)
        except OSError: pass
    for f in glob.glob("input_*.webm"):
        try: os.remove(f)
        except OSError: pass


# ── Keep-alive: prevent Render free-tier 15-min sleep ──
async def _keep_alive():
    """
    Ping our own /health endpoint every 5 minutes to stay awake.
    Uses exponential backoff on failure to avoid hammering a broken endpoint.
    """
    url = os.getenv("RENDER_EXTERNAL_URL", "")
    if not url:
        logger.info("RENDER_EXTERNAL_URL not set — keep-alive disabled (local dev).")
        return

    logger.info("Keep-alive enabled: pinging %s/health every %d sec.", url, KEEP_ALIVE_INTERVAL)
    await asyncio.sleep(30)  # let startup finish

    consecutive_failures = 0
    async with httpx.AsyncClient(timeout=15) as client:
        while True:
            try:
                resp = await client.get(f"{url}/health")
                if resp.status_code == 200:
                    logger.debug("Keep-alive ping OK: %d", resp.status_code)
                    consecutive_failures = 0
                else:
                    logger.warning("Keep-alive ping returned %d", resp.status_code)
                    consecutive_failures += 1
            except Exception as exc:
                consecutive_failures += 1
                logger.warning("Keep-alive ping failed (%d): %s", consecutive_failures, exc)

            # Back off if multiple failures, but cap at 10 min
            delay = min(KEEP_ALIVE_INTERVAL * (1 + consecutive_failures), 600)
            await asyncio.sleep(delay)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting AI PDF Voice Assistant...")
    db_type = DATABASE_URL.split(":")[0] if ":" in DATABASE_URL else "unknown"
    logger.info("Database URL type: %s", db_type)

    # Import here to catch errors gracefully
    from database import engine, Base
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables created successfully.")
    except Exception as e:
        logger.error("Database setup failed: %s", e)
        # Don't crash the entire app — the DB might recover
        logger.error("App will start but database features may be unavailable.")

    _cleanup_temp_files()

    # Pre-warm the embedding model in background (don't block startup)
    async def _prewarm():
        await asyncio.sleep(5)  # let the server bind to PORT first
        try:
            from services.llm_service import _get_embeddings
            logger.info("Pre-warming embedding model...")
            _get_embeddings()
            logger.info("Embedding model ready.")
        except Exception as e:
            logger.warning("Embedding pre-warm failed (will retry on first request): %s", e)

    prewarm_task = asyncio.create_task(_prewarm())
    logger.info("Application started successfully!")

    # Start keep-alive background task
    keep_alive_task = asyncio.create_task(_keep_alive())

    yield

    keep_alive_task.cancel()
    prewarm_task.cancel()


# ── App ───────────────────────────────────────────────
app = FastAPI(title="AI PDF Voice Assistant", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────
from routers import auth_router, chat_router, pdf_router
app.include_router(auth_router.router)
app.include_router(chat_router.router)
app.include_router(pdf_router.router)

# ── Static files ──────────────────────────────────────
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ── Health check ──────────────────────────────────────
@app.get("/health")
async def health():
    """Health check endpoint — used by Render and keep-alive."""
    db_type = DATABASE_URL.split(":")[0] if ":" in DATABASE_URL else "unknown"
    return JSONResponse({"status": "ok", "db": db_type})


# ── Frontend SPA ──────────────────────────────────────
@app.get("/")
async def home():
    return FileResponse("llm.html")