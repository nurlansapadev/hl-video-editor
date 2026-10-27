"""Лицензии: разбор записей источников в короткий код и тексты для титров.

Можно только: pd, cc0, by (с автором), by-sa (если "allowShareAlike": true), лицензии стоков pexels/pixabay/unsplash.
NC и ND (некоммерческие, без изменений) — никогда.
"""
from __future__ import annotations

import re

# признаки несвободных фото в описаниях (агентства, «все права защищены»)
NOT_FREE = ("getty", "reuters", "associated press", "ap photo", "afp", "©", "copyright", "all rights reserved", "courtesy of")

LICENSE_TEXT = {"pd": "Public domain", "cc0": "CC0", "by": "CC BY", "by-sa": "CC BY-SA", "own": "Own footage",
                "pexels": "Pexels License", "pixabay": "Pixabay Content License", "unsplash": "Unsplash License"}


def norm_license(raw: str) -> str | None:
    """Приводим разные записи лицензий к коду: pd, cc0, by, by-sa. None — нельзя (NC, ND, неизвестная)."""
    r = (raw or "").lower().replace("_", "-")
    if not r:
        return None
    if "-nc" in r or "noncommercial" in r or "non-commercial" in r or "-nd" in r or "noderiv" in r or " nc" in r or " nd" in r:
        return None
    if "cc0" in r or "cc-zero" in r:
        return "cc0"
    if "public domain" in r or r in ("pd", "pdm") or r.startswith("pd-") or "no known restrictions" in r or "publicdomain" in r:
        return "pd"
    if "by-sa" in r or "by sa" in r:
        return "by-sa"
    if re.search(r"\bcc[- ]by\b|^by$|^by[- ]\d", r) or r == "cc-by":
        return "by"
    return None
