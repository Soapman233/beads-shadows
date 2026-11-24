"""Project membership and ordered, version-pinned grid collaboration."""
import asyncio
import os
import uuid
from collections import Counter
from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from sqlalchemy import JSON, ForeignKey, Index, String, UniqueConstraint, or_, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .auth import (COOKIE, TOKEN, LoginSession, User, current_user, normalized_username, rate_limit,
                   token_digest, utc_now)
from .db import enabled, get_db, session_factory, Base
from .notifications import create_notice
from .project_data import CreateProject, UpdateProject
from .projects import Project, ProjectVersion, create_project, prepare_version, project_info, stamp

router = APIRouter(prefix="/collab", tags=["协作"])
presence: dict[str, dict[str, dict]] = {}
STRUCTURE_LEASE_SECONDS = 75


class Member(Base):
    __tablename__ = "project_members"

    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    role: Mapped[str] = mapped_column(String(12))
    created_at: Mapped[datetime] = mapped_column(default=utc_now)


class Invitation(Base):
    __tablename__ = "project_invitations"
    __table_args__ = (UniqueConstraint("project_id", "user_id", name="uq_project_invite"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    role: Mapped[str] = mapped_column(String(12))
    expires_at: Mapped[datetime]
    accepted_at: Mapped[datetime | None]
    revoked_at: Mapped[datetime | None]


class Room(Base):
    __tablename__ = "project_rooms"
    __table_args__ = (UniqueConstraint("project_id", "active_slot", name="uq_project_active_room"),
                      Index("ix_project_room_archived", "project_id", "active_slot", "created_at", "id"))

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    base_version_id: Mapped[str] = mapped_column(ForeignKey("project_versions.id"))
    base_revision: Mapped[int]
    active_slot: Mapped[int | None] = mapped_column(default=1)
    status: Mapped[str] = mapped_column(String(12), default="open")
    sequence: Mapped[int] = mapped_column(default=0)
    pattern: Mapped[dict] = mapped_column(JSON)
    latest: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=utc_now)


class Operation(Base):
    __tablename__ = "room_operations"
    __table_args__ = (UniqueConstraint("room_id", "sequence", name="uq_room_operation_sequence"),
                      UniqueConstraint("room_id", "actor_id", "request_id", name="uq_room_operation_request"),
                      Index("ix_room_actor_sequence", "room_id", "actor_id", "sequence"))

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    room_id: Mapped[str] = mapped_column(ForeignKey("project_rooms.id"))
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    request_id: Mapped[str] = mapped_column(String(80, collation="utf8mb4_bin"))
    sequence: Mapped[int]
    changes: Mapped[list] = mapped_column(JSON)
    undo_of: Mapped[str | None] = mapped_column(ForeignKey("room_operations.id"))
    created_at: Mapped[datetime] = mapped_column(default=utc_now)


class StructureLease(Base):
    __tablename__ = "room_structure_leases"
    __table_args__ = (
        UniqueConstraint("room_id", "session_digest", "request_id", name="uq_room_structure_request"),
        Index("ix_room_structure_active", "room_id", "ended_at", "expires_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    room_id: Mapped[str] = mapped_column(ForeignKey("project_rooms.id"))
    session_digest: Mapped[str] = mapped_column(String(64, collation="utf8mb4_bin"))
    request_id: Mapped[str] = mapped_column(String(80, collation="utf8mb4_bin"))
    base_revision: Mapped[int]
    sequence: Mapped[int]
    expires_at: Mapped[datetime]
    ended_at: Mapped[datetime | None]
    receipt: Mapped[dict | None] = mapped_column(JSON)


class CollabInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InviteInput(CollabInput):
    username: str = Field(min_length=3, max_length=64)
    role: Literal["viewer", "editor"]


class OperationRequest(CollabInput):
    requestId: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")


class CellChange(CollabInput):
    index: StrictInt = Field(ge=0, le=8191)
    code: str | None = Field(max_length=40)


class EditRequest(OperationRequest):
    changes: list[CellChange] = Field(min_length=1, max_length=256)


class UndoRequest(OperationRequest):
    operationId: str = Field(min_length=36, max_length=36)


class CommitRequest(CollabInput):
    expectedSequence: StrictInt = Field(ge=0)


class StructureLeaseRequest(OperationRequest):
    expectedRevision: StrictInt = Field(ge=1)
    expectedSequence: StrictInt = Field(ge=0)


class StructureCommitRequest(UpdateProject):
    leaseId: str = Field(min_length=36, max_length=36)
    expectedSequence: StrictInt = Field(ge=0)


class CopyRequest(CollabInput):
    requestId: str = Field(pattern=r"^[A-Za-z0-9_-]{1,42}$")


def active_project(database, project_id, lock=False):
    statement = select(Project).where(Project.id == project_id, Project.deleted_at.is_(None))
    if lock:
        # Account closure and creation both acquire the user lock first.
        owner_id = database.scalar(select(Project.owner_id).where(Project.id == project_id))
        owner_status = database.scalar(select(User.status).where(User.id == owner_id).with_for_update(read=True))
        if owner_status != "active":
            raise HTTPException(404, "未找到协作项目")
        statement = statement.with_for_update().execution_options(populate_existing=True)
    else:
        statement = statement.join(User, User.id == Project.owner_id).where(User.status == "active")
    project = database.scalar(statement)
    if not project:
        raise HTTPException(404, "未找到协作项目")
    return project


def owned_collab_project(database, project_id, user):
    project = active_project(database, project_id, lock=True)
    if project.owner_id != user.id:
        raise HTTPException(404, "未找到协作项目")
    return project


def project_access(database, project_id, user_id, lock=False):
    project = active_project(database, project_id, lock=lock)
    if project.owner_id == user_id:
        return project, "owner"
    membership = select(Member.role).where(Member.project_id == project.id, Member.user_id == user_id)
    role = database.scalar(membership.with_for_update() if lock else membership)
    if role is None:
        raise HTTPException(404, "未找到协作项目")
    return project, role


def member_data(peer, role):
    return {"id": peer.id, "username": peer.username, "nickname": peer.nickname, "role": role}


def active_room(database, project_id, lock=False):
    statement = select(Room).where(Room.project_id == project_id, Room.active_slot == 1)
    return database.scalar(statement.with_for_update() if lock else statement)


def room_access(database, room_id, user_id, lock=False):
    project_id = database.scalar(select(Room.project_id).where(Room.id == room_id))
    if not project_id:
        raise HTTPException(404, "未找到协作房间")
    project, role = project_access(database, project_id, user_id, lock=lock)
    statement = select(Room).where(Room.id == room_id)
    room = database.scalar(statement.with_for_update() if lock else statement)
    if not room:
        raise HTTPException(404, "未找到协作房间")
    return room, project, role


def active_structure_lease(database, room_id, lock=False):
    statement = select(StructureLease).where(
        StructureLease.room_id == room_id, StructureLease.ended_at.is_(None),
        StructureLease.expires_at > utc_now(),
    )
    return database.scalar(statement.with_for_update() if lock else statement)


def ensure_no_structure_lease(database, room):
    if active_structure_lease(database, room.id, lock=True):
        raise HTTPException(409, "正在更新图纸结构，请等待提交或租约到期")


def undoable_operation(database, room, user_id):
    recent = database.scalars(select(Operation).where(Operation.room_id == room.id, Operation.actor_id == user_id,
                              Operation.undo_of.is_(None)).order_by(Operation.sequence.desc()).limit(20))
    for row in recent:
        if all(room.latest.get(str(change["index"])) == row.sequence for change in row.changes):
            return row.id
    return None


def room_data(database, room, project, role, user_id):
    status = "conflict" if room.status == "open" and room.base_revision != project.revision else room.status
    lease = active_structure_lease(database, room.id) if status == "open" else None
    last = undoable_operation(database, room, user_id) if not lease and status == "open" and role in ("owner", "editor") else None
    return {"id": room.id, "projectId": project.id, "name": project.name, "role": role,
            "status": status, "sequence": room.sequence, "baseRevision": room.base_revision,
            "pattern": room.pattern, "lastEditableOperationId": last,
            "structureLockedUntil": stamp(lease.expires_at) if lease else None}


@router.get("/projects")
def shared_projects(page: int = Query(1, ge=1, le=5000), user: User = Depends(current_user),
                    database: Session = Depends(get_db)):
    rows = database.execute(select(Project, Member.role).join(User, User.id == Project.owner_id)
                            .outerjoin(Member, (Member.project_id == Project.id) & (Member.user_id == user.id))
                            .where(Project.deleted_at.is_(None), User.status == "active",
                            or_(Project.owner_id == user.id, Member.user_id == user.id))
                            .order_by(Project.updated_at.desc(), Project.id.desc()).offset((page - 1) * 30).limit(31)).all()
    return {"items": [{"id": project.id, "name": project.name,
                       "role": "owner" if project.owner_id == user.id else role}
                      for project, role in rows[:30]], "hasMore": len(rows) > 30}


@router.get("/projects/{project_id}")
def project_members(project_id: str, user: User = Depends(current_user), database: Session = Depends(get_db)):
    project, role = project_access(database, project_id, user.id)
    room = active_room(database, project.id)
    archived_room_id = database.scalar(select(Room.id).where(Room.project_id == project.id, Room.active_slot.is_(None))
                                       .order_by(Room.created_at.desc(), Room.id.desc()).limit(1))
    people = database.execute(select(User, Member.role).join(Member, User.id == Member.user_id)
                              .where(Member.project_id == project.id).order_by(User.nickname, User.id)).all()
    owner = database.get(User, project.owner_id)
    return {"id": project.id, "name": project.name, "role": role, "roomId": room.id if room else None,
            "archivedRoomId": archived_room_id,
            "members": [member_data(owner, "owner"), *[member_data(*peer) for peer in people]]}


@router.post("/projects/{project_id}/invite", status_code=201)
def invite(project_id: str, body: InviteInput, request: Request, user: User = Depends(current_user),
           database: Session = Depends(get_db)):
    rate_limit(request, f"room-invite:{user.id}", 20)
    project = owned_collab_project(database, project_id, user)
    peer = database.scalar(select(User).where(User.username == normalized_username(body.username), User.status == "active"))
    if peer is None or peer.id == user.id:
        raise HTTPException(404, "未找到可邀请的账号")
    if database.get(Member, (project.id, peer.id), with_for_update=True):
        raise HTTPException(409, "该用户已加入协作")
    previous = database.scalar(select(Invitation).where(Invitation.project_id == project.id,
                              Invitation.user_id == peer.id).with_for_update())
    if previous and previous.accepted_at is None and previous.revoked_at is None and previous.expires_at > utc_now() and previous.role == body.role:
        return {"id": previous.id, "role": previous.role, "expiresAt": stamp(previous.expires_at)}
    target = previous or Invitation(id=str(uuid.uuid4()), project_id=project.id, user_id=peer.id)
    target.role = body.role
    target.expires_at = utc_now() + timedelta(days=3)
    target.accepted_at = target.revoked_at = None
    database.add(target)
    create_notice(database, peer.id, "collaboration", target.id, "收到图纸协作邀请")
    database.commit()
    return {"id": target.id, "role": target.role, "expiresAt": stamp(target.expires_at)}


@router.get("/invitations")
def invitations(user: User = Depends(current_user), database: Session = Depends(get_db)):
    rows = database.execute(select(Invitation, Project.name).join(Project).join(User, User.id == Project.owner_id)
                            .where(Invitation.user_id == user.id, Project.deleted_at.is_(None), User.status == "active",
                                   Invitation.revoked_at.is_(None), Invitation.accepted_at.is_(None),
                                   Invitation.expires_at > utc_now()).order_by(Invitation.expires_at, Invitation.id)
                            .limit(100)).all()
    return {"items": [{"id": row.id, "projectId": row.project_id, "name": name,
                       "role": row.role, "expiresAt": stamp(row.expires_at)} for row, name in rows]}


@router.post("/invitations/{invite_id}/accept")
def accept(invite_id: str, user: User = Depends(current_user), database: Session = Depends(get_db)):
    project_id = database.scalar(select(Invitation.project_id).where(Invitation.id == invite_id, Invitation.user_id == user.id))
    if not project_id:
        raise HTTPException(404, "协作邀请不可用")
    project = active_project(database, project_id, lock=True)
    row = database.scalar(select(Invitation).where(Invitation.id == invite_id, Invitation.user_id == user.id).with_for_update())
    if not row or row.revoked_at is not None or (row.accepted_at is None and row.expires_at <= utc_now()):
        raise HTTPException(404, "协作邀请不可用")
    if row.accepted_at is None:
        count = database.scalars(select(Member.user_id).where(Member.project_id == project.id).with_for_update()).all()
        if len(count) >= 16:
            raise HTTPException(409, "该项目协作成员已达上限")
        database.add(Member(project_id=project.id, user_id=user.id, role=row.role))
        row.accepted_at = utc_now()
        database.commit()
    return {"projectId": project.id, "role": row.role}


@router.delete("/projects/{project_id}/members/{peer_id}", status_code=204)
def revoke_member(project_id: str, peer_id: str, user: User = Depends(current_user), database: Session = Depends(get_db)):
    project = owned_collab_project(database, project_id, user)
    member = database.get(Member, (project.id, peer_id), with_for_update=True)
    if member:
        database.delete(member)
    row = database.scalar(select(Invitation).where(Invitation.project_id == project.id,
                          Invitation.user_id == peer_id).with_for_update())
    if row and row.revoked_at is None:
        row.revoked_at = utc_now()
    database.commit()


def shareable_pattern(pattern):
    return {key: pattern[key] for key in ("width", "height", "palette", "cells", "colorLimit")}


@router.post("/projects/{project_id}/room", status_code=201)
def open_room(project_id: str, user: User = Depends(current_user), database: Session = Depends(get_db)):
    project = owned_collab_project(database, project_id, user)
    room = active_room(database, project.id, lock=True)
    if room:
        return room_data(database, room, project, "owner", user.id)
    version = database.scalar(select(ProjectVersion).where(ProjectVersion.project_id == project.id)
                              .order_by(ProjectVersion.revision.desc()).limit(1).with_for_update())
    pattern = version.data.get("pattern") if version else None
    if not pattern:
        raise HTTPException(422, "请先保存一份含图纸的项目版本")
    room = Room(id=str(uuid.uuid4()), project_id=project.id, base_version_id=version.id,
                base_revision=project.revision, pattern=shareable_pattern(pattern), latest={})
    database.add(room)
    database.commit()
    return room_data(database, room, project, "owner", user.id)


@router.get("/rooms/{room_id}")
def get_room(room_id: str, user: User = Depends(current_user), database: Session = Depends(get_db)):
    return room_data(database, *room_access(database, room_id, user.id), user.id)


def assert_editable(room, project, role):
    if role not in ("owner", "editor"):
        raise HTTPException(403, "此项目只允许查看")
    if room.status != "open" or project.revision != room.base_revision:
        raise HTTPException(409, "项目版本或协作状态已改变，请查看或另存协作图纸")
    if room.sequence >= 100_000:
        raise HTTPException(409, "此房间操作已达上限，请保存版本后开启新房间")


def operation_data(row):
    return {"id": row.id, "sequence": row.sequence, "actorId": row.actor_id,
            "changes": [{"index": change["index"], "code": change["code"]} for change in row.changes],
            "undoOf": row.undo_of}


def prior_operation(database, room, user_id, request_id):
    return database.scalar(select(Operation).where(Operation.room_id == room.id, Operation.actor_id == user_id,
                           Operation.request_id == request_id).with_for_update())


def write_operation(database, room, actor_id, request_id, changes, undo_of=None):
    cells = list(room.pattern["cells"])
    valid = {color["code"] for color in room.pattern["palette"]}
    indexes = set()
    stored = []
    room.sequence += 1
    latest = dict(room.latest)
    for change in changes:
        index, code = change["index"], change["code"]
        if index >= len(cells) or index in indexes or (code is not None and code not in valid):
            raise HTTPException(422, "编辑包含无效、重复的格子或色号")
        indexes.add(index)
        stored.append({"index": index, "code": code, "before": cells[index]})
        cells[index] = code
        latest[str(index)] = room.sequence
    room.pattern = {**room.pattern, "cells": cells}
    room.latest = latest
    row = Operation(id=str(uuid.uuid4()), room_id=room.id, actor_id=actor_id, request_id=request_id,
                    sequence=room.sequence, changes=stored, undo_of=undo_of)
    database.add(row)
    database.commit()
    return operation_data(row)


@router.post("/rooms/{room_id}/operations", status_code=201)
def edit_room(room_id: str, body: EditRequest, request: Request, user: User = Depends(current_user),
              database: Session = Depends(get_db)):
    rate_limit(request, f"room-edit:{user.id}", 300)
    room, project, role = room_access(database, room_id, user.id, lock=True)
    assert_editable(room, project, role)
    ensure_no_structure_lease(database, room)
    changes = [change.model_dump() for change in body.changes]
    previous = prior_operation(database, room, user.id, body.requestId)
    if previous:
        result = operation_data(previous)
        if result["changes"] != changes or previous.undo_of:
            raise HTTPException(409, "请求编号已用于其他编辑")
        return result
    return write_operation(database, room, user.id, body.requestId, changes)


@router.post("/rooms/{room_id}/undo", status_code=201)
def undo_room(room_id: str, body: UndoRequest, request: Request, user: User = Depends(current_user),
              database: Session = Depends(get_db)):
    rate_limit(request, f"room-edit:{user.id}", 300)
    room, project, role = room_access(database, room_id, user.id, lock=True)
    assert_editable(room, project, role)
    ensure_no_structure_lease(database, room)
    previous = prior_operation(database, room, user.id, body.requestId)
    if previous:
        if previous.undo_of != body.operationId:
            raise HTTPException(409, "请求编号已用于其他编辑")
        return operation_data(previous)
    row = database.scalar(select(Operation).where(Operation.id == body.operationId, Operation.room_id == room.id,
                           Operation.actor_id == user.id, Operation.undo_of.is_(None)).with_for_update())
    if not row:
        raise HTTPException(404, "找不到可撤销的本人操作")
    if any(room.latest.get(str(change["index"])) != row.sequence for change in row.changes):
        raise HTTPException(409, "选中的格子此后已有改动")
    changes = [{"index": change["index"], "code": change["before"]} for change in row.changes]
    return write_operation(database, room, user.id, body.requestId, changes, undo_of=row.id)


@router.post("/rooms/{room_id}/commit")
def commit_room(room_id: str, body: CommitRequest, user: User = Depends(current_user),
                database: Session = Depends(get_db)):
    room, project, role = room_access(database, room_id, user.id, lock=True)
    if role != "owner":
        raise HTTPException(403, "只有项目所有者可提交协作版本")
    if room.status != "open" or project.revision != room.base_revision or room.sequence != body.expectedSequence:
        raise HTTPException(409, "协作状态已变更，请查阅当前记录后重试")
    ensure_no_structure_lease(database, room)
    base = database.get(ProjectVersion, room.base_version_id)
    cells = room.pattern["cells"]
    counts = Counter(code for code in cells if code is not None)
    project.revision += 1
    project.updated_at = utc_now()
    data = {**base.data, "pattern": {**base.data["pattern"], "cells": cells}, "step": 3}
    database.add(ProjectVersion(id=str(uuid.uuid4()), project_id=project.id, revision=project.revision,
                                data=data, counts=dict(counts), bead_count=sum(counts.values()), color_count=len(counts),
                                source_id=base.source_id, mask_id=base.mask_id))
    room.status, room.active_slot = "committed", None
    database.commit()
    return project_info(project)


@router.post("/rooms/{room_id}/close")
def close_room(room_id: str, user: User = Depends(current_user), database: Session = Depends(get_db)):
    room, project, role = room_access(database, room_id, user.id, lock=True)
    if role != "owner":
        raise HTTPException(403, "只有项目所有者可关闭协作")
    if room.status == "open":
        ensure_no_structure_lease(database, room)
        room.status, room.active_slot = "closed", None
        database.commit()
    return room_data(database, room, project, role, user.id)


def owner_room(database, room_id, user):
    room, project, role = room_access(database, room_id, user.id, lock=True)
    if role != "owner":
        raise HTTPException(403, "只有项目所有者可更新图纸结构")
    return room, project


def lease_data(lease):
    return {"leaseId": lease.id, "expiresAt": stamp(lease.expires_at),
            "baseRevision": lease.base_revision, "sequence": lease.sequence}


@router.post("/rooms/{room_id}/structure/lease", status_code=201)
def acquire_structure_lease(room_id: str, body: StructureLeaseRequest, request: Request,
                            user: User = Depends(current_user), database: Session = Depends(get_db)):
    rate_limit(request, f"room-structure:{user.id}", 30)
    room, project = owner_room(database, room_id, user)
    session_digest = request.state.login_session.token_digest
    previous = database.scalar(select(StructureLease).where(
        StructureLease.room_id == room.id, StructureLease.session_digest == session_digest,
        StructureLease.request_id == body.requestId,
    ).with_for_update())
    if previous:
        if (previous.base_revision, previous.sequence) != (body.expectedRevision, body.expectedSequence):
            raise HTTPException(409, "请求编号已用于其他结构更新")
        if previous.receipt or (previous.ended_at is None and previous.expires_at > utc_now()):
            return lease_data(previous)
        raise HTTPException(409, "该租约已结束，请重新获取")
    if (room.status != "open" or room.base_revision != project.revision
            or project.revision != body.expectedRevision or room.sequence != body.expectedSequence):
        raise HTTPException(409, "项目版本或房间序号已变更，请先刷新")
    ensure_no_structure_lease(database, room)
    lease = StructureLease(id=str(uuid.uuid4()), room_id=room.id, session_digest=session_digest,
                           request_id=body.requestId, base_revision=project.revision, sequence=room.sequence,
                           expires_at=utc_now().replace(microsecond=0) + timedelta(seconds=STRUCTURE_LEASE_SECONDS))
    database.add(lease)
    database.commit()
    return lease_data(lease)


def owned_structure_lease(database, room_id, lease_id, request):
    lease = database.scalar(select(StructureLease).where(
        StructureLease.id == lease_id, StructureLease.room_id == room_id,
        StructureLease.session_digest == request.state.login_session.token_digest,
    ).with_for_update())
    if not lease:
        raise HTTPException(409, "结构租约无效，请从当前登录会话重新获取")
    return lease


@router.post("/rooms/{room_id}/structure/commit")
def commit_structure(room_id: str, body: StructureCommitRequest, request: Request,
                     user: User = Depends(current_user), database: Session = Depends(get_db)):
    room, project = owner_room(database, room_id, user)
    lease = owned_structure_lease(database, room.id, body.leaseId, request)
    if (lease.base_revision, lease.sequence) != (body.expected_revision, body.expectedSequence):
        raise HTTPException(409, "结构租约与项目版本或房间序号不匹配")
    name = body.name.strip() or "未命名"
    if lease.receipt:
        saved = database.scalar(select(ProjectVersion).where(
            ProjectVersion.project_id == project.id, ProjectVersion.revision == lease.receipt["revision"],
        ).with_for_update())
        data, _ = prepare_version(database, user, body)
        if (saved is None or saved.data != data or lease.receipt["name"] != name
                or saved.source_id != body.source_id or saved.mask_id != body.mask_id):
            raise HTTPException(409, "此租约已提交另一份图纸")
        return lease.receipt
    if (lease.ended_at is not None or lease.expires_at <= utc_now() or room.status != "open"
            or room.base_revision != project.revision or room.sequence != lease.sequence):
        raise HTTPException(409, "结构租约已失效或协作状态已变更")
    data, counts = prepare_version(database, user, body)
    if "pattern" not in data:
        raise HTTPException(422, "结构更新必须包含新的图纸")
    if lease.expires_at <= utc_now():
        raise HTTPException(409, "结构租约已到期，请重新获取")
    project.revision += 1
    project.name = name
    project.updated_at = utc_now()
    database.add(ProjectVersion(id=str(uuid.uuid4()), project_id=project.id, revision=project.revision,
                                data=data, counts=dict(counts), bead_count=sum(counts.values()), color_count=len(counts),
                                source_id=body.source_id, mask_id=body.mask_id))
    room.status, room.active_slot = "committed", None
    lease.ended_at, lease.receipt = utc_now(), project_info(project)
    database.commit()
    return lease.receipt


@router.delete("/rooms/{room_id}/structure/lease/{lease_id}", status_code=204)
def cancel_structure_lease(room_id: str, lease_id: str, request: Request,
                           user: User = Depends(current_user), database: Session = Depends(get_db)):
    room, _ = owner_room(database, room_id, user)
    lease = owned_structure_lease(database, room.id, lease_id, request)
    if lease.ended_at is None:
        lease.ended_at = utc_now()
        database.commit()


@router.post("/rooms/{room_id}/copy", status_code=201)
def copy_room(room_id: str, body: CopyRequest, user: User = Depends(current_user), database: Session = Depends(get_db)):
    room, project, role = room_access(database, room_id, user.id)
    if role == "viewer":
        raise HTTPException(403, "只读协作者不可复制到自己的项目")
    payload = CreateProject(name=(project.name + " 副本")[:80], request_id=f"{room.id}_{body.requestId}",
                            project={"schemaVersion": 2, "pattern": room.pattern, "step": 3})
    return create_project(payload, user, database)


def socket_state(room_id, token, after_sequence=None):
    if not enabled() or not TOKEN.fullmatch(token):
        raise HTTPException(401)
    with session_factory()() as database:
        user = database.scalar(select(User).join(LoginSession).where(
            LoginSession.token_digest == token_digest(token), LoginSession.expires_at > utc_now(),
            LoginSession.revoked_at.is_(None), User.status == "active"))
        if not user:
            raise HTTPException(401)
        room, project, role = room_access(database, room_id, user.id)
        state = room_data(database, room, project, role, user.id)
        if after_sequence is None or state["sequence"] - after_sequence > 256:
            event = {"type": "snapshot", "room": state}
        else:
            ops = database.scalars(select(Operation).where(Operation.room_id == room.id,
                                   Operation.sequence > after_sequence).order_by(Operation.sequence)).all()
            event = {"type": "operations", "operations": [operation_data(row) for row in ops],
                     "sequence": state["sequence"], "status": state["status"], "role": role,
                     "lastEditableOperationId": state["lastEditableOperationId"],
                     "structureLockedUntil": state["structureLockedUntil"]}
        return event, state, {"id": user.id, "nickname": user.nickname, "role": role, "index": None}


def socket_origin_allowed(socket):
    origin = socket.headers.get("origin")
    scheme = "https" if socket.url.scheme == "wss" else "http"
    configured = os.environ.get("BEAD_WEB_ORIGIN", "").rstrip("/")
    return bool(origin and origin in (f"{scheme}://{socket.url.netloc}", configured))


@router.websocket("/ws/{room_id}")
async def watch_room(room_id: str, socket: WebSocket):
    if not socket_origin_allowed(socket):
        await socket.close(code=4403)
        return
    token = socket.cookies.get(COOKIE, "")
    connection_id = str(uuid.uuid4())
    accepted = False
    try:
        event, state, person = await asyncio.to_thread(socket_state, room_id, token)
        await socket.accept()
        accepted = True
        peers = presence.setdefault(room_id, {})
        peers[connection_id] = person
        await socket.send_json({**event, "presence": list(peers.values())})
        while state["status"] == "open":
            # A fixed tick prevents a noisy client from driving the database polling rate.
            await asyncio.sleep(0.65)
            try:
                message = await asyncio.wait_for(socket.receive_json(), timeout=0.05)
            except (TimeoutError, ValueError, KeyError):
                message = None
            event, state, person = await asyncio.to_thread(socket_state, room_id, token, state["sequence"])
            if isinstance(message, dict) and message.get("type") == "presence":
                index = message.get("index")
                if type(index) is int and 0 <= index < len(state["pattern"]["cells"]):
                    person["index"] = index
            else:
                person["index"] = peers[connection_id]["index"]
            peers[connection_id] = person
            await socket.send_json({**event, "presence": list(peers.values())})
        await socket.close(code=1000)
    except HTTPException as error:
        await socket.close(code=4401 if error.status_code == 401 else 4404)
    except WebSocketDisconnect:
        pass
    finally:
        if accepted:
            peers = presence.get(room_id, {})
            peers.pop(connection_id, None)
            if not peers:
                presence.pop(room_id, None)
