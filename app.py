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

from config import STATIC_DIR, UPLOAD_DIR, DATABASE_URL

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
    """Ping our own /health endpoint every 10 minutes to stay awake."""
    url = os.getenv("RENDER_EXTERNAL_URL", "")
    if not url:
        logger.info("RENDER_EXTERNAL_URL not set — keep-alive disabled (local dev).")
        return
    logger.info("Keep-alive enabled: pinging %s/health every 10 min.", url)
    await asyncio.sleep(60)  # let startup finish
    async with httpx.AsyncClient() as client:
        while True:
            try:
                resp = await client.get(f"{url}/health", timeout=10)
                logger.debug("Keep-alive ping: %s", resp.status_code)
            except Exception as exc:
                logger.warning("Keep-alive ping failed: %s", exc)
            await asyncio.sleep(600)  # 10 minutes


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting AI PDF Voice Assistant...")
    logger.info("Database URL type: %s", DATABASE_URL.split(":")[0])

    # Import here to catch errors gracefully
    from database import engine, Base
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables created successfully.")
    except Exception as e:
        logger.error("Database setup failed: %s", e)
        raise

    _cleanup_temp_files()
    logger.info("Application started successfully!")

    # Start keep-alive background task
    keep_alive_task = asyncio.create_task(_keep_alive())
    yield
    keep_alive_task.cancel()


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
    return JSONResponse({"status": "ok", "db": DATABASE_URL.split(":")[0]})


# ── Frontend SPA ──────────────────────────────────────
@app.get("/")
async def home():
    return FileResponse("llm.html")