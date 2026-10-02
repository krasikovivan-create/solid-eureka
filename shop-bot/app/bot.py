"""Сборка бота: Bot, Dispatcher, middlewares, зависимости, планировщик."""

from __future__ import annotations

from dataclasses import dataclass

import anthropic
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.enums import ParseMode
from aiogram.fsm.storage.base import BaseStorage
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.config import Settings
from app.db.session import create_engine, create_sessionmaker
from app.handlers import build_root_router
from app.middlewares.db import DbSessionMiddleware
from app.middlewares.throttling import ThrottlingMiddleware
from app.middlewares.user import UserMiddleware
from app.scheduler import setup_scheduler
from app.services.admins import AdminRegistry
from app.services.delivery import build_providers
from app.services.jobs import Jobs
from app.services.notifications import BotNotifier
from app.services.shop_config import ShopConfig
from app.services.stylist import build_client


@dataclass
class App:
    bot: Bot
    dp: Dispatcher
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    scheduler: AsyncIOScheduler
    anthropic_client: anthropic.AsyncAnthropic | None
    admins: AdminRegistry
    shop: ShopConfig


def build_storage(settings: Settings) -> BaseStorage:
    if settings.redis_url:
        from aiogram.fsm.storage.redis import RedisStorage

        return RedisStorage.from_url(settings.redis_url)
    return MemoryStorage()


def build_app(settings: Settings, bot_session: BaseSession | None = None) -> App:
    """bot_session — своя HTTP-сессия Bot API (в тестах — фейковая)."""
    bot = Bot(
        token=settings.bot_token.get_secret_value(),
        session=bot_session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    engine = create_engine(settings.database_url, echo=settings.db_echo)
    session_factory = create_sessionmaker(engine)
    providers = build_providers(autoadvance=settings.mock_tracking_autoadvance)
    admins = AdminRegistry(settings.admin_ids)
    shop = ShopConfig(settings)
    notifier = BotNotifier(bot, admins)
    anthropic_client = build_client(settings)
    jobs = Jobs(bot, session_factory, settings, notifier, providers)

    dp = Dispatcher(storage=build_storage(settings))
    dp.update.outer_middleware(DbSessionMiddleware(session_factory))
    dp.update.outer_middleware(UserMiddleware())
    throttling = ThrottlingMiddleware(settings.throttle_rate)
    dp.message.outer_middleware(throttling)
    dp.callback_query.outer_middleware(throttling)
    dp.include_router(build_root_router())
    dp.workflow_data.update(
        settings=settings,
        providers=providers,
        notifier=notifier,
        session_factory=session_factory,
        anthropic_client=anthropic_client,
        jobs=jobs,
        admins=admins,
        shop=shop,
    )
    scheduler = setup_scheduler(
        jobs, settings.timezone, keep_awake=settings.keep_awake and settings.is_webhook
    )
    return App(bot, dp, engine, session_factory, scheduler, anthropic_client, admins, shop)
