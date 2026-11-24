import csv
import io
import re
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, String, UniqueConstraint, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from .auth import User, public_user, require_admin, revoke_sessions, utc_now
from .db import Base, get_db

router = APIRouter(tags=["色卡与管理"])
COLOR_CODE = re.compile(r"[A-Za-z0-9_.-]{1,32}")
HEX = re.compile(r"#[A-Fa-f0-9]{6}")


class Palette(Base):
    __tablename__ = "palettes"
    __table_args__ = (UniqueConstraint("brand", "series", "size_mm", name="uq_palette_identity"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    brand: Mapped[str] = mapped_column(String(60))
    series: Mapped[str] = mapped_column(String(60))
    size_mm: Mapped[Decimal] = mapped_column(Numeric(5, 2))


class PaletteVersion(Base):
    __tablename__ = "palette_versions"
    __table_args__ = (
        UniqueConstraint("palette_id", "label", name="uq_palette_label"),
        CheckConstraint("status IN ('draft','published','retired')", name="ck_palette_version_status"),
        Index("ix_palette_version_state", "palette_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    palette_id: Mapped[str] = mapped_column(ForeignKey("palettes.id"))
    label: Mapped[str] = mapped_column(String(80))
    source: Mapped[str] = mapped_column(String(800))
    license_status: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(12), default="draft")
    created_at: Mapped[datetime] = mapped_column(default=utc_now)


class PaletteColor(Base):
    __tablename__ = "palette_colors"
    __table_args__ = (
        UniqueConstraint("version_id", "code", name="uq_palette_code"),
        UniqueConstraint("version_id", "stable_color_key", name="uq_palette_stable_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    version_id: Mapped[str] = mapped_column(ForeignKey("palette_versions.id"))
    code: Mapped[str] = mapped_column(String(32, collation="utf8mb4_bin"))
    hex: Mapped[str] = mapped_column(String(7))
    material: Mapped[str] = mapped_column(String(60))
    stable_color_key: Mapped[str] = mapped_column(String(36))


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_created", "created_at", "id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(45))
    target_id: Mapped[str] = mapped_column(String(36))
    summary: Mapped[str] = mapped_column(String(240))
    created_at: Mapped[datetime] = mapped_column(default=utc_now)


class PaletteInput(BaseModel):
    brand: str = Field(min_length=1, max_length=60)
    series: str = Field(min_length=1, max_length=60)
    sizeMm: Decimal = Field(gt=0, le=50, max_digits=5, decimal_places=2)


class ImportInput(BaseModel):
    version: str = Field(min_length=1, max_length=80)
    source: HttpUrl
    licenseStatus: Literal["unknown", "open", "permission", "internal"] = "unknown"
    csv: str = Field(min_length=1, max_length=64_000)
    reuseColorCodes: list[str] = Field(default_factory=list, max_length=512)


class UserPatch(BaseModel):
    status: Literal["active", "frozen"]
    reason: str = Field(min_length=1, max_length=180)


def write_audit(database: Session, actor_id: str, action: str, target_id: str, summary: str):
    database.add(AuditLog(actor_id=actor_id, action=action, target_id=target_id, summary=summary))


def version_data(version: PaletteVersion, palette: Palette):
    return {
        "id": version.id,
        "paletteId": palette.id,
        "brand": palette.brand,
        "series": palette.series,
        "sizeMm": float(palette.size_mm),
        "version": version.label,
        "source": version.source,
        "licenseStatus": version.license_status,
        "status": version.status,
    }


def get_version(database: Session, version_id: str, allow_draft: bool = False):
    stmt = select(PaletteVersion, Palette).join(Palette).where(PaletteVersion.id == version_id)
    if not allow_draft:
        stmt = stmt.where(PaletteVersion.status.in_(("published", "retired")))
    row = database.execute(stmt).one_or_none()
    if not row:
        raise HTTPException(404, "未找到色卡版本")
    return row


def get_colors(database: Session, version_id: str):
    return list(database.scalars(select(PaletteColor).where(PaletteColor.version_id == version_id).order_by(PaletteColor.id)))


def full_version(database: Session, version: PaletteVersion, palette: Palette):
    result = version_data(version, palette)
    result["colors"] = [
        {"code": item.code, "hex": item.hex, "material": item.material, "stableColorKey": item.stable_color_key}
        for item in get_colors(database, version.id)
    ]
    return result


@router.get("/palettes")
def published_palettes(database: Session = Depends(get_db)):
    versions = database.execute(
        select(PaletteVersion, Palette).join(Palette).where(PaletteVersion.status == "published")
        .order_by(Palette.brand, Palette.series, Palette.size_mm)
    ).all()
    return [version_data(version, palette) for version, palette in versions]


@router.get("/palettes/{version_id}")
def published_palette(version_id: str, database: Session = Depends(get_db)):
    return full_version(database, *get_version(database, version_id))


@router.get("/admin/palettes")
def all_palettes(admin: User = Depends(require_admin), database: Session = Depends(get_db)):
    palettes = list(database.scalars(select(Palette).order_by(Palette.brand, Palette.series, Palette.size_mm)))
    versions = database.execute(select(PaletteVersion).order_by(PaletteVersion.created_at.desc())).scalars()
    grouped = {}
    for version in versions:
        grouped.setdefault(version.palette_id, []).append(version)
    return [{"id": p.id, "brand": p.brand, "series": p.series, "sizeMm": float(p.size_mm),
             "versions": [version_data(v, p) for v in grouped.get(p.id, [])]} for p in palettes]


@router.post("/admin/palettes", status_code=201)
def add_palette(payload: PaletteInput, admin: User = Depends(require_admin), database: Session = Depends(get_db)):
    brand, series = payload.brand.strip(), payload.series.strip()
    if not brand or not series:
        raise HTTPException(422, "品牌与系列不能为空")
    palette = Palette(id=str(uuid.uuid4()), brand=brand, series=series, size_mm=payload.sizeMm)
    database.add(palette)
    write_audit(database, admin.id, "palette.create", palette.id, "创建色卡系列")
    try:
        database.commit()
    except IntegrityError:
        raise HTTPException(409, "同品牌、系列和规格的色卡已存在") from None
    return {"id": palette.id, "brand": brand, "series": series, "sizeMm": float(payload.sizeMm), "versions": []}


def parse_colors(data: str):
    try:
        reader = csv.DictReader(io.StringIO(data.lstrip("\ufeff"), newline=""), strict=True)
        headings = reader.fieldnames or []
        if len(set(headings)) != len(headings) or not {"code", "hex"} <= set(headings) <= {"code", "hex", "material"}:
            raise HTTPException(422, "CSV 列应为 code,hex 或 code,hex,material")
        colors = {}
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise HTTPException(422, f"第 {reader.line_num} 行列数错误")
            code = row["code"].strip()
            value = row["hex"].strip().upper()
            material = row.get("material", "").strip() or "unknown"
            if (not COLOR_CODE.fullmatch(code) or code in {"__proto__", "prototype", "constructor"}
                    or not HEX.fullmatch(value) or len(material) > 60):
                raise HTTPException(422, f"第 {reader.line_num} 行色号、HEX 或材质格式无效")
            if code in colors:
                raise HTTPException(422, f"第 {reader.line_num} 行色号重复")
            colors[code] = (value, material)
            if len(colors) > 512:
                raise HTTPException(422, "每版色卡最多 512 色")
    except csv.Error:
        raise HTTPException(422, "CSV 无法解析") from None
    if not colors:
        raise HTTPException(422, "色卡不能为空")
    return colors


def import_plan(database: Session, palette_id: str, payload: ImportInput):
    palette = database.scalar(select(Palette).where(Palette.id == palette_id).with_for_update())
    if palette is None:
        raise HTTPException(404, "色卡系列不存在")
    if not payload.version.strip() or len(str(payload.source)) > 800:
        raise HTTPException(422, "版本名或来源地址无效")
    colors = parse_colors(payload.csv)
    previous = database.scalar(select(PaletteVersion).where(
        PaletteVersion.palette_id == palette_id, PaletteVersion.status == "published"
    ).with_for_update())
    old = {color.code: color for color in get_colors(database, previous.id)} if previous else {}
    reuse = set(payload.reuseColorCodes)
    if reuse - (colors.keys() & old.keys()):
        raise HTTPException(422, "只能确认沿用新旧版本中均存在的色号身份")
    diff = {"added": sorted(colors.keys() - old.keys()), "removed": sorted(old.keys() - colors.keys()),
            "changed": sorted(code for code in old.keys() & colors.keys()
                              if colors[code] != (old[code].hex, old[code].material)),
            "reused": sorted(reuse), "previousVersionId": previous.id if previous else None}
    return palette, colors, old, reuse, diff


@router.post("/admin/palettes/{palette_id}/preview")
def preview_palette(palette_id: str, payload: ImportInput, admin: User = Depends(require_admin),
                    database: Session = Depends(get_db)):
    _, colors, _, _, diff = import_plan(database, palette_id, payload)
    return {"count": len(colors), "diff": diff}


@router.post("/admin/palettes/{palette_id}/versions", status_code=201)
def import_palette(palette_id: str, payload: ImportInput, admin: User = Depends(require_admin),
                   database: Session = Depends(get_db)):
    palette, colors, old, reuse, diff = import_plan(database, palette_id, payload)
    version = PaletteVersion(id=str(uuid.uuid4()), palette_id=palette.id, label=payload.version.strip(),
                             source=str(payload.source), license_status=payload.licenseStatus)
    database.add(version)
    try:
        database.flush()
        for code, (value, material) in colors.items():
            key = old[code].stable_color_key if code in reuse else str(uuid.uuid4())
            database.add(PaletteColor(version_id=version.id, code=code, hex=value, material=material, stable_color_key=key))
        write_audit(database, admin.id, "palette.import", version.id, f"导入 {len(colors)} 个颜色")
        database.commit()
    except IntegrityError:
        raise HTTPException(409, "该系列已有同名色卡版本") from None
    return {**full_version(database, version, palette), "diff": diff}


def lock_version(database: Session, version_id: str):
    version, _ = get_version(database, version_id, allow_draft=True)
    palette = database.scalar(select(Palette).where(Palette.id == version.palette_id).with_for_update())
    version = database.scalar(select(PaletteVersion).where(PaletteVersion.id == version_id)
                              .with_for_update().execution_options(populate_existing=True))
    return version, palette


@router.post("/admin/palette-versions/{version_id}/publish")
def publish_palette(version_id: str, admin: User = Depends(require_admin), database: Session = Depends(get_db)):
    version, palette = lock_version(database, version_id)
    if version.status != "draft":
        raise HTTPException(409, "仅草稿可发布")
    previous = database.scalar(select(PaletteVersion).where(
        PaletteVersion.palette_id == palette.id, PaletteVersion.status == "published"
    ).with_for_update())
    if previous:
        previous.status = "retired"
    version.status = "published"
    write_audit(database, admin.id, "palette.publish", version.id, "发布新色卡版本")
    database.commit()
    return version_data(version, palette)


@router.post("/admin/palette-versions/{version_id}/retire")
def retire_palette(version_id: str, admin: User = Depends(require_admin), database: Session = Depends(get_db)):
    version, palette = lock_version(database, version_id)
    if version.status != "published":
        raise HTTPException(409, "仅已发布的版本可停用")
    version.status = "retired"
    write_audit(database, admin.id, "palette.retire", version.id, "停用色卡版本")
    database.commit()
    return version_data(version, palette)


@router.get("/admin/users")
def list_users(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0),
               admin: User = Depends(require_admin), database: Session = Depends(get_db)):
    users = database.scalars(select(User).order_by(User.created_at.desc(), User.id).offset(offset).limit(limit))
    return [public_user(user) for user in users]


@router.patch("/admin/users/{user_id}")
def set_user_status(user_id: str, payload: UserPatch, admin: User = Depends(require_admin),
                    database: Session = Depends(get_db)):
    user = database.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None:
        raise HTTPException(404, "用户不存在")
    if user.role == "admin":
        raise HTTPException(403, "管理员账号须由运维处理")
    if payload.status == "active":
        from .account_tools import Closure
        if database.get(Closure, user.id):
            raise HTTPException(409, "已主动关闭的账号请按档案恢复流程处理")
    reason = payload.reason.strip()
    if not reason:
        raise HTTPException(422, "请填写操作原因")
    if user.status != payload.status:
        user.status = payload.status
        revoke_sessions(database, user.id)
        write_audit(database, admin.id, f"user.{user.status}", user.id, reason)
        database.commit()
    return public_user(user)


@router.get("/admin/audit")
def audit_log(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0),
              admin: User = Depends(require_admin), database: Session = Depends(get_db)):
    entries = database.scalars(select(AuditLog).order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).offset(offset).limit(limit))
    return [{"id": row.id, "actorId": row.actor_id, "action": row.action, "targetId": row.target_id,
             "summary": row.summary, "createdAt": row.created_at.isoformat() + "Z"} for row in entries]
