"""Unsplash — фото (ключ unsplash.com/developers; лимит 50 запросов в час). Умеет искать на языке страны сцены."""
from __future__ import annotations

import time
import urllib.parse
import urllib.request

from util import log

from ._http import http_json, keys

NAME = "unsplash"
LABEL = "Unsplash"
KINDS = ["image", "news"]
KEY = "unsplash"

PER_HOUR = 49  # лимит Unsplash — 50 запросов в час; на 50-м отвечает 403, и мы теряли источник до конца поиска
_calls: list[float] = []
_told = False


def _take() -> bool:
    """Можно ли ещё обратиться к Unsplash в этот час (поиск и отметки скачиваний считаются вместе)."""
    global _told
    now = time.time()
    _calls[:] = [t for t in _calls if now - t < 3600]
    if len(_calls) >= PER_HOUR:
        if not _told:
            _told = True
            log(f"    · unsplash: {PER_HOUR} запросов за час — пропускаю его, пока лимит не освободится")
        return False
    _calls.append(now)
    return True


def search(q: str, kind: str, n: int, lang: str = "en") -> list[dict]:
    key = keys().get("unsplash")
    if not key or kind not in ("image", "news") or not _take():
        return []
    url = "https://api.unsplash.com/search/photos?" + urllib.parse.urlencode(
        {"query": q, "per_page": min(30, max(10, n * 4)), "orientation": "landscape", "content_filter": "high",
         **({"lang": lang} if lang and lang != "en" else {})})
    out = []
    for p in http_json(url, headers={"Authorization": f"Client-ID {key}", "Accept-Version": "v1"}, host_delay=1.0).get("results", []):
        urls = p.get("urls") or {}
        raw = urls.get("raw") or urls.get("full")
        if not raw:
            continue
        out.append({"source": "unsplash", "type": "image", "url": raw + ("&" if "?" in raw else "?") + "w=2400&fm=jpg&q=85",
                    "thumb": urls.get("small") or urls.get("regular"), "page": (p.get("links") or {}).get("html"),
                    "title": p.get("alt_description") or p.get("description") or q, "author": (p.get("user") or {}).get("name", ""),
                    "license": "unsplash", "license_url": "https://unsplash.com/license", "width": p.get("width", 0),
                    "height": p.get("height", 0), "ping": (p.get("links") or {}).get("download_location"),
                    "text": " ".join(t.get("title", "") for t in (p.get("tags") or []) if isinstance(t, dict))[:300]})
    return out


def on_saved(c: dict) -> None:
    """Unsplash просит отмечать скачивания (правила их API)."""
    if c.get("ping") and _take():
        try:
            req = urllib.request.Request(c["ping"], headers={"Authorization": f"Client-ID {keys().get('unsplash', '')}"})
            urllib.request.urlopen(req, timeout=15).read()
        except Exception:  # noqa: BLE001
            pass
