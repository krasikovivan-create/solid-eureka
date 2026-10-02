"""Генератор картинок демо-каталога: assets/products/*.png и assets/banner.png.

Картинки лежат в репозитории, поэтому бот показывает фото товаров сразу после запуска
и не зависит от внешних сервисов с заглушками. Перегенерировать (нужен Pillow):

    pip install pillow
    python -m scripts.make_assets
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from scripts.seed import COLOR_HEX, PRODUCTS, product_colors

ASSETS = Path(__file__).resolve().parents[1] / "assets"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REGULAR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
W, H = 800, 1000
BACKGROUND = (244, 241, 236)


def _rgb(hex_color: str) -> tuple[int, int, int]:
    return tuple(int(hex_color[i : i + 2], 16) for i in (0, 2, 4))


def _shade(rgb: tuple[int, int, int], k: float) -> tuple[int, int, int]:
    return tuple(max(0, min(255, int(c * k))) for c in rgb)


def _outline(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    return _shade(rgb, 0.6) if sum(rgb) > 200 else (90, 90, 90)


# Силуэты — многоугольники в координатах 0..1 внутри области рисунка.
SHAPES: dict[str, list[list[tuple[float, float]]]] = {
    "tshirts": [
        [
            (0.30, 0.12),
            (0.42, 0.08),
            (0.50, 0.14),
            (0.58, 0.08),
            (0.70, 0.12),
            (0.92, 0.28),
            (0.82, 0.40),
            (0.72, 0.33),
            (0.72, 0.92),
            (0.28, 0.92),
            (0.28, 0.33),
            (0.18, 0.40),
            (0.08, 0.28),
        ],
    ],
    "hoodies": [
        [
            (0.32, 0.16),
            (0.40, 0.04),
            (0.60, 0.04),
            (0.68, 0.16),
            (0.88, 0.30),
            (0.94, 0.86),
            (0.80, 0.86),
            (0.74, 0.40),
            (0.74, 0.94),
            (0.26, 0.94),
            (0.26, 0.40),
            (0.20, 0.86),
            (0.06, 0.86),
            (0.12, 0.30),
        ],
    ],
    "pants": [
        [
            (0.26, 0.06),
            (0.74, 0.06),
            (0.80, 0.94),
            (0.58, 0.94),
            (0.50, 0.34),
            (0.42, 0.94),
            (0.20, 0.94),
        ],
    ],
    "jackets": [
        [
            (0.34, 0.10),
            (0.50, 0.18),
            (0.66, 0.10),
            (0.90, 0.26),
            (0.96, 0.88),
            (0.80, 0.88),
            (0.76, 0.42),
            (0.76, 0.94),
            (0.24, 0.94),
            (0.24, 0.42),
            (0.20, 0.88),
            (0.04, 0.88),
            (0.10, 0.26),
        ],
    ],
    "shoes": [
        [
            (0.06, 0.52),
            (0.30, 0.48),
            (0.46, 0.30),
            (0.62, 0.30),
            (0.70, 0.50),
            (0.94, 0.62),
            (0.96, 0.78),
            (0.06, 0.78),
        ],
    ],
    "accessories": [
        [
            (0.18, 0.62),
            (0.22, 0.38),
            (0.36, 0.24),
            (0.64, 0.24),
            (0.78, 0.38),
            (0.82, 0.62),
            (0.96, 0.70),
            (0.04, 0.70),
        ],
    ],
}


def draw_product(path: Path, category: str, title: str, color: str) -> None:
    fill = _rgb(COLOR_HEX.get(color, ("cccccc", "333333"))[0])
    image = Image.new("RGB", (W, H), BACKGROUND)
    draw = ImageDraw.Draw(image)
    left, top, size = 120, 90, 560
    draw.ellipse((90, 120, 710, 740), fill=(234, 229, 221))
    for polygon in SHAPES[category]:
        points = [(left + x * size, top + y * size) for x, y in polygon]
        shadow = [(px + 10, py + 12) for px, py in points]
        draw.polygon(shadow, fill=(214, 208, 198))
        draw.polygon(points, fill=fill, outline=_outline(fill), width=6)

    title_font = ImageFont.truetype(FONT_BOLD, 40)
    small_font = ImageFont.truetype(FONT_REGULAR, 30)
    lines, line = [], ""
    for word in title.split():
        candidate = f"{line} {word}".strip()
        if draw.textlength(candidate, font=title_font) > W - 120:
            lines.append(line)
            line = word
        else:
            line = candidate
    lines.append(line)
    y = 760
    for text in lines[:2]:
        x = (W - draw.textlength(text, font=title_font)) / 2
        draw.text((x, y), text, (40, 40, 40), title_font)
        y += 52
    caption = f"цвет: {color}"
    draw.text(
        ((W - draw.textlength(caption, font=small_font)) / 2, y + 10),
        caption,
        (110, 110, 110),
        small_font,
    )
    image.save(path, optimize=True)


def draw_banner(path: Path) -> None:
    image = Image.new("RGB", (1280, 640), (32, 32, 36))
    draw = ImageDraw.Draw(image)
    palette = ["1f1f1f", "d8c3a5", "1e3a8a", "6d1a36", "9e9e9e", "6b705c"]
    for i, hex_color in enumerate(palette):
        x, y = 900 + (i % 3) * 120, 150 + (i // 3) * 180
        draw.rounded_rectangle(
            (x, y, x + 100, y + 150),
            radius=20,
            fill=_rgb(hex_color),
            outline=(230, 230, 230),
            width=3,
        )
    big = ImageFont.truetype(FONT_BOLD, 68)
    mid = ImageFont.truetype(FONT_REGULAR, 30)
    draw.text((80, 200), "Новая коллекция", (250, 250, 250), big)
    draw.text((80, 300), "Одежда и обувь с доставкой по России", (200, 200, 200), mid)
    draw.text((80, 350), "Каталог · ИИ-стилист · оплата в Telegram", (160, 160, 160), mid)
    image.save(path, optimize=True)


def main() -> None:
    products_dir = ASSETS / "products"
    products_dir.mkdir(parents=True, exist_ok=True)
    for index, row in enumerate(PRODUCTS):
        category, title, colors = row[0], row[1], row[8]
        for color_index, color in enumerate(product_colors(colors)):
            draw_product(products_dir / f"{index:02d}-{color_index}.png", category, title, color)
    draw_banner(ASSETS / "banner.png")
    print(f"Готово: {ASSETS}")


if __name__ == "__main__":
    main()
