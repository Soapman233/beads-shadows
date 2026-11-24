"""Local demo store with transactional reservations and membership grants."""
import asyncio
import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from .auth import User, current_user, require_admin, utc_now
from .catalog import Palette, PaletteColor, PaletteVersion, write_audit
from .db import enabled, get_db, session_factory
from .inventory import owner_lock, required_materials
from .payment_providers import VerifiedPaymentEvent, mock_event
from .projects import stamp
from .shop_data import CartItem, Membership, MembershipPlan, PaymentEvent, ShopOrder, ShopOrderItem, ShopSku

MAX_LINES = 64
MAX_TOTAL = 1_000_000_000
MAX_STOCK = 1_000_000_000
PAGE_SIZE = 24
RESERVATION_MINUTES = 15
logger = logging.getLogger(__name__)


def simulation_enabled():
    return os.environ.get("BEAD_MOCK_PAYMENTS") == "1"


def require_simulation():
    if not simulation_enabled():
        raise HTTPException(503, "未启用本地模拟支付")


@asynccontextmanager
async def shop_lifespan(_app):
    stop = asyncio.Event()
    worker = None
    if enabled():
        worker = asyncio.create_task(expiration_worker(stop))
    try:
        yield
    finally:
        stop.set()
        if worker:
            await worker


async def expiration_worker(stop):
    while not stop.is_set():
        try:
            await asyncio.to_thread(reap_expired_orders)
        except Exception:
            logger.warning("商城预留释放暂不可用，请检查 MySQL 和迁移状态")
        try:
            await asyncio.wait_for(stop.wait(), timeout=30)
        except TimeoutError:
            continue


router = APIRouter(tags=["商城"], lifespan=shop_lifespan)


class ShopInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SkuInput(ShopInput):
    stableColorKey: str = Field(min_length=36, max_length=36)
    title: str = Field(min_length=1, max_length=100)
    piecesPerPack: StrictInt = Field(ge=1, le=100_000)
    priceCents: StrictInt = Field(ge=1, le=1_000_000)
    availablePacks: StrictInt = Field(ge=0, le=MAX_STOCK // 2)


class SkuPatch(ShopInput):
    active: StrictBool | None = None
    availablePacks: StrictInt | None = Field(default=None, ge=0, le=MAX_STOCK // 2)
    priceCents: StrictInt | None = Field(default=None, ge=1, le=1_000_000)


class CartInput(ShopInput):
    packs: StrictInt = Field(ge=0, le=1000)


class ShortageInput(ShopInput):
    projectId: str = Field(min_length=36, max_length=36)
    revision: StrictInt = Field(ge=1)
    reservePercent: StrictInt = Field(default=0, ge=0, le=100)
    apply: StrictBool = False


class CheckoutInput(ShopInput):
    requestId: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    planId: str | None = Field(default=None, min_length=36, max_length=36)


class SimulationInput(ShopInput):
    scenario: Literal["paid", "failed"]


class ShipmentInput(ShopInput):
    trackingReference: str = Field(min_length=1, max_length=100)


Benefit = Annotated[str, Field(min_length=1, max_length=100)]


class PlanInput(ShopInput):
    title: str = Field(min_length=1, max_length=80)
    durationDays: StrictInt = Field(ge=1, le=3650)
    priceCents: StrictInt = Field(ge=1, le=1_000_000)
    benefits: list[Benefit] = Field(default_factory=list, max_length=20)


class GrantInput(ShopInput):
    userId: str = Field(min_length=36, max_length=36)
    planId: str = Field(min_length=36, max_length=36)


def sku_query():
    return (select(ShopSku, PaletteColor, Palette).select_from(ShopSku)
            .join(PaletteColor, ShopSku.palette_color_id == PaletteColor.id)
            .join(PaletteVersion, PaletteColor.version_id == PaletteVersion.id)
            .join(Palette, PaletteVersion.palette_id == Palette.id))


def sku_data(sku, color, palette):
    return {"id": sku.id, "title": sku.title, "stableColorKey": sku.stable_color_key,
            "code": color.code, "hex": color.hex, "brand": palette.brand, "series": palette.series,
            "sizeMm": float(palette.size_mm), "piecesPerPack": sku.pieces_per_pack,
            "priceCents": sku.price_cents, "availablePacks": sku.available_packs, "active": sku.active}


def listed_skus(database, page, all_states=False):
    query = sku_query()
    if not all_states:
        query = query.where(ShopSku.active.is_(True))
    rows = database.execute(query.order_by(ShopSku.title, ShopSku.id)
                            .offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE + 1)).all()
    return {"items": [sku_data(*row) for row in rows[:PAGE_SIZE]], "hasMore": len(rows) > PAGE_SIZE}


@router.get("/shop/status")
def shop_status():
    return {"simulationEnabled": simulation_enabled()}


@router.get("/shop/skus")
def shop_catalog(page: int = Query(1, ge=1, le=5000), database: Session = Depends(get_db)):
    return listed_skus(database, page)


@router.get("/admin/shop/skus")
def admin_catalog(page: int = Query(1, ge=1, le=5000), admin: User = Depends(require_admin),
                  database: Session = Depends(get_db)):
    return listed_skus(database, page, all_states=True)


@router.post("/admin/shop/skus", status_code=201)
def create_sku(body: SkuInput, admin: User = Depends(require_admin), database: Session = Depends(get_db)):
    row = database.execute(select(PaletteColor, Palette).select_from(PaletteColor)
                           .join(PaletteVersion, PaletteVersion.id == PaletteColor.version_id)
                           .join(Palette, Palette.id == PaletteVersion.palette_id)
                           .where(PaletteColor.stable_color_key == body.stableColorKey,
                                  PaletteVersion.status == "published")).one_or_none()
    if row is None:
        raise HTTPException(404, "未找到已发布色号")
    color, palette = row
    sku = ShopSku(id=str(uuid.uuid4()), stable_color_key=color.stable_color_key, palette_color_id=color.id,
                  title=body.title, pieces_per_pack=body.piecesPerPack, price_cents=body.priceCents,
                  available_packs=body.availablePacks, active=True)
    database.add(sku)
    write_audit(database, admin.id, "shop.sku.create", sku.id, "创建模拟商城材料")
    database.commit()
    return sku_data(sku, color, palette)


@router.patch("/admin/shop/skus/{sku_id}")
def update_sku(sku_id: str, body: SkuPatch, admin: User = Depends(require_admin), database: Session = Depends(get_db)):
    row = database.execute(sku_query().where(ShopSku.id == sku_id).with_for_update()).one_or_none()
    if row is None:
        raise HTTPException(404, "材料不存在")
    sku, color, palette = row
    for field, column in (("active", "active"), ("availablePacks", "available_packs"), ("priceCents", "price_cents")):
        value = getattr(body, field)
        if value is not None:
            setattr(sku, column, value)
    write_audit(database, admin.id, "shop.sku.update", sku.id, "更新材料上架、价格或可售库存")
    database.commit()
    return sku_data(sku, color, palette)


def cart_rows(database, user):
    return database.execute(sku_query().add_columns(CartItem.packs).join(CartItem, CartItem.sku_id == ShopSku.id)
                            .where(CartItem.user_id == user.id).order_by(ShopSku.title, ShopSku.id)).all()


def cart_data(database, user):
    items = [{**sku_data(sku, color, palette), "packs": packs, "lineTotalCents": sku.price_cents * packs}
             for sku, color, palette, packs in cart_rows(database, user)]
    return {"items": items, "totalCents": sum(item["lineTotalCents"] for item in items)}


def lock_cart(database, user):
    items = database.scalars(select(CartItem).where(CartItem.user_id == user.id).order_by(CartItem.sku_id).with_for_update())
    return {item.sku_id: item for item in items}


@router.get("/shop/cart")
def get_cart(user: User = Depends(current_user), database: Session = Depends(get_db)):
    return cart_data(database, user)


@router.put("/shop/cart/{sku_id}")
def set_cart(sku_id: str, body: CartInput, user: User = Depends(current_user), database: Session = Depends(get_db)):
    owner_lock(database, user)
    items = lock_cart(database, user)
    existing = items.get(sku_id)
    if body.packs == 0:
        if existing:
            database.delete(existing)
    else:
        sku = database.scalar(select(ShopSku).where(ShopSku.id == sku_id, ShopSku.active.is_(True)).with_for_update())
        if not sku:
            raise HTTPException(404, "材料未上架")
        if body.packs > sku.available_packs:
            raise HTTPException(409, "现有可售库存不足")
        if existing:
            existing.packs = body.packs
        else:
            if len(items) >= MAX_LINES:
                raise HTTPException(409, "购物车材料种类已达上限")
            database.add(CartItem(user_id=user.id, sku_id=sku.id, packs=body.packs))
    database.commit()
    return cart_data(database, user)


@router.post("/shop/cart/shortages")
def fill_shortages(body: ShortageInput, user: User = Depends(current_user), database: Session = Depends(get_db)):
    materials = required_materials(body.projectId, body.revision, body.reservePercent, user, database)
    missing = [row for row in materials["rows"] if row["shortage"] or row["shortage"] is None]
    relevant = {row["stableColorKey"] for row in missing if row["stableColorKey"]}
    if body.apply:
        owner_lock(database, user)
        items = lock_cart(database, user)
    rows = select(ShopSku).where(ShopSku.active.is_(True), ShopSku.stable_color_key.in_(relevant)).order_by(ShopSku.id)
    if body.apply:
        rows = rows.with_for_update()
    skus = list(database.scalars(rows))
    result = []
    additions = {}
    for row in missing:
        quantity = row["shortage"]
        key = row["stableColorKey"]
        candidates = []
        for sku in skus:
            if sku.stable_color_key == key and quantity is not None:
                packs = (quantity + sku.pieces_per_pack - 1) // sku.pieces_per_pack
                candidates.append((packs > sku.available_packs or packs > 1000, packs * sku.price_cents,
                                   packs * sku.pieces_per_pack - quantity, sku.id, packs, sku.available_packs))
        best = min(candidates, default=None)
        if best and not best[0]:
            additions[best[3]] = best[4]
        result.append({"code": row["code"], "beadsNeeded": quantity, "skuId": best[3] if best else None,
                       "packs": best[4] if best else None, "availablePacks": best[5] if best else None,
                       "canAdd": bool(best and not best[0])})
    if not body.apply:
        return {"items": result}
    if len(set(items) | additions.keys()) > MAX_LINES:
        raise HTTPException(409, "购物车材料种类已达上限")
    for sku_id, packs in additions.items():
        if sku_id in items:
            items[sku_id].packs = max(items[sku_id].packs, packs)
        else:
            database.add(CartItem(user_id=user.id, sku_id=sku_id, packs=packs))
    database.commit()
    return {"items": result, "cart": cart_data(database, user)}


def plan_data(plan):
    return {"id": plan.id, "title": plan.title, "durationDays": plan.duration_days,
            "priceCents": plan.price_cents, "benefits": plan.benefits, "active": plan.active}


def order_items(database, order):
    return list(database.scalars(select(ShopOrderItem).where(ShopOrderItem.order_id == order.id)
                                 .order_by(ShopOrderItem.sku_id).with_for_update()))


def order_data(order, items):
    return {"id": order.id, "status": order.status, "provider": order.provider,
            "simulation": order.provider == "local_mock", "totalCents": order.total_cents,
            "currency": "CNY", "createdAt": stamp(order.created_at), "expiresAt": stamp(order.expires_at),
            "updatedAt": stamp(order.updated_at), "trackingReference": order.tracking_reference,
            "plan": order.plan_snapshot, "items": [{**item.snapshot, "skuId": item.sku_id,
                "packs": item.packs, "priceCents": item.price_cents} for item in items]}


def order_page(database, page, user=None):
    query = select(ShopOrder)
    if user:
        query = query.where(ShopOrder.user_id == user.id)
    orders = database.scalars(query.order_by(ShopOrder.created_at.desc(), ShopOrder.id.desc())
                              .offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE + 1)).all()
    items_by_order = {order.id: [] for order in orders[:PAGE_SIZE]}
    items = database.scalars(select(ShopOrderItem).where(ShopOrderItem.order_id.in_(items_by_order))
                             .order_by(ShopOrderItem.sku_id))
    for item in items:
        items_by_order[item.order_id].append(item)
    return {"items": [{**order_data(order, items_by_order[order.id]), **({} if user else {"userId": order.user_id})}
                      for order in orders[:PAGE_SIZE]], "hasMore": len(orders) > PAGE_SIZE}


