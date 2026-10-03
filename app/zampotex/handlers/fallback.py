from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from zampotex.files import store_photo
from zampotex.handlers.garage import accept_vin
from zampotex.keyboards import main_menu
from zampotex.parsing import message_is_vin
from zampotex.texts import PHOTO_SAVED, STALE_BUTTON, VOICE_UNSUPPORTED

router = Router()


@router.message(F.voice)
async def voice(message: Message) -> None:
    await message.answer(VOICE_UNSUPPORTED, reply_markup=main_menu())


@router.message(F.photo)
async def photo(message: Message, session: AsyncSession, user) -> None:
    await store_photo(message, session, user, user.active_car_id)
    await message.answer(PHOTO_SAVED, reply_markup=main_menu())


@router.message()
async def fallback(message: Message, state: FSMContext, session: AsyncSession, user) -> None:
    current = await state.get_state()
    vin = message_is_vin(message.text or "")
    if vin and current is None:
        await accept_vin(message, state, session, user, vin)
        return
    if current:
        await message.answer("Жду ответ на предыдущий шаг. Если хотите выйти, нажмите /cancel или выберите раздел внизу.", reply_markup=main_menu())
        return
    await message.answer(
        "Не разобрал сообщение.\nМожно прислать VIN из 17 знаков — проверю международный WMI, mcp.vin, NHTSA и DB.VIN. "
        "Или нажмите «Найти запчасть» и опишите деталь своими словами.",
        reply_markup=main_menu(),
    )


@router.callback_query()
async def stale(callback, state: FSMContext) -> None:
    await callback.answer(STALE_BUTTON, show_alert=True)
