import re
from dataclasses import dataclass
from pathlib import Path

VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")
YEAR_RE = re.compile(r"^(19[5-9]\d|20\d{2}|2100)$")

# Десятый знак VIN повторяется каждые 30 лет. Буквы I, O, Q, U, Z не используются.
_YEAR_LETTERS = "ABCDEFGHJKLMNPRSTVWXY"
YEAR_BY_SIGN: dict[str, list[int]] = {}
for _index, _sign in enumerate(_YEAR_LETTERS):
    YEAR_BY_SIGN[_sign] = [1980 + _index, 2010 + _index]
for _digit in range(1, 10):
    YEAR_BY_SIGN[str(_digit)] = [2000 + _digit, 2030 + _digit]

WMI_BRANDS: dict[str, str] = {
    "XW8": "Volkswagen",
    "WVW": "Volkswagen",
    "WVG": "Volkswagen",
    "WV1": "Volkswagen",
    "WV2": "Volkswagen",
    "WV3": "Volkswagen",
    "1VW": "Volkswagen",
    "3VW": "Volkswagen",
    "9BW": "Volkswagen",
    "WA1": "Audi",
    "WUA": "Audi",
    "WAU": "Audi",
    "TRU": "Audi",
    "WBA": "BMW",
    "WBS": "BMW",
    "WBY": "BMW",
    "WBX": "BMW",
    "4US": "BMW",
    "5UX": "BMW",
    "5YM": "BMW",
    "X4X": "BMW",
    "WDB": "Mercedes-Benz",
    "WDD": "Mercedes-Benz",
    "WDC": "Mercedes-Benz",
    "XTA": "Lada",
    "XTH": "ГАЗ",
    "Z94": "Hyundai",
    "XWE": "Kia",
    "XWB": "УАЗ",
    "TMB": "Skoda",
    "TMP": "Skoda",
    "VF1": "Renault",
    "X7L": "Renault",
    "VF3": "Peugeot",
    "ZFA": "Fiat",
    "SJN": "Nissan",
    "VSK": "Nissan",
    "NMT": "Toyota",
    "SB1": "Toyota",
    "JMB": "Mitsubishi",
    "JHM": "Honda",
    "JH4": "Acura",
    "KMH": "Hyundai",
    "KNA": "Kia",
    "YV1": "Volvo",
    "WF0": "Ford",
    "XUF": "Opel",
    "W0L": "Opel",
    "Z8N": "Nissan",
    "XTT": "УАЗ",
    "X96": "ГАЗ",
    "EBE": "ГАЗ",
}

CITIES = [
    "Москва",
    "Санкт-Петербург",
    "Новосибирск",
    "Екатеринбург",
    "Казань",
    "Нижний Новгород",
    "Челябинск",
    "Самара",
    "Омск",
    "Ростов-на-Дону",
    "Уфа",
    "Красноярск",
    "Воронеж",
    "Пермь",
    "Волгоград",
    "Краснодар",
    "Саратов",
    "Тюмень",
    "Тольятти",
    "Ижевск",
    "Барнаул",
    "Иркутск",
    "Ульяновск",
    "Хабаровск",
    "Ярославль",
    "Владивосток",
    "Махачкала",
    "Томск",
    "Оренбург",
    "Кемерово",
    "Новокузнецк",
    "Рязань",
    "Астрахань",
    "Пенза",
    "Липецк",
    "Киров",
    "Чебоксары",
    "Тула",
    "Калининград",
    "Курск",
    "Ставрополь",
    "Сочи",
    "Тверь",
    "Брянск",
    "Иваново",
    "Белгород",
    "Владимир",
    "Архангельск",
    "Калуга",
    "Смоленск",
    "Вологда",
    "Саранск",
    "Череповец",
    "Курган",
    "Орёл",
    "Владикавказ",
    "Грозный",
    "Мурманск",
    "Тамбов",
    "Петрозаводск",
    "Кострома",
    "Йошкар-Ола",
    "Новороссийск",
    "Таганрог",
    "Сыктывкар",
    "Нальчик",
    "Шахты",
    "Дзержинск",
    "Братск",
    "Орск",
    "Ангарск",
    "Энгельс",
    "Благовещенск",
    "Старый Оскол",
    "Великий Новгород",
    "Псков",
    "Бийск",
    "Прокопьевск",
    "Рыбинск",
    "Балашиха",
    "Подольск",
    "Химки",
    "Мытищи",
    "Люберцы",
    "Королёв",
]

