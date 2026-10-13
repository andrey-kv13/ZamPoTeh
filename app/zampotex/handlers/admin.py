import asyncio
import html

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from zampotex.config import is_admin
from zampotex.parts_catalog import admin_probe
from zampotex.models import User
from zampotex.repo import recent_users, search_limit, set_setting, stats
from zampotex.texts import ADMIN_DENIED, LEADS_DENIED
from zampotex.ui import present

router = Router()


def admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Статистика", callback_data="admin:stats")],
            [InlineKeyboardButton(text="Пользователи", callback_data="admin:users")],
            [InlineKeyboardButton(text="Лимит поиска", callback_data="admin:limit")],
            [InlineKeyboardButton(text="PartsAPI / TecDoc", callback_data="admin:partsapi")],
            [InlineKeyboardButton(text="В меню пользователя", callback_data="nav:menu")],
        ]
    )


async def show_admin(target, session: AsyncSession) -> None:
    data = await stats(session)
    limit = await search_limit(session)
    text = (
        "<b>Администрирование</b>\n\n"
        f"Пользователи: {data['users']}\n"
        f"Автомобили: {data['cars']}\n"
        f"Запросы: {data['searches']}\n"
        f"Из них без каталога: {data['unavailable']}\n"
        f"Суточный лимит внешней проверки: {limit}\n\n"
        "TecDoc (PartsAPI): см. кнопку «PartsAPI / TecDoc».\n"
        "Очереди сервисов и покупки автомобиля в этом запуске выключены.\n"
        "Лиды организаций пока недоступны."
    )
    await present(target, text, admin_keyboard())


@router.message(Command("admin"))
async def admin_cmd(message: Message, session: AsyncSession, user: User) -> None:
    if not is_admin(user.telegram_id):
        await message.answer(ADMIN_DENIED)
        return
    await show_admin(message, session)


@router.message(Command("leads"))
async def leads_cmd(message: Message) -> None:
    await message.answer(LEADS_DENIED)


@router.callback_query(F.data == "admin:home")
async def admin_home(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    if not is_admin(user.telegram_id):
        await callback.answer(ADMIN_DENIED, show_alert=True)
        return
    await show_admin(callback, session)


@router.callback_query(F.data == "admin:stats")
async def admin_stats(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    if not is_admin(user.telegram_id):
        await callback.answer(ADMIN_DENIED, show_alert=True)
        return
    await show_admin(callback, session)


@router.callback_query(F.data == "admin:users")
async def admin_users(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    if not is_admin(user.telegram_id):
        await callback.answer(ADMIN_DENIED, show_alert=True)
        return
    rows = await recent_users(session)
    lines = ["<b>Последние пользователи</b>\n"]
    buttons = []
    for person in rows:
        mark = "заблокирован" if person.is_blocked else "активен"
        lines.append(f"• {person.telegram_id} · {html.escape(person.telegram_name or 'без имени')} · {mark}")
        if person.telegram_id not in {user.telegram_id} and not is_admin(person.telegram_id):
            action = "Разблокировать" if person.is_blocked else "Заблокировать"
            buttons.append([InlineKeyboardButton(text=f"{action} {person.telegram_id}", callback_data=f"blk:{person.telegram_id}")])
    buttons.append([InlineKeyboardButton(text="← Назад", callback_data="admin:home")])
    await present(callback, "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=buttons))


@router.callback_query(F.data.startswith("blk:"))
async def block_user(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    if not is_admin(user.telegram_id):
        await callback.answer(ADMIN_DENIED, show_alert=True)
        return
    telegram_id = int(callback.data.split(":")[1])
    if is_admin(telegram_id):
        await callback.answer("Администратора заблокировать нельзя", show_alert=True)
        return
    from zampotex.repo import get_user

    person = await get_user(session, telegram_id)
    if person is None:
        await callback.answer("Пользователь не найден", show_alert=True)
        return
    person.is_blocked = not person.is_blocked
    await callback.answer("Готово")
    await admin_users(callback, session, user)


@router.callback_query(F.data == "admin:partsapi")
async def admin_partsapi(callback: CallbackQuery, user: User) -> None:
    if not is_admin(user.telegram_id):
        await callback.answer(ADMIN_DENIED, show_alert=True)
        return
    vin = "X4X5D39490D883173"
    text = html.escape(await asyncio.to_thread(admin_probe, vin, "правый рулевой наконечник"))
    await present(
        callback,
        f"<b>PartsAPI / TecDoc</b>\n\n<pre>{text}</pre>",
        InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="← Назад", callback_data="admin:home")]]
        ),
    )


@router.callback_query(F.data == "admin:limit")
async def limit_menu(callback: CallbackQuery, user: User) -> None:
    if not is_admin(user.telegram_id):
        await callback.answer(ADMIN_DENIED, show_alert=True)
        return
    await present(
        callback,
        "Лимит считается только для внешней проверки каталога.\nСейчас адаптер выключен, и отказы лимит не тратят.\nВыберите значение на будущее.",
        InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="10", callback_data="limit:10"),
                    InlineKeyboardButton(text="20", callback_data="limit:20"),
                    InlineKeyboardButton(text="50", callback_data="limit:50"),
                ],
                [InlineKeyboardButton(text="← Назад", callback_data="admin:home")],
            ]
        ),
    )


@router.callback_query(F.data.startswith("limit:"))
async def set_limit(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    if not is_admin(user.telegram_id):
        await callback.answer(ADMIN_DENIED, show_alert=True)
        return
    await set_setting(session, "search_daily_limit", callback.data.split(":")[1])
    await callback.answer("Лимит сохранён")
    await show_admin(callback, session)