@router.get("/shop/orders")
def my_orders(page: int = Query(1, ge=1, le=5000), user: User = Depends(current_user),
              database: Session = Depends(get_db)):
    return order_page(database, page, user)


@router.get("/admin/shop/orders")
def admin_orders(page: int = Query(1, ge=1, le=5000), admin: User = Depends(require_admin),
                 database: Session = Depends(get_db)):
    return order_page(database, page)


@router.post("/shop/orders", status_code=201)
def checkout(body: CheckoutInput, user: User = Depends(current_user), database: Session = Depends(get_db)):
    require_simulation()
    for attempt in range(3):
        try:
            return reserve_order(body, user, database)
        except OperationalError as error:
            if getattr(error.orig, "args", ())[:1] not in ((1213,), (1205,)):
                raise
            database.rollback()
            if attempt == 2:
                raise HTTPException(409, "订单正在竞争库存，请用相同请求编号重试") from None


def reserve_order(body, user, database):
    owner_lock(database, user)
    existing = database.scalar(select(ShopOrder).where(ShopOrder.user_id == user.id,
                                ShopOrder.request_id == body.requestId).with_for_update())
    if existing:
        if existing.plan_id != body.planId:
            raise HTTPException(409, "请求编号已用于另一种订单")
        return order_data(existing, order_items(database, existing))
    items = {}
    plan = None
    if body.planId:
        plan = database.scalar(select(MembershipPlan).where(MembershipPlan.id == body.planId,
                                                           MembershipPlan.active.is_(True)).with_for_update())
        if plan is None:
            raise HTTPException(404, "套餐未上架")
        total = plan.price_cents
    else:
        cart = lock_cart(database, user)
        if not cart:
            raise HTTPException(422, "购物车为空")
        skus = list(database.scalars(select(ShopSku).where(ShopSku.id.in_(cart)).order_by(ShopSku.id).with_for_update()))
        if len(skus) != len(cart):
            raise HTTPException(409, "购物车包含不可用材料")
        total = 0
        for sku in skus:
            item = cart[sku.id]
            if not sku.active or item.packs > sku.available_packs:
                raise HTTPException(409, "有材料已下架或库存不足，请更新购物车")
            _, color, palette = database.execute(sku_query().where(ShopSku.id == sku.id)).one()
            snapshot = sku_data(sku, color, palette)
            items[sku.id] = (sku, item.packs, {key: snapshot[key] for key in
                            ("title", "code", "hex", "brand", "series", "sizeMm", "piecesPerPack")})
            total += item.packs * sku.price_cents
        if total > MAX_TOTAL:
            raise HTTPException(422, "订单金额超出上限")
    order = ShopOrder(id=str(uuid.uuid4()), user_id=user.id, request_id=body.requestId,
                      plan_id=plan.id if plan else None, plan_snapshot=plan_data(plan) if plan else None,
                      total_cents=total, expires_at=utc_now() + timedelta(minutes=RESERVATION_MINUTES))
    database.add(order)
    database.flush()
    order_lines = []
    for sku, packs, snapshot in items.values():
        sku.available_packs -= packs
        order_lines.append(ShopOrderItem(order_id=order.id, sku_id=sku.id, snapshot=snapshot,
                                         packs=packs, price_cents=sku.price_cents))
        database.delete(cart[sku.id])
    database.add_all(order_lines)
    database.commit()
    return order_data(order, order_lines)


