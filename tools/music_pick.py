"""Автовыбор музыки эпизода из фонотеки (с EP-15, решение Nurlan): common/Music/Library/index.json → 04_music + music_plan.json.

  .venv/Scripts/python.exe tools/music_pick.py ep-15          — подобрать, скопировать, записать план
  .venv/Scripts/python.exe tools/music_pick.py ep-15 --dry    — только показать подбор

Нужно: распознанная озвучка (analyze → work/transcript.json), voice_parts.json, 00-script/sound-vo.md (такты + музыкальный план).
Как выбирает: такты и их «Начинается с «…»» — из таблицы блоков sound-vo.md, характер музыки — из таблицы «Музыкальный план»;
время такта — по распознаванию + паузам voice_parts. Gemini (текст, без звука) подбирает треки по описаниям index.json;
код проверяет: трек длиннее отрезка с запасом ≥ 4,5 с (иначе второй трек со смены абзаца), без повторов в эпизоде.
Ротация мягкая (Nurlan): трек из прошлого эпизода — только если подходит заметно лучше; давно не звучавшие — первыми.
Свои треки Nurlan в 04_music (не из фонотеки) — главнее: тогда автовыбор не запускается.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from image_gemini import ANALYSTS, _call, _key
from music_library import INDEX, LIB, sha1
from util import AUDIO_EXT, CLEAN_SCRIPT, MUSIC_DIR, PRODUCTION, VO_DIR, edit_dir, load_json, log, save_json

XFADE = 4.5  # запас трека над отрезком (наплыв), с


def norm(w: str) -> str:
    return re.sub(r"[^a-z0-9']", "", w.lower())


def ep_num(name: str) -> int:
    return int(re.sub(r"\D", "", name) or 0)


def timeline(ep: Path) -> tuple[list[dict], float]:
    """Слова распознавания на шкале ролика (паузы voice_parts) → [{w, n, t}], длина."""
    words = load_json(edit_dir(ep.name) / "work" / "transcript.json")["words"]
    vp = load_json(edit_dir(ep.name) / "voice_parts.json", {}) or {}
    files = sorted(p for p in (ep / VO_DIR).iterdir() if p.suffix.lower() in AUDIO_EXT)
    dur = [float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)],
                                capture_output=True, text=True).stdout) for f in files]
    raw, fin, r, t = [], [], 0.0, 0.0
    for f, d in zip(files, dur):
        raw.append(r); fin.append(t)
        r += d + 1.0  # склейка для распознавания — пауза 1 с
        t += d + float((vp.get("gaps") or {}).get(f.stem, vp.get("default_gap", 1.5)))
    total = fin[-1] + dur[-1]
    out = []
    for w in words:
        k = max(i for i in range(len(raw)) if raw[i] <= w["start"] + 0.05)
        out.append({"w": w["w"], "n": norm(w["w"]), "t": w["start"] - raw[k] + fin[k]})
    return out, total


def locate(tl: list[dict], phrase: str, pos: int) -> int | None:
    """Индекс слова, с которого начинается фраза: первые 4 (3, 2) слова; числа пропускаются с обеих сторон
    (Whisper пишет «1939» цифрами, сценарий — тоже, но «twenty-four» и «24» не совпадут)."""
    ws = [norm(x) for x in phrase.split() if norm(x) and not re.search(r"\d", x)][:4]
    idx = [i for i in range(pos, len(tl)) if tl[i]["n"] and not re.search(r"\d", tl[i]["n"])]
    ns = [tl[i]["n"] for i in idx]
    for tgt, back in ((ws[:4], 0), (ws[:3], 0), (ws[1:5], 1), (ws[1:4], 1), (ws[:2], 0)):  # back: имя в начале распознано иначе
        if len(tgt) < 2:
            continue
        for j in range(len(ns) - len(tgt) + 1):
            if ns[j:j + len(tgt)] == tgt:
                return idx[max(0, j - back)]
    return None


def blocks(ep: Path, tl: list[dict]) -> list[dict]:
    """Такты из sound-vo.md: | T1 | «You know why…» | … | регистр | … | + строка музплана для такта."""
    sv = (ep / "00-script" / "sound-vo.md").read_text(encoding="utf-8")
    music = {}
    for m in re.finditer(r"^\|\s*([^|\n]+?)\s*\|\s*([^|\n]+?)\s*\|\s*([^|\n]*?)\s*\|\s*$", sv, re.M):
        name, desc, lvl = m.groups()
        if not desc.startswith("«") and not set(name) <= set("-: "):
            music[name] = f"{desc}. {lvl}".strip(". ")
    out, pos = [], 0
    for m in re.finditer(r"^\|\s*([^|\n]+?)\s*\|\s*«([^»]+)»\s*\|[^|\n]*\|\s*([^|\n]*?)\s*\|", sv, re.M):
        name, start, register = m.groups()
        i = locate(tl, start, pos)
        if i is None:
            log(f"  ! такт {name}: не нашёл «{start[:40]}» в распознавании — пропускаю")
            continue
        out.append({"block": name, "i": i, "t": tl[i]["t"], "register": register, "music": music.get(name, "")})
        pos = i + 1
    return out


def paragraphs(ep: Path, tl: list[dict]) -> list[float]:
    """Начала абзацев clean-script на шкале — места для смены трека внутри такта."""
    out, pos = [], 0
    for p in (ep / CLEAN_SCRIPT).read_text(encoding="utf-8").split("\n"):
        if p.strip():
            i = locate(tl, p, pos)
            if i is not None:
                out.append(i); pos = i + 1
    return out


def ask_gemini(segs: list[dict], tracks: list[dict], last_ep: str | None) -> dict:
    lib = [{"id": t["file"].rsplit(".", 1)[0], "title": t["title"], "genre": t["family"], "moods": t["moods"],
            "uses": t["uses"], "energy": t["energy"], "tension": t["tension"],
            "warmth": t["warmth"], "bpm": t["bpm"], "sec": round(t["dur"]),
            "last_used": max((u["ep"] for u in t["used"]), key=ep_num, default=None)} for t in tracks]
    task = [{"block": s["block"], "seconds": round(s["need"]), "narrator": s["register"], "music_brief": s["music"]} for s in segs]
    prompt = (
        "You pick background music for a calm US true-story documentary episode. For EVERY block choose an ordered list of "
        "1-3 track ids from LIBRARY that fit the music_brief and narrator register. Rules: no track used twice in the episode; "
        f"the tracks of a block together must be at least the block seconds + {XFADE} each (longer is fine); neighbouring blocks "
        f"should differ in character; avoid tracks whose last_used is {last_ep!r} unless clearly the best fit; prefer tracks never "
        "used or used long ago; the teaser/outro block gets a warm light track; avoid lyrics. "
        'Answer JSON: {"picks": [{"block": "...", "tracks": ["id", ...], "why_ru": "коротко по-русски"}]}.\n\n'
        f"BLOCKS:\n{json.dumps(task, ensure_ascii=False)}\n\nLIBRARY:\n{json.dumps(lib, ensure_ascii=False)}")
    last = None
    for model in ANALYSTS:
        try:
            res = _call(model, [{"text": prompt}], _key(), {"responseMimeType": "application/json", "temperature": 0.3})
            return json.loads(res["candidates"][0]["content"]["parts"][0]["text"])
        except Exception as e:  # noqa: BLE001
            last = e
            log(f"  · {model}: {str(e)[:100]}")
    raise SystemExit(f"Gemini не подобрал музыку: {last}")


def main(name: str, dry: bool = False) -> None:
    ep = PRODUCTION / name
    md = ep / MUSIC_DIR
    md.mkdir(exist_ok=True)
    index = load_json(INDEX, None)
    if not index:
        raise SystemExit(f"Нет фонотеки {INDEX} — tools/music_library.py scan → apply")
    lib_sha = {t["sha1"] for t in index["tracks"]} | {d["sha1"] for d in index.get("duplicates", [])}
    own = [f for f in md.iterdir() if f.suffix.lower() in AUDIO_EXT and sha1(f) not in lib_sha]
    if own:
        raise SystemExit(f"В {md} свои треки Nurlan ({len(own)}) — автовыбор не нужен, music_plan.json вручную")
    tl, total = timeline(ep)
    bl = blocks(ep, tl)
    if not bl:
        raise SystemExit("В sound-vo.md не нашёл таблицу тактов «| T1 | «Начинается с…» |»")
    bl[0]["t"], bl[0]["i"] = 0.0, 0
    for k, b in enumerate(bl):
        b["need"] = (bl[k + 1]["t"] if k + 1 < len(bl) else total) - b["t"]
    pool = [t for t in index["tracks"] if not t["brand"] and t.get("vocals") != "lyrics"]
    prev = [e.name for e in PRODUCTION.glob("ep-*") if ep_num(e.name) < ep_num(name)]
    last_ep = max(prev, key=ep_num, default=None)
    log(f"▶ Музыка {name}: тактов {len(bl)}, ролик {int(total // 60)}:{int(total % 60):02d}, в фонотеке {len(pool)} треков")
    picks = {p["block"]: p for p in ask_gemini(bl, pool, last_ep).get("picks", [])}
    by_id = {t["file"].rsplit(".", 1)[0]: t for t in pool}
    paras = paragraphs(ep, tl)
    used: set[str] = set()
    segments = []

    def spare(need: float) -> str | None:
        """Запасной трек: не звучал в эпизоде, реже звучал раньше; сначала те, что покрывают need целиком."""
        free = [t for t in pool if t["file"].rsplit(".", 1)[0] not in used]
        fit = [t for t in free if t["dur"] - XFADE >= need] or sorted(free, key=lambda t: -t["dur"])[:5]
        best = min(fit, key=lambda t: (len(t["used"]), -t["dur"]), default=None)
        return best["file"].rsplit(".", 1)[0] if best else None

    for k, b in enumerate(bl):
        end_t = bl[k + 1]["t"] if k + 1 < len(bl) else total
        why = (picks.get(b["block"]) or {}).get("why_ru", "")
        queue = [i for i in (picks.get(b["block"]) or {}).get("tracks", []) if i in by_id and i not in used]
        t0, i0 = b["t"], b["i"]
        while True:
            tid = queue.pop(0) if queue else spare(end_t - t0)
            if tid is None:
                log(f"  ! {b['block']}: в фонотеке не осталось свободных треков"); break
            tr = by_id[tid]
            reach = t0 + tr["dur"] - XFADE
            cut = [p for p in paras if t0 + 20 < tl[p]["t"] <= reach]
            if reach < end_t and not cut:  # короче отрезка и негде сменить — нужен длиннее
                alt = spare(end_t - t0)
                if alt and by_id[alt]["dur"] > tr["dur"]:
                    tid, tr = alt, by_id[alt]
                    reach = t0 + tr["dur"] - XFADE
                    cut = [p for p in paras if t0 + 20 < tl[p]["t"] <= reach]
            at = "start" if not segments else "text:" + " ".join(x["w"] for x in tl[i0:i0 + 5])
            segments.append({"at": at, "tracks": [tid], "_why": f"{b['block']}: {why or 'запасной по длине'} "
                             f"({int(t0 // 60)}:{int(t0 % 60):02d}–{int(end_t // 60)}:{int(end_t % 60):02d}, {tr['title']}, {tr['dur']:.0f} с)"})
            used.add(tid)
            if reach >= end_t or not cut:
                if reach < end_t:
                    log(f"  ! {b['block']}: {tid} не дотягивает до конца такта на {end_t - reach:.0f} с")
                break
            i0 = max(cut); t0 = tl[i0]["t"]
    for s in segments:
        log(f"  {s['at'][:42]:42} → {s['tracks'][0]}  · {s['_why'][:110]}")
    if dry:
        return
    for tid in used:
        src = LIB / by_id[tid]["file"]
        if not (md / src.name).exists():
            shutil.copy2(src, md / src.name)
        t = by_id[tid]
        if name not in {u["ep"] for u in t["used"]}:
            t["used"].append({"ep": name, "by": "plan"})
    save_json(edit_dir(name) / "music_plan.json", {
        "_about": "Музыка подобрана автоматически из фонотеки (tools/music_pick.py): такты sound-vo.md, ротация мягкая.",
        "segments": segments})
    save_json(INDEX, index)
    from music_library import write_md
    write_md(index)
    log(f"✔ {len(used)} треков → {md}; music_plan.json; фонотека: отмечено «звучал в {name}»")


if __name__ == "__main__":
    main(sys.argv[1], "--dry" in sys.argv)
