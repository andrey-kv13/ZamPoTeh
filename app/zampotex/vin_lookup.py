import asyncio
import html
import json
from dataclasses import dataclass
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from zampotex.config import get_settings
from zampotex.parsing import wmi_brand, year_hints
from zampotex.open_sources import notes_html, vin_public_notes

# Коды типа VAG в 7–8 знаках VIN. Это заводские обозначения кузова, не догадка модели.
VAG_TYPE_CODES = {
    "CR": "Touareg",
    "7P": "Touareg",
    "7L": "Touareg",
    "5N": "Tiguan",
    "AD": "Tiguan",
    "3C": "Passat",
    "3G": "Passat",
    "1K": "Golf",
    "5K": "Golf",
    "AU": "Golf",
    "CD": "Golf",
    "1J": "Golf",
    "1T": "Touran",
    "5T": "Touran",
    "7N": "Sharan",
    "6R": "Polo",
    "AW": "Polo",
}

@dataclass(frozen=True)
class BmwTypeSpec:
    model: str
    series: str
    generation: str
    body: str
    engine: str
    power: str
    drive: str
    gearbox: str
    market: str
    year_range: str
    sources: str


# Заводской тип BMW — знаки 4–7 VIN. 5D39: bimmerarchiv.de/code/5d39, WMI X4X.
BMW_TYPE_SPECS: dict[str, BmwTypeSpec] = {
    "5D39": BmwTypeSpec(
        model="530d xDrive",
        series="5 Series",
        generation="F10 LCI / F10N",
        body="седан",
        engine="N57N / N57D30O1, дизель 3.0",
        power="190 кВт / 258 л.с.",
        drive="полный xDrive",
        gearbox="автомат",
        market="Россия, левый руль",
        year_range="2013–2016",
        sources="BimmerArchive (Typschlüssel 5D39), WMI X4X",
    ),
}

# BMW на Автоторе (X4X/X4A): при 10-м знаке 0 год часто кодируется 11-м знаком (открытые таблицы BMW/VIN).
_BMW_AVOTOR_YEAR = {
    "A": 2010,
    "B": 2011,
    "C": 2012,
    "D": 2013,
    "E": 2014,
    "F": 2015,
    "G": 2016,
    "H": 2017,
    "J": 2018,
    "K": 2019,
    "L": 2020,
    "M": 2021,
    "N": 2022,
    "P": 2023,
    "R": 2024,
    "S": 2025,
    "T": 2026,
    "V": 1997,
    "W": 1998,
    "X": 1999,
    "Y": 2000,
    "1": 2001,
    "2": 2002,
    "3": 2003,
    "4": 2004,
    "5": 2005,
    "6": 2006,
    "7": 2007,
    "8": 2008,
    "9": 2009,
}

VEHICLE_TYPES = {
    "MULTIPURPOSE PASSENGER VEHICLE (MPV)": "внедорожник или кроссовер",
    "PASSENGER CAR": "легковой автомобиль",
    "TRUCK": "грузовой автомобиль",
    "BUS": "автобус",
    "MOTORCYCLE": "мотоцикл",
    "TRAILER": "прицеп",
}

MAKE_NAMES = {
    "VOLKSWAGEN": "Volkswagen",
    "AUDI": "Audi",
    "BMW": "BMW",
    "MERCEDES-BENZ": "Mercedes-Benz",
    "SKODA": "Skoda",
    "TOYOTA": "Toyota",
    "NISSAN": "Nissan",
    "HYUNDAI": "Hyundai",
    "KIA": "Kia",
    "LADA": "Lada",
    "RENAULT": "Renault",
    "FORD": "Ford",
    "OPEL": "Opel",
    "HONDA": "Honda",
    "MAZDA": "Mazda",
    "MITSUBISHI": "Mitsubishi",
    "VOLVO": "Volvo",
    "PEUGEOT": "Peugeot",
    "CITROEN": "Citroen",
    "CHEVROLET": "Chevrolet",
}

_CHECK_VALUES = {str(digit): digit for digit in range(10)}
for _letters, _numbers in (
    ("AJ", (1, 1)),
    ("BKS", (2, 2, 2)),
    ("CLT", (3, 3, 3)),
    ("DMU", (4, 4, 4)),
    ("ENV", (5, 5, 5)),
    ("FW", (6, 6)),
    ("GPX", (7, 7, 7)),
    ("HY", (8, 8)),
    ("RZ", (9, 9)),
):
    for _letter, _number in zip(_letters, _numbers, strict=True):
        _CHECK_VALUES[_letter] = _number
