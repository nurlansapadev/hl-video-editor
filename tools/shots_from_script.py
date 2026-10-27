"""Шаг 2а (с EP-10): все [КАРТИНКА] из 06_montage/script.txt → 06_montage/output/ep-N-shots.json с полем generate (вход Gen).

  .venv/Scripts/python.exe tools/shots_from_script.py ep-10

Фамилии людей с face_policy archive_only в полях задания заменяются на «[name]»: иначе Gen/ReGen пропускают шот
(EP-10: «Zacharski», «Hughes Aircraft»). Сценарий не меняется. Шоты, уже записанные в ep-N-shots.json, обновляются,
остальные (пробелы после find с kind «любое») сохраняются.
"""
from __future__ import annotations

import re
import sys

from util import CHARACTERS_DIR, edit_dir, load_json, log, save_json, PRODUCTION


def archive_only_surnames(cast: dict) -> list[str]:
    out = []
    for p in cast.get("people", []) or []:
        if p.get("face_policy") == "archive_only" and p.get("name"):
            words = [w for w in re.sub(r"\(.*?\)", "", p["name"]).split()
                     if w.rstrip(".,").lower() not in ("jr", "sr", "ii", "iii")]
            surname = words[-1] if words else ""
            if len(surname) > 2:
                out.append(surname)
    return out


def neutral(text: str, surnames: list[str]) -> str:
    for s in surnames:
        text = re.sub(rf"\b{re.escape(s)}(?:'s|s')?(?!\w)", "[name]", text)
    return text


def main(episode: str) -> None:
    montage = edit_dir(episode)
    cast = load_json(PRODUCTION / episode / CHARACTERS_DIR / "cast.json", {}) or {}
    era = (cast.get("era") or "").split("(")[0].strip()
    surnames = archive_only_surnames(cast)
    shots, cur = [], None
    for line in (montage / "script.txt").read_text(encoding="utf-8").splitlines():
        m = re.match(r"#\s*shot\s+(\d+)", line)
        if m:
            cur = {"no": int(m.group(1)), "gen": None, "epoch": era, "text": []}
            shots.append(cur)
            continue
        if cur is None or not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith("[ГЛАВА"):
            cur = None
            continue
        k = re.match(r"\[КАРТИНКА:\s*(.+)\]\s*$", line)
        e = re.match(r"\[ЭПОХА:\s*(.+)\]", line)
        if k:
            cur["gen"] = k.group(1).strip()
        elif e:
            cur["epoch"] = e.group(1).strip()
        elif not line.startswith("["):
            cur["text"].append(line.strip())
    path = montage / "output" / f"{episode}-shots.json"
    old = {s["shot_no"]: s for s in (load_json(path, []) or [])}
    for s in shots:
        if not s["gen"]:
            continue
        gen = neutral(s["gen"], surnames)
        old[s["no"]] = {"shot_no": s["no"], "scenario_text": neutral(" ".join(s["text"]), surnames),
                        "epoch": s["epoch"], "day_time": "", "place": "",
                        "expected": "Сгенерированный кадр по промту generate; без узнаваемых лиц",
                        "query": gen[:120], "kind": "фото", "generate": gen}
    save_json(path, sorted(old.values(), key=lambda s: s["shot_no"]))
    log(f"✔ {path}: шотов {len(old)} (фамилии archive_only скрыты: {', '.join(surnames) or '—'})")


if __name__ == "__main__":
    main(sys.argv[1])
