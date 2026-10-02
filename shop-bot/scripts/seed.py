"""Демо-данные: 6 категорий, 25 товаров, зоны и тарифы доставки, промокоды.

Запуск:  python -m scripts.seed           — заполнить пустую базу
         python -m scripts.seed --reset   — удалить каталог/тарифы/промокоды и заполнить заново
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.constants import DeliveryMethod as DM
from app.db.base import utcnow
from app.db.models import (
    CartItem,
    Category,
    DeliveryTariff,
    DeliveryZone,
    Product,
    ProductPhoto,
    ProductVariant,
    PromoCode,
)
from app.db.session import create_engine, create_sessionmaker

CATEGORIES = [
    ("tshirts", "Футболки", "👕"),
    ("hoodies", "Худи", "🧥"),
    ("pants", "Штаны", "👖"),
    ("jackets", "Куртки", "🧥"),
    ("shoes", "Обувь", "👟"),
    ("accessories", "Аксессуары", "🧢"),
]

CLOTHES = ["XS", "S", "M", "L", "XL"]
MEN = ["S", "M", "L", "XL", "XXL"]
SHOES = ["38", "39", "40", "41", "42", "43", "44"]
WOMEN_SHOES = ["36", "37", "38", "39", "40"]

COLOR_HEX = {
    "чёрный": ("1f1f1f", "ffffff"),
    "белый": ("f2f2f2", "222222"),
    "серый": ("9e9e9e", "ffffff"),
    "бежевый": ("d8c3a5", "333333"),
    "синий": ("1e3a8a", "ffffff"),
    "голубой": ("7fb3d5", "1a1a1a"),
    "хаки": ("6b705c", "ffffff"),
    "бордовый": ("6d1a36", "ffffff"),
    "розовый": ("f4c2c2", "333333"),
    "коричневый": ("6f4e37", "ffffff"),
    "зелёный": ("2e7d32", "ffffff"),
}

# slug, title, en-label, gender, style, price, old_price, composition, colors, sizes, description
PRODUCTS = [
    (
        "tshirts",
        "Футболка оверсайз базовая",
        "Oversize Tee",
        "unisex",
        "casual",
        1990,
        2490,
        "100% хлопок, плотность 220 г/м²",
        ["чёрный", "белый", "серый"],
        CLOTHES,
        "Плотная футболка свободного кроя со спущенным плечом. Не просвечивает, держит форму после "
        "стирок. База, которая подходит к джинсам, карго и костюмным брюкам.",
    ),
    (
        "tshirts",
        "Футболка с принтом «Город»",
        "City Print Tee",
        "unisex",
        "street",
        2490,
        None,
        "100% хлопок",
        ["белый", "чёрный"],
        CLOTHES,
        "Футболка прямого кроя с графичным принтом на груди. Принт нанесён методом DTF — не "
        "трескается и не выцветает.",
    ),
    (
        "tshirts",
        "Лонгслив в рубчик",
        "Ribbed Longsleeve",
        "female",
        "casual",
        2290,
        None,
        "95% хлопок, 5% эластан",
        ["бежевый", "чёрный", "белый"],
        ["XS", "S", "M", "L"],
        "Облегающий лонгслив из мягкого трикотажа в рубчик. Хорош сам по себе и как слой под "
        "пиджак или рубашку.",
    ),
    (
        "tshirts",
        "Поло классическое",
        "Classic Polo",
        "male",
        "classic",
        3490,
        None,
        "100% хлопок пике",
        ["синий", "белый", "бордовый"],
        MEN,
        "Поло из фактурного пике с трикотажным воротником. Уместно и в офисе в пятницу, и на "
        "летней прогулке.",
    ),
    (
        "tshirts",
        "Спортивная футболка Dry-Fit",
        "Dry-Fit Tee",
        "male",
        "sport",
        1790,
        2290,
        "100% полиэстер, влагоотводящий",
        ["чёрный", "синий"],
        MEN,
        "Лёгкая футболка для тренировок: быстро сохнет, отводит влагу, плоские швы не натирают.",
    ),
    (
        "hoodies",
        "Худи оверсайз на флисе",
        "Fleece Hoodie",
        "unisex",
        "street",
        4990,
        5990,
        "80% хлопок, 20% полиэстер, начёс",
        ["чёрный", "серый", "бежевый"],
        CLOTHES,
        "Тёплое худи свободного силуэта с двойным капюшоном и карманом-кенгуру. Внутри мягкий "
        "начёс — комфортно до +5 °C под курткой.",
    ),
    (
        "hoodies",
        "Худи на молнии",
        "Zip Hoodie",
        "male",
        "sport",
        5490,
        None,
        "70% хлопок, 30% полиэстер",
        ["серый", "синий"],
        MEN,
        "Спортивное худи на металлической молнии с карманами. Удобно надевать поверх футболки "
        "на тренировку и после неё.",
    ),
    (
        "hoodies",
        "Свитшот базовый",
        "Basic Sweatshirt",
        "unisex",
        "casual",
        3990,
        None,
        "100% хлопок, футер трёхнитка",
        ["серый", "чёрный", "зелёный"],
        CLOTHES,
        "Классический свитшот с круглой горловиной и манжетами в рубчик. Сочетается со всем — "
        "от джинсов до юбки.",
    ),
    (
        "hoodies",
        "Укороченное худи",
        "Cropped Hoodie",
        "female",
        "street",
        4590,
        None,
        "80% хлопок, 20% полиэстер",
        ["розовый", "чёрный", "серый"],
        ["XS", "S", "M", "L"],
        "Худи укороченной длины с объёмными рукавами. Отлично смотрится с джинсами mom и "
        "карго с высокой посадкой.",
    ),
    (
        "pants",
        "Джинсы прямые",
        "Straight Jeans",
        "male",
        "casual",
        5990,
        None,
        "99% хлопок, 1% эластан, деним 13 oz",
        ["синий", "чёрный"],
        ["S", "M", "L", "XL"],
        "Прямые джинсы средней посадки из плотного денима. Немного тянутся, не теряют форму.",
    ),
    (
        "pants",
        "Джинсы mom",
        "Mom Jeans",
        "female",
        "casual",
        5490,
        6990,
        "100% хлопок",
        ["голубой", "синий"],
        ["XS", "S", "M", "L"],
        "Джинсы с высокой посадкой и зауженным к низу силуэтом. Подчёркивают талию, удлиняют ноги.",
    ),
    (
        "pants",
        "Брюки классические",
        "Classic Trousers",
        "male",
        "classic",
        6490,
        None,
        "65% полиэстер, 33% вискоза, 2% эластан",
        ["чёрный", "серый"],
        MEN,
        "Костюмные брюки прямого кроя со стрелками. Не мнутся в течение дня, подходят к "
        "пиджаку и к поло.",
    ),
    (
        "pants",
        "Брюки карго",
        "Cargo Pants",
        "unisex",
        "street",
        5290,
        None,
        "100% хлопок, твил",
        ["хаки", "чёрный", "бежевый"],
        CLOTHES,
        "Свободные брюки с объёмными карманами и регулировкой по низу. Главный низ для "
        "стритвир-образов.",
    ),
    (
        "pants",
        "Джоггеры спортивные",
        "Joggers",
        "unisex",
        "sport",
        3990,
        None,
        "80% хлопок, 20% полиэстер",
        ["серый", "чёрный"],
        CLOTHES,
        "Мягкие джоггеры с манжетами и шнурком на поясе. Для спорта, дома и дороги.",
    ),
    (
        "jackets",
        "Куртка-бомбер",
        "Bomber Jacket",
        "unisex",
        "street",
        8990,
        10990,
        "100% нейлон, утеплитель 80 г/м²",
        ["чёрный", "хаки"],
        CLOTHES,
        "Бомбер с трикотажными манжетами и лёгким утеплителем. Межсезонье: от +15 до +3 °C.",
    ),
    (
        "jackets",
        "Пуховик укороченный",
        "Short Puffer",
        "female",
        "casual",
        14990,
        None,
        "Верх: полиэстер; наполнитель: 80% пух, 20% перо",
        ["чёрный", "бежевый"],
        ["XS", "S", "M", "L"],
        "Тёплый укороченный пуховик с высоким воротником. Держит до −25 °C, "
        "весит меньше килограмма.",
    ),
    (
        "jackets",
        "Ветровка",
        "Windbreaker",
        "unisex",
        "sport",
        6990,
        None,
        "100% полиэстер, мембрана 5000 мм",
        ["синий", "чёрный"],
        CLOTHES,
        "Лёгкая ветровка с капюшоном, защищает от ветра и мелкого дождя. Складывается в карман.",
    ),
    (
        "jackets",
        "Тренч классический",
        "Trench Coat",
        "female",
        "classic",
        12990,
        None,
        "65% хлопок, 35% полиэстер",
        ["бежевый"],
        ["XS", "S", "M", "L"],
        "Двубортный тренч с поясом и погонами — вещь, которая не выходит из моды.",
    ),
    (
        "shoes",
        "Кеды белые кожаные",
        "White Sneakers",
        "unisex",
        "casual",
        5990,
        None,
        "Верх: натуральная кожа; подошва: резина",
        ["белый"],
        ["36", "37", *SHOES],
        "Минималистичные кожаные кеды. Подходят к джинсам, брюкам, платьям и спортивным костюмам.",
    ),
    (
        "shoes",
        "Кроссовки беговые",
        "Running Shoes",
        "male",
        "sport",
        8990,
        9990,
        "Верх: текстиль; подошва: ЭВА",
        ["чёрный", "серый"],
        SHOES,
        "Лёгкие кроссовки с амортизирующей подошвой для бега и зала.",
    ),
    (
        "shoes",
        "Ботинки челси",
        "Chelsea Boots",
        "unisex",
        "classic",
        10990,
        None,
        "Натуральная кожа, подошва TPR",
        ["чёрный", "коричневый"],
        ["37", *SHOES],
        "Кожаные челси с эластичными вставками. Подходят к классике и к джинсам.",
    ),
    (
        "shoes",
        "Лоферы",
        "Loafers",
        "female",
        "classic",
        7990,
        None,
        "Натуральная кожа",
        ["чёрный", "бордовый"],
        WOMEN_SHOES,
        "Классические лоферы на низком каблуке: офис, учёба, прогулки.",
    ),
    (
        "accessories",
        "Кепка бейсболка",
        "Baseball Cap",
        "unisex",
        "street",
        1490,
        None,
        "100% хлопок",
        ["чёрный", "бежевый", "синий"],
        ["ONE"],
        "Бейсболка с изогнутым козырьком и регулируемым ремешком.",
    ),
    (
        "accessories",
        "Шапка бини",
        "Beanie",
        "unisex",
        "casual",
        1290,
        1690,
        "50% шерсть, 50% акрил",
        ["чёрный", "серый", "бордовый"],
        ["ONE"],
        "Тёплая шапка двойной вязки с отворотом.",
    ),
    (
        "accessories",
        "Рюкзак городской",
        "City Backpack",
        "unisex",
        "casual",
        4490,
        None,
        "Полиэстер 600D, водоотталкивающая пропитка",
        ["чёрный", "серый"],
        ["ONE"],
        'Рюкзак на 20 л с отделением для ноутбука 15" и потайным карманом на спинке.',
    ),
]

ZONES = [
    (
        "Москва и область",
        "москва, зеленоград, химки, мытищи, красногорск, балашиха, одинцово, "
        "люберцы, королев, подольск",
        False,
        [
            (DM.COURIER, 390, 5000, 1, 2),
            (DM.CDEK, 290, 7000, 1, 3),
            (DM.POST, 300, None, 2, 5),
            (DM.PICKUP, 0, None, 1, 1),
        ],
    ),
    (
        "Санкт-Петербург",
        "санкт-петербург, спб, питер, пушкин, колпино, петергоф",
        False,
        [
            (DM.COURIER, 450, 6000, 1, 2),
            (DM.CDEK, 350, 7000, 2, 4),
            (DM.POST, 350, None, 3, 7),
        ],
    ),
    (
        "Остальная Россия",
        "",
        True,
        [
            (DM.CDEK, 490, 10000, 3, 8),
            (DM.POST, 390, None, 5, 14),
        ],
    ),
]


def product_colors(colors: list[str]) -> list[str]:
    """Цвета, для которых есть картинки в assets/products (не больше трёх)."""
    return colors[:3]


def asset_photo(index: int, color_index: int) -> str:
    return f"asset:products/{index:02d}-{color_index}.png"


def stock_for(index: int, color_index: int, size_index: int) -> int:
    """Детерминированные «живые» остатки: иногда 0, иногда мало, чаще 3–12."""
    value = (index * 7 + color_index * 5 + size_index * 3) % 13
    return 0 if value == 0 else (1 if value == 1 else value)


async def seed(session: AsyncSession, reset: bool = False) -> bool:
    if reset:
        for model in (
            CartItem,
            ProductVariant,
            ProductPhoto,
            Product,
            Category,
            DeliveryTariff,
            DeliveryZone,
            PromoCode,
        ):
            await session.execute(delete(model))
        await session.commit()
    if await session.scalar(select(func.count(Category.id))):
        return False

    categories = {}
    for sort, (slug, title, emoji) in enumerate(CATEGORIES, start=1):
        categories[slug] = Category(slug=slug, title=title, emoji=emoji, sort=sort)
        session.add(categories[slug])
    await session.flush()

    now = utcnow()
    for index, row in enumerate(PRODUCTS):
        slug, title, _en, gender, style, price, old, composition, colors, sizes, description = row
        category = categories[slug]
        product = Product(
            category_id=category.id,
            title=title,
            description=description,
            composition=composition,
            gender=gender,
            style=style,
            price=price,
            old_price=old,
            created_at=now - timedelta(days=len(PRODUCTS) - index),
            is_demo=True,
        )
        product.photos = [
            ProductPhoto(url=asset_photo(index, n), sort=n)
            for n in range(len(product_colors(colors)))
        ]
        product.variants = [
            ProductVariant(size=size, color=color, stock=stock_for(index, ci, si))
            for ci, color in enumerate(colors)
            for si, size in enumerate(sizes)
        ]
        product.rebuild_search_text(category.title)
        session.add(product)

    for name, cities, is_default, tariffs in ZONES:
        zone = DeliveryZone(name=name, cities=cities, is_default=is_default)
        zone.tariffs = [
            DeliveryTariff(method=m, price=p, free_from=f, days_min=dmin, days_max=dmax)
            for m, p, f, dmin, dmax in tariffs
        ]
        session.add(zone)

    session.add_all(
        [
            PromoCode(code="WELCOME10", kind="percent", value=10, per_user_limit=1),
            PromoCode(
                code="SALE500",
                kind="fixed",
                value=500,
                min_total=4000,
                max_uses=100,
                valid_to=now + timedelta(days=90),
            ),
        ]
    )
    await session.commit()
    return True


async def main(reset: bool) -> None:
    settings = get_settings()
    engine = create_engine(settings.database_url)
    async with create_sessionmaker(engine)() as session:
        created = await seed(session, reset=reset)
    await engine.dispose()
    if created:
        print(
            f"Готово: {len(CATEGORIES)} категорий, {len(PRODUCTS)} товаров, "
            f"{len(ZONES)} зоны доставки, 2 промокода (WELCOME10, SALE500)."
        )
    else:
        print("Каталог уже заполнен — пропускаю. Для перезаливки: python -m scripts.seed --reset")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true", help="очистить каталог перед заливкой")
    asyncio.run(main(parser.parse_args().reset))