_WEIGHTS = (8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2)


@dataclass
class VinInfo:
    vin: str
    brand: str | None
    model: str | None
    year: int | None
    vehicle_type: str | None
    nhtsa_reached: bool
    model_from_type_code: bool
    check_digit_ok: bool
    expected_check: str | None
    type_code_kind: str | None = None
    type_code_detail: str | None = None
    nhtsa_make_missing: bool = False
    open_notes: tuple[str, ...] = ()
    source_lines: tuple[str, ...] = ()
    bmw_model_year_code: int | None = None
    country: str | None = None
    region: str | None = None
    world_manufacturer: str | None = None


def expected_check_digit(vin: str) -> str | None:
    total = 0
    for index, char in enumerate(vin):
        value = _CHECK_VALUES.get(char)
        if value is None:
            return None
        total += value * _WEIGHTS[index]
    remainder = total % 11
    return "X" if remainder == 10 else str(remainder)


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    if not text or text.lower() in {"not applicable", "null", "n/a"}:
        return None
    return text


def _pretty_make(name: str) -> str:
    return MAKE_NAMES.get(name.upper(), name.title())


_COUNTRY_RU = {
    "South Africa": "ЮАР",
    "Ivory Coast": "Кот-д’Ивуар",
    "Lesotho": "Лесото",
    "Botswana": "Ботсвана",
    "Namibia": "Намибия",
    "Madagascar": "Мадагаскар",
    "Mauritius": "Маврикий",
    "Tunisia": "Тунис",
    "Cyprus": "Кипр",
    "Zimbabwe": "Зимбабве",
    "Mozambique": "Мозамбик",
    "Angola": "Ангола",
    "Kenya": "Кения",
    "Nigeria": "Нигерия",
    "Algeria": "Алжир",
    "Libya": "Ливия",
    "Egypt": "Египет",
    "Morocco": "Марокко",
    "Zambia": "Замбия",
    "China": "Китай",
    "Japan": "Япония",
    "Israel": "Израиль",
    "South Korea": "Южная Корея",
    "Jordan": "Иордания",
    "India": "Индия",
    "Indonesia": "Индонезия",
    "Thailand": "Таиланд",
    "Myanmar": "Мьянма",
    "Mongolia": "Монголия",
    "Kazakhstan": "Казахстан",
    "Iran": "Иран",
    "Pakistan": "Пакистан",
    "Iraq": "Ирак",
    "Turkey": "Турция",
    "Uzbekistan": "Узбекистан",
    "Azerbaijan": "Азербайджан",
    "Armenia": "Армения",
    "Philippines": "Филиппины",
    "Singapore": "Сингапур",
    "Malaysia": "Малайзия",
    "Bangladesh": "Бангладеш",
    "United Arab Emirates": "ОАЭ",
    "Taiwan": "Тайвань",
    "Vietnam": "Вьетнам",
    "Laos": "Лаос",
    "Saudi Arabia": "Саудовская Аравия",
    "Russia": "Россия",
    "Hong Kong": "Гонконг",
    "United Kingdom": "Великобритания",
    "Germany": "Германия",
    "Poland": "Польша",
    "Latvia": "Латвия",
    "South Ossetia": "Южная Осетия",
    "Switzerland": "Швейцария",
    "Czech Republic": "Чехия",
    "Hungary": "Венгрия",
    "Portugal": "Португалия",
    "Serbia & Montenegro": "Сербия и Черногория",
    "Andorra": "Андорра",
    "Spain": "Испания",
    "Denmark": "Дания",
    "Ireland": "Ирландия",
    "Romania": "Румыния",
    "Macedonia": "Северная Македония",
    "Slovakia": "Словакия",
    "Bosnia & Herzogovina": "Босния и Герцеговина",
    "Austria": "Австрия",
    "France": "Франция",
    "Serbia": "Сербия",
    "Croatia": "Хорватия",
    "Estonia": "Эстония",
    "Bulgaria": "Болгария",
    "Greece": "Греция",
    "Netherlands": "Нидерланды",
    "Luxembourg": "Люксембург",
    "Belgium": "Бельгия",
    "Finland": "Финляндия",
    "Malta": "Мальта",
    "Sweden": "Швеция",
    "Norway": "Норвегия",
    "Belarus": "Беларусь",
    "Ukraine": "Украина",
    "Italy": "Италия",
    "Slovenia": "Словения",
    "San Marino": "Сан-Марино",
    "Lithuania": "Литва",
    "United States": "США",
    "Canada": "Канада",
    "Mexico": "Мексика",
    "Dom. Republic": "Доминиканская Республика",
    "Honduras": "Гондурас",
    "Panama": "Панама",
    "Puerto Rico": "Пуэрто-Рико",
    "Australia": "Австралия",
    "New Zealand": "Новая Зеландия",
    "Argentina": "Аргентина",
    "Chile": "Чили",
    "Ecuador": "Эквадор",
    "Peru": "Перу",
    "Venezuela": "Венесуэла",
    "Bolivia": "Боливия",
    "Brazil": "Бразилия",
    "Colombia": "Колумбия",
    "Uruguay": "Уругвай",
}
_REGION_RU = {
    "Africa": "Африка",
    "Asia": "Азия",
    "Europe": "Европа",
    "North America": "Северная Америка",
    "Oceania": "Океания",
    "South America": "Южная Америка",
}


