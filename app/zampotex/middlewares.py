import logging

from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message

from zampotex.config import is_admin
from zampotex.db import session_factory
from zampotex.keyboards import consent_keyboard
from zampotex.repo import get_or_create_user, has_consent
from zampotex.texts import BLOCKED, PRIVATE_ONLY, SERVICE_DOWN, WELCOME

logger = logging.getLogger("zampotex")


def _chat_type(event: Message | CallbackQuery) -> str | None:
    if isinstance(event, Message):
        return event.chat.type
    if event.message:
        return event.message.chat.type
    return None


def _allowed_without_consent(event: Message | CallbackQuery) -> bool:
    if isinstance(event, CallbackQuery):
        return bool(event.data and event.data.startswith("consent:"))
    text = event.text or ""
    return text.startswith("/start") or text.startswith("/help")


class AppMiddleware:
    async def __call__(self, handler, event, data):
        if _chat_type(event) not in {None, ChatType.PRIVATE}:
            if isinstance(event, Message):
                await event.answer(PRIVATE_ONLY)
            elif isinstance(event, CallbackQuery):
                await event.answer(PRIVATE_ONLY, show_alert=True)
            return None

        from_user = event.from_user
        if from_user is None:
            return None
        name = " ".join(part for part in (from_user.first_name, from_user.last_name) if part) or from_user.username

        async with session_factory()() as session:
            data["session"] = session
            try:
                user = await get_or_create_user(session, from_user.id, name)
                data["user"] = user
                if user.is_blocked and not is_admin(from_user.id):
                    await _reply(event, BLOCKED)
                elif not has_consent(user) and not _allowed_without_consent(event):
                    await _reply(event, WELCOME, consent_keyboard())
                else:
                    await handler(event, data)
            except TelegramBadRequest:
                logger.info("Telegram отклонил сообщение", exc_info=True)
            except Exception:
                await session.rollback()
                logger.exception("Ошибка обработки сообщения")
                await _reply(event, SERVICE_DOWN)
                return None
            await session.commit()
        return None


async def _reply(event: Message | CallbackQuery, text: str, markup=None) -> None:
    if isinstance(event, Message):
        await event.answer(text, reply_markup=markup)
        return
    await event.answer()
    if event.message:
        await event.message.answer(text, reply_markup=markup)
