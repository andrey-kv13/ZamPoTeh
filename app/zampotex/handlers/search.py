import asyncio

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from zampotex.files import store_photo
from zampotex.formatters import history_text, result_link_keyboard, result_messages
from zampotex.keyboards import cars_keyboard, side_keyboard, skip_keyboard
from zampotex.models import Car, Search, ShelfItem, User
from zampotex.open_sources import search_open_parts
from zampotex.parts_catalog import search_catalog_lines
from zampotex.partsapi_client import catalog_api_configured
from zampotex.parsing import parse_engine_line, parse_query
from zampotex.pdfexport import write_pdf
from zampotex.repo import get_car, get_search, history_for_car, list_cars
from zampotex.states import SearchFlow
from zampotex.texts import NO_CARS_SEARCH, PHOTO_SAVED, VOICE_UNSUPPORTED
from zampotex.ui import present

router = Router()
SEARCH_STATES = (SearchFlow.text, SearchFlow.side, SearchFlow.engine, SearchFlow.gearbox, SearchFlow.stabilizer)


async def _catalog_for_search(vin: str, text: str, intent: str) -> tuple[tuple[str, ...], bool]:
    configured = catalog_api_configured()
    if not configured:
        return (), False
    lines = await asyncio.to_thread(search_catalog_lines, vin, text, intent)
    return lines, True


def result_keyboard(
    search_id: int,
    hidden: bool,
    car: Car | None = None,
    query: str | None = None,
) -> InlineKeyboardMarkup:
    hide = "Снова показать в истории VIN" if hidden else "Скрыть из общей истории"
    rows = [
        [InlineKeyboardButton(text="Повторить проверку", callback_data=f"srep:{search_id}")],
        [InlineKeyboardButton(text=hide, callback_data=f"shide:{search_id}")],
        [InlineKeyboardButton(text="Сохранить формулировку в стеллаж", callback_data=f"sshelf:{search_id}")],
        [InlineKeyboardButton(text="Скачать PDF", callback_data=f"spdf:{search_id}")],
    ]
    if car is not None and query:
        rows.extend(result_link_keyboard(car, query))
    rows.extend(
        [
            [InlineKeyboardButton(text="Новый запрос", callback_data="find:again")],
            [InlineKeyboardButton(text="В меню", callback_data="nav:menu")],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def current_cars(session: AsyncSession, user: User) -> list[Car]:
    return [car for car in await list_cars(session, user.id) if car.ownership == "current"]


PRESET_QUERIES = {
    "oil": "замена моторного масла и масляного фильтра по регламенту",
}


@router.callback_query(F.data.startswith("cfind:"))
async def car_preset_search(callback: CallbackQuery, state: FSMContext, session: AsyncSession, user: User) -> None:
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("Неизвестный шаблон", show_alert=True)
        return
    kind, car_id_raw = parts[1], parts[2]
    text = PRESET_QUERIES.get(kind)
    if text is None:
        await callback.answer("Шаблон не найден", show_alert=True)
        return
    car = await get_car(session, int(car_id_raw), user.id)
    if car is None or car.ownership != "current":
        await callback.answer("Автомобиль недоступен", show_alert=True)
        return
    await callback.answer()
    await state.clear()
    await state.update_data(
        car_id=car.id,
        text=text,
        side_done=True,
        engine_done=bool(car.engine_code),
        gearbox_done=bool(car.gearbox),
        stab_done=True,
    )
    parsed = parse_query(text, car.vin)
    if callback.message is None:
        return
    await finish(callback.message, state, session, user, car, parsed)


async def start_search(target: Message | CallbackQuery, state: FSMContext, session: AsyncSession, user: User, car_id: int | None = None) -> None:
    cars = await current_cars(session, user)
    if not cars:
        await present(target, NO_CARS_SEARCH, cars_keyboard([], "caropen"))
        return
    chosen = None
    if car_id is not None:
        chosen = await get_car(session, car_id, user.id)
    elif user.active_car_id:
        chosen = next((car for car in cars if car.id == user.active_car_id), None)
    if chosen is None and len(cars) == 1:
        chosen = cars[0]
    if chosen is None or chosen.ownership != "current":
        await state.set_state(SearchFlow.text)
        await present(
            target,
            "Для какой машины ищем запчасть?\nЗапрос будет только про выбранный автомобиль.",
            cars_keyboard(cars, "find"),
        )
        return
    user.active_car_id = chosen.id
    await state.set_state(SearchFlow.text)
    await state.update_data(car_id=chosen.id)
    await present(
        target,
        f"Ищу для <b>{chosen.brand} {chosen.model}, {chosen.year}</b>.\n\n"
        "Опишите деталь своими словами.\n"
        "Например: <i>зеркало левое, водительская сторона</i>\n\n"
        "Если артикул уже известен, допишите его в ту же фразу. "
        "Голосовые сообщения бот пока не разбирает, фото шильдика сохранит, но текст с него нужно ввести вручную.",
        InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Сменить автомобиль", callback_data="find:pick")],
                [InlineKeyboardButton(text="Отмена", callback_data="nav:cancel")],
            ]
        ),
    )


