from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from zampotex.formatters import car_title, esc, reminders_text
from zampotex.keyboards import cars_keyboard, works_keyboard
from zampotex.models import Reminder, User
from zampotex.parsing import WORK_LABELS
from zampotex.repo import get_car, get_reminder, list_cars, list_reminders
from zampotex.states import RemindFlow
from zampotex.texts import REGULATION_ABSENT
from zampotex.ui import present

router = Router()
MOSCOW = ZoneInfo("Europe/Moscow")


def _alive(cars):
    return [car for car in cars if car.ownership == "current"]


async def show_reminders(target, session: AsyncSession, user: User) -> None:
    rows = []
    cars = {car.id: car for car in await list_cars(session, user.id)}
    for reminder in await list_reminders(session, user.id):
        car = cars.get(reminder.car_id)
        if car is not None:
            rows.append((reminder, car))
    buttons = []
    for reminder, car in rows:
        label = WORK_LABELS.get(reminder.work_code, reminder.work_code)
        buttons.append(
            [InlineKeyboardButton(text=f"Выполнено · {label}", callback_data=f"remdone:{reminder.id}")]
        )
        buttons.append([InlineKeyboardButton(text=f"Отключить · {label}", callback_data=f"remoff:{reminder.id}")])
    buttons.append([InlineKeyboardButton(text="➕ Новое напоминание", callback_data="remnew")])
    buttons.append([InlineKeyboardButton(text="В меню", callback_data="nav:menu")])
    await present(target, reminders_text(rows), InlineKeyboardMarkup(inline_keyboard=buttons))


@router.callback_query(F.data == "remnew")
async def rem_new(callback: CallbackQuery, state: FSMContext, session: AsyncSession, user: User) -> None:
    cars = _alive(await list_cars(session, user.id))
    if not cars:
        await present(callback, "Сначала добавьте автомобиль в гараж.", cars_keyboard([], "caropen"))
        return
    if len(cars) == 1:
        await state.update_data(car_id=cars[0].id)
        await state.set_state(RemindFlow.pick_car)
        await present(callback, REGULATION_ABSENT + "\n\nКакую работу напомнить?", works_keyboard())
        return
    await present(callback, "Для какой машины поставить напоминание?", cars_keyboard(cars, "remcar"))


@router.callback_query(F.data.startswith("remcar:"))
async def rem_car(callback: CallbackQuery, state: FSMContext, session: AsyncSession, user: User) -> None:
    car = await get_car(session, int(callback.data.split(":")[1]), user.id)
    if car is None or car.ownership != "current":
        await show_reminders(callback, session, user)
        return
    await state.update_data(car_id=car.id)
    await state.set_state(RemindFlow.pick_car)
    await present(callback, REGULATION_ABSENT + "\n\nКакую работу напомнить?", works_keyboard())


@router.callback_query(RemindFlow.pick_car, F.data.startswith("work:"))
async def rem_work(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(work_code=callback.data.split(":", 1)[1])
    await state.set_state(RemindFlow.mileage)
    await present(
        callback,
        "При каком пробеге напомнить?\nНапишите число километров или нажмите «Без пробега».",
        InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Без пробега", callback_data="remskip:km")],
                [InlineKeyboardButton(text="Отмена", callback_data="nav:cancel")],
            ]
        ),
    )


@router.callback_query(RemindFlow.mileage, F.data == "remskip:km")
async def skip_km(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(next_mileage=None)
    await _ask_date(callback, state)


@router.message(RemindFlow.mileage, F.text)
async def rem_km(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").replace(" ", "")
    if not raw.isdigit() or int(raw) > 2_000_000:
        await message.answer("Нужно число километров, например 200000, или кнопка «Без пробега».")
        return
    await state.update_data(next_mileage=int(raw))
    await _ask_date(message, state)


async def _ask_date(target, state: FSMContext) -> None:
    await state.set_state(RemindFlow.date)
    await present(
        target,
        "Какого числа напомнить? Формат ДД.ММ.ГГГГ.\nИли нажмите «Без даты», если достаточно пробега.",
        InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Без даты", callback_data="remskip:date")],
                [InlineKeyboardButton(text="Отмена", callback_data="nav:cancel")],
            ]
        ),
    )


@router.callback_query(RemindFlow.date, F.data == "remskip:date")
async def skip_date(callback: CallbackQuery, state: FSMContext, session: AsyncSession, user: User) -> None:
    await _save_reminder(callback, state, session, user, None)


@router.message(RemindFlow.date, F.text)
async def rem_date(message: Message, state: FSMContext, session: AsyncSession, user: User) -> None:
    parsed = _parse_date(message.text or "")
    if parsed is None:
        await message.answer("Дата в формате ДД.ММ.ГГГГ, например 15.04.2027.")
        return
    await _save_reminder(message, state, session, user, parsed)


