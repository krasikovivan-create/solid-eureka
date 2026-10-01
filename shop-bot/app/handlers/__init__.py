from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, ErrorEvent, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import User
from app.filters import IsAdmin
from app.handlers.admin import marketing as admin_marketing
from app.handlers.admin import menu as admin_menu
from app.handlers.admin import orders as admin_orders
from app.handlers.admin import products as admin_products
from app.handlers.admin import settings as admin_settings
from app.handlers.user import cart, catalog, checkout, orders, start, stylist
from app.handlers.user.start import menu_markup
from app.texts import t

logger = logging.getLogger(__name__)


def _detached(*routers: Router) -> tuple[Router, ...]:
    """Роутеры хэндлеров объявлены на уровне модулей. Отвязываем их от предыдущего
    диспетчера, чтобы приложение можно было собрать повторно (тесты, перезапуск)."""
    for router in routers:
        router._parent_router = None
    return routers


def build_admin_router() -> Router:
    router = Router(name="admin")
    router.message.filter(IsAdmin())
    router.callback_query.filter(IsAdmin())
    router.include_routers(
        *_detached(
            admin_menu.router,
            admin_products.router,
            admin_settings.router,
            admin_orders.router,
            admin_marketing.router,
        )
    )
    return router


fallback_router = Router(name="fallback")


@fallback_router.callback_query()
async def unknown_callback(callback: CallbackQuery) -> None:
    await callback.answer(t("common.not_found"))


@fallback_router.message(F.chat.type == "private")
async def unknown_message(
    message: Message, state: FSMContext, session: AsyncSession, user: User, settings: Settings
) -> None:
    if await state.get_state() is not None:
        # Пользователь в сценарии, но прислал не то (например, стикер вместо текста).
        await message.answer(t("common.unknown"))
        return
    await message.answer(
        t("common.unknown"), reply_markup=await menu_markup(session, user, settings)
    )


errors_router = Router(name="errors")


@errors_router.error()
async def on_error(event: ErrorEvent) -> bool:
    logger.exception("Ошибка обработки апдейта: %s", event.exception, exc_info=event.exception)
    update = event.update
    try:
        if update.callback_query:
            await update.callback_query.answer(t("common.error"), show_alert=True)
        elif update.message:
            await update.message.answer(t("common.error"))
    except Exception:  # ответить пользователю не удалось — ошибка уже залогирована
        logger.debug("Не удалось сообщить пользователю об ошибке", exc_info=True)
    return True


def build_root_router() -> Router:
    root = Router(name="root")
    root.include_routers(
        *_detached(errors_router, start.router),
        # Админка — раньше каталога: её FSM-хэндлеры получают ввод админа первыми.
        build_admin_router(),
        *_detached(
            catalog.router,
            cart.router,
            checkout.router,
            orders.router,
            stylist.router,
            fallback_router,
        ),
    )
    return root