def find_order(database, order_id, user=None):
    query = select(ShopOrder).where(ShopOrder.id == order_id)
    if user:
        query = query.where(ShopOrder.user_id == user.id)
    order = database.scalar(query.with_for_update())
    if not order:
        raise HTTPException(404, "未找到订单")
    return order


def release_stock(database, items):
    reserved = {item.sku_id: item.packs for item in items}
    for sku in database.scalars(select(ShopSku).where(ShopSku.id.in_(reserved)).order_by(ShopSku.id).with_for_update()):
        sku.available_packs += reserved[sku.id]


def set_status(order, status):
    order.status = status
    order.updated_at = utc_now()


def expire_one(database, order, items):
    if order.status == "awaiting_payment" and order.expires_at <= utc_now():
        release_stock(database, items)
        set_status(order, "expired")
        return True
    return False


def reap_expired_orders():
    factory = session_factory()
    for _ in range(20):
        with factory() as database:
            order = database.scalar(select(ShopOrder).where(ShopOrder.status == "awaiting_payment",
                                    ShopOrder.expires_at <= utc_now()).order_by(ShopOrder.expires_at, ShopOrder.id)
                                    .limit(1).with_for_update(skip_locked=True))
            if order is None:
                return
            expire_one(database, order, order_items(database, order))
            database.commit()


