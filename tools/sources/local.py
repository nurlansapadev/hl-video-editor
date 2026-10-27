"""Свои кадры эпизода (05_footage, 03_generated, 02_characters) — раньше интернета.
Кандидаты из каталога описаний (local_index.py), подбор по словам запроса."""
from __future__ import annotations

import re
from pathlib import Path

NAME = "local"
LABEL = ""
KINDS = ["image", "video", "news", "amateur"]
KEY = None
PRIORITY = 1.0

DIRS: list[Path] = []  # папки эпизода — задаёт finder перед поиском
TYPES = {"image": ("image",), "video": ("video",), "news": ("video", "image"), "amateur": ("video",)}


def search(q: str, kind: str, n: int, lang: str = "en") -> list[dict]:
    """Фото из реестра (02_characters, «subject» = имя из cast.json): если имя целиком есть в запросе —
    кандидат «trusted» (Nurlan отобрал сам; проверка глазами лицо не узнаёт, поэтому её пропускаем)."""
    from local_index import load
    types = TYPES.get(kind)
    if not types:
        return []
    ql = q.lower()
    words = [w for w in re.findall(r"\w{3,}", ql)]
    out = []
    for folder in DIRS:
        for it in load(folder).values():
            if it.get("type") not in types or not Path(it["file"]).exists():
                continue
            subject = it.get("subject") or ""
            text = f"{subject} {it.get('caption', '')} {' '.join(it.get('tags') or [])} {it.get('era', '')} {it['name']}".lower()
            match = sum(1 for w in words if w in text) / max(1, len(words))
            trusted = bool(subject) and all(w in ql for w in re.findall(r"\w{3,}", subject.lower()))
            if trusted:
                match = 2.0  # фото именно этого человека / места / объекта — выше любых совпадений по описанию
            if match <= 0:
                continue
            if it.get("subject_kind") == "person" and not trusted:
                continue  # портрет человека — только в шоты с его именем (EP-09: гравюра Tunney ушла в шот McGoff по слову «John»)
            out.append({"source": "local", "type": it["type"], "url": Path(it["file"]).as_uri(),
                        "thumb": Path(it["thumb"]).as_uri(), "page": "", "title": subject or it.get("caption") or it["name"],
                        "text": " ".join(it.get("tags") or []), "author": "", "license": "own", "license_url": "",
                        "width": it.get("width") or 1920, "height": it.get("height") or 1080,
                        "duration": it.get("duration"), "match": match, "trusted": trusted})
    out.sort(key=lambda c: -c["match"])
    return out[:12]
