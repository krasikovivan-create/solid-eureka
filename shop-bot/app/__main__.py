"""Точка входа: python -m app

Режим polling — по умолчанию (WEBHOOK_URL пуст). В обоих режимах поднимается HTTP-сервер
с /health на PORT — это нужно Railway/Render для проверки живости сервиса.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal

from aiogram.types import BotCommand
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

from app.bot import App, build_app
from app.config import get_settings

logger = logging.getLogger("app")


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


async def health(_: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


async def on_startup(app: App) -> None:
    settings = get_settings()
    await app.bot.set_my_commands(
        [
            BotCommand(command="start", description="Главное меню"),
            BotCommand(command="admin", description="Админ-панель (для администраторов)"),
        ]
    )
    if settings.payments_mode == "fake":
        logger.warning("PAYMENTS_MODE=fake: оплата работает в тестовом режиме без списания денег")
    await app.admins.load(app.session_factory)
    if app.admins.empty:
        logger.warning(
            "Админов пока нет: первый, кто отправит боту /admin, станет владельцем магазина"
        )
    app.scheduler.start()
    me = await app.bot.me()
    logger.info("Бот @%s запущен", me.username)


async def on_shutdown(app: App) -> None:
    if app.scheduler.running:
        app.scheduler.shutdown(wait=False)
    if app.anthropic_client is not None:
        await app.anthropic_client.close()
    await app.engine.dispose()


async def run() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    if not settings.bot_token.get_secret_value():
        raise SystemExit("BOT_TOKEN не задан. Скопируйте .env.example в .env и заполните его.")
    app = build_app(settings)

    web_app = web.Application()
    web_app.router.add_get("/health", health)
    web_app.router.add_get("/", health)

    if settings.is_webhook:
        secret = settings.webhook_secret.get_secret_value() or None
        SimpleRequestHandler(dispatcher=app.dp, bot=app.bot, secret_token=secret).register(
            web_app, path=settings.webhook_path
        )
        setup_application(web_app, app.dp, bot=app.bot)

    runner = web.AppRunner(web_app)
    await runner.setup()
    await web.TCPSite(runner, settings.host, settings.port).start()
    logger.info("HTTP-сервер слушает %s:%s", settings.host, settings.port)

    await on_startup(app)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):  # Windows
            loop.add_signal_handler(sig, stop.set)

    try:
        if settings.is_webhook:
            url = settings.webhook_url.rstrip("/") + settings.webhook_path
            await app.bot.set_webhook(
                url,
                secret_token=settings.webhook_secret.get_secret_value() or None,
                allowed_updates=app.dp.resolve_used_update_types(),
                drop_pending_updates=False,
            )
            logger.info("Webhook установлен: %s", url)
            await stop.wait()
        else:
            await app.bot.delete_webhook(drop_pending_updates=False)
            polling = asyncio.create_task(
                app.dp.start_polling(
                    app.bot,
                    allowed_updates=app.dp.resolve_used_update_types(),
                    handle_signals=False,
                )
            )
            stopper = asyncio.create_task(stop.wait())
            await asyncio.wait({polling, stopper}, return_when=asyncio.FIRST_COMPLETED)
            if not polling.done():
                await app.dp.stop_polling()
                await asyncio.wait({polling}, timeout=10)
            stopper.cancel()
            if polling.done() and not polling.cancelled() and polling.exception():
                raise polling.exception()
    finally:
        await on_shutdown(app)
        await runner.cleanup()
        await app.bot.session.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
