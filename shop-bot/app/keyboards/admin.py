"""Клавиатуры админ-панели."""

from __future__ import annotations

from collections.abc import Sequence

from aiogram.types import (
    InlineKeyboardMarkup,
    KeyboardButton,
    KeyboardButtonRequestUsers,
    ReplyKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.constants import ORDER_TRANSITIONS, DeliveryMethod, Gender, OrderStatus, Style
from app.db.models import Category, DeliveryZone, Order, Product, PromoCode
from app.keyboards.callbacks import AdminCB
from app.keyboards.user import btn, menu_row
from app.texts import labels, t
from app.utils.formatting import delivery_label, money, status_label


def admin_menu_kb() -> InlineKeyboardMarkup:
    rows = [
        [
            btn(t("adm.btn_products"), AdminCB(s="prod")),
            btn(t("adm.btn_categories"), AdminCB(s="cat")),
        ],
        [
            btn(t("adm.btn_orders"), AdminCB(s="order")),
            btn(t("adm.btn_promos"), AdminCB(s="promo")),
        ],
        [btn(t("adm.btn_tariffs"), AdminCB(s="zone")), btn(t("adm.btn_stats"), AdminCB(s="stats"))],
        [btn(t("adm.btn_broadcast"), AdminCB(s="bc")), btn(t("adm.btn_stylist"), AdminCB(s="sty"))],
        [btn(t("adm.btn_shop"), AdminCB(s="shop")), btn(t("adm.btn_team"), AdminCB(s="team"))],
        menu_row(),
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def back_kb(cb: AdminCB) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[btn(t("common.back"), cb)]])


def cancel_admin_kb(cb: AdminCB | None = None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[btn(t("common.cancel"), cb or AdminCB(s="menu"))]]
    )


def skip_kb(cb: AdminCB) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[btn(t("common.skip"), cb)], [btn(t("common.cancel"), AdminCB(s="menu"))]]
    )


# ---------- Товары ----------
def admin_categories_kb(categories: Sequence[Category], section: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for cat in categories:
        mark = "" if cat.is_active else " 🔴"
        kb.add(
            btn(
                cat.label + mark,
                AdminCB(s=section, a="list" if section == "prod" else "view", id=cat.id),
            )
        )
    kb.adjust(2)
    if section == "prod":
        kb.row(btn(t("adm.btn_add_product"), AdminCB(s="prod", a="new")))
    else:
        kb.row(btn(t("adm.btn_add_category"), AdminCB(s="cat", a="new")))
    kb.row(btn(t("common.back"), AdminCB(s="menu")))
    return kb.as_markup()


def admin_products_kb(
    products: Sequence[Product], cat_id: int, page: int, pages: int
) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for p in products:
        mark = "" if p.is_active else "🔴 "
        kb.row(
            btn(
                f"{mark}#{p.id} {p.title} — {money(p.price)}"[:64],
                AdminCB(s="prod", a="view", id=p.id),
            )
        )
    nav = []
    if page > 0:
        nav.append(btn(t("common.prev"), AdminCB(s="prod", a="list", id=cat_id, page=page - 1)))
    if page < pages - 1:
        nav.append(btn(t("common.next"), AdminCB(s="prod", a="list", id=cat_id, page=page + 1)))
    if nav:
        kb.row(*nav)
    kb.row(btn(t("adm.btn_add_product"), AdminCB(s="prod", a="new", id=cat_id)))
    kb.row(btn(t("common.back"), AdminCB(s="prod")))
    return kb.as_markup()


def admin_product_kb(product: Product) -> InlineKeyboardMarkup:
    pid = product.id
    rows = [
        [
            btn(t("adm.btn_edit_title"), AdminCB(s="prod", a="edit", id=pid, v="title")),
            btn(
                t("adm.btn_edit_description"), AdminCB(s="prod", a="edit", id=pid, v="description")
            ),
        ],
        [
            btn(
                t("adm.btn_edit_composition"), AdminCB(s="prod", a="edit", id=pid, v="composition")
            ),
            btn(t("adm.btn_edit_price"), AdminCB(s="prod", a="edit", id=pid, v="price")),
        ],
        [
            btn(t("adm.btn_edit_old_price"), AdminCB(s="prod", a="edit", id=pid, v="old_price")),
            btn(t("adm.btn_edit_photos"), AdminCB(s="prod", a="photos", id=pid)),
        ],
        [btn(t("adm.btn_edit_variants"), AdminCB(s="prod", a="variants", id=pid))],
        [
            btn(t("adm.btn_toggle"), AdminCB(s="prod", a="toggle", id=pid)),
            btn(t("adm.btn_delete"), AdminCB(s="prod", a="delete", id=pid)),
        ],
        [btn(t("common.back"), AdminCB(s="prod", a="list", id=product.category_id))],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_delete_kb(yes: AdminCB, no: AdminCB) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[btn(t("common.yes"), yes), btn(t("common.no"), no)]]
    )


