import pytest

from app.constants import DeliveryMethod, OrderStatus, PaymentMethod, PromoKind
from app.db.models import ProductVariant, PromoCode, User
from app.services.cart import CartService
from app.services.orders import (
    CartChanged,
    CheckoutData,
    InvalidTransition,
    OrderService,
    max_bonus,
)
from app.services.promo import PromoService


def make_service(session, notifier, providers):
    return OrderService(session, notifier, providers, referral_bonus=300, bonus_share_percent=30)


def checkout(method=DeliveryMethod.COURIER, city="Москва", use_bonus=False):
    return CheckoutData(
        name="Иван",
        phone="+79123456789",
        city=city,
        address="ул. Ленина, д. 5, кв. 1",
        method=method,
        use_bonus=use_bonus,
    )


async def stock_of(session, variant_id):
    variant = await session.get(ProductVariant, variant_id, populate_existing=True)
    return variant.stock


async def test_cod_order_reserves_stock_and_clears_cart(
    session, user, catalog, notifier, providers
):
    cart = CartService(session)
    await cart.add(user.id, catalog["tee_m_black"].id, 2)
    service = make_service(session, notifier, providers)

    order = await service.create_from_cart(user, checkout(), PaymentMethod.COD)

    assert order.status == OrderStatus.NEW
    assert order.items_total == 3980
    assert order.delivery_price == 390
    assert order.total == 3980 + 390
    assert order.stock_deducted
    assert await stock_of(session, catalog["tee_m_black"].id) == 3
    assert await cart.count(user.id) == 0
    assert "new_order" in notifier.names()


async def test_card_order_deducts_only_after_payment(session, user, catalog, notifier, providers):
    await CartService(session).add(user.id, catalog["hoodie_l"].id)
    service = make_service(session, notifier, providers)
    order = await service.create_from_cart(user, checkout(), PaymentMethod.CARD)

    assert not order.stock_deducted
    assert await stock_of(session, catalog["hoodie_l"].id) == 1
    assert order.delivery_price == 0  # бесплатно от 5000

    assert await service.validate_for_payment(order.id, user.id, order.total)
    assert not await service.validate_for_payment(order.id, user.id, order.total + 1)
    assert not await service.validate_for_payment(order.id, 999, order.total)

    paid = await service.mark_paid(order.id, "tg-charge", "provider-charge")
    assert paid.is_paid
    assert paid.status == OrderStatus.PAID
    assert await stock_of(session, catalog["hoodie_l"].id) == 0
    assert ("status", OrderStatus.PAID) in notifier.calls
    # Повторный вебхук об оплате не списывает остатки второй раз.
    await service.mark_paid(order.id, "tg-charge", "provider-charge")
    assert await stock_of(session, catalog["hoodie_l"].id) == 0


async def test_cancel_returns_stock_promo_and_bonus(session, user, catalog, notifier, providers):
    user.bonus_balance = 500
    await PromoService(session).create("TEN", PromoKind.PERCENT, 10)
    cart = CartService(session)
    await cart.add(user.id, catalog["tee_m_black"].id, 2)
    await cart.apply_promo(user, "TEN")
    service = make_service(session, notifier, providers)
    order = await service.create_from_cart(user, checkout(use_bonus=True), PaymentMethod.COD)

    assert order.discount == 398
    assert order.bonus_used == max_bonus(500, 3980, 398, 30)
    assert order.total == 3980 - 398 - order.bonus_used + 390
    assert await stock_of(session, catalog["tee_m_black"].id) == 3

    await service.change_status(order.id, OrderStatus.CANCELLED, changed_by=1)

    assert await stock_of(session, catalog["tee_m_black"].id) == 5
    promo = await session.get(PromoCode, order.promo_id, populate_existing=True)
    assert promo.used_count == 0
    refreshed = await session.get(User, user.id, populate_existing=True)
    assert refreshed.bonus_balance == 500


async def test_full_status_flow(session, user, catalog, notifier, providers):
    await CartService(session).add(user.id, catalog["tee_s_black"].id)
    service = make_service(session, notifier, providers)
    order = await service.create_from_cart(user, checkout(DeliveryMethod.CDEK), PaymentMethod.COD)

    for status in (
        OrderStatus.ASSEMBLING,
        OrderStatus.SHIPPED,
        OrderStatus.IN_TRANSIT,
        OrderStatus.DELIVERED,
    ):
        order = await service.change_status(order.id, status, changed_by=1)
        assert order.status == status

    assert order.track_number  # СДЭК выдал трек при передаче в доставку
    assert order.is_paid  # наложенный платёж оплачен при вручении
    assert [h.to_status for h in order.history] == [
        "new",
        "assembling",
        "shipped",
        "in_transit",
        "delivered",
    ]
    assert notifier.names().count("status") == 4


