"""DVIDS — видео и фото госслужб США, общественное достояние (ключ dvidshub.net)."""
from __future__ import annotations

import json
import re
import urllib.parse

from ._http import http_json, keys, urls_in

NAME = "dvids"
LABEL = "DVIDS"
KINDS = ["image", "video", "news"]
KEY = "dvids"


def search(q: str, kind: str, n: int, lang: str = "en") -> list[dict]:
    key = keys().get("dvids")
    if not key or kind not in ("video", "news", "image"):
        return []
    t = "image" if kind == "image" else "video"
    url = "https://api.dvidshub.net/search?" + urllib.parse.urlencode(
        [("api_key", key), ("q", q), ("type[]", t), ("max_results", min(30, max(10, n * 4)))])
    out = []
    for r in (http_json(url, host_delay=1.0).get("results") or []):
        if not isinstance(r, dict):
            continue
        th = r.get("thumbnail")
        thumb = th.get("url") if isinstance(th, dict) else th
        if not thumb:
            thumb = next(iter(urls_in(r, ("jpg", "jpeg", "png"))), None)
        out.append({"source": "dvids", "type": t, "url": None, "dvids_id": r.get("id"), "thumb": thumb,
                    "page": r.get("url") or f"https://www.dvidshub.net/{t}/{str(r.get('id', '')).split(':')[-1]}",
                    "title": r.get("title", ""), "author": "DVIDS / U.S. Department of Defense", "license": "pd",
                    "license_url": "https://www.dvidshub.net/about/copyright", "width": 0, "height": 0,
                    "date": str(r.get("date_published") or r.get("publishdate") or "")[:10],
                    "text": str(r.get("short_description") or r.get("description") or "")[:400]})
    return out


def resolve(c: dict) -> str | None:
    """Ссылка на сам файл; чужие права внутри архива — не берём."""
    key = keys().get("dvids")
    res = http_json("https://api.dvidshub.net/asset?" + urllib.parse.urlencode({"api_key": key, "id": c.get("dvids_id")}))
    body = json.dumps(res).lower()
    if any(x in body for x in ("all rights reserved", "copyrighted", "getty", "reuters", "associated press")):
        return None
    if c["type"] == "video":
        files = [f for f in urls_in(res, ("mp4",))]
        files.sort(key=lambda u: (0 if re.search(r"1280|720|1920|1080|hd", u, re.I) else 1))
        return files[0] if files else None
    imgs = urls_in(res, ("jpg", "jpeg", "png"))
    return imgs[0] if imgs else None
