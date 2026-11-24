"""Private bead inventory and material requirements for immutable pattern revisions."""
import csv
import io
import re
import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from sqlalchemy import JSON, CheckConstraint, ForeignKey, Index, Numeric, String, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .auth import User, current_user, utc_now
from .catalog import Palette, PaletteColor, PaletteVersion
from .db import Base, get_db
from .projects import ProjectVersion, find_project, stamp

router = APIRouter(tags=["库存与用料"])
MAX_QUANTITY = 1_000_000_000
MAX_ITEMS = 4096
KIND_SIGNS = {"stock_in": 1, "return": 1, "issue": -1, "loss": -1}


class InventoryItem(Base):
    __tablename__ = "inventory_items"
    __table_args__ = (
        UniqueConstraint("user_id", "stable_color_key", name="uq_inventory_color"),
        CheckConstraint("quantity BETWEEN 0 AND 1000000000", name="ck_inventory_quantity"),
        CheckConstraint("unit_price >= 0", name="ck_inventory_price"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    palette_color_id: Mapped[int] = mapped_column(ForeignKey("palette_colors.id"))
    stable_color_key: Mapped[str] = mapped_column(String(36))
    quantity: Mapped[int] = mapped_column(default=0)
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))


class InventoryRequest(Base):
    __tablename__ = "inventory_requests"
    __table_args__ = (UniqueConstraint("user_id", "request_id", name="uq_inventory_request"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    request_id: Mapped[str] = mapped_column(String(80, collation="utf8mb4_bin"))
    command: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=utc_now)


class InventoryMovement(Base):
    __tablename__ = "inventory_movements"
    __table_args__ = (
        Index("ix_inventory_movements_time", "item_id", "created_at", "id"),
        CheckConstraint("kind IN ('stock_in','issue','return','loss')", name="ck_inventory_movement_kind"),
        CheckConstraint("delta <> 0", name="ck_inventory_movement_delta"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    item_id: Mapped[str] = mapped_column(ForeignKey("inventory_items.id"))
    operation_id: Mapped[str] = mapped_column(ForeignKey("inventory_requests.id"))
    project_version_id: Mapped[str | None] = mapped_column(ForeignKey("project_versions.id"))
    kind: Mapped[str] = mapped_column(String(12))
    delta: Mapped[int]
    balance: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(default=utc_now)


class ItemInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stableColorKey: str = Field(min_length=36, max_length=36)
    unitPrice: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=4)


class MovementInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    itemId: str = Field(min_length=36, max_length=36)
    kind: Literal["stock_in", "issue", "return", "loss"]
    quantity: StrictInt = Field(gt=0, le=MAX_QUANTITY)
    piecesPerPack: StrictInt | None = Field(default=None, gt=0, le=MAX_QUANTITY)
    requestId: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    projectVersionId: str | None = Field(default=None, min_length=36, max_length=36)


class InventoryImport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    versionId: str = Field(min_length=36, max_length=36)
    csv: str = Field(min_length=1, max_length=64_000)
    requestId: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")


def owner_lock(database: Session, user: User):
    # Serializes writes and establishes one lock order for imports and single edits.
    status = database.scalar(select(User.status).where(User.id == user.id).with_for_update())
    if status != "active":
        raise HTTPException(401, "账号当前不可用")


def item_join():
    return (select(InventoryItem, PaletteColor, Palette)
            .join(PaletteColor, PaletteColor.id == InventoryItem.palette_color_id)
            .join(PaletteVersion, PaletteVersion.id == PaletteColor.version_id)
            .join(Palette, Palette.id == PaletteVersion.palette_id))


def serialize_item(item, color, palette):
    return {"id": item.id, "stableColorKey": item.stable_color_key, "brand": palette.brand,
            "series": palette.series, "sizeMm": float(palette.size_mm), "code": color.code,
            "hex": color.hex, "quantity": item.quantity,
            "unitPrice": format(item.unit_price, "f") if item.unit_price is not None else None}


@router.get("/inventory")
def list_items(user: User = Depends(current_user), database: Session = Depends(get_db)):
    rows = database.execute(item_join().where(InventoryItem.user_id == user.id)
                            .order_by(Palette.brand, Palette.series, Palette.size_mm, PaletteColor.code))
    return [serialize_item(*row) for row in rows]


def item_count(database, user):
    return len(database.scalars(select(InventoryItem.id).where(InventoryItem.user_id == user.id).with_for_update()).all())


@router.post("/inventory")
def add_item(payload: ItemInput, user: User = Depends(current_user), database: Session = Depends(get_db)):
    owner_lock(database, user)
    item = database.scalar(select(InventoryItem).where(InventoryItem.user_id == user.id,
                           InventoryItem.stable_color_key == payload.stableColorKey).with_for_update())
    if item is None:
        color = database.scalar(select(PaletteColor).join(PaletteVersion).where(
            PaletteColor.stable_color_key == payload.stableColorKey, PaletteVersion.status == "published"))
        if color is None:
            raise HTTPException(404, "色号未发布或不存在")
        if item_count(database, user) >= MAX_ITEMS:
            raise HTTPException(409, "库存色号数量达到上限")
        item = InventoryItem(id=str(uuid.uuid4()), user_id=user.id, palette_color_id=color.id,
                             stable_color_key=color.stable_color_key, quantity=0)
        database.add(item)
    if "unitPrice" in payload.model_fields_set:
        item.unit_price = payload.unitPrice
    database.flush()
    result = serialize_item(*database.execute(item_join().where(InventoryItem.id == item.id).with_for_update()).one())
    database.commit()
    return result


def request_operation(database, user, key, command):
    previous = database.scalar(select(InventoryRequest).where(InventoryRequest.user_id == user.id,
                               InventoryRequest.request_id == key).with_for_update())
    if previous:
        if previous.command != command:
            raise HTTPException(409, "请求编号已用于其他库存操作")
        return previous, True
    operation = InventoryRequest(id=str(uuid.uuid4()), user_id=user.id, request_id=key, command=command, result={})
    database.add(operation)
    database.flush()
    return operation, False


def serialize_movement(movement):
    return {"id": movement.id, "itemId": movement.item_id, "kind": movement.kind,
            "delta": movement.delta, "balance": movement.balance,
            "projectVersionId": movement.project_version_id, "createdAt": stamp(movement.created_at)}


def record(database, item, operation, kind, quantity, version_id=None):
    delta = KIND_SIGNS[kind] * quantity
    balance = item.quantity + delta
    if balance < 0:
        raise HTTPException(409, "库存不足，未扣减")
    if balance > MAX_QUANTITY:
        raise HTTPException(409, "库存数量达到上限")
    movement = InventoryMovement(id=str(uuid.uuid4()), item_id=item.id, operation_id=operation.id,
                                 project_version_id=version_id, kind=kind, delta=delta, balance=balance,
                                 created_at=utc_now())
    database.add(movement)
    item.quantity = balance
    return serialize_movement(movement)


@router.post("/inventory/movements", status_code=201)
def change_inventory(payload: MovementInput, user: User = Depends(current_user), database: Session = Depends(get_db)):
    quantity = payload.quantity * (payload.piecesPerPack or 1)
    if quantity > MAX_QUANTITY:
        raise HTTPException(422, "换算后数量超过上限")
    owner_lock(database, user)
    row = database.execute(item_join().where(InventoryItem.id == payload.itemId,
                          InventoryItem.user_id == user.id).with_for_update()).one_or_none()
    if row is None:
        raise HTTPException(404, "未找到库存项目")
    if payload.projectVersionId:
        version = database.get(ProjectVersion, payload.projectVersionId)
        if version is None:
            raise HTTPException(404, "未找到图纸版本")
        find_project(database, user, version.project_id)
    operation, reused = request_operation(database, user, payload.requestId,
                                          {"type": "movement", **payload.model_dump(exclude={"requestId"})})
    if reused:
        return operation.result
    item, color, palette = row
    result = {"movement": record(database, item, operation, payload.kind, quantity, payload.projectVersionId),
              "item": serialize_item(item, color, palette)}
    operation.result = result
    database.commit()
    return result


@router.get("/inventory/{item_id}/movements")
def movement_history(item_id: str, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0),
                     user: User = Depends(current_user), database: Session = Depends(get_db)):
    item = database.scalar(select(InventoryItem.id).where(InventoryItem.id == item_id, InventoryItem.user_id == user.id))
    if item is None:
        raise HTTPException(404, "未找到库存项目")
    rows = database.scalars(select(InventoryMovement).where(InventoryMovement.item_id == item)
                            .order_by(InventoryMovement.created_at.desc(), InventoryMovement.id.desc())
                            .offset(offset).limit(limit))
    return [serialize_movement(row) for row in rows]


def parse_inventory_csv(source):
    rows = {}
    try:
        reader = csv.DictReader(io.StringIO(source.lstrip("\ufeff"), newline=""), strict=True)
        fields = reader.fieldnames or []
        if len(set(fields)) != len(fields) or not {"code", "quantity"} <= set(fields) <= {"code", "quantity", "unitPrice"}:
            raise HTTPException(422, "CSV 列应为 code,quantity[,unitPrice]，quantity 按颗")
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError()
            code, raw_quantity = row["code"].strip(), row["quantity"].strip()
            price = row.get("unitPrice", "").strip()
            if (not 1 <= len(code) <= 32 or code in rows or not re.fullmatch(r"[1-9][0-9]{0,9}", raw_quantity)
                    or int(raw_quantity) > MAX_QUANTITY
                    or (price and not re.fullmatch(r"[0-9]{1,8}(\.[0-9]{1,4})?", price))):
                raise ValueError()
            rows[code] = int(raw_quantity), Decimal(price) if price else None
            if len(rows) > 512:
                raise ValueError()
    except (ValueError, InvalidOperation, csv.Error):
        raise HTTPException(422, "库存 CSV 含重复色号、无效数量或单价") from None
    if not rows:
        raise HTTPException(422, "库存 CSV 不能为空")
    return rows


@router.post("/inventory/import", status_code=201)
def import_inventory(payload: InventoryImport, user: User = Depends(current_user), database: Session = Depends(get_db)):
    rows = parse_inventory_csv(payload.csv)
    owner_lock(database, user)
    command = {"type": "import", "versionId": payload.versionId,
               "rows": {code: [quantity, format(price, "f") if price is not None else None]
                        for code, (quantity, price) in rows.items()}}
    operation, reused = request_operation(database, user, payload.requestId, command)
    if reused:
        return operation.result
    available = database.execute(
        select(PaletteColor, Palette).select_from(PaletteColor)
        .join(PaletteVersion, PaletteVersion.id == PaletteColor.version_id)
        .join(Palette, Palette.id == PaletteVersion.palette_id)
        .where(PaletteVersion.id == payload.versionId, PaletteVersion.status == "published", PaletteColor.code.in_(rows))
    ).all()
    colors = {color.code: (color, palette) for color, palette in available}
    if rows.keys() - colors.keys():
        raise HTTPException(422, "所选已发布色卡中有色号不存在")
    items = {item.stable_color_key: item for item in database.scalars(select(InventoryItem).where(
        InventoryItem.user_id == user.id).with_for_update())}
    if len(items) + sum(color.stable_color_key not in items for color, _ in colors.values()) > MAX_ITEMS:
        raise HTTPException(409, "库存色号数量达到上限")
    changed = []
    for code, (quantity, price) in rows.items():
        color, palette = colors[code]
        item = items.get(color.stable_color_key)
        if item is None:
            item = InventoryItem(id=str(uuid.uuid4()), user_id=user.id, palette_color_id=color.id,
                                 stable_color_key=color.stable_color_key, quantity=0)
            database.add(item)
            database.flush()
        if price is not None:
            item.unit_price = price
        item.palette_color_id = color.id
        record(database, item, operation, "stock_in", quantity)
        changed.append(serialize_item(item, color, palette))
    operation.result = {"items": changed}
    database.commit()
    return operation.result


def matched_colors(database, pattern):
    palette_id = pattern.get("paletteId", "")
    if not palette_id.startswith("db:"):
        return {}
    version_id = palette_id[3:]
    snapshot = {color["code"]: color["hex"].upper() for color in pattern["palette"]}
    rows = database.scalars(select(PaletteColor).join(PaletteVersion).where(
        PaletteVersion.id == version_id, PaletteVersion.status.in_(("published", "retired"))))
    return {row.code: row.stable_color_key for row in rows if snapshot.get(row.code) == row.hex}


@router.get("/projects/{project_id}/versions/{revision}/materials")
def required_materials(project_id: str, revision: int, reservePercent: int = Query(0, ge=0, le=100),
                       user: User = Depends(current_user), database: Session = Depends(get_db)):
    project = find_project(database, user, project_id)
    version = database.scalar(select(ProjectVersion).where(ProjectVersion.project_id == project.id,
                                                           ProjectVersion.revision == revision))
    if version is None:
        raise HTTPException(404, "未找到图纸版本")
    pattern = version.data.get("pattern")
    if pattern is None:
        raise HTTPException(409, "此版本尚无图纸")
    stable_keys = matched_colors(database, pattern)
    keys = set(stable_keys.values())
    stock = {row.stable_color_key: row for row in database.scalars(select(InventoryItem).where(
        InventoryItem.user_id == user.id, InventoryItem.stable_color_key.in_(keys)))}
    swatches = {color["code"]: color["hex"] for color in pattern["palette"]}
    rows = []
    for code, needed in sorted(version.counts.items()):
        key = stable_keys.get(code)
        reserve = (needed * (100 + reservePercent) + 99) // 100
        item = stock.get(key)
        on_hand = (item.quantity if item else 0) if key else None
        missing = max(0, reserve - on_hand) if on_hand is not None else None
        unit_price = item.unit_price if item else None
        estimated = (unit_price * missing).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if unit_price is not None else None
        rows.append({"code": code, "hex": swatches[code], "stableColorKey": key, "needed": needed,
                     "withReserve": reserve, "onHand": on_hand, "shortage": missing,
                     "unitPrice": format(unit_price, "f") if unit_price is not None else None,
                     "estimatedCost": format(estimated, "f") if estimated is not None else None})
    return {"projectId": project.id, "versionId": version.id, "revision": version.revision,
            "reservePercent": reservePercent, "beadCount": version.bead_count,
            "unmapped": sum(row["stableColorKey"] is None for row in rows), "rows": rows}
