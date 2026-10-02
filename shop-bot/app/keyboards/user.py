"""Клавиатуры покупателя."""

from __future__ import annotations

from collections.abc import Sequence

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.constants import PRICE_RANGES, Gender, size_sort_key
from app.db.models import Category, Order, Product
from app.keyboards.callbacks import (
    CartCB,
    CatCB,
    CheckoutCB,
    HelpCB,
    MenuCB,
    OrderCB,
    ProdCB,
    StylistCB,
)
from app.services.cart import CartSummary
from app.texts import labels, t
from app.utils.formatting import delivery_label, money, payment_label, status_label

SORTS = ("new", "cheap", "expensive", "discount")


def btn(text: str, callback_data) -> InlineKeyboardButton:
    data = callback_data if isinstance(callback_data, str) else callback_data.pack()
    return InlineKeyboardButton(text=text, callback_data=data)


def menu_row() -> list[InlineKeyboardButton]:
    return [btn(t("common.menu"), MenuCB(a="main"))]


def main_menu(cart_count: int, show_stylist: bool, is_admin: bool) -> InlineKeyboardMarkup:
    cart_label = t("menu.cart_count", count=cart_count) if cart_count else t("menu.cart")
    rows = [
        [btn(t("menu.catalog"), MenuCB(a="catalog")), btn(t("menu.search"), MenuCB(a="search"))],
        [btn(cart_label, MenuCB(a="cart")), btn(t("menu.orders"), MenuCB(a="orders"))],
    ]
    if show_stylist:
        rows.append([btn(t("menu.stylist"), MenuCB(a="stylist"))])
    rows += [
        [btn(t("menu.favorites"), MenuCB(a="fav")), btn(t("menu.for_you"), MenuCB(a="foryou"))],
        [btn(t("menu.referral"), MenuCB(a="ref")), btn(t("menu.help"), MenuCB(a="help"))],
    ]
    if is_admin:
        rows.append([btn(t("menu.admin"), MenuCB(a="admin"))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------- Каталог ----------
def categories_kb(categories: Sequence[Category]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for cat in categories:
        kb.add(btn(cat.label, CatCB(a="list", cat=cat.id)))
    kb.adjust(2)
    kb.row(*menu_row())
    return kb.as_markup()


def product_button(product: Product, callback) -> InlineKeyboardButton:
    key = "catalog.product_btn_sale" if product.discount_percent else "catalog.product_btn"
    return btn(t(key, title=product.title, price=money(product.price)), callback)


def product_list_kb(
    products: Sequence[Product], cat: int, page: int, pages: int, sort: str
) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for product in products:
        kb.row(product_button(product, ProdCB(a="view", pid=product.id)))
    if pages > 1:
        nav = []
        if page > 0:
            nav.append(btn(t("common.prev"), CatCB(a="list", cat=cat, page=page - 1)))
        nav.append(btn(t("common.page", page=page + 1, pages=pages), CartCB(a="noop")))
        if page < pages - 1:
            nav.append(btn(t("common.next"), CatCB(a="list", cat=cat, page=page + 1)))
        kb.row(*nav)
    kb.row(
        btn(t("catalog.btn_filters"), CatCB(a="flt", cat=cat)),
        btn(t("catalog.btn_sort", sort=t(f"sort.{sort}")), CatCB(a="sort", cat=cat)),
    )
    kb.row(btn(t("catalog.btn_categories"), CatCB(a="cats")), *menu_row())
    return kb.as_markup()


def filters_kb(cat: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                btn(t("catalog.btn_size"), CatCB(a="fk", cat=cat, k="size")),
                btn(t("catalog.btn_color"), CatCB(a="fk", cat=cat, k="color")),
            ],
            [
                btn(t("catalog.btn_price"), CatCB(a="fk", cat=cat, k="price")),
                btn(t("catalog.btn_gender"), CatCB(a="fk", cat=cat, k="gender")),
            ],
            [
                btn(t("catalog.btn_reset"), CatCB(a="reset", cat=cat)),
                btn(t("catalog.btn_show"), CatCB(a="list", cat=cat)),
            ],
        ]
    )


def filter_values_kb(cat: int, key: str, values: Sequence[str]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if key == "price":
        options = [(code, t(f"price.{code}")) for code in PRICE_RANGES]
    elif key == "gender":
        options = [(g.value, labels("gender")[g.value]) for g in Gender]
    else:
        options = [(v, v) for v in values]
    for value, label in options:
        kb.add(btn(label, CatCB(a="fv", cat=cat, k=key, v=value[:24])))
    kb.add(btn(t("catalog.any"), CatCB(a="fv", cat=cat, k=key, v="")))
    kb.adjust(3)
    kb.row(btn(t("common.back"), CatCB(a="flt", cat=cat)))
    return kb.as_markup()


def sort_kb(cat: int, current: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for sort in SORTS:
        mark = "✅ " if sort == current else ""
        kb.row(btn(mark + t(f"sort.{sort}"), CatCB(a="sv", cat=cat, v=sort)))
    kb.row(btn(t("common.back"), CatCB(a="list", cat=cat)))
    return kb.as_markup()


def products_kb(products: Sequence[Product], back) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for product in products:
        kb.row(product_button(product, ProdCB(a="view", pid=product.id)))
    kb.row(btn(t("common.back"), back) if back else menu_row()[0])
    if back:
        kb.row(*menu_row())
    return kb.as_markup()


def product_card_kb(
    product: Product, color_idx: int, variant_id: int, is_favorite: bool
) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    colors = product.colors
    if len(colors) == 1:
        color_idx = 0
    if len(colors) > 1:
        color_buttons = [
            btn(
                ("✅ " if i == color_idx else "") + color,
                ProdCB(a="color", pid=product.id, c=i),
            )
            for i, color in enumerate(colors)
        ]
        kb.row(*color_buttons[:3])
        if len(color_buttons) > 3:
            kb.row(*color_buttons[3:6])
    if 0 <= color_idx < len(colors):
        variants = sorted(
            (v for v in product.variants if v.color == colors[color_idx]),
            key=lambda v: size_sort_key(v.size),
        )
        size_buttons = []
        for v in variants:
            if v.stock > 0:
                label = ("✅ " if v.id == variant_id else "") + t(
                    "product.size_btn", size=v.size, stock=v.stock
                )
                size_buttons.append(
                    btn(label, ProdCB(a="var", pid=product.id, c=color_idx, vid=v.id))
                )
            else:
                size_buttons.append(
                    btn(t("product.size_btn_none", size=v.size), ProdCB(a="noop", pid=product.id))
                )
        for i in range(0, len(size_buttons), 4):
            kb.row(*size_buttons[i : i + 4])
    fav_key = "product.btn_fav_remove" if is_favorite else "product.btn_fav_add"
    kb.row(
        btn(t("product.btn_to_cart"), ProdCB(a="add", pid=product.id, c=color_idx, vid=variant_id)),
        btn(t(fav_key), ProdCB(a="fav", pid=product.id, c=color_idx, vid=variant_id)),
    )
    kb.row(btn(t("product.btn_size_chart"), ProdCB(a="chart", pid=product.id)))
    kb.row(
        btn(t("product.btn_similar"), ProdCB(a="sim", pid=product.id)),
        btn(t("product.btn_bought_with"), ProdCB(a="bw", pid=product.id)),
    )
    kb.row(btn(t("product.btn_back"), ProdCB(a="back", pid=product.id)), *menu_row())
    return kb.as_markup()


# ---------- Корзина ----------
def cart_kb(summary: CartSummary) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for n, line in enumerate(summary.lines, start=1):
        kb.row(
            btn(f"{n}. ➖", CartCB(a="dec", item=line.item_id)),
            btn(str(line.qty), CartCB(a="noop")),
            btn("➕", CartCB(a="inc", item=line.item_id)),
            btn("🗑", CartCB(a="del", item=line.item_id)),
        )
    if summary.promo_code:
        kb.row(btn(t("cart.btn_remove_promo"), CartCB(a="unpromo")))
    else:
        kb.row(btn(t("cart.btn_promo"), CartCB(a="promo")))
    kb.row(btn(t("cart.btn_clear"), CartCB(a="clear")))
    kb.row(btn(t("cart.btn_checkout"), CartCB(a="checkout")))
    kb.row(*menu_row())
    return kb.as_markup()


def empty_cart_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[btn(t("menu.catalog"), MenuCB(a="catalog"))], menu_row()]
    )


def cancel_kb(back=None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[btn(t("common.cancel"), back or MenuCB(a="main"))]]
    )


