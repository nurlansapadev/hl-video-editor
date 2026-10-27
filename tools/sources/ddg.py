"""DuckDuckGo — поиск картинок по всему интернету (библиотека ddgs), без ключа.

Только ОБРАЗЦЫ для ReGen, в ролик напрямую не идёт (решение Nurlan, 2026-10-27): лицензию и автора DuckDuckGo
не сообщает, а фильтр license_image="ShareCommercially" ненадёжен (пропустил фото NY Post). Поэтому license="web":
finder отсеивает такие кадры из ролика и, если свободных не хватило, кладёт лучшие как образцы refs/s_<шот>_N —
по ним ReGen рисует свой кадр (композиция источника, своя картинка — без чужих прав и без «шаблонности»).

ДОРАБОТАТЬ (не срочно, может и не понадобиться): если страница картинки — Wikimedia, Flickr, NASA, .mil,
проверять лицензию через API этого сайта и подтверждённые кадры пускать в ролик как обычные.

Ограничение: DuckDuckGo считает нагрузку по IP — пауза перед каждым запросом, при «слишком часто» — пауза больше,
после нескольких отказов подряд источник выключается до конца поиска (в отчёте — колонка «блок»).
"""
from __future__ import annotations

import time

from ._http import SourceBlocked

NAME = "ddg"
LABEL = "DuckDuckGo"
KINDS = ["image", "document"]
KEY = None
PRIORITY = 0.6
REFS_ONLY = True  # finder спрашивает его только когда свободных кадров на шот не хватило и нужен образец

PAUSE = 1.5  # секунд между запросами
MAX_REFUSALS = 3  # отказов «слишком часто» подряд — и источник выключается до конца поиска
_last = 0.0
_refusals = 0


def search(q: str, kind: str, n: int, lang: str = "en") -> list[dict]:
    global _last, _refusals
    if kind not in KINDS:
        return []
    if _refusals >= MAX_REFUSALS:
        raise SourceBlocked("duckduckgo.com")
    from ddgs import DDGS
    from ddgs.exceptions import DDGSException, RatelimitException
    glitches = 0  # разовые сбои библиотеки («malformed headers», 2026-10-27) — при повторе проходят
    for attempt in range(MAX_REFUSALS):
        wait = PAUSE - (time.time() - _last)
        if wait > 0:
            time.sleep(wait)
        try:
            res = DDGS().images(q, region="us-en", safesearch="moderate", license_image="ShareCommercially",
                                max_results=min(40, max(12, n * 4)))
            _last, _refusals = time.time(), 0
            break
        except RatelimitException:
            _last = time.time()
            _refusals += 1
            if _refusals >= MAX_REFUSALS:
                raise SourceBlocked("duckduckgo.com") from None
            time.sleep(10 * (attempt + 1))
        except DDGSException:
            _last = time.time()
            glitches += 1
            if glitches >= 2:
                raise
            time.sleep(3)
    else:
        return []
    out = []
    for r in res or []:
        if not r.get("image"):
            continue
        out.append({"source": "ddg", "type": "document" if kind == "document" else "image", "url": r["image"],
                    "thumb": r.get("thumbnail") or r["image"], "page": r.get("url"), "title": r.get("title") or "",
                    "author": r.get("source") or "", "license": "web", "license_url": "",
                    "width": _int(r.get("width")), "height": _int(r.get("height")), "text": r.get("source") or ""})
    return out


def _int(v) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0
