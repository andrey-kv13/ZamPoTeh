import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError

from zampotex.db import session_factory
from html import escape

from zampotex.formatters import car_title
from zampotex.handlers.reminders import _aware
from zampotex.parsing import WORK_LABELS
from zampotex.repo import due_reminders
from zampotex.texts import MILEAGE_NAG

logger = logging.getLogger("zampotex")


async def dispatch_reminders(bot: Bot) -> None:
    async with session_factory()() as session:
        now = datetime.now(timezone.utc)
        rows = await due_reminders(session)
        for reminder, car, user in rows:
            mileage_stale = car.mileage_at is None or (_aware(car.mileage_at) < now - timedelta(days=180))
            pieces = []
            key_parts = []
            if reminder.next_mileage is not None and mileage_stale:
                nag_at = _aware(user.mileage_nag_at) if user.mileage_nag_at else None
                if nag_at is None or nag_at < now - timedelta(days=30):
                    await _send(bot, user.telegram_id, f"{escape(car_title(car))}\n{MILEAGE_NAG}")
                    user.mileage_nag_at = now
            elif (
                reminder.next_mileage is not None
                and car.mileage_km is not None
                and car.mileage_km >= reminder.next_mileage - reminder.warn_km
            ):
                pieces.append(f"пробег около {reminder.next_mileage} км")
                key_parts.append(f"km:{reminder.next_mileage}")
            if reminder.next_date is not None and now >= _aware(reminder.next_date) - timedelta(days=reminder.warn_days):
                pieces.append(f"дата {_aware(reminder.next_date).astimezone().strftime('%d.%m.%Y')}")
                key_parts.append(f"dt:{_aware(reminder.next_date).date().isoformat()}")
            key = "|".join(key_parts)
            if not pieces or key == (reminder.last_sent_key or ""):
                continue
            work = WORK_LABELS.get(reminder.work_code, reminder.work_code)
            text = (
                f"Напоминание: {work}\n"
                f"{escape(car_title(car))}\n"
                f"Подошёл срок: {', '.join(pieces)}.\n"
                "Интервал задан вами. Откройте «Напоминания» и нажмите «Выполнено», когда работа будет сделана."
            )
            if await _send(bot, user.telegram_id, text):
                reminder.last_sent_key = key
        await session.commit()


async def _send(bot: Bot, telegram_id: int, text: str) -> bool:
    try:
        await bot.send_message(telegram_id, text)
        return True
    except TelegramForbiddenError:
        logger.info("Пользователь %s запретил сообщения бота", telegram_id)
        return False
    except Exception:
        logger.exception("Не удалось отправить напоминание")
        return False
