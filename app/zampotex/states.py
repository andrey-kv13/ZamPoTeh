from aiogram.fsm.state import State, StatesGroup


class AddCar(StatesGroup):
    vin = State()
    brand = State()
    model = State()
    year = State()
    city = State()


class EditCar(StatesGroup):
    mileage = State()
    engine = State()
    pr = State()
    city = State()


class SearchFlow(StatesGroup):
    text = State()
    side = State()
    engine = State()
    gearbox = State()
    stabilizer = State()


class ShelfFlow(StatesGroup):
    title = State()
    oem = State()
    price = State()


class RemindFlow(StatesGroup):
    pick_car = State()
    mileage = State()
    date = State()
    done_mileage = State()
    done_next = State()


class ProfileFlow(StatesGroup):
    city = State()


class TransferFlow(StatesGroup):
    code = State()
