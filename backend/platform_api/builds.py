"""User-owned progress on fixed grid revisions."""
import uuid
from collections import Counter
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from sqlalchemy import CheckConstraint, ForeignKey, Index, String, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .auth import User, current_user, utc_now
from .db import Base, get_db
from .projects import ProjectVersion, find_project, stamp

router = APIRouter(prefix="/builds", tags=["制作进度"])


class Build(Base):
    __tablename__ = "builds"
    __table_args__ = (
        Index("ix_build_user_updated", "user_id", "updated_at", "id"),
        UniqueConstraint("user_id", "request_id", name="uq_build_request"),
        CheckConstraint("completed_beads BETWEEN 0 AND bead_count", name="ck_build_progress"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    project_version_id: Mapped[str] = mapped_column(ForeignKey("project_versions.id"))
    name: Mapped[str] = mapped_column(String(80))
    request_id: Mapped[str | None] = mapped_column(String(80, collation="utf8mb4_bin"))
    block_size: Mapped[int]
    revision: Mapped[int] = mapped_column(default=1)
    bead_count: Mapped[int]
    completed_beads: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(default=utc_now)


class BuildBlock(Base):
    __tablename__ = "build_blocks"

    build_id: Mapped[str] = mapped_column(ForeignKey("builds.id", ondelete="CASCADE"), primary_key=True)
    x: Mapped[int] = mapped_column(primary_key=True)
    y: Mapped[int] = mapped_column(primary_key=True)
    beads: Mapped[int]
    completed: Mapped[bool] = mapped_column(default=False)


class BuildInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    projectId: str = Field(min_length=36, max_length=36)
    versionId: str = Field(min_length=36, max_length=36)
    blockSize: Literal[16, 29, 32] = 16
    requestId: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,80}$")


class BlockInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: StrictInt = Field(ge=0, le=127)
    y: StrictInt = Field(ge=0, le=127)
    completed: bool = Field(strict=True)
    expectedRevision: StrictInt = Field(ge=1)


def find_build(database, user, build_id, *, lock=False):
    statement = select(Build).where(Build.id == build_id, Build.user_id == user.id)
    if lock:
        statement = statement.with_for_update()
    build = database.scalar(statement)
    if build is None:
        raise HTTPException(404, "未找到制作记录")
    return build


def build_summary(build, version):
    return {"id": build.id, "projectId": version.project_id, "versionId": version.id,
            "name": build.name, "blockSize": build.block_size, "revision": build.revision,
            "beadCount": build.bead_count, "completedBeads": build.completed_beads,
            "status": "done" if build.completed_beads == build.bead_count else "in_progress",
            "updatedAt": stamp(build.updated_at)}


def build_detail(database, build, version):
    blocks = database.scalars(select(BuildBlock).where(BuildBlock.build_id == build.id)
                             .order_by(BuildBlock.y, BuildBlock.x)).all()
    return {**build_summary(build, version), "pattern": version.data["pattern"],
            "blocks": [{"x": block.x, "y": block.y, "beads": block.beads,
                        "completed": block.completed} for block in blocks]}


@router.post("", status_code=201)
def create_build(payload: BuildInput, user: User = Depends(current_user), database: Session = Depends(get_db)):
    project = find_project(database, user, payload.projectId)
    version = database.scalar(select(ProjectVersion).where(ProjectVersion.id == payload.versionId,
                                                           ProjectVersion.project_id == project.id))
    if version is None:
        raise HTTPException(404, "未找到图纸版本")
    pattern = version.data.get("pattern")
    if pattern is None or version.bead_count == 0:
        raise HTTPException(422, "请选择有拼豆格子的图纸版本")
    if payload.requestId:
        database.execute(select(User.id).where(User.id == user.id).with_for_update()).scalar_one()
        existing = database.scalar(select(Build).where(Build.user_id == user.id, Build.request_id == payload.requestId)
                                   .with_for_update())
        if existing:
            if existing.project_version_id != version.id or existing.block_size != payload.blockSize:
                raise HTTPException(409, "该请求编号已用于其他制作记录")
            return build_detail(database, existing, version)
    size, width = payload.blockSize, pattern["width"]
    blocks = Counter((index % width // size, index // width // size)
                     for index, code in enumerate(pattern["cells"]) if code is not None)
    build = Build(id=str(uuid.uuid4()), user_id=user.id, project_version_id=version.id, name=project.name,
                  request_id=payload.requestId, block_size=size, bead_count=version.bead_count)
    database.add(build)
    database.flush()
    database.add_all(BuildBlock(build_id=build.id, x=x, y=y, beads=beads) for (x, y), beads in blocks.items())
    database.commit()
    return build_detail(database, build, version)


@router.get("")
def list_builds(page: int = Query(1, ge=1, le=5000), user: User = Depends(current_user),
                database: Session = Depends(get_db)):
    rows = database.execute(select(Build, ProjectVersion).join(ProjectVersion)
                            .where(Build.user_id == user.id).order_by(Build.updated_at.desc(), Build.id.desc())
                            .offset((page - 1) * 30).limit(31)).all()
    return {"items": [build_summary(build, version) for build, version in rows[:30]], "hasMore": len(rows) > 30}


@router.get("/{build_id}")
def get_build(build_id: str, user: User = Depends(current_user), database: Session = Depends(get_db)):
    build = find_build(database, user, build_id)
    return build_detail(database, build, database.get(ProjectVersion, build.project_version_id))


@router.patch("/{build_id}/blocks")
def change_block(build_id: str, payload: BlockInput, user: User = Depends(current_user),
                 database: Session = Depends(get_db)):
    build = find_build(database, user, build_id, lock=True)
    if build.revision != payload.expectedRevision:
        raise HTTPException(409, "制作进度已更新，请刷新后继续")
    block = database.scalar(select(BuildBlock).where(BuildBlock.build_id == build.id,
                                                     BuildBlock.x == payload.x, BuildBlock.y == payload.y).with_for_update())
    if block is None:
        raise HTTPException(404, "该板块没有拼豆")
    if block.completed != payload.completed:
        block.completed = payload.completed
        build.completed_beads += block.beads if payload.completed else -block.beads
        build.revision += 1
        build.updated_at = utc_now()
    database.commit()
    return build_detail(database, build, database.get(ProjectVersion, build.project_version_id))
