from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from zampotex.handlers.garage import show_garage
from zampotex.handlers.profile import show_profile
from zampotex.handlers.reminders import show_reminders
from zampotex.handlers.search import show_history_picker, start_search
from zampotex.handlers.shelf import show_shelf
from zampotex.keyboards import GARAGE, HISTORY, MENU_TEXTS, PROFILE, REMINDERS, SEARCH, SHELF, consent_keyboard, main_menu
from zampotex.repo import has_consent, mark_link_code
from zampotex.texts import CANCELLED, CONSENT_DECLINED, HELP, ONBOARDING, WELCOME
from zampotex.ui import present

router = Router()


async def _link_from_state(state: FSMContext, session: AsyncSession, telegram_id: int) -> str:
    data = await state.get_data()
    code = data.get("link_code")
    if code:
        await mark_link_code(session, str(code)[:16], telegram_id)
        await state.update_data(link_code=None)
        return "\n\nВход в приложение подтверждён. Вернитесь в приложение."
    return ""


@router.message(CommandStart())
async def start(message: Message, command: CommandObject, state: FSMContext, session: AsyncSession, user) -> None:
    payload = (command.args or "").strip()
    if payload.startswith("link_"):
        await state.update_data(link_code=payload.removeprefix("link_")[:16])
    if not has_consent(user):
        await message.answer(WELCOME, reply_markup=consent_keyboard())
        return
    extra = await _link_from_state(state, session, user.telegram_id)
    await state.clear()
    await message.answer("С возвращением. Разделы внизу — нажимайте их, не нужно помнить команды." + extra, reply_markup=main_menu())


@router.callback_query(F.data == "consent:yes")
async def consent_yes(callback: CallbackQuery, state: FSMContext, session: AsyncSession, user) -> None:
    from zampotex.texts import OFFER_VERSION, PRIVACY_VERSION

    user.consent_offer_version = OFFER_VERSION
    user.consent_privacy_version = PRIVACY_VERSION
    extra = await _link_from_state(state, session, user.telegram_id)
    await state.clear()
    await callback.answer("Согласие сохранено")
    if callback.message:
        await callback.message.answer(ONBOARDING + extra, reply_markup=main_menu())


@router.callback_query(F.data == "consent:no")
async def consent_no(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await present(callback, CONSENT_DECLINED, None)


@router.message(Command("help"))
async def help_cmd(message: Message) -> None:
    await message.answer(HELP, reply_markup=main_menu())


@router.message(Command("menu"))
@router.message(Command("cancel"))
async def cancel_cmd(message: Message, state: FSMContext) -> None:
    await state.clear()
    text = CANCELLED if (message.text or "").startswith("/cancel") else "Разделы внизу. Если нужно найти деталь — нажмите «Найти запчасть» и опишите её своими словами."
    await message.answer(text, reply_markup=main_menu())


@router.message(Command("garage"))
@router.message(F.text == GARAGE)
async def garage_entry(message: Message, state: FSMContext, session: AsyncSession, user) -> None:
    await state.clear()
    await show_garage(message, session, user)


@router.message(Command("search"))
@router.message(F.text == SEARCH)
async def search_entry(message: Message, state: FSMContext, session: AsyncSession, user) -> None:
    await state.clear()
    await start_search(message, state, session, user)


@router.message(Command("shelf"))
@router.message(F.text == SHELF)
async def shelf_entry(message: Message, state: FSMContext, session: AsyncSession, user) -> None:
    await state.clear()
    await show_shelf(message, session, user)


@router.message(Command("reminders"))
@router.message(F.text == REMINDERS)
async def reminders_entry(message: Message, state: FSMContext, session: AsyncSession, user) -> None:
    await state.clear()
    await show_reminders(message, session, user)


@router.message(Command("history"))
@router.message(F.text == HISTORY)
async def history_entry(message: Message, state: FSMContext, session: AsyncSession, user) -> None:
    await state.clear()
    await show_history_picker(message, session, user)


@router.message(Command("profile"))
@router.message(F.text == PROFILE)
async def profile_entry(message: Message, state: FSMContext, session: AsyncSession, user) -> None:
    await state.clear()
    await show_profile(message, session, user)


@router.callback_query(F.data == "nav:menu")
@router.callback_query(F.data == "nav:cancel")
async def nav_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    if callback.message:
        text = CANCELLED if callback.data == "nav:cancel" else "Выберите раздел кнопкой внизу."
        await callback.message.answer(text, reply_markup=main_menu())


@router.callback_query(F.data == "nav:garage")
async def nav_garage(callback: CallbackQuery, state: FSMContext, session: AsyncSession, user) -> None:
    await state.clear()
    await show_garage(callback, session, user)


@router.message(F.text.in_(MENU_TEXTS))
async def menu_guard(message: Message) -> None:
    await message.answer("Выберите раздел ещё раз.", reply_markup=main_menu())
