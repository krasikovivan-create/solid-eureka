"""Заказы: создание из корзины, смена статусов, оплата, отмена, повтор."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.constants import (
    ORDER_TRANSITIONS,
    SUCCESSFUL_STATUSES,
    USER_CANCELLABLE,
    OrderStatus,
    PaymentMethod,
    UserEvent,
)
from app.db.base import utcnow
from app.db.models import (
    Order,
    OrderItem,
    OrderStatusHistory,
    StylistLook,
    User,
)
from app.repositories.users import UserRepository
from app.services.cart import CartService, CartSummary, NotEnoughStock, VariantUnavailable
from app.services.delivery import DeliveryCalculator, DeliveryProvider, DeliveryQuote
from app.services.notifications import Notifier
from app.services.promo import PromoService
from app.services.stock import OutOfStock, StockService

logger = logging.getLogger(__name__)


class OrderError(Exception):
    pass


class CartChanged(OrderError):
    """Корзина пуста, товара не хватает или промокод перестал действовать."""


class InvalidTransition(OrderError):
    def __init__(self, current: str, target: str) -> None:
        super().__init__(f"{current} -> {target}")
        self.current = current
        self.target = target


@dataclass(slots=True)
class CheckoutData:
    name: str
    phone: str
    city: str
    address: str
    method: str
    use_bonus: bool = False


@dataclass(slots=True)
class Totals:
    items_total: int
    discount: int
    bonus: int
    delivery: int

    @property
    def total(self) -> int:
        return self.items_total - self.discount - self.bonus + self.delivery


def max_bonus(balance: int, items_total: int, discount: int, share_percent: int) -> int:
    """Сколько бонусов можно списать: не больше баланса и не больше доли от товаров."""
    payable = max(items_total - discount - 1, 0)
    return max(0, min(balance, payable * share_percent // 100))


def calc_totals(
    summary: CartSummary, quote: DeliveryQuote, user: User, use_bonus: bool, share_percent: int
) -> Totals:
    bonus = 0
    if use_bonus:
        bonus = max_bonus(user.bonus_balance, summary.items_total, summary.discount, share_percent)
    return Totals(summary.items_total, summary.discount, bonus, quote.price)


class OrderService:
    def __init__(
        self,
        session: AsyncSession,
        notifier: Notifier,
        providers: dict[str, DeliveryProvider],
        *,
        referral_bonus: int = 300,
        bonus_share_percent: int = 30,
    ) -> None:
        self.session = session
        self.notifier = notifier
        self.providers = providers
        self.referral_bonus = referral_bonus
        self.bonus_share_percent = bonus_share_percent
        self.stock = StockService(session)

    # ---------- Чтение ----------
    async def get(self, order_id: int, user_id: int | None = None) -> Order | None:
        stmt = (
            select(Order)
            .where(Order.id == order_id)
            .options(selectinload(Order.items), selectinload(Order.history))
            .execution_options(populate_existing=True)
        )
        if user_id is not None:
            stmt = stmt.where(Order.user_id == user_id)
        return await self.session.scalar(stmt)

    async def list_for_user(self, user_id: int, limit: int = 20) -> list[Order]:
        stmt = select(Order).where(Order.user_id == user_id).order_by(Order.id.desc()).limit(limit)
        return list((await self.session.scalars(stmt)).all())

    async def list_admin(
        self, status: str | None, offset: int = 0, limit: int = 8
    ) -> tuple[list[Order], int]:
        stmt = select(Order)
        count_stmt = select(func.count(Order.id))
        if status:
            stmt = stmt.where(Order.status == status)
            count_stmt = count_stmt.where(Order.status == status)
        stmt = stmt.order_by(Order.id.desc()).offset(offset).limit(limit)
        orders = list((await self.session.scalars(stmt)).all())
        return orders, int(await self.session.scalar(count_stmt) or 0)

    # ---------- Создание ----------
    async def quote(self, data: CheckoutData, items_total: int) -> DeliveryQuote:
        return await DeliveryCalculator(self.session, self.providers).quote(
            data.city, data.method, items_total
        )

    async def create_from_cart(self, user: User, data: CheckoutData, payment_method: str) -> Order:
        cart = CartService(self.session)
        summary = await cart.summary(user)
        if summary.is_empty or summary.has_problems or summary.promo_error is not None:
            raise CartChanged
        quote = await self.quote(data, summary.items_total - summary.discount)
        totals = calc_totals(summary, quote, user, data.use_bonus, self.bonus_share_percent)

        order = Order(
            user_id=user.id,
            status=OrderStatus.NEW,
            customer_name=data.name,
            phone=data.phone,
            delivery_method=data.method,
            city=data.city,
            address=data.address,
            delivery_price=quote.price,
            delivery_days_min=quote.days_min,
            delivery_days_max=quote.days_max,
            items_total=totals.items_total,
            discount=totals.discount,
            bonus_used=totals.bonus,
            total=totals.total,
            promo_id=summary.promo.id if summary.promo else None,
            payment_method=payment_method,
            items=[
                OrderItem(
                    product_id=line.product_id,
                    variant_id=line.variant_id,
                    title=line.title,
                    size=line.size,
                    color=line.color,
                    price=line.price,
                    qty=line.qty,
                )
                for line in summary.lines
            ],
            history=[OrderStatusHistory(from_status=None, to_status=OrderStatus.NEW)],
        )
        self.session.add(order)
        await self.session.flush()

        if payment_method == PaymentMethod.COD:
            # Оплата при получении: резервируем товар сразу, иначе его могут купить.
            try:
                await self.stock.deduct(order)
            except OutOfStock as exc:
                await self.session.rollback()
                raise CartChanged from exc
        elif await self.stock.check(order):
            await self.session.rollback()
            raise CartChanged

        if summary.promo:
            await PromoService(self.session).register_usage(summary.promo, user.id, order.id)
        if totals.bonus:
            user.bonus_balance -= totals.bonus
        look_ids = {line.look_id for line in summary.lines if line.look_id}
        if look_ids:
            await self.session.execute(
                update(StylistLook)
                .where(StylistLook.id.in_(look_ids), StylistLook.order_id.is_(None))
                .values(order_id=order.id)
            )
        await cart.clear(user.id)
        user.cart_promo_code = None
        await UserRepository(self.session).log_event(user.id, UserEvent.ORDER_CREATED)
        await self.session.commit()
        order = await self.get(order.id)
        await self.notifier.new_order(order)
        return order

    # ---------- Оплата ----------
    async def validate_for_payment(self, order_id: int, user_id: int, amount: int) -> bool:
        """Проверка перед списанием денег (pre_checkout_query)."""
        order = await self.get(order_id, user_id)
        if order is None or order.status != OrderStatus.NEW or order.is_paid:
            return False
        if order.total != amount:
            return False
        return not await self.stock.check(order)

    async def mark_paid(
        self,
        order_id: int,
        telegram_charge_id: str | None = None,
        provider_charge_id: str | None = None,
    ) -> Order:
        order = await self.get(order_id)
        if order is None:
            raise OrderError(f"order {order_id} not found")
        if order.is_paid:
            return order
        shortages = await self.stock.deduct(order, allow_partial=True)
        if shortages:
            order.comment = "Нехватка на складе при оплате — свяжитесь с покупателем"
        order.is_paid = True
        order.paid_at = utcnow()
        order.telegram_charge_id = telegram_charge_id
        order.provider_charge_id = provider_charge_id
        await UserRepository(self.session).log_event(order.user_id, UserEvent.ORDER_PAID)
        await self._apply_status(order, OrderStatus.PAID, changed_by=None)
        await self.session.commit()
        await self.notifier.order_status_changed(order)
        await self.notifier.order_paid(order)
        if shortages:
            await self.notifier.refund_needed(order)
        await self._reward_referrer(order)
        return order

    # ---------- Статусы ----------
    async def _apply_status(
        self, order: Order, target: str, changed_by: int | None, comment: str | None = None
    ) -> None:
        current = OrderStatus(order.status)
        target = OrderStatus(target)
        if target not in ORDER_TRANSITIONS[current]:
            raise InvalidTransition(current, target)
        if (
            target == OrderStatus.ASSEMBLING
            and current == OrderStatus.NEW
            and order.payment_method == PaymentMethod.CARD
        ):
            # Онлайн-заказ нельзя собирать, пока он не оплачен.
            raise InvalidTransition(current, target)

        if target in (OrderStatus.PAID, OrderStatus.ASSEMBLING) and not order.stock_deducted:
            await self.stock.deduct(order, allow_partial=True)
        if target == OrderStatus.PAID and not order.is_paid:
            # Ручная отметка оплаты админом (например, перевод по счёту).
            order.is_paid = True
            order.paid_at = utcnow()
        if target in (OrderStatus.CANCELLED, OrderStatus.RETURNED):
            await self.stock.restore(order)
        if target == OrderStatus.CANCELLED:
            if order.promo_id:
                await PromoService(self.session).release_usage(order.promo_id, order.id)
            if order.bonus_used:
                user = await self.session.get(User, order.user_id)
                if user:
                    user.bonus_balance += order.bonus_used
        if target == OrderStatus.SHIPPED and not order.track_number:
            provider = self.providers.get(order.delivery_method)
            if provider is not None:
                order.track_number = await provider.create_shipment(order)
        if target == OrderStatus.DELIVERED and order.payment_method == PaymentMethod.COD:
            order.is_paid = True
            order.paid_at = utcnow()

        order.status = target
        order.history.append(
            OrderStatusHistory(
                from_status=current, to_status=target, changed_by=changed_by, comment=comment
            )
        )

    async def change_status(
        self, order_id: int, target: str, changed_by: int | None = None, comment: str | None = None
    ) -> Order:
        order = await self.get(order_id)
        if order is None:
            raise OrderError(f"order {order_id} not found")
        await self._apply_status(order, target, changed_by, comment)
        await self.session.commit()
        await self.notifier.order_status_changed(order)
        if target in (OrderStatus.PAID, OrderStatus.DELIVERED):
            await self._reward_referrer(order)
        return order

    async def set_track(self, order_id: int, track_number: str) -> Order:
        order = await self.get(order_id)
        if order is None:
            raise OrderError(f"order {order_id} not found")
        order.track_number = track_number.strip()
        await self.session.commit()
        await self.notifier.order_status_changed(order)
        return order

    async def create_shipment(self, order_id: int) -> Order:
        order = await self.get(order_id)
        if order is None:
            raise OrderError(f"order {order_id} not found")
        provider = self.providers.get(order.delivery_method)
        track = await provider.create_shipment(order) if provider else None
        if not track:
            raise OrderError("Эта служба доставки не выдаёт трек-номер")
        return await self.set_track(order_id, track)

    async def cancel_by_user(self, user_id: int, order_id: int) -> Order:
        order = await self.get(order_id, user_id)
        if order is None or order.status not in USER_CANCELLABLE:
            raise InvalidTransition(order.status if order else "?", OrderStatus.CANCELLED)
        was_paid = order.is_paid
        order = await self.change_status(order_id, OrderStatus.CANCELLED, changed_by=user_id)
        if was_paid:
            await self.notifier.refund_needed(order)
        return order

    async def cancel_stale_unpaid(self, hours: int) -> int:
        deadline = utcnow() - timedelta(hours=hours)
        stmt = select(Order.id).where(
            Order.status == OrderStatus.NEW,
            Order.payment_method == PaymentMethod.CARD,
            Order.is_paid.is_(False),
            Order.created_at < deadline,
        )
        ids = list((await self.session.scalars(stmt)).all())
        for order_id in ids:
            await self.change_status(order_id, OrderStatus.CANCELLED, comment="auto: не оплачен")
        return len(ids)

    # ---------- Повтор ----------
    async def repeat(self, user_id: int, order_id: int) -> tuple[int, list[str]]:
        order = await self.get(order_id, user_id)
        if order is None:
            raise OrderError("not found")
        cart = CartService(self.session)
        added, missing = 0, []
        for item in order.items:
            if item.variant_id is None:
                missing.append(item.title)
                continue
            try:
                await cart.add(user_id, item.variant_id, item.qty)
                added += 1
            except NotEnoughStock as exc:
                if exc.available > 0:
                    await cart.add(user_id, item.variant_id, exc.available)
                    added += 1
                else:
                    missing.append(f"{item.title} ({item.size})")
            except VariantUnavailable:
                missing.append(f"{item.title} ({item.size})")
        return added, missing

    # ---------- Рефералы ----------
    async def _reward_referrer(self, order: Order) -> None:
        if order.status not in SUCCESSFUL_STATUSES:
            return
        user = await self.session.get(User, order.user_id)
        if user is None or user.referrer_id is None or user.referral_rewarded:
            return
        referrer = await self.session.get(User, user.referrer_id)
        user.referral_rewarded = True
        if referrer is not None:
            referrer.bonus_balance += self.referral_bonus
        await self.session.commit()
        if referrer is not None:
            await self.notifier.referral_rewarded(referrer.id, self.referral_bonus)
