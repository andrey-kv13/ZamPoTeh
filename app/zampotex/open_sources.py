import asyncio
import html
import json
import re
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

# Ключевые открытые источники без ключа и без обхода защиты.
# Платные каталоги (TecDoc и аналоги) сюда не входят: открытого доступа к ним нет.

RECALLS_URL = "https://api.nhtsa.gov/recalls/recallsByVehicle"
SAFETY_URL = "https://api.nhtsa.gov/SafetyRatings"
CANADIAN_URL = "https://vpic.nhtsa.dot.gov/api/vehicles/GetCanadianVehicleSpecifications/"
TORQUE_URL = "https://autotools.brightcoding.dev/api/torque-specs"
OIL_URL = "https://autotools.brightcoding.dev/api/oil-specs"

_RECALL_TOPICS = (
    (("тормоз", "колодк", "суппорт"), ("brake",)),
    (("подушк", "airbag", "аирбаг"), ("air bag", "airbag")),
    (("рулев", "рул"), ("steering",)),
    (("ремень",), ("seat belt", "belt")),
    (("фар", "фонар"), ("light", "lamp", "visibility")),
    (("топлив", "бензонасос"), ("fuel",)),
    (("подвеск", "рычаг", "сайлент", "амортиз"), ("suspension",)),
    (("зеркал",), ("mirror", "visibility")),
    (("двигател", "мотор"), ("engine",)),
    (("акпп", "коробк", "трансмис"), ("power train", "transmission")),
    (("шина", "колес"), ("tire", "wheel")),
)

_TORQUE_TOPICS = (
    (("тормоз", "колодк"), "wheel"),
    (("тормоз", "колодк", "суппорт"), "caliper"),
    (("колес", "болт колес", "гайк"), "wheel"),
    (("ступиц", "подшипник"), "wheel-bearing"),
    (("суппорт",), "caliper"),
    (("свеч",), "spark-plug"),
    (("форсун",), "injector"),
    (("маховик",), "flywheel"),
    (("гбц", "головк блока"), "cylinder-head"),
    (("сливн", "пробк"), "oil-drain"),
    (("подвеск",), "suspension"),
)

_CANADIAN_FIELDS = (
    ("enginesize", "двигатель"),
    ("engine", "двигатель"),
    ("transmission", "коробка"),
    ("drivetype", "привод"),
    ("drive type", "привод"),
    ("bodystyle", "кузов"),
    ("body style", "кузов"),
    ("fueltype", "топливо"),
    ("fuel type", "топливо"),
)


@dataclass(frozen=True)
class OpenHit:
    source: str
    title: str
    text: str


@dataclass(frozen=True)
class SourceStatus:
    name: str
    detail: str


@dataclass(frozen=True)
class OpenReport:
    statuses: tuple[SourceStatus, ...]
    hits: tuple[OpenHit, ...]


def _fold(text: str) -> str:
    return text.lower().replace("ё", "е")