def choose_category_kb(categories: Sequence[Category]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for cat in categories:
        kb.add(btn(cat.label, AdminCB(s="prod", a="newcat", id=cat.id)))
    kb.adjust(2)
    kb.row(btn(t("common.cancel"), AdminCB(s="prod")))
    return kb.as_markup()


def gender_kb() -> InlineKeyboardMarkup:
    gl = labels("gender")
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [btn(gl[g.value], AdminCB(s="prod", a="gender", v=g.value)) for g in Gender]
        ]
    )


def style_kb() -> InlineKeyboardMarkup:
    sl = labels("style")
    kb = InlineKeyboardBuilder()
    for s in Style:
        kb.add(btn(sl[s.value], AdminCB(s="prod", a="style", v=s.value)))
    kb.adjust(2)
    return kb.as_markup()


def photos_done_kb(cb: AdminCB) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[btn(t("common.done"), cb)], [btn(t("common.cancel"), AdminCB(s="prod"))]]
    )


def variants_kb(product: Product) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for v in product.variants:
        kb.add(btn(f"{v.size} · {v.color}: {v.stock}", AdminCB(s="prod", a="stock", id=v.id)))
    kb.adjust(2)
    kb.row(btn(t("adm.btn_add_variants"), AdminCB(s="prod", a="addvar", id=product.id)))
    kb.row(btn(t("common.back"), AdminCB(s="prod", a="view", id=product.id)))
    return kb.as_markup()


# ---------- Категории ----------
def category_kb(category: Category) -> InlineKeyboardMarkup:
    cid = category.id
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [btn(t("adm.btn_rename"), AdminCB(s="cat", a="rename", id=cid))],
            [
                btn(t("adm.btn_toggle"), AdminCB(s="cat", a="toggle", id=cid)),
                btn(t("adm.btn_delete"), AdminCB(s="cat", a="delete", id=cid)),
            ],
            [btn(t("common.back"), AdminCB(s="cat"))],
        ]
    )


# ---------- Промокоды ----------
def promos_kb(promos: Sequence[PromoCode]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for p in promos[:30]:
        mark = "🟢" if p.is_active else "🔴"
        kb.row(btn(f"{mark} {p.code}", AdminCB(s="promo", a="view", id=p.id)))
    kb.row(btn(t("adm.btn_add_promo"), AdminCB(s="promo", a="new")))
    kb.row(btn(t("common.back"), AdminCB(s="menu")))
    return kb.as_markup()


def promo_kb(promo: PromoCode) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                btn(t("adm.btn_toggle"), AdminCB(s="promo", a="toggle", id=promo.id)),
                btn(t("adm.btn_delete"), AdminCB(s="promo", a="delete", id=promo.id)),
            ],
            [btn(t("common.back"), AdminCB(s="promo"))],
        ]
    )


def promo_kind_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                btn(t("adm.promo_percent"), AdminCB(s="promo", a="kind", v="percent")),
                btn(t("adm.promo_fixed"), AdminCB(s="promo", a="kind", v="fixed")),
            ],
            [btn(t("common.cancel"), AdminCB(s="promo"))],
        ]
    )