WORKS = [
    ("oil", "Замена масла ДВС"),
    ("air_filter", "Воздушный фильтр"),
    ("cabin_filter", "Салонный фильтр"),
    ("brake_front", "Передние колодки"),
    ("brake_rear", "Задние колодки"),
    ("plugs", "Свечи"),
    ("other", "Другая работа"),
]
WORK_LABELS = dict(WORKS)

LEFT_MARKERS = ("лев", "водитель")
RIGHT_MARKERS = ("прав", "пассажир")
PAIRED_MARKERS = (
    "зеркал",
    "фар",
    "фонар",
    "рычаг",
    "суппорт",
    "крыл",
    "порог",
    "пыльник",
)
ARTICLE_RE = re.compile(r"\b(?=[A-Z0-9][A-Z0-9./-]{4,19}\b)(?=[A-Z0-9./-]*\d)[A-Z0-9][A-Z0-9./-]{4,19}\b")


@dataclass
class ParsedQuery:
    side: str | None
    articles: list[str]
    intent: str
    paired: bool


def normalize_vin(value: str) -> str:
    return re.sub(r"\s+", "", value).upper().replace("А", "A").replace("В", "B").replace("С", "C").replace("Е", "E").replace("Н", "H").replace("К", "K").replace("М", "M").replace("О", "O").replace("Р", "P").replace("Т", "T").replace("Х", "X").replace("У", "Y")


def validate_vin(value: str) -> str | None:
    vin = normalize_vin(value)
    if VIN_RE.fullmatch(vin):
        return vin
    return None


_BRAND_IN_NAME = (
    ("BMW", "BMW"),
    ("VOLKSWAGEN", "Volkswagen"),
    ("AUDI", "Audi"),
    ("MERCEDES", "Mercedes-Benz"),
    ("SKODA", "Skoda"),
    ("ŠKODA", "Skoda"),
    ("HYUNDAI", "Hyundai"),
    ("TOYOTA", "Toyota"),
    ("NISSAN", "Nissan"),
    ("HONDA", "Honda"),
    ("RENAULT", "Renault"),
    ("PEUGEOT", "Peugeot"),
    ("CITRO", "Citroen"),
    ("FORD", "Ford"),
    ("OPEL", "Opel"),
    ("VOLVO", "Volvo"),
    ("MAZDA", "Mazda"),
    ("MITSUBISHI", "Mitsubishi"),
    ("KIA", "Kia"),
    ("FIAT", "Fiat"),
    ("CHEVROLET", "Chevrolet"),
    ("LADA", "Lada"),
)


def _load_wmi_csv() -> dict[str, str]:
    path = Path(__file__).with_name("data").joinpath("wmi.csv")
    found: dict[str, str] = {}
    if not path.exists():
        return found
    for line in path.read_text(encoding="utf-8").splitlines()[1:]:
        code, _, name = line.partition(",")
        code = code.strip().upper()
        name = name.strip()
        if len(code) == 3 and name:
            found[code] = name
    return found


_WMI_CSV = _load_wmi_csv()


def _brand_from_manufacturer(name: str) -> str:
    upper = name.upper()
    for needle, brand in _BRAND_IN_NAME:
        if needle in upper:
            return brand
    cleaned = name.split("(", 1)[0].strip()
    return cleaned or name.strip()


def wmi_brand(vin: str) -> str | None:
    code = vin[:3]
    if code in WMI_BRANDS:
        return WMI_BRANDS[code]
    name = _WMI_CSV.get(code)
    if not name:
        return None
    return _brand_from_manufacturer(name)


