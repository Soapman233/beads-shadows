"""Verified recovery addresses, development mail and private account exports."""
from datetime import datetime, timedelta
from email.message import EmailMessage
import io
import json
import os
from pathlib import Path
import secrets
import smtplib
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import DateTime, ForeignKey, String, select, update
from sqlalchemy.orm import Mapped, Session, mapped_column

from .auth import (COOKIE, TOKEN, User, block_cross_origin, current_user, normalized_username,
                   password_hasher, public_user, rate_limit, revoke_sessions, token_digest, utc_now, valid_password)
from .catalog import write_audit
from .db import Base, get_db
from .projects import Asset, Project, ProjectVersion, asset_path, project_info, version_info
from .publications import Publication

router = APIRouter(prefix="/account", tags=["账号管理"])


class Recovery(Base):
    __tablename__ = "account_recovery"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    email: Mapped[str] = mapped_column(String(254))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    verify_digest: Mapped[str | None] = mapped_column(String(64))
    verify_until: Mapped[datetime | None] = mapped_column(DateTime)
    reset_digest: Mapped[str | None] = mapped_column(String(64))
    reset_until: Mapped[datetime | None] = mapped_column(DateTime)


class Closure(Base):
    __tablename__ = "account_closures"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class AddressInput(BaseModel):
    email: str = Field(pattern=r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}$", max_length=254)
    password: str = Field(min_length=1, max_length=128)


class CodeInput(BaseModel):
    code: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")


class UsernameInput(BaseModel):
    username: str = Field(min_length=3, max_length=64)


class ResetInput(UsernameInput, CodeInput):
    password: str = Field(min_length=10, max_length=128)


class CloseInput(BaseModel):
    password: str = Field(min_length=1, max_length=128)
    acknowledge: bool


def mail_mode():
    if os.getenv("BEAD_DEVELOPMENT_OUTBOX"):
        return "local"
    if os.getenv("BEAD_SMTP_HOST") and os.getenv("BEAD_SMTP_FROM"):
        return "smtp"
    return None


def notify(address, subject, code):
    mode = mail_mode()
    if not mode:
        raise HTTPException(503, "邮件服务未配置")
    message = EmailMessage()
    message["To"] = address
    message["From"] = os.getenv("BEAD_SMTP_FROM", "beads-local@example.invalid")
    message["Subject"] = subject
    message.set_content("一次性验证码（15 分钟有效）：\n" + code)
    try:
        if mode == "local":
            folder = Path(os.environ["BEAD_DEVELOPMENT_OUTBOX"])
            folder.mkdir(parents=True, exist_ok=True)
            with (folder / (str(uuid4()) + ".eml")).open("xb") as target:
                target.write(message.as_bytes())
            return
        with smtplib.SMTP_SSL(os.environ["BEAD_SMTP_HOST"], int(os.getenv("BEAD_SMTP_PORT", "465")), timeout=15) as smtp:
            if os.getenv("BEAD_SMTP_USER"):
                smtp.login(os.environ["BEAD_SMTP_USER"], os.environ.get("BEAD_SMTP_PASSWORD", ""))
            smtp.send_message(message)
    except (OSError, ValueError, smtplib.SMTPException):
        raise HTTPException(502, "暂时无法投递验证码") from None


@router.get("/recovery/status")
def recovery_status():
    return {"mailEnabled": bool(mail_mode())}


def issue():
    code = secrets.token_urlsafe(32)
    return code, token_digest(code), utc_now() + timedelta(minutes=15)


def user_lock(db, user_id):
    return db.scalar(select(User).where(User.id == user_id).with_for_update().execution_options(populate_existing=True))