@router.callback_query(F.data.startswith("find:"))
async def find_entry(callback: CallbackQuery, state: FSMContext, session: AsyncSession, user: User) -> None:
    tail = callback.data.split(":", 1)[1]
    if tail in {"again", "pick"}:
        await state.clear()
        if tail == "pick":
            cars = await current_cars(session, user)
            await present(callback, "Выберите автомобиль.", cars_keyboard(cars, "find"))
            return
        await start_search(callback, state, session, user)
        return
    await start_search(callback, state, session, user, int(tail))


@router.callback_query(F.data.startswith("hist:"))
async def history_entry(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    car = await get_car(session, int(callback.data.split(":")[1]), user.id)
    if car is None:
        await present(callback, "Автомобиль не найден.", None)
        return
    rows = await history_for_car(session, car, user.id)
    buttons = [[InlineKeyboardButton(text=row.text[:40], callback_data=f"sopen:{row.id}")] for row in rows[:8]]
    buttons.append([InlineKeyboardButton(text="← К автомобилю", callback_data=f"caropen:{car.id}")])
    await present(callback, history_text(car, rows, user.id), InlineKeyboardMarkup(inline_keyboard=buttons))


async def show_history_picker(target: Message | CallbackQuery, session: AsyncSession, user: User) -> None:
    cars = await list_cars(session, user.id)
    if not cars:
        await present(target, "История появится после первого запроса, а запрос — после автомобиля в гараже.", cars_keyboard([], "caropen"))
        return
    if len(cars) == 1:
        car = cars[0]
        rows = await history_for_car(session, car, user.id)
        buttons = [[InlineKeyboardButton(text=row.text[:40], callback_data=f"sopen:{row.id}")] for row in rows[:8]]
        buttons.append([InlineKeyboardButton(text="В меню", callback_data="nav:menu")])
        await present(target, history_text(car, rows, user.id), InlineKeyboardMarkup(inline_keyboard=buttons))
        return
    await present(target, "История привязана к VIN. Выберите автомобиль.", cars_keyboard(cars, "hist"))


@router.message(SearchFlow.text, F.text)
async def search_text(message: Message, state: FSMContext, session: AsyncSession, user: User) -> None:
    text = (message.text or "").strip()
    if len(text) < 2:
        await message.answer("Опишите деталь чуть подробнее. Например: передний сайлентблок нижнего рычага.")
        return
    data = await state.get_data()
    if "car_id" not in data:
        await message.answer("Сначала выберите автомобиль кнопкой.")
        return
    parsed = parse_query(text)
    await state.update_data(text=text, side=parsed.side, side_done=parsed.side is not None)
    await advance(message, state, session, user)


@router.message(SearchFlow.side, F.text)
async def search_side_text(message: Message, state: FSMContext, session: AsyncSession, user: User) -> None:
    from zampotex.parsing import detect_side

    raw = (message.text or "").strip().lower().replace("ё", "е")
    if raw in {"не знаю", "незнаю", "без разницы"}:
        await state.update_data(side=None, side_done=True, side_unknown=True)
    else:
        side = detect_side(raw)
        if side is None:
            await message.answer("Нажмите кнопку: левая, правая или «Не знаю».", reply_markup=side_keyboard())
            return
        await state.update_data(side=side, side_done=True, side_unknown=False)
    await advance(message, state, session, user)


@router.callback_query(SearchFlow.side, F.data.startswith("side:"))
async def search_side(callback: CallbackQuery, state: FSMContext, session: AsyncSession, user: User) -> None:
    side = callback.data.split(":", 1)[1]
    await state.update_data(side=None if side == "unknown" else side, side_done=True, side_unknown=side == "unknown")
    await callback.answer()
    await advance(callback.message, state, session, user)


@router.message(SearchFlow.engine, F.text)
async def search_engine(message: Message, state: FSMContext, session: AsyncSession, user: User) -> None:
    parsed = parse_engine_line(message.text or "")
    data = await state.get_data()
    car = await get_car(session, int(data["car_id"]), user.id)
    if car and parsed["engine_code"]:
        car.engine_code = str(parsed["engine_code"])
        await state.update_data(engine_done=True, engine_skip=False)
    else:
        await state.update_data(engine_done=True, engine_skip=True)
    if car and parsed["gearbox"]:
        car.gearbox = str(parsed["gearbox"])
        await state.update_data(gearbox_done=True)
    await advance(message, state, session, user)


@router.callback_query(SearchFlow.engine, F.data == "skip:engine")
async def skip_engine(callback: CallbackQuery, state: FSMContext, session: AsyncSession, user: User) -> None:
    await state.update_data(engine_done=True, engine_skip=True)
    await callback.answer()
    await advance(callback.message, state, session, user)


@router.callback_query(SearchFlow.gearbox, F.data.startswith("box:"))
async def search_box(callback: CallbackQuery, state: FSMContext, session: AsyncSession, user: User) -> None:
    value = callback.data.split(":", 1)[1]
    data = await state.get_data()
    car = await get_car(session, int(data["car_id"]), user.id)
    labels = {"auto": "АКПП", "manual": "МКПП", "cvt": "вариатор", "robot": "робот"}
    if value == "skip":
        await state.update_data(gearbox_done=True, gearbox_skip=True)
    elif car is not None:
        car.gearbox = labels[value]
        await state.update_data(gearbox_done=True, gearbox_skip=False)
    await callback.answer()
    await advance(callback.message, state, session, user)


@router.message(SearchFlow.stabilizer, F.text)
async def search_stabilizer(message: Message, state: FSMContext, session: AsyncSession, user: User) -> None:
    data = await state.get_data()
    car = await get_car(session, int(data["car_id"]), user.id)
    if car is not None:
        car.pr_codes = (message.text or "").strip()[:1000]
    await state.update_data(stab_done=True, stab_skip=False)
    await advance(message, state, session, user)


@router.callback_query(SearchFlow.stabilizer, F.data == "skip:stab")
async def skip_stab(callback: CallbackQuery, state: FSMContext, session: AsyncSession, user: User) -> None:
    await state.update_data(stab_done=True, stab_skip=True)
    await callback.answer()
    await advance(callback.message, state, session, user)


@router.message(StateFilter(*SEARCH_STATES), F.photo)
async def search_photo(message: Message, state: FSMContext, session: AsyncSession, user: User) -> None:
    data = await state.get_data()
    car_id = data.get("car_id")
    await store_photo(message, session, user, int(car_id) if car_id else None)
    await message.answer(PHOTO_SAVED)


@router.message(StateFilter(*SEARCH_STATES), F.voice)
async def search_voice(message: Message) -> None:
    await message.answer(VOICE_UNSUPPORTED)


async def advance(message: Message, state: FSMContext, session: AsyncSession, user: User) -> None:
    data = await state.get_data()
    car = await get_car(session, int(data["car_id"]), user.id)
    if car is None:
        await state.clear()
        await message.answer("Автомобиль не найден. Откройте гараж и добавьте его снова.")
        return
    parsed = parse_query(data["text"], car.vin)
    if data.get("side_done"):
        parsed.side = data.get("side")
    elif parsed.side:
        await state.update_data(side=parsed.side, side_done=True)

    if parsed.paired and not data.get("side_done") and parsed.side is None:
        await state.set_state(SearchFlow.side)
        await message.answer(
            "Эта деталь бывает левой и правой, номера у них разные.\nКакая сторона нужна?",
            reply_markup=side_keyboard(),
        )
        return
    needs_engine = parsed.intent in {"oil", "mount"}
    if needs_engine and not car.engine_code and not data.get("engine_done"):
        await state.set_state(SearchFlow.engine)
        await message.answer(
            "Чтобы не перепутать модификацию, нужен код двигателя.\n"
            "Пример: <code>CBAB</code>. Если кода нет под рукой, нажмите «Не знаю».",
            reply_markup=skip_keyboard("skip:engine"),
        )
        return
    if parsed.intent == "mount" and not car.gearbox and not data.get("gearbox_done"):
        await state.set_state(SearchFlow.gearbox)
        await message.answer(
            "Опора зависит от коробки. Выберите тип.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(text="АКПП", callback_data="box:auto"),
                        InlineKeyboardButton(text="МКПП", callback_data="box:manual"),
                    ],
                    [
                        InlineKeyboardButton(text="Вариатор", callback_data="box:cvt"),
                        InlineKeyboardButton(text="Робот", callback_data="box:robot"),
                    ],
                    [InlineKeyboardButton(text="Не знаю", callback_data="box:skip")],
                ]
            ),
        )
        return
    if parsed.intent in {"stabilizer_bush", "stabilizer_link"} and not car.pr_codes and not data.get("stab_done"):
        await state.set_state(SearchFlow.stabilizer)
        await message.answer(
            "У стабилизатора несколько размеров. Напишите диаметр, PR-код или номер со снятой детали.\n"
            "Без этого бот не будет выбирать размер наугад.",
            reply_markup=skip_keyboard("skip:stab"),
        )
        return
    await finish(message, state, session, user, car, parsed)


