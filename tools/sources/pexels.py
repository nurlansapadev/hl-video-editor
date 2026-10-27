"""Pexels — стоковые фото и видео (ключ pexels.com/api).

ЗАГЛУШКА: ключа Pexels пока нет. Рабочая версия — в VideoEditor/tools/finder.py (src_pexels), перенести при появлении ключа.
"""
from __future__ import annotations

NAME = "pexels"
LABEL = "Pexels"
KINDS = ["image", "video"]
KEY = "pexels"
PRIORITY = 0.85


def search(q: str, kind: str, n: int, lang: str = "en") -> list[dict]:
    return []
