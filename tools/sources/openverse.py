"""Openverse — сводный каталог свободных изображений (Flickr, музеи, Wikimedia…), без ключа."""
from __future__ import annotations

import urllib.parse

from ._http import http_json
from ._license import norm_license

NAME = "openverse"
LABEL = "Openverse"
KINDS = ["image", "news", "document"]
KEY = None
PRIORITY = 0.8
STRICT_TEXT = True  # теги Flickr часто случайные — без проверки глазами нужно сильное совпадение
CHECK_NOT_FREE = True


def search(q: str, kind: str, n: int, lang: str = "en") -> list[dict]:
    if kind == "video":
        return []
    url = "https://api.openverse.org/v1/images/?" + urllib.parse.urlencode(
        {"q": q, "license_type": "commercial,modification", "page_size": min(40, n * 4), "mature": "false"})
    out = []
    for r in http_json(url, host_delay=1.2).get("results", []):
        out.append({"source": "openverse", "type": "image", "url": r.get("url"), "thumb": r.get("thumbnail") or r.get("url"),
                    "page": r.get("foreign_landing_url"), "title": r.get("title") or "", "author": r.get("creator") or "",
                    "license": norm_license(r.get("license", "")), "license_url": r.get("license_url"),
                    "width": r.get("width") or 0, "height": r.get("height") or 0, "provider": r.get("provider") or ""})
    return out
