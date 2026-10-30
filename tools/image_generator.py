"""ImageGenerator (Gen) — фото с нуля для шотов без референса (OpenAI).

Идёт по 06_montage/output/ep-N-shots.json: шоты с полем «generate» и БЕЗ референса в 06_montage/refs
(шоты с референсом — дело ImageReGen). Итерация:
  1) промт = «generate» шота + PROMPT_SUFFIX (без ИИ — промт Nurlan уходит как есть);
  2) gpt-image-2.5-flare генерирует картинку с нуля;
  3) gpt-4.1-mini проверяет правдоподобие (0–10) — общая проверка с ImageReGen. ≥ PASS_SCORE — принято;
     ниже — gpt-4.1-mini переписывает промт с учётом ошибки → одна перегенерация (MAX_RETRIES), сохраняется лучшая.
Результат → 03_generated/<шот>-g.png (32-g.png); существующий файл не перезаписывается (--force — перезаписать).
Люди из cast.json с face_policy archive_only — шот не генерируется. Журнал и стоимость — 06_montage/work/regen.json.

  .venv/Scripts/python.exe tools/ve.py gen ep-8 [--shots 32,37] [--force] [--dry]
  --dry — только показать промты, без запросов к OpenAI.
"""
from __future__ import annotations

import base64
import re
import json
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from image_regenerator import (ANALYST, CHECK_PROMPT, FORMAT, MAX_RETRIES, PARALLEL, PASS_SCORE, QUALITY, REF_EXT, SIZE,
                               _ask, is_video, _blocked_person, _cost, _key, _open, _task_text)
from util import CHARACTERS_DIR, EDIT_DIR, GENERATED_DIR, load_json, log, save_json

PAINTER = "gpt-image-2.5-flare"  # генерация с нуля — быстрая модель (ReGen по референсу — sunburst)
PROMPT_SUFFIX = "16:9 photograph, period-accurate."
PROMPT_SUFFIX_DRAWING = "16:9, period-accurate."  # если generate просит схему, карту, гравюру, картину
# сцена без года в задании и с широкой эпохой паспорта (1939–2025) — «period-accurate» старил её под 1950-е (EP-14: 11 картинок)
PROMPT_SUFFIX_NOW = "16:9 photograph, present-day."
NO_BRANDS = "No real brand names, logos or newspaper mastheads."  # EP-11, EP-14: Radio Shack, SEARS, MACY'S, шапка NYT
YEAR = r"\b(1[5-9]|20)\d\d\s?s?\b|\b(sixties|seventies|eighties|nineties|victorian|edwardian|medieval|ancient)\b"


def _suffix(gen: str, epoch: str) -> str:
    """Добавка к промту: тип картинки + время. Год в задании → «period-accurate»; узкая эпоха шота ([ЭПОХА: 1961]) →
    «period-accurate, {год}»; широкая эпоха паспорта («1939–2025») и нет года → «present-day»."""
    if re.search(DRAWING_WORDS, gen, re.I):
        return PROMPT_SUFFIX_DRAWING
    if re.search(YEAR, gen, re.I):
        return PROMPT_SUFFIX
    ep = str(epoch or "").strip()
    if ep and not re.search(r"[–—-]", ep):  # один год / десятилетие — метка [ЭПОХА] сцены
        return f"16:9 photograph, period-accurate, {ep}."
    return PROMPT_SUFFIX_NOW
# признаки «это не фото» в тексте generate (поле kind ненадёжно: у схем там тоже «фото»)
DRAWING_WORDS = (r"\b(illustrations?|diagrams?|schematics?|cutaway|maps?|engravings?|(pencil|ink|line|charcoal|chalk|technical|patent) drawings?|hand-drawn|paintings?|painted|"
                 r"oil on canvas|watercolou?r|sketch(es)?|posters?|cartoons?|comics?|charts?|infographics?|blueprints?|"
                 r"lithograph|woodcut|etching|propaganda poster|storyboard)\b")


