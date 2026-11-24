"""Durable, opt-in image editing jobs and per-account quota."""
from datetime import datetime, timedelta
from typing import Literal
import base64
import io
import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from PIL import Image
from pydantic import BaseModel, Field
from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column

import ai_images
from .auth import User, current_user, require_admin
from .catalog import write_audit
from .db import Base, get_db, session_factory
from .projects import Asset, USER_BUDGET, asset_path, find_asset, now, stamp

router = APIRouter(prefix='/ai')


class AIQuota(Base):
    __tablename__ = 'ai_quotas'
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), primary_key=True)
    remaining: Mapped[int] = mapped_column(Integer, default=0)
    reserved: Mapped[int] = mapped_column(Integer, default=0)
    used: Mapped[int] = mapped_column(Integer, default=0)


class AIJob(Base):
    __tablename__ = 'ai_jobs'
    __table_args__ = (UniqueConstraint('user_id', 'request_id', name='uq_ai_job_request'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    request_id: Mapped[str] = mapped_column(String(36))
    input_id: Mapped[str] = mapped_column(ForeignKey('assets.id'))
    output_id: Mapped[str | None] = mapped_column(ForeignKey('assets.id'))
    provider: Mapped[str] = mapped_column(String(16))
    prompt: Mapped[str] = mapped_column(String(1000))
    status: Mapped[str] = mapped_column(String(24), index=True)
    error: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class QuotaEvent(Base):
    __tablename__ = 'ai_quota_events'
    __table_args__ = (UniqueConstraint('user_id', 'request_id', name='uq_ai_quota_request'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    job_id: Mapped[str | None] = mapped_column(ForeignKey('ai_jobs.id'))
    request_id: Mapped[str] = mapped_column(String(60))
    action: Mapped[str] = mapped_column(String(20))
    quantity: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


def provider():
    if os.getenv('BEAD_AI_SIMULATION') == '1':
        return 'simulation'
    if os.getenv('BEAD_AI_PLATFORM_LIVE') == '1' and ai_images.settings()[0]:
        return 'bailian'
    return None


@router.get('/capabilities')
def capabilities():
    selected = provider()
    return {'available': bool(selected), 'provider': selected, 'model': ai_images.MODEL if selected == 'bailian' else None}


class JobRequest(BaseModel):
    assetId: str = Field(min_length=36, max_length=36)
    requestId: str = Field(pattern=r'^[A-Za-z0-9-]{36}$')
    prompt: str = Field(min_length=1, max_length=1000)
    consent: Literal[True]
    provider: Literal['simulation', 'bailian']


class QuotaGrant(BaseModel):
    requestId: str = Field(pattern=r'^[A-Za-z0-9-]{36}$')
    count: int = Field(ge=1, le=1000)


class ReconcileRequest(BaseModel):
    billed: bool
    reason: str = Field(min_length=2, max_length=200)


def event(db, user_id, action, quantity, request_id, job_id=None):
    db.add(QuotaEvent(id=str(uuid.uuid4()), user_id=user_id, job_id=job_id, request_id=request_id,
                      action=action, quantity=quantity))


def quota_row(db, user_id):
    owner = db.scalar(select(User).where(User.id == user_id).with_for_update())
    if not owner:
        raise HTTPException(404, '账号不存在')
    quota = db.scalar(select(AIQuota).where(AIQuota.user_id == user_id).with_for_update())
    if quota is None:
        quota = AIQuota(user_id=user_id, remaining=0, reserved=0, used=0)
        db.add(quota)
    return quota


def quota_info(quota):
    return {key: getattr(quota, key) if quota else 0 for key in ('remaining', 'reserved', 'used')}


def job_info(job):
    return {'id': job.id, 'inputId': job.input_id, 'outputId': job.output_id, 'provider': job.provider,
            'status': job.status, 'error': job.error, 'createdAt': stamp(job.created_at)}


@router.get('/quota')
def get_quota(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return quota_info(db.get(AIQuota, user.id))


@router.post('/admin/quota/{user_id}')
def grant(user_id: str, body: QuotaGrant, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    quota = quota_row(db, user_id)
    prior = db.scalar(select(QuotaEvent).where(QuotaEvent.user_id == user_id, QuotaEvent.request_id == body.requestId)
                      .with_for_update())
    if prior:
        if prior.action != 'grant' or prior.quantity != body.count:
            raise HTTPException(409, '此编号已用于其他额度操作')
        return quota_info(quota)
    quota.remaining += body.count
    event(db, user_id, 'grant', body.count, body.requestId)
    write_audit(db, admin.id, 'ai.grant', user_id, str(body.count))
    db.commit()
    return quota_info(quota)


@router.post('/jobs', status_code=201)
def create_job(body: JobRequest, user: User = Depends(current_user), db: Session = Depends(get_db)):
    selected = provider()
    if not selected:
        raise HTTPException(503, '尚未启用图片重绘服务')
    quota = quota_row(db, user.id)
    prior = db.scalar(select(AIJob).where(AIJob.user_id == user.id, AIJob.request_id == body.requestId).with_for_update())
    if prior:
        if prior.input_id != body.assetId or prior.prompt != body.prompt or prior.provider != body.provider:
            raise HTTPException(409, '此编号已用于其他生成请求')
        return job_info(prior)
    if selected != body.provider:
        raise HTTPException(409, '重绘服务已变化，请重新查看并确认')
    asset = find_asset(db, user, body.assetId)
    if asset.kind != 'source' or asset.size > ai_images.LIMIT:
        raise HTTPException(422, '请选择10MB以内的原图')
    if quota.remaining < 1:
        raise HTTPException(409, '可用重绘次数不足')
    if quota.reserved >= 3:
        raise HTTPException(429, '已有多个任务等待处理或核对')
    quota.remaining -= 1
    quota.reserved += 1
    job = AIJob(id=str(uuid.uuid4()), user_id=user.id, request_id=body.requestId, input_id=asset.id,
                provider=selected, prompt=body.prompt, status='queued')
    db.add(job)
    db.flush()
    event(db, user.id, 'reserve', 1, job.id + ':reserve', job.id)
    db.commit()
    return job_info(job)


@router.get('/jobs')
def list_jobs(page: int = Query(1, ge=1, le=5000), user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(AIJob).where(AIJob.user_id == user.id)
                      .order_by(AIJob.created_at.desc(), AIJob.id.desc()).offset((page - 1) * 20).limit(21)).all()
    return {'items': [job_info(row) for row in rows[:20]], 'hasMore': len(rows) > 20}


def settle(db, job, quota, status, error=None):
    job.status, job.error, job.updated_at = status, error, now()
    if status == 'unknown':
        return
    quota.reserved -= 1
    if status in ('succeeded', 'billed'):
        quota.used += 1
        action = 'consume'
    else:
        quota.remaining += 1
        action = 'release'
    event(db, job.user_id, action, 1, job.id + ':' + action, job.id)


@router.get('/admin/unknown')
def unknown_jobs(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    rows = db.scalars(select(AIJob).where(AIJob.status == 'unknown').order_by(AIJob.updated_at.desc()).limit(50))
    return [{'id': row.id, 'userId': row.user_id, 'provider': row.provider, 'error': row.error,
             'createdAt': stamp(row.created_at)} for row in rows]


@router.post('/admin/jobs/{job_id}/reconcile')
def reconcile(job_id: str, body: ReconcileRequest, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    owner = db.scalar(select(AIJob.user_id).where(AIJob.id == job_id))
    if owner is None:
        raise HTTPException(404, '未找到重绘任务')
    quota = quota_row(db, owner)
    job = db.scalar(select(AIJob).where(AIJob.id == job_id).with_for_update())
    if job.status != 'unknown':
        raise HTTPException(409, '任务状态已变化')
    if not body.reason.strip():
        raise HTTPException(422, '请填写核对依据')
    settle(db, job, quota, 'billed' if body.billed else 'failed', '管理员已核对')
    write_audit(db, admin.id, 'ai.reconcile', job.id, body.reason.strip())
    db.commit()
    return {'id': job.id, 'status': job.status}


@router.post('/jobs/{job_id}/cancel')
def cancel(job_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    quota = quota_row(db, user.id)
    job = db.scalar(select(AIJob).where(AIJob.id == job_id, AIJob.user_id == user.id).with_for_update())
    if not job:
        raise HTTPException(404, '未找到重绘任务')
    if job.status == 'queued':
        settle(db, job, quota, 'cancelled')
    elif job.status == 'running':
        job.status = 'cancel_requested'
    db.commit()
    return job_info(job)


def run_one():
    """Claim in one short transaction, call the provider outside it, settle in another."""
    active = provider()
    factory = session_factory()
    with factory() as db:
        timestamp = now()
        for stale in db.scalars(select(AIJob).where(
            AIJob.status.in_(('running', 'cancel_requested')), AIJob.updated_at < timestamp - timedelta(minutes=30)
        ).limit(8).with_for_update(skip_locked=True)):
            stale.status = 'unknown'
            stale.error = '任务意外中断，等待人工核对'
        db.commit()
        if not active:
            return
        job = db.scalar(select(AIJob).join(User, User.id == AIJob.user_id)
                        .where(AIJob.status == 'queued', AIJob.provider == active, User.status == 'active')
                        .order_by(AIJob.created_at, AIJob.id).limit(1).with_for_update(skip_locked=True))
        if not job:
            return
        job.status, job.updated_at = 'running', now()
        db.commit()
        job_id, owner, input_id, prompt = job.id, job.user_id, job.input_id, job.prompt
    status, error, result = 'failed', '输入图片无法读取', None
    try:
        raw = asset_path(input_id).read_bytes()
        if active == 'simulation':
            with Image.open(io.BytesIO(raw)) as image:
                rgba = image.convert('RGBA')
                size = rgba.size
                rgba.thumbnail((48, 48))
                zoom = rgba.resize(size, Image.Resampling.NEAREST)
                stream = io.BytesIO()
                zoom.save(stream, format='PNG')
                result = stream.getvalue()
        else:
            status, error = 'unknown', '上游结果未确认，请先核对服务商账单'
            response = ai_images.edit(ai_images.EditRequest(
                image='data:image/png;base64,' + base64.b64encode(raw).decode('ascii'), prompt=prompt, consent=True))
            result = base64.b64decode(response['image'].split(',', 1)[1], validate=True)
        status, error = 'succeeded', None
    except (HTTPException, OSError, ValueError):
        pass
    with factory() as db:
        quota = quota_row(db, owner)
        job = db.scalar(select(AIJob).where(AIJob.id == job_id).with_for_update())
        if not job or job.status not in ('running', 'cancel_requested'):
            return
        if result is not None:
            try:
                sizes = db.scalars(select(Asset.size).where(Asset.owner_id == owner).with_for_update()).all()
                if len(sizes) >= 512 or sum(sizes) + len(result) > USER_BUDGET:
                    raise ValueError()
                with Image.open(io.BytesIO(result)) as image:
                    width, height = image.size
                asset_id = str(uuid.uuid4())
                target = asset_path(asset_id)
                with target.open('xb') as stream:
                    stream.write(result)
                db.add(Asset(id=asset_id, owner_id=owner, kind='source', size=len(result), width=width, height=height))
                db.flush()
                job.output_id = asset_id
            except (OSError, ValueError):
                status = 'unknown' if active == 'bailian' else 'failed'
                error = '结果未能保存，请核对账号空间和供应商状态'
        settle(db, job, quota, status, error)
        db.commit()
