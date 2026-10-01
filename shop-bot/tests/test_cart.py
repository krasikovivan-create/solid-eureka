import pytest

from app.services.cart import CartService, NotEnoughStock, VariantUnavailable


async def test_add_and_summary(session, user, catalog):
    cart = CartService(session)
    await cart.add(user.id, catalog["tee_m_black"].id, 2)
    await cart.add(user.id, catalog["hoodie_l"].id)
    summary = await cart.summary(user)
    assert len(summary.lines) == 2
    assert summary.items_total == 2 * 1990 + 5990
    assert summary.total == summary.items_total
    assert summary.count == 3
    assert not summary.has_problems


async def test_add_same_variant_accumulates(session, user, catalog):
    cart = CartService(session)
    await cart.add(user.id, catalog["tee_m_black"].id, 2)
    item = await cart.add(user.id, catalog["tee_m_black"].id, 3)
    assert item.qty == 5
    assert await cart.count(user.id) == 5


async def test_add_more_than_stock_fails(session, user, catalog):
    cart = CartService(session)
    await cart.add(user.id, catalog["tee_s_black"].id, 2)
    with pytest.raises(NotEnoughStock) as exc:
        await cart.add(user.id, catalog["tee_s_black"].id, 2)
    assert exc.value.available == 1


async def test_add_out_of_stock_variant(session, user, catalog):
    with pytest.raises(NotEnoughStock):
        await CartService(session).add(user.id, catalog["tee_m_white"].id)


async def test_add_inactive_product(session, user, catalog):
    catalog["hoodie"].is_active = False
    await session.flush()
    with pytest.raises(VariantUnavailable):
        await CartService(session).add(user.id, catalog["hoodie_l"].id)


async def test_change_qty_and_remove(session, user, catalog):
    cart = CartService(session)
    item = await cart.add(user.id, catalog["tee_s_black"].id, 1)
    assert await cart.change_qty(user.id, item.id, +2) == 3
    with pytest.raises(NotEnoughStock):
        await cart.change_qty(user.id, item.id, +1)
    assert await cart.change_qty(user.id, item.id, -1) == 2
    assert await cart.change_qty(user.id, item.id, -5) == 0
    assert (await cart.summary(user)).is_empty


async def test_other_user_cannot_touch_item(session, user, catalog):
    cart = CartService(session)
    item = await cart.add(user.id, catalog["tee_s_black"].id, 1)
    with pytest.raises(VariantUnavailable):
        await cart.change_qty(999, item.id, +1)


async def test_summary_marks_stock_problems(session, user, catalog):
    cart = CartService(session)
    await cart.add(user.id, catalog["tee_m_black"].id, 4)
    catalog["tee_m_black"].stock = 2
    await session.flush()
    summary = await cart.summary(user)
    assert summary.has_problems


async def test_clear(session, user, catalog):
    cart = CartService(session)
    await cart.add(user.id, catalog["tee_s_black"].id, 1)
    await cart.clear(user.id)
    assert await cart.count(user.id) == 0
