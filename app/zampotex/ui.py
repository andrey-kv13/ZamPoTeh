from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message

from zampotex.keyboards import main_menu


async def present(target: Message | CallbackQuery, text: str, inline=None, reply=None) -> None:
    markup = inline if inline is not None else reply
    if isinstance(target, CallbackQuery):
        await target.answer()
        message = target.message
        if message is None:
            return
        try:
            await message.edit_text(text, reply_markup=markup)
            return
        except TelegramBadRequest:
            await message.answer(text, reply_markup=markup or main_menu())
            return
    await target.answer(text, reply_markup=markup or main_menu())
