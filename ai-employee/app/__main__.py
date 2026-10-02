"""Точка входа: python -m app"""

from __future__ import annotations

import asyncio
import logging
import sys

from aiogram.exceptions import TelegramNetworkError, TelegramUnauthorizedError
from aiohttp import web

from app.bot import BOT_COMMANDS, Application, build_health_app, create_application
from app.config import get_settings


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)


async def connect_telegram(application: Application, attempts: int = 6):
    """Проверяет токен и снимает webhook. Сетевые сбои — повтор с паузой."""
    log = logging.getLogger("app")
    delay = 2.0
    for attempt in range(1, attempts + 1):
        try:
            me = await application.bot.get_me()
            await application.bot.delete_webhook(drop_pending_updates=False)
            return me
        except TelegramUnauthorizedError:
            log.error("Telegram отклонил токен. Проверьте переменную TELEGRAM_BOT_TOKEN.")
            raise SystemExit(1) from None
        except TelegramNetworkError as exc:
            if attempt == attempts:
                raise
            log.warning("Нет связи с Telegram (%s), повтор через %.0f с", exc, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30)
    raise RuntimeError("unreachable")


async def run(application: Application) -> None:
    log = logging.getLogger("app")
    runner = web.AppRunner(build_health_app(application))
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", application.settings.port)
    await site.start()
    log.info("Health-check слушает порт %s (/health)", application.settings.port)

    try:
        me = await connect_telegram(application)
        await application.scheduler.start()
        try:
            await application.bot.set_my_commands(BOT_COMMANDS)
        except Exception:
            log.warning("Не удалось установить список команд", exc_info=True)
        log.info("Бот @%s запущен", me.username)
        await application.dp.start_polling(application.bot, handle_signals=True)
    finally:
        await application.scheduler.stop()
        await application.bot.session.close()
        await runner.cleanup()
        await application.engine.dispose()


def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    log = logging.getLogger("app")
    missing = settings.missing_required()
    if missing:
        log.error(
            "Не заданы обязательные переменные окружения: %s. См. .env.example и SETUP.md",
            ", ".join(missing),
        )
        sys.exit(1)
    if not settings.allowed_user_ids:
        log.warning("ALLOWED_USER_IDS пуст: владельцем станет первый, кто нажмёт /start в боте.")
    asyncio.run(_main(settings))


async def _main(settings) -> None:
    application = await create_application(settings)
    await run(application)


if __name__ == "__main__":
    main()
