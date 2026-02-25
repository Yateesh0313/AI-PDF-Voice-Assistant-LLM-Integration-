# AI PDF Voice Assistant v2.0

A **production-ready** FastAPI-based PDF Question-Answering system with authentication, chat history, multi-PDF management, and voice I/O.

## Features

| Feature | Description |
|---|---|
| 🔐 **Authentication** | JWT-based register/login with bcrypt password hashing |
| 💬 **Text & Voice Chat** | Ask questions via text or voice recording |
| 📄 **Multi-PDF RAG** | Upload multiple PDFs — answers are sourced from your PDF library |
| 🧠 **Hybrid Answers** | PDF-context first, fallback to general LLM knowledge |
| 📊 **Source Badges** | Each answer shows whether it came from PDF or general knowledge |
| 🗂️ **Chat History** | Persistent sessions saved to SQLite, accessible from the sidebar |
| 🎤 **Whisper STT** | OpenAI Whisper (small model) for high-accuracy voice recognition |
| 🔊 **TTS Output** | Google TTS for voice answers, with per-message replay |
| 📱 **Responsive UI** | Full-screen dark glassmorphism SPA, works on mobile & desktop |

## Architecture

```
app.py                    ← FastAPI entry point
config.py                 ← Centralized settings (env-var overrides)
database.py               ← SQLite + SQLAlchemy
models.py                 ← User, ChatSession, Message, PDFDocument
auth.py                   ← JWT + bcrypt authentication
routers/
  auth_router.py          ← Register, Login, Me
  chat_router.py          ← Text chat, Voice chat, Sessions CRUD
  pdf_router.py           ← Upload, List, Delete PDFs
services/
  llm_service.py          ← RAG pipeline, per-user FAISS retriever
stt.py                    ← Speech-to-Text (Whisper)
tts.py                    ← Text-to-Speech (gTTS)
llm.html                  ← Full-screen SPA frontend
```

## Setup

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Start LM Studio
# Set Base URL → http://localhost:1234/v1

# 3. Run the server
uvicorn app:app --reload

# 4. Open browser
# http://127.0.0.1:8000
```

## Tech Stack

- **Backend**: FastAPI, SQLAlchemy, LangChain, FAISS, Whisper, gTTS
- **Auth**: JWT (python-jose), bcrypt (passlib)
- **LLM**: LM Studio (TinyLlama 1.1B) via OpenAI-compatible API
- **Embeddings**: sentence-transformers/all-MiniLM-L6-v2
- **Frontend**: Pure HTML/CSS/JS SPA (no frameworks)
- **Database**: SQLite (zero config)