def _rows(payload: object) -> list[dict]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("results", "Results", "specs", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
    return []


def _clip(text: str, limit: int = 280) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "…"


def recall_needles(query: str) -> tuple[str, ...]:
    folded = _fold(query)
    found: list[str] = []
    for words, needles in _RECALL_TOPICS:
        if any(word in folded for word in words):
            found.extend(needles)
    return tuple(dict.fromkeys(found))


def torque_components(query: str, intent: str) -> tuple[str, ...]:
    folded = _fold(query)
    found: list[str] = []
    for words, component in _TORQUE_TOPICS:
        if any(word in folded for word in words):
            found.append(component)
    if intent == "oil":
        found.append("oil-drain")
    return tuple(dict.fromkeys(found))


def _compact_model(model: str) -> str:
    return re.sub(r"[^a-z0-9]", "", model.lower())


def _series_key(model: str) -> str | None:
    compact = re.sub(r"[^A-Z0-9]", "", model.upper())
    numbered = re.search(r"([1-8])\d{2}", compact)
    if numbered:
        return numbered.group(1)
    cross = re.search(r"X([1-7])", compact)
    if cross:
        return "X" + cross.group(1)
    return None


def _is_diesel(model: str) -> bool:
    compact = re.sub(r"[^A-Z0-9]", "", model.upper())
    return re.search(r"\dD(?!\d)", compact) is not None


def _is_xdrive(model: str) -> bool:
    return "XDRIVE" in re.sub(r"[^A-Z0-9]", "", model.upper())


def _model_number(model: str) -> int:
    compact = re.sub(r"[^A-Z0-9]", "", model.upper())
    numbered = re.search(r"([1-8]\d{2})", compact)
    return int(numbered.group(1)) if numbered else 0


def choose_listed_model(car_model: str, listed: list[str]) -> tuple[str | None, bool]:
    names = [name.strip() for name in listed if name and name.strip()]
    if not names:
        return None, False
    wanted = _compact_model(car_model)
    for name in names:
        if _compact_model(name) == wanted:
            return name, True
    series = _series_key(car_model)
    if series is None:
        return None, False
    pool = [name for name in names if _series_key(name) == series]
    if not pool:
        return None, False

    def score(name: str) -> tuple[int, int, int]:
        return (
            int(_is_diesel(name) == _is_diesel(car_model)),
            int(_is_xdrive(name) == _is_xdrive(car_model)),
            -abs(_model_number(name) - _model_number(car_model)),
        )

    return max(pool, key=score), False


def recall_name_variants(model: str) -> tuple[str, ...]:
    variants = [model.strip()]
    plain = re.sub(r"(?i)\b(xdrive|sdrive)\b", "", model)
    plain = re.sub(r"\s+", " ", plain).strip()
    if plain and plain.lower() not in {item.lower() for item in variants}:
        variants.append(plain)
    return tuple(variants)


def _norm_model(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def models_related(car_model: str, source_model: str | None) -> bool:
    if not source_model:
        return True
    car = _norm_model(car_model)
    source = _norm_model(source_model)
    if not car or not source:
        return False
    if car in source or source in car:
        return True
    series = re.search(r"\b([1-8])\d{2}", car_model)
    if series and f"{series.group(1)} series" in source:
        return True
    cross = re.search(r"\bx\s*([1-7])\b", car)
    if cross and f"x{cross.group(1)}" in source.replace(" ", ""):
        return True
    return False


def matching_recalls(payload: object, query: str) -> tuple[tuple[OpenHit, ...], str]:
    rows = _rows(payload)
    if not query.strip():
        return (), f"кампаний в базе: {len(rows)}"
    needles = recall_needles(query)
    if not needles:
        return (), f"кампаний в базе: {len(rows)}, к словам запроса не привязаны"
    hits: list[OpenHit] = []
    for row in rows:
        blob = f"{row.get('Component', '')} {row.get('Summary', '')}".lower()
        if not any(needle in blob for needle in needles):
            continue
        number = str(row.get("NHTSACampaignNumber") or "").strip()
        component = str(row.get("Component") or "компонент не указан").strip()
        summary = _clip(str(row.get("Summary") or ""))
        title = f"Кампания {number}" if number else "Отзывная кампания"
        hits.append(OpenHit("NHTSA, отзывные кампании", title, f"{component}. {summary}".strip()))
        if len(hits) == 5:
            break
    if not hits:
        return (), f"кампаний в базе: {len(rows)}, по этому узлу пусто"
    return tuple(hits), f"совпадений с запросом: {len(hits)}"


def matching_torque(payload: object, car_model: str, component: str) -> tuple[tuple[OpenHit, ...], str]:
    rows = [row for row in _rows(payload) if str(row.get("component") or "") == component]
    specific = [row for row in rows if row.get("model") and models_related(car_model, str(row.get("model")))]
    generic = [row for row in rows if not row.get("model")]
    chosen = specific or generic
    hits: list[OpenHit] = []
    for row in chosen[:3]:
        label = str(row.get("component_label") or component)
        torque = row.get("torque_nm")
        model = str(row.get("model") or "").strip()
        scope = f"В источнике модель указана как «{model}»." if model else "В источнике модель не разделена, это норма для марки."
        note = str(row.get("note") or "").strip()
        text = f"{label}: {torque} Н·м. {scope}"
        if note:
            text = f"{text} {note}"
        hits.append(OpenHit("AutoTools, моменты затяжки", label, _clip(text)))
    if not hits:
        return (), "по этому узлу и модели пусто"
    return tuple(hits), f"записей: {len(hits)}"


def matching_oil(payload: object, car_model: str) -> tuple[tuple[OpenHit, ...], str]:
    rows = _rows(payload)
    related = [row for row in rows if models_related(car_model, str(row.get("model") or "") or None)]
    if rows and not related:
        related = [row for row in rows if not row.get("model")]
    hits: list[OpenHit] = []
    skip = {"id", "brand", "created_at", "updated_at"}
    for row in related[:3]:
        parts = []
        for key, value in row.items():
            if key in skip or value in (None, ""):
                continue
            parts.append(f"{key}: {value}")
        if not parts:
            continue
        hits.append(OpenHit("AutoTools, масло", "Спецификация масла", _clip("; ".join(parts))))
    if not hits:
        return (), "по этой модели пусто"
    return tuple(hits), f"записей: {len(hits)}"


def canadian_summary(payload: object) -> str:
    rows = _rows(payload)
    if not rows:
        return "по этой модели пусто"
    folded = {str(key).lower().replace("_", " "): value for key, value in rows[0].items()}
    bits = []
    seen = set()
    for key, label in _CANADIAN_FIELDS:
        value = folded.get(key)
        if value in (None, "") or label in seen:
            continue
        seen.add(label)
        bits.append(f"{label}: {value}")
        if len(bits) == 4:
            break
    if not bits:
        return "ответ есть, понятных полей нет"
    return _clip(", ".join(bits), 220)


def safety_summary(model_payload: object, vehicle_payload: object | None) -> str:
    vehicles = _rows(model_payload)
    if not vehicles:
        return "по этой модели пусто"
    description = str(vehicles[0].get("VehicleDescription") or "").strip()
    ratings = _rows(vehicle_payload) if vehicle_payload else []
    rating = ""
    if ratings:
        overall = ratings[0].get("OverallRating")
        if overall not in (None, "", "Not Rated"):
            rating = f"общая оценка {overall}"
    if description and rating:
        return _clip(f"{description}; {rating}", 220)
    if description:
        return _clip(description, 220)
    if rating:
        return rating
    return "оценка не опубликована"


def _get_json(url: str, timeout: float = 8) -> tuple[object | None, str | None]:
    request = Request(url, headers={"User-Agent": "ZamPoTeh/1.0", "Accept": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.load(response), None
    except HTTPError as error:
        if error.code == 400:
            return None, "такой модели в этой базе нет"
        return None, f"ошибка HTTP {error.code}"
    except (URLError, TimeoutError, json.JSONDecodeError):
        return None, "не ответила вовремя"
    except Exception:
        return None, "не ответила"


async def _json(url: str) -> tuple[object | None, str | None]:
    return await asyncio.to_thread(_get_json, url)


def _recall_url(brand: str, model: str, year: int) -> str:
    query = urlencode({"make": brand.lower(), "model": model.lower(), "modelYear": str(year)})
    return f"{RECALLS_URL}?{query}"


def _safety_model_url(brand: str, model: str, year: int) -> str:
    return f"{SAFETY_URL}/modelyear/{year}/make/{quote(brand)}/model/{quote(model)}"


def _canadian_url(brand: str, model: str, year: int) -> str:
    query = urlencode({"year": str(year), "make": brand, "model": model, "units": "metric", "format": "json"})
    return f"{CANADIAN_URL}?{query}"


def _model_names(payload: object) -> list[str]:
    names: list[str] = []
    for row in _rows(payload):
        for key in ("model", "Model", "Model_Name"):
            value = row.get(key)
            if isinstance(value, str) and value.strip():
                names.append(value.strip())
                break
    return list(dict.fromkeys(names))


def _with_alias(note: str, detail: str) -> str:
    if note and detail:
        return f"{note}. {detail}"
    return note or detail


def _alias_hits(note: str, hits: tuple[OpenHit, ...]) -> tuple[OpenHit, ...]:
    if not note:
        return hits
    return tuple(OpenHit(hit.source, hit.title, f"{note}. {hit.text}") for hit in hits)


def _vehicle_ready(brand: str | None, model: str | None, year: int | None) -> bool:
    return bool(brand and model and year)


def _alias_note(car_model: str, queried: str, exact: bool) -> str:
    if exact or _compact_model(car_model) == _compact_model(queried):
        return ""
    return f"модели «{car_model}» в базе нет, проверена ближайшая «{queried}»"


async def _listed_models(kind: str, brand: str, year: int) -> list[str]:
    if kind == "safety":
        url = f"{SAFETY_URL}/modelyear/{year}/make/{quote(brand)}"
    else:
        query = urlencode({"make": brand, "modelYear": str(year), "issueType": "r"})
        url = f"https://api.nhtsa.gov/products/vehicle/models?{query}"
    payload, error = await _json(url)
    if error or payload is None:
        return []
    return _model_names(payload)


async def _resolve_model(kind: str, brand: str, model: str, year: int) -> tuple[str, str]:
    listed = await _listed_models(kind, brand, year)
    chosen, exact = choose_listed_model(model, listed)
    if chosen is None:
        return model, ""
    return chosen, _alias_note(model, chosen, exact)


async def _recall_status(brand: str | None, model: str | None, year: int | None, query: str) -> tuple[SourceStatus, tuple[OpenHit, ...]]:
    name = "NHTSA, отзывные кампании"
    if not _vehicle_ready(brand, model, year):
        return SourceStatus(name, "нужны марка, модель и год"), ()
    queried, note = await _resolve_model("recalls", brand or "", model or "", int(year or 0))
    payload = None
    error = "пустой ответ"
    used = queried
    for variant in recall_name_variants(queried):
        payload, error = await _json(_recall_url(brand or "", variant, int(year or 0)))
        used = variant
        if error != "такой модели в этой базе нет":
            break
    if not error and used.lower() != queried.lower():
        note = _with_alias(note, f"база приняла имя «{used}»")
    if error or payload is None:
        return SourceStatus(name, _with_alias(note, error or "пустой ответ")), ()
    hits, detail = matching_recalls(payload, query)
    return SourceStatus(name, _with_alias(note, detail)), _alias_hits(note, hits)


async def _safety_status(brand: str | None, model: str | None, year: int | None) -> tuple[SourceStatus, tuple[OpenHit, ...]]:
    name = "NHTSA, рейтинг безопасности"
    if not _vehicle_ready(brand, model, year):
        return SourceStatus(name, "нужны марка, модель и год"), ()
    queried, note = await _resolve_model("safety", brand or "", model or "", int(year or 0))
    payload, error = await _json(_safety_model_url(brand or "", queried, int(year or 0)))
    if error or payload is None:
        return SourceStatus(name, _with_alias(note, error or "пустой ответ")), ()
    vehicle_payload = None
    vehicles = _rows(payload)
    vehicle_id = vehicles[0].get("VehicleId") if vehicles else None
    if vehicle_id:
        vehicle_payload, _vehicle_error = await _json(f"{SAFETY_URL}/VehicleId/{vehicle_id}")
    return SourceStatus(name, _with_alias(note, safety_summary(payload, vehicle_payload))), ()


async def _canadian_status(brand: str | None, model: str | None, year: int | None) -> tuple[SourceStatus, tuple[OpenHit, ...]]:
    name = "NHTSA, канадские спецификации"
    if not _vehicle_ready(brand, model, year):
        return SourceStatus(name, "нужны марка, модель и год"), ()
    queried, note = await _resolve_model("recalls", brand or "", model or "", int(year or 0))
    payload, error = await _json(_canadian_url(brand or "", queried, int(year or 0)))
    if error or payload is None:
        return SourceStatus(name, _with_alias(note, error or "пустой ответ")), ()
    return SourceStatus(name, _with_alias(note, canadian_summary(payload))), ()


async def _torque_status(brand: str | None, model: str | None, query: str, intent: str) -> tuple[SourceStatus, tuple[OpenHit, ...]]:
    name = "AutoTools, моменты затяжки"
    components = torque_components(query, intent)
    if not brand:
        return SourceStatus(name, "нужна марка"), ()
    if not components:
        return SourceStatus(name, "запрос не про узел из этой базы"), ()
    hits: list[OpenHit] = []
    details: list[str] = []
    for component in components:
        query_string = urlencode({"brand": brand, "component": component})
        payload, error = await _json(f"{TORQUE_URL}?{query_string}")
        if error or payload is None:
            details.append(f"{component}: {error or 'пустой ответ'}")
            continue
        found, detail = matching_torque(payload, model or "", component)
        hits.extend(found)
        details.append(detail)
    return SourceStatus(name, "; ".join(details)), tuple(hits)


async def _oil_status(brand: str | None, model: str | None, query: str, intent: str) -> tuple[SourceStatus, tuple[OpenHit, ...]]:
    name = "AutoTools, масло"
    folded = _fold(query)
    if intent != "oil" and "масл" not in folded:
        return SourceStatus(name, "запрос не про масло"), ()
    if not brand:
        return SourceStatus(name, "нужна марка"), ()
    query_string = urlencode({"brand": brand, "model": model or ""})
    payload, error = await _json(f"{OIL_URL}?{query_string}")
    if error or payload is None:
        return SourceStatus(name, error or "пустой ответ"), ()
    hits, detail = matching_oil(payload, model or "")
    return SourceStatus(name, detail), hits


async def search_open_parts(brand: str | None, model: str | None, year: int | None, query: str, intent: str) -> OpenReport:
    parts = await asyncio.gather(
        _recall_status(brand, model, year, query),
        _safety_status(brand, model, year),
        _canadian_status(brand, model, year),
        _torque_status(brand, model, query, intent),
        _oil_status(brand, model, query, intent),
    )
    statuses = tuple(item[0] for item in parts)
    hits = tuple(hit for item in parts for hit in item[1])
    return OpenReport(statuses, hits)


async def vin_public_notes(brand: str | None, model: str | None, year: int | None) -> tuple[str, ...]:
    if not brand or not model:
        return ("Марка или модель не определены, базы по модели не запрашиваются.",)
    if not year:
        return ("Год в VIN не прочитан, поэтому отзывные кампании, рейтинг и канадские спецификации NHTSA пока не запрашиваются.",)
    recalls, safety, canadian = await asyncio.gather(
        _recall_status(brand, model, year, ""),
        _safety_status(brand, model, year),
        _canadian_status(brand, model, year),
    )
    lines = [f"{item.name}: {item.detail}" for item, _hits in (recalls, safety, canadian)]
    return tuple(lines)


def notes_html(notes: tuple[str, ...]) -> str:
    if not notes:
        return ""
    body = "\n".join(html.escape(note) for note in notes)
    return f"\n<b>Другие открытые базы</b>\n{body}"
