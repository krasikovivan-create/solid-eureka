"""Приложение собирается и стартует без исключений при заданных переменных."""

import asyncio
import socket
import subprocess
import sys
from pathlib import Path

from aiogram import Bot
from aiogram.methods import GetUpdates, SetMyCommands
from aiohttp.test_utils import TestClient, TestServer

from app.bot import build_health_app, create_application
from tests.conftest import TOKEN, FakeAnthropic

ROOT = Path(__file__).resolve().parents[1]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def test_full_start_and_stop(settings, session):
    from app.__main__ import run

    settings.port = free_port()
    bot = Bot(TOKEN, session=session)
    application = await create_application(settings, bot=bot, llm_client=FakeAnthropic())

    async def stop_soon():
        for _ in range(100):
            if any(isinstance(r, GetUpdates) for r in session.requests):
                break
            await asyncio.sleep(0.05)
        await application.dp.stop_polling()

    stopper = asyncio.create_task(stop_soon())
    await asyncio.wait_for(run(application), timeout=15)
    await stopper
    assert any(isinstance(r, SetMyCommands) for r in session.requests)
    assert any(isinstance(r, GetUpdates) for r in session.requests)
    assert Path(settings.db_path).exists()


async def test_health_endpoint(settings, session):
    application = await create_application(
        settings, bot=Bot(TOKEN, session=session), llm_client=FakeAnthropic()
    )
    try:
        async with TestClient(TestServer(build_health_app(application))) as client:
            resp = await client.get("/health")
            assert resp.status == 200
            data = await resp.json()
            assert data["status"] == "ok" and data["db"] is True
    finally:
        await application.engine.dispose()


def test_main_exits_with_clear_message_without_env(tmp_path):
    env = {"PATH": "/usr/bin:/bin", "DB_PATH": str(tmp_path / "x.db"), "HOME": str(tmp_path)}
    proc = subprocess.run(
        [sys.executable, "-m", "app"], cwd=ROOT, env=env, capture_output=True, text=True, timeout=60
    )
    assert proc.returncode == 1
    assert "TELEGRAM_BOT_TOKEN" in proc.stdout + proc.stderr


def test_app_imports():
    import app.__main__
    import app.bot  # noqa: F401


async def test_bad_token_exits_with_clear_message(settings, session, caplog):
    import pytest
    from aiogram.exceptions import TelegramUnauthorizedError
    from aiogram.methods import GetMe

    from app.__main__ import connect_telegram

    original = session.make_request

    async def make_request(bot, method, timeout=None):
        if isinstance(method, GetMe):
            raise TelegramUnauthorizedError(method=method, message="Unauthorized")
        return await original(bot, method, timeout)

    session.make_request = make_request
    application = await create_application(
        settings, bot=Bot(TOKEN, session=session), llm_client=FakeAnthropic()
    )
    try:
        with pytest.raises(SystemExit):
            await connect_telegram(application)
        assert "TELEGRAM_BOT_TOKEN" in caplog.text
    finally:
        await application.engine.dispose()