@dataclass
class WorldVin:
    country: str | None = None
    region: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    detail: str | None = None


def _readable_detail(value: object) -> str | None:
    text = str(value or "").strip()
    if sum(char.isalpha() for char in text) < 2 or len(text) < 3:
        return None
    return text


def _country_ru(name: str | None) -> str | None:
    if not name:
        return None
    return _COUNTRY_RU.get(name, name)


def build_vin_source_lines(
    info: VinInfo,
    nhtsa: dict | None,
    mcp: dict | None,
    dbvin: dict | None,
    partsapi: dict | list | None = None,
) -> tuple[str, ...]:
    lines: list[str] = []
    wmi_bits: list[str] = []
    if info.country:
        wmi_bits.append(f"страна {info.country}")
    if info.region:
        wmi_bits.append(info.region)
    if info.brand:
        wmi_bits.append(f"марка {info.brand}")
    elif info.world_manufacturer:
        wmi_bits.append(f"производитель {info.world_manufacturer}")
    lines.append(
        "Международный WMI (ISO 3779, vininfo + локальный справочник): "
        + (", ".join(wmi_bits) if wmi_bits else "структура VIN разобрана")
    )

    if mcp:
        validation = mcp.get("validation") or {}
        wmi = validation.get("wmi") or {}
        checksum = validation.get("checksum") or {}
        mcp_bits: list[str] = []
        if wmi.get("code"):
            mcp_bits.append(f"WMI {wmi['code']}")
        country = _country_ru(wmi.get("country"))
        if country:
            mcp_bits.append(country)
        if wmi.get("region"):
            mcp_bits.append(_REGION_RU.get(str(wmi["region"]), str(wmi["region"])))
        if checksum:
            mcp_bits.append(
                "контрольная цифра сходится" if checksum.get("valid") else "контрольная цифра не сходится"
            )
        vehicle = mcp.get("vehicle") or {}
        if vehicle.get("make"):
            mcp_bits.append(f"{vehicle['make']} {vehicle.get('model') or ''}".strip())
        lines.append("mcp.vin (открытый агрегатор): " + (", ".join(mcp_bits) if mcp_bits else "только структура VIN"))
    else:
        lines.append("mcp.vin (открытый агрегатор): не ответил")

    if nhtsa is not None:
        if info.nhtsa_make_missing:
            lines.append("NHTSA vPIC (каталог США/Канады): ответ есть, этой марки в каталоге нет")
        else:
            lines.append("NHTSA vPIC (каталог США/Канады): марка и модель получены")
    else:
        lines.append("NHTSA vPIC (каталог США/Канады): не ответил")

    if dbvin is None:
        lines.append("DB.VIN (открытая база объявлений): не ответил")
    elif dbvin.get("missing"):
        lines.append("DB.VIN (открытая база объявлений): записи по этому VIN нет")
    else:
        bits = [str(dbvin.get("brand") or "").strip(), str(dbvin.get("model") or "").strip()]
        label = " ".join(part for part in bits if part)
        if dbvin.get("year"):
            label = f"{label}, {dbvin['year']}".strip(", ")
        reg = dbvin.get("registrationCountry")
        if reg:
            label = f"{label}, рег. {reg}".strip(", ")
        lines.append("DB.VIN (открытая база объявлений): " + (label or "ответ без марки"))

    if info.type_code_kind in {"bmw", "vag"}:
        lines.append("Заводской код типа в VIN: модель взята из открытых таблиц производителя")
    elif info.type_code_kind == "world":
        lines.append("Разбор VIN по открытым правилам производителя: модель уточнена локально")
    if info.bmw_model_year_code:
        lines.append(
            f"Код модельного года BMW: 11-й знак {info.vin[10]} → {info.bmw_model_year_code} "
            "(не равен году выпуска в СТС)"
        )
    from zampotex.partsapi_client import summarize_vindecode

    pa_notes = summarize_vindecode(partsapi)
    if pa_notes:
        lines.append("PartsAPI TecDoc VINdecode (лицензия): " + "; ".join(pa_notes))
    elif get_settings().partsapi_key_vindecode:
        lines.append("PartsAPI TecDoc VINdecode (лицензия): ключ задан, ответ пустой или ошибка")
    return tuple(lines)


