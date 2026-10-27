"""Tavily — поисковый API для ИИ-агентов (ключ tavily.com → keys.json "tavily"; бесплатно 1000 кредитов в месяц).

Как DuckDuckGo: лицензию и автора не даёт → license="web", только ОБРАЗЦЫ для ReGen, в ролик напрямую не идёт.
Запасной к DuckDuckGo: finder спрашивает его, только если DuckDuckGo не дал ни одного образца
(ничего не нашёл или заблокирован) — так бесплатных кредитов хватает на месяц.

Счётчик кредитов: data/tavily_usage.json {"2026-10": 37}. Один запрос basic = 1 кредит.
Дошли до LIMIT за месяц — источник молча выключается до следующего месяца (в журнале — одна строка).
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request

from util import ROOT, load_json, log, save_json

from ._http import SourceBlocked, keys

NAME = "tavily"
LABEL = "Tavily"
KINDS = ["image", "document"]
KEY = "tavily"
PRIORITY = 0.6
REFS_ONLY = True

LIMIT = 950  # кредитов в месяц (бесплатно 1000 — запас на ручные пробы)
USAGE = ROOT / "data" / "tavily_usage.json"
_told = False
_blocked = ""  # причина, если Tavily отказал (ключ, лимит) — до конца поиска не спрашиваем


def _month() -> str:
    return time.strftime("%Y-%m")


def used() -> int:
    """Сколько кредитов Tavily потрачено в этом месяце."""
    return int((load_json(USAGE, {}) or {}).get(_month(), 0))


def _spend(n: int) -> None:
    data = load_json(USAGE, {}) or {}
    data[_month()] = int(data.get(_month(), 0)) + n
    save_json(USAGE, data)


def search(q: str, kind: str, n: int, lang: str = "en") -> list[dict]:
    global _told, _blocked
    key = keys().get("tavily")
    if not key or kind not in KINDS:
        return []
    if _blocked:
        raise SourceBlocked(_blocked)
    if used() >= LIMIT:
        if not _told:
            _told = True
            log(f"    · tavily: за {_month()} потрачено {used()} кредитов из {LIMIT} — пропускаю до следующего месяца")
        return []
    body = {"query": q, "search_depth": "basic", "include_images": True, "include_image_descriptions": True,
            "max_results": 5}
    req = urllib.request.Request("https://api.tavily.com/search", data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            res = json.loads(r.read().decode("utf-8", errors="ignore"))
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 429, 432, 433):  # ключ неверный / лимит тарифа — до конца поиска не трогаем
            _blocked = f"api.tavily.com (HTTP {e.code})"
            raise SourceBlocked(_blocked) from None
        raise
    _spend(1)
    out = []
    for im in res.get("images") or []:
        url, desc = (im.get("url"), im.get("description") or "") if isinstance(im, dict) else (im, "")
        if not url:
            continue
        out.append({"source": "tavily", "type": "document" if kind == "document" else "image", "url": url, "thumb": url,
                    "page": "", "title": desc[:200] or q, "author": urllib.parse.urlparse(url).netloc,
                    "license": "web", "license_url": "", "width": 0, "height": 0, "text": desc[:400]})
    return out
