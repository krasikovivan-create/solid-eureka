"""Mock-реализации служб доставки. Генерируют правдоподобные трек-номера и
статусы, ничего не отправляя во внешние API."""

from __future__ import annotations

import hashlib
from datetime import timedelta

from app.constants import DeliveryMethod, OrderStatus
from app.db.base import utcnow
from app.db.models import Order
from app.services.delivery.base import DeliveryProvider, TrackingEvent, TrackingInfo


def _digits(seed: str, length: int) -> str:
    digest = hashlib.sha256(seed.encode()).hexdigest()
    return str(int(digest, 16))[:length].rjust(length, "0")


def _shipped_at(order: Order):
    for entry in reversed(order.history):
        if entry.to_status == OrderStatus.SHIPPED:
            return entry.created_at
    return None


class _MockTrackingMixin:
    autoadvance: bool = False

    def _mock_track(self, order: Order, carrier: str) -> TrackingInfo | None:
        if not order.track_number:
            return None
        shipped_at = _shipped_at(order) or order.updated_at
        events = [TrackingEvent(shipped_at, f"{carrier}: отправление принято")]
        info = TrackingInfo(track_number=order.track_number, events=events)
        if not self.autoadvance:
            return info
        elapsed = utcnow() - shipped_at
        if elapsed >= timedelta(hours=12):
            events.append(TrackingEvent(shipped_at + timedelta(hours=12), f"{carrier}: в пути"))
            info.order_status = OrderStatus.IN_TRANSIT
        if elapsed >= timedelta(days=order.delivery_days_max or 3):
            events.append(
                TrackingEvent(
                    shipped_at + timedelta(days=order.delivery_days_max or 3),
                    f"{carrier}: вручено получателю",
                )
            )
            info.order_status = OrderStatus.DELIVERED
        return info


class CdekMockProvider(_MockTrackingMixin, DeliveryProvider):
    method = DeliveryMethod.CDEK

    def __init__(self, autoadvance: bool = False) -> None:
        self.autoadvance = autoadvance

    async def create_shipment(self, order: Order) -> str:
        return "10" + _digits(f"cdek-{order.id}", 8)

    async def track(self, order: Order) -> TrackingInfo | None:
        return self._mock_track(order, "СДЭК")


class RussianPostMockProvider(_MockTrackingMixin, DeliveryProvider):
    method = DeliveryMethod.POST

    def __init__(self, autoadvance: bool = False) -> None:
        self.autoadvance = autoadvance

    async def create_shipment(self, order: Order) -> str:
        # Формат внутрироссийского ШПИ — 14 цифр.
        return "8" + _digits(f"post-{order.id}", 13)

    async def track(self, order: Order) -> TrackingInfo | None:
        return self._mock_track(order, "Почта России")


class CourierProvider(DeliveryProvider):
    method = DeliveryMethod.COURIER
    supports_tracking = False

    async def create_shipment(self, order: Order) -> None:
        return None

    async def track(self, order: Order) -> None:
        return None


class PickupProvider(DeliveryProvider):
    method = DeliveryMethod.PICKUP
    needs_address = False
    supports_tracking = False

    async def create_shipment(self, order: Order) -> None:
        return None

    async def track(self, order: Order) -> None:
        return None