# ---------- Оформление ----------
def consent_kb(with_policy: bool = True) -> InlineKeyboardMarkup:
    rows = [
        [btn(t("checkout.btn_agree"), CheckoutCB(a="agree"))],
        [btn(t("checkout.btn_decline"), CheckoutCB(a="decline"))],
    ]
    if with_policy:
        rows.insert(0, [btn(t("checkout.btn_policy"), CheckoutCB(a="policy"))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def name_kb(suggested: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=suggested[:64])], [KeyboardButton(text=t("common.cancel"))]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def phone_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=t("checkout.btn_contact"), request_contact=True)],
            [KeyboardButton(text=t("common.cancel"))],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def city_kb(last_city: str | None) -> ReplyKeyboardMarkup:
    rows = []
    if last_city:
        rows.append([KeyboardButton(text=last_city)])
    rows.append([KeyboardButton(text="Москва"), KeyboardButton(text="Санкт-Петербург")])
    rows.append([KeyboardButton(text=t("common.cancel"))])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, one_time_keyboard=True)


def methods_kb(methods: Sequence[str]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for method in methods:
        kb.row(btn(delivery_label(method), CheckoutCB(a="method", v=method)))
    kb.row(btn(t("common.cancel"), CheckoutCB(a="cancel")))
    return kb.as_markup()


def confirm_kb(bonus_available: int, bonus_on: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(btn(t("checkout.btn_confirm"), CheckoutCB(a="confirm")))
    if bonus_available and not bonus_on:
        kb.row(
            btn(
                t("checkout.btn_use_bonus", amount=money(bonus_available)),
                CheckoutCB(a="bonus_on"),
            )
        )
    elif bonus_on:
        kb.row(btn(t("checkout.btn_drop_bonus"), CheckoutCB(a="bonus_off")))
    kb.row(btn(t("checkout.btn_edit"), CheckoutCB(a="edit")))
    kb.row(btn(t("common.cancel"), CheckoutCB(a="cancel")))
    return kb.as_markup()


def payment_kb(card_enabled: bool, cod_enabled: bool, test_mode: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if card_enabled:
        label = t("checkout.btn_pay_test") if test_mode else payment_label("card")
        kb.row(btn(label, CheckoutCB(a="pay", v="card")))
    if cod_enabled:
        kb.row(btn(payment_label("cod"), CheckoutCB(a="pay", v="cod")))
    kb.row(btn(t("common.cancel"), CheckoutCB(a="cancel")))
    return kb.as_markup()


def test_pay_kb(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[btn(t("checkout.btn_pay_test"), OrderCB(a="pay", oid=order_id))]]
    )


# ---------- Заказы ----------
def orders_kb(orders: Sequence[Order]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for order in orders:
        kb.row(
            btn(
                t(
                    "orders.btn",
                    id=order.id,
                    status=status_label(order.status),
                    total=money(order.total),
                ),
                OrderCB(a="view", oid=order.id),
            )
        )
    kb.row(*menu_row())
    return kb.as_markup()


def order_kb(
    order: Order, can_cancel: bool, can_pay: bool, can_track: bool
) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if can_pay:
        kb.row(btn(t("orders.btn_pay"), OrderCB(a="pay", oid=order.id)))
    if can_track:
        kb.row(btn(t("orders.btn_track"), OrderCB(a="track", oid=order.id)))
    kb.row(btn(t("orders.btn_repeat"), OrderCB(a="repeat", oid=order.id)))
    if can_cancel:
        kb.row(btn(t("orders.btn_cancel"), OrderCB(a="cancel", oid=order.id)))
    kb.row(btn(t("common.back"), OrderCB(a="list")), *menu_row())
    return kb.as_markup()


def order_cancel_confirm_kb(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                btn(t("common.yes"), OrderCB(a="cancel_yes", oid=order_id)),
                btn(t("common.no"), OrderCB(a="view", oid=order_id)),
            ]
        ]
    )


# ---------- Помощь ----------
def help_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [btn(t("help.btn_delivery"), HelpCB(a="delivery"))],
            [btn(t("help.btn_returns"), HelpCB(a="returns"))],
            [btn(t("help.btn_sizes"), HelpCB(a="sizes"))],
            [btn(t("help.btn_payment"), HelpCB(a="payment"))],
            [btn(t("help.btn_manager"), HelpCB(a="manager"))],
            menu_row(),
        ]
    )


