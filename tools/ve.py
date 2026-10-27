"""VideoEditor 2.0 — пульт команд. Вызывает Claude по шагам из CLAUDE.md; Nurlan сам не запускает.

  .venv/Scripts/python.exe tools/ve.py <команда> ep-8

Папку эпизода со всеми подпапками создаёт hl-script (production/tools/new_episode.py); см. util.py.
Этап 1 (только сценарий):
  prepare  — проверить структуру эпизода и 00-script/clean-script.txt, создать 06_montage
  passport — черновик паспорта 06_montage/context.json из 02_characters/cast.json + новые места/страны
             для data/ (--apply — дописать их в data/places.json и countries.json, после «да» Nurlan)
  index    — каталог своих кадров: 05_footage, 03_generated, 02_characters (описания для поиска)
  prompts  — задание на генерацию [КАРТИНКА] → 06_montage/output/ep-N_generate.txt (картинки — в 03_generated)
  find     — поиск кадров: сначала свои папки, потом интернет (отчёт — 06_montage/work/find_report.txt)
  fill     — сразу после find: пустые шоты с образцом (refs/) → ReGen → [СЦЕНА: N-1-rg] в script.txt (gap_fill.py)
  findstats — журнал поиска по всем эпизодам (data/find_history.jsonl): вклад источников, пустые шоты, подсказки;
             эпизод не нужен: ve.py findstats
Переход:
  inputs   — что готово к этапу 2: озвучка (01_vo), музыка (04_music), сгенерированные картинки
Этап 2 (озвучка готова):
  analyze  — озвучка → тайминг слов + громкость голоса; материалы → media.json
  empty    — обзор пустых сцен → 06_montage/empty_scenes.json (решения Nurlan: card | nearby)
  plan     — план монтажа 06_montage/plan.json (стоп, если нет музыки, картинок или решений)
  render   — рендер (ТОЛЬКО после «рендер» от Nurlan) → громкость → .srt, главы → 06_montage/ep-N_vK.mp4
  check    — контрольный лист кадров готового видео
  studio   — открыть монтаж в браузере (перемотка без рендера)
Рабочий сценарий с метками — 06_montage/script.txt (его пишет Claude по clean-script.txt).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from audio import ensure_default_sfx, loudnorm, measure_lufs, normalize_music, prepare_voice  # noqa: E402
from media import make_contact_sheet, scan_audio, scan_media  # noqa: E402
from scriptparse import WORDS_PER_MIN, align, parse_script  # noqa: E402
from util import (AUDIO_EXT, CHARACTERS_DIR, CLEAN_SCRIPT, EDIT_DIR, ENGINE, FOOTAGE_DIR, GENERATED_DIR,  # noqa: E402
                  IMAGE_EXT, MONTAGE_DIR, MUSIC_DIR, OWN_DIRS, PRODUCTION, ROOT, VIDEO_EXT, VO_DIR, die, edit_dir,
                  files_in, fmt_time, load_json, log, read_text, rel, run, save_json, which_or_die)

EPISODE_DIRS = ("00-script", VO_DIR, CHARACTERS_DIR, GENERATED_DIR, MUSIC_DIR, FOOTAGE_DIR, EDIT_DIR)


# ───────────────────────── эпизод и настройки ─────────────────────────
def episode_dir(ep: str) -> Path:
    p = PRODUCTION / ep
    if not p.is_dir():
        die(f"Нет папки эпизода: {p}")
    return p


def settings_for(project: Path) -> dict:
    """settings.json программы (копия STYLE.md) → 06_montage/settings.json эпизода (если есть)."""
    s = {k: v for k, v in (load_json(ROOT / "settings.json", {}) or {}).items() if not k.startswith("_")}
    for k, v in (load_json(project / "settings.json", {}) or {}).items():
        s[k] = {**s[k], **v} if isinstance(v, dict) and isinstance(s.get(k), dict) else v
    return s


def context_for(project: Path) -> dict:
    """Паспорт эпизода (06_montage/context.json): тема, эпоха, страна, люди, запреты."""
    return load_json(project / "context.json", {}) or {}


def script_text(project: Path) -> str:
    path = project / "script.txt"
    if not path.exists():
        die(f"Нет размеченного сценария {path} — его пишет Claude по {CLEAN_SCRIPT}")
    return "\n".join(ln for ln in read_text(path).splitlines() if not ln.lstrip().startswith(("#", "//")))


def files_hash(files: list[Path]) -> str:
    h = hashlib.md5()
    for f in files:
        st = f.stat()
        h.update(f"{f.name}:{st.st_size}:{int(st.st_mtime)}".encode())
    return h.hexdigest()


def link(src: Path, dst: Path) -> None:
    """Файл эпизода → 06_montage жёсткой ссылкой: исходник не меняется, место на диске не тратится."""
    if dst.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


# ───────────────────────── этап 1 ─────────────────────────
def cmd_prepare(ep: Path, project: Path) -> None:
    """Проверка структуры эпизода (её создаёт hl-script) и сценария; 06_montage досоздаётся."""
    project.mkdir(parents=True, exist_ok=True)
    missing = [d for d in EPISODE_DIRS if not (ep / d).is_dir()]
    if missing:
        log(f"  ! Нет подпапок: {', '.join(missing)} — эпизод создаётся hl-script (new_episode.py)")
    clean = ep / CLEAN_SCRIPT
    if not clean.exists():
        die(f"Нет сценария {clean} — его делает hl-script на фазе 7 (Voicer)")
    n = len(read_text(clean).split())
    log(f"✔ Эпизод {ep.name}: сценарий {n} слов ≈ {fmt_time(n / WORDS_PER_MIN * 60)} озвучки")
    log(f"  Рабочая папка: {project}")
    for d in OWN_DIRS:
        files = [p for p in (ep / d).glob("*") if p.suffix.lower() in IMAGE_EXT | VIDEO_EXT] if (ep / d).is_dir() else []
        log(f"  Свои кадры {d}: {len(files)}")
    cast = ep / CHARACTERS_DIR / "cast.json"
    log(f"  Реестр {cast.name}: {'есть' if cast.exists() else 'НЕТ — паспорт придётся собирать по сценарию'}")


def cmd_passport(ep: Path, project: Path, apply: bool = False, force: bool = False) -> None:
    """Черновик паспорта из реестра 02_characters/cast.json → 06_montage/context.json (если его ещё нет);
    места и страны реестра, которых нет в data/, — список (apply=True — дописать)."""
    cast = load_json(ep / CHARACTERS_DIR / "cast.json")
    if not cast:
        die(f"Нет {ep / CHARACTERS_DIR / 'cast.json'} — паспорт собрать по сценарию вручную (CLAUDE.md, шаг 0)")
    places = {k: v for k, v in (cast.get("places") or {}).items() if isinstance(v, dict) and "lat" in v and "lon" in v}
    countries = {k: v for k, v in (cast.get("countries") or {}).items() if isinstance(v, dict)}
    by_country: dict[str, int] = {}
    known_countries = set(countries) | set(load_json(ROOT / "data" / "countries.json", {}) or {})
    for name, v in places.items():
        if v.get("country"):
            by_country[v["country"]] = by_country.get(v["country"], 0) + 1
        # контракт hl-script: у каждого места country, и эта страна есть в блоке countries
        if not v.get("country"):
            log(f"  ! Реестр: у места «{name}» не заполнено country")
        elif v["country"] not in known_countries:
            log(f"  ! Реестр: страны «{v['country']}» (место «{name}») нет в блоке countries")
    ctx_path = project / "context.json"
    if not ctx_path.exists() or force:
        ctx = {"topic": cast.get("episode", ep.name), "era": cast.get("era", ""),
               "country": max(by_country, key=by_country.get) if by_country else "",
               "places": list(places), "flashbacks": [], "forbidden": [],
               "people": [{k: p.get(k) for k in ("name", "role", "years") if p.get(k)} for p in cast.get("people", []) or []]}
        save_json(ctx_path, ctx)
        log(f"✔ Черновик паспорта: {ctx_path} — показать Nurlan (главная страна: {ctx['country'] or '?'})")
    else:
        log(f"  Паспорт уже есть: {ctx_path} (--force — пересобрать из реестра)")
    data_places = ROOT / "data" / "places.json"
    data_countries = ROOT / "data" / "countries.json"
    known_p, known_c = load_json(data_places, {}) or {}, load_json(data_countries, {}) or {}
    new_p = {k: {"lat": round(float(v["lat"]), 4), "lon": round(float(v["lon"]), 4), "aliases": v.get("aliases", [])}
             for k, v in places.items() if k not in known_p}
    new_c = {k: {"lang": v.get("lang", "en"), "words": v.get("words", [])} for k, v in countries.items() if k not in known_c}
    for k, v in new_p.items():
        log(f"  Новое место: {k} ({v['lat']}, {v['lon']})" + (f" — также {', '.join(v['aliases'])}" if v["aliases"] else ""))
    for k, v in new_c.items():
        log(f"  Новая страна: {k} — язык {v['lang']}, признаки: {', '.join(v['words'])}")
    if not new_p and not new_c:
        log("  Новых мест и стран нет — справочники data/ уже всё знают")
    elif apply:
        save_json(data_places, {**known_p, **new_p})
        save_json(data_countries, {**known_c, **new_c})
        log(f"✔ Дописано в data/: мест {len(new_p)}, стран {len(new_c)}")
    else:
        log("  … показать Nurlan; после «да» — passport --apply")


def cmd_index(ep: Path) -> None:
    from local_index import build
    dirs = [ep / d for d in OWN_DIRS if (ep / d).is_dir()]
    if not dirs:
        die(f"Нет папок своих кадров ({', '.join(OWN_DIRS)})")
    for d in dirs:
        build(d)


AI_NAME = re.compile(r"^ai[\s_\-]*0*(\d{1,2})(?:[\s_\-]?([a-d]))?(?=$|[\s_\-.(])", re.I)
AI_TAG = re.compile(r"\[\s*(картинка|генерация|ии|ai)\s*[:：]\s*([^\]]+)\]", re.I)


def import_ai_images(ep: Path, project: Path) -> int:
    """Сгенерированные картинки из 03_generated (ai01.png, AI_03b.jpg, в подпапках) → 06_montage/media/ai01.png … ссылками.
    Если имена не те — карта 06_montage/media/ai_map.json {"имя файла в 03_generated": "ai06"} (составляет Claude по содержимому)."""
    footage, media = ep / GENERATED_DIR, project / "media"
    if not footage.is_dir():
        return 0
    linked = 0
    amap = load_json(media / "ai_map.json", {}) or {}
    for name, code in amap.items():
        src = next((x for x in footage.rglob(name) if x.is_file()), None)
        if src:
            target = media / f"{code.lower()}{src.suffix.lower().replace('.jpeg', '.jpg')}"
            if not target.exists():
                link(src, target)
                linked += 1
    for p in sorted(footage.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
            continue
        m = AI_NAME.match(p.stem)
        if not m:
            continue
        target = media / f"ai{int(m.group(1)):02d}{(m.group(2) or '').lower()}{p.suffix.lower().replace('.jpeg', '.jpg')}"
        if not target.exists():
            link(p, target)
            linked += 1
    if linked:
        log(f"  Сгенерированные картинки: подключил {linked}")
    return linked


def ai_needed(text: str) -> list[str]:
    """Коды картинок, которые нужны по сценарию: ai01, ai01b (длинная сцена), ai01c …"""
    need = []
    for k, m in enumerate(AI_TAG.finditer(text), 1):
        name = f"ai{k:02d}"
        pos = m.end()
        while True:  # метки подряд ([ДАТА], [ПОДПИСЬ] …) пропускаем — нужен сам текст под картинкой
            mm = re.match(r"\s*\[[^\]]*\]", text[pos:])
            if not mm:
                break
            pos += mm.end()
        nxt = text.find("[", pos)
        secs = len(text[pos: nxt if nxt > 0 else None].split()) / (WORDS_PER_MIN / 60)
        need += [name] + ([f"{name}b"] if secs > 10 else []) + ([f"{name}c"] if secs > 18 else [])
    return need


def cmd_prompts(ep: Path, project: Path) -> None:
    """Задание на генерацию: общие правила + по каждой картинке промт и текст, который звучит под ней."""
    text = script_text(project)
    tags = list(AI_TAG.finditer(text))
    out = project / "output" / f"{ep.name}_generate.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    if not tags:
        out.write_text("В сценарии нет [КАРТИНКА] — генерировать ничего не нужно.\n", encoding="utf-8")
        log("  [КАРТИНКА] в сценарии нет")
        return
    import_ai_images(ep, project)
    have = {p.stem.lower() for p in (project / "media").glob("ai*")}
    s, ctx = settings_for(project), context_for(project)
    style = s.get("aiStyle") or "photorealistic documentary photograph, natural cinematic lighting, 16:9, high detail, no text"
    items, total = [], 0
    for k, m in enumerate(tags, 1):
        name = f"ai{k:02d}"
        pos = m.end()
        era = ""
        while True:
            mm = re.match(r"\s*\[([^\]]*)\]", text[pos:])
            if not mm:
                break
            em = re.match(r"\s*(?:эпоха|era)\s*[:：]\s*(.+)", mm.group(1), re.I)
            era = em.group(1).strip() if em else era
            pos += mm.end()
        nxt = text.find("[", pos)
        said = " ".join(text[pos: nxt if nxt > 0 else None].split())
        secs = len(said.split()) / (WORDS_PER_MIN / 60)
        variants = [name] + ([f"{name}b"] if secs > 10 else []) + ([f"{name}c"] if secs > 18 else [])
        need = [v for v in variants if v not in have]
        if not need:
            continue
        raw = m.group(2).strip()
        recon = bool(re.search(r"\|\s*(реконстр|reconstr)", raw, re.I))
        total += len(need)
        block = [f"── {' + '.join(v + '.png' for v in need)}",
                 f"Era: {era or ctx.get('era', 'see episode')}",
                 f"Narration over this shot (context only, do NOT write it on the image): \"{said[:300]}\"",
                 f"Prompt: {raw.split('|')[0].strip()}"]
        if recon:
            block.append("Period RECONSTRUCTION of a real past event (labelled “AI reconstruction” on screen): "
                         "every detail period-accurate — no modern cars, phones, LED lights or signage.")
        if len(need) > 1:
            block.append(f"Make {len(need)} different images: {need[0]}.png as described; "
                         + "; ".join(f"{v}.png from a clearly different camera angle or distance" for v in need[1:]) + ".")
        items.append("\n".join(block))
    if not items:
        out.write_text("Все сгенерированные картинки на месте.\n", encoding="utf-8")
        log("  Сгенерированные картинки: все на месте")
        return
    head = f"""=== ДЛЯ NURLAN ===
