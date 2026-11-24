"""Permission-scoped comments, direct messages and reporting."""
import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import ForeignKey, Index, String, UniqueConstraint, or_, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .auth import User, current_user, normalized_username, rate_limit, require_admin, utc_now
from .catalog import write_audit
from .db import Base, get_db
from .notifications import create_notice
from .projects import stamp
from .publications import ReasonInput, checked_text, find_publication

router = APIRouter(tags=["互动"])
PAGE_SIZE = 30


class Comment(Base):
    __tablename__ = "publication_comments"
    __table_args__ = (Index("ix_comment_publication_time", "publication_id", "created_at", "id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    publication_id: Mapped[str] = mapped_column(ForeignKey("publications.id"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    reply_to: Mapped[str | None] = mapped_column(ForeignKey("publication_comments.id"))
    text: Mapped[str] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(default=utc_now)
    deleted_at: Mapped[datetime | None]


class Conversation(Base):
    __tablename__ = "direct_conversations"
    __table_args__ = (UniqueConstraint("first_user", "second_user", name="uq_conversation_users"),
                      Index("ix_conversation_second", "second_user", "updated_at"))

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    first_user: Mapped[str] = mapped_column(ForeignKey("users.id"))
    second_user: Mapped[str] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(default=utc_now)


class DirectMessage(Base):
    __tablename__ = "direct_messages"
    __table_args__ = (UniqueConstraint("sender_id", "request_id", name="uq_direct_message_request"),
                      Index("ix_direct_conversation_time", "conversation_id", "created_at", "id"))

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("direct_conversations.id"))
    sender_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    request_id: Mapped[str] = mapped_column(String(80, collation="utf8mb4_bin"))
    text: Mapped[str] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(default=utc_now)


class UserBlock(Base):
    __tablename__ = "user_blocks"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    blocked_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(default=utc_now)


class SocialReport(Base):
    __tablename__ = "social_reports"
    __table_args__ = (UniqueConstraint("reporter_id", "kind", "content_id", name="uq_social_report"),
                      Index("ix_social_report_state", "status", "created_at"))

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    reporter_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(12))
    content_id: Mapped[str] = mapped_column(String(36))
    reason: Mapped[str] = mapped_column(String(240))
    status: Mapped[str] = mapped_column(String(12), default="pending")
    resolution: Mapped[str | None] = mapped_column(String(240))
    created_at: Mapped[datetime] = mapped_column(default=utc_now)


class CommentInput(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    replyTo: str | None = Field(default=None, min_length=36, max_length=36)


class MessageInput(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    requestId: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")


def comment_data(row, nickname):
    return {"id": row.id, "author": nickname, "authorId": row.user_id, "text": row.text,
            "replyTo": row.reply_to, "createdAt": stamp(row.created_at)}


@router.get("/publications/{id}/comments")
def comments(id: str, page: int = Query(1, ge=1, le=2000), database: Session = Depends(get_db)):
    find_publication(database, id)
    rows = database.execute(select(Comment, User.nickname).join(User).where(Comment.publication_id == id,
                            Comment.deleted_at.is_(None)).order_by(Comment.created_at.desc(), Comment.id.desc())
                            .offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE + 1)).all()
    return {"items": [comment_data(*row) for row in rows[:PAGE_SIZE]], "hasMore": len(rows) > PAGE_SIZE}


@router.post("/publications/{id}/comments", status_code=201)
def add_comment(id: str, payload: CommentInput, request: Request, user: User = Depends(current_user),
                database: Session = Depends(get_db)):
    rate_limit(request, f"comment:{user.id}", 12)
    publication = find_publication(database, id, lock=True)
    recipient = publication.author_id
    if payload.replyTo:
        parent = database.scalar(select(Comment).where(Comment.id == payload.replyTo, Comment.publication_id == id,
                                                       Comment.deleted_at.is_(None)).with_for_update())
        if parent is None:
            raise HTTPException(404, "回复的评论不可见")
        recipient = parent.user_id
    row = Comment(id=str(uuid.uuid4()), publication_id=id, user_id=user.id, reply_to=payload.replyTo,
                  text=checked_text(payload.text, "请填写评论"))
    database.add(row)
    if recipient != user.id:
        create_notice(database, recipient, "comment", publication.id, "你的作品或评论有新回复")
    database.commit()
    return comment_data(row, user.nickname)


@router.delete("/comments/{id}", status_code=204)
def delete_comment(id: str, user: User = Depends(current_user), database: Session = Depends(get_db)):
    row = database.scalar(select(Comment).where(Comment.id == id, Comment.user_id == user.id).with_for_update())
    if row is None:
        raise HTTPException(404, "未找到评论")
    if row.deleted_at is None:
        row.deleted_at = utc_now()
        database.commit()
    return Response(status_code=204)


def person_data(user):
    return {"id": user.id, "username": user.username, "nickname": user.nickname}


@router.get("/people/{username}")
def find_person(username: str, request: Request, user: User = Depends(current_user), database: Session = Depends(get_db)):
    rate_limit(request, f"search-person:{user.id}", 20)
    peer = database.scalar(select(User).where(User.username == normalized_username(username), User.status == "active"))
    if peer is None:
        raise HTTPException(404, "未找到账号")
    return person_data(peer)


def lock_people(database, user_id, peer_id):
    if user_id == peer_id:
        raise HTTPException(422, "请选择其他账号")
    first, second = sorted((user_id, peer_id))
    people = database.execute(select(User.id, User.status).where(User.id.in_((first, second)))
                              .order_by(User.id).with_for_update()).all()
    states = dict(people)
    if states.get(user_id) != "active":
        raise HTTPException(401, "账号当前不可用")
    if peer_id not in states:
        raise HTTPException(404, "未找到对方账号")
    return first, second, states[peer_id]


def find_conversation(database, user_id, peer_id, *, lock=False):
    first, second = sorted((user_id, peer_id))
    statement = select(Conversation).where(Conversation.first_user == first, Conversation.second_user == second)
    return database.scalar(statement.with_for_update() if lock else statement)


def message_data(row):
    return {"id": row.id, "senderId": row.sender_id, "text": row.text, "createdAt": stamp(row.created_at)}


@router.get("/conversations")
def conversations(page: int = Query(1, ge=1, le=2000), user: User = Depends(current_user),
                  database: Session = Depends(get_db)):
    rows = database.scalars(select(Conversation).where(or_(Conversation.first_user == user.id,
                            Conversation.second_user == user.id)).order_by(Conversation.updated_at.desc(), Conversation.id.desc())
                            .offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE + 1)).all()
    peer_ids = {row.second_user if row.first_user == user.id else row.first_user for row in rows}
    peers = {peer.id: peer for peer in database.scalars(select(User).where(User.id.in_(peer_ids)))}
    return {"items": [{"id": row.id, "peer": person_data(peers[row.second_user if row.first_user == user.id else row.first_user]),
                       "updatedAt": stamp(row.updated_at)} for row in rows[:PAGE_SIZE]], "hasMore": len(rows) > PAGE_SIZE}


@router.get("/messages/{peer_id}")
def messages(peer_id: str, page: int = Query(1, ge=1, le=2000), user: User = Depends(current_user),
             database: Session = Depends(get_db)):
    peer = database.get(User, peer_id)
    if peer is None or user.id == peer.id:
        raise HTTPException(404, "未找到对方账号")
    row = find_conversation(database, user.id, peer_id)
    result = {"peer": person_data(peer), "items": [], "hasMore": False,
              "blocked": database.get(UserBlock, (user.id, peer_id)) is not None}
    if row:
        items = database.scalars(select(DirectMessage).where(DirectMessage.conversation_id == row.id)
                                 .order_by(DirectMessage.created_at.desc(), DirectMessage.id.desc())
                                 .offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE + 1)).all()
        result.update(items=[message_data(item) for item in items[:PAGE_SIZE]], hasMore=len(items) > PAGE_SIZE)
    return result


@router.post("/messages/{peer_id}", status_code=201)
def send_message(peer_id: str, payload: MessageInput, request: Request, user: User = Depends(current_user),
                 database: Session = Depends(get_db)):
    rate_limit(request, f"direct:{user.id}", 20)
    text = checked_text(payload.text, "请填写消息")
    first, second, peer_state = lock_people(database, user.id, peer_id)
    row = find_conversation(database, user.id, peer_id, lock=True)
    previous = database.scalar(select(DirectMessage).where(DirectMessage.sender_id == user.id,
                               DirectMessage.request_id == payload.requestId).with_for_update())
    if previous:
        if row is None or previous.conversation_id != row.id or previous.text != text:
            raise HTTPException(409, "该编号已用于另一条消息")
        return message_data(previous)
    blocks = database.execute(select(UserBlock).where(or_(
        (UserBlock.user_id == user.id) & (UserBlock.blocked_id == peer_id),
        (UserBlock.user_id == peer_id) & (UserBlock.blocked_id == user.id),
    )).with_for_update()).first()
    if blocks or peer_state != "active":
        raise HTTPException(403, "当前无法向该账号发送消息")
    if row is None:
        row = Conversation(id=str(uuid.uuid4()), first_user=first, second_user=second)
        database.add(row)
        database.flush()
    item = DirectMessage(id=str(uuid.uuid4()), conversation_id=row.id, sender_id=user.id,
                         request_id=payload.requestId, text=text)
    row.updated_at = utc_now()
    database.add(item)
    create_notice(database, peer_id, "message", user.id, "收到一条新私信")
    database.commit()
    return message_data(item)


@router.get("/blocks")
def blocks(user: User = Depends(current_user), database: Session = Depends(get_db)):
    peers = database.scalars(select(User).join(UserBlock, User.id == UserBlock.blocked_id)
                             .where(UserBlock.user_id == user.id).order_by(UserBlock.created_at.desc()))
    return {"items": [person_data(peer) for peer in peers]}


@router.put("/blocks/{peer_id}", status_code=204)
def block_person(peer_id: str, user: User = Depends(current_user), database: Session = Depends(get_db)):
    lock_people(database, user.id, peer_id)
    if database.get(UserBlock, (user.id, peer_id), with_for_update=True) is None:
        database.add(UserBlock(user_id=user.id, blocked_id=peer_id))
        database.commit()
    return Response(status_code=204)


@router.delete("/blocks/{peer_id}", status_code=204)
def unblock_person(peer_id: str, user: User = Depends(current_user), database: Session = Depends(get_db)):
    lock_people(database, user.id, peer_id)
    block = database.get(UserBlock, (user.id, peer_id), with_for_update=True)
    if block:
        database.delete(block)
        database.commit()
    return Response(status_code=204)


def record_report(database, user, kind, content_id, reason):
    database.execute(select(User.id).where(User.id == user.id).with_for_update()).scalar_one()
    row = database.scalar(select(SocialReport).where(SocialReport.reporter_id == user.id, SocialReport.kind == kind,
                           SocialReport.content_id == content_id).with_for_update())
    if row is None:
        row = SocialReport(id=str(uuid.uuid4()), reporter_id=user.id, kind=kind, content_id=content_id,
                           reason=checked_text(reason, "请填写举报原因"))
        database.add(row)
        database.commit()
    return {"id": row.id, "status": row.status}


@router.post("/comments/{id}/report", status_code=201)
def report_comment(id: str, payload: ReasonInput, request: Request, user: User = Depends(current_user),
                   database: Session = Depends(get_db)):
    rate_limit(request, f"social-report:{user.id}", 12)
    row = database.get(Comment, id)
    if not row or row.deleted_at is not None:
        raise HTTPException(404, "评论不可见")
    find_publication(database, row.publication_id)
    if row.user_id == user.id:
        raise HTTPException(422, "请在评论中删除自己的内容")
    return record_report(database, user, "comment", id, payload.reason)


@router.post("/messages/report/{id}", status_code=201)
def report_message(id: str, payload: ReasonInput, request: Request, user: User = Depends(current_user),
                   database: Session = Depends(get_db)):
    rate_limit(request, f"social-report:{user.id}", 12)
    item = database.scalar(select(DirectMessage).join(Conversation).where(DirectMessage.id == id,
                            DirectMessage.sender_id != user.id,
                            or_(Conversation.first_user == user.id, Conversation.second_user == user.id)))
    if not item:
        raise HTTPException(404, "消息不可用")
    return record_report(database, user, "message", id, payload.reason)


@router.get("/admin/social-reports")
def social_reports(page: int = Query(1, ge=1, le=2000), admin: User = Depends(require_admin),
                   database: Session = Depends(get_db)):
    rows = database.scalars(select(SocialReport).where(SocialReport.status == "pending")
                            .order_by(SocialReport.created_at, SocialReport.id)
                            .offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE + 1)).all()
    result = []
    for row in rows[:PAGE_SIZE]:
        model = Comment if row.kind == "comment" else DirectMessage
        content = database.get(model, row.content_id)
        result.append({"id": row.id, "kind": row.kind, "text": content.text if content else None,
                       "reason": row.reason, "createdAt": stamp(row.created_at)})
    return {"items": result, "hasMore": len(rows) > PAGE_SIZE}


class Resolution(ReasonInput):
    action: Literal["resolve", "remove_comment"] = "resolve"


@router.post("/admin/social-reports/{id}/resolve")
def resolve_social_report(id: str, payload: Resolution, admin: User = Depends(require_admin),
                          database: Session = Depends(get_db)):
    report = database.scalar(select(SocialReport).where(SocialReport.id == id).with_for_update())
    if not report or report.status != "pending":
        raise HTTPException(404, "未找到待处理举报")
    if payload.action == "remove_comment":
        if report.kind != "comment":
            raise HTTPException(422, "此操作仅适用于评论")
        row = database.scalar(select(Comment).where(Comment.id == report.content_id).with_for_update())
        if row and row.deleted_at is None:
            row.deleted_at = utc_now()
    report.status = "resolved"
    report.resolution = checked_text(payload.reason, "请填写处理原因")
    write_audit(database, admin.id, f"social.report.{payload.action}", report.id, report.resolution)
    database.commit()
    return {"id": report.id, "status": report.status}
