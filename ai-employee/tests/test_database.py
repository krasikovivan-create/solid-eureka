from datetime import UTC, datetime

from sqlalchemy import inspect

from app.database.models import Task
from app.services import profile as profile_service
from tests.conftest import OWNER_ID


async def test_schema_created(app):
    async with app.sf() as s:
        conn = await s.connection()
        tables = await conn.run_sync(lambda c: inspect(c).get_table_names())
    for name in (
        "company_profile",
        "users",
        "clients",
        "interactions",
        "tasks",
        "audits",
        "proposals",
        "documents",
        "document_chunks",
        "messages",
        "conversation_summaries",
        "facts",
        "usage_records",
    ):
        assert name in tables


async def test_profile_defaults_and_update(app):
    p = await profile_service.get_profile(app.sf)
    assert p.onboarded is False
    assert p.morning_time == "09:00" and p.evening_time == "19:00"
    assert p.timezone == "Europe/Moscow"
    p = await profile_service.update_profile(app.sf, morning_time="8:30", company_name="Тест")
    assert p.morning_time == "08:30"
    assert p.company_name == "Тест"


async def test_profile_validation(app):
    import pytest

    with pytest.raises(ValueError):
        await profile_service.update_profile(app.sf, morning_time="99:99")
    with pytest.raises(ValueError):
        await profile_service.update_profile(app.sf, timezone="Mars/Base")
    with pytest.raises(ValueError):
        await profile_service.update_profile(app.sf, unknown_field=1)


async def test_owner_claim_and_access(app):
    assert not await profile_service.is_allowed(app.sf, [], OWNER_ID)
    assert await profile_service.try_claim_owner(app.sf, OWNER_ID)
    assert await profile_service.is_allowed(app.sf, [], OWNER_ID)
    # второй пользователь владельцем стать не может
    assert not await profile_service.try_claim_owner(app.sf, 2002)
    assert not await profile_service.is_allowed(app.sf, [], 2002)
    # явный список имеет приоритет
    assert await profile_service.is_allowed(app.sf, [2002], 2002)
    assert not await profile_service.is_allowed(app.sf, [2002], OWNER_ID)


async def test_recipients(app):
    await profile_service.try_claim_owner(app.sf, OWNER_ID)
    assert await profile_service.recipients(app.sf, []) == [OWNER_ID]
    await profile_service.upsert_user(app.sf, 5, "A")
    assert await profile_service.recipients(app.sf, [5, 6]) == [5]


async def test_utc_datetime_roundtrip(app):
    when = datetime(2026, 10, 3, 7, 0, tzinfo=UTC)
    async with app.sf() as s:
        t = Task(user_id=1, title="x", due_at=when)
        s.add(t)
        await s.commit()
        tid = t.id
    async with app.sf() as s:
        t = await s.get(Task, tid)
        assert t.due_at == when
        assert t.due_at.tzinfo is not None


async def test_data_persists_between_engines(settings):
    from app.database.session import create_engine, init_db, make_session_factory

    engine = create_engine(settings.db_path)
    await init_db(engine)
    await profile_service.update_profile(make_session_factory(engine), company_name="Сохранено")
    await engine.dispose()

    engine2 = create_engine(settings.db_path)
    await init_db(engine2)
    p = await profile_service.get_profile(make_session_factory(engine2))
    assert p.company_name == "Сохранено"
    await engine2.dispose()
