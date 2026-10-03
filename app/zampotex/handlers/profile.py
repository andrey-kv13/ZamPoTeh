from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from zampotex.config import is_admin
from zampotex.formatters import profile_text
from zampotex.keyboards import city_keyboard
from zampotex.parsing import CITIES
from zampotex.repo import delete_account, search_limit, searches_today
from zampotex.states import ProfileFlow
from zampotex.texts import CITY_HINT, CITY_INPUT, DELETE_ASK, DELETE_DONE, DELETE_KEEP, DISCLAIMER
from zampotex.ui import present

router = Router()


def profile_keyboard(admin: bool) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="Изменить город", callback_data="prof:city")],
        [
            InlineKeyboardButton(text="Обычные условия", callback_data="prof:normal"),
            InlineKeyboardButton(text="Тяжёлые условия", callback_data="prof:severe"),
        ],
        [InlineKeyboardButton(text="Оферта и оговорка", callback_data="prof:offer")],
        [InlineKeyboardButton(text="Удалить аккаунт", callback_data="prof:del")],
    ]
    if admin:
        rows.append([InlineKeyboardButton(text="Администрирование", callback_data="admin:home")])
    rows.append([InlineKeyboardButton(text="В меню", callback_data="nav:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def show_profile(target, session: AsyncSession, user) -> None:
    used = await searches_today(session, user.id)
    limit = await search_limit(session)
    admin = is_admin(user.telegram_id)
    await present(target, profile_text(user, used, limit, admin), profile_keyboard(admin))


@router.callback_query(F.data == "prof:city")
async def ask_city(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ProfileFlow.city)
    await present(callback, "Город в профиле подставляется в новые автомобили, если у них город ещё пуст.\n" + CITY_HINT, city_keyboard(0, "cityuser"))


@router.callback_query(ProfileFlow.city, F.data.startswith("cityuserpg:"))
async def city_page(callback: CallbackQuery) -> None:
    await present(callback, CITY_HINT, city_keyboard(int(callback.data.split(":")[1]), "cityuser"))


@router.callback_query(ProfileFlow.city, F.data.startswith("cityuser:"))
async def city_set(callback: CallbackQuery, state: FSMContext, session: AsyncSession, user) -> None:
    value = callback.data.split(":", 1)[1]
    if value == "custom":
        await present(callback, CITY_INPUT, None)
        return
    user.city = CITIES[int(value)]
    await state.clear()
    await show_profile(callback, session, user)


@router.message(ProfileFlow.city, F.text)
async def city_text(message: Message, state: FSMContext, session: AsyncSession, user) -> None:
    city = (message.text or "").strip()
    if len(city) < 2:
        await message.answer(CITY_INPUT)
        return
    user.city = city[:120]
    await state.clear()
    await show_profile(message, session, user)


@router.callback_query(F.data == "prof:normal")
async def set_normal(callback: CallbackQuery, session: AsyncSession, user) -> None:
    user.interval_profile = "normal"
    await show_profile(callback, session, user)


@router.callback_query(F.data == "prof:severe")
async def set_severe(callback: CallbackQuery, session: AsyncSession, user) -> None:
    user.interval_profile = "severe"
    await show_profile(callback, session, user)


@router.callback_query(F.data == "prof:offer")
async def offer(callback: CallbackQuery) -> None:
    await present(
        callback,
        "<b>Оферта</b>\n"
        "Сервис помогает искать сведения и вести учёт. Он не продаёт запчасти и не выполняет ремонт.\n\n"
        + DISCLAIMER,
        InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="← В профиль", callback_data="prof:back")]]),
    )


@router.callback_query(F.data == "prof:back")
async def back(callback: CallbackQuery, session: AsyncSession, user) -> None:
    await show_profile(callback, session, user)


@router.callback_query(F.data == "prof:del")
async def ask_delete(callback: CallbackQuery) -> None:
    await present(
        callback,
        DELETE_ASK,
        InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Удалить навсегда", callback_data="prof:delyes")],
                [InlineKeyboardButton(text="Оставить аккаунт", callback_data="prof:back")],
            ]
        ),
    )


@router.callback_query(F.data == "prof:delyes")
async def do_delete(callback: CallbackQuery, state: FSMContext, session: AsyncSession, user) -> None:
    await state.clear()
    await delete_account(session, user)
    await present(callback, DELETE_DONE, None)


@router.callback_query(F.data == "prof:delno")
async def keep(callback: CallbackQuery, session: AsyncSession, user) -> None:
    await present(callback, DELETE_KEEP, None)
    await show_profile(callback, session, user)
