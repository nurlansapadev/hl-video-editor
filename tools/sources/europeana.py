"""Europeana — европейские архивы и музеи, без ключа (открытый демонстрационный ключ)."""
from __future__ import annotations

import re
import urllib.parse

from ._http import http_json, keys

NAME = "europeana"
LABEL = "Europeana"
KINDS = ["image", "video", "news", "amateur", "document"]
KEY = None
REGIONS = "europe"  # спрашивается только для запросов про европейскую страну (Nurlan, EP-14)


def _license(rights: str) -> str | None:
    r = (rights or "").lower()
    if "publicdomain" in r:
        return "pd"
    if "/licenses/by-sa/" in r:
        return "by-sa"
    if "/licenses/by/" in r:
        return "by"
    return None


def search(q: str, kind: str, n: int, lang: str = "en") -> list[dict]:
    key = keys().get("europeana") or "api2demo"  # открытый демонстрационный ключ Europeana
    t = {"image": "IMAGE", "document": "TEXT", "video": "VIDEO", "news": "VIDEO", "amateur": "VIDEO"}.get(kind)
    if not t:
        return []
    url = "https://api.europeana.eu/record/v2/search.json?" + urllib.parse.urlencode(
        [("wskey", key), ("query", q), ("rows", min(40, max(12, n * 4))), ("media", "true"), ("reusability", "open"),
         ("qf", f"TYPE:{t}"), ("profile", "rich")])
    out = []
    for it in http_json(url, host_delay=1.0).get("items", []):
        lic = _license((it.get("rights") or [""])[0])
        media_url = (it.get("edmIsShownBy") or [None])[0]
        if not lic or not media_url:
            continue
        is_video = t == "VIDEO"
        if is_video and not re.search(r"\.(mp4|webm|mov)(\?|$)", media_url, re.I):
            continue  # только прямые ссылки на файлы, без плееров
        title = (it.get("title") or [""])[0]
        out.append({"source": "europeana", "type": "video" if is_video else ("document" if t == "TEXT" else "image"),
                    "url": media_url, "thumb": (it.get("edmPreview") or [media_url])[0], "page": it.get("guid"),
                    "title": title, "author": ((it.get("dcCreator") or []) + (it.get("dataProvider") or ["Europeana"]))[0],
                    "license": lic, "license_url": (it.get("rights") or [""])[0], "width": 0, "height": 0,
                    "date": str((it.get("year") or [""])[0]), "text": " ".join((it.get("dcDescription") or [])[:1])[:400]})
    return out
