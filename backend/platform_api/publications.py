"""Read-only public snapshots, moderation and personal favourites."""
import uuid
import io
from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import JSONResponse
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy import JSON, CheckConstraint, ForeignKey, Index, String, UniqueConstraint, func, select
from sqlalchemy.orm import Mapped, Session, defer, mapped_column

from .auth import User, current_user, optional_user, require_admin, utc_now
from .catalog import Palette, PaletteVersion, write_audit
from .db import Base, get_db
from .inventory import InventoryMovement
from .notifications import create_notice
from .projects import Project, ProjectVersion, find_project, stamp

router = APIRouter(tags=["公开图纸库"])
CATEGORIES = ("portrait", "animal", "object", "scenery", "other")
PUBLIC_PAGE_SIZE = 24
BUILTIN_BRANDS = {"pixel-perler": "Perler", "pixel-hama-midi": "Hama", "pixel-artkal-s": "Artkal",
                  "pixel-mard": "MARD", "legacy-mard220": "MARD"}


class Publication(Base):
    __tablename__ = "publications"
    __table_args__ = (
        Index("ix_publication_visibility", "status", "published_at", "id"),
        Index("ix_publication_author", "author_id", "created_at", "id"),
        CheckConstraint("status IN ('pending','published','rejected','withdrawn','removed')", name="ck_publication_status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    project_version_id: Mapped[str] = mapped_column(ForeignKey("project_versions.id"))
    title: Mapped[str] = mapped_column(String(80))
    category: Mapped[str] = mapped_column(String(24))
    brand: Mapped[str | None] = mapped_column(String(60))
    pattern: Mapped[dict] = mapped_column(JSON)
    width: Mapped[int]
    height: Mapped[int]
    bead_count: Mapped[int]
    color_count: Mapped[int]
    allow_download: Mapped[bool]
    allow_remix: Mapped[bool]
    status: Mapped[str] = mapped_column(String(12), default="pending")
    decision_reason: Mapped[str | None] = mapped_column(String(240))
    created_at: Mapped[datetime] = mapped_column(default=utc_now)
    published_at: Mapped[datetime | None]


class Favorite(Base):
    __tablename__ = "favorites"
    __table_args__ = (Index("ix_favorite_publication", "publication_id"),)

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    publication_id: Mapped[str] = mapped_column(ForeignKey("publications.id"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(default=utc_now)


class PublicationReport(Base):
    __tablename__ = "publication_reports"
    __table_args__ = (
        UniqueConstraint("user_id", "publication_id", name="uq_publication_report"),
        Index("ix_report_state", "status", "created_at", "id"),
        CheckConstraint("status IN ('pending','resolved')", name="ck_publication_report_status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    publication_id: Mapped[str] = mapped_column(ForeignKey("publications.id"))
    reason: Mapped[str] = mapped_column(String(240))
    status: Mapped[str] = mapped_column(String(12), default="pending")
    resolution: Mapped[str | None] = mapped_column(String(240))
    created_at: Mapped[datetime] = mapped_column(default=utc_now)


class PublicationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    projectId: str = Field(min_length=36, max_length=36)
    versionId: str = Field(min_length=36, max_length=36)
    title: str = Field(min_length=1, max_length=80)
    category: Literal["portrait", "animal", "object", "scenery", "other"]
    allowDownload: StrictBool = False
    allowRemix: StrictBool = False
    rightsConfirmed: StrictBool


class ReasonInput(BaseModel):
    reason: str = Field(min_length=1, max_length=240)


class ModerationInput(ReasonInput):
    action: Literal["approve", "reject", "takedown"]


def checked_text(value, message):
    text = value.strip()
    if not text:
        raise HTTPException(422, message)
    return text


def pick_public_pattern(source):
    # Do not copy palette metadata or private project fields into a public row.
    return {key: source[key] for key in ("width", "height", "cells", "palette", "colorLimit")}


def public_brand(database, source):
    palette_id = source.get("paletteId", "")
    if palette_id.startswith("db:"):
        return database.scalar(select(Palette.brand).join(PaletteVersion).where(
            PaletteVersion.id == palette_id[3:], PaletteVersion.status.in_(("published", "retired"))))
    return BUILTIN_BRANDS.get(palette_id)


def public_summary(row, nickname, favorites=0):
    return {"id": row.id, "title": row.title, "category": row.category, "brand": row.brand,
            "author": nickname, "width": row.width, "height": row.height, "beadCount": row.bead_count,
            "colorCount": row.color_count, "allowDownload": row.allow_download, "allowRemix": row.allow_remix,
            "publishedAt": stamp(row.published_at) if row.published_at else None, "favoriteCount": favorites}


def owner_summary(row):
    return {"id": row.id, "title": row.title, "category": row.category, "status": row.status,
            "reason": row.decision_reason, "createdAt": stamp(row.created_at),
            "publishedAt": stamp(row.published_at) if row.published_at else None}


def visible_publication():
    # account_tools owns the closure record and imports the publication model.
    from .account_tools import Closure
    closed = select(Closure.user_id).where(Closure.user_id == Publication.author_id).exists()
    return (Publication.status == "published") & ~closed


def find_publication(database, publication_id, *, public_only=True, lock=False):
    statement = select(Publication).where(Publication.id == publication_id)
    if public_only:
        statement = statement.where(visible_publication())
    if lock:
        statement = statement.with_for_update()
    result = database.scalar(statement)
    if result is None:
        raise HTTPException(404, "未找到作品")
    return result


@router.post("/publications", status_code=201)
def submit_publication(payload: PublicationInput, user: User = Depends(current_user), database: Session = Depends(get_db)):
    if not payload.rightsConfirmed:
        raise HTTPException(422, "请确认可公开发布此图纸")
    title = checked_text(payload.title, "标题不能为空")
    # Account closure takes the user lock before withdrawing publications.
    status = database.scalar(select(User.status).where(User.id == user.id).with_for_update())
    if status != "active":
        raise HTTPException(401, "账号当前不可用")
    project = find_project(database, user, payload.projectId, lock=True)
    version = database.scalar(select(ProjectVersion).where(ProjectVersion.id == payload.versionId,
                                                           ProjectVersion.project_id == project.id))
    if version is None:
        raise HTTPException(404, "未找到图纸版本")
    source = version.data.get("pattern")
    if not source or not version.bead_count:
        raise HTTPException(422, "请选择有拼豆格子的图纸版本")
    existing = database.scalar(select(Publication).where(
        Publication.project_version_id == version.id, Publication.status.in_(("pending", "published"))
    ).with_for_update())
    if existing:
        raise HTTPException(409, "此版本已提交或已发布")
    row = Publication(id=str(uuid.uuid4()), author_id=user.id, project_version_id=version.id, title=title,
                      category=payload.category, brand=public_brand(database, source), pattern=pick_public_pattern(source),
                      width=source["width"], height=source["height"], bead_count=version.bead_count,
                      color_count=version.color_count, allow_download=payload.allowDownload, allow_remix=payload.allowRemix)
    database.add(row)
    database.commit()
    return owner_summary(row)


@router.get("/publications")
def public_directory(
    query: str = Query("", max_length=80), brand: str = Query("", max_length=60),
    category: str = Query("", max_length=24), minWidth: int = Query(1, ge=1, le=128),
    maxWidth: int = Query(128, ge=1, le=128), minColors: int = Query(1, ge=1, le=512),
    maxColors: int = Query(512, ge=1, le=512), minBeads: int = Query(1, ge=1, le=8192),
    maxBeads: int = Query(8192, ge=1, le=8192), minHeight: int = Query(1, ge=1, le=128),
    maxHeight: int = Query(128, ge=1, le=128), sort: Literal["newest", "popular"] = "newest",
    page: int = Query(1, ge=1, le=5000), database: Session = Depends(get_db),
):
    if (category and category not in CATEGORIES) or minWidth > maxWidth or minHeight > maxHeight or minColors > maxColors or minBeads > maxBeads:
        raise HTTPException(422, "筛选范围无效")
    count = select(func.count()).where(Favorite.publication_id == Publication.id).correlate(Publication).scalar_subquery()
    statement = select(Publication, User.nickname, count).options(defer(Publication.pattern)).join(User, User.id == Publication.author_id).where(
        visible_publication(), Publication.width.between(minWidth, maxWidth),
        Publication.height.between(minHeight, maxHeight), Publication.color_count.between(minColors, maxColors),
        Publication.bead_count.between(minBeads, maxBeads),
    )
    if query.strip():
        statement = statement.where(Publication.title.contains(query.strip(), autoescape=True))
    if brand.strip():
        statement = statement.where(Publication.brand == brand.strip())
    if category:
        statement = statement.where(Publication.category == category)
    if sort == "popular":
        statement = statement.order_by(count.desc())
    rows = database.execute(statement.order_by(Publication.published_at.desc(), Publication.id.desc())
                            .offset((page - 1) * PUBLIC_PAGE_SIZE).limit(PUBLIC_PAGE_SIZE + 1)).all()
    return {"items": [public_summary(*row) for row in rows[:PUBLIC_PAGE_SIZE]], "hasMore": len(rows) > PUBLIC_PAGE_SIZE}


@router.get("/publications/{publication_id}")
def public_detail(publication_id: str, user: User | None = Depends(optional_user), database: Session = Depends(get_db)):
    row = find_publication(database, publication_id)
    nickname = database.scalar(select(User.nickname).where(User.id == row.author_id))
    count = database.scalar(select(func.count()).where(Favorite.publication_id == row.id))
    favorited = bool(user and database.get(Favorite, (user.id, row.id)))
    return {**public_summary(row, nickname, count), "previewUrl": f"/api/publications/{row.id}/preview",
            "favorited": favorited}


@router.get("/publications/{publication_id}/preview")
def preview_pattern(publication_id: str, database: Session = Depends(get_db)):
    row = find_publication(database, publication_id)
    palette = {item["code"]: item["hex"] for item in row.pattern["palette"]}
    preview = Image.new("RGBA", (row.width, row.height))
    preview.putdata([tuple(bytes.fromhex(palette[code][1:])) + (255,) if code else (0, 0, 0, 0)
                     for code in row.pattern["cells"]])
    output = io.BytesIO()
    preview.save(output, format="PNG")
    return Response(output.getvalue(), media_type="image/png", headers={"Cache-Control": "no-store"})


@router.get("/publications/{publication_id}/download")
def download_pattern(publication_id: str, database: Session = Depends(get_db)):
    row = find_publication(database, publication_id)
    if not row.allow_download:
        raise HTTPException(403, "作者未开放下载")
    return JSONResponse({"schemaVersion": 2, "pattern": row.pattern}, headers={
        "Cache-Control": "no-store", "Content-Disposition": "attachment; filename=bead-pattern.json",
    })


@router.get("/my-publications")
def my_publications(page: int = Query(1, ge=1, le=5000), user: User = Depends(current_user),
                    database: Session = Depends(get_db)):
    rows = list(database.scalars(select(Publication).where(Publication.author_id == user.id)
                                 .order_by(Publication.created_at.desc(), Publication.id.desc())
                                 .offset((page - 1) * PUBLIC_PAGE_SIZE).limit(PUBLIC_PAGE_SIZE + 1)))
    return {"items": [owner_summary(row) for row in rows[:PUBLIC_PAGE_SIZE]], "hasMore": len(rows) > PUBLIC_PAGE_SIZE}


@router.post("/publications/{publication_id}/withdraw")
def withdraw_publication(publication_id: str, user: User = Depends(current_user), database: Session = Depends(get_db)):
    row = database.scalar(select(Publication).where(Publication.id == publication_id,
                                                    Publication.author_id == user.id).with_for_update())
    if row is None:
        raise HTTPException(404, "未找到作品")
    if row.status not in ("published", "pending", "withdrawn"):
        raise HTTPException(409, "当前状态无法撤回")
    if row.status != "withdrawn":
        row.status = "withdrawn"
        row.decision_reason = None
        database.commit()
    return owner_summary(row)


@router.put("/publications/{publication_id}/favorite", status_code=204)
def favorite_pattern(publication_id: str, user: User = Depends(current_user), database: Session = Depends(get_db)):
    row = find_publication(database, publication_id, lock=True)
    existing = database.scalar(select(Favorite).where(Favorite.user_id == user.id, Favorite.publication_id == row.id).with_for_update())
    if existing is None:
        database.add(Favorite(user_id=user.id, publication_id=row.id))
        if row.author_id != user.id:
            create_notice(database, row.author_id, "favorite", row.id, "你的图纸收到新收藏")
        database.commit()
    return Response(status_code=204)


@router.delete("/publications/{publication_id}/favorite", status_code=204)
def unfavorite_pattern(publication_id: str, user: User = Depends(current_user), database: Session = Depends(get_db)):
    row = database.get(Favorite, (user.id, publication_id))
    if row is not None:
        database.delete(row)
        database.commit()
    return Response(status_code=204)


@router.get("/favorites")
def my_favorites(page: int = Query(1, ge=1, le=5000), user: User = Depends(current_user),
                 database: Session = Depends(get_db)):
    rows = database.execute(select(Publication, User.nickname).options(defer(Publication.pattern)).select_from(Publication)
                            .join(Favorite, Favorite.publication_id == Publication.id)
                            .join(User, User.id == Publication.author_id)
                            .where(Favorite.user_id == user.id, visible_publication())
                            .order_by(Favorite.created_at.desc(), Favorite.publication_id.desc())
                            .offset((page - 1) * PUBLIC_PAGE_SIZE).limit(PUBLIC_PAGE_SIZE + 1)).all()
    return {"items": [public_summary(*row) for row in rows[:PUBLIC_PAGE_SIZE]], "hasMore": len(rows) > PUBLIC_PAGE_SIZE}


@router.post("/publications/{publication_id}/report", status_code=201)
def report_publication(publication_id: str, payload: ReasonInput, user: User = Depends(current_user),
                       database: Session = Depends(get_db)):
    row = find_publication(database, publication_id, lock=True)
    if row.author_id == user.id:
        raise HTTPException(422, "可在我的作品中直接撤回自己的图纸")
    existing = database.scalar(select(PublicationReport).where(PublicationReport.user_id == user.id,
                            PublicationReport.publication_id == row.id).with_for_update())
    if existing:
        return {"id": existing.id, "status": existing.status}
    report = PublicationReport(id=str(uuid.uuid4()), user_id=user.id, publication_id=row.id,
                               reason=checked_text(payload.reason, "请填写举报原因"))
    database.add(report)
    database.commit()
    return {"id": report.id, "status": report.status}


@router.get("/admin/publications")
def moderation_queue(status: Literal["pending", "published", "rejected", "withdrawn", "removed"] = "pending",
                     page: int = Query(1, ge=1, le=5000), admin: User = Depends(require_admin),
                     database: Session = Depends(get_db)):
    rows = database.execute(select(Publication, User.nickname).join(User, Publication.author_id == User.id)
                            .where(Publication.status == status).order_by(Publication.created_at.desc(), Publication.id.desc())
                            .offset((page - 1) * PUBLIC_PAGE_SIZE).limit(PUBLIC_PAGE_SIZE + 1)).all()
    return {"items": [{**public_summary(row, nickname), **owner_summary(row), "pattern": row.pattern}
                       for row, nickname in rows[:PUBLIC_PAGE_SIZE]], "hasMore": len(rows) > PUBLIC_PAGE_SIZE}


@router.post("/admin/publications/{publication_id}/moderate")
def moderate_publication(publication_id: str, payload: ModerationInput, admin: User = Depends(require_admin),
                         database: Session = Depends(get_db)):
    reason = checked_text(payload.reason, "请填写审核原因")
    author_id = database.scalar(select(Publication.author_id).where(Publication.id == publication_id))
    if author_id is None:
        raise HTTPException(404, "未找到作品")
    author_status = database.scalar(select(User.status).where(User.id == author_id).with_for_update())
    if payload.action == "approve" and author_status != "active":
        raise HTTPException(409, "作者账号当前不可用")
    row = find_publication(database, publication_id, public_only=False, lock=True)
    initial, target = {"approve": ("pending", "published"), "reject": ("pending", "rejected"),
                       "takedown": ("published", "removed")}[payload.action]
    if row.status != initial:
        raise HTTPException(409, "作品状态已变化，请刷新审核列表")
    row.status, row.decision_reason = target, reason
    if target == "published":
        row.published_at = utc_now()
    write_audit(database, admin.id, f"publication.{payload.action}", row.id, reason)
    message = {"approve": "你的图纸已通过审核", "reject": "你的图纸审核未通过", "takedown": "你的图纸已被下架"}[payload.action]
    create_notice(database, row.author_id, "moderation", row.id, message)
    database.commit()
    return owner_summary(row)


@router.get("/admin/publication-reports")
def list_reports(page: int = Query(1, ge=1, le=5000), admin: User = Depends(require_admin),
                 database: Session = Depends(get_db)):
    rows = database.execute(select(PublicationReport, Publication.title).join(Publication)
                            .where(PublicationReport.status == "pending")
                            .order_by(PublicationReport.created_at, PublicationReport.id)
                            .offset((page - 1) * PUBLIC_PAGE_SIZE).limit(PUBLIC_PAGE_SIZE + 1)).all()
    return {"items": [{"id": row.id, "publicationId": row.publication_id, "title": title,
                       "reason": row.reason, "createdAt": stamp(row.created_at)}
                      for row, title in rows[:PUBLIC_PAGE_SIZE]], "hasMore": len(rows) > PUBLIC_PAGE_SIZE}


@router.post("/admin/publication-reports/{report_id}/resolve")
def resolve_report(report_id: str, payload: ReasonInput, admin: User = Depends(require_admin),
                   database: Session = Depends(get_db)):
    row = database.scalar(select(PublicationReport).where(PublicationReport.id == report_id).with_for_update())
    if row is None:
        raise HTTPException(404, "举报记录不存在")
    if row.status != "pending":
        raise HTTPException(409, "此举报已处理")
    row.status = "resolved"
    row.resolution = checked_text(payload.reason, "请填写处理原因")
    write_audit(database, admin.id, "publication.report.resolve", row.id, row.resolution)
    database.commit()
    return {"id": row.id, "status": row.status}


@router.get("/admin/overview")
def admin_overview(days: int = Query(7, ge=1, le=365), admin: User = Depends(require_admin),
                   database: Session = Depends(get_db)):
    # Existing MySQL DATETIME columns round writes to the nearest second.
    until = (utc_now() + timedelta(microseconds=500_000)).replace(microsecond=0)
    since = until - timedelta(days=days)

    def count(model, *filters):
        return database.scalar(select(func.count()).select_from(model).where(*filters))

    return {
        "since": stamp(since), "until": stamp(until),
        "activeAccounts": count(User, User.status == "active"),
        "savedProjects": count(Project, Project.deleted_at.is_(None)),
        "pendingPublications": count(Publication, Publication.status == "pending"),
        "pendingReports": count(PublicationReport, PublicationReport.status == "pending"),
        "newAccounts": count(User, User.created_at.between(since, until)),
        "recentInventoryMovements": count(InventoryMovement, InventoryMovement.created_at.between(since, until)),
        "recentPublished": count(Publication, Publication.status == "published", Publication.published_at.between(since, until)),
    }