@pytest.mark.parametrize(
    ("path", "target"),
    [
        ([], OrderStatus.DELIVERED),
        ([OrderStatus.CANCELLED], OrderStatus.PAID),
        ([OrderStatus.ASSEMBLING, OrderStatus.SHIPPED], OrderStatus.CANCELLED),
    ],
)
async def test_invalid_transitions(session, user, catalog, notifier, providers, path, target):
    await CartService(session).add(user.id, catalog["tee_s_black"].id)
    service = make_service(session, notifier, providers)
    order = await service.create_from_cart(user, checkout(), PaymentMethod.COD)
    for status in path:
        await service.change_status(order.id, status)
    with pytest.raises(InvalidTransition):
        await service.change_status(order.id, target)


async def test_unpaid_card_order_cannot_be_assembled(session, user, catalog, notifier, providers):
    await CartService(session).add(user.id, catalog["tee_s_black"].id)
    service = make_service(session, notifier, providers)
    order = await service.create_from_cart(user, checkout(), PaymentMethod.CARD)
    with pytest.raises(InvalidTransition):
        await service.change_status(order.id, OrderStatus.ASSEMBLING)


async def test_return_after_delivery_restores_stock(session, user, catalog, notifier, providers):
    await CartService(session).add(user.id, catalog["tee_s_black"].id, 2)
    service = make_service(session, notifier, providers)
    order = await service.create_from_cart(user, checkout(), PaymentMethod.COD)
    for status in (OrderStatus.ASSEMBLING, OrderStatus.SHIPPED, OrderStatus.DELIVERED):
        await service.change_status(order.id, status)
    assert await stock_of(session, catalog["tee_s_black"].id) == 1
    await service.change_status(order.id, OrderStatus.RETURNED)
    assert await stock_of(session, catalog["tee_s_black"].id) == 3


async def test_cart_changed_when_stock_is_gone(session, user, catalog, notifier, providers):
    await CartService(session).add(user.id, catalog["tee_s_black"].id, 3)
    catalog["tee_s_black"].stock = 1
    await session.commit()
    service = make_service(session, notifier, providers)
    with pytest.raises(CartChanged):
        await service.create_from_cart(user, checkout(), PaymentMethod.COD)


async def test_user_cancel_paid_order_requests_refund(session, user, catalog, notifier, providers):
    await CartService(session).add(user.id, catalog["tee_s_black"].id)
    service = make_service(session, notifier, providers)
    order = await service.create_from_cart(user, checkout(), PaymentMethod.CARD)
    await service.mark_paid(order.id, "c1", "p1")
    await service.cancel_by_user(user.id, order.id)
    assert "refund" in notifier.names()
    assert await stock_of(session, catalog["tee_s_black"].id) == 3


async def test_referral_bonus_after_first_paid_order(session, user, catalog, notifier, providers):
    friend = User(id=2002, full_name="Друг")
    session.add(friend)
    await session.flush()
    user.referrer_id = friend.id
    await session.commit()
    await CartService(session).add(user.id, catalog["tee_s_black"].id)
    service = make_service(session, notifier, providers)
    order = await service.create_from_cart(user, checkout(), PaymentMethod.CARD)
    await service.mark_paid(order.id)
    friend = await session.get(User, 2002, populate_existing=True)
    assert friend.bonus_balance == 300
    assert ("referral", 2002) in notifier.calls

    # Второй заказ бонус не начисляет.
    await CartService(session).add(user.id, catalog["tee_s_black"].id)
    order2 = await service.create_from_cart(user, checkout(), PaymentMethod.CARD)
    await service.mark_paid(order2.id)
    friend = await session.get(User, 2002, populate_existing=True)
    assert friend.bonus_balance == 300


async def test_repeat_order(session, user, catalog, notifier, providers):
    cart = CartService(session)
    await cart.add(user.id, catalog["tee_s_black"].id, 1)
    await cart.add(user.id, catalog["hoodie_l"].id, 1)
    service = make_service(session, notifier, providers)
    order = await service.create_from_cart(user, checkout(), PaymentMethod.COD)
    added, missing = await service.repeat(user.id, order.id)
    assert added == 1  # худи закончилось после первого заказа
    assert missing and "Худи" in missing[0]
