"""Профиль компании, владелец и пользователи."""

from __future__ import annotations

from sqlalchemy import select

from app.database.models import CompanyProfile, User
from app.database.session import SessionFactory
from app.services.timeutils import is_valid_tz, parse_hhmm

EDITABLE_FIELDS = {
    "company_name",
    "company_description",
    "agent_name",
    "agent_role",
    "communication_style",
    "timezone",
    "morning_time",
    "evening_time",
    "morning_enabled",
    "evening_enabled",
    "hourly_rate",
}


async def get_profile(sf: SessionFactory, default_tz: str = "Europe/Moscow") -> CompanyProfile:
    async with sf() as s:
        profile = await s.get(CompanyProfile, 1)
        if profile is None:
            profile = CompanyProfile(id=1, timezone=default_tz)
            s.add(profile)
            await s.commit()
            await s.refresh(profile)
        return profile


async def update_profile(sf: SessionFactory, **fields: object) -> CompanyProfile:
    unknown = set(fields) - EDITABLE_FIELDS - {"onboarded", "owner_id", "onboarding_step"}
    if unknown:
        raise ValueError(f"Неизвестные поля: {', '.join(sorted(unknown))}")
    for key in ("morning_time", "evening_time"):
        if key in fields and fields[key] is not None:
            parsed = parse_hhmm(str(fields[key]))
            if not parsed:
                raise ValueError("Время укажите в формате ЧЧ:ММ, например 09:00")
            fields[key] = parsed
    if "timezone" in fields and not is_valid_tz(str(fields["timezone"])):
        raise ValueError("Неизвестный часовой пояс. Пример: Europe/Moscow, Asia/Yekaterinburg")
    if "hourly_rate" in fields:
        rate = int(fields["hourly_rate"])  # type: ignore[arg-type]
        if rate <= 0:
            raise ValueError("Ставка должна быть больше нуля")
        fields["hourly_rate"] = rate
    await get_profile(sf)
    async with sf() as s:
        profile = await s.get(CompanyProfile, 1)
        assert profile is not None
        for key, value in fields.items():
            if value is not None:
                setattr(profile, key, value)
        await s.commit()
        await s.refresh(profile)
        return profile


async def is_allowed(sf: SessionFactory, allowed_ids: list[int], user_id: int) -> bool:
    """Доступ: явный список ALLOWED_USER_IDS или владелец из БД."""
    if allowed_ids:
        return user_id in allowed_ids
    profile = await get_profile(sf)
    return profile.owner_id is not None and profile.owner_id == user_id


async def try_claim_owner(sf: SessionFactory, user_id: int) -> bool:
    """Если владельца ещё нет — делает пользователя владельцем. True при успехе."""
    await get_profile(sf)
    async with sf() as s:
        profile = await s.get(CompanyProfile, 1)
        assert profile is not None
        if profile.owner_id is None:
            profile.owner_id = user_id
            await s.commit()
            return True
        return profile.owner_id == user_id


async def upsert_user(
    sf: SessionFactory, user_id: int, full_name: str = "", username: str | None = None
) -> User:
    async with sf() as s:
        user = await s.get(User, user_id)
        if user is None:
            user = User(id=user_id, full_name=full_name, username=username)
            s.add(user)
        else:
            user.full_name = full_name or user.full_name
            user.username = username or user.username
        await s.commit()
        return user


async def recipients(sf: SessionFactory, allowed_ids: list[int]) -> list[int]:
    """Кому слать ежедневные сводки: разрешённые пользователи, которые нажимали /start."""
    async with sf() as s:
        known = set((await s.scalars(select(User.id))).all())
    if allowed_ids:
        return [uid for uid in allowed_ids if uid in known]
    profile = await get_profile(sf)
    return [profile.owner_id] if profile.owner_id else []
