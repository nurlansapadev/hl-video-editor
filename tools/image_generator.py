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
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

from image_regenerator import (ANALYST, CHECK_PROMPT, FORMAT, MAX_RETRIES, PASS_SCORE, QUALITY, REF_EXT, SIZE,
                               _ask, is_video, _blocked_person, _cost, _key, _task_text)
from util import CHARACTERS_DIR, EDIT_DIR, GENERATED_DIR, load_json, log, save_json

PAINTER = "gpt-image-2.5-flare"  # генерация с нуля — быстрая модель (ReGen по референсу — sunburst)
PROMPT_SUFFIX = "16:9 photograph, period-accurate."
PROMPT_SUFFIX_DRAWING = "16:9, period-accurate."  # если generate просит схему, карту, гравюру, картину
# признаки «это не фото» в тексте generate (поле kind ненадёжно: у схем там тоже «фото»)
DRAWING_WORDS = (r"\b(illustrations?|diagrams?|schematics?|cutaway|maps?|engravings?|(pencil|ink|line|charcoal|chalk|technical) drawings?|hand-drawn|paintings?|painted|"
                 r"oil on canvas|watercolou?r|sketch(es)?|posters?|cartoons?|comics?|charts?|infographics?|blueprints?|"
                 r"lithograph|woodcut|etching|propaganda poster|storyboard)\b")


def _generate(prompt: str, key: str) -> tuple[bytes, dict]:
    """PAINTER: текст → картинка с нуля. → (байты, usage)."""
    body = {"model": PAINTER, "prompt": prompt, "size": SIZE, "quality": QUALITY, "output_format": FORMAT, "n": 1}
    req = urllib.request.Request("https://api.openai.com/v1/images/generations", data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=300) as r:
        res = json.loads(r.read().decode())
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
    n_analyst = n_painter = 0
    spent = 0.0
    log(f"▶ ImageGenerator {ep.name}: {PAINTER}, {SIZE}, {QUALITY}{' — ТОЛЬКО ПРОМТЫ (--dry)' if dry else ''}")
    for shot in shots:
        no = shot.get("shot_no")
        if no is None or not shot.get("generate") or (shots_filter and no not in shots_filter):
            continue
        if is_video(shot):
            if shots_filter:
                log(f"  шот {no}: пропуск — kind «{shot.get('kind')}» (нужно видео, не картинка)")
            continue
        if any(p.suffix.lower() in REF_EXT for p in refs_dir.glob(f"s_{no}_*")):
            continue  # есть референс — это работа ImageReGen
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
        drawing = re.search(DRAWING_WORDS, gen, re.I)
        prompt = f"{gen}. {PROMPT_SUFFIX_DRAWING if drawing else PROMPT_SUFFIX}"
        log(f"  шот {no}: {prompt[:200]}")
        if dry:
            continue
        entry = {"date": datetime.now().isoformat(timespec="seconds"), "tool": "gen", "shot": no, "out": out.name,
                 "size": SIZE, "quality": QUALITY, "prompt": prompt}
        t0 = time.time()
        c_an = c_img = 0.0
        try:
            best, attempts = None, []
            for attempt in range(MAX_RETRIES + 1):
                img, u2 = _generate(prompt, key)
                n_painter += 1
                c_img += _cost(PAINTER, u2)
                check, u3 = _ask(img, "image/png", CHECK_PROMPT.format(task=_task_text(shot), prompt=prompt), key)
                n_analyst += 1
                c_an += _cost(ANALYST, u3)
                score = float(check.get("score", 0) or 0)
                attempts.append({"prompt": prompt, "score": score, "issues": check.get("issues", [])})
                log(f"    попытка {attempt + 1}: правдоподобие {score:g}/10"
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
        spent += c_an + c_img
        journal.append(entry)
        save_json(journal_path, journal)
    total = sum(x.get("cost_analysis", 0) + x.get("cost_image", 0) for x in journal)
    log(f"✔ Готово: запросов {PAINTER} {n_painter}, проверок {ANALYST} {n_analyst} — ${spent:.2f} "
        f"(за всё время по {ep.name}, ReGen + Gen: ${total:.2f}). Журнал: {journal_path}")
