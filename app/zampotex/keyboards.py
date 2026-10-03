from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from zampotex.parsing import CITIES, WORKS

SEARCH = "🔍 Найти запчасть"
GARAGE = "🚗 Мой гараж"
SHELF = "📦 Стеллаж"
REMINDERS = "🔔 Напоминания"
HISTORY = "📜 История"
PROFILE = "👤 Профиль"

MENU_TEXTS = {SEARCH, GARAGE, SHELF, REMINDERS, HISTORY, PROFILE}

PAGE = 8


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=SEARCH)],
            [KeyboardButton(text=GARAGE), KeyboardButton(text=SHELF)],
            [KeyboardButton(text=REMINDERS), KeyboardButton(text=HISTORY)],
            [KeyboardButton(text=PROFILE)],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Напишите деталь или выберите раздел",
    )


def consent_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Принимаю", callback_data="consent:yes")],
            [InlineKeyboardButton(text="❌ Не принимаю", callback_data="consent:no")],
        ]
    )


def cancel_inline(back: str = "nav:menu") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Отмена", callback_data=back)],
        ]
    )


def city_keyboard(page: int, prefix: str) -> InlineKeyboardMarkup:
    start = page * PAGE
    rows: list[list[InlineKeyboardButton]] = []
    for index, city in enumerate(CITIES[start : start + PAGE], start=start):
        rows.append([InlineKeyboardButton(text=city, callback_data=f"{prefix}:{index}")])
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="← Назад", callback_data=f"{prefix}pg:{page - 1}"))
    if start + PAGE < len(CITIES):
        nav.append(InlineKeyboardButton(text="Дальше →", callback_data=f"{prefix}pg:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="Ввести свой город", callback_data=f"{prefix}:custom")])
    rows.append([InlineKeyboardButton(text="Отмена", callback_data="nav:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def years_keyboard(years: list[int]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=str(year), callback_data=f"year:{year}")] for year in years]
    rows.append([InlineKeyboardButton(text="Другой год", callback_data="year:manual")])
    rows.append([InlineKeyboardButton(text="Отмена", callback_data="nav:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def brand_keyboard(brand: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"Да, {brand}", callback_data="brand:yes")],
            [InlineKeyboardButton(text="Нет, введу сам", callback_data="brand:no")],
            [InlineKeyboardButton(text="Отмена", callback_data="nav:cancel")],
        ]
    )


def confirm_car_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Сохранить автомобиль", callback_data="carnew:save")],
            [InlineKeyboardButton(text="Начать заново", callback_data="carnew:restart")],
            [InlineKeyboardButton(text="Отмена", callback_data="nav:cancel")],
        ]
    )


def side_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Левая", callback_data="side:left"),
                InlineKeyboardButton(text="Правая", callback_data="side:right"),
            ],
            [InlineKeyboardButton(text="Не знаю", callback_data="side:unknown")],
            [InlineKeyboardButton(text="Отмена", callback_data="nav:cancel")],
        ]
    )


def skip_keyboard(callback: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Не знаю", callback_data=callback)],
            [InlineKeyboardButton(text="Отмена", callback_data="nav:cancel")],
        ]
    )


def works_keyboard() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=label, callback_data=f"work:{code}")] for code, label in WORKS]
    rows.append([InlineKeyboardButton(text="Отмена", callback_data="nav:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def cars_keyboard(cars, prefix: str) -> InlineKeyboardMarkup:
    rows = []
    for car in cars:
        title = f"{car.brand} {car.model}, {car.year}"
        if car.ownership != "current":
            title = f"{title} · продан"
        rows.append([InlineKeyboardButton(text=title, callback_data=f"{prefix}:{car.id}")])
    if prefix == "caropen":
        rows.append([InlineKeyboardButton(text="➕ Добавить автомобиль", callback_data="carnew:start")])
        rows.append([InlineKeyboardButton(text="Принять автомобиль по коду", callback_data="transfer:claim")])
    rows.append([InlineKeyboardButton(text="В меню", callback_data="nav:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
