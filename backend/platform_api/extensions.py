"""Inventory-aware design helpers, finished pieces and authorized remixing."""
import uuid
from datetime import datetime

import cv2
import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from sqlalchemy import ForeignKey, String, select
from sqlalchemy.orm import Mapped, Session, defer, mapped_column

from .auth import User, current_user, utc_now
from .builds import find_build
from .catalog import PaletteColor, get_version
from .db import Base, get_db
from .inventory import InventoryItem, matched_colors, owner_lock
from .projects import Project, ProjectVersion, find_asset, find_project, project_info, stamp
from .publications import Publication, find_publication, public_summary

router = APIRouter(tags=["制作扩展"])


class BuildCompletion(Base):
    __tablename__ = "build_completions"

    build_id: Mapped[str] = mapped_column(ForeignKey("builds.id", ondelete="CASCADE"), primary_key=True)
    photo_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id"))
    minutes: Mapped[int]
    note: Mapped[str] = mapped_column(String(2000))
    updated_at: Mapped[datetime] = mapped_column(default=utc_now)


class ProjectRemix(Base):
    __tablename__ = "project_remixes"

    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), primary_key=True)
    publication_id: Mapped[str] = mapped_column(ForeignKey("publications.id"))
    title: Mapped[str] = mapped_column(String(80))
    author: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(default=utc_now)


class CompletionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    minutes: StrictInt = Field(ge=0, le=525600)
    note: str = Field(default="", max_length=2000)
    photoId: str | None = Field(default=None, min_length=36, max_length=36)


class RemixInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requestId: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")


def available_stock(database, user, version_id):
    rows = database.execute(select(PaletteColor, InventoryItem.quantity)
                            .join(InventoryItem, InventoryItem.stable_color_key == PaletteColor.stable_color_key)
                            .where(PaletteColor.version_id == version_id, InventoryItem.user_id == user.id,
                                   InventoryItem.quantity > 0)
                            .order_by(PaletteColor.code)).all()
    return [{"code": color.code, "hex": color.hex, "quantity": quantity} for color, quantity in rows]


@router.get("/inventory/available-colors/{version_id}")
def stocked_colors(version_id: str, user: User = Depends(current_user), database: Session = Depends(get_db)):
    get_version(database, version_id)
    return {"versionId": version_id, "colors": available_stock(database, user, version_id)}


def to_lab(hex_values):
    rgb = np.array([[int(value[num:num + 2], 16) / 255 for num in (1, 3, 5)] for value in hex_values],
                   dtype=np.float32)
    return cv2.cvtColor(rgb.reshape(1, -1, 3), cv2.COLOR_RGB2LAB)[0]


@router.get("/projects/{project_id}/versions/{revision}/substitutions/{code}")
def substitutions(project_id: str, revision: int, code: str, user: User = Depends(current_user),
                  database: Session = Depends(get_db)):
    project = find_project(database, user, project_id)
    version = database.scalar(select(ProjectVersion).where(ProjectVersion.project_id == project.id,
                                                           ProjectVersion.revision == revision))
    if version is None or code not in version.counts:
        raise HTTPException(404, "图纸版本未使用此颜色")
    if code in version.data.get("locked", []):
        raise HTTPException(409, "此色已锁定")
    pattern = version.data["pattern"]
    if code not in matched_colors(database, pattern):
        raise HTTPException(409, "此色未匹配到数据库色卡")
    source = next(color["hex"] for color in pattern["palette"] if color["code"] == code)
    options = [row for row in available_stock(database, user, pattern["paletteId"][3:]) if row["code"] != code]
    if options:
        units = to_lab([source] + [row["hex"] for row in options])
        distances = np.linalg.norm(units[1:] - units[0], axis=1)
        for row, distance in zip(options, distances):
            row["distance"] = round(float(distance), 3)
        options.sort(key=lambda row: (row["distance"], row["code"]))
    return {"sourceCode": code, "affectedCells": version.counts[code], "options": options[:10]}


def completion_info(completion):
    return {"minutes": completion.minutes, "note": completion.note, "photoId": completion.photo_id,
            "updatedAt": stamp(completion.updated_at)}


@router.get("/builds/{build_id}/completion")
def get_completion(build_id: str, user: User = Depends(current_user), database: Session = Depends(get_db)):
    find_build(database, user, build_id)
    completion = database.get(BuildCompletion, build_id)
    return {"completion": completion_info(completion) if completion else None}


