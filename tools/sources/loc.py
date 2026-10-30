"""Библиотека Конгресса США — фото без ограничений, без ключа. Права проверяются перед скачиванием."""
from __future__ import annotations

import urllib.parse

from ._http import http_json
from ._loc_common import biggest

NAME = "loc"
LABEL = "Library of Congress"
KINDS = ["image", "document"]
KEY = None
PRIORITY = 0.9


def wants(q: str, kind: str) -> bool:
    """Только документы (Nurlan, EP-14): на фото LoC отвечает 403 и в EP-13/14 не дал ни одного кадра."""
    return kind == "document"


def search(q: str, kind: str, n: int, lang: str = "en") -> list[dict]:
    if kind == "video":
        return []
    url = "https://www.loc.gov/photos/?" + urllib.parse.urlencode({"q": q, "fo": "json", "c": min(40, n * 4)})
    out = []
    for r in http_json(url, host_delay=3.2).get("results", []):
        img = biggest(r.get("image_url"))
        if not img:
            continue
        out.append({"source": "loc", "type": "image", "url": img, "thumb": (r.get("image_url") or [img])[0].split("#")[0],
                    "page": r.get("url") or r.get("id"), "title": r.get("title", ""), "author": "Library of Congress",
                    "license": "check-loc", "license_url": "https://www.loc.gov/legal/", "width": 0, "height": 0,
                    "date": str(r.get("date", ""))})
    return out


def rights_ok(c: dict) -> bool:
    """Страница снимка: берём только «no known restrictions» / «public domain»."""
    if c.get("license") != "check-loc":
        return True
    try:
        item = http_json((c["page"].rstrip("/") + "/?fo=json"), host_delay=3.2).get("item") or {}
    except Exception:  # noqa: BLE001
        return False
    rights = " ".join(item.get("rights_advisory") or item.get("rights") or [])
    if "no known restrictions" in rights.lower() or "public domain" in rights.lower():
        c["license"] = "pd"
        c["author"] = ", ".join((item.get("contributor_names") or item.get("creators") or ["Library of Congress"])[:2])
        return True
    return False
