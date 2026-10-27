"""Определение страны сцены — для поиска материалов (кадры из той же страны, запрос на её языке).

Страны и слова-признаки — в data/countries.json (только английский); пополняется на шаге 0 (паспорт эпизода).
Главная страна эпизода берётся из паспорта (06_montage/context.json); project_region — только запасной вариант.
"""
from __future__ import annotations

import re
from collections import Counter

from scriptparse import norm
from util import ROOT, load_json

COUNTRIES_FILE = ROOT / "data" / "countries.json"

# языки, на которых Pixabay умеет искать (параметр lang)
PIXABAY_LANGS = {"cs", "da", "de", "en", "es", "fr", "id", "it", "hu", "nl", "no", "pl", "pt", "ro", "sk", "fi", "sv", "tr",
                 "vi", "th", "bg", "ru", "el", "ja", "ko", "zh"}


def countries() -> dict[str, dict]:
    """{"USA": {"lang": "en", "words": [...]}, …} без служебных полей."""
    data = load_json(COUNTRIES_FILE, {}) or {}
    return {k: v for k, v in data.items() if not k.startswith("_") and isinstance(v, dict)}


def _nstem(st: str) -> str:
    exact = st.endswith("$")  # «thai$» — только целое слово (не «thailand»)
    return " ".join(norm(w) for w in st.rstrip("$").lower().split()) + ("$" if exact else "")


def _text_norm(text: str) -> str:
    """Нижний регистр, без ударений и дефисов."""
    return " " + " ".join(norm(w) for w in re.findall(r"[\w\-]+", text.lower())) + " "


def count_countries(text: str) -> Counter:
    t = _text_norm(text)
    c: Counter = Counter()
    for country, info in countries().items():
        stems = [_nstem(s) for s in info.get("words", [])]
        n = sum(len(re.findall(r"(?<=\s)" + (re.escape(s[:-1]) + r"(?=\s)" if s.endswith("$") else re.escape(s)), t))
                for s in stems if s)
        if n:
            c[country] += n
    return c


def project_region(script_text: str) -> str | None:
    """Запасной вариант, если в паспорте эпизода страна не указана: самая частая, если явно преобладает."""
    c = count_countries(re.sub(r"\[[^\]]*\]", " ", script_text) + " " + " ".join(re.findall(r"\[[^\]]*\]", script_text)))
    if not c:
        return None
    (top, n), = c.most_common(1)
    total = sum(c.values())
    return top if n >= 2 and n / total >= 0.4 else None


def scene_region(scene_text: str, query: str, default: str | None) -> str | None:
    """Страна конкретной сцены. Другая страна вместо главной — только если:
    • она названа в самом запросе («jungle Vietnam 1972»), или
    • в тексте сцены упомянута минимум дважды и чаще главной (сцена действительно там).
    Одно упоминание («Prime Minister of India» в сцене про Вашингтон) страну не меняет."""
    q = count_countries(query)
    if q:
        return q.most_common(1)[0][0]
    c = count_countries(scene_text)
    if c:
        top, n = c.most_common(1)[0]
        if top != default and n >= 2 and n > c.get(default or "", 0):
            return top
    return default


def region_lang(region: str | None) -> str | None:
    return (countries().get(region or "") or {}).get("lang")