@router.put("/builds/{build_id}/completion")
def save_completion(build_id: str, payload: CompletionInput, user: User = Depends(current_user),
                    database: Session = Depends(get_db)):
    build = find_build(database, user, build_id, lock=True)
    if build.completed_beads < build.bead_count:
        raise HTTPException(409, "完成全部板块后即可保存成品档案")
    if payload.photoId and find_asset(database, user, payload.photoId).kind != "finished":
        raise HTTPException(422, "请选择已上传的成品照片")
    completion = database.scalar(select(BuildCompletion).where(BuildCompletion.build_id == build.id).with_for_update())
    if completion is None:
        completion = BuildCompletion(build_id=build.id)
        database.add(completion)
    completion.minutes = payload.minutes
    completion.note = payload.note.strip()
    completion.photo_id = payload.photoId
    completion.updated_at = utc_now()
    database.commit()
    return {"completion": completion_info(completion)}


def isolated_colors(pattern):
    cells, width, height = pattern["cells"], pattern["width"], pattern["height"]
    isolated = 0
    for index, color in enumerate(cells):
        if color is None:
            continue
        x, y = index % width, index // width
        neighbors = ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1))
        if all(cells[ny * width + nx] != color for nx, ny in neighbors if 0 <= nx < width and 0 <= ny < height):
            isolated += 1
    return isolated


@router.get("/publications/{publication_id}/difficulty")
def difficulty(publication_id: str, database: Session = Depends(get_db)):
    row = find_publication(database, publication_id)
    return {"beadCount": row.bead_count, "colorCount": row.color_count, "isolatedCount": isolated_colors(row.pattern)}


@router.get("/publications/{publication_id}/related")
def related(publication_id: str, database: Session = Depends(get_db)):
    row = find_publication(database, publication_id)
    peers = database.execute(select(Publication, User.nickname).options(defer(Publication.pattern))
                             .join(User, User.id == Publication.author_id)
                             .where(Publication.id != row.id, Publication.status == "published",
                                    Publication.category == row.category)
                             .order_by(Publication.published_at.desc(), Publication.id.desc()).limit(6)).all()
    return {"items": [public_summary(*peer) for peer in peers], "rule": "同类别最新作品"}


@router.post("/publications/{publication_id}/remix", status_code=201)
def remix(publication_id: str, payload: RemixInput, user: User = Depends(current_user),
          database: Session = Depends(get_db)):
    owner_lock(database, user)
    previous = database.scalar(select(Project).where(Project.owner_id == user.id, Project.request_id == payload.requestId)
                               .with_for_update())
    if previous:
        provenance = database.scalar(select(ProjectRemix).where(ProjectRemix.project_id == previous.id).with_for_update())
        if provenance is None or provenance.publication_id != publication_id:
            raise HTTPException(409, "该请求编号已用于其他项目")
        return project_info(previous)
    row = find_publication(database, publication_id, lock=True)
    if not row.allow_remix:
        raise HTTPException(403, "作者未开放复制编辑")
    nickname = database.scalar(select(User.nickname).where(User.id == row.author_id))
    project = Project(id=str(uuid.uuid4()), owner_id=user.id, request_id=payload.requestId, name=row.title, revision=1)
    database.add(project)
    database.flush()
    counts = {}
    for code in row.pattern["cells"]:
        if code is not None:
            counts[code] = counts.get(code, 0) + 1
    original = database.get(ProjectVersion, row.project_version_id)
    palette_provenance = {}
    if original:
        saved = original.data.get("pattern", {})
        palette_id = saved.get("paletteId", "")
        if palette_id.startswith("db:") and len(matched_colors(database, saved)) == len(row.pattern["palette"]):
            version, brand = get_version(database, palette_id[3:])
            palette_provenance = {
                "paletteId": palette_id,
                "paletteName": f"{brand.brand} / {brand.series} · {version.label}",
                "paletteInfo": {
                    "brand": brand.brand, "series": f"{brand.series} {float(brand.size_mm)}mm",
                    "version": version.label, "source": version.source, "license": version.license_status,
                    "note": "授权二创 · 数据库色卡",
                },
            }
    data = {"schemaVersion": 2, "pattern": {**row.pattern, **palette_provenance}, "step": 3}
    database.add(ProjectVersion(id=str(uuid.uuid4()), project_id=project.id, revision=1, data=data, counts=counts,
                                bead_count=row.bead_count, color_count=row.color_count))
    database.add(ProjectRemix(project_id=project.id, publication_id=row.id, title=row.title, author=nickname))
    database.commit()
    return project_info(project)


@router.get("/projects/{project_id}/provenance")
def project_provenance(project_id: str, user: User = Depends(current_user), database: Session = Depends(get_db)):
    project = find_project(database, user, project_id)
    origin = database.get(ProjectRemix, project.id)
    if origin is None:
        return {"origin": None}
    return {"origin": {"publicationId": origin.publication_id, "title": origin.title, "author": origin.author,
                       "copiedAt": stamp(origin.created_at)}}
