"""Валидация контактных данных покупателя."""

from __future__ import annotations

import re

_NAME_RE = re.compile(r"^[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё\s'\-.]{1,63}$")
_CITY_RE = re.compile(r"^[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё\s\-.()]{1,63}$")
_LETTERS_RE = re.compile(r"[A-Za-zА-Яа-яЁё]")
_DIGIT_RE = re.compile(r"\d")


def normalize_phone(raw: str) -> str | None:
    """Приводит российский номер к виду +7XXXXXXXXXX. None — номер некорректен.

    Принимает «8 912 345-67-89», «+7 (912) 345 67 89», «79123456789», «9123456789».
    """
    if not raw:
        return None
    cleaned = raw.strip()
    if re.search(r"[^\d\s()+\-.]", cleaned):
        return None
    digits = re.sub(r"\D", "", cleaned)
    if len(digits) == 10 and digits[0] == "9":
        digits = "7" + digits
    elif len(digits) == 11 and digits[0] == "8":
        digits = "7" + digits[1:]
    if len(digits) != 11 or digits[0] != "7" or digits[1] not in "3489":
        return None
    return "+" + digits


def validate_name(raw: str) -> str | None:
    name = " ".join(raw.split())
    if not _NAME_RE.match(name) or len(_LETTERS_RE.findall(name)) < 2:
        return None
    return name


def validate_city(raw: str) -> str | None:
    city = " ".join(raw.split())
    if not _CITY_RE.match(city):
        return None
    return city


def validate_address(raw: str) -> str | None:
    """Адрес: 8–300 символов, есть буквы (улица) и цифры (дом)."""
    address = " ".join(raw.split())
    if not 8 <= len(address) <= 300:
        return None
    if len(_LETTERS_RE.findall(address)) < 3 or not _DIGIT_RE.search(address):
        return None
    if re.search(r"(https?://|www\.|<|>)", address, re.IGNORECASE):
        return None
    return address
