import html
from datetime import datetime

from zampotex.car_spec import car_spec_rows
from zampotex.maintenance import format_kit_block
from zampotex.marketplace_links import marketplace_url_buttons
from zampotex.models import Car, Reminder, Search, ShelfItem, User
from zampotex.open_sources import OpenReport
from zampotex.parsing import WORK_LABELS, ParsedQuery, side_label
from zampotex.texts import DISCLAIMER, NO_CATALOG_HINT, NO_CATALOG_NO_API, NO_CATALOG_NUMBER
from zampotex.vin_lookup import VinInfo

STATUS_LABELS = {
    "purchased": "Куплено",
    "in_stock": "На складе",
    "installed": "Установлено",
    "failed": "Вышло из строя",
    "written_off": "Списано",
}


def esc(value: object) -> str:
    return html.escape(str(value if value is not None else "—"))


def car_title(car: Car) -> str:
    sold = " · продан" if car.ownership != "current" else ""
    return f"{car.brand} {car.model}, {car.year}{sold}"


def car_card(car: Car, info: VinInfo | None = None) -> str:
    lines = [f"<b>{esc(car_title(car))}</b>", ""]
    for label, value in car_spec_rows(car, info):
        lines.append(f"{esc(label)}: {esc(value)}")
    if car.pr_codes:
        lines.append(f"PR-коды: {esc(car.pr_codes)}")
    lines.extend(
        [
            "",
            "<i>Карточка из гаража и открытых источников по VIN. "
            "Каталожные номера запчастей здесь не подставляются.</i>",
            "",
            "Дополните двигатель и коробку — так меньше уточнений при поиске масла, опор и трансмиссии.",
        ]
    )
    return "\n".join(lines)


def _url_button_rows(pairs: list[tuple[str, str]]) -> list[list]:
    from zampotex.keyboards import InlineKeyboardButton

    rows: list[list] = []
    row: list = []
    for label, url in pairs:
        row.append(InlineKeyboardButton(text=label, url=url))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return rows


