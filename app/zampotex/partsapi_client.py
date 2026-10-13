"""Клиент PartsAPI (partsapi.ru). Ключ — отдельно на каждый купленный метод."""

from __future__ import annotations

import json
import logging
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from zampotex.config import get_settings

logger = logging.getLogger("zampotex.partsapi")

BASE = "https://partsapi.ru/method"


def _key_for_method(method: str) -> str | None:
    settings = get_settings()
    mapping = settings.partsapi_keys
    return mapping.get(method) or mapping.get(method.lower())


def call_method(method: str, **params: str) -> dict | list | None:
    """GET https://partsapi.ru/method/{Method}?key=...&param=value"""
    key = _key_for_method(method)
    if not key:
        return None
    query = {"key": key, **{k: v for k, v in params.items() if v is not None}}
    url = f"{BASE}/{method}?{urlencode(query)}"
    try:
        request = Request(url, headers={"User-Agent": "ZamPoTeh/1.0"})
        with urlopen(request, timeout=20) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except (HTTPError, URLError, TimeoutError) as exc:
        logger.info("PartsAPI %s: %s", method, exc)
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.info("PartsAPI %s: non-JSON response", method)
        return None


def vindecode(vin: str, lang: str = "ru") -> dict | list | None:
    return call_method("VINdecode", vin=vin.upper(), lang=lang)


def vindecode_oe(vin: str) -> dict | list | None:
    return call_method("VINdecodeOE", vin=vin.upper())


def catalog_api_configured() -> bool:
    settings = get_settings()
    keys = settings.partsapi_keys
    return bool(keys.get("VINdecode") and keys.get("getSearchTree") and keys.get("getArticles"))


def summarize_vindecode(payload: dict | list | None) -> tuple[str, ...]:
    if not payload:
        return ()
    row = payload[0] if isinstance(payload, list) and payload else payload
    if not isinstance(row, dict):
        return ()
    bits: list[str] = []
    for label, key in (
        ("марка", "manuName"),
        ("модель", "modelName"),
        ("модификация", "typeName"),
        ("топливо", "fuelType"),
        ("кузов", "constructionType"),
        ("привод", "impulsionType"),
    ):
        val = row.get(key)
        if val:
            bits.append(f"{label}: {val}")
    if row.get("carId"):
        bits.append(f"TecDoc carId: {row['carId']}")
    motors = row.get("motorCodes")
    if motors:
        bits.append(f"код двигателя: {motors}")
    return tuple(bits) if bits else ("TecDoc VINdecode ответил без полей марки/модели",)
