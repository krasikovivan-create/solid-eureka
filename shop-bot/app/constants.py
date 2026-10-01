"""Справочники предметной области."""

from __future__ import annotations

from enum import StrEnum


class OrderStatus(StrEnum):
    NEW = "new"
    PAID = "paid"
    ASSEMBLING = "assembling"
    SHIPPED = "shipped"
    IN_TRANSIT = "in_transit"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    RETURNED = "returned"


# Допустимые переходы статусов. Всё, что не перечислено, запрещено.
ORDER_TRANSITIONS: dict[OrderStatus, frozenset[OrderStatus]] = {
    OrderStatus.NEW: frozenset({OrderStatus.PAID, OrderStatus.ASSEMBLING, OrderStatus.CANCELLED}),
    OrderStatus.PAID: frozenset({OrderStatus.ASSEMBLING, OrderStatus.CANCELLED}),
    OrderStatus.ASSEMBLING: frozenset({OrderStatus.SHIPPED, OrderStatus.CANCELLED}),
    OrderStatus.SHIPPED: frozenset(
        {OrderStatus.IN_TRANSIT, OrderStatus.DELIVERED, OrderStatus.RETURNED}
    ),
    OrderStatus.IN_TRANSIT: frozenset({OrderStatus.DELIVERED, OrderStatus.RETURNED}),
    OrderStatus.DELIVERED: frozenset({OrderStatus.RETURNED}),
    OrderStatus.CANCELLED: frozenset(),
    OrderStatus.RETURNED: frozenset(),
}

# Статусы, при которых заказ считается «состоявшимся» для статистики и рекомендаций.
SUCCESSFUL_STATUSES: frozenset[OrderStatus] = frozenset(
    {
        OrderStatus.PAID,
        OrderStatus.ASSEMBLING,
        OrderStatus.SHIPPED,
        OrderStatus.IN_TRANSIT,
        OrderStatus.DELIVERED,
    }
)
# Покупатель может сам отменить заказ только до начала сборки.
USER_CANCELLABLE: frozenset[OrderStatus] = frozenset({OrderStatus.NEW, OrderStatus.PAID})


class DeliveryMethod(StrEnum):
    COURIER = "courier"
    CDEK = "cdek"
    POST = "post"
    PICKUP = "pickup"


class PaymentMethod(StrEnum):
    CARD = "card"
    COD = "cod"


class Gender(StrEnum):
    MALE = "male"
    FEMALE = "female"
    UNISEX = "unisex"


class Style(StrEnum):
    CASUAL = "casual"
    STREET = "street"
    SPORT = "sport"
    CLASSIC = "classic"


class PromoKind(StrEnum):
    PERCENT = "percent"
    FIXED = "fixed"


class Segment(StrEnum):
    ALL = "all"
    BUYERS = "buyers"
    ABANDONED = "abandoned"
    CATEGORY = "category"


class UserEvent(StrEnum):
    START = "start"
    CART_ADD = "cart_add"
    CHECKOUT_START = "checkout_start"
    ORDER_CREATED = "order_created"
    ORDER_PAID = "order_paid"


SIZE_ORDER = [
    "XS",
    "S",
    "M",
    "L",
    "XL",
    "XXL",
    "36",
    "37",
    "38",
    "39",
    "40",
    "41",
    "42",
    "43",
    "44",
    "45",
    "ONE",
]

PRICE_RANGES: dict[str, tuple[int | None, int | None]] = {
    "p1": (None, 2000),
    "p2": (2000, 5000),
    "p3": (5000, 10000),
    "p4": (10000, None),
}


def size_sort_key(size: str) -> tuple[int, str]:
    try:
        return SIZE_ORDER.index(size.upper()), size
    except ValueError:
        return len(SIZE_ORDER), size
