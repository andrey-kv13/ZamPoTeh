from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from zampotex.models import Car, CarPhoto, LinkCode, Reminder, Search, Setting, ShelfItem, TransferCode, User

MOSCOW = ZoneInfo("Europe/Moscow")


def display_name(user: User) -> str:
    return user.telegram_name or str(user.telegram_id)


async def get_user(session: AsyncSession, telegram_id: int) -> User | None:
    result = await session.execute(select(User).where(User.telegram_id == telegram_id))
    return result.scalar_one_or_none()


async def get_or_create_user(session: AsyncSession, telegram_id: int, name: str | None) -> User:
    user = await get_user(session, telegram_id)
    if user is None:
        user = User(telegram_id=telegram_id, telegram_name=name)
        session.add(user)
        await session.flush()
    elif name and user.telegram_name != name:
        user.telegram_name = name
    return user


def has_consent(user: User | None) -> bool:
    return bool(user and user.consent_offer_version and user.consent_privacy_version)


async def get_setting(session: AsyncSession, key: str, default: str) -> str:
    row = await session.get(Setting, key)
    if row is None:
        row = Setting(key=key, value=default)
        session.add(row)
        await session.flush()
    return row.value


async def set_setting(session: AsyncSession, key: str, value: str) -> None:
    row = await session.get(Setting, key)
    if row is None:
        session.add(Setting(key=key, value=value))
    else:
        row.value = value


async def search_limit(session: AsyncSession) -> int:
    raw = await get_setting(session, "search_daily_limit", "20")
    try:
        return max(1, int(raw))
    except ValueError:
        return 20


def moscow_day_start() -> datetime:
    now = datetime.now(MOSCOW)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(timezone.utc)


async def searches_today(session: AsyncSession, user_id: int) -> int:
    result = await session.execute(
        select(Search.created_at).where(Search.user_id == user_id, Search.counted.is_(True))
    )
    start = moscow_day_start()
    total = 0
    for (moment,) in result.all():
        if moment is None:
            continue
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        if moment >= start:
            total += 1
    return total


async def list_cars(session: AsyncSession, user_id: int) -> list[Car]:
    result = await session.execute(select(Car).where(Car.user_id == user_id).order_by(Car.ownership, Car.id))
    return list(result.scalars())


async def count_cars(session: AsyncSession, user_id: int) -> int:
    result = await session.execute(
        select(func.count(Car.id)).where(Car.user_id == user_id, Car.ownership == "current")
    )
    return int(result.scalar_one())


async def get_car(session: AsyncSession, car_id: int, user_id: int) -> Car | None:
    result = await session.execute(select(Car).where(Car.id == car_id, Car.user_id == user_id))
    return result.scalar_one_or_none()


async def list_shelf(session: AsyncSession, user_id: int, car_id: int) -> list[ShelfItem]:
    result = await session.execute(
        select(ShelfItem).where(ShelfItem.user_id == user_id, ShelfItem.car_id == car_id).order_by(ShelfItem.id.desc())
    )
    return list(result.scalars())


async def get_shelf_item(session: AsyncSession, item_id: int, user_id: int) -> ShelfItem | None:
    result = await session.execute(select(ShelfItem).where(ShelfItem.id == item_id, ShelfItem.user_id == user_id))
    return result.scalar_one_or_none()


async def list_reminders(session: AsyncSession, user_id: int) -> list[Reminder]:
    result = await session.execute(
        select(Reminder).where(Reminder.user_id == user_id, Reminder.active.is_(True)).order_by(Reminder.id)
    )
    return list(result.scalars())


async def get_reminder(session: AsyncSession, reminder_id: int, user_id: int) -> Reminder | None:
    result = await session.execute(
        select(Reminder).where(Reminder.id == reminder_id, Reminder.user_id == user_id, Reminder.active.is_(True))
    )
    return result.scalar_one_or_none()


async def history_for_car(session: AsyncSession, car: Car, viewer_id: int) -> list[Search]:
    result = await session.execute(
        select(Search)
        .where(Search.vin == car.vin)
        .where(or_(Search.hidden.is_(False), Search.user_id == viewer_id))
        .order_by(Search.created_at.desc())
        .limit(20)
    )
    return list(result.scalars())


