"""Фабрики callback-data. Префиксы короткие: лимит Telegram — 64 байта."""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData


class MenuCB(CallbackData, prefix="m"):
    a: str  # main, catalog, search, cart, orders, fav, stylist, foryou, ref, help, admin


class CatCB(CallbackData, prefix="c"):
    a: str  # cats, list, flt, fk, fv, reset, sort, sv
    cat: int = 0
    page: int = 0
    k: str = ""
    v: str = ""


class ProdCB(CallbackData, prefix="p"):
    a: str  # view, color, var, add, fav, sim, bw, chart, back, noop
    pid: int
    c: int = -1  # индекс выбранного цвета
    vid: int = 0  # выбранный вариант


class CartCB(CallbackData, prefix="k"):
    a: str  # show, inc, dec, del, clear, promo, unpromo, checkout, noop
    item: int = 0


class CheckoutCB(CallbackData, prefix="o"):
    a: str  # agree, decline, method, bonus_on, bonus_off, confirm, edit, pay
    v: str = ""


class OrderCB(CallbackData, prefix="u"):
    a: str  # list, view, repeat, cancel, cancel_yes, pay, track
    oid: int = 0


class HelpCB(CallbackData, prefix="h"):
    a: str  # menu, delivery, returns, sizes, payment, manager


class StylistCB(CallbackData, prefix="s"):
    a: str  # start, look_cart, other, reset, pair, pair_pick, capsule
    id: int = 0


class AdminCB(CallbackData, prefix="a"):
    s: str  # раздел: menu, prod, cat, promo, zone, order, stats, bc, sty
    a: str = ""
    id: int = 0
    v: str = ""
    page: int = 0
