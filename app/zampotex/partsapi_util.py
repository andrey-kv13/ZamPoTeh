"""Разбор ответов PartsAPI (разные обёртки и регистр полей)."""

from __future__ import annotations

from typing import Any


def upper_row(row: dict[str, Any]) -> dict[str, Any]:
    return {str(key).upper(): value for key, value in row.items()}


def extract_rows(payload: dict | list | None, *prefer_keys: str) -> list[dict[str, Any]]:
    if payload is None:
        return []
    if isinstance(payload, list):
        return [upper_row(item) for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in prefer_keys:
        inner = payload.get(key)
        if isinstance(inner, list):
            return [upper_row(item) for item in inner if isinstance(item, dict)]
    for key, inner in payload.items():
        if key.lower() in {"error", "err", "message", "status"}:
            continue
        if isinstance(inner, list) and inner and isinstance(inner[0], dict):
            return [upper_row(item) for item in inner]
    if any(k.upper() in payload or k in payload for k in ("NODE_1_TEXT", "ART_ARTICLE_NR", "CARID")):
        return [upper_row(payload)]
    return []


def api_error_text(payload: dict | list | None) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in ("error", "Error", "message", "Message", "description", "Description"):
        val = payload.get(key)
        if val:
            return str(val)
    status = payload.get("status") or payload.get("Status")
    if status in (0, "0", False, "error", "fail"):
        return str(payload)
    return None
