"""Общее для источников loc.gov (loc, newspapers)."""
from __future__ import annotations

import re


def biggest(urls: list[str]) -> str | None:
    """Самая крупная картинка из списка loc.gov; у IIIF-сервера просим крупную версию."""
    best, bw = None, -1
    for u in urls or []:
        m = re.search(r"#h=(\d+)&w=(\d+)", u)
        w = int(m.group(2)) if m else 0
        if w > bw:
            best, bw = u.split("#")[0], w
    if best and "/iiif/" in best:
        best = re.sub(r"/full/[^/]+/", "/full/pct:50/", best)
    return best
