"""Wikimedia Commons — фото и видео со свободными лицензиями, без ключа."""
from __future__ import annotations

import urllib.parse

from . import is_specific
from ._http import http_json, strip_html
from ._license import norm_license

NAME = "commons"
LABEL = "Wikimedia Commons"
KINDS = ["image", "video", "news", "amateur", "document"]
KEY = None
PRIORITY = 0.9
CHECK_NOT_FREE = True


def wants(q: str, kind: str) -> bool:
    """Видео — только по конкретному запросу (имя, название, год): на общих видео-запросах («family eating pie»)
    EP-13+14 — 376 кадров на проверку глазами → 5 скачано. Фото, хроника, газеты — всегда (там Commons лучший)."""
    return kind != "video" or is_specific(q)


def search(q: str, kind: str, n: int, lang: str = "en") -> list[dict]:
    if kind == "news":  # хроника: и видео, и фото событий
        return _search(q, "filetype:video", n) + _search(q, "filetype:bitmap", n)
    return _search(q, "filetype:video" if kind in ("video", "amateur") else "filetype:bitmap", n)


def _search(q: str, ft: str, n: int) -> list[dict]:
    url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode({
        "action": "query", "format": "json", "generator": "search", "gsrsearch": f"{q} {ft}", "gsrnamespace": 6,
        "gsrlimit": min(40, n * 4), "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata", "iiurlwidth": 2400})
    out = []
    pages = (http_json(url).get("query") or {}).get("pages") or {}
    for p in sorted(pages.values(), key=lambda x: x.get("index", 0)):
        ii = (p.get("imageinfo") or [{}])[0]
        md = ii.get("extmetadata") or {}
        val = lambda k: strip_html((md.get(k) or {}).get("value", ""))  # noqa: E731
        lic = norm_license(val("LicenseShortName") or val("UsageTerms"))
        is_video = (ii.get("mime") or "").startswith("video")
        out.append({"source": "commons", "type": "video" if is_video else "image",
                    "url": ii.get("url") if is_video else (ii.get("thumburl") or ii.get("url")),
                    "thumb": ii.get("thumburl") or ii.get("url"), "page": ii.get("descriptionurl"),
                    "title": p.get("title", "").replace("File:", ""), "author": val("Artist")[:120] or val("Credit")[:120],
                    "license": lic, "license_url": val("LicenseUrl"), "width": ii.get("width") or 0, "height": ii.get("height") or 0,
                    "license_name": val("LicenseShortName"), "pageid": p.get("pageid"),
                    "text": val("ImageDescription")[:400]})
    return out