def decode_world(vin: str) -> WorldVin:
    try:
        from vininfo import Vin
        parsed = Vin(vin)
    except Exception:
        return WorldVin()
    manufacturer = str(parsed.manufacturer or "").strip()
    if not manufacturer or "unsupported" in manufacturer.lower():
        manufacturer = ""
    model = None
    bits: list[str] = []
    details = parsed.details
    if details is not None:
        model = _readable_detail(getattr(details, "model", None))
        for key, label in (("body", "Кузов"), ("engine", "Двигатель"), ("transmission", "Коробка")):
            text = _readable_detail(getattr(details, key, None))
            if text and text != model:
                bits.append(f"{label}: {text}")
    country = _COUNTRY_RU.get(str(parsed.country or ""), str(parsed.country or "")) or None
    region = _REGION_RU.get(str(parsed.region or ""), str(parsed.region or "")) or None
    if country == "":
        country = None
    if region == "":
        region = None
    return WorldVin(country, region, manufacturer or None, model, " ".join(bits) or None)


def vag_model(vin: str, brand: str | None) -> str | None:
    if brand != "Volkswagen":
        return None
    return VAG_TYPE_CODES.get(vin[6:8])


def bmw_type_spec(vin: str, brand: str | None) -> BmwTypeSpec | None:
    if brand != "BMW":
        return None
    return BMW_TYPE_SPECS.get(vin[3:7])


def bmw_spec_explain_lines(vin: str, spec: BmwTypeSpec, model_year_code: int | None) -> list[str]:
    lines = [
        f"<b>BMW {html.escape(spec.series)} {html.escape(spec.model)}</b>",
        f"Кузов: {html.escape(spec.generation)}, {html.escape(spec.body)}.",
        f"Двигатель: {html.escape(spec.engine)}.",
        f"Мощность: {html.escape(spec.power)}.",
        f"Привод: {html.escape(spec.drive)}, КПП: {html.escape(spec.gearbox)}.",
        f"Рынок: {html.escape(spec.market)}.",
        f"Тип-код <b>{html.escape(vin[3:7])}</b> — рестайлинговая F10, ориентир выпуска {html.escape(spec.year_range)}.",
    ]
    if model_year_code is not None:
        lines.append(
            f"11-й знак VIN (<b>{html.escape(vin[10])}</b>) — код BMW {model_year_code}, "
            "это не дата с конвейера. Точный год выпуска — из СТС; заводская дата — только в BMW ETK/ISTA."
        )
    else:
        lines.append(
            "10-й знак VIN — <b>0</b>, модельный год по ISO не читается. "
            "Точный год выпуска — из СТС; заводская дата — только в BMW ETK/ISTA."
        )
    lines.append(f"<i>Источники: {html.escape(spec.sources)}.</i>")
    return lines


def bmw_avtotor_year(vin: str, current_year: int) -> int | None:
    if len(vin) != 17 or vin[:3] not in {"X4X", "X4A"} or vin[9] != "0":
        return None
    year = _BMW_AVOTOR_YEAR.get(vin[10])
    if year is None or year < 1950 or year > current_year + 1:
        return None
    return year


def interpret(
    vin: str,
    nhtsa: dict | None,
    current_year: int,
    mcp: dict | None = None,
    dbvin: dict | None = None,
) -> VinInfo:
    expected = expected_check_digit(vin)
    check_ok = expected is not None and vin[8] == expected
    brand = wmi_brand(vin)
    model = None
    year = None
    vehicle_type = None
    reached = nhtsa is not None
    nhtsa_make_missing = reached and not bool(_clean((nhtsa or {}).get("Make")))
    if nhtsa:
        make = _clean(nhtsa.get("Make"))
        if make:
            brand = _pretty_make(make)
        api_model = _clean(nhtsa.get("Model"))
        if api_model:
            model = api_model.title() if api_model.isupper() else api_model
        raw_year = _clean(nhtsa.get("ModelYear"))
        if raw_year and raw_year.isdigit():
            parsed = int(raw_year)
            if 1950 <= parsed <= current_year + 1:
                year = parsed
        raw_type = _clean(nhtsa.get("VehicleType"))
        if raw_type:
            vehicle_type = VEHICLE_TYPES.get(raw_type.upper(), raw_type)
    world = decode_world(vin)
    if mcp:
        validation = mcp.get("validation") or {}
        wmi = validation.get("wmi") or {}
        if not world.country and wmi.get("country"):
            world.country = _country_ru(str(wmi["country"]))
        if not world.region and wmi.get("region"):
            world.region = _REGION_RU.get(str(wmi["region"]), str(wmi["region"]))
    if dbvin and not dbvin.get("missing"):
        if brand is None and _clean(dbvin.get("brand")):
            brand = _pretty_make(str(dbvin["brand"]))
        if model is None and _clean(dbvin.get("model")):
            model = str(dbvin["model"]).strip()
        raw_year = dbvin.get("year")
        if year is None and isinstance(raw_year, int) and 1950 <= raw_year <= current_year + 1:
            year = raw_year
    if brand is None and world.manufacturer:
        brand = world.manufacturer if not world.manufacturer.isupper() else _pretty_make(world.manufacturer)
    from_code = False
    type_kind = None
    type_detail = None
    if model is None:
        coded = vag_model(vin, brand)
        if coded:
            model = coded
            from_code = True
            type_kind = "vag"
    if model is None:
        spec = bmw_type_spec(vin, brand)
        if spec:
            model = spec.model
            type_detail = f"{spec.series}, {spec.generation}"
            from_code = True
            type_kind = "bmw"
    if model is None and world.model:
        model = world.model
        from_code = True
        type_kind = "world"
        type_detail = world.detail
    bmw_model_year_code = bmw_avtotor_year(vin, current_year)
    if year is None:
        hints = year_hints(vin, current_year)
        if len(hints) == 1:
            year = hints[0]
    info = VinInfo(
        vin,
        brand,
        model,
        year,
        vehicle_type,
        reached,
        from_code,
        check_ok,
        expected,
        type_kind,
        type_detail,
        nhtsa_make_missing,
    )
    info.country = world.country
    info.region = world.region
    info.world_manufacturer = world.manufacturer
    info.bmw_model_year_code = bmw_model_year_code
    return info


