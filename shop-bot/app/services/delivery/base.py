"""Интерфейс службы доставки.

Чтобы подключить реальный API (например, СДЭК), напишите класс-наследник DeliveryProvider
и зарегистрируйте его в app/services/delivery/__init__.py вместо mock-реализации —
остальной код (оформление заказа, админка) менять не придётся.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime

from app.db.models import DeliveryTariff, Order


@dataclass(slots=True, frozen=True)
class DeliveryQuote:
    method: str
    price: int
    days_min: int
    days_max: int


@dataclass(slots=True)
class TrackingEvent:
    at: datetime
    description: str


@dataclass(slots=True)
class TrackingInfo:
    track_number: str
    # Статус заказа, который соответствует состоянию посылки (in_transit / delivered),
    # или None, если служба не сообщает ничего нового.
    order_status: str | None = None
    events: list[TrackingEvent] = field(default_factory=list)


class DeliveryProvider(ABC):
    method: str
    needs_address: bool = True
    supports_tracking: bool = True

    async def quote(self, tariff: DeliveryTariff, city: str, items_total: int) -> DeliveryQuote:
        """Стоимость и срок. По умолчанию — из тарифа зоны в БД; реальный провайдер
        может переопределить метод и спросить цену у API службы."""
        price = tariff.price
        if tariff.free_from is not None and items_total >= tariff.free_from:
            price = 0
        return DeliveryQuote(self.method, price, tariff.days_min, tariff.days_max)

    @abstractmethod
    async def create_shipment(self, order: Order) -> str | None:
        """Регистрирует отправление и возвращает трек-номер (None — трек не нужен)."""

    @abstractmethod
    async def track(self, order: Order) -> TrackingInfo | None:
        """Текущее состояние отправления."""
