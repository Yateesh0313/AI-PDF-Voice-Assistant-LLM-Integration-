"""
Chat router — text chat, voice chat, session management, and chat history.
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy.orm import Session
import shutil, uuid, os
from typing import Optional

from database import get_db
from models import User, ChatSession, Message
from auth import get_current_user
from services.llm_service import get_answer
from stt import speech_to_text
from tts import text_to_speech

router = APIRouter(prefix="/api/chat", tags=["chat"])


# ── Schemas ────────────────────────────────────────────
class AskRequest(BaseModel):
    question: str
    session_id: int | None = None

class SessionCreate(BaseModel):
    title: str = "New Chat"


# ── Sessions ──────────────────────────────────────────
@router.get("/sessions")
def list_sessions(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    sessions = (
        db.query(ChatSession)
        .filter(ChatSession.user_id == user.id)
        .order_by(ChatSession.created_at.desc())
        .all()
    )
    return [
        {"id": s.id, "title": s.title, "created_at": s.created_at.isoformat()}
        for s in sessions
    ]


@router.post("/sessions")
def create_session(req: SessionCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    session = ChatSession(user_id=user.id, title=req.title)
    db.add(session)
    db.commit()
    db.refresh(session)
    return {"id": session.id, "title": session.title, "created_at": session.created_at.isoformat()}


@router.get("/sessions/{session_id}")
def get_session_messages(session_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    session = db.query(ChatSession).filter(
        ChatSession.id == session_id, ChatSession.user_id == user.id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return {
        "id": session.id,
        "title": session.title,
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "audio_url": m.audio_url,
                "is_voice": m.is_voice,
                "source": m.source,
                "created_at": m.created_at.isoformat(),
            }
            for m in session.messages
        ],
    }


@router.delete("/sessions/{session_id}")
def delete_session(session_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    session = db.query(ChatSession).filter(
        ChatSession.id == session_id, ChatSession.user_id == user.id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    db.delete(session)
    db.commit()
    return {"ok": True}


# ── Helper: ensure session ─────────────────────────────
def _ensure_session(session_id: int | None, user: User, db: Session, title: str = "New Chat") -> ChatSession:
    if session_id:
        session = db.query(ChatSession).filter(
            ChatSession.id == session_id, ChatSession.user_id == user.id
        ).first()
        if session:
            return session
    # Create new session
    session = ChatSession(user_id=user.id, title=title)
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


# ── Text chat ──────────────────────────────────────────
@router.post("/ask")
def ask(req: AskRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    session = _ensure_session(req.session_id, user, db, title=req.question[:60])

    # Save user message
    user_msg = Message(session_id=session.id, role="user", content=req.question)
    db.add(user_msg)

    answer, source = get_answer(req.question, user.id)

    # Save AI message
    ai_msg = Message(session_id=session.id, role="ai", content=answer, source=source)
    db.add(ai_msg)
    db.commit()

    return {
        "answer": answer,
        "source": source,
        "session_id": session.id,
    }


# ── Voice chat ─────────────────────────────────────────
@router.post("/voice")
def voice_chat(
    file: UploadFile = File(...),
    session_id: int | None = Form(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    audio_path = f"input_{uuid.uuid4().hex}.webm"
    with open(audio_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # Check file isn't empty
    if os.path.getsize(audio_path) < 100:
        os.remove(audio_path)
        raise HTTPException(status_code=400, detail="Audio file is too short. Please hold the mic button longer and speak clearly.")

    try:
        question = speech_to_text(audio_path)
        if not question:
            raise HTTPException(status_code=400, detail="Could not understand audio. Please speak clearly and try again.")
        answer, source = get_answer(question, user.id)
        audio_file = text_to_speech(answer)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Voice processing error: {str(e)}")
    finally:
        if os.path.exists(audio_path):
            os.remove(audio_path)

    session = _ensure_session(session_id, user, db, title=question[:60])

    # Save messages
    user_msg = Message(session_id=session.id, role="user", content=question, is_voice=True)
    db.add(user_msg)

    ai_msg = Message(
        session_id=session.id, role="ai", content=answer,
        audio_url=audio_file, source=source,
    )
    db.add(ai_msg)
    db.commit()

    return {
        "question": question,
        "answer": answer,
        "source": source,
        "audio_file": audio_file,
        "session_id": session.id,
    }
