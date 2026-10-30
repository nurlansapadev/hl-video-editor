"""ImageReGen — новые фото по референсам (OpenAI): обход шаблонности стоков и чужих прав.

Идёт по 06_montage/output/ep-N-shots.json. Для шота ищет референсы 06_montage/refs/s_<шот>_N.jpg;
нет референсов — шот пропускается. Один референс — одна итерация:
  1) gpt-4.1-mini смотрит референс и задание шота (scenario_text, epoch, day_time, place, expected, generate)
     и пишет промт правок: новый снимок по мотивам — другой ракурс, 16:9, время суток, детали задания;
  2) gpt-image-2.5-sunburst получает тот же референс + промт → картинка;
  3) gpt-4.1-mini проверяет правдоподобие результата (0–10). ≥ PASS_SCORE (7) — принято; ниже — одна перегенерация
     по исправленному промту (MAX_RETRIES), сохраняется лучшая → 03_generated/<шот>-<N>-rg.png (63-1-rg.png, 63-2-rg.png).
Уже существующий файл не перезаписывается (--force — перезаписать).
Люди из 02_characters/cast.json с face_policy archive_only — шот не перерисовывается.
Журнал и стоимость (по usage из ответов OpenAI) — 06_montage/work/regen.json.

  .venv/Scripts/python.exe tools/ve.py regen ep-8 [--shots 63,71] [--force] [--dry]
  --dry — только анализ и промт (доли цента), без генерации картинки.
"""
from __future__ import annotations

import base64
import http.client
import io
import json
import re
import threading
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from util import CHARACTERS_DIR, EDIT_DIR, GENERATED_DIR, ROOT, load_json, log, save_json

ANALYST = "gpt-4.1-mini"
PAINTER = "gpt-image-2.5-sunburst"
SIZE = "1280x720"      # 16:9, стороны кратны 16 (требование API); ~1K — «простое» качество
QUALITY = "medium"
FORMAT = "png"
# цены, $ за 1 млн токенов (developers.openai.com, 2026-10): анализ и картинка
PRICE = {ANALYST: {"in": 0.40, "out": 1.60},
         PAINTER: {"text_in": 5.0, "image_in": 8.0, "out": 30.0},
         "gpt-image-2.5-flare": {"text_in": 5.0, "image_in": 8.0, "out": 30.0}}
REF_EXT = (".jpg", ".jpeg", ".png", ".webp")
PASS_SCORE = 7     # правдоподобие ≥ 7 из 10 — принимаем, без перегенерации
MAX_RETRIES = 1    # сколько раз максимум перегенерировать один референс (ограничитель расходов)
PARALLEL = 3       # картинок одновременно (Gen и ReGen): каждая ~15–25 с ждёт OpenAI, процессор не грузит
RETRY_CODES = (429, 500, 502, 503, 504)  # OpenAI перегружен — повторить, а не ронять шот (EP-14: таймауты, 500-е)


def _open(make_req, timeout: int) -> dict:
    """Запрос к OpenAI с двумя повторами при перегрузке (429/5xx) и обрыве / таймауте. → JSON-ответ.
    Повтор картинки после таймаута может стоить вторую картинку (~$0,01–0,02) — дешевле, чем потерянный шот."""
    for attempt in range(3):
        try:
            with urllib.request.urlopen(make_req(), timeout=timeout) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code in RETRY_CODES and attempt < 2:
                log(f"    · OpenAI HTTP {e.code} — повтор через {10 * (attempt + 1)} с")
                time.sleep(10 * (attempt + 1))
                continue
            raise
        except (urllib.error.URLError, TimeoutError, http.client.IncompleteRead, ConnectionError) as e:
            # IncompleteRead — ответ оборвался посреди картинки (EP-14: 1,6 из 1,9 МБ)
            if attempt < 2:
                log(f"    · OpenAI не ответил ({type(e).__name__}) — повтор через 5 с")
                time.sleep(5)
                continue
            raise
    raise RuntimeError("OpenAI: нет ответа")

