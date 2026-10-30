"""Фонотека канала (с EP-15, решение Nurlan): common/Music/Library — все треки одной папкой, понятные имена,
описание один раз → index.json (для программы) + index.md (таблица для Nurlan). Эпизоды берут музыку отсюда,
заново ничего не анализируют.

  .venv/Scripts/python.exe tools/music_library.py scan    — новые треки из common/Music (любые подпапки, кроме Library):
                                                            замер (music_stats.measure) + прослушивание Gemini (запасной — OpenAI) → кэш
  .venv/Scripts/python.exe tools/music_library.py apply   — перенести их в Library/ под новыми именами, точные дубли →
                                                            Library/_duplicates, обновить index.json / index.md
  .venv/Scripts/python.exe tools/music_library.py history — где какой трек уже звучал (по 04_music всех эпизодов)

Новые треки: положить в common/Music (в любую папку) → scan → apply. Старые имена нигде не нужны (Nurlan, EP-14).
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import subprocess
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from image_gemini import ANALYSTS, _call, _key
from music_stats import measure
from util import AUDIO_EXT, MUSIC_DIR, PRODUCTION, ROOT, load_json, log, save_json

MUSIC = PRODUCTION / "common" / "Music"
LIB = MUSIC / "Library"
INDEX = LIB / "index.json"
CACHE = LIB / "_scan_cache.json"  # результаты scan до apply (ключ — sha1 файла)

MOODS = ["tension", "suspense", "investigation", "nostalgia", "warm", "melancholy", "deadpan", "playful",
         "upbeat", "triumphant", "dreamy", "romantic", "dark", "calm", "festive"]
USES = ["hook", "history", "investigation", "reveal", "deadpan", "montage", "nostalgia", "finale", "teaser", "brand"]

PROMPT = f"""You are a music librarian for a calm US true-story documentary channel (narration over background music).
Listen to the whole instrumental track and answer in JSON with exactly these keys:
"title": 2-4 word evocative English title, no artist names (e.g. "Smoky Office Sax"),
"style": short genre, 1-3 words, lowercase (e.g. "cool jazz", "smooth jazz", "tango", "lounge piano", "orchestral"),
"lead": main instruments, up to 3, lowercase,
"era": decade the track SOUNDS like, e.g. "1950s", "1990s", "2000s", or "timeless",
"place": region the style suggests, e.g. "us", "latin", "europe", "middle east", "asia", "neutral",
"moods": 1-3 from {MOODS},
"uses": 1-3 best documentary uses from {USES},
"energy": 1-5, "tension": 1-5, "warmth": 1-5,
"vocals": "none" | "humming" | "lyrics",
"start": how it begins (e.g. "soft piano intro 8 s", "drums right away"),
"end": how it ends ("fades out", "hard stop", "loops"),
"note_ru": one sentence in Russian: what this track is and under what kind of scene it works best."""


def sha1(p: Path) -> str:
    h = hashlib.sha1()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def fingerprint(p: Path) -> list[int]:
    """Грубый отпечаток звука: громкость по 64 отрезкам 8 полос → биты. Один трек в mp3 и wav даёт почти тот же."""
    raw = subprocess.run(["ffmpeg", "-v", "quiet", "-i", str(p), "-ac", "1", "-ar", "8000", "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    y = np.frombuffer(raw, np.float32)
    seg = np.array_split(y, 64)
    bands = []
    for s in seg:
        sp = np.abs(np.fft.rfft(s[: 1 << 14] if len(s) >= 1 << 14 else np.pad(s, (0, (1 << 14) - len(s)))))
        bands.append([float(b.mean()) for b in np.array_split(sp[20:], 8)])
    a = np.log1p(np.array(bands))
    return (a > np.median(a, axis=0)).astype(int).flatten().tolist()


def same_audio(a: list[int], b: list[int]) -> bool:
    return len(a) == len(b) and sum(x != y for x, y in zip(a, b)) <= len(a) * 0.08


AUDIO_MODEL = "gpt-audio-mini"  # запасной: OpenAI слушает ~3 с, ~$0,01 за трек


def _clip(p: Path, fmt: str) -> bytes:
    """90 с: 40 с начала + 50 с из середины — хватает на характер трека, дешевле целого."""
    dur = measure_dur(p)
    mid = max(40.0, dur / 2 - 25)
    codec = ["-c:a", "libopus", "-b:a", "24k", "-f", "ogg"] if fmt == "ogg" else ["-b:a", "32k", "-f", "mp3"]
    return subprocess.run(["ffmpeg", "-v", "quiet", "-i", str(p), "-filter_complex",
                           f"[0]atrim=0:40,asetpts=N/SR/TB[a];[0]atrim={mid:.1f}:{mid + 50:.1f},asetpts=N/SR/TB[b];"
                           "[a][b]concat=n=2:v=0:a=1", "-ac", "1", "-ar", "16000", *codec, "-"],
                          capture_output=True, check=True).stdout


def measure_dur(p: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                         capture_output=True, text=True).stdout
    return float(out or 0)


def _openai(p: Path) -> dict:
    key = (load_json(ROOT / "keys.json", {}) or {}).get("openai")
    if not key:
        raise RuntimeError("нет ключа openai")
    body = {"model": AUDIO_MODEL, "modalities": ["text"], "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": PROMPT + " You hear 40 s from the start and 50 s from the middle."},
                {"type": "input_audio", "input_audio": {"data": base64.b64encode(_clip(p, "mp3")).decode(), "format": "mp3"}}]}]}
    last = None
    for wait in (0, 10, 30):
        time.sleep(wait)
        req = urllib.request.Request("https://api.openai.com/v1/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        try:
            res = json.loads(urllib.request.urlopen(req, timeout=90).read())
            return json.loads(res["choices"][0]["message"]["content"])
        except Exception as e:  # noqa: BLE001 — 429/5xx/таймаут: повтор
            last = e
    raise RuntimeError(f"{AUDIO_MODEL}: {last}")


def _gemini(p: Path) -> dict:
    parts = [{"inline_data": {"mime_type": "audio/ogg", "data": base64.b64encode(_clip(p, "ogg")).decode()}},
             {"text": PROMPT + " You hear 40 s from the start and 50 s from the middle."}]
    last = None
    for model in ANALYSTS:
        try:
            res = _call(model, parts, _key(), {"responseMimeType": "application/json", "temperature": 0.2})
            d = json.loads(res["candidates"][0]["content"]["parts"][0]["text"])
            return d[0] if isinstance(d, list) else d
        except Exception as e:  # noqa: BLE001 — следующая модель
            last = e
            log(f"    · {model}: {str(e)[:100]}")
    raise RuntimeError(f"Gemini: {last}")


def listen(p: Path) -> dict:
    """Описание «на слух»: Gemini (платный уровень с EP-15, ~$0,003 за трек; Opus — mp3 из пайпа Gemini отвергает),
    при сбое — OpenAI gpt-audio-mini (~$0,01)."""
    try:
        return _gemini(p)
    except Exception as e:  # noqa: BLE001
        log(f"    · {str(e)[:100]} — пробую OpenAI")
    return _openai(p)


def sources() -> list[Path]:
    return sorted(p for p in MUSIC.rglob("*") if p.is_file() and p.suffix.lower() in AUDIO_EXT
                  and LIB not in p.parents)


def scan() -> None:
    LIB.mkdir(parents=True, exist_ok=True)
    cache = load_json(CACHE, {}) or {}
    index = load_json(INDEX, {"tracks": []}) or {"tracks": []}
    known = {t["sha1"] for t in index["tracks"]} | {t["sha1"] for t in index.get("duplicates", [])}
    todo = sources()
    log(f"▶ Фонотека: файлов вне Library {len(todo)}")
    lock = threading.Lock()

    def one(p: Path) -> None:
        h = sha1(p)
        if h in known or (h in cache and cache[h].get("listen")):
            return
        c = cache.get(h) or {"sha1": h}
        c["src"] = str(p)
        c.setdefault("stats", measure(p))
        c.setdefault("fp", fingerprint(p))
        try:
            c["listen"] = listen(p)
            log(f"  ✓ {p.name} → {c['listen'].get('title')} · {c['listen'].get('style')} · {c['listen'].get('moods')}")
        except Exception as e:  # noqa: BLE001
            log(f"  ! {p.name}: {e}")
        with lock:
            cache[h] = c
            save_json(CACHE, cache)

    with ThreadPoolExecutor(4) as ex:
        list(ex.map(one, todo))
    left = sum(1 for c in cache.values() if not c.get("listen"))
    log(f"✔ scan: в кэше {len(cache)}, без описания {left}" + (" — запустить scan ещё раз" if left else " → apply"))


# Модели сходятся в общем жанре и настроении, а инструменты и эпоху часто выдумывают (EP-14: один трек — «диксиленд
# с кларнетом», «джаз с вибрафоном», «джаз с гитарой»). В имя и индекс — только надёжное: жанр-семья, настроение, замер.
FAMILIES = [("jazz", r"jazz|swing|bossa|lounge|noir|dixieland|ragtime|vaudeville|bebop|blues"),
            ("latin", r"latin|tango|flamenco|rumba|salsa|montuno|bolero"),
            ("funk", r"funk|disco|groove|r-?&?-?b|soul|boogie"),
            ("orchestral", r"orchestr|cinematic|symphon|classical|chamber|waltz|march|suspense|hybrid|score"),
            ("piano", r"piano"),
            ("acoustic", r"acoustic|folk|guitar|americana|country|ballad|pop"),
            ("ambient", r"ambient|lullaby|new age")]
MOOD_RU = {"tension": "напряжённый", "suspense": "тревожный", "investigation": "«расследование»", "nostalgia": "ностальгический",
           "warm": "тёплый", "melancholy": "грустный", "deadpan": "сухой, ироничный", "playful": "игривый", "upbeat": "бодрый",
           "triumphant": "торжественный", "dreamy": "мечтательный", "romantic": "романтичный", "dark": "мрачный",
           "calm": "спокойный", "festive": "праздничный"}
FAMILY_RU = {"jazz": "джаз", "latin": "латина", "funk": "фанк", "orchestral": "оркестр", "piano": "пианино",
             "acoustic": "акустика", "ambient": "эмбиент"}


def tempo(bpm: float) -> int:
    """Замер темпа иногда берёт удвоенный (баллада 92 → 185): выше 160 — пополам."""
    return int(round(bpm / 2)) if bpm > 160 else int(round(bpm))


def family(style: str) -> str:
    st = (style or "").lower()
    return next((f for f, rx in FAMILIES if re.search(rx, st)), "other")


def note(L: dict, st: dict) -> str:
    moods = ", ".join(MOOD_RU.get(m, m) for m in (L.get("moods") or [])[:2])
    b = tempo(st["bpm"])
    speed = "медленный" if b < 80 else "средний темп" if b < 115 else "быстрый"
    return (f"{FAMILY_RU.get(family(L.get('style')), 'другое')}, {moods}; {speed}; энергия {L.get('energy')}/5, "
            f"напряжение {L.get('tension')}/5, теплота {L.get('warmth')}/5")


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")


def new_name(c: dict, taken: set[str]) -> str:
    L, st = c["listen"], c["stats"]
    base = f"{slug((L.get('moods') or ['calm'])[0])}_{family(L.get('style'))}_{tempo(st['bpm']):03d}bpm"
    n = 1
    while f"{base}_{n:02d}" in taken:
        n += 1
    taken.add(f"{base}_{n:02d}")
    return f"{base}_{n:02d}"


def apply() -> None:
    cache = load_json(CACHE, {}) or {}
    index = load_json(INDEX, {"tracks": [], "duplicates": []}) or {"tracks": [], "duplicates": []}
    index.setdefault("duplicates", [])
    taken = {t["file"].rsplit(".", 1)[0] for t in index["tracks"]}
    ready = [c for c in cache.values() if c.get("listen") and Path(c["src"]).exists()]
    # оригинал среди одинаковых по звуку: wav лучше mp3, длиннее лучше
    ready.sort(key=lambda c: (Path(c["src"]).suffix.lower() != ".wav", -c["stats"]["dur"]))
    moved = dup = 0
    for c in ready:
        src = Path(c["src"])
        twin = next((t for t in index["tracks"] if same_audio(t["fp"], c["fp"])
                     and abs(t["dur"] - c["stats"]["dur"]) < 3), None)
        if twin:
            dst = LIB / "_duplicates" / f"{twin['file'].rsplit('.', 1)[0]}__dup{len(index['duplicates']) + 1}{src.suffix.lower()}"
            dst.parent.mkdir(exist_ok=True)
            src.rename(dst)
            index["duplicates"].append({"file": f"_duplicates/{dst.name}", "sha1": c["sha1"], "same_as": twin["file"],
                                        "was": str(src.relative_to(MUSIC))})
            dup += 1
            continue
        name = new_name(c, taken) + src.suffix.lower()
        src.rename(LIB / name)
        L, st = c["listen"], c["stats"]
        brand = bool(re.search(r"master music|intro-hook", src.name, re.I))
        index["tracks"].append({
            "file": name, "title": L.get("title"), "family": family(L.get("style")), "moods": L.get("moods"),
            "uses": ["brand"] if brand else L.get("uses"), "energy": L.get("energy"), "tension": L.get("tension"),
            "warmth": L.get("warmth"), "vocals": L.get("vocals"), "note_ru": note(L, st),
            "dur": st["dur"], "bpm": tempo(st["bpm"]), "pulse": st["pulse"], "notes_per_s": st["notes_per_s"],
            "bright_hz": st["bright_hz"], "loud_db": st["loud_db"], "dyn_db": st["dyn_db"],
            "brand": brand, "sha1": c["sha1"], "fp": c["fp"], "was": str(src.relative_to(MUSIC)), "used": [],
            "_heard": {k: L.get(k) for k in ("style", "lead", "era", "place", "start", "end")}})  # ненадёжно — не показываем
        moved += 1
    for c in list(cache):
        if not Path(cache[c]["src"]).exists():
            cache.pop(c)
    save_json(CACHE, cache)
    index["tracks"].sort(key=lambda t: t["file"])
    history(index)
    save_json(INDEX, index)
    write_md(index)
    log(f"✔ apply: в Library +{moved}, дублей +{dup}; всего треков {len(index['tracks'])} → {INDEX}")


def history(index: dict | None = None) -> None:
    """used: эпизоды, где трек лежал в 04_music (совпадение файла или звука)."""
    save = index is None
    index = index or load_json(INDEX, {"tracks": []})
    by_sha = {t["sha1"]: t for t in index["tracks"]}
    for d in index.get("duplicates", []):
        if d["same_as"] in {t["file"] for t in index["tracks"]}:
            by_sha[d["sha1"]] = next(t for t in index["tracks"] if t["file"] == d["same_as"])
    for t in index["tracks"]:
        t["used"] = [u for u in t.get("used", []) if u.get("by") == "plan"]  # точные записи от автовыбора не трогаем
    for ep in sorted(PRODUCTION.glob("ep-*"), key=lambda p: int(re.sub(r"\D", "", p.name) or 0)):
        md = ep / MUSIC_DIR
        if not md.is_dir():
            continue
        for f in md.iterdir():
            if f.suffix.lower() not in AUDIO_EXT:
                continue
            t = by_sha.get(sha1(f))
            if t and ep.name not in {u["ep"] for u in t["used"]}:
                t["used"].append({"ep": ep.name, "by": "04_music"})
    if save:
        save_json(INDEX, index)
        write_md(index)
        log("✔ history обновлена")


def write_md(index: dict) -> None:
    ts = index["tracks"]
    total = sum(t["dur"] for t in ts if not t["brand"])
    lines = ["# Фонотека Honest Lies", "",
             f"Треков: {len(ts)} · фоновой музыки {int(total // 3600)} ч {int(total % 3600 // 60)} мин. "
             "Обновляется `tools/music_library.py scan` → `apply` (новые треки — в любую папку common/Music).",
             "Имя файла: настроение_жанр_темп_номер. Эпизоды берут музыку отсюда сами (`tools/music_pick.py`).", "",
             "| Файл | Название | Длина | Темп | Какой | Звучал |", "|---|---|---|---|---|---|"]
    for t in ts:
        m, s = divmod(int(t["dur"]), 60)
        used = ", ".join(u["ep"] for u in t["used"]) or "—"
        lines.append(f"| {t['file']} | {t['title']}{' · фирменный' if t['brand'] else ''} | {m}:{s:02d} | {t['bpm']} | "
                     f"{t['note_ru']} | {used} |")
    (LIB / "index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "scan"
    {"scan": scan, "apply": apply, "history": history}[cmd]()