# ---------- Доставка ----------
def zones_kb(zones: Sequence[DeliveryZone]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for z in zones:
        kb.row(btn(z.name + (" ⭐" if z.is_default else ""), AdminCB(s="zone", a="view", id=z.id)))
    kb.row(btn(t("adm.btn_add_zone"), AdminCB(s="zone", a="new")))
    kb.row(btn(t("common.back"), AdminCB(s="menu")))
    return kb.as_markup()


def zone_kb(zone: DeliveryZone) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for method in DeliveryMethod:
        kb.add(btn(delivery_label(method), AdminCB(s="zone", a="tariff", id=zone.id, v=method)))
    kb.adjust(2)
    kb.row(btn(t("adm.btn_edit_cities"), AdminCB(s="zone", a="cities", id=zone.id)))
    if not zone.is_default:
        kb.row(btn(t("adm.btn_delete"), AdminCB(s="zone", a="delete", id=zone.id)))
    kb.row(btn(t("common.back"), AdminCB(s="zone")))
    return kb.as_markup()


# ---------- Заказы ----------
def order_filter_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.add(btn(t("adm.orders_all"), AdminCB(s="order", a="list", v="")))
    for status in OrderStatus:
        kb.add(btn(status_label(status), AdminCB(s="order", a="list", v=status)))
    kb.adjust(3)
    kb.row(btn(t("common.back"), AdminCB(s="menu")))
    return kb.as_markup()


def admin_orders_kb(
    orders: Sequence[Order], status: str, page: int, pages: int
) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for o in orders:
        kb.row(
            btn(
                f"№{o.id} · {status_label(o.status)} · {money(o.total)}",
                AdminCB(s="order", a="view", id=o.id, v=status),
            )
        )
    nav = []
    if page > 0:
        nav.append(btn(t("common.prev"), AdminCB(s="order", a="list", v=status, page=page - 1)))
    if page < pages - 1:
        nav.append(btn(t("common.next"), AdminCB(s="order", a="list", v=status, page=page + 1)))
    if nav:
        kb.row(*nav)
    kb.row(btn(t("common.back"), AdminCB(s="order")))
    return kb.as_markup()


def admin_order_kb(order: Order, back_status: str, can_ship: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for target in ORDER_TRANSITIONS[OrderStatus(order.status)]:
        kb.add(btn("→ " + status_label(target), AdminCB(s="order", a="set", id=order.id, v=target)))
    kb.adjust(2)
    kb.row(btn(t("adm.btn_set_track"), AdminCB(s="order", a="track", id=order.id)))
    if can_ship and not order.track_number:
        kb.row(btn(t("adm.btn_create_shipment"), AdminCB(s="order", a="ship", id=order.id)))
    kb.row(btn(t("common.back"), AdminCB(s="order", a="list", v=back_status)))
    return kb.as_markup()


# ---------- Статистика и рассылки ----------
def stats_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                btn(t("adm.period_day"), AdminCB(s="stats", a="p", v="day")),
                btn(t("adm.period_week"), AdminCB(s="stats", a="p", v="week")),
                btn(t("adm.period_month"), AdminCB(s="stats", a="p", v="month")),
            ],
            [btn(t("common.back"), AdminCB(s="menu"))],
        ]
    )


def segment_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [btn(t("adm.bc_seg_all"), AdminCB(s="bc", a="seg", v="all"))],
            [btn(t("adm.bc_seg_buyers"), AdminCB(s="bc", a="seg", v="buyers"))],
            [btn(t("adm.bc_seg_abandoned"), AdminCB(s="bc", a="seg", v="abandoned"))],
            [btn(t("adm.bc_seg_category"), AdminCB(s="bc", a="seg", v="category"))],
            [btn(t("common.back"), AdminCB(s="menu"))],
        ]
    )


def bc_category_kb(categories: Sequence[Category]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for cat in categories:
        kb.add(btn(cat.label, AdminCB(s="bc", a="cat", id=cat.id)))
    kb.adjust(2)
    kb.row(btn(t("common.cancel"), AdminCB(s="menu")))
    return kb.as_markup()


def bc_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [btn(t("adm.btn_bc_send"), AdminCB(s="bc", a="send"))],
            [btn(t("adm.btn_bc_schedule"), AdminCB(s="bc", a="schedule"))],
            [btn(t("common.cancel"), AdminCB(s="menu"))],
        ]
    )


# ---------- Администраторы ----------
def team_kb(removable: Sequence[int]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for user_id in removable:
        kb.row(btn(f"🗑 {user_id}", AdminCB(s="team", a="del", id=user_id)))
    kb.row(btn(t("adm.btn_add_admin"), AdminCB(s="team", a="add")))
    kb.row(btn(t("common.back"), AdminCB(s="menu")))
    return kb.as_markup()


def pick_user_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(
                    text=t("adm.btn_pick_user"),
                    request_users=KeyboardButtonRequestUsers(
                        request_id=1, user_is_bot=False, max_quantity=1
                    ),
                )
            ],
            [KeyboardButton(text=t("common.cancel"))],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


# ---------- Настройки магазина ----------
def shop_kb(demo_count: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(
        btn(t("adm.btn_shop_name"), AdminCB(s="shop", a="edit", v="shop_name")),
        btn(t("adm.btn_shop_welcome"), AdminCB(s="shop", a="edit", v="welcome")),
    )
    kb.row(
        btn(t("adm.btn_shop_banner"), AdminCB(s="shop", a="banner")),
        btn(t("adm.btn_shop_pickup"), AdminCB(s="shop", a="edit", v="pickup_address")),
    )
    kb.row(
        btn(t("adm.btn_shop_operator"), AdminCB(s="shop", a="edit", v="operator")),
        btn(t("adm.btn_shop_policy"), AdminCB(s="shop", a="policy")),
    )
    if demo_count:
        kb.row(btn(t("adm.btn_delete_demo"), AdminCB(s="shop", a="demo")))
    kb.row(btn(t("common.back"), AdminCB(s="menu")))
    return kb.as_markup()
