import pytest

from app.services.validation import (
    normalize_phone,
    validate_address,
    validate_city,
    validate_name,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("+7 (912) 345-67-89", "+79123456789"),
        ("89123456789", "+79123456789"),
        ("79123456789", "+79123456789"),
        ("9123456789", "+79123456789"),
        ("+7 495 123 45 67", "+74951234567"),
        ("12345", None),
        ("+1 202 555 0143", None),
        ("+7 112 345 67 89", None),
        ("телефон 89123456789", None),
        ("", None),
    ],
)
def test_phone(raw, expected):
    assert normalize_phone(raw) == expected


@pytest.mark.parametrize(
    ("raw", "ok"),
    [
        ("ул. Ленина, д. 5, кв. 12", True),
        ("125009, Москва, Тверская 7", True),
        ("Ленина", False),
        ("12345678", False),
        ("ул. Пушкина <script>1</script>", False),
        ("https://evil.example 5 street", False),
    ],
)
def test_address(raw, ok):
    assert (validate_address(raw) is not None) is ok


def test_name_and_city():
    assert validate_name("  Иван   Петров ") == "Иван Петров"
    assert validate_name("1") is None
    assert validate_name("Анна-Мария") == "Анна-Мария"
    assert validate_city("Санкт-Петербург") == "Санкт-Петербург"
    assert validate_city("123") is None