def _generate(prompt: str, key: str) -> tuple[bytes, dict]:
    """PAINTER: текст → картинка с нуля. → (байты, usage)."""
    body = {"model": PAINTER, "prompt": prompt, "size": SIZE, "quality": QUALITY, "output_format": FORMAT, "n": 1}
    res = _open(lambda: urllib.request.Request(
        "https://api.openai.com/v1/images/generations", data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"}), timeout=150)
    return base64.b64decode(res["data"][0]["b64_json"]), res.get("usage", {})


def run(ep: Path, shots_filter: set[int] | None = None, force: bool = False, dry: bool = False) -> None:
    montage = ep / EDIT_DIR
    shots_path = montage / "output" / f"{ep.name}-shots.json"
    shots = load_json(shots_path)
    if not shots:
        raise SystemExit(f"Нет {shots_path}")
    refs_dir, out_dir = montage / "refs", ep / GENERATED_DIR
    cast = load_json(ep / CHARACTERS_DIR / "cast.json", {}) or {}
    journal_path = montage / "work" / "regen.json"
    journal = load_json(journal_path, []) or []
    key = None if dry else _key()
    n = {"analyst": 0, "painter": 0, "spent": 0.0}
    lock = threading.Lock()
    jobs: list[tuple[dict, int, Path, str]] = []
    log(f"▶ ImageGenerator {ep.name}: {PAINTER}, {SIZE}, {QUALITY}{' — ТОЛЬКО ПРОМТЫ (--dry)' if dry else ''}")
    for shot in shots:
        no = shot.get("shot_no")
        if no is None or not shot.get("generate") or (shots_filter and no not in shots_filter):
            continue
        if is_video(shot):
            if shots_filter:
                log(f"  шот {no}: пропуск — kind «{shot.get('kind')}» (нужно видео, не картинка)")
            continue
        refs_of = [p.name for p in refs_dir.glob(f"s_{no}_*") if p.suffix.lower() in REF_EXT]
        if refs_of:  # есть референс — это работа ImageReGen (EP-11, EP-14: шоты молча «пропадали» из Gen)
            log(f"  шот {no}: пропуск — есть образец refs\\{refs_of[0]} → ve.py regen ep-N --shots {no} "
                f"(или удалить образец, чтобы рисовать с нуля)")
            continue
        who = _blocked_person(shot, cast)
        if who:
            log(f"  шот {no}: пропуск — {who} (face_policy archive_only, только архив)")
            continue
        out = out_dir / f"{no}-g.{FORMAT}"
        if out.exists() and not force and not dry:
            log(f"  шот {no}: {out.name} уже есть — пропуск (--force — перезаписать)")
            continue
        gen = shot["generate"].strip().rstrip(".")
        # схема / карта / гравюра — не фото: «photograph» в добавке противоречил бы заданию
        prompt = f"{gen}. {_suffix(gen, shot.get('epoch', ''))} {NO_BRANDS}"
        log(f"  шот {no}: {prompt[:200]}")
        if not dry:
            jobs.append((shot, no, out, prompt))

    def do(job: tuple[dict, int, Path, str]) -> None:
        shot, no, out, prompt = job
        entry = {"date": datetime.now().isoformat(timespec="seconds"), "tool": "gen", "shot": no, "out": out.name,
                 "size": SIZE, "quality": QUALITY, "prompt": prompt}
        t0 = time.time()
        c_an = c_img = 0.0
        try:
            best, attempts = None, []
            for attempt in range(MAX_RETRIES + 1):
                img, u2 = _generate(prompt, key)
                c_img += _cost(PAINTER, u2)
                check, u3 = _ask(img, "image/png", CHECK_PROMPT.format(task=_task_text(shot), prompt=prompt), key)
                c_an += _cost(ANALYST, u3)
                with lock:
                    n["painter"] += 1
                    n["analyst"] += 1
                score = float(check.get("score", 0) or 0)
                attempts.append({"prompt": prompt, "score": score, "issues": check.get("issues", [])})
                log(f"    шот {no}, попытка {attempt + 1}: правдоподобие {score:g}/10"
                    + (f" — {'; '.join(check.get('issues', []))[:160]}" if check.get("issues") else ""))
                if best is None or score > best[1]:
                    best = (img, score)
                if score >= PASS_SCORE or not check.get("prompt"):
                    break
                prompt = check["prompt"]  # gpt-4.1-mini переписал промт с учётом ошибки
            out_dir.mkdir(parents=True, exist_ok=True)
            out.write_bytes(best[0])
            entry.update({"status": "ok" if best[1] >= PASS_SCORE else "low_score", "model": PAINTER, "score": best[1],
                          "attempts": attempts, "seconds": round(time.time() - t0)})
            log(f"    {'✓' if best[1] >= PASS_SCORE else '~'} {out.name} — правдоподобие {best[1]:g}/10, "
                f"${c_an + c_img:.3f}, {entry['seconds']} с")
        except urllib.error.HTTPError as e:
            msg = e.read().decode(errors="ignore")
            entry.update({"status": "error", "error": f"HTTP {e.code}: {msg[:400]}"})
            log(f"    ! шот {no}: HTTP {e.code} {'(модерация OpenAI)' if 'moderation' in msg else ''} {msg[:160]}")
        except Exception as e:  # noqa: BLE001
            entry.update({"status": "error", "error": repr(e)[:400]})
            log(f"    ! шот {no}: {e!r}"[:200])
        entry.update({"cost_analysis": round(c_an, 5), "cost_image": round(c_img, 5)})
        with lock:
            n["spent"] += c_an + c_img
            journal.append(entry)
            save_json(journal_path, journal)

    if len(jobs) > 1:
        log(f"  картинок: {len(jobs)}, одновременно до {PARALLEL}")
    with ThreadPoolExecutor(max_workers=PARALLEL) as ex:
        list(ex.map(do, jobs))
    total = sum(x.get("cost_analysis", 0) + x.get("cost_image", 0) for x in journal)
    log(f"✔ Готово: запросов {PAINTER} {n['painter']}, проверок {ANALYST} {n['analyst']} — ${n['spent']:.2f} "
        f"(за всё время по {ep.name}, ReGen + Gen: ${total:.2f}). Журнал: {journal_path}")