Сгенерируй картинки по заданию ниже и положи в {ep / GENERATED_DIR}
Имена ai01.png, ai02.png … (или как получится — Claude сопоставит по содержимому). Картинок: {total}.
────────────────────────────────────────────────────────────

TASK
Generate {total} still images for a documentary YouTube episode: {ctx.get('topic', ep.name)}.
Main era: {ctx.get('era', '')}. Main country: {ctx.get('country', '')}.

RULES FOR EVERY IMAGE
1. 16:9 landscape, at least 1920×1080.
2. Style: {style}.
3. NO text anywhere: no captions, letters, numbers, readable signs, watermarks, logos or borders.
4. People only small in the frame, from behind or for scale. No close-up faces, no real identifiable people.
5. No injured or dead people, no blood, nothing graphic — the video must be advertiser-friendly.
6. Period-accurate for the era of each image: cars, clothes, technology, interiors. No modern objects in historical scenes.
7. Geography correct for the place of the scene.
8. Variants (…b, …c) — same subject from a clearly different angle or distance, never a near-copy.
9. Do not recreate real, identifiable buildings as if photographed — those are shown with real photos.

IMAGES
"""
    out.write_text(head + "\n\n".join(items) + "\n", encoding="utf-8")
    log(f"▶ Задание на генерацию: {total} картинок → {out}")


def cmd_find(ep: Path, project: Path, force: bool = False) -> None:
    from finder import fetch_sources, run_finder
    text = script_text(project)
    fetch_sources(project, force=force)
    run_finder(project, settings_for(project), text, ctx=context_for(project), own_dirs=[ep / d for d in OWN_DIRS], force=force)


def cmd_inputs(ep: Path, project: Path) -> bool:
    """Готовность к этапу 2. True — всё на месте."""
    ok = True
    voice = files_in(ep / VO_DIR, AUDIO_EXT)
    log(f"  Озвучка ({ep / VO_DIR}): {', '.join(f.name for f in voice) if voice else 'НЕТ'}")
    ok &= bool(voice)
    music = files_in(ep / MUSIC_DIR, AUDIO_EXT)
    log(f"  Музыка ({ep / MUSIC_DIR}): {', '.join(f.name for f in music) if music else 'НЕТ — обязательна'}")
    ok &= bool(music)
    if (project / "script.txt").exists():
        need = ai_needed(script_text(project))
        if need:
            import_ai_images(ep, project)
            have = {p.stem.lower() for p in (project / "media").glob("ai*")}
            missing = [n for n in need if n not in have]
            log(f"  Сгенерированные картинки: {len(need) - len(missing)} из {len(need)}"
                + (f" — нет: {', '.join(missing)}" if missing else ""))
            ok &= not missing
    log("✔ Всё готово к этапу 2" if ok else "… Ещё не всё на месте")
    return ok


# ───────────────────────── этап 2 ─────────────────────────
def link_scene_files(ep: Path, project: Path, text: str) -> None:
    """Свои кадры, названные в [СЦЕНА: файл] / [ФОН: файл], → 06_montage/media ссылками (поиск по имени без расширения
    во всех своих папках: 05_footage, 03_generated, 02_characters)."""
    by_stem = {}
    for d in OWN_DIRS:
        if not (ep / d).is_dir():
            continue
        for p in (ep / d).rglob("*"):
            if (p.is_file() and p.suffix.lower() in IMAGE_EXT | VIDEO_EXT and not p.name.lower().startswith(("s_", "s-"))
                    and "source_for_gen" not in p.parts):
                by_stem.setdefault(p.stem.lower(), p)
                by_stem.setdefault(p.name.lower(), p)
    for m in re.finditer(r"\[\s*(?:сцена|scene|фон|background)\s*:\s*([^\]]+)\]", text, re.I):
        for tok in re.split(r"[,;]+", m.group(1)):
            key = tok.strip().split("@")[0].lower()
            src = by_stem.get(key)
            if src:
                link(src, project / "media" / src.name)


def cmd_analyze(ep: Path, project: Path, force: bool = False) -> None:
    s = settings_for(project)
    work = project / "work"
    work.mkdir(parents=True, exist_ok=True)
    log(f"▶ Анализ эпизода «{ep.name}»")
    text = script_text(project)
    import_ai_images(ep, project)
    link_scene_files(ep, project, text)
    media = scan_media(project)
    save_json(work / "media.json", media)
    log(f"  Материалы: {sum(m['type'] == 'image' for m in media)} фото, {sum(m['type'] == 'video' for m in media)} видео")
    make_contact_sheet(project, media, work / "contact.jpg")
    voice_files = files_in(ep / VO_DIR, AUDIO_EXT)
    if not voice_files:
        die(f"Нет озвучки в {ep / VO_DIR} — этап 2 начинается с wav")
    parts_plan = load_json(project / "voice_parts.json", None)  # паузы между тактами (audio.voice_layout)
    vh = (files_hash(voice_files) + f":e{bool(s.get('voiceEnhance'))}:g{float(s.get('voicePartGap', 1.0)):.2f}:v2"
          + (":p" + hashlib.md5(json.dumps(parts_plan, sort_keys=True).encode()).hexdigest()[:8] if parts_plan else ""))
    old = load_json(work / "transcript.json", {}) or {}
    voice_wav = work / "voice.wav"
    if not force and old.get("voiceHash") == vh and voice_wav.exists():
        log("  Озвучка не менялась — расшифровка уже есть")
        return
    log(f"  Озвучка: {', '.join(f.name for f in voice_files)}")
    prepare_voice(voice_files, voice_wav, enhance=bool(s.get("voiceEnhance")), gap=float(s.get("voicePartGap", 1.0)),
                  plan=parts_plan)
    from transcribe import glossary, transcribe
    prompt = glossary(" ".join(re.sub(r"\[[^\]]*\]", " ", text).split()))
    t0 = time.time()
    tr = transcribe(voice_wav, language="en", prompt=prompt)
    tr["voiceHash"] = vh
    tr["voiceLufs"] = measure_lufs(voice_wav)
    save_json(work / "transcript.json", tr)
    log(f"  Распознано слов: {len(tr['words'])} за {time.time() - t0:.0f} с; громкость голоса {tr['voiceLufs']} LUFS")


def _planner(ep: Path, project: Path, s: dict):
    """Сцены + тайминг + материалы → Planner (общая часть empty и plan)."""
    from planner import Planner
    work = project / "work"
    media = load_json(work / "media.json")
    if media is None:
        die("Сначала analyze")
    tr = load_json(work / "transcript.json", {"words": []})
    blocks = parse_script(script_text(project), [m["name"] for m in media])
    words = [w for b in blocks for w in b.words]
    ratio = align(words, tr.get("words", []))
    voice_src = rel(work / "voice.wav", project) if (work / "voice.wav").exists() and tr.get("words") else None
    music = [{"src": rel(normalize_music(m["path"], work / "music" / (m["path"].stem + ".wav")), project), "duration": m["duration"]}
             for m in scan_audio(ep / MUSIC_DIR)]
    sfx = ensure_default_sfx(work / "sfx") if s.get("sfx", True) else None
    if tr.get("voiceLufs") is not None:
        s["voiceLufs"] = tr["voiceLufs"]
    return Planner(project, s, media, blocks, words, voice_src, max((w.end for w in words), default=0.0), music, sfx), ratio, tr


def cmd_empty(ep: Path, project: Path) -> list[dict]:
    """Пустые сцены → 06_montage/empty_scenes.json; прошлые решения сохраняются."""
    planner, _, _ = _planner(ep, project, settings_for(project))
    path = project / "empty_scenes.json"
    old = {x["key"]: x.get("choice") for x in (load_json(path, []) or [])}
    empty = planner.empty_scenes()
    for x in empty:
        x["choice"] = old.get(x["key"])
    save_json(path, empty)
    if not empty:
        log("✔ Пустых сцен нет")
    for i, x in enumerate(empty, 1):
        log(f"  {i}) {fmt_time(x['start'])}–{fmt_time(x['end'])} «{x['text'][:70]}» запрос: {x['query'] or '—'}"
            f" → {x['choice'] or 'НУЖНО РЕШЕНИЕ: card | nearby | или [КАРТИНКА] в сценарии'}")
    return empty


def cmd_plan(ep: Path, project: Path, force: bool = False) -> dict:
    s = settings_for(project)
    plan_path = project / "plan.json"
    existing = load_json(plan_path)
    if existing and existing.get("manual") and not force:
        log("▶ plan.json отмечен как ручной (\"manual\": true) — не перезаписываю (--force для пересборки)")
        return existing
    if not cmd_inputs(ep, project):
        die("Не всё на месте для плана (см. выше)")
    empty = cmd_empty(ep, project)
    undecided = [x for x in empty if x.get("choice") not in ("card", "nearby")]
    if undecided:
        die(f"Пустых сцен без решения: {len(undecided)} — заполнить choice в {project / 'empty_scenes.json'}")
    s["emptyScenes"] = {x["key"]: x["choice"] for x in empty}
    log("▶ Строю план монтажа")
    planner, ratio, tr = _planner(ep, project, s)
    log(f"  Совпадение сценария с озвучкой: {ratio * 100:.0f}%")
    if ratio < 0.9:
        log("  ! Меньше 90% — найти расхождение по work/transcript.json и показать Nurlan")
    plan = planner.build()
    prebake_lut(project, plan, s)
    prebake_blur(project, plan)
    save_json(plan_path, plan)
    found = load_json(project / "work" / "found.json")
    if found:  # авторство — только для того, что реально попало в ролик
        from finder import write_credits
        write_credits(project, found)
    write_chapters(plan, project / "output" / f"{ep.name}_chapters.txt")
    write_words(plan, project / "output" / f"{ep.name}-words.json")
    write_shotlist(ep, project, plan, project / "output" / f"{ep.name}_shotlist.json")
    kinds: dict[str, int] = {}
    for sc in plan["scenes"]:
        kinds[sc["kind"]] = kinds.get(sc["kind"], 0) + 1
    srcs = [Path(sc.get("src", "")).name for sc in plan["scenes"] if sc.get("kind") == "media"]
    srcs += [Path(it.get("src", "")).name for sc in plan["scenes"] if sc.get("kind") == "collage" for it in sc.get("items", [])]
    source_of = {f["file"]: f.get("source") for it in (found or {}).values() for f in it.get("files", [])}
    n_ai = sum(n.lower().startswith("ai") for n in srcs)
    n_web = sum(source_of.get(n) not in (None, "local") for n in srcs)  # интернет и sources.txt
    log(f"  Сцен: {len(plan['scenes'])} ({', '.join(f'{k} {v}' for k, v in kinds.items())}), длительность {fmt_time(plan['duration'])}")
    log(f"  Кадры: свои (05_footage) {len(srcs) - n_ai - n_web}, из интернета {n_web}, сгенерированные {n_ai}")
    log(f"  Главы: {len(plan['meta']['chapters'])}; музыка под голосом: {plan['music'][0]['duckVolume']} (голос − 13 дБ)")
    for w in plan["meta"]["warnings"]:
        log(f"  ! {w}")
    log("⏸ Рендер — только после подтверждения Nurlan")
    return plan


def prebake_lut(project: Path, plan: dict, s: dict) -> None:
    """LUT канала на кадры (решение Nurlan, EP-08): каждый кадр сцены из media/ → цветокоррекция копией в work/lut/.
    Плашки, титры и инфографику движок рисует поверх — LUT их не трогает. settings: "lut" — путь к .cube."""
    lut = Path(str(s.get("lut") or ""))
    if not s.get("lut") or not lut.is_file():
        if s.get("lut"):
            log(f"  ! LUT не найден: {lut} — кадры без цветокоррекции")
        return
    out_dir = project / "work" / "lut"
    out_dir.mkdir(parents=True, exist_ok=True)
    img_ext, vid_ext = (".jpg", ".jpeg", ".png", ".webp", ".bmp"), (".mp4", ".mov", ".webm", ".mkv", ".m4v")
    cache: dict[str, str] = {}
    n_new = 0

    def graded(src: str) -> str:
        nonlocal n_new
        if src in cache:
            return cache[src]
        path = project / src
        ext = path.suffix.lower()
        if not src.replace("\\", "/").startswith("media/") or ext not in img_ext + vid_ext or not path.exists():
            return src
        dst = out_dir / (path.stem + (".jpg" if ext in img_ext else ".mp4"))
        if not dst.exists() or dst.stat().st_mtime < max(path.stat().st_mtime, lut.stat().st_mtime):
            scale = "" if ext in img_ext else "scale=w='min(1920,iw)':h='min(1080,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2,"  # видео больше 1080p движку тяжело
            cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(path.resolve()), "-vf", f"{scale}format=rgb24,lut3d={lut.name}"]
            cmd += (["-frames:v", "1", "-q:v", "2"] if ext in img_ext else
                    ["-c:v", "libx264", "-crf", "17", "-preset", "veryfast", "-g", "15", "-bf", "0", "-pix_fmt", "yuv420p", "-c:a", "copy"])
            subprocess.run(cmd + [str(dst.resolve())], check=True, cwd=str(lut.parent))  # имя .cube без пути — без экранирования «D:»
            n_new += 1
        cache[src] = rel(dst, project)
        return cache[src]

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k in ("src", "blurSrc") and isinstance(v, str):
                    x[k] = graded(v)
                else:
                    walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(plan.get("scenes", []))
    log(f"  LUT {lut.name}: кадров {len(cache)}, новых {n_new}")


def prebake_blur(project: Path, plan: dict) -> None:
    """Размытые фоны готовим заранее картинками — рендер заметно быстрее."""
    try:
        from PIL import Image, ImageFilter
        Image.MAX_IMAGE_PIXELS = None
    except ImportError:
        return
    out_dir = project / "work" / "blur"
    out_dir.mkdir(parents=True, exist_ok=True)
    cache: dict[tuple[str, int], str] = {}

    def baked(src: str, radius: int) -> str | None:
        key = (src, radius)
        if key in cache:
            return cache[key]
        path = project / src
        if path.suffix.lower() not in (".jpg", ".jpeg", ".png", ".webp", ".bmp") or not path.exists():
            return None
        dst = out_dir / f"{path.stem}_b{radius}.jpg"
        if not dst.exists() or dst.stat().st_mtime < path.stat().st_mtime:
            im = Image.open(path).convert("RGB")
            im.thumbnail((960, 960))
            im = im.filter(ImageFilter.GaussianBlur(radius / 2))
            im.save(dst, quality=90)
        cache[key] = rel(dst, project)
        return cache[key]

    for sc in plan["scenes"]:
        bg = sc.get("background")
        if bg and bg.get("src") and bg.get("mediaType", "image") == "image" and bg.get("blur", 18) > 0:
            b = baked(bg["src"], int(bg.get("blur", 18)))
            if b:
                bg["src"], bg["blur"] = b, 0
        if sc.get("kind") == "media" and sc.get("fit") == "blurfill" and sc.get("mediaType") == "image":
            b = baked(sc["src"], 40)
            if b:
                sc["blurSrc"] = b


# ───────────────────────── рендер ─────────────────────────
def remotion_cmd() -> list[str]:
    cli = ENGINE / "node_modules" / "@remotion" / "cli" / "remotion-cli.js"
    if not cli.exists():
        die("Движок не установлен: в папке engine выполнить npm install (кэш npm — на D:)")
    return [which_or_die("node"), str(cli)]


def final_asset(ep: Path) -> Path:
    """Готовый ролик для загрузки (правило Nurlan, EP-08): ep-N/09_final_assets/ep-NN-final.mp4 (ep-8 → ep-08-final.mp4).
    Последний полный рендер заменяет прошлый финал; версии ep-N_vK.mp4 остаются в 06_montage."""
    m = re.search(r"(\d+)", ep.name)
    return ep / "09_final_assets" / (f"ep-{int(m.group(1)):02d}-final.mp4" if m else f"{ep.name}-final.mp4")


def next_version(ep: Path) -> Path:
    """06_montage/ep-8_v1.mp4, _v2 … — следующая свободная версия (в корне папки монтажа)."""
    out = ep / MONTAGE_DIR
    out.mkdir(exist_ok=True)
    k = 1
    while (out / f"{ep.name}_v{k}.mp4").exists():
        k += 1
    return out / f"{ep.name}_v{k}.mp4"


def cmd_render(ep: Path, project: Path, preview: bool = False, part: str | None = None) -> Path:
    s = settings_for(project)
    plan = load_json(project / "plan.json")
    if not plan:
        die("Нет plan.json — сначала plan")
    if s.get("sfx", True):
        ensure_default_sfx(project / "work" / "sfx")
    props_path = project / "work" / "props.json"
    save_json(props_path, {k: v for k, v in plan.items() if k not in ("meta", "manual")})
    out_dir = project / "output"
    out_dir.mkdir(exist_ok=True)
    raw = project / "work" / ("render_preview.mp4" if preview else "render.mp4")
    conc = s.get("concurrency") or max(2, (os.cpu_count() or 4) // 2)
    cmd = remotion_cmd() + ["render", "src/index.ts", "Main", str(raw), f"--props={props_path}",
                            f"--public-dir={project}", f"--concurrency={conc}", "--log=info", "--timeout=120000"]
    if preview:
        cmd += ["--scale=0.5", "--crf=26"]
    if part:  # кусок ролика: --part 50-70 (секунды)
        a, b = (float(x) for x in part.split("-"))
        cmd += [f"--frames={int(a * plan['fps'])}-{min(int(b * plan['fps']), int(plan['duration'] * plan['fps']) - 1)}"]
        raw = raw.with_name(raw.stem + "_part.mp4")
        cmd[cmd.index("Main") + 1] = str(raw)
    log(f"▶ Рендер {'чернового ' if preview else ''}видео ({fmt_time(plan['duration'])}, потоков: {conc})...")
    t0 = time.time()
    # временные файлы движка (копия папки монтажа ~1 ГБ, кадры видео) — на D:, на C: мало места (EP-08: рендер упал)
    tmp = Path(os.environ.get("VE_TMP", "D:/YouTube-Studio/.cache/remotion-tmp"))
    tmp.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "TEMP": str(tmp), "TMP": str(tmp), "TMPDIR": str(tmp)}
    if subprocess.run(cmd, cwd=str(ENGINE), env=env).returncode != 0:
        die("Рендер не удался — смотрите сообщения выше")
    log(f"  Рендер занял {time.time() - t0:.0f} с")
    final = out_dir / (f"{ep.name}_preview.mp4" if preview else f"{ep.name}_part_{part}.mp4" if part else f"{ep.name}.mp4")
    log("▶ Громкость под стандарт YouTube...")
    # прошлые версии ep-N_vK.mp4 — жёсткие ссылки на этот файл: перезапись на месте испортила бы их (EP-08: v1 стал равен v2)
    final.unlink(missing_ok=True)
    meas = loudnorm(raw, final, target=float(s.get("loudness", -14)))
    if meas:
        log(f"  Было {meas.get('input_i')} LUFS → стало {s.get('loudness', -14)} LUFS")
    write_srt(plan, out_dir / f"{ep.name}.srt")
    write_chapters(plan, out_dir / f"{ep.name}_chapters.txt")
    write_words(plan, out_dir / f"{ep.name}-words.json")
    if not preview and not part:
        dst = next_version(ep)
        link(final, dst)
        fin = final_asset(ep)
        fin.parent.mkdir(exist_ok=True)
        fin.unlink(missing_ok=True)
        shutil.copy2(final, fin)  # отдельный файл, не ссылка — следующий рендер его не тронет
        log(f"\n✔ Готово: {dst}\n  Финал: {fin}")
    else:
        log(f"\n✔ Готово: {final}")
    return final


def srt_time(t: float) -> str:
    ms = int(round(max(0.0, t) * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    sec, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"


def write_srt(plan: dict, path: Path) -> None:
    """Субтитры для загрузки в YouTube отдельным файлом (в видео не вшиваются)."""
    cues = (plan.get("captions") or {}).get("cues", [])
    if cues:
        path.write_text("\n".join(f"{i}\n{srt_time(c['start'])} --> {srt_time(c['end'])}\n" + "\n".join(c["lines"]) + "\n"
                                  for i, c in enumerate(cues, 1)), encoding="utf-8")


def write_words(plan: dict, path: Path) -> None:
    """Слова озвучки на шкале готового ролика — для Video-Wrapper (таймкоды берёт только у нас, с EP-09).
    [{"w": "Greenland.", "start": 0.3, "end": 1.2}, …] — из plan.json → captions.cues[].words."""
    words = [{"w": w["text"], "start": w["start"], "end": w["end"]}
             for c in (plan.get("captions") or {}).get("cues", []) for w in c.get("words", [])]
    if words:
        save_json(path, words)


def write_shotlist(ep: Path, project: Path, plan: dict, path: Path) -> None:
    """Каждый кадр ролика для Video-Wrapper (выбор кадров на обложку): таймкод, текст под кадром, что в кадре,
    исходный файл — 03_generated / 05_footage / 02_characters (по жёсткой ссылке) или скачанный из интернета (media).
    Это НЕ ep-N-shots.json (тот — список пробелов для Nurlan и вход ReGen/Gen)."""
    from local_index import load as load_index
    found = load_json(project / "work" / "found.json", {}) or {}
    by_file = {f.get("file"): f for it in found.values() for f in it.get("files", []) if f.get("file")}
    own, captions = {}, {}
    for d in OWN_DIRS:
        if (ep / d).is_dir():
            for p in (ep / d).rglob("*"):
                if p.is_file() and p.suffix.lower() in IMAGE_EXT | VIDEO_EXT:
                    st = p.stat()
                    own[(st.st_dev, st.st_ino)] = p
            captions.update({k: v.get("caption", "") for k, v in load_index(ep / d).items()})
    for e in load_json(project / "work" / "regen.json", []) or []:  # сгенерированное ReGen / Gen — описание из журнала
        if e.get("status") in ("ok", "low_score") and e.get("out"):
            captions.setdefault(e["out"], (e.get("analysis") or {}).get("shows") or e.get("prompt", "")[:200])
    media_by_stem = {p.stem: p for p in (project / "media").glob("*") if p.is_file()}
    words = [w for c in (plan.get("captions") or {}).get("cues", []) for w in c.get("words", [])]

    def origin(src: str) -> tuple[str, str]:
        """(путь исходника относительно эпизода, что в кадре)."""
        m = media_by_stem.get(Path(src).stem)  # work/lut/<stem>.jpg → media/<stem>.*
        if not m:
            return src, ""
        st = m.stat()
        o = own.get((st.st_dev, st.st_ino))
        f = by_file.get(m.name) or {}
        what = (f.get("check") or {}).get("shows") or (captions.get(o.name) if o else "") or f.get("title") or ""
        return (rel(o, ep) if o else rel(m, ep)), str(what)[:200]

    out = []
    for sc in plan.get("scenes", []):
        srcs = [sc["src"]] if sc.get("src") else [it["src"] for it in sc.get("items", []) if it.get("src")]
        if not srcs:
            continue
        text = " ".join(w["text"] for w in words if sc["start"] - 0.05 <= w["start"] < sc["end"])
        for src in srcs:
            file, what = origin(src)
            out.append({"start": fmt_time(sc["start"]), "end": fmt_time(sc["end"]), "start_s": sc["start"], "end_s": sc["end"],
                        "kind": sc.get("mediaType", sc["kind"]), "text": text[:300], "shows": what, "file": file})
    save_json(path, out)


def write_chapters(plan: dict, path: Path) -> None:
    """Главы для описания YouTube: «0:00 Intro» … (YouTube требует минимум 3)."""
    ch = (plan.get("meta") or {}).get("chapters") or []
    if len(ch) >= 3:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(f"{fmt_time(c['start'])} {c['title']}" for c in ch) + "\n", encoding="utf-8")


def cmd_check(ep: Path, project: Path) -> None:
    """Кадр из середины каждой сцены → 06_montage/work/check.jpg + поиск пустых чёрных участков."""
    plan = load_json(project / "plan.json")
    video = project / "output" / f"{ep.name}.mp4"
    if not video.exists():
        video = project / "output" / f"{ep.name}_preview.mp4"
    if not plan or not video.exists():
        die("Нет готового видео для проверки")
    chk = project / "work" / "check"
    if chk.exists():
        shutil.rmtree(chk)  # своя служебная папка в 06_montage
    chk.mkdir(parents=True)
    log("▶ Проверка: кадры из середины каждой сцены")
    for i, sc in enumerate(plan["scenes"]):
        t = (sc["start"] + sc["end"]) / 2
        run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1", "-vf", "scale=640:-2",
             str(chk / f"{i + 1:03d}_{sc['id']}.jpg")], check=False)
    res = run(["ffmpeg", "-hide_banner", "-i", str(video), "-vf", "blackdetect=d=0.4:pix_th=0.06", "-an", "-f", "null", "-"], check=False)
    blacks = []
    for ln in (res.stderr or "").splitlines():
        m = re.search(r"black_start:([\d.]+) black_end:([\d.]+)", ln)
        if m and float(m.group(1)) > 1.5 and float(m.group(2)) < plan["duration"] - 1.5:  # начало и конец — норма
            blacks.append(f"{fmt_time(float(m.group(1)))} – {fmt_time(float(m.group(2)))}")
    from PIL import Image
    imgs = sorted(chk.glob("*.jpg"))
    sheet = Image.new("RGB", (4 * 640, ((len(imgs) + 3) // 4) * 360), (0, 0, 0))
    for k, p in enumerate(imgs):
        sheet.paste(Image.open(p), ((k % 4) * 640, (k // 4) * 360))
    sheet.save(project / "work" / "check.jpg", quality=85)
    log(f"  Контрольный лист: {project / 'work' / 'check.jpg'}")
    log("  ! Тёмные участки: " + ", ".join(blacks) if blacks else "  Пустых чёрных участков нет")


def cmd_studio(project: Path) -> None:
    plan = load_json(project / "plan.json")
    if not plan:
        die("Нет plan.json")
    props_path = project / "work" / "props.json"
    save_json(props_path, {k: v for k, v in plan.items() if k not in ("meta", "manual")})
    log("▶ Открываю просмотр в браузере (остановить — закрыть процесс)")
    subprocess.run(remotion_cmd() + ["studio", "src/index.ts", f"--props={props_path}", f"--public-dir={project}"], cwd=str(ENGINE))


# ───────────────────────── запуск ─────────────────────────
def main() -> None:
    ap = argparse.ArgumentParser(description="VideoEditor 2.0", formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("command", choices=["prepare", "passport", "index", "prompts", "find", "inputs", "analyze", "empty", "plan",
                                        "render", "check", "studio", "regen", "gen", "regravure", "refs", "shotrefs",
                                        "findstats", "fill"])
    ap.add_argument("episode", nargs="?", help="папка эпизода в production/honest-lies, например ep-7 (findstats — не нужен)")
    ap.add_argument("--force", action="store_true", help="пересобрать заново (поиск / расшифровку / ручной план / regen: перезаписать)")
    ap.add_argument("--preview", action="store_true", help="render: черновик в половинном разрешении")
    ap.add_argument("--part", help="render: только кусок, секунды «50-70»")
    ap.add_argument("--apply", action="store_true", help="passport: дописать новые места и страны в data/")
    ap.add_argument("--shots", help="regen / gen / shotrefs: только эти шоты, через запятую: 63,71")
    ap.add_argument("--dry", action="store_true", help="regen / gen / regravure: только промты, без генерации картинки")
    ap.add_argument("--file", help="shotrefs: другой список шотов вместо ep-N-shots.json (например to-find-manually.json)")
    ap.add_argument("--note", default="", help="regravure: разовая добавка к промту, по-английски")
    ap.add_argument("--ids", help="regravure / refs: только эти люди из cast.json, через запятую: john_mcgoff,eschel_rhoodie")
    a = ap.parse_args()
    if a.command == "findstats":
        return __import__("find_history").stats()
    if not a.episode:
        die("Укажите эпизод, например: ve.py find ep-13")
    ep = episode_dir(a.episode)
    project = edit_dir(a.episode)
    if a.command != "prepare" and not project.exists():
        die(f"Нет {project} — сначала prepare")
    {"prepare": lambda: cmd_prepare(ep, project),
     "passport": lambda: cmd_passport(ep, project, a.apply, a.force),
     "index": lambda: cmd_index(ep),
     "prompts": lambda: cmd_prompts(ep, project),
     "find": lambda: cmd_find(ep, project, a.force),
     "fill": lambda: __import__("gap_fill").run(ep),  # пустые шоты с образцом → ReGen → сценарий
     "inputs": lambda: cmd_inputs(ep, project),
     "analyze": lambda: cmd_analyze(ep, project, a.force),
     "empty": lambda: cmd_empty(ep, project),
     "plan": lambda: cmd_plan(ep, project, a.force),
     "render": lambda: cmd_render(ep, project, a.preview, a.part),
     "check": lambda: cmd_check(ep, project),
     "studio": lambda: cmd_studio(project),
     "regen": lambda: __import__("image_regenerator").run(  # ImageReGen: новые фото по референсам refs/s_<шот>_N
         ep, {int(x) for x in a.shots.split(",")} if a.shots else None, a.force, a.dry),
     "gen": lambda: __import__("image_generator").run(  # ImageGenerator: фото с нуля по полю generate
         ep, {int(x) for x in a.shots.split(",")} if a.shots else None, a.force, a.dry),
     "regravure": lambda: __import__("image_regravure").run(  # ReGravure: гравюры людей по 02_characters/refs/s_<id>_N
         ep, {x.strip() for x in a.ids.split(",")} if a.ids else None, a.force, a.dry, a.note),
     "refs": lambda: __import__("person_refs").run(  # референсы людей по cast.json → 02_characters/refs/s_<id>_1
         ep, {x.strip() for x in a.ids.split(",")} if a.ids else None, a.dry),
     "shotrefs": lambda: __import__("shot_refs").run(  # образцы для ReGen по шотам-пробелам → 06_montage/refs/s_<шот>_1
         ep, {int(x) for x in a.shots.split(",")} if a.shots else None, a.dry, a.file)}[a.command]()


if __name__ == "__main__":
    main()