@router.post("/shop/orders/{order_id}/cancel")
def cancel_order(order_id: str, user: User = Depends(current_user), database: Session = Depends(get_db)):
    order = find_order(database, order_id, user)
    items = order_items(database, order)
    if order.status == "awaiting_payment" and not expire_one(database, order, items):
        release_stock(database, items)
        set_status(order, "canceled")
    if order.status not in ("canceled", "expired"):
        raise HTTPException(409, "当前订单不可取消")
    database.commit()
    return order_data(order, items)


@router.post("/shop/orders/{order_id}/refund")
def request_refund(order_id: str, user: User = Depends(current_user), database: Session = Depends(get_db)):
    order = find_order(database, order_id, user)
    if order.status == "paid":
        set_status(order, "refund_requested")
        database.commit()
    elif order.status not in ("refund_requested", "refunded"):
        raise HTTPException(409, "当前订单不可申请退款")
    return order_data(order, order_items(database, order))


def grant_membership(database, user_id, plan_snapshot, order_id=None):
    start = utc_now().replace(microsecond=0)
    row = Membership(id=str(uuid.uuid4()), user_id=user_id, plan_id=plan_snapshot["id"], order_id=order_id,
                     snapshot=plan_snapshot, starts_at=start,
                     expires_at=start + timedelta(days=plan_snapshot["durationDays"]))
    database.add(row)
    return row


def apply_payment_event(database: Session, order: ShopOrder, items: list[ShopOrderItem], event: VerifiedPaymentEvent):
    """Apply a provider-verified event while the corresponding order row is locked."""
    if (event.provider != order.provider or event.order_id != order.id or event.amount_cents != order.total_cents
            or event.currency != "CNY"):
        raise HTTPException(422, "支付事件信息与订单不匹配")
    previous = database.scalar(select(PaymentEvent).where(PaymentEvent.provider == event.provider,
                                PaymentEvent.event_id == event.id).with_for_update())
    if previous:
        if previous.order_id != order.id or previous.kind != event.kind or previous.amount_cents != event.amount_cents:
            raise HTTPException(409, "事件编号已用于另一笔操作")
        return
    if event.kind == "paid" and order.status == "awaiting_payment":
        if order.plan_id:
            grant_membership(database, order.user_id, order.plan_snapshot, order.id)
        set_status(order, "paid")
    elif event.kind == "failed" and order.status == "awaiting_payment":
        release_stock(database, items)
        set_status(order, "failed")
    elif event.kind == "refunded" and order.status == "refund_requested":
        release_stock(database, items)
        membership = database.scalar(select(Membership).where(Membership.order_id == order.id).with_for_update())
        if membership:
            membership.revoked_at = utc_now()
        set_status(order, "refunded")
    else:
        raise HTTPException(409, "订单状态与支付事件不匹配")
    database.add(PaymentEvent(id=str(uuid.uuid4()), order_id=order.id, provider=event.provider, event_id=event.id,
                              kind=event.kind, amount_cents=event.amount_cents, currency=event.currency))