async def get_search(session: AsyncSession, search_id: int) -> Search | None:
    return await session.get(Search, search_id)


async def due_reminders(session: AsyncSession) -> list[tuple[Reminder, Car, User]]:
    result = await session.execute(
        select(Reminder, Car, User)
        .join(Car, Car.id == Reminder.car_id)
        .join(User, User.id == Reminder.user_id)
        .where(Reminder.active.is_(True), Car.ownership == "current", User.is_blocked.is_(False))
    )
    return list(result.all())


async def stats(session: AsyncSession) -> dict[str, int]:
    users = int((await session.execute(select(func.count(User.id)))).scalar_one())
    cars = int((await session.execute(select(func.count(Car.id)))).scalar_one())
    searches = int((await session.execute(select(func.count(Search.id)))).scalar_one())
    empty = int(
        (await session.execute(select(func.count(Search.id)).where(Search.status == "search_unavailable"))).scalar_one()
    )
    return {"users": users, "cars": cars, "searches": searches, "unavailable": empty}


async def recent_users(session: AsyncSession, limit: int = 15) -> list[User]:
    result = await session.execute(select(User).order_by(User.id.desc()).limit(limit))
    return list(result.scalars())


async def mark_link_code(session: AsyncSession, code: str, telegram_id: int) -> None:
    row = await session.get(LinkCode, code)
    now = datetime.now(timezone.utc)
    if row is None:
        session.add(LinkCode(code=code, telegram_id=telegram_id, used_at=now))
    else:
        row.telegram_id = telegram_id
        row.used_at = now


async def create_transfer(session: AsyncSession, car_id: int, code: str) -> TransferCode:
    row = TransferCode(code=code, car_id=car_id, expires_at=datetime.now(timezone.utc) + timedelta(hours=48))
    session.add(row)
    await session.flush()
    return row


async def claim_transfer(session: AsyncSession, code: str, new_user: User) -> Car | None:
    row = await session.get(TransferCode, code.upper())
    if row is None or row.used_at is not None or row.expires_at < datetime.now(timezone.utc):
        return None
    car = await session.get(Car, row.car_id)
    if car is None:
        return None
    if await count_cars(session, new_user.id) >= 10:
        return None
    car.ownership = "sold"
    await session.execute(update(Reminder).where(Reminder.car_id == car.id).values(active=False))
    clone = Car(
        user_id=new_user.id,
        vin=car.vin,
        brand=car.brand,
        model=car.model,
        year=car.year,
        engine_code=car.engine_code,
        power_hp=car.power_hp,
        gearbox=car.gearbox,
        gearbox_code=car.gearbox_code,
        city=car.city,
        ownership="current",
    )
    session.add(clone)
    row.used_at = datetime.now(timezone.utc)
    await session.flush()
    new_user.active_car_id = clone.id
    return clone


async def delete_account(session: AsyncSession, user: User) -> None:
    await session.execute(
        update(Search)
        .where(Search.user_id == user.id, Search.hidden.is_(False))
        .values(user_id=None, car_id=None)
    )
    await session.execute(delete(Search).where(Search.user_id == user.id))
    await session.execute(delete(ShelfItem).where(ShelfItem.user_id == user.id))
    await session.execute(delete(Reminder).where(Reminder.user_id == user.id))
    await session.execute(delete(CarPhoto).where(CarPhoto.user_id == user.id))
    car_ids = select(Car.id).where(Car.user_id == user.id)
    await session.execute(delete(TransferCode).where(TransferCode.car_id.in_(car_ids)))
    await session.execute(delete(Car).where(Car.user_id == user.id))
    await session.delete(user)


async def delete_car(session: AsyncSession, car: Car) -> None:
    await session.execute(delete(ShelfItem).where(ShelfItem.car_id == car.id))
    await session.execute(delete(Reminder).where(Reminder.car_id == car.id))
    await session.execute(delete(CarPhoto).where(CarPhoto.car_id == car.id))
    await session.execute(delete(TransferCode).where(TransferCode.car_id == car.id))
    await session.execute(update(Search).where(Search.car_id == car.id).values(car_id=None))
    await session.delete(car)
