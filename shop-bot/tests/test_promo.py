from datetime import timedelta

import pytest

from app.constants import PromoKind
from app.db.base import utcnow
from app.services.cart import CartService
from app.services.promo import PromoError, PromoService, calc_discount


async def test_percent_discount(session, user, catalog):
    promo = await PromoService(session).create("sale10", PromoKind.PERCENT, 10)
    assert promo.code == "SALE10"
    assert calc_discount(promo, 3990) == 399


async def test_fixed_discount_never_zeroes_order(session):
    promo = await PromoService(session).create("FIX", PromoKind.FIXED, 5000)
    assert calc_discount(promo, 1990) == 1989
    assert calc_discount(promo, 9000) == 5000


async def test_apply_to_cart(session, user, catalog):
    await PromoService(session).create("WELCOME", PromoKind.PERCENT, 15)
    cart = CartService(session)
    await cart.add(user.id, catalog["tee_m_black"].id, 2)
    summary = await cart.apply_promo(user, " welcome ")
    assert summary.discount == 3980 * 15 // 100
    assert user.cart_promo_code == "WELCOME"
    again = await cart.summary(user)
    assert again.discount == summary.discount
    assert again.total == 3980 - summary.discount


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"valid_to": utcnow() - timedelta(days=1)}, "expired"),
        ({"valid_from": utcnow() + timedelta(days=1)}, "not_started"),
        ({"max_uses": 0}, "exhausted"),
        ({"min_total": 100000}, "min_total"),
    ],
)
async def test_validation_errors(session, user, kwargs, reason):
    await PromoService(session).create("CODE", PromoKind.PERCENT, 10, **kwargs)
    with pytest.raises(PromoError) as exc:
        await PromoService(session).validate("code", user.id, 5000)
    assert exc.value.key == reason
    assert exc.value.message


async def test_unknown_and_inactive(session, user):
    service = PromoService(session)
    with pytest.raises(PromoError, match="not_found"):
        await service.validate("NOPE", user.id, 1000)
    promo = await service.create("OFF", PromoKind.FIXED, 100)
    promo.is_active = False
    with pytest.raises(PromoError, match="inactive"):
        await service.validate("OFF", user.id, 1000)


async def test_per_user_limit_and_release(session, user):
    service = PromoService(session)
    promo = await service.create("ONCE", PromoKind.FIXED, 100, max_uses=10)
    await service.register_usage(promo, user.id, order_id=None)
    await session.flush()
    with pytest.raises(PromoError, match="user_limit"):
        await service.validate("ONCE", user.id, 1000)
    assert promo.used_count == 1


async def test_invalid_promo_in_cart_is_reported(session, user, catalog):
    service = PromoService(session)
    promo = await service.create("TEMP", PromoKind.PERCENT, 20)
    cart = CartService(session)
    await cart.add(user.id, catalog["tee_m_black"].id)
    await cart.apply_promo(user, "TEMP")
    promo.is_active = False
    summary = await cart.summary(user)
    assert summary.discount == 0
    assert summary.promo_error is not None
    assert summary.promo_error.key == "inactive"