def help_back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[btn(t("common.back"), HelpCB(a="menu"))], menu_row()]
    )


def open_product_kb(product_id: int, label: str | None = None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[btn(label or t("fav.open"), ProdCB(a="view", pid=product_id))]]
    )


def open_cart_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[btn(t("cart.reminder_btn"), MenuCB(a="cart"))]])


# ---------- Стилист ----------
def stylist_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                btn(t("stylist.btn_pair"), StylistCB(a="pair")),
                btn(t("stylist.btn_capsule"), StylistCB(a="capsule")),
            ],
            [btn(t("stylist.btn_reset"), StylistCB(a="reset"))],
            menu_row(),
        ]
    )


def stylist_fallback_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[btn(t("stylist.btn_catalog"), MenuCB(a="catalog"))], menu_row()]
    )


def stylist_look_kb(
    look_id: int, items: Sequence[dict], with_menu: bool = False
) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(btn(t("stylist.btn_look_to_cart"), StylistCB(a="look_cart", id=look_id)))
    for item in items:
        kb.row(btn(f"👕 {item['title']}"[:60], ProdCB(a="view", pid=item["product_id"])))
    kb.row(btn(t("stylist.btn_other"), StylistCB(a="other")))
    if with_menu:
        kb.row(btn(t("stylist.btn_reset"), StylistCB(a="reset")), *menu_row())
    return kb.as_markup()


def stylist_pair_kb(products: Sequence[Product]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for product in products:
        kb.row(btn(product.title[:60], StylistCB(a="pair_pick", id=product.id)))
    kb.row(btn(t("common.back"), StylistCB(a="start")))
    return kb.as_markup()
