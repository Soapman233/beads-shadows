import hashlib
import os
import re
import secrets
import threading
import time
import unicodedata
import uuid
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from functools import lru_cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import CheckConstraint, ForeignKey, Index, String, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from .db import Base, get_db, optional_db

router = APIRouter(prefix="/auth", tags=["账号"])
COOKIE = "bead_session"
SESSION_SECONDS = 7 * 24 * 60 * 60
USER_NAME = re.compile(r"[a-z0-9][a-z0-9_.-]{2,31}")
TOKEN = re.compile(r"[A-Za-z0-9_-]{43}")
password_hasher = PasswordHasher()
attempts: OrderedDict[tuple[str, str], tuple[int, float]] = OrderedDict()
attempts_lock = threading.Lock()


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('user', 'admin')", name="ck_user_role"),
        CheckConstraint("status IN ('active', 'frozen')", name="ck_user_status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    username: Mapped[str] = mapped_column(String(32, collation="utf8mb4_bin"), unique=True)
    nickname: Mapped[str] = mapped_column(String(80))
    password_digest: Mapped[str] = mapped_column(String(255))
    preferred_palette: Mapped[str | None] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(12), default="user")
    status: Mapped[str] = mapped_column(String(12), default="active")
    created_at: Mapped[datetime] = mapped_column(default=utc_now)


