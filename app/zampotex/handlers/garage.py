import secrets
from datetime import datetime

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from zampotex.formatters import car_card, car_keyboard, esc, garage_text
from zampotex.keyboards import (
    cancel_inline,
    cars_keyboard,
    city_keyboard,
    confirm_car_keyboard,
    years_keyboard,
)
from zampotex.models import Car, User
from zampotex.parsing import CITIES, find_vin, year_hints
from zampotex.vin_lookup import explain, lookup_vin
from zampotex.repo import count_cars, create_transfer, delete_car, get_car, list_cars
from zampotex.states import AddCar, EditCar, TransferFlow
from zampotex.texts import CAR_LIMIT, CITY_HINT, CITY_INPUT, TRANSFER_HINT, VIN_BAD
from zampotex.ui import present

router = Router()


async def show_garage(target: Message | CallbackQuery, session: AsyncSession, user: User) -> None:
    cars = await list_cars(session, user.id)
    await present(target, garage_text(cars), cars_keyboard(cars, "caropen"))


async def show_car(target: Message | CallbackQuery, car: Car) -> None:
    if isinstance(target, CallbackQuery):
        await target.answer("Обновляю открытые данные по VIN…", show_alert=False)
    info = await lookup_vin(car.vin, datetime.now().year)
    await present(target, car_card(car, info), car_keyboard(car))


@router.callback_query(F.data == "carnew:start")
async def add_car_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession, user: User) -> None:
    if await count_cars(session, user.id) >= 10:
        await present(callback, CAR_LIMIT, cancel_inline("nav:garage"))
        return
    await state.set_state(AddCar.vin)
    await present(
        callback,
        "Введите VIN из 17 знаков.\n"
        "Он есть в СТС и на табличке кузова.\n"
        "Пример: 17 латинских букв и цифр из СТС, без I, O и Q.\n\n"
        "Пробелы можно оставить — я уберу их сам.",
        cancel_inline("nav:garage"),
    )


@router.message(AddCar.vin)
async def add_car_vin(message: Message, state: FSMContext, session: AsyncSession, user: User) -> None:
    vin = find_vin(message.text or "")
    if vin is None:
        await message.answer(VIN_BAD, reply_markup=cancel_inline("nav:garage"))
        return
    await accept_vin(message, state, session, user, vin)


async def accept_vin(message: Message, state: FSMContext, session: AsyncSession, user: User, vin: str) -> None:
    if await count_cars(session, user.id) >= 10:
        await message.answer(CAR_LIMIT, reply_markup=cancel_inline("nav:garage"))
        return
    await state.set_state(AddCar.brand)
    await state.update_data(vin=vin)
    progress = await message.answer("Ищу этот VIN в открытых базах…")
    info = await lookup_vin(vin, datetime.now().year)
    await state.update_data(
        brand_hint=info.brand,
        model_hint=info.model,
        year_hint=info.year,
        bmw_model_year_code=info.bmw_model_year_code,
    )
    await progress.edit_text(explain(info), reply_markup=_vin_keyboard())


def _vin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Да, это он", callback_data="vinok:yes")],
            [InlineKeyboardButton(text="Нет, введу сам", callback_data="vinok:no")],
            [InlineKeyboardButton(text="Отмена", callback_data="nav:cancel")],
        ]
    )


