"""ReGravure — гравюры людей по референсам (OpenAI): один стиль канала для всех лиц, без чужих прав на фото.

Идёт по людям из 02_characters/cast.json. Для человека ищет референс 02_characters/refs/s_<id>_N.jpg
(понимает и s_<id>.jpg, s-<id>-2.jpg); нет референса — человек пропускается. Одна гравюра на человека —
по первому референсу (меньший N). Итерация:
  1) gpt-4.1-mini смотрит референс: он / она (местоимение в промте) и есть ли на нём одно ясное лицо;
  2) gpt-image-2.5-sunburst получает референс + ПРОМТ NURLAN (как есть, без переписывания) → гравюра;
  3) gpt-4.1-mini сравнивает гравюру с референсом: сходство лица + стиль (сине-серый фон, без сепии, без растра), 0–10.
     ≥ PASS_SCORE (7) — принято; ниже — одна перегенерация с тем же промтом, сохраняется лучшая.
Результат → 02_characters/<id>_01.png (john_mcgoff_01.png) — подставляется в шоты по имени, как фото Nurlan.
Если у человека уже есть свой кадр <id>_NN.* — пропуск (--force — перезаписать <id>_01.png).
Журнал и стоимость — общий 06_montage/work/regen.json (tool: "regravure").

  .venv/Scripts/python.exe tools/ve.py regravure ep-9 [--ids john_mcgoff,eschel_rhoodie] [--force] [--dry]
  --dry — только найти референсы и показать промт, без запросов к OpenAI.
  --note "…" — разовая добавка к промту (EP-09, Mostert: дорисовать пол-лица по центру).
"""
from __future__ import annotations

import re
import time
import urllib.error
from datetime import datetime
from pathlib import Path

from image_regenerator import ANALYST, FORMAT, MAX_RETRIES, PAINTER, PASS_SCORE, QUALITY, REF_EXT, SIZE, _ask, _cost, _key, _paint
from util import CHARACTERS_DIR, EDIT_DIR, load_json, log, save_json

# промт Nurlan (2026-10-20) — слово в слово; {pron} — his / her по референсу
GRAVURE_PROMPT = ("Using the provided reference image, generate an engraving illustration of the character while strictly "
                  "preserving {pron} exact facial anatomy, proportions, expression, lighting, and composition: modern technical "
                  "engraving, banknote style crosshatch etching, crisp late 20th-century line art, sharp and precise ink line work, "
                  "pure monochrome, no halftone, strict light slate-blue navy background, clean graphic illustration, NOT a "
                  "photograph, strictly NO sepia, NO antique feel, NO warm brown tints, NO yellowed paper texture. Convert all "
                  "photographic shading, skin textures, fabric folds of the suit, and anatomical volume of the skull and facial "
                  "bone, eyes, ears, mouth, nose structure entirely into sharp, interlocking mathematical cross-hatching under "
                  "clean, directional lighting against the solid light slate-blue navy background. Absolutely no film grain, no "
                  "photographic blur, and no halftone dots. Aspect ratio 16:9")

REF_PROMPT = """Look at this reference photo of one person (a portrait for an engraving).
Return JSON: {"gender": "male" or "female", "one_clear_face": true/false, "notes": "1 short sentence: who/what is visible"}"""

CHECK_PROMPT = """You check an ENGRAVING made from a reference portrait for a history documentary channel.
The first image is the engraving. The person in the reference: {notes}
Rate 0-10 how well it meets BOTH:
1) likeness — same face: facial anatomy, proportions, expression, hairline, glasses if any (judge the engraving itself:
   is it a believable precise portrait, not a generic face);
2) style — monochrome cross-hatching line engraving on a solid light slate-blue / navy background; NO sepia, NO brown or
   yellow paper tint, NO halftone dots, NO film grain, NOT a photograph; no captions, signatures or watermarks.
Return JSON: {{"score": 0-10, "issues": ["short list, empty if none"]}}"""


def _mime(p: Path) -> str:
    s = p.suffix.lower()
    return "image/png" if s == ".png" else "image/webp" if s == ".webp" else "image/jpeg"


def _refs(refs_dir: Path, pid: str) -> list[Path]:
    """Референсы человека: s_<id>_N / s_<id> / s-<id>-N (регистр и разделители не важны), по возрастанию N."""
    pat = re.compile(rf"^s[_\-]{re.escape(pid)}(?:[_\-](\d+))?$", re.I)
    found = []
    for p in refs_dir.glob("*") if refs_dir.exists() else []:
        m = pat.match(p.stem)
        if m and p.suffix.lower() in REF_EXT:
            found.append((int(m.group(1) or 0), p))
    return [p for _, p in sorted(found)]


