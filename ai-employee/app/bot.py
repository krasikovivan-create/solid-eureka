"""Сборка приложения: БД, ИИ, бот, диспетчер, планировщик, health-check."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, ErrorEvent
from aiohttp import web
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app import keyboards
from app.agent.agent import Agent
from app.agent.llm import LLM
from app.config import Settings
from app.context import AppContext
from app.database.session import create_engine, init_db, make_session_factory
from app.handlers import audit, chat, clients, confirm, documents, menu, settings, start
from app.handlers.common import send_html
from app.middlewares import AppMiddleware
from app.scheduler.scheduler import BotScheduler
from app.services.knowledge import KnowledgeBase

log = logging.getLogger(__name__)

BOT_COMMANDS = [
    BotCommand(command="menu", description="Главное меню"),
    BotCommand(command="today", description="План на сегодня"),
    BotCommand(command="tasks", description="Задачи"),
    BotCommand(command="clients", description="Клиенты и воронка"),
    BotCommand(command="audit", description="Аудит процессов клиента"),
    BotCommand(command="kb", description="База знаний"),
    BotCommand(command="settings", description="Настройки"),
    BotCommand(command="usage", description="Расходы на ИИ"),
    BotCommand(command="new", description="Начать диалог заново"),
    BotCommand(command="help", description="Помощь и примеры"),
]

ERROR_TEXT = (
    "⚠️ Что-то пошло не так, но я записал ошибку в лог. Попробуйте ещё раз или откройте /menu."
)


@dataclass
class Application:
    settings: Settings
    engine: AsyncEngine
    app: AppContext
    bot: Bot
    dp: Dispatcher
    agent: Agent
    scheduler: BotScheduler


def build_dispatcher(app: AppContext, agent: Agent) -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    middleware = AppMiddleware(app, agent)
    dp.message.outer_middleware(middleware)
    dp.callback_query.outer_middleware(middleware)
    # Порядок важен: команды и состояния — раньше свободного чата.
    dp.include_routers(
        start.router,
        settings.router,
        audit.router,
        menu.router,
        clients.router,
        confirm.router,
        documents.router,
        chat.router,
    )

    @dp.errors()
    async def on_error(event: ErrorEvent) -> bool:
        log.exception("Необработанная ошибка: %s", event.exception, exc_info=event.exception)
        update = event.update
        chat_id = None
        if update.message is not None:
            chat_id = update.message.chat.id
        elif update.callback_query is not None and update.callback_query.message is not None:
            chat_id = update.callback_query.message.chat.id
            try:
                await update.callback_query.answer()
            except Exception:
                pass
        if chat_id is not None:
            try:
                await event.update.bot.send_message(chat_id, ERROR_TEXT, parse_mode=None)
            except Exception:
                log.exception("Не удалось сообщить пользователю об ошибке")
        return True

    return dp


async def create_application(
    settings: Settings, bot: Bot | None = None, llm_client=None
) -> Application:
    engine = create_engine(settings.db_path)
    await init_db(engine)
    sf = make_session_factory(engine)
    llm = LLM(settings, sf, client=llm_client)
    kb = KnowledgeBase(sf, settings.documents_dir)
    app = AppContext(settings=settings, sf=sf, llm=llm, kb=kb)
    bot = bot or Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True),
    )

    async def sender(user_id: int, text: str, markup) -> None:
        await send_html(bot, user_id, text, markup)

    scheduler = BotScheduler(app, sender, reminder_keyboard=keyboards.reminder)
    app.scheduler = scheduler
    agent = Agent(app)
    dp = build_dispatcher(app, agent)
    return Application(settings, engine, app, bot, dp, agent, scheduler)


def build_health_app(application: Application) -> web.Application:
    async def health(_request: web.Request) -> web.Response:
        try:
            async with application.app.sf() as s:
                await s.execute(text("SELECT 1"))
        except Exception:
            log.exception("Health-check: БД недоступна")
            return web.json_response({"status": "error", "db": False}, status=503)
        return web.json_response(
            {"status": "ok", "db": True, "scheduler": application.scheduler.scheduler.running}
        )

    web_app = web.Application()
    web_app.router.add_get("/health", health)
    web_app.router.add_get("/", health)
    return web_app
