from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import Select, and_, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.constants import PRICE_RANGES, Gender, size_sort_key
from app.db.models import Category, Product, ProductPhoto, ProductVariant, ProductView


@dataclass(slots=True)
class ProductFilter:
    category_id: int | None = None
    size: str | None = None
    color: str | None = None
    price_key: str | None = None
    min_price: int | None = None
    max_price: int | None = None
    gender: str | None = None
    style: str | None = None
    query: str | None = None
    sort: str = "new"
    in_stock_only: bool = True
    exclude_ids: Sequence[int] = ()


class CatalogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ---------- Категории ----------
    async def categories(self, only_active: bool = True) -> list[Category]:
        stmt = select(Category).order_by(Category.sort, Category.id)
        if only_active:
            stmt = stmt.where(Category.is_active.is_(True))
        return list((await self.session.scalars(stmt)).all())

    async def get_category(self, category_id: int) -> Category | None:
        return await self.session.get(Category, category_id)

    async def category_product_count(self, category_id: int) -> int:
        stmt = select(func.count(Product.id)).where(Product.category_id == category_id)
        return int(await self.session.scalar(stmt) or 0)

    # ---------- Товары ----------
    @staticmethod
    def _variant_exists(**conditions: object):
        clauses = [ProductVariant.product_id == Product.id, ProductVariant.stock > 0]
        if conditions.get("size"):
            clauses.append(ProductVariant.size == conditions["size"])
        if conditions.get("color"):
            clauses.append(ProductVariant.color == conditions["color"])
        return select(ProductVariant.id).where(and_(*clauses)).exists()

    def _filtered(self, flt: ProductFilter) -> Select:
        stmt = select(Product).where(Product.is_active.is_(True))
        if flt.category_id:
            stmt = stmt.where(Product.category_id == flt.category_id)
        if flt.gender and flt.gender != Gender.UNISEX:
            stmt = stmt.where(Product.gender.in_([flt.gender, Gender.UNISEX]))
        elif flt.gender == Gender.UNISEX:
            stmt = stmt.where(Product.gender == Gender.UNISEX)
        if flt.style:
            stmt = stmt.where(Product.style == flt.style)
        low, high = PRICE_RANGES.get(flt.price_key or "", (None, None))
        low = flt.min_price if flt.min_price is not None else low
        high = flt.max_price if flt.max_price is not None else high
        if low is not None:
            stmt = stmt.where(Product.price >= low)
        if high is not None:
            stmt = stmt.where(Product.price <= high)
        if flt.size or flt.color or flt.in_stock_only:
            stmt = stmt.where(self._variant_exists(size=flt.size, color=flt.color))
        if flt.query:
            for word in flt.query.lower().split():
                stmt = stmt.where(Product.search_text.contains(word, autoescape=True))
        if flt.exclude_ids:
            stmt = stmt.where(Product.id.not_in(list(flt.exclude_ids)))
        if flt.sort == "discount":
            stmt = stmt.where(Product.old_price.is_not(None), Product.old_price > Product.price)
        return stmt

    @staticmethod
    def _ordered(stmt: Select, sort: str) -> Select:
        if sort == "cheap":
            return stmt.order_by(Product.price.asc(), Product.id)
        if sort == "expensive":
            return stmt.order_by(Product.price.desc(), Product.id)
        if sort == "discount":
            return stmt.order_by(
                ((Product.old_price - Product.price) * 1.0 / Product.old_price).desc(), Product.id
            )
        return stmt.order_by(Product.created_at.desc(), Product.id.desc())

    async def count_products(self, flt: ProductFilter) -> int:
        sub = self._filtered(flt).with_only_columns(Product.id).subquery()
        return int(await self.session.scalar(select(func.count()).select_from(sub)) or 0)

    async def list_products(
        self, flt: ProductFilter, offset: int = 0, limit: int = 6
    ) -> list[Product]:
        stmt = self._ordered(self._filtered(flt), flt.sort).offset(offset).limit(limit)
        stmt = stmt.options(selectinload(Product.variants), selectinload(Product.category))
        return list((await self.session.scalars(stmt)).all())

    async def get_product(self, product_id: int, with_inactive: bool = False) -> Product | None:
        stmt = (
            select(Product)
            .where(Product.id == product_id)
            .options(
                selectinload(Product.photos),
                selectinload(Product.variants),
                selectinload(Product.category),
            )
        )
        if not with_inactive:
            stmt = stmt.where(Product.is_active.is_(True))
        return await self.session.scalar(stmt)

    async def get_products(self, ids: Sequence[int]) -> list[Product]:
        if not ids:
            return []
        stmt = (
            select(Product)
            .where(Product.id.in_(list(ids)))
            .options(selectinload(Product.variants), selectinload(Product.category))
        )
        found = {p.id: p for p in (await self.session.scalars(stmt)).all()}
        return [found[i] for i in ids if i in found]

    async def get_variant(self, variant_id: int) -> ProductVariant | None:
        stmt = (
            select(ProductVariant)
            .where(ProductVariant.id == variant_id)
            .options(selectinload(ProductVariant.product))
        )
        return await self.session.scalar(stmt)

    async def available_sizes(self, category_id: int | None) -> list[str]:
        stmt = (
            select(ProductVariant.size)
            .join(Product)
            .where(Product.is_active.is_(True), ProductVariant.stock > 0)
            .distinct()
        )
        if category_id:
            stmt = stmt.where(Product.category_id == category_id)
        sizes = list((await self.session.scalars(stmt)).all())
        return sorted(sizes, key=size_sort_key)

    async def available_colors(self, category_id: int | None) -> list[str]:
        stmt = (
            select(ProductVariant.color)
            .join(Product)
            .where(Product.is_active.is_(True), ProductVariant.stock > 0)
            .distinct()
            .order_by(ProductVariant.color)
        )
        if category_id:
            stmt = stmt.where(Product.category_id == category_id)
        return list((await self.session.scalars(stmt)).all())

    async def save_photo_file_id(self, photo_id: int, file_id: str) -> None:
        photo = await self.session.get(ProductPhoto, photo_id)
        if photo and not photo.file_id:
            photo.file_id = file_id

    async def replace_photos(self, product: Product, file_ids: Sequence[str]) -> None:
        await self.session.execute(
            delete(ProductPhoto).where(ProductPhoto.product_id == product.id)
        )
        for i, file_id in enumerate(file_ids):
            self.session.add(ProductPhoto(product_id=product.id, file_id=file_id, sort=i))
        await self.session.flush()
        await self.session.refresh(product, ["photos"])

    async def add_view(self, user_id: int, product_id: int) -> None:
        self.session.add(ProductView(user_id=user_id, product_id=product_id))
