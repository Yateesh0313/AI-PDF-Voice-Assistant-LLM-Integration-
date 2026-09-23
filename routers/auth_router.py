"""
Authentication router — register, login, logout, and user info.
Uses HTTP-only cookies for JWT token storage (no localStorage).
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import User
from auth import hash_password, verify_password, create_access_token, get_current_user
from config import ACCESS_TOKEN_EXPIRE_MINUTES

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ── Schemas ────────────────────────────────────────────
class RegisterRequest(BaseModel):
    username: str
    email: str
    password: str

class LoginRequest(BaseModel):
    username: str
    password: str

class UserResponse(BaseModel):
    id: int
    username: str
    email: str


# ── Helper: set auth cookie ───────────────────────────
def _set_auth_cookie(response: Response, token: str):
    """Set JWT as an HTTP-only cookie (not accessible via JavaScript)."""
    import os
    is_production = bool(os.getenv("RENDER"))
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        samesite="lax",
        secure=is_production,      # True on Render (HTTPS), False locally
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/",
    )


# ── Endpoints ──────────────────────────────────────────
@router.post("/register")
def register(req: RegisterRequest, response: Response, db: Session = Depends(get_db)):
    # Check duplicates
    if db.query(User).filter(User.username == req.username).first():
        raise HTTPException(status_code=400, detail="Username already taken")
    if db.query(User).filter(User.email == req.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        username=req.username,
        email=req.email,
        hashed_password=hash_password(req.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token({"sub": str(user.id)})
    _set_auth_cookie(response, token)

    return {
        "user": {"id": user.id, "username": user.username, "email": user.email},
    }


@router.post("/login")
def login(req: LoginRequest, response: Response, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == req.username).first()
    if not user or not verify_password(req.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    token = create_access_token({"sub": str(user.id)})
    _set_auth_cookie(response, token)

    return {
        "user": {"id": user.id, "username": user.username, "email": user.email},
    }


@router.post("/logout")
def logout_user(response: Response):
    import os
    is_production = bool(os.getenv("RENDER"))
    response.delete_cookie(
        key="access_token",
        path="/",
        samesite="lax",
        secure=is_production,
    )
    return {"ok": True}


@router.get("/me", response_model=UserResponse)
def me(user: User = Depends(get_current_user)):
    return {"id": user.id, "username": user.username, "email": user.email}


@router.get("/check")
def check_session(request: Request, db: Session = Depends(get_db)):
    """
    Silent session check — returns status without throwing HTTP errors.
    Used by the frontend to detect DB-wipe vs token-expiry vs valid session.
    """
    from jose import JWTError, jwt as jose_jwt
    from config import SECRET_KEY, ALGORITHM

    token = request.cookies.get("access_token")
    if not token:
        return {"valid": False, "reason": "no_token"}
    try:
        payload = jose_jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload.get("sub", 0))
    except (JWTError, ValueError):
        return {"valid": False, "reason": "token_expired"}

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return {"valid": False, "reason": "user_gone"}

    return {"valid": True, "user": {"id": user.id, "username": user.username, "email": user.email}}
