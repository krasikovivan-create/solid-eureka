from aiohttp import web

from app.config import Settings
from app.services.admins import AdminRegistry
from app.services.jobs import Jobs


async def test_registry_add_remove_and_claim(session_factory, session):
    registry = AdminRegistry([1])
    assert registry.is_admin(1) and not registry.empty
    assert not await registry.claim(session, 2)  # владелец уже есть (ADMIN_IDS)

    assert await registry.add(session, 2, added_by=1)
    assert not await registry.add(session, 2, added_by=1)
    assert not await registry.remove(session, 1)  # из ADMIN_IDS удалить нельзя
    assert await registry.remove(session, 2)
    assert registry.ids == [1]


async def test_last_admin_cannot_be_removed(session):
    registry = AdminRegistry([])
    assert await registry.claim(session, 10)
    assert not await registry.claim(session, 11)
    assert not await registry.remove(session, 10)
    assert registry.ids == [10]


async def test_claim_respects_admins_from_other_process(session_factory, session):
    await AdminRegistry([]).claim(session, 10)  # «другой процесс» уже назначил владельца
    stale = AdminRegistry([])  # кэш этого процесса ещё пуст
    assert not await stale.claim(session, 99)
    assert stale.ids == [10]


async def test_keep_awake_pings_health(session_factory, notifier, providers, unused_tcp_port):
    app = web.Application()
    hits = []

    async def health(_):
        hits.append(1)
        return web.json_response({"status": "ok"})

    app.router.add_get("/health", health)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", unused_tcp_port).start()
    try:
        settings = Settings(
            _env_file=None, bot_token="1:x", WEBHOOK_URL=f"http://127.0.0.1:{unused_tcp_port}/"
        )
        jobs = Jobs(None, session_factory, settings, notifier, providers)
        assert await jobs.keep_awake()
        assert hits == [1]
    finally:
        await runner.cleanup()
