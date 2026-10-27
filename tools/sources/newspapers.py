"""Chronicling America — газеты США до 1928 года (общественное достояние), без ключа."""
from __future__ import annotations

import re
import urllib.parse

from ._http import http_json
from ._loc_common import biggest

NAME = "newspapers"
LABEL = "Chronicling America"
KINDS = ["document"]
KEY = None
PRIORITY = 1.0


def search(q: str, kind: str, n: int, lang: str = "en") -> list[dict]:
    if kind == "video":
        return []
    url = "https://www.loc.gov/collections/chronicling-america/?" + urllib.parse.urlencode(
        {"q": q, "fo": "json", "c": min(30, n * 3), "dates": "1777/1928"})
    out = []
    for r in http_json(url, host_delay=3.2).get("results", []):
        year = re.search(r"(1[6-9]\d\d)", str(r.get("date", "")))
        if not year or int(year.group(1)) > 1928:
            continue  # позже 1928 года — возможны права, не берём
        img = biggest(r.get("image_url"))
        if not img:
            continue
        paper = (r.get("partof_title") or r.get("partof") or [""])
        paper = paper[0] if isinstance(paper, list) and paper else str(paper)
        out.append({"source": "newspapers", "type": "document", "url": img, "thumb": (r.get("image_url") or [img])[0].split("#")[0],
                    "page": r.get("url") or r.get("id"), "title": r.get("title", ""), "author": paper or "Chronicling America",
                    "license": "pd", "license_url": "https://www.loc.gov/collections/chronicling-america/about-this-collection/rights-and-access/",
                    "width": 0, "height": 0, "date": str(r.get("date", ""))})
    return out
