"""Internet Archive — старые фильмы в общественном достоянии (кладутся в library/ для выбора отрывка), без ключа."""
from __future__ import annotations

import urllib.parse

from ._http import http_json

NAME = "archive"
LABEL = "Internet Archive"
KINDS = ["film"]
KEY = None
PRIORITY = 0.8


def search(q: str, kind: str, n: int, lang: str = "en") -> list[dict]:
    if kind not in ("film",):
        return []
    query = f'({q}) AND mediatype:movies AND (licenseurl:*publicdomain* OR collection:prelinger)'
    url = "https://archive.org/advancedsearch.php?" + urllib.parse.urlencode(
        [("q", query), ("fl[]", "identifier"), ("fl[]", "title"), ("fl[]", "year"), ("fl[]", "licenseurl"), ("rows", min(20, n * 4)), ("output", "json")])
    out = []
    for d in (http_json(url).get("response") or {}).get("docs", []):
        ident = d.get("identifier")
        out.append({"source": "archive", "type": "film", "ident": ident, "url": None, "thumb": f"https://archive.org/services/img/{ident}",
                    "page": f"https://archive.org/details/{ident}", "title": d.get("title", ""), "author": "Internet Archive / Prelinger",
                    "license": "pd", "license_url": d.get("licenseurl") or "https://archive.org/details/prelinger", "width": 0, "height": 0,
                    "date": str(d.get("year", ""))})
    return out


def resolve(c: dict) -> str | None:
    """Самый крупный mp4 до 400 МБ."""
    md = http_json(f"https://archive.org/metadata/{c['ident']}")
    best = None
    for f in md.get("files", []):
        name = f.get("name", "")
        if name.lower().endswith(".mp4") and int(f.get("size") or 0) < 400 * 1024 * 1024:
            if best is None or int(f.get("size") or 0) > int(best.get("size") or 0):
                best = f
    return f"https://archive.org/download/{c['ident']}/{urllib.parse.quote(best['name'])}" if best else None
