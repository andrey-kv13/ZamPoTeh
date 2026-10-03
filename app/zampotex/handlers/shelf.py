import html

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from zampotex.formatters import shelf_text
from zampotex.keyboards import cancel_inline, cars_keyboard
from zampotex.models import ShelfItem, User
from zampotex.repo import get_car, get_shelf_item, list_cars, list_shelf
from zampotex.states import ShelfFlow
from zampotex.ui import present

router = Router()

STATUSES = (
    ("in_stock", "На складе"),
    ("purchased", "Куплено"),
    ("installed", "Установлено"),
    ("failed", "Вышло из строя"),
    ("written_off", "Списано"),
)


def _current(cars):
    return [car for car in cars if car.ownership == "current"]


async def show_shelf(target, session: AsyncSession, user: User, car_id: int | None = None) -> None:
    cars = _current(await list_cars(session, user.id))
    if not cars:
        await present(target, "Стеллаж привязан к автомобилю. Сначала добавьте машину в гараж.", cars_keyboard([], "caropen"))
        return
    car = None
    if car_id is not None:
        car = await get_car(session, car_id, user.id)
    elif user.active_car_id:
        car = next((item for item in cars if item.id == user.active_car_id), None)
    if car is None and len(cars) == 1:
        car = cars[0]
    if car is None or car.ownership != "current":
        await present(target, "Для какой машины показать стеллаж?", cars_keyboard(cars, "shelf"))
        return
    user.active_car_id = car.id
    items = await list_shelf(session, user.id, car.id)
    buttons = [[InlineKeyboardButton(text=item.title[:40], callback_data=f"shelfopen:{item.id}")] for item in items[:10]]
    buttons.append([InlineKeyboardButton(text="➕ Добавить запчасть", callback_data=f"shelfadd:{car.id}")])
    buttons.append([InlineKeyboardButton(text="В меню", callback_data="nav:menu")])
    await present(target, shelf_text(car, items), InlineKeyboardMarkup(inline_keyboard=buttons))


@router.callback_query(F.data.startswith("shelf:"))
async def shelf_pick(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    await show_shelf(callback, session, user, int(callback.data.split(":")[1]))


@router.callback_query(F.data.startswith("shelfadd:"))
async def shelf_add(callback: CallbackQuery, state: FSMContext) -> None:
    car_id = int(callback.data.split(":")[1])
    await state.set_state(ShelfFlow.title)
    await state.update_data(car_id=car_id)
    await present(
        callback,
        "Как называется запчасть?\nНапример: зеркало левое или масляный фильтр.",
        cancel_inline("nav:cancel"),
    )


@router.message(ShelfFlow.title, F.text)
async def shelf_title(message: Message, state: FSMContext) -> None:
    title = (message.text or "").strip()
    if len(title) < 2:
        await message.answer("Напишите название подробнее.")
        return
    await state.update_data(title=title[:255])
    await state.set_state(ShelfFlow.oem)
    await message.answer(
        "Если знаете артикул, пришлите его. Это пометка для вас, каталогом она не подтверждается.\n"
        "Или нажмите «Пропустить».",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Пропустить", callback_data="shelfskip:oem")],
                [InlineKeyboardButton(text="Отмена", callback_data="nav:cancel")],
            ]
        ),
    )


@router.callback_query(ShelfFlow.oem, F.data == "shelfskip:oem")
async def skip_oem(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(oem=None)
    await state.set_state(ShelfFlow.price)
    await present(callback, "Цена покупки в рублях или «Пропустить».", _price_keyboard())


@router.message(ShelfFlow.oem, F.text)
async def shelf_oem(message: Message, state: FSMContext) -> None:
    await state.update_data(oem=(message.text or "").strip()[:64])
    await state.set_state(ShelfFlow.price)
    await message.answer("Цена покупки в рублях или кнопка «Пропустить».", reply_markup=_price_keyboard())


def _price_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Пропустить", callback_data="shelfskip:price")],
            [InlineKeyboardButton(text="Отмена", callback_data="nav:cancel")],
        ]
    )


@router.callback_query(ShelfFlow.price, F.data == "shelfskip:price")
async def skip_price(callback: CallbackQuery, state: FSMContext, session: AsyncSession, user: User) -> None:
    await _save_shelf(callback, state, session, user, None)


@router.message(ShelfFlow.price, F.text)
async def shelf_price(message: Message, state: FSMContext, session: AsyncSession, user: User) -> None:
    raw = (message.text or "").replace(" ", "")
    if not raw.isdigit():
        await message.answer("Нужно целое число рублей или кнопка «Пропустить».", reply_markup=_price_keyboard())
        return
    await _save_shelf(message, state, session, user, int(raw))


async def _save_shelf(target, state: FSMContext, session: AsyncSession, user: User, price: int | None) -> None:
    data = await state.get_data()
    car = await get_car(session, int(data["car_id"]), user.id)
    await state.clear()
    if car is None:
        await present(target, "Автомобиль не найден.", None)
        return
    item = ShelfItem(
        user_id=user.id,
        car_id=car.id,
        title=data["title"],
        oem=data.get("oem"),
        buy_price=price,
        status="in_stock",
        comment="Добавлено вручную.",
    )
    session.add(item)
    await session.flush()
    await present(target, "Запчасть на стеллаже. Отметьте, что с ней происходит.", _status_keyboard(item.id))


def _status_keyboard(item_id: int) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=label, callback_data=f"st:{item_id}:{code}")] for code, label in STATUSES]
    rows.append([InlineKeyboardButton(text="Удалить запись", callback_data=f"shelfdel:{item_id}")])
    rows.append([InlineKeyboardButton(text="← К стеллажу", callback_data="shelfback")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data.startswith("shelfopen:"))
async def open_item(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    item = await get_shelf_item(session, int(callback.data.split(":")[1]), user.id)
    if item is None:
        await show_shelf(callback, session, user)
        return
    oem = html.escape(item.oem or "не указан")
    price = f"{item.buy_price} ₽" if item.buy_price is not None else "не указана"
    await present(
        callback,
        f"<b>{html.escape(item.title)}</b>\nАртикул: {oem}\nЦена: {price}\n\nВыберите статус. Каталог это не проверяет.",
        _status_keyboard(item.id),
    )


@router.callback_query(F.data.startswith("st:"))
async def set_status(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    _, item_id, code = callback.data.split(":")
    item = await get_shelf_item(session, int(item_id), user.id)
    if item is None:
        await callback.answer("Запись не найдена", show_alert=True)
        return
    item.status = code
    await callback.answer("Статус обновлён")
    await show_shelf(callback, session, user, item.car_id)


@router.callback_query(F.data.startswith("shelfdel:"))
async def delete_item(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    item = await get_shelf_item(session, int(callback.data.split(":")[1]), user.id)
    if item is None:
        await show_shelf(callback, session, user)
        return
    car_id = item.car_id
    await session.delete(item)
    await show_shelf(callback, session, user, car_id)


@router.callback_query(F.data == "shelfback")
async def shelf_back(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    await show_shelf(callback, session, user)