def year_hints(vin: str, current_year: int) -> list[int]:
    sign = vin[9]
    years = YEAR_BY_SIGN.get(sign, [])
    return [year for year in years if 1950 <= year <= current_year + 1]


def _fold(text: str) -> str:
    return text.lower().replace("ё", "е")


def detect_side(text: str) -> str | None:
    folded = _fold(text)
    left = re.search(r"(^|[^а-яa-z])(лев|водитель)", folded) is not None
    right = re.search(r"(^|[^а-яa-z])(прав|пассажир)", folded) is not None
    if left and right:
        return None
    if left:
        return "left"
    if right:
        return "right"
    return None


def is_paired(text: str) -> bool:
    folded = _fold(text)
    return any(marker in folded for marker in PAIRED_MARKERS)


def find_vin(text: str) -> str | None:
    for token in re.findall(r"[A-Za-zА-Яа-я0-9]{17}", text):
        vin = validate_vin(token)
        if vin:
            return vin
    return None


def message_is_vin(text: str) -> str | None:
    vin = find_vin(text)
    if vin is None:
        return None
    leftover = re.sub(re.escape(vin), "", text.upper(), count=1)
    leftover = re.sub(r"VIN|НОМЕР|КОД", "", leftover)
    leftover = re.sub(r"[\s:;,\-–—]+", "", leftover)
    if leftover:
        return None
    return vin


def detect_intent(text: str) -> str:
    folded = _fold(text)
    if "масл" in folded and not any(part in folded for part in ("короб", "акпп", "мкпп", "вариатор", "редуктор")):
        return "oil"
    if any(part in folded for part in ("тормоз", "колодк", "суппорт")) or (
        "диск" in folded and any(part in folded for part in ("тормоз", "колод"))
    ):
        return "brake"
    if "втулк" in folded and "стабил" in folded:
        return "stabilizer_bush"
    if "стойк" in folded and "стабил" in folded:
        return "stabilizer_link"
    if "опор" in folded and any(part in folded for part in ("двиг", "кпп", "короб")):
        return "mount"
    return "part"


def extract_articles(text: str, vin: str | None) -> list[str]:
    found: list[str] = []
    for match in ARTICLE_RE.findall(text.upper()):
        token = match.strip("./-")
        if vin and token == vin:
            continue
        if token.isdigit() and len(token) < 6:
            continue
        if token not in found:
            found.append(token)
    return found[:8]


def parse_query(text: str, vin: str | None = None) -> ParsedQuery:
    return ParsedQuery(
        side=detect_side(text),
        articles=extract_articles(text, vin),
        intent=detect_intent(text),
        paired=is_paired(text),
    )


def side_label(side: str | None) -> str:
    return {"left": "левая", "right": "правая", "unknown": "не знаю"}.get(side or "", "не указана")


def parse_engine_line(text: str) -> dict[str, str | int | None]:
    raw = text.strip()
    power = None
    power_match = re.search(r"(\d{2,3})\s*(л\.?\s*с|hp)", raw, flags=re.IGNORECASE)
    if power_match:
        power = int(power_match.group(1))
    engine = None
    engine_match = re.search(r"\b([A-Z0-9]{3,6})\b", raw.upper())
    if engine_match and not engine_match.group(1).isdigit():
        engine = engine_match.group(1)
    gearbox = None
    folded = _fold(raw)
    if "акпп" in folded or "автомат" in folded:
        gearbox = "АКПП"
    elif "мкпп" in folded or "механ" in folded:
        gearbox = "МКПП"
    elif "вариатор" in folded:
        gearbox = "вариатор"
    elif "робот" in folded:
        gearbox = "робот"
    code_match = re.search(r"\b([A-Z0-9]{2,5})\s*$", raw.upper())
    gearbox_code = code_match.group(1) if code_match and gearbox else None
    return {
        "engine_code": engine,
        "power_hp": power,
        "gearbox": gearbox,
        "gearbox_code": gearbox_code,
    }