async def finish(message: Message, state: FSMContext, session: AsyncSession, user: User, car: Car, parsed) -> None:
    data = await state.get_data()
    missing = []
    if parsed.paired and (data.get("side_unknown") or parsed.side is None):
        missing.append("сторона")
    if data.get("engine_skip"):
        missing.append("код двигателя")
    if data.get("gearbox_skip"):
        missing.append("тип коробки")
    if data.get("stab_skip"):
        missing.append("диаметр или PR-код стабилизатора")
    show_kit = parsed.intent == "oil"
    progress = await message.answer("Ищу…")
    report, catalog = await asyncio.gather(
        search_open_parts(car.brand, car.model, car.year, data["text"], parsed.intent),
        _catalog_for_search(car.vin, data["text"], parsed.intent),
    )
    catalog_lines, partsapi_on = catalog
    html_text, plain = result_messages(
        car,
        data["text"],
        parsed,
        missing,
        show_kit,
        report,
        catalog_lines=catalog_lines,
        partsapi_configured=partsapi_on,
    )
    row = Search(
        user_id=user.id,
        car_id=car.id,
        vin=car.vin,
        text=data["text"],
        side=parsed.side,
        status="open_checked",
        binding_level="unverified",
        summary=plain,
        counted=False,
    )
    session.add(row)
    await session.flush()
    await state.clear()
    await progress.edit_text(html_text, reply_markup=result_keyboard(row.id, False, car, data["text"]))