ANALYST_PROMPT = """You prepare an image-edit instruction for a history documentary YouTube channel (mid-20th century stories).
You get a REFERENCE image and the TASK of one shot. The reference is only a starting point: the result must be a NEW
photograph inspired by it, not a copy and not a cleanup of the original.

TASK of the shot:
{task}

Write a short edit instruction (English, max 120 words) for an image model that will receive this same reference image:
- KEEP the scene of the reference: its subject, setting and type of shot (it was chosen on purpose). Do not replace it
  with a different scene, even if the task describes something else — the task only adjusts details;
- the result is a photograph in 16:9 landscape — unless the TASK explicitly asks for a drawing, painting, illustration,
  map, diagram or poster: then that kind of image, still 16:9; extend or recompose the frame to 16:9;
- change the camera angle or composition noticeably (new viewpoint, different framing or distance);
- adjust toward the TASK where it fits this scene: era details, time of day, place cues, number of people, objects;
- keep everything physically plausible for this setting and era: nothing that could not exist there (e.g. no windows
  or portholes inside a submarine, no daylight deep underground, no modern equipment in a 1960 scene);
- no captions, watermarks, logos or signatures over the photo; text that belongs to the scene itself (signs, plates,
  hull numbers, labels on equipment) is fine if it fits the task and era;
- mention a period film stock (35mm, Polaroid, black-and-white film of the 1930s, etc.) ONLY if the reference or the task
  clearly needs it; otherwise just say "photograph" (or the image type the task asks for);
- do not ask to keep or reproduce faces of real identifiable people; people may appear as unidentifiable figures.

Return JSON: {{"shows": "what the reference shows, 1 sentence", "has_watermark": true/false, "has_logo_or_text": true/false,
"identifiable_people": true/false, "gap": "what differs from the task, 1 sentence", "prompt": "the edit instruction"}}"""

CHECK_PROMPT = """You check a generated image for a history documentary YouTube channel (mid-20th century stories).
It is a photograph, unless the task asks for a drawing, painting, illustration, map, diagram or poster.
TASK of the shot:
{task}
Prompt it was generated from:
{prompt}

Rate PLAUSIBILITY 0-10: for a photo — could it really have been taken in this setting and era; for a drawing / map /
diagram — is it the kind of image the task asks for and true to the setting and era. Be practical, not picky:
small generation artifacts are fine. Lower the score for things that could not exist there (windows inside a submarine,
daylight underground, modern equipment or clothes in an old scene), broken anatomy, garbled objects, captions,
watermarks or logos over the photo. Signs and labels that belong to the scene are fine.
Return JSON: {{"score": 0-10, "issues": ["short list, empty if none"],
"prompt": "the same edit instruction rewritten to fix the issues (English, max 120 words)"}}"""


def _key() -> str:
    k = (load_json(ROOT / "keys.json", {}) or {}).get("openai")
    if not k:
        raise SystemExit("Нет ключа openai в keys.json")
    return k


def is_video(shot: dict) -> bool:
    """Шот, для которого нужен видеоряд (kind = видео / video), — картинки ReGen и Gen для него не делают."""
    return str(shot.get("kind", "")).strip().lower() in ("видео", "video")


def _task_text(shot: dict) -> str:
    fields = ("scenario_text", "epoch", "day_time", "place", "expected", "generate", "query")
    return "\n".join(f"{f}: {shot[f]}" for f in fields if shot.get(f))


def _blocked_person(shot: dict, cast: dict) -> str | None:
    """Имя человека с face_policy archive_only, упомянутого в задании шота (его не перерисовываем)."""
    text = " ".join(str(shot.get(f, "")) for f in ("scenario_text", "expected", "generate", "query")).lower()
    for p in cast.get("people", []) or []:
        if p.get("face_policy") != "archive_only" or not p.get("name"):
            continue
        surname = re.sub(r"\(.*?\)", "", p["name"]).split()[-1].lower()
        if len(surname) > 2 and re.search(rf"\b{re.escape(surname)}\b", text):
            return p["name"]
    return None