@router.post("/recovery/address", status_code=202)
def set_address(body: AddressInput, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    rate_limit(request, "recovery-address", 5)
    locked = user_lock(db, user.id)
    if locked.status != "active" or not valid_password(locked.password_digest, body.password):
        raise HTTPException(400, "当前密码无效")
    row = db.get(Recovery, user.id, with_for_update=True)
    if not row:
        row = Recovery(user_id=user.id)
        db.add(row)
    row.email, row.verified_at = body.email, None
    row.reset_digest = row.reset_until = None
    code, row.verify_digest, row.verify_until = issue()
    notify(row.email, "豆影邮箱验证", code)
    db.commit()
    return {"sent": True}


def valid_code(code, digest, until):
    return bool(digest and until and until > utc_now() and secrets.compare_digest(digest, token_digest(code)))


@router.post("/recovery/verify")
def verify_address(body: CodeInput, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    rate_limit(request, "recovery-verify", 8)
    row = db.get(Recovery, user.id, with_for_update=True)
    if not row or not valid_code(body.code, row.verify_digest, row.verify_until):
        raise HTTPException(400, "验证码无效或已过期")
    row.verified_at = utc_now()
    row.verify_digest = row.verify_until = None
    db.commit()
    return {"verified": True}


@router.post("/recovery/request", status_code=202)
def recover(body: UsernameInput, request: Request, db: Session = Depends(get_db)):
    block_cross_origin(request)
    rate_limit(request, "recover-request", 5)
    if not mail_mode():
        raise HTTPException(503, "邮件服务未配置")
    owner = db.scalar(select(User).where(User.username == normalized_username(body.username), User.status == "active").with_for_update())
    if owner:
        row = db.get(Recovery, owner.id, with_for_update=True)
        if row and row.verified_at:
            code, row.reset_digest, row.reset_until = issue()
            try:
                notify(row.email, "豆影密码重置", code)
            except HTTPException:
                db.rollback()
                return {"accepted": True}
            db.commit()
    return {"accepted": True}


@router.post("/recovery/reset")
def reset(body: ResetInput, request: Request, db: Session = Depends(get_db)):
    block_cross_origin(request)
    rate_limit(request, "recover-reset", 8)
    owner = db.scalar(select(User).where(User.username == normalized_username(body.username), User.status == "active").with_for_update())
    row = db.get(Recovery, owner.id, with_for_update=True) if owner else None
    if not row or not row.verified_at or not valid_code(body.code, row.reset_digest, row.reset_until):
        raise HTTPException(400, "验证码无效或已过期")
    owner.password_digest = password_hasher.hash(body.password)
    row.reset_digest = row.reset_until = None
    revoke_sessions(db, owner.id)
    db.commit()
    return {"reset": True}


@router.get("/export")
def export_account(user: User = Depends(current_user), db: Session = Depends(get_db)):
    manifest = {"account": public_user(user), "projects": [], "contents": "projects, versions, private PNG assets"}
    for project in db.scalars(select(Project).where(Project.owner_id == user.id)):
        versions = db.scalars(select(ProjectVersion).where(ProjectVersion.project_id == project.id)
                              .order_by(ProjectVersion.revision)).all()
        manifest["projects"].append({**project_info(project), "versions": [
            {**version_info(v), "project": v.data, "sourceId": v.source_id, "maskId": v.mask_id} for v in versions
        ]})
    data = io.BytesIO()
    with ZipFile(data, "w", ZIP_DEFLATED, compresslevel=3) as archive:
        archive.writestr("projects.json", json.dumps(manifest, ensure_ascii=False))
        for asset in db.scalars(select(Asset).where(Asset.owner_id == user.id)):
            path = asset_path(asset.id)
            if not path.is_file():
                raise HTTPException(409, "存在缺失资产，请检查服务器备份")
            archive.write(path, "assets/" + asset.id + ".png")
    data.seek(0)
    return StreamingResponse(data, media_type="application/zip",
                             headers={"Cache-Control": "private, no-store",
                                      "Content-Disposition": "attachment; filename=bead-account.zip"})


@router.post("/close", status_code=204)
def close_account(body: CloseInput, request: Request, response: Response,
                  user: User = Depends(current_user), db: Session = Depends(get_db)):
    rate_limit(request, "close", 5)
    if not body.acknowledge or user.role == "admin":
        raise HTTPException(400, "请确认关闭普通用户账号")
    locked = user_lock(db, user.id)
    if not valid_password(locked.password_digest, body.password):
        raise HTTPException(400, "当前密码无效")
    if not db.get(Closure, user.id):
        db.add(Closure(user_id=user.id))
    locked.status = "frozen"
    revoke_sessions(db, user.id)
    db.execute(update(Publication).where(Publication.author_id == user.id, Publication.status.in_(("published", "pending")))
               .values(status="withdrawn"))
    write_audit(db, user.id, "account.close", user.id, "本人确认关闭")
    db.commit()
    response.delete_cookie(COOKIE)
