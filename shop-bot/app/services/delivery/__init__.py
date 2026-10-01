"""Расчёт доставки по зонам/городам и реестр служб доставки."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.constants import DeliveryMethod
from app.db.models import DeliveryTariff, DeliveryZone
from app.services.delivery.base import DeliveryProvider, DeliveryQuote, TrackingInfo
from app.services.delivery.providers import (
    CdekMockProvider,
    CourierProvider,
    PickupProvider,
    RussianPostMockProvider,
)

__all__ = [
    "DeliveryCalculator",
    "DeliveryProvider",
    "DeliveryQuote",
    "NoTariff",
    "TrackingInfo",
    "build_providers",
    "normalize_city",
]


class NoTariff(Exception):
    """Для города нет активного тарифа выбранным способом."""


def normalize_city(city: str) -> str:
    city = " ".join(city.strip().lower().replace("ё", "е").split())
    for prefix in ("г. ", "г ", "город "):
        if city.startswith(prefix):
            city = city.removeprefix(prefix)
    return city


def build_providers(autoadvance: bool = False) -> dict[str, DeliveryProvider]:
    return {
        DeliveryMethod.COURIER: CourierProvider(),
        DeliveryMethod.CDEK: CdekMockProvider(autoadvance=autoadvance),
        DeliveryMethod.POST: RussianPostMockProvider(autoadvance=autoadvance),
        DeliveryMethod.PICKUP: PickupProvider(),
    }


class DeliveryCalculator:
    def __init__(self, session: AsyncSession, providers: dict[str, DeliveryProvider]) -> None:
        self.session = session
        self.providers = providers

    async def zones(self) -> list[DeliveryZone]:
        stmt = (
            select(DeliveryZone)
            .options(selectinload(DeliveryZone.tariffs))
            .order_by(DeliveryZone.is_default, DeliveryZone.id)
        )
        return list((await self.session.scalars(stmt)).all())

    async def zone_for_city(self, city: str) -> DeliveryZone | None:
        target = normalize_city(city)
        default: DeliveryZone | None = None
        for zone in await self.zones():
            if target and target in {normalize_city(c) for c in zone.city_list}:
                return zone
            if zone.is_default and default is None:
                default = zone
        return default

    async def tariff(self, city: str, method: str) -> DeliveryTariff:
        zone = await self.zone_for_city(city)
        if zone is not None:
            for tariff in zone.tariffs:
                if tariff.method == method and tariff.is_active:
                    return tariff
        raise NoTariff(method)

    async def available_methods(self, city: str | None = None) -> list[str]:
        """Способы доставки: для города — доступные в его зоне, без города — хоть где-то."""
        if city is not None:
            zone = await self.zone_for_city(city)
            zones = [zone] if zone else []
        else:
            zones = await self.zones()
        methods = {t.method for z in zones for t in z.tariffs if t.is_active}
        return [m for m in DeliveryMethod if m in methods and m in self.providers]

    async def quote(self, city: str, method: str, items_total: int) -> DeliveryQuote:
        tariff = await self.tariff(city, method)
        return await self.providers[method].quote(tariff, city, items_total)
