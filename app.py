"""
AI PDF Voice Assistant — FastAPI entry point.
Wires up all routers, middleware, and serves the SPA frontend.
"""
from contextlib import asynccontextmanager
import glob, os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from config import STATIC_DIR, UPLOAD_DIR
from database import engine, Base
from routers import auth_router, chat_router, pdf_router


# ── Startup / shutdown ────────────────────────────────
def _cleanup_temp_files():
    for f in glob.glob("static/response_*.mp3"):
        try: os.remove(f)
        except OSError: pass
    for f in glob.glob("input_*.webm"):
        try: os.remove(f)
        except OSError: pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create DB tables
    Base.metadata.create_all(bind=engine)
    _cleanup_temp_files()
    yield


# ── App ───────────────────────────────────────────────
app = FastAPI(title="AI PDF Voice Assistant", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────
app.include_router(auth_router.router)
app.include_router(chat_router.router)
app.include_router(pdf_router.router)

# ── Static files ──────────────────────────────────────
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ── Frontend SPA ──────────────────────────────────────
@app.get("/")
async def home():
    return FileResponse("llm.html")