def car_keyboard(car: Car):
    from zampotex.keyboards import InlineKeyboardButton, InlineKeyboardMarkup

    rows = []
    if car.ownership == "current":
        rows.append([InlineKeyboardButton(text="🔍 Искать запчасть", callback_data=f"find:{car.id}")])
        rows.append([InlineKeyboardButton(text="🛢 Комплект: замена масла", callback_data=f"cfind:oil:{car.id}")])
    rows.extend(
        [
            [
                InlineKeyboardButton(text="Пробег", callback_data=f"caredit:mileage:{car.id}"),
                InlineKeyboardButton(text="Двигатель и коробка", callback_data=f"caredit:engine:{car.id}"),
            ],
            [
                InlineKeyboardButton(text="Город", callback_data=f"caredit:city:{car.id}"),
                InlineKeyboardButton(text="PR-коды", callback_data=f"caredit:pr:{car.id}"),
            ],
            [InlineKeyboardButton(text="📜 История запросов", callback_data=f"hist:{car.id}")],
        ]
    )
    rows.extend(_url_button_rows(marketplace_url_buttons(car)))
    rows.extend(
        [
            [InlineKeyboardButton(text="Передать автомобиль", callback_data=f"transfer:make:{car.id}")],
            [InlineKeyboardButton(text="🗑 Удалить из гаража", callback_data=f"cardel:{car.id}")],
            [InlineKeyboardButton(text="← К гаражу", callback_data="nav:garage")],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def result_link_keyboard(car: Car, query: str) -> list[list]:
    from zampotex.keyboards import InlineKeyboardButton

    rows = _url_button_rows(marketplace_url_buttons(car, query))
    rows.append([InlineKeyboardButton(text="Обновить карточку VIN", callback_data=f"caropen:{car.id}")])
    return rows


def garage_text(cars: list[Car]) -> str:
    if not cars:
        return (
            "<b>Гараж пуст</b>\n\n"
            "Добавьте машину по VIN — тогда поиск, стеллаж и напоминания будут про этот автомобиль.\n"
            "VIN смотрите в СТС или на табличке кузова. В нём 17 знаков."
        )
    lines = ["<b>Ваш гараж</b>\n", "Выберите автомобиль. Поиск пойдёт только по нему.\n"]
    for index, car in enumerate(cars, start=1):
        city = car.city or "город не указан"
        lines.append(f"{index}. {esc(car_title(car))} · {esc(city)}")
    return "\n".join(lines)


def _order_block(catalog_lines: tuple[str, ...] | None, partsapi_on: bool) -> str:
    if catalog_lines:
        return "\n".join(catalog_lines)
    if not partsapi_on:
        return NO_CATALOG_NO_API
    return NO_CATALOG_NUMBER


def _open_hits_for_user(report: OpenReport) -> list[str]:
    lines: list[str] = []
    for hit in report.hits:
        lines.append(f"• {hit.title}: {hit.text}")
    return lines or []


def result_messages(
    car: Car,
    query: str,
    parsed: ParsedQuery,
    missing: list[str],
    show_maintenance_kit: bool,
    report: OpenReport | None = None,
    catalog_lines: tuple[str, ...] | None = None,
    partsapi_configured: bool = True,
) -> tuple[str, str]:
    if report is None:
        report = OpenReport((), ())
    understood = [
        f"{car.brand} {car.model}, {car.year} · VIN {car.vin}",
        f"Запрос: {query}",
        f"Сторона: {side_label(parsed.side)}",
    ]
    if parsed.articles:
        understood.append("Номера из текста (TecDoc не проверял): " + ", ".join(parsed.articles))

    order_text = _order_block(catalog_lines, partsapi_configured)
    open_lines = _open_hits_for_user(report)

    plain_parts = ["Результат подбора", "", *understood, "", "Можно включать в заказ", order_text]
    if not catalog_lines and not open_lines:
        plain_parts.extend(["", NO_CATALOG_HINT])
    elif open_lines:
        plain_parts.extend(["", "Справочно из открытых баз", *open_lines])

    kit_block = format_kit_block(parsed.intent, car) if show_maintenance_kit else None
    if kit_block:
        plain_parts.extend(["", kit_block])
    if missing:
        plain_parts.extend(["", "Уточните: " + "; ".join(missing)])
    plain_parts.extend(["", DISCLAIMER])
    plain = "\n".join(plain_parts)

    html_text = (
        "<b>Результат подбора</b>\n\n"
        + "\n".join(esc(line) for line in understood)
        + f"\n\n<b>Можно включать в заказ</b>\n{esc(order_text)}"
    )
    if not catalog_lines and not open_lines:
        html_text += f"\n\n{esc(NO_CATALOG_HINT)}"
    elif open_lines:
        html_text += "\n\n<b>Справочно из открытых баз</b>\n" + "\n".join(esc(line) for line in open_lines)
    if kit_block:
        html_text += f"\n\n<b>Комплект работ</b>\n{esc(kit_block)}"
    if missing:
        html_text += "\n\nУточните: " + esc("; ".join(missing))
    html_text += f"\n\n<i>{esc(DISCLAIMER)}</i>"
    return html_text, plain


def history_text(car: Car, rows: list[Search], mine: int) -> str:
    if not rows:
        return (
            f"<b>История {esc(car_title(car))}</b>\n\n"
            "Запросов по этому VIN пока нет.\n"
            "Технический запрос без заметок виден следующему владельцу этого VIN."
        )
    lines = [
        f"<b>История {esc(car_title(car))}</b>",
        "Чужие имя, пробег и заметки здесь не показываются.",
        "",
    ]
    for row in rows:
        moment = row.created_at
        if isinstance(moment, datetime):
            stamp = moment.strftime("%d.%m %H:%M")
        else:
            stamp = "—"
        own = "ваш" if row.user_id == mine else "по VIN"
        hidden = ", скрыт от других" if row.hidden else ""
        status = " · есть справка" if row.status == "open_checked" else ""
        lines.append(f"• {stamp} · {own}{hidden}{status}\n{esc(row.text[:180])}")
    return "\n".join(lines)


def shelf_text(car: Car, items: list[ShelfItem]) -> str:
    if not items:
        return (
            f"<b>Стеллаж · {esc(car_title(car))}</b>\n\n"
            "Запчастей пока нет.\n"
            "Сюда попадают детали, которые вы сохранили сами: купленные, лежащие на полке или уже стоящие на машине."
        )
    lines = [f"<b>Стеллаж · {esc(car_title(car))}</b>\n"]
    for item in items:
        price = f", {item.buy_price} ₽" if item.buy_price is not None else ""
        oem = f", {item.oem}" if item.oem else ""
        lines.append(f"• {esc(item.title)}{esc(oem)} — {esc(STATUS_LABELS.get(item.status, item.status))}{esc(price)}")
    return "\n".join(lines)


def reminders_text(items: list[tuple[Reminder, Car]]) -> str:
    if not items:
        return (
            "<b>Напоминаний нет</b>\n\n"
            "Можно поставить своё: по пробегу, по дате или по обоим сразу.\n"
            "Заводской интервал бот назовёт только если он заведён в базе. Сейчас база регламентов пустая, "
            "поэтому срок из воздуха не появится."
        )
    lines = ["<b>Напоминания</b>\n", "Предупреждение придёт за 1000 км или за 14 дней.\n"]
    for reminder, car in items:
        when = []
        if reminder.next_mileage is not None:
            when.append(f"{reminder.next_mileage} км")
        if reminder.next_date is not None:
            when.append(reminder.next_date.strftime("%d.%m.%Y"))
        lines.append(
            f"• {esc(WORK_LABELS.get(reminder.work_code, reminder.work_code))} · {esc(car_title(car))}\n"
            f"  {esc(', '.join(when) or 'срок не задан')} · интервал задан пользователем"
        )
    return "\n".join(lines)


def profile_text(user: User, used: int, limit: int, admin: bool) -> str:
    mode = "тяжёлые условия" if user.interval_profile == "severe" else "заводской интервал"
    admin_line = "\nВам доступен раздел администратора: /admin" if admin else ""
    return (
        "<b>Профиль</b>\n\n"
        f"Имя: {esc(user.telegram_name)}\n"
        f"Город: {esc(user.city)}\n"
        f"Режим обслуживания: {mode}\n"
        f"Поисков сегодня, которые тратят лимит: {used} из {limit}\n"
        "Лимит тратится только когда запускается внешняя проверка каталога. "
        "Сейчас адаптер выключен, поэтому отказы каталога лимит не уменьшают."
        f"{admin_line}\n\n"
        "Тяжёлые условия сокращают срок только при отдельной норме в базе. "
        "Пока нормы нет, выбранный режим ничего не укорачивает."
    )
