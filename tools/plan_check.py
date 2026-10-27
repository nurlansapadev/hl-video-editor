"""Шаг 4, проверка плана до сводки (с EP-10): то, что раньше ловили только на контрольном листе после рендера.

  .venv/Scripts/python.exe tools/plan_check.py ep-10

Печатает: значения счётчиков и диаграмм (подпись «$» или пропавший % — ошибка разметки), кадры короче 2 с,
несуществующие src, повтор трека по главам, повторы картинок по хэшу 16×16 (≤ 20 бит из 256 — один снимок).
Гравюры людей (общий синий фон) часто дают ложное сходство — их пары не браковать.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

from util import edit_dir, load_json, log

SAME_BITS = 20


def thumb(path: Path, video: bool):
    if video:
        raw = subprocess.run(["ffmpeg", "-v", "quiet", "-ss", "1", "-i", str(path), "-frames:v", "1", "-vf", "scale=16:16",
                              "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True).stdout
        h = np.frombuffer(raw, np.uint8).astype(float) if len(raw) == 256 else None
    else:
        h = np.asarray(Image.open(path).convert("L").resize((16, 16)), float).ravel()
    return None if h is None else h > h.mean()


def main(episode: str) -> None:
    montage = edit_dir(episode)
    plan = load_json(montage / "plan.json")
    srcs, short = [], []
    for s in plan["scenes"]:
        if s["kind"] in ("counter", "bars"):
            log(f"  {s['kind']} {s['data']}")
        if s["kind"] != "media":
            continue
        items = s.get("items") or [s]
        if (s["end"] - s["start"]) / len(items) < 2:
            short.append((s["id"], round(s["start"], 1)))
        srcs += [(s["id"], it["src"], it.get("mediaType")) for it in items]
    tracks = [Path(m["src"]).stem for m in plan["music"]]
    log(f"  кадры короче 2 с: {short or 'нет'}")
    log(f"  нет файла: {[x[1] for x in srcs if not (montage / x[1]).exists()] or 'нет'}")
    log(f"  треки по главам: {tracks}; повтор: {sorted({t for t in tracks if tracks.count(t) > 1}) or 'нет'}")
    hashes = {}
    for sid, src, mt in srcs:
        if src not in hashes and (h := thumb(montage / src, mt == "video")) is not None:
            hashes[src] = (sid, h)
    keys = list(hashes)
    pairs = sorted((int((hashes[a][1] != hashes[b][1]).sum()), hashes[a][0], Path(a).name, hashes[b][0], Path(b).name)
                   for i, a in enumerate(keys) for b in keys[i + 1:]
                   if (hashes[a][1] != hashes[b][1]).sum() <= SAME_BITS)
    log("  похожие кадры (бит различий, сцена, файл):" if pairs else "  похожих кадров нет")
    for p in pairs:
        log(f"    {p}")


if __name__ == "__main__":
    main(sys.argv[1])
