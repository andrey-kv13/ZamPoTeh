"""Подбор артикулов TecDoc через PartsAPI (VIN → carId → дерево → getArticles)."""

from __future__ import annotations

import re
from typing import Any

from zampotex.partsapi_client import call_method, vindecode

# Русский язык в TecDoc (partsapi.ru LANGUAGES).
_TECDOC_LANG_RU = 16
_CAR_TYPE_PASSENGER = 1
_MAX_LINES = 12


def _fold(text: str) -> str:
    return text.lower().replace("ё", "е")


def _vin_row(vin: str) -> dict[str, Any] | None:
    payload = vindecode(vin)
    if not payload:
        return None
    row = payload[0] if isinstance(payload, list) and payload else payload
    return row if isinstance(row, dict) else None


def _tree_rows(payload: dict | list | None) -> list[dict[str, Any]]:
    if payload is None:
        return []
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("data", "result", "searchTree", "rows"):
            inner = payload.get(key)
            if isinstance(inner, list):
                return [row for row in inner if isinstance(row, dict)]
    return []


def _article_rows(payload: dict | list | None) -> list[dict[str, Any]]:
    if payload is None:
        return []
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("data", "result", "articles", "rows"):
            inner = payload.get(key)
            if isinstance(inner, list):
                return [row for row in inner if isinstance(row, dict)]
    return []


def _search_terms(query: str, intent: str) -> tuple[str, ...]:
    folded = _fold(query)
    terms: list[str] = []
    if intent == "oil" or "масл" in folded:
        terms.extend(["масл", "моторн"])
        if "фильтр" in folded:
            terms.append("фильтр")
        return tuple(dict.fromkeys(terms))
    if intent == "brake" or any(x in folded for x in ("тормоз", "колод", "суппорт", "диск")):
        if "диск" in folded:
            terms.extend(["диск", "тормоз"])
        if "колод" in folded:
            terms.extend(["колод", "тормоз"])
        if "суппорт" in folded:
            terms.append("суппорт")
        if not terms:
            terms.append("тормоз")
    if "наконечник" in folded:
        terms.extend(["наконечник", "рул"])
    if "тяга" in folded and ("рул" in folded or "рулев" in folded):
        terms.extend(["тяга", "рул"])
    elif "рулев" in folded or re.search(r"(^|[^а-я])рул[^а-я]", folded):
        if any(x in folded for x in ("наконечник", "тяга", "рейк", "насос")):
            terms.append("рул")
    if "шаров" in folded and "опор" in folded:
        terms.extend(["шаров", "опор"])
    if "сайлент" in folded:
        terms.append("сайлент")
    if "рычаг" in folded:
        terms.append("рычаг")
    if "стойк" in folded and "стабил" in folded:
        terms.extend(["стойк", "стабил"])
    if "перед" in folded or re.search(r"(^|[^а-я])пер[^а-я]", folded):
        terms.append("перед")
    if "зад" in folded:
        terms.append("зад")
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
    if best_score < 2 and len(terms) >= 2:
        return None, ""
    return best_id, best_label


def search_catalog_lines(vin: str, query: str, intent: str) -> tuple[str, ...]:
    """Синхронный вызов PartsAPI. Пустой кортеж — нет ключей, VIN или подходящей группы."""
    row = _vin_row(vin)
    if not row or not row.get("carId"):
        return ()
    try:
        car_id = int(row["carId"])
    except (TypeError, ValueError):
        return ()

    tree_payload = call_method(
        "getSearchTree",
        lang=str(_TECDOC_LANG_RU),
        carId=str(car_id),
        carType=str(_CAR_TYPE_PASSENGER),
    )
    terms = _search_terms(query, intent)
    str_id, group_label = _pick_group_id(_tree_rows(tree_payload), terms)
    if str_id is None:
        return ()

    articles_payload = call_method(
        "getArticles",
        lang=str(_TECDOC_LANG_RU),
        strId=str(str_id),
        carId=str(car_id),
        carType=str(_CAR_TYPE_PASSENGER),
    )
    rows = _article_rows(articles_payload)
    if not rows:
        return ()

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
        if brand:
            lines.append(f"• {prefix}{brand} {number}".strip())
        else:
            lines.append(f"• {prefix}{number}".strip())
        if len(lines) >= _MAX_LINES:
            break
    if len(seen) > _MAX_LINES:
        lines.append(f"• … ещё {len(seen) - _MAX_LINES} позиций в TecDoc")
    return tuple(lines)