async def _visible(session: AsyncSession, user: User, row: Search | None) -> Search | None:
    if row is None:
        return None
    if row.user_id == user.id:
        return row
    cars = await list_cars(session, user.id)
    if any(car.vin == row.vin for car in cars) and not row.hidden:
        return row
    return None


@router.callback_query(F.data.startswith("sopen:"))
async def open_search(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    row = await _visible(session, user, await get_search(session, int(callback.data.split(":")[1])))
    if row is None:
        await present(callback, "Запрос не найден или скрыт владельцем.", None)
        return
    from html import escape

    text = escape(row.summary)[:3800]
    markup = result_keyboard(row.id, row.hidden) if row.user_id == user.id else None
    await present(callback, text, markup)


@router.callback_query(F.data.startswith("shide:"))
async def hide_search(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    row = await get_search(session, int(callback.data.split(":")[1]))
    if row is None or row.user_id != user.id:
        await callback.answer("Скрыть можно только свой запрос", show_alert=True)
        return
    row.hidden = not row.hidden
    await callback.answer("Скрыто из общей истории" if row.hidden else "Снова видно по VIN")
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=result_keyboard(row.id, row.hidden))


@router.callback_query(F.data.startswith("srep:"))
async def repeat_search(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    row = await get_search(session, int(callback.data.split(":")[1]))
    if row is None or row.user_id != user.id or row.car_id is None:
        await callback.answer("Повторить можно только свой запрос", show_alert=True)
        return
    car = await get_car(session, row.car_id, user.id)
    if car is None:
        await callback.answer("Автомобиль уже удалён", show_alert=True)
        return
    parsed = parse_query(row.text, car.vin)
    parsed.side = row.side
    await callback.answer("Проверяю…")
    report, catalog = await asyncio.gather(
        search_open_parts(car.brand, car.model, car.year, row.text, parsed.intent),
        _catalog_for_search(car.vin, row.text, parsed.intent),
    )
    catalog_lines, partsapi_on = catalog
    show_kit = parsed.intent == "oil"
    html_text, plain = result_messages(
        car,
        row.text,
        parsed,
        [],
        show_kit,
        report,
        catalog_lines=catalog_lines,
        partsapi_configured=partsapi_on,
    )
    plain = "Повторная проверка открытых баз.\n\n" + plain
    html_text = "<b>Повторная проверка открытых баз.</b>\n\n" + html_text
    fresh = Search(
        user_id=user.id,
        car_id=car.id,
        vin=car.vin,
        text=row.text,
        side=row.side,
        status="open_checked",
        binding_level="unverified",
        summary=plain,
        counted=False,
    )
    session.add(fresh)
    await session.flush()
    await present(callback, html_text, result_keyboard(fresh.id, False, car, row.text))


@router.callback_query(F.data.startswith("sshelf:"))
async def search_to_shelf(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    row = await get_search(session, int(callback.data.split(":")[1]))
    if row is None or row.user_id != user.id or row.car_id is None:
        await callback.answer("Сохранить можно только свой запрос", show_alert=True)
        return
    parsed = parse_query(row.text, row.vin)
    item = ShelfItem(
        user_id=user.id,
        car_id=row.car_id,
        search_id=row.id,
        title=row.text[:255],
        oem=parsed.articles[0] if parsed.articles else None,
        status="in_stock",
        comment="Сформулировано пользователем. Каталогом не подтверждено.",
    )
    session.add(item)
    await callback.answer("Добавил в стеллаж")
    if callback.message:
        await callback.message.answer(
            "Запись в стеллаже создана со статусом «На складе».\n"
            "Это ваша формулировка, а не подтверждённый номер."
        )


@router.callback_query(F.data.startswith("spdf:"))
async def search_pdf(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    from aiogram.types import FSInputFile

    row = await _visible(session, user, await get_search(session, int(callback.data.split(":")[1])))
    if row is None:
        await callback.answer("Запрос не найден", show_alert=True)
        return
    await callback.answer("Готовлю файл")
    path = write_pdf(f"search-{row.id}.pdf", row.summary)
    if path is None or callback.message is None:
        if callback.message:
            await callback.message.answer_document(
                FSInputFile(_write_txt(row), filename=f"zampotex-{row.id}.txt")
            )
        return
    await callback.message.answer_document(FSInputFile(path), caption="Та же справка, что на экране.")


def _write_txt(row: Search):
    from zampotex.config import PDF_DIR

    PDF_DIR.mkdir(parents=True, exist_ok=True)
    target = PDF_DIR / f"search-{row.id}.txt"
    target.write_text(row.summary, encoding="utf-8")
    return target