def _ask(image: bytes, mime: str, text: str, key: str) -> tuple[dict, dict]:
    """gpt-4.1-mini: картинка + задание → JSON-ответ. → (ответ, usage)."""
    b64 = base64.b64encode(image).decode()
    body = {"model": ANALYST, "temperature": 0.4, "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": text},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}", "detail": "low"}}]}]}
    res = _open(lambda: urllib.request.Request(
        "https://api.openai.com/v1/chat/completions", data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"}), timeout=60)
    return json.loads(res["choices"][0]["message"]["content"]), res.get("usage", {})


REF_MAX_PX = 2000  # больше — уменьшаем перед отправкой (EP-14: Hopkins 7474×9269 → HTTP 400 «Invalid input image»)


def _ref_bytes(path: Path) -> tuple[bytes, str, str]:
    """Референс как есть или, если больше REF_MAX_PX по длинной стороне, — уменьшенный JPEG. → (байты, mime, имя)."""
    mime = "image/png" if path.suffix.lower() == ".png" else "image/webp" if path.suffix.lower() == ".webp" else "image/jpeg"
    try:
        from PIL import Image
        Image.MAX_IMAGE_PIXELS = None
        with Image.open(path) as im:
            if max(im.size) <= REF_MAX_PX:
                return path.read_bytes(), mime, path.name
            im = im.convert("RGB")
            im.thumbnail((REF_MAX_PX, REF_MAX_PX))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=90)
            return buf.getvalue(), "image/jpeg", path.stem + ".jpg"
    except Exception:  # noqa: BLE001 — не открылось Pillow: шлём как есть, ответ API скажет, что не так
        return path.read_bytes(), mime, path.name


def _multipart(fields: dict, files: list[tuple[str, Path]]) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    out = []
    for k, v in fields.items():
        out.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    for name, path in files:
        data, mime, fname = _ref_bytes(path)
        out.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{fname}"\r\n'
                   f"Content-Type: {mime}\r\n\r\n".encode() + data + b"\r\n")
    out.append(f"--{boundary}--\r\n".encode())
    return b"".join(out), f"multipart/form-data; boundary={boundary}"


def _paint(ref: Path, prompt: str, key: str) -> tuple[bytes, dict]:
    """gpt-image-2.5-sunburst: референс + промт → картинка. → (байты, usage)."""
    data, ctype = _multipart({"model": PAINTER, "prompt": prompt, "size": SIZE, "quality": QUALITY,
                              "output_format": FORMAT, "n": "1"}, [("image", ref)])
    res = _open(lambda: urllib.request.Request("https://api.openai.com/v1/images/edits", data=data, method="POST",
                                               headers={"Content-Type": ctype, "Authorization": f"Bearer {key}"}), timeout=150)
    return base64.b64decode(res["data"][0]["b64_json"]), res.get("usage", {})


