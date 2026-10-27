"""Pixabay — стоковые фото и видео (ключ pixabay.com/api/docs). Умеет искать на языке страны сцены."""
from __future__ import annotations

import urllib.parse

from ._http import http_json, keys

NAME = "pixabay"
LABEL = "Pixabay"
KINDS = ["image", "video"]
KEY = "pixabay"
PRIORITY = 0.75
STRICT_TEXT = True  # теги стока часто случайные — без проверки глазами нужно сильное совпадение


def search(q: str, kind: str, n: int, lang: str = "en") -> list[dict]:
    key = keys().get("pixabay")
    if not key:
        return []
    out = []
    if kind == "video":
        url = "https://pixabay.com/api/videos/?" + urllib.parse.urlencode({"key": key, "q": q[:100], "per_page": min(40, max(3, n * 4)), "safesearch": "true",
                                                                          "lang": _lang(lang)})
        for v in http_json(url).get("hits", []):
            vv = v.get("videos") or {}
            f = vv.get("medium") if (vv.get("medium") or {}).get("url") else vv.get("large")
            if not f or not f.get("url"):
                continue
            out.append({"source": "pixabay", "type": "video", "url": f["url"], "thumb": (vv.get("tiny") or {}).get("thumbnail") or (vv.get("medium") or {}).get("thumbnail"),
                        "page": v.get("pageURL"), "title": v.get("tags", q), "author": v.get("user", ""), "license": "pixabay",
                        "license_url": "https://pixabay.com/service/license-summary/", "width": f.get("width", 0), "height": f.get("height", 0),
                        "duration": v.get("duration")})
    else:
        url = "https://pixabay.com/api/?" + urllib.parse.urlencode({"key": key, "q": q[:100], "image_type": "photo", "orientation": "horizontal",
                                                                   "min_width": 1600, "per_page": min(40, max(3, n * 4)), "safesearch": "true",
                                                                   "lang": _lang(lang)})
        for p in http_json(url).get("hits", []):
            out.append({"source": "pixabay", "type": "image", "url": p.get("largeImageURL"), "thumb": p.get("webformatURL"),
                        "page": p.get("pageURL"), "title": p.get("tags", q), "author": p.get("user", ""), "license": "pixabay",
                        "license_url": "https://pixabay.com/service/license-summary/", "width": p.get("imageWidth", 0),
                        "height": p.get("imageHeight", 0)})
    return out


def _lang(lang: str) -> str:
    from regions import PIXABAY_LANGS
    return lang if lang in PIXABAY_LANGS else "en"
