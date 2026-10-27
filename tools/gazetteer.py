"""Справочник мест для карт: data/places.json (название → широта, долгота).

Данные в JSON, не в коде: справочник пополняется на шаге 0 (паспорт эпизода) после подтверждения Nurlan.
В метке можно дать координаты прямо: [КАРТА: … | Hueytown(33.45, -86.99)].
"""
from __future__ import annotations

from util import ROOT, load_json

PLACES_FILE = ROOT / "data" / "places.json"


def _index() -> dict[str, tuple[float, float]]:
    """Все названия и синонимы (в нижнем регистре) → (долгота, широта) — порядок, который ждёт карта."""
    out = {}
    for name, p in (load_json(PLACES_FILE, {}) or {}).items():
        if name.startswith("_") or not isinstance(p, dict):
            continue
        for n in [name, *p.get("aliases", [])]:
            out[n.strip().lower()] = (float(p["lon"]), float(p["lat"]))
    return out


def lookup(name: str) -> tuple[float, float] | None:
    """Координаты места (долгота, широта) или None, если места нет в справочнике."""
    return _index().get(name.strip().lower())