def _parse_date(value: str) -> datetime | None:
    for fmt in ("%d.%m.%Y", "%d.%m.%y"):
        try:
            moment = datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
        return moment.replace(tzinfo=MOSCOW)

    return None


async def _save_reminder(target, state: FSMContext, session: AsyncSession, user: User, next_date: datetime | None) -> None:
    data = await state.get_data()
    await state.clear()
    if data.get("next_mileage") is None and next_date is None:
        await present(target, "Нужен пробег или дата. Напоминание без срока не создаю.", None)
        return
    car = await get_car(session, int(data["car_id"]), user.id)
    if car is None:
        await present(target, "Автомобиль не найден.", None)
        return
    interval = None
    if data.get("next_mileage") is not None and car.mileage_km is not None and data["next_mileage"] > car.mileage_km:
        interval = data["next_mileage"] - car.mileage_km
    session.add(
        Reminder(
            user_id=user.id,
            car_id=car.id,
            work_code=data.get("work_code", "other"),
            basis="user_stated",
            next_mileage=data.get("next_mileage"),
            next_date=next_date,
            interval_km=interval,
        )
    )
    await present(
        target,
        f"Напоминание для {esc(car_title(car))} сохранено.\n"
        "Оно помечено как интервал, заданный вами. Заводскую норму бот не подставлял.",
        InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="К напоминаниям", callback_data="remlist")]]),
    )


@router.callback_query(F.data == "remlist")
async def rem_list(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    await show_reminders(callback, session, user)


@router.callback_query(F.data.startswith("remoff:"))
async def rem_off(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    reminder = await get_reminder(session, int(callback.data.split(":")[1]), user.id)
    if reminder is not None:
        reminder.active = False
    await show_reminders(callback, session, user)


@router.callback_query(F.data.startswith("remdone:"))
async def rem_done(callback: CallbackQuery, state: FSMContext, session: AsyncSession, user: User) -> None:
    reminder = await get_reminder(session, int(callback.data.split(":")[1]), user.id)
    if reminder is None:
        await show_reminders(callback, session, user)
        return
    await state.set_state(RemindFlow.done_mileage)
    await state.update_data(reminder_id=reminder.id)
    await present(callback, "Введите текущий пробег. От него посчитаю следующий срок, если интервал известен.", None)


@router.message(RemindFlow.done_mileage, F.text)
async def done_mileage(message: Message, state: FSMContext, session: AsyncSession, user: User) -> None:
    raw = (message.text or "").replace(" ", "")
    if not raw.isdigit():
        await message.answer("Нужен текущий пробег числом.")
        return
    data = await state.get_data()
    reminder = await get_reminder(session, int(data["reminder_id"]), user.id)
    car = await get_car(session, reminder.car_id, user.id) if reminder else None
    if reminder is None or car is None:
        await state.clear()
        await show_reminders(message, session, user)
        return
    car.mileage_km = int(raw)
    car.mileage_at = datetime.now(timezone.utc)
    if reminder.interval_km:
        reminder.next_mileage = car.mileage_km + reminder.interval_km
        reminder.last_sent_key = None
        await state.clear()
        await message.answer(
            f"Отметил выполнение. Следующее напоминание около {reminder.next_mileage} км. "
            "Срок задан вашим интервалом, не заводским регламентом."
        )
        await show_reminders(message, session, user)
        return
    await state.set_state(RemindFlow.done_next)
    await message.answer("Интервал в километрах не был задан. Напишите следующий пробег или дату ДД.ММ.ГГГГ.")


@router.message(RemindFlow.done_next, F.text)
async def done_next(message: Message, state: FSMContext, session: AsyncSession, user: User) -> None:
    data = await state.get_data()
    reminder = await get_reminder(session, int(data["reminder_id"]), user.id)
    if reminder is None:
        await state.clear()
        return
    raw = (message.text or "").strip()
    compact = raw.replace(" ", "")
    if compact.isdigit():
        reminder.next_mileage = int(compact)
        reminder.last_sent_key = None
    else:
        parsed = _parse_date(raw)
        if parsed is None:
            await message.answer("Нужен пробег или дата ДД.ММ.ГГГГ.")
            return
        reminder.next_date = parsed
        reminder.last_sent_key = None
    await state.clear()
    await message.answer("Следующая точка напоминания сохранена.")
    await show_reminders(message, session, user)


def due_key(reminder: Reminder, now: datetime) -> str | None:
    parts = []
    if reminder.next_mileage is not None:
        parts.append(f"km:{reminder.next_mileage}")
    if reminder.next_date is not None and now >= _aware(reminder.next_date) - timedelta(days=reminder.warn_days):
        parts.append(f"dt:{_aware(reminder.next_date).date().isoformat()}")
    return "|".join(parts) or None


def _aware(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment
