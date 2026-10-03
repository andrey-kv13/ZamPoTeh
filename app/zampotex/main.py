import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeChat

from zampotex.config import get_settings
from zampotex.db import init_db
from zampotex.handlers import admin, fallback, garage, profile, reminders, search, shelf, start
from zampotex.middlewares import AppMiddleware
from zampotex.notifier import dispatch_reminders

logger = logging.getLogger("zampotex")

USER_COMMANDS = [
    BotCommand(command="menu", description="Показать разделы"),
    BotCommand(command="search", description="Найти запчасть"),
    BotCommand(command="garage", description="Мой гараж"),
    BotCommand(command="shelf", description="Стеллаж"),
    BotCommand(command="reminders", description="Напоминания"),
    BotCommand(command="history", description="История запросов"),
    BotCommand(command="profile", description="Профиль"),
    BotCommand(command="help", description="Подсказки"),
    BotCommand(command="cancel", description="Отменить текущий шаг"),
]


async def _reminders(bot: Bot) -> None:
    while True:
        try:
            await dispatch_reminders(bot)
        except Exception:
            logger.exception("Сбой напоминаний")
        await asyncio.sleep(300)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = get_settings()
    if not settings.bot_token.strip():
        raise SystemExit(
            "В файле app/.env нет BOT_TOKEN.\n"
            "Откройте @BotFather, скопируйте токен бота 8893240032 и вставьте его в app/.env:\n"
            "BOT_TOKEN=8893240032:сюда_секретная_часть"
        )
    await init_db()
    bot = Bot(token=settings.bot_token.strip(), default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    me = await bot.get_me()
    if me.id != settings.bot_id:
        logger.warning("Токен принадлежит боту %s, а в настройках указан id %s", me.id, settings.bot_id)
    await bot.set_my_commands(USER_COMMANDS)
    for admin_id in settings.admins:
        try:
            await bot.set_my_commands(
                USER_COMMANDS + [BotCommand(command="admin", description="Администрирование")],
                scope=BotCommandScopeChat(chat_id=admin_id),
            )
        except Exception:
            logger.info("Не удалось записать команды администратору %s, пока он не нажмёт /start", admin_id)

    dispatcher = Dispatcher(storage=MemoryStorage())
    middleware = AppMiddleware()
    dispatcher.message.middleware(middleware)
    dispatcher.callback_query.middleware(middleware)
    dispatcher.include_router(start.router)
    dispatcher.include_router(admin.router)
    dispatcher.include_router(garage.router)
    dispatcher.include_router(search.router)
    dispatcher.include_router(shelf.router)
    dispatcher.include_router(reminders.router)
    dispatcher.include_router(profile.router)
    dispatcher.include_router(fallback.router)

    asyncio.create_task(_reminders(bot))
    logger.info("Бот @%s запущен", me.username)
    await dispatcher.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