async def _continue_known(target: Message | CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if data.get("brand_hint") and not data.get("brand"):
        await state.update_data(brand=data["brand_hint"])
    if data.get("model_hint") and not data.get("model"):
        await state.update_data(model=data["model_hint"])
    if data.get("year_hint") and not data.get("year"):
        await state.update_data(year=int(data["year_hint"]))
    data = await state.get_data()
    if not data.get("brand"):
        await state.set_state(AddCar.brand)
        await present(target, "Напишите марку, например: Volkswagen", cancel_inline("nav:garage"))
        return
    if not data.get("model"):
        await state.set_state(AddCar.model)
        await present(target, "Напишите модель так, как в СТС.", cancel_inline("nav:garage"))
        return
    if not data.get("year"):
        hints = year_hints(data["vin"], datetime.now().year)
        await state.set_state(AddCar.year)
        if data.get("bmw_model_year_code") and not hints:
            code = int(data["bmw_model_year_code"])
            await present(
                target,
                f"В VIN код BMW <b>{code}</b> — это модельный год (поколение), "
                "а не всегда год выпуска с конвейера.\n"
                "Напишите год выпуска из СТС, например <b>2015</b>.",
                cancel_inline("nav:garage"),
            )
            return
        if hints:
            listed = " или ".join(str(year) for year in hints)
            await present(target, f"По VIN год может быть {listed}. Выберите кнопкой или введите свой.", years_keyboard(hints))
            return
        await present(target, "Напишите год выпуска четырьмя цифрами, например 2010.", cancel_inline("nav:garage"))
        return
    await _ask_city(target, state)


@router.callback_query(AddCar.brand, F.data == "vinok:yes")
async def vin_confirmed(callback: CallbackQuery, state: FSMContext) -> None:
    await _continue_known(callback, state)


@router.callback_query(AddCar.brand, F.data == "vinok:no")
async def vin_rejected(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(
        brand_hint=None,
        model_hint=None,
        year_hint=None,
        bmw_model_year_code=None,
        brand=None,
        model=None,
        year=None,
    )
    await present(callback, "Напишите марку, например: Volkswagen", cancel_inline("nav:garage"))


@router.callback_query(AddCar.brand, F.data == "brand:yes")
async def brand_yes(callback: CallbackQuery, state: FSMContext) -> None:
    await _continue_known(callback, state)


@router.callback_query(AddCar.brand, F.data == "brand:no")
async def brand_no(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(brand_hint=None)
    await present(callback, "Напишите марку, например: Volkswagen", cancel_inline("nav:garage"))


@router.message(AddCar.brand)
async def brand_text(message: Message, state: FSMContext) -> None:
    brand = (message.text or "").strip()
    if len(brand) < 2:
        await message.answer("Марка слишком короткая. Напишите её целиком.", reply_markup=cancel_inline("nav:garage"))
        return
    await state.update_data(brand=brand[:80])
    await state.set_state(AddCar.model)
    await message.answer("Напишите модель так, как в СТС.", reply_markup=cancel_inline("nav:garage"))


@router.message(AddCar.model)
async def model_text(message: Message, state: FSMContext) -> None:
    model = (message.text or "").strip()
    if len(model) < 1:
        await message.answer("Напишите модель текстом.", reply_markup=cancel_inline("nav:garage"))
        return
    await state.update_data(model=model[:80])
    data = await state.get_data()
    hints = year_hints(data["vin"], datetime.now().year)
    await state.set_state(AddCar.year)
    if len(hints) >= 2:
        listed = " или ".join(str(year) for year in hints)
        await message.answer(
            f"По VIN год может быть {listed}. Выберите кнопкой или введите свой.",
            reply_markup=years_keyboard(hints),
        )
        return
    if len(hints) == 1:
        await message.answer(
            f"По VIN год похож на {hints[0]}. Можно нажать его или написать другой.",
            reply_markup=years_keyboard(hints),
        )
        return
    await message.answer("Напишите год выпуска четырьмя цифрами, например 2010.", reply_markup=cancel_inline("nav:garage"))


async def _ask_city(target: Message | CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AddCar.city)
    await present(target, "В каком городе эксплуатируется автомобиль?\n" + CITY_HINT, city_keyboard(0, "citynew"))


@router.callback_query(AddCar.year, F.data.startswith("year:"))
async def year_button(callback: CallbackQuery, state: FSMContext) -> None:
    value = callback.data.split(":", 1)[1]
    if value == "manual":
        await present(callback, "Напишите год выпуска четырьмя цифрами.", cancel_inline("nav:garage"))
        return
    await state.update_data(year=int(value))
    await _ask_city(callback, state)


@router.message(AddCar.year)
async def year_text(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer("Нужны четыре цифры, например 2010.", reply_markup=cancel_inline("nav:garage"))
        return
    year = int(raw)
    current = datetime.now().year
    if year < 1950 or year > current + 1:
        await message.answer(f"Год должен быть от 1950 до {current + 1}.", reply_markup=cancel_inline("nav:garage"))
        return
    await state.update_data(year=year)
    await _ask_city(message, state)


@router.callback_query(AddCar.city, F.data.startswith("citynewpg:"))
async def city_page(callback: CallbackQuery) -> None:
    page = int(callback.data.split(":")[1])
    await present(callback, CITY_HINT, city_keyboard(page, "citynew"))


@router.callback_query(AddCar.city, F.data.startswith("citynew:"))
async def city_pick(callback: CallbackQuery, state: FSMContext, session: AsyncSession, user: User) -> None:
    value = callback.data.split(":", 1)[1]
    if value == "custom":
        await present(callback, CITY_INPUT, cancel_inline("nav:garage"))
        return
    city = CITIES[int(value)]
    await state.update_data(city=city)
    await _confirm(callback, state)


@router.message(AddCar.city)
async def city_text(message: Message, state: FSMContext) -> None:
    city = (message.text or "").strip()
    if len(city) < 2:
        await message.answer(CITY_INPUT, reply_markup=city_keyboard(0, "citynew"))
        return
    await state.update_data(city=city[:120])
    await _confirm(message, state)


async def _confirm(target: Message | CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    text = (
        "<b>Проверьте карточку</b>\n\n"
        f"VIN: <code>{data['vin']}</code>\n"
        f"Марка: {esc(data['brand'])}\n"
        f"Модель: {esc(data['model'])}\n"
        f"Год: {esc(data['year'])}\n"
        f"Город: {esc(data['city'])}\n\n"
        "Двигатель и коробку можно добавить сразу после сохранения."
    )
    await present(target, text, confirm_car_keyboard())


@router.callback_query(F.data == "carnew:restart")
async def restart(callback: CallbackQuery, state: FSMContext, session: AsyncSession, user: User) -> None:
    await state.clear()
    await add_car_start(callback, state, session, user)


@router.callback_query(F.data == "carnew:save")
async def save_car(callback: CallbackQuery, state: FSMContext, session: AsyncSession, user: User) -> None:
    data = await state.get_data()
    if not all(key in data for key in ("vin", "brand", "model", "year", "city")):
        await present(callback, "Данных не хватает. Начнём добавление заново.", cancel_inline("nav:garage"))
        await state.clear()
        return
    if await count_cars(session, user.id) >= 10:
        await present(callback, CAR_LIMIT, cancel_inline("nav:garage"))
        return
    car = Car(
        user_id=user.id,
        vin=data["vin"],
        brand=data["brand"],
        model=data["model"],
        year=int(data["year"]),
        city=data["city"],
    )
    session.add(car)
    await session.flush()
    user.active_car_id = car.id
    if user.city is None:
        user.city = car.city
    await state.clear()
    await present(
        callback,
        "Автомобиль сохранён. Теперь можно искать запчасть или дополнить двигатель и коробку.\n\n" + car_card(car),
        car_keyboard(car),
    )


@router.callback_query(F.data.startswith("caropen:"))
async def open_car(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    car = await get_car(session, int(callback.data.split(":")[1]), user.id)
    if car is None:
        await show_garage(callback, session, user)
        return
    user.active_car_id = car.id
    await show_car(callback, car)


@router.callback_query(F.data.startswith("cardel:"))
async def ask_delete(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    car = await get_car(session, int(callback.data.split(":")[1]), user.id)
    if car is None:
        await show_garage(callback, session, user)
        return
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Удалить", callback_data=f"cardelok:{car.id}")],
            [InlineKeyboardButton(text="Оставить", callback_data=f"caropen:{car.id}")],
        ]
    )
    await present(callback, f"Удалить {car.brand} {car.model} из гаража? Стеллаж и напоминания этой машины тоже исчезнут.", markup)


@router.callback_query(F.data.startswith("cardelok:"))
async def do_delete(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    car = await get_car(session, int(callback.data.split(":")[1]), user.id)
    if car is not None:
        if user.active_car_id == car.id:
            user.active_car_id = None
        await delete_car(session, car)
    await show_garage(callback, session, user)


@router.callback_query(F.data.startswith("caredit:mileage:"))
async def edit_mileage(callback: CallbackQuery, state: FSMContext, session: AsyncSession, user: User) -> None:
    car = await get_car(session, int(callback.data.split(":")[2]), user.id)
    if car is None or car.ownership != "current":
        await show_garage(callback, session, user)
        return
    await state.set_state(EditCar.mileage)
    await state.update_data(car_id=car.id)
    await present(callback, "Введите текущий пробег в километрах, только число.", cancel_inline(f"caropen:{car.id}"))


@router.message(EditCar.mileage)
async def save_mileage(message: Message, state: FSMContext, session: AsyncSession, user: User) -> None:
    raw = (message.text or "").replace(" ", "")
    if not raw.isdigit() or int(raw) > 2_000_000:
        await message.answer("Нужно целое число километров, например 185000.")
        return
    data = await state.get_data()
    car = await get_car(session, int(data["car_id"]), user.id)
    if car is None:
        await state.clear()
        await show_garage(message, session, user)
        return
    from datetime import timezone

    car.mileage_km = int(raw)
    car.mileage_at = datetime.now(timezone.utc)
    await state.clear()
    await message.answer("Пробег обновлён.")
    await show_car(message, car)


@router.callback_query(F.data.startswith("caredit:engine:"))
async def edit_engine(callback: CallbackQuery, state: FSMContext, session: AsyncSession, user: User) -> None:
    car = await get_car(session, int(callback.data.split(":")[2]), user.id)
    if car is None:
        await show_garage(callback, session, user)
        return
    await state.set_state(EditCar.engine)
    await state.update_data(car_id=car.id)
    await present(
        callback,
        "Напишите двигатель и коробку одним сообщением.\n"
        "Пример: <code>CBAB 140 л.с. АКПП MKD</code>\n"
        "Если чего-то не знаете, эту часть просто пропустите.",
        cancel_inline(f"caropen:{car.id}"),
    )


@router.message(EditCar.engine)
async def save_engine(message: Message, state: FSMContext, session: AsyncSession, user: User) -> None:
    from zampotex.parsing import parse_engine_line

    parsed = parse_engine_line(message.text or "")
    data = await state.get_data()
    car = await get_car(session, int(data["car_id"]), user.id)
    if car is None:
        await state.clear()
        return
    if parsed["engine_code"]:
        car.engine_code = str(parsed["engine_code"])
    if parsed["power_hp"]:
        car.power_hp = int(parsed["power_hp"])
    if parsed["gearbox"]:
        car.gearbox = str(parsed["gearbox"])
    if parsed["gearbox_code"]:
        car.gearbox_code = str(parsed["gearbox_code"])
    await state.clear()
    if not any(parsed.values()):
        await message.answer("Не разобрал ни код двигателя, ни коробку. Пример: CBAB 140 л.с. АКПП")
        return
    await message.answer("Данные двигателя и коробки сохранил.")
    await show_car(message, car)


@router.callback_query(F.data.startswith("caredit:pr:"))
async def edit_pr(callback: CallbackQuery, state: FSMContext, session: AsyncSession, user: User) -> None:
    car = await get_car(session, int(callback.data.split(":")[2]), user.id)
    if car is None:
        await show_garage(callback, session, user)
        return
    await state.set_state(EditCar.pr)
    await state.update_data(car_id=car.id)
    await present(
        callback,
        "Введите PR-коды с наклейки в багажнике или сервисной книжке.\n"
        "Фото можно прислать, но текст с него сам не прочитается: распознавание не подключено.",
        cancel_inline(f"caropen:{car.id}"),
    )


@router.message(EditCar.pr)
async def save_pr(message: Message, state: FSMContext, session: AsyncSession, user: User) -> None:
    data = await state.get_data()
    car = await get_car(session, int(data["car_id"]), user.id)
    if car is None:
        await state.clear()
        return
    car.pr_codes = (message.text or "").strip()[:1000]
    await state.clear()
    await message.answer("PR-коды записал после вашего подтверждения текстом.")
    await show_car(message, car)


@router.callback_query(F.data.startswith("caredit:city:"))
async def edit_city(callback: CallbackQuery, state: FSMContext, session: AsyncSession, user: User) -> None:
    car = await get_car(session, int(callback.data.split(":")[2]), user.id)
    if car is None:
        await show_garage(callback, session, user)
        return
    await state.set_state(EditCar.city)
    await state.update_data(car_id=car.id)
    await present(callback, "Выберите город автомобиля.", city_keyboard(0, "citycar"))


@router.callback_query(EditCar.city, F.data.startswith("citycarpg:"))
async def edit_city_page(callback: CallbackQuery) -> None:
    page = int(callback.data.split(":")[1])
    await present(callback, CITY_HINT, city_keyboard(page, "citycar"))


@router.callback_query(EditCar.city, F.data.startswith("citycar:"))
async def edit_city_pick(callback: CallbackQuery, state: FSMContext, session: AsyncSession, user: User) -> None:
    value = callback.data.split(":", 1)[1]
    if value == "custom":
        await present(callback, CITY_INPUT, cancel_inline("nav:garage"))
        return
    await _set_city(callback, state, session, user, CITIES[int(value)])


@router.message(EditCar.city)
async def edit_city_text(message: Message, state: FSMContext, session: AsyncSession, user: User) -> None:
    city = (message.text or "").strip()
    if len(city) < 2:
        await message.answer(CITY_INPUT)
        return
    await _set_city(message, state, session, user, city[:120])


async def _set_city(target, state: FSMContext, session: AsyncSession, user: User, city: str) -> None:
    data = await state.get_data()
    car = await get_car(session, int(data["car_id"]), user.id)
    await state.clear()
    if car is None:
        await show_garage(target, session, user)
        return
    car.city = city
    await show_car(target, car)


@router.callback_query(F.data.startswith("transfer:make:"))
async def make_transfer(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    car = await get_car(session, int(callback.data.split(":")[2]), user.id)
    if car is None:
        await show_garage(callback, session, user)
        return
    code = secrets.token_hex(3).upper()
    await create_transfer(session, car.id, code)
    await present(
        callback,
        f"Код передачи: <code>{code}</code>\n{TRANSFER_HINT}\n"
        "Новому владельцу попадут марка, модель, VIN и город. Пробег, заметки и стеллаж останутся у вас.",
        car_keyboard(car),
    )


@router.callback_query(F.data == "transfer:claim")
async def claim_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(TransferFlow.code)
    await present(callback, "Введите код из 6 символов, который прислал текущий владелец.", cancel_inline("nav:garage"))


@router.message(TransferFlow.code)
async def claim_code(message: Message, state: FSMContext, session: AsyncSession, user: User) -> None:
    from zampotex.repo import claim_transfer

    code = (message.text or "").strip().upper()
    car = await claim_transfer(session, code, user)
    await state.clear()
    if car is None:
        await message.answer("Код не найден, уже использован или у вас уже 10 автомобилей.")
        await show_garage(message, session, user)
        return
    await message.answer("Автомобиль добавлен в ваш гараж. Личные записи прежнего владельца не переносились.")
    await show_car(message, car)
