"""Private in-app notifications shared by product services."""
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import ForeignKey, Index, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .auth import User, current_user, utc_now
from .db import Base, get_db
from .projects import stamp

router = APIRouter(prefix="/notifications", tags=["站内通知"])


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notice_recipient_time", "user_id", "created_at", "id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(24))
    target_id: Mapped[str] = mapped_column(String(36))
    text: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(default=utc_now)
    read_at: Mapped[datetime | None]


def create_notice(database, user_id, kind, target_id, text):
    database.add(Notification(id=str(uuid.uuid4()), user_id=user_id, kind=kind, target_id=target_id, text=text))


def notice_data(row):
    return {"id": row.id, "kind": row.kind, "targetId": row.target_id, "text": row.text,
            "createdAt": stamp(row.created_at), "read": row.read_at is not None}


@router.get("")
def notifications(page: int = Query(1, ge=1, le=2000), user: User = Depends(current_user),
                  database: Session = Depends(get_db)):
    rows = database.scalars(select(Notification).where(Notification.user_id == user.id)
                            .order_by(Notification.created_at.desc(), Notification.id.desc())
                            .offset((page - 1) * 30).limit(31)).all()
    return {"items": [notice_data(row) for row in rows[:30]], "hasMore": len(rows) > 30}


@router.patch("/{id}/read")
def read_notice(id: str, user: User = Depends(current_user), database: Session = Depends(get_db)):
    row = database.scalar(select(Notification).where(Notification.id == id, Notification.user_id == user.id).with_for_update())
    if row is None:
        raise HTTPException(404, "未找到通知")
    if row.read_at is None:
        row.read_at = utc_now()
        database.commit()
    return notice_data(row)