def explain(info: VinInfo) -> str:
    lines = [f"VIN <code>{info.vin}</code>", ""]
    if info.country:
        place = info.country if not info.region else f"{info.country}, {info.region}"
        lines.append(f"Международный код WMI, все страны: <b>{html.escape(place)}</b>")
    if info.world_manufacturer and info.world_manufacturer.casefold() != (info.brand or "").casefold():
        lines.append(f"Производитель по мировому справочнику: <b>{html.escape(info.world_manufacturer)}</b>")
    if info.vin.startswith("X4X") and info.brand == "BMW":
        lines.append("Код <b>X4X</b> — крупноузловая сборка BMW на Автоторе, Калининград.")
    if info.brand:
        lines.append(f"Марка: <b>{info.brand}</b>")
    if info.year:
        lines.append(f"Год выпуска: <b>{info.year}</b>")
    if info.vehicle_type and info.nhtsa_reached:
        lines.append(f"Тип: {info.vehicle_type}")
    if info.model and info.model_from_type_code and info.type_code_kind == "bmw":
        spec = bmw_type_spec(info.vin, info.brand)
        if spec:
            lines.extend(bmw_spec_explain_lines(info.vin, spec, info.bmw_model_year_code))
        else:
            detail = f" {html.escape(info.type_code_detail)}" if info.type_code_detail else ""
            lines.append(
                f"Модель по заводскому коду типа <b>{info.vin[3:7]}</b>: <b>{html.escape(info.model)}</b>.{detail}"
            )
    elif info.model and info.model_from_type_code and info.type_code_kind == "world":
        detail = f" {html.escape(info.type_code_detail)}" if info.type_code_detail else ""
        lines.append(f"Модель по открытому разбору VIN: <b>{html.escape(info.model)}</b>.{detail}")
    elif info.model and info.model_from_type_code:
        lines.append(
            f"Модель по коду кузова <b>{info.vin[6:8]}</b>: <b>{info.model}</b>. "
            "В ответе NHTSA модели не было, код взят из заводского обозначения VAG."
        )
    elif info.model:
        lines.append(f"Модель: <b>{info.model}</b>")
    elif not info.brand:
        lines.append("Марку и модель открытые источники не вернули.")
    if info.year is None and info.bmw_model_year_code is None and info.vin[9] == "0" and info.vin[:3] in {"X4X", "X4A"}:
        lines.append(
            "Десятый знак VIN — <b>0</b>. Год выпуска в СТС нужно вписать вручную "
            f"(11-й знак <b>{info.vin[10]}</b> в таблице BMW не найден)."
        )
    elif info.year is None and info.bmw_model_year_code is None and info.vin[9] == "0":
        lines.append("Десятый знак VIN — <b>0</b>. Это не код года по ISO, поэтому год нужно вписать вручную.")
    if not info.check_digit_ok and info.expected_check:
        lines.append(
            f"\nКонтрольный знак в 9-й позиции не сходится: сейчас <b>{info.vin[8]}</b>, "
            f"по стандарту ожидается <b>{info.expected_check}</b>. Проверьте VIN в СТС."
        )
    if info.source_lines:
        body = "\n".join(f"• {html.escape(line)}" for line in info.source_lines)
        lines.append(f"\n<b>Проверенные открытые источники</b>\n{body}")
    extra = notes_html(info.open_notes)
    if extra:
        lines.append(extra)
    lines.append("\nЭто ваш автомобиль?")
    return "\n".join(lines)


async def lookup_vin(vin: str, current_year: int) -> VinInfo:
    def load_nhtsa() -> dict | None:
        url = f"https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues/{vin}?format=json"
        with urlopen(url, timeout=12) as response:
            payload = json.load(response)
        rows = payload.get("Results") or []
        return rows[0] if rows else None

    def load_mcp() -> dict | None:
        url = f"https://mcp.vin/api/vin/{vin}"
        request = Request(url, headers={"User-Agent": "ZamPoTeh/1.0", "Accept": "application/json"})
        with urlopen(request, timeout=12) as response:
            payload = json.load(response)
        return payload if isinstance(payload, dict) else None

    def load_dbvin() -> dict | None:
        url = f"https://db.vin/api/v1/vin/{vin}"
        request = Request(url, headers={"User-Agent": "ZamPoTeh/1.0", "Accept": "application/json"})
        try:
            with urlopen(request, timeout=10) as response:
                payload = json.load(response)
            return payload if isinstance(payload, dict) else None
        except HTTPError as error:
            if error.code == 404:
                return {"missing": True}
            return None
        except Exception:
            return None

    def load_partsapi():
        from zampotex.partsapi_client import vindecode

        return vindecode(vin)

    nhtsa_raw, mcp_raw, dbvin_raw, partsapi_raw = await asyncio.gather(
        asyncio.to_thread(load_nhtsa),
        asyncio.to_thread(load_mcp),
        asyncio.to_thread(load_dbvin),
        asyncio.to_thread(load_partsapi),
        return_exceptions=True,
    )
    nhtsa = None if isinstance(nhtsa_raw, Exception) else nhtsa_raw
    mcp = None if isinstance(mcp_raw, Exception) else mcp_raw
    dbvin = None if isinstance(dbvin_raw, Exception) else dbvin_raw
    partsapi = None if isinstance(partsapi_raw, Exception) else partsapi_raw

    info = interpret(vin, nhtsa, current_year, mcp=mcp, dbvin=dbvin)
    info.source_lines = build_vin_source_lines(info, nhtsa, mcp, dbvin, partsapi=partsapi)
    try:
        info.open_notes = await vin_public_notes(info.brand, info.model, info.year)
    except Exception:
        info.open_notes = ("Дополнительные открытые базы сейчас не ответили.",)
    return info
