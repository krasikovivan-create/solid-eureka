import pytest

from app.constants import DeliveryMethod
from app.services.delivery import DeliveryCalculator, NoTariff, normalize_city


def test_normalize_city():
    assert normalize_city("  г. Москва ") == "москва"
    assert normalize_city("Город  Королёв") == "королев"


async def test_city_zone_tariff(session, catalog, providers):
    calc = DeliveryCalculator(session, providers)
    quote = await calc.quote("Москва", DeliveryMethod.COURIER, 3000)
    assert (quote.price, quote.days_min, quote.days_max) == (390, 1, 2)


async def test_free_delivery_threshold(session, catalog, providers):
    calc = DeliveryCalculator(session, providers)
    assert (await calc.quote("москва", DeliveryMethod.COURIER, 5000)).price == 0
    assert (await calc.quote("москва", DeliveryMethod.COURIER, 4999)).price == 390


async def test_default_zone_for_unknown_city(session, catalog, providers):
    calc = DeliveryCalculator(session, providers)
    quote = await calc.quote("Казань", DeliveryMethod.CDEK, 1000)
    assert quote.price == 490
    assert quote.days_max == 7


async def test_unavailable_method(session, catalog, providers):
    calc = DeliveryCalculator(session, providers)
    with pytest.raises(NoTariff):
        await calc.quote("Казань", DeliveryMethod.COURIER, 1000)


async def test_available_methods(session, catalog, providers):
    calc = DeliveryCalculator(session, providers)
    assert await calc.available_methods("Зеленоград") == [
        DeliveryMethod.COURIER,
        DeliveryMethod.CDEK,
        DeliveryMethod.PICKUP,
    ]
    assert await calc.available_methods("Омск") == [DeliveryMethod.CDEK, DeliveryMethod.POST]


async def test_inactive_tariff_is_skipped(session, catalog, providers):
    calc = DeliveryCalculator(session, providers)
    zone = await calc.zone_for_city("Москва")
    for tariff in zone.tariffs:
        if tariff.method == DeliveryMethod.COURIER:
            tariff.is_active = False
    with pytest.raises(NoTariff):
        await calc.quote("Москва", DeliveryMethod.COURIER, 1000)


async def test_mock_providers_issue_tracks(providers):
    class FakeOrder:
        id = 42

    cdek = await providers[DeliveryMethod.CDEK].create_shipment(FakeOrder())
    post = await providers[DeliveryMethod.POST].create_shipment(FakeOrder())
    assert cdek.startswith("10") and len(cdek) == 10
    assert len(post) == 14 and post.isdigit()
    assert await providers[DeliveryMethod.PICKUP].create_shipment(FakeOrder()) is None
