"""NASA Image and Video Library — фото и видео NASA (общественное достояние), без ключа."""
from __future__ import annotations

import urllib.parse

from ._http import http_json
from ._license import NOT_FREE

NAME = "nasa"
LABEL = "NASA"
KINDS = ["image", "video", "news", "document"]
KEY = None
PRIORITY = 0.9


def search(q: str, kind: str, n: int, lang: str = "en") -> list[dict]:
    mt = "video" if kind in ("video", "news") else "image"
    if kind == "amateur":
        return []
    url = "https://images-api.nasa.gov/search?" + urllib.parse.urlencode({"q": q, "media_type": mt, "page_size": min(40, n * 4)})
    out = []
    for it in (http_json(url).get("collection") or {}).get("items", []):
        d = (it.get("data") or [{}])[0]
        credit = " ".join(str(d.get(k, "")) for k in ("secondary_creator", "photographer", "description_508", "description"))
        if any(x in credit.lower() for x in NOT_FREE):
            continue  # снимки сторонних агентств внутри архива NASA
        thumb = next((l.get("href") for l in it.get("links", []) if l.get("render") == "image"), None)
        out.append({"source": "nasa", "type": mt, "nasa_id": d.get("nasa_id"), "url": None, "thumb": thumb,
                    "page": f"https://images.nasa.gov/details/{d.get('nasa_id')}", "title": d.get("title", ""),
                    "author": d.get("secondary_creator") or "NASA", "license": "pd", "license_url": "https://www.nasa.gov/nasa-brand-center/images-and-media/",
                    "width": 0, "height": 0, "text": (d.get("description") or "")[:400]})
    return out


def resolve(c: dict) -> str | None:
    """Ссылка на сам файл: в поиске NASA отдаёт только превью. В номере бывают пробелы («Apollo 14 Launch Coverage»)."""
    asset = f"https://images-api.nasa.gov/asset/{urllib.parse.quote(str(c['nasa_id']))}"
    files = [i.get("href", "") for i in (http_json(asset).get("collection") or {}).get("items", [])]
    prefs = ["~orig.mp4", "~large.mp4", "~medium.mp4"] if c["type"] == "video" else ["~large.jpg", "~orig.jpg", "~medium.jpg"]
    for p in prefs:
        for f in files:
            if f.endswith(p):
                return urllib.parse.quote(f.replace("http://", "https://"), safe=":/~%")
    return None