def run(ep: Path, ids_filter: set[str] | None = None, force: bool = False, dry: bool = False, note: str = "") -> None:
    chars = ep / CHARACTERS_DIR
    refs_dir = chars / "refs"
    refs_dir.mkdir(parents=True, exist_ok=True)
    cast = load_json(chars / "cast.json", {}) or {}
    people = [p for p in cast.get("people", []) or [] if p.get("id")]
    if not people:
        raise SystemExit(f"Нет людей в {chars / 'cast.json'}")
    journal_path = ep / EDIT_DIR / "work" / "regen.json"
    journal = load_json(journal_path, []) or []
    key = None if dry else _key()
    n_analyst = n_painter = 0
    spent = 0.0
    log(f"▶ ReGravure {ep.name}: {PAINTER}, {SIZE}, {QUALITY}; референсы — {refs_dir}{' — ТОЛЬКО ПОИСК (--dry)' if dry else ''}")
    no_ref = []
    for person in people:
        pid = person["id"]
        if ids_filter and pid not in ids_filter:
            continue
        refs = _refs(refs_dir, pid)
        if not refs:
            no_ref.append(pid)
            continue
        out = chars / f"{pid}_01.{FORMAT}"
        own = [p for p in chars.glob(f"{pid}_*") if re.fullmatch(rf"{re.escape(pid)}_\d+", p.stem, re.I) and p.suffix.lower() in REF_EXT]
        if own and not force:
            log(f"  {pid}: уже есть {own[0].name} — пропуск (--force — перезаписать {out.name})")
            continue
        ref = refs[0]
        log(f"  {pid} · {ref.name}")
        if dry:
            continue
        entry = {"date": datetime.now().isoformat(timespec="seconds"), "tool": "regravure", "person": pid, "ref": ref.name,
                 "out": out.name, "size": SIZE, "quality": QUALITY}
        t0 = time.time()
        c_an = c_img = 0.0
        try:
            info, u1 = _ask(ref.read_bytes(), _mime(ref), REF_PROMPT, key)
            n_analyst += 1
            c_an += _cost(ANALYST, u1)
            pron = "her" if str(info.get("gender", "")).lower().startswith("f") else "his"
            if info.get("one_clear_face") is False:
                log(f"    ! на референсе нет одного ясного лица ({info.get('notes', '')[:100]}) — гравюра может не выйти")
            prompt = GRAVURE_PROMPT.format(pron=pron)
            if note:  # разовая правка к промту Nurlan (--note), сам промт не меняется
                prompt += ". " + note.strip()
            best, attempts = None, []
            for attempt in range(MAX_RETRIES + 1):
                img, u2 = _paint(ref, prompt, key)
                n_painter += 1
                c_img += _cost(PAINTER, u2)
                check, u3 = _ask(img, "image/png", CHECK_PROMPT.format(notes=info.get("notes", "")), key)
                n_analyst += 1
                c_an += _cost(ANALYST, u3)
                score = float(check.get("score", 0) or 0)
                attempts.append({"score": score, "issues": check.get("issues", [])})
                log(f"    попытка {attempt + 1}: сходство и стиль {score:g}/10"
                    + (f" — {'; '.join(check.get('issues', []))[:160]}" if check.get("issues") else ""))
                if best is None or score > best[1]:
                    best = (img, score)
                if score >= PASS_SCORE:
                    break  # промт Nurlan не переписываем — при низкой оценке просто ещё одна попытка с ним же
            out.write_bytes(best[0])
            entry.update({"status": "ok" if best[1] >= PASS_SCORE else "low_score", "model": PAINTER, "prompt": prompt,
                          "pronoun": pron, "score": best[1], "attempts": attempts, "seconds": round(time.time() - t0)})
            log(f"    {'✓' if best[1] >= PASS_SCORE else '~'} {out.name} — {best[1]:g}/10, ${c_an + c_img:.3f}, {entry['seconds']} с")
        except urllib.error.HTTPError as e:
            msg = e.read().decode(errors="ignore")
            entry.update({"status": "error", "error": f"HTTP {e.code}: {msg[:400]}"})
            log(f"    ! {pid}: HTTP {e.code} {'(модерация OpenAI)' if 'moderation' in msg else ''} {msg[:160]}")
        except Exception as e:  # noqa: BLE001
            entry.update({"status": "error", "error": repr(e)[:400]})
            log(f"    ! {pid}: {e!r}"[:200])
        entry.update({"cost_analysis": round(c_an, 5), "cost_image": round(c_img, 5)})
        spent += c_an + c_img
        journal.append(entry)
        save_json(journal_path, journal)
    if no_ref and not ids_filter:
        log(f"  без референса ({len(no_ref)}): {', '.join(no_ref)}")
    total = sum(x.get("cost_analysis", 0) + x.get("cost_image", 0) for x in journal)
    log(f"✔ Готово: запросов {PAINTER} {n_painter}, проверок {ANALYST} {n_analyst} — ${spent:.2f} "
        f"(за всё время по {ep.name}, ReGen + Gen + ReGravure: ${total:.2f}). Журнал: {journal_path}")