@router.post("/shop/orders/{order_id}/simulate-payment")
def simulate_payment(order_id: str, body: SimulationInput, user: User = Depends(current_user),
                     database: Session = Depends(get_db)):
    require_simulation()
    order = find_order(database, order_id, user)
    items = order_items(database, order)
    if expire_one(database, order, items):
        database.commit()
        raise HTTPException(409, "订单已过期，库存已释放")
    apply_payment_event(database, order, items, mock_event(order, body.scenario))
    database.commit()
    return order_data(order, items)


@router.post("/admin/shop/orders/{order_id}/refund")
def simulate_refund(order_id: str, admin: User = Depends(require_admin), database: Session = Depends(get_db)):
    require_simulation()
    order = find_order(database, order_id)
    items = order_items(database, order)
    original = order.status
    apply_payment_event(database, order, items, mock_event(order, "refunded"))
    if order.status != original:
        write_audit(database, admin.id, "shop.mock.refund", order.id, "处理模拟退款")
    database.commit()
    return order_data(order, items)


@router.post("/admin/shop/orders/{order_id}/ship")
def record_shipment(order_id: str, body: ShipmentInput, admin: User = Depends(require_admin),
                    database: Session = Depends(get_db)):
    require_simulation()
    order = find_order(database, order_id)
    if order.provider != "local_mock" or order.plan_id:
        raise HTTPException(409, "此订单不属于模拟材料发货")
    if order.status == "paid":
        order.tracking_reference = body.trackingReference
        set_status(order, "shipped")
        write_audit(database, admin.id, "shop.mock.ship", order.id, "记录模拟发货")
        database.commit()
    elif order.status != "shipped" or order.tracking_reference != body.trackingReference:
        raise HTTPException(409, "当前订单无法登记此发货记录")
    return order_data(order, order_items(database, order))


@router.get("/shop/plans")
def plans(database: Session = Depends(get_db)):
    rows = database.scalars(select(MembershipPlan).where(MembershipPlan.active.is_(True))
                            .order_by(MembershipPlan.price_cents, MembershipPlan.id).limit(100))
    return {"items": [plan_data(row) for row in rows]}


@router.post("/admin/shop/plans", status_code=201)
def create_plan(body: PlanInput, admin: User = Depends(require_admin), database: Session = Depends(get_db)):
    row = MembershipPlan(id=str(uuid.uuid4()), title=body.title, duration_days=body.durationDays,
                         price_cents=body.priceCents, benefits=list(dict.fromkeys(body.benefits)))
    database.add(row)
    write_audit(database, admin.id, "shop.plan.create", row.id, "创建会员套餐")
    database.commit()
    return plan_data(row)


def membership_data(row):
    now = utc_now()
    return {"id": row.id, "plan": row.snapshot, "startsAt": stamp(row.starts_at), "expiresAt": stamp(row.expires_at),
            "active": row.revoked_at is None and row.starts_at <= now < row.expires_at}


@router.get("/shop/memberships")
def memberships(user: User = Depends(current_user), database: Session = Depends(get_db)):
    rows = database.scalars(select(Membership).where(Membership.user_id == user.id)
                            .order_by(Membership.expires_at.desc(), Membership.id.desc()).limit(100))
    return {"items": [membership_data(row) for row in rows]}


@router.post("/admin/shop/memberships", status_code=201)
def admin_grant(body: GrantInput, admin: User = Depends(require_admin), database: Session = Depends(get_db)):
    account = database.scalar(select(User).where(User.id == body.userId, User.status == "active").with_for_update())
    plan = database.scalar(select(MembershipPlan).where(MembershipPlan.id == body.planId, MembershipPlan.active.is_(True)))
    if account is None or plan is None:
        raise HTTPException(404, "未找到可用账号或套餐")
    row = grant_membership(database, account.id, plan_data(plan))
    write_audit(database, admin.id, "shop.membership.grant", row.id, "发放会员权益")
    database.commit()
    return membership_data(row)
