from pathlib import Path

from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from zampotex.config import PHOTOS_DIR
from zampotex.models import CarPhoto, User


async def store_photo(message: Message, session: AsyncSession, user: User, car_id: int | None = None) -> Path | None:
    if not message.photo or message.bot is None:
        return None
    photo = message.photo[-1]
    file = await message.bot.get_file(photo.file_id)
    if not file.file_path:
        return None
    PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
    target = PHOTOS_DIR / f"{user.telegram_id}_{photo.file_unique_id}.jpg"
    await message.bot.download_file(file.file_path, target)
    session.add(CarPhoto(user_id=user.id, car_id=car_id, path=str(target)))
    return target