class LoginSession(Base):
    __tablename__ = "sessions"
    __table_args__ = (Index("ix_sessions_user_expires", "user_id", "expires_at"),)

    token_digest: Mapped[str] = mapped_column(String(64, collation="utf8mb4_bin"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    csrf_token: Mapped[str] = mapped_column(String(43))
    expires_at: Mapped[datetime]
    revoked_at: Mapped[datetime | None]


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class Registration(Credentials):
    password: str = Field(min_length=10, max_length=128)
    nickname: str | None = Field(default=None, max_length=80)


class ProfileUpdate(BaseModel):
    nickname: str | None = Field(default=None, min_length=1, max_length=80)
    preferredPalette: str | None = Field(default=None, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")


class PasswordChange(BaseModel):
    currentPassword: str = Field(min_length=1, max_length=128)
    newPassword: str = Field(min_length=10, max_length=128)


def normalized_username(name: str) -> str:
    value = unicodedata.normalize("NFKC", name).strip().casefold()
    if not USER_NAME.fullmatch(value):
        raise HTTPException(422, "账号需为 3–32 位英文字母、数字或 ._-，以字母或数字开头")
    return value


def public_user(user: User):
    return {
        "id": user.id,
        "username": user.username,
        "nickname": user.nickname,
        "preferredPalette": user.preferred_palette,
        "role": user.role,
        "status": user.status,
    }


def block_cross_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    same_origin = f"{request.url.scheme}://{request.url.netloc}"
    configured = os.environ.get("BEAD_WEB_ORIGIN", "").rstrip("/")
    if (origin and origin not in (same_origin, configured)) or request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(403, "请求来源无效")


def rate_limit(request: Request, operation: str, limit: int) -> None:
    ip = request.client.host if request.client else "unknown"
    key = operation, ip
    now = time.monotonic()
    with attempts_lock:
        count, expiry = attempts.get(key, (0, now + 60))
        if expiry <= now:
            count, expiry = 0, now + 60
        if count >= limit:
            raise HTTPException(429, "操作过于频繁，请稍后再试", headers={"Retry-After": str(max(1, int(expiry - now)))})
        attempts[key] = count + 1, expiry
        attempts.move_to_end(key)
        if len(attempts) > 4096:
            attempts.popitem(last=False)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def revoke_sessions(database: Session, user_id: str) -> None:
    database.execute(
        update(LoginSession)
        .where(LoginSession.user_id == user_id, LoginSession.revoked_at.is_(None))
        .values(revoked_at=utc_now())
    )


def optional_user(request: Request, database: Session | None = Depends(optional_db)) -> User | None:
    expected_user = request.headers.get("x-bead-account")
    token = request.cookies.get(COOKIE, "")
    if not database or not TOKEN.fullmatch(token):
        if expected_user is not None:
            raise HTTPException(401, "登录状态已变化，请重新打开账号空间")
        return None
    result = database.execute(
        select(LoginSession, User).join(User, LoginSession.user_id == User.id).where(
            LoginSession.token_digest == token_digest(token),
            LoginSession.expires_at > utc_now(),
            LoginSession.revoked_at.is_(None),
            User.status == "active",
        )
    ).one_or_none()
    if result is None:
        if expected_user is not None:
            raise HTTPException(401, "登录状态已变化，请重新打开账号空间")
        return None
    session, user = result
    if expected_user is not None and expected_user != user.id:
        raise HTTPException(409, "登录账号已切换，请重新打开账号空间")
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        block_cross_origin(request)
        supplied = request.headers.get("x-csrf-token", "")
        if not TOKEN.fullmatch(supplied) or not secrets.compare_digest(session.csrf_token, supplied):
            raise HTTPException(403, "会话校验失败，请刷新后重试")
    request.state.login_session = session
    return user


def current_user(user: User | None = Depends(optional_user)) -> User:
    if user is None:
        raise HTTPException(401, "请先登录")
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(403, "需要管理员权限")
    return user


def start_session(database: Session, user: User, response: Response, request: Request):
    old_token = request.cookies.get(COOKIE, "")
    if TOKEN.fullmatch(old_token):
        existing = database.get(LoginSession, token_digest(old_token))
        if existing:
            existing.revoked_at = utc_now()
    token = secrets.token_urlsafe(32)
    session = LoginSession(
        token_digest=token_digest(token),
        user_id=user.id,
        csrf_token=secrets.token_urlsafe(32),
        expires_at=utc_now() + timedelta(seconds=SESSION_SECONDS),
    )
    database.add(session)
    database.commit()
    response.set_cookie(
        COOKIE, token, max_age=SESSION_SECONDS, httponly=True, samesite="lax",
        secure=request.url.scheme == "https" or os.environ.get("BEAD_COOKIE_SECURE") == "1",
    )
    response.headers["Cache-Control"] = "no-store"
    return {"user": public_user(user), "csrfToken": session.csrf_token}


@router.get("/me")
def me(request: Request, response: Response, user: User | None = Depends(optional_user)):
    response.headers["Cache-Control"] = "no-store"
    if user is None:
        return {"user": None, "csrfToken": None}
    return {"user": public_user(user), "csrfToken": request.state.login_session.csrf_token}


@router.post("/register", status_code=201)
def register(payload: Registration, request: Request, response: Response, database: Session = Depends(get_db)):
    block_cross_origin(request)
    rate_limit(request, "register", 10)
    username = normalized_username(payload.username)
    user = User(
        id=str(uuid.uuid4()), username=username, nickname=(payload.nickname or "").strip() or username,
        password_digest=password_hasher.hash(payload.password),
    )
    database.add(user)
    try:
        database.flush()
    except IntegrityError:
        raise HTTPException(409, "账号已存在") from None
    return start_session(database, user, response, request)


@lru_cache(maxsize=1)
def substitute_digest():
    return password_hasher.hash(secrets.token_urlsafe(32))


def valid_password(digest: str, value: str) -> bool:
    try:
        return password_hasher.verify(digest, value)
    except (VerificationError, InvalidHashError):
        return False


@router.post("/login")
def login(payload: Credentials, request: Request, response: Response, database: Session = Depends(get_db)):
    block_cross_origin(request)
    rate_limit(request, "login", 20)
    username = normalized_username(payload.username)
    user = database.scalar(select(User).where(User.username == username))
    old_digest = user.password_digest if user else substitute_digest()
    if not valid_password(old_digest, payload.password) or not user or user.status != "active":
        raise HTTPException(401, "账号或密码无效")
    locked = database.scalar(select(User).where(User.id == user.id).with_for_update().execution_options(populate_existing=True))
    if not locked or locked.status != "active" or locked.password_digest != old_digest:
        raise HTTPException(401, "账号或密码无效")
    if password_hasher.check_needs_rehash(old_digest):
        locked.password_digest = password_hasher.hash(payload.password)
    return start_session(database, locked, response, request)


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, user: User = Depends(current_user), database: Session = Depends(get_db)):
    request.state.login_session.revoked_at = utc_now()
    database.commit()
    response.delete_cookie(COOKIE)
    response.headers["Cache-Control"] = "no-store"


@router.patch("/me")
def update_profile(payload: ProfileUpdate, user: User = Depends(current_user), database: Session = Depends(get_db)):
    if "nickname" in payload.model_fields_set:
        nickname = (payload.nickname or "").strip()
        if not nickname:
            raise HTTPException(422, "昵称不能为空")
        user.nickname = nickname
    if "preferredPalette" in payload.model_fields_set:
        user.preferred_palette = payload.preferredPalette
    database.commit()
    return public_user(user)


@router.post("/password")
def change_password(payload: PasswordChange, request: Request, response: Response,
                    user: User = Depends(current_user), database: Session = Depends(get_db)):
    rate_limit(request, "password", 8)
    old_digest = user.password_digest
    if not valid_password(old_digest, payload.currentPassword):
        raise HTTPException(400, "当前密码错误")
    new_digest = password_hasher.hash(payload.newPassword)
    locked = database.scalar(select(User).where(User.id == user.id).with_for_update().execution_options(populate_existing=True))
    if not locked or locked.status != "active" or locked.password_digest != old_digest:
        raise HTTPException(409, "账号状态已变化，请重新登录")
    locked.password_digest = new_digest
    revoke_sessions(database, locked.id)
    return start_session(database, locked, response, request)
