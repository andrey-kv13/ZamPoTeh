"""Подбор артикулов TecDoc через PartsAPI (VIN → carId → дерево → getArticles)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from zampotex.partsapi_client import call_method, catalog_api_configured, configured_methods, vindecode
from zampotex.partsapi_util import extract_rows, upper_row

logger = logging.getLogger("zampotex.parts_catalog")

_LANG_TRY = (16, 4, 7)
_CAR_TYPE_TRY = (1, 2)
_MAX_LINES = 12


@dataclass(frozen=True)
class CatalogResult:
    lines: tuple[str, ...]
    configured: bool
    reason: str  # ok | no_keys | vin | tree | group | articles | error

    @property
    def ok(self) -> bool:
        return bool(self.lines)


def _fold(text: str) -> str:
    return text.lower().replace("ё", "е")


def _vin_row(vin: str) -> dict[str, Any] | None:
    payload = vindecode(vin)
    if not payload:
        return None
    row = payload[0] if isinstance(payload, list) and payload else payload
    return upper_row(row) if isinstance(row, dict) else None


def _car_types_from_vin(row: dict[str, Any]) -> tuple[int, ...]:
    found: list[int] = []
    for key in ("CARTYPE", "CAR_TYPE", "LINKTYPID", "LINK_TYP_ID", "VEHICLETYPE", "VEHICLE_TYPE"):
        raw = row.get(key)
        if raw in (None, ""):
            continue
        try:
            found.append(int(raw))
        except (TypeError, ValueError):
            continue
    for value in _CAR_TYPE_TRY:
        if value not in found:
            found.append(value)
    return tuple(found)


def _search_terms(query: str, intent: str) -> tuple[str, ...]:
    folded = _fold(query)
    terms: list[str] = []
    if intent == "oil" or "масл" in folded:
        terms.extend(["масл", "моторн", "engine oil"])
        if "фильтр" in folded:
            terms.append("фильтр")
        return tuple(dict.fromkeys(terms))
    if intent == "brake" or any(x in folded for x in ("тормоз", "колод", "суппорт", "диск")):
        if "диск" in folded:
            terms.extend(["диск", "тормоз", "brake disc"])
        if "колод" in folded:
            terms.extend(["колод", "тормоз", "brake pad"])
        if "суппорт" in folded:
            terms.append("суппорт")
        if not terms:
            terms.append("тормоз")
    if "наконечник" in folded:
        terms.extend(["наконечник", "рул", "steering", "tie rod", "track rod"])
    if "тяга" in folded and ("рул" in folded or "рулев" in folded):
        terms.extend(["тяга", "рул", "track rod", "steering"])
    elif "рулев" in folded or re.search(r"(^|[^а-я])рул[^а-я]", folded):
        if any(x in folded for x in ("наконечник", "тяга", "рейк", "насос")):
            terms.extend(["рул", "steering"])
    if "шаров" in folded and "опор" in folded:
        terms.extend(["шаров", "опор", "ball joint"])
    if "сайлент" in folded:
        terms.append("сайлент")
    if "рычаг" in folded:
        terms.extend(["рычаг", "control arm"])
    if "стойк" in folded and "стабил" in folded:
        terms.extend(["стойк", "стабил", "stabiliser"])
    if "перед" in folded or re.search(r"(^|[^а-я])пер[^а-я]", folded):
        terms.extend(["перед", "front"])
    if "зад" in folded:
        terms.extend(["зад", "rear"])
    if "прав" in folded:
        terms.append("прав")
    if "лев" in folded or "водител" in folded:
        terms.append("лев")
    if not terms:
        tokens = [t for t in re.split(r"[^a-zа-я0-9]+", folded) if len(t) >= 4]
        terms.extend(tokens[:4])
    return tuple(dict.fromkeys(terms))


def _row_label(row: dict[str, Any]) -> str:
    bits: list[str] = []
    root = row.get("ROOT_NODE_TEXT")
    if root:
        bits.append(str(root))
    for level in (1, 2, 3):
        text = row.get(f"NODE_{level}_TEXT")
        if text:
            bits.append(str(text))
    return " / ".join(bits)


def _row_str_id(row: dict[str, Any]) -> int | None:
    try:
        level = int(row.get("STR_LEVEL") or 0)
    except (TypeError, ValueError):
        level = 0
    for lvl in range(level, 0, -1):
        raw = row.get(f"NODE_{lvl}_STR_ID")
        if raw not in (None, "", 0, "0"):
            return int(raw)
    raw = row.get("ROOT_NODE_STR_ID")
    if raw not in (None, "", 0, "0"):
        return int(raw)
    return None


def _pick_group_id(tree: list[dict[str, Any]], terms: tuple[str, ...]) -> tuple[int | None, str]:
    if not tree or not terms:
        return None, ""
    best_score = 0
    best_id: int | None = None
    best_label = ""
    for row in tree:
        label = _row_label(row)
        folded = _fold(label)
        score = sum(1 for term in terms if term in folded)
        if score > best_score:
            best_score = score
            best_id = _row_str_id(row)
            best_label = label
    if best_score == 0:
        return None, ""
    if best_score < 2 and len(terms) >= 2:
        strong = ("наконечник", "колод", "диск", "масл", "фильтр", "steering", "brake")
        if not any(s in _fold(" ".join(terms)) for s in strong):
            return None, ""
        if best_score < 1:
            return None, ""
    return best_id, best_label


def _fetch_tree(car_id: int, car_type: int, lang: int) -> list[dict[str, Any]]:
    payload = call_method(
        "getSearchTree",
        lang=str(lang),
        carId=str(car_id),
        carType=str(car_type),
    )
    return extract_rows(payload, "data", "result", "searchTree", "rows", "list")


def _fetch_articles(car_id: int, car_type: int, lang: int, str_id: int) -> list[dict[str, Any]]:
    payload = call_method(
        "getArticles",
        lang=str(lang),
        strId=str(str_id),
        carId=str(car_id),
        carType=str(car_type),
    )
    return extract_rows(payload, "data", "result", "articles", "rows", "list")


def _lines_from_articles(rows: list[dict[str, Any]], group_label: str) -> tuple[str, ...]:
    seen: set[str] = set()
    lines: list[str] = []
    prefix = f"{group_label}: " if group_label else ""
    for item in rows:
        brand = (item.get("ART_SUP_BRAND") or item.get("SUP_BRAND") or "").strip()
        number = (item.get("ART_ARTICLE_NR") or "").strip()
        if not number:
            continue
        key = f"{brand}|{number}".upper()
        if key in seen:
            continue
        seen.add(key)
        group = (item.get("PRODUCT_GROUP") or "").strip()
        tail = f"{brand} {number}".strip()
        if group and group.lower() not in group_label.lower():
            tail = f"{group} — {tail}"
        lines.append(f"• {prefix}{tail}".strip())
        if len(lines) >= _MAX_LINES:
            break
    if len(seen) > _MAX_LINES:
        lines.append(f"• … ещё {len(seen) - _MAX_LINES} позиций в TecDoc")
    return tuple(lines)


def search_catalog(vin: str, query: str, intent: str) -> CatalogResult:
    if not catalog_api_configured():
        return CatalogResult((), False, "no_keys")

    row = _vin_row(vin)
    if not row or not row.get("CARID"):
        logger.info("Parts catalog: VINdecode empty for %s", vin)
        return CatalogResult((), True, "vin")

    try:
        car_id = int(row["CARID"])
    except (TypeError, ValueError):
        return CatalogResult((), True, "vin")

    terms = _search_terms(query, intent)
    car_types = _car_types_from_vin(row)
    tree: list[dict[str, Any]] = []
    used_lang = _LANG_TRY[0]
    used_type = car_types[0]
    for lang in _LANG_TRY:
        for car_type in car_types:
            tree = _fetch_tree(car_id, car_type, lang)
            if tree:
                used_lang = lang
                used_type = car_type
                break
        if tree:
            break
    if not tree:
        return CatalogResult((), True, "tree")

    str_id, group_label = _pick_group_id(tree, terms)
    if str_id is None:
        logger.info("Parts catalog: no group for %r terms=%s carId=%s", query, terms, car_id)
        return CatalogResult((), True, "group")

    articles = _fetch_articles(car_id, used_type, used_lang, str_id)
    if not articles:
        return CatalogResult((), True, "articles")

    lines = _lines_from_articles(articles, group_label)
    if not lines:
        return CatalogResult((), True, "articles")
    return CatalogResult(lines, True, "ok")


def search_catalog_lines(vin: str, query: str, intent: str) -> tuple[str, ...]:
    return search_catalog(vin, query, intent).lines


def admin_probe(vin: str, query: str) -> str:
    methods = configured_methods()
    if not methods:
        return (
            "PartsAPI: ключи не загружены.\n"
            "Файл app/.env.partsapi на ПК или PARTSAPI_* в /opt/zampotex/app/.env на сервере, затем деплой."
        )
    need = ("VINdecode", "getSearchTree", "getArticles")
    missing = [name for name in need if name not in methods]
    lines = [f"Методы в .env: {', '.join(methods)}"]
    if missing:
        lines.append(f"Не хватает для подбора: {', '.join(missing)} (у PartsAPI ключ отдельный на метод).")
    result = search_catalog(vin, query, "part")
    lines.append(f"Пробный запрос «{query[:60]}»: {result.reason}")
    if result.lines:
        lines.append("Примеры:")
        lines.extend(result.lines[:3])
    return "\n".join(lines)