def _cost(model: str, usage: dict) -> float:
    p = PRICE[model]
    if model == ANALYST:
        return (usage.get("prompt_tokens", 0) * p["in"] + usage.get("completion_tokens", 0) * p["out"]) / 1e6
    det = usage.get("input_tokens_details") or {}
    text_in = det.get("text_tokens", 0)
    image_in = det.get("image_tokens", max(0, usage.get("input_tokens", 0) - text_in))
    return (text_in * p["text_in"] + image_in * p["image_in"] + usage.get("output_tokens", 0) * p["out"]) / 1e6


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
    key = _key()
    n = {"analyst": 0, "painter": 0, "spent": 0.0}
    lock = threading.Lock()
    jobs: list[tuple[dict, int, Path, Path]] = []
    log(f"▶ ImageReGen {ep.name}: {PAINTER}, {SIZE}, {QUALITY}{' — ТОЛЬКО АНАЛИЗ (--dry)' if dry else ''}")
    for shot in shots:
        no = shot.get("shot_no")
        if no is None or (shots_filter and no not in shots_filter):
            continue
        if is_video(shot):
            if shots_filter:
                log(f"  шот {no}: пропуск — kind «{shot.get('kind')}» (нужно видео, не картинка)")
            continue
        refs = sorted((p for p in refs_dir.glob(f"s_{no}_*") if p.suffix.lower() in REF_EXT),
                      key=lambda p: int(re.search(r"_(\d+)$", p.stem).group(1)) if re.search(r"_(\d+)$", p.stem) else 0)
        if not refs:
            continue
        who = _blocked_person(shot, cast)
        if who:
            log(f"  шот {no}: пропуск — {who} (face_policy archive_only, только архив)")
            continue
        for k, ref in enumerate(refs, 1):
            out = out_dir / f"{no}-{k}-rg.{FORMAT}"  # 63-1-rg.png, 63-2-rg.png — результат ReGen по 1-му, 2-му референсу
            if out.exists() and not force and not dry:
                log(f"  шот {no}: {out.name} уже есть — пропуск (--force — перезаписать)")
                continue
            jobs.append((shot, no, ref, out))

    def _gemini_fallback(mode: str, shot: dict, ref, out: Path, failed: dict) -> None:
        """OpenAI не справился (таймаут, 5xx, обрыв, отказ модерации) — этот шот рисует Gemini (с 2026-10-30, Nurlan).
        ReGravure сюда не ходит: гравюры только OpenAI."""
        from image_gemini import fallback_ok, paint_one  # здесь: image_gemini сам импортирует этот модуль
        if not fallback_ok():
            return
        log(f"    → шот {shot.get('shot_no')}: OpenAI не справился ({failed.get('error', '')[:60]}) — рисую через Gemini")
        g = paint_one(mode, shot, ref, out)
        g["fallback_for"] = failed.get("error", "")[:200]
        with lock:
            n["spent"] += g["cost_analysis"] + g["cost_image"]
            journal.append(g)
            save_json(journal_path, journal)

    def do(job: tuple[dict, int, Path, Path]) -> None:
        shot, no, ref, out = job
        entry = {"date": datetime.now().isoformat(timespec="seconds"), "shot": no, "ref": ref.name, "out": out.name,
                 "size": SIZE, "quality": QUALITY}
        c_an = c_img = 0.0
        try:
            data, mime, _ = _ref_bytes(ref)
            analysis, u1 = _ask(data, mime, ANALYST_PROMPT.format(task=_task_text(shot)), key)
            n_an, n_im = 1, 0
            c_an = _cost(ANALYST, u1)
            entry.update({"analysis": analysis, "prompt": analysis.get("prompt", "")})
            log(f"  шот {no} · {ref.name}: {analysis.get('shows', '')[:90]}")
            log(f"    шот {no} промт: {entry['prompt'][:220]}")
            if dry:
                entry["status"] = "dry"
            else:
                t0 = time.time()
                prompt, best, attempts = entry["prompt"], None, []
                for attempt in range(MAX_RETRIES + 1):
                    img, u2 = _paint(ref, prompt, key)
                    n_im += 1
                    c_img += _cost(PAINTER, u2)
                    # проверка правдоподобия результата (gpt-4.1-mini), шкала допуска PASS_SCORE
                    check, u3 = _ask(img, "image/png", CHECK_PROMPT.format(task=_task_text(shot), prompt=prompt), key)
                    n_an += 1
                    c_an += _cost(ANALYST, u3)
                    score = float(check.get("score", 0) or 0)
                    attempts.append({"prompt": prompt, "score": score, "issues": check.get("issues", [])})
                    log(f"    шот {no}, попытка {attempt + 1}: правдоподобие {score:g}/10"
                        + (f" — {'; '.join(check.get('issues', []))[:160]}" if check.get("issues") else ""))
                    if best is None or score > best[1]:
                        best = (img, score)
                    if score >= PASS_SCORE or not check.get("prompt"):
                        break
                    prompt = check["prompt"]  # исправленный промт — на следующую попытку
                out_dir.mkdir(parents=True, exist_ok=True)
                out.write_bytes(best[0])
                entry.update({"status": "ok" if best[1] >= PASS_SCORE else "low_score", "model": PAINTER,
                              "score": best[1], "attempts": attempts, "cost_image": round(c_img, 5),
                              "seconds": round(time.time() - t0)})
                log(f"    {'✓' if best[1] >= PASS_SCORE else '~'} {out.name} — правдоподобие {best[1]:g}/10, "
                    f"${c_an + c_img:.3f}, {entry['seconds']} с")
            entry["cost_analysis"] = round(c_an, 5)
            with lock:
                n["analyst"] += n_an
                n["painter"] += n_im
        except urllib.error.HTTPError as e:
            msg = e.read().decode(errors="ignore")
            entry.update({"status": "error", "error": f"HTTP {e.code}: {msg[:400]}"})
            log(f"    ! шот {no}: HTTP {e.code} {'(модерация OpenAI)' if 'moderation' in msg else ''} {msg[:160]}")
        except Exception as e:  # noqa: BLE001
            entry.update({"status": "error", "error": repr(e)[:400]})
            log(f"    ! шот {no}: {e!r}"[:200])
        with lock:
            n["spent"] += c_an + c_img
            journal.append(entry)
            save_json(journal_path, journal)
        if entry.get("status") == "error" and not dry:
            _gemini_fallback("regen", shot, ref, out, entry)

    if len(jobs) > 1:
        log(f"  картинок: {len(jobs)}, одновременно до {PARALLEL}")
    with ThreadPoolExecutor(max_workers=PARALLEL) as ex:
        list(ex.map(do, jobs))
    total = sum(x.get("cost_analysis", 0) + x.get("cost_image", 0) for x in journal)
    log(f"✔ Готово: запросов {PAINTER} {n['painter']}, анализ {ANALYST} {n['analyst']} — ${n['spent']:.2f} "
        f"(за всё время по {ep.name}: ${total:.2f}). Журнал: {journal_path}")
