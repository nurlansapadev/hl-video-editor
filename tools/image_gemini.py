"""Gen и ReGen через Gemini — запасной путь, когда OpenAI сбоит (таймауты, ошибки 500).

Те же шоты, те же имена файлов и тот же журнал, что у image_generator (Gen) и image_regenerator (ReGen):
  gen   — шоты с «generate» и без референса → 03_generated/<шот>-g.png;
  regen — шоты с референсами 06_montage/refs/s_<шот>_N.jpg → 03_generated/<шот>-<N>-rg.png.
Всё делает Gemini, OpenAI не нужен совсем: анализ референса и проверка правдоподобия — ANALYST,
картинка — PAINTER (Nano Banana). Промты анализа и проверки — общие с ImageReGen (CHECK_PROMPT, ANALYST_PROMPT),
порог PASS_SCORE и одна перегенерация MAX_RETRIES — те же. Картинка приводится к 1280×720 PNG, как у OpenAI.
Сбой ответа (429, 500, 503, таймаут) — до 3 повторов с паузой; отказ по безопасности — шот пропускается.

Картинки на бесплатном уровне Gemini API недоступны (лимит 0): нужен проект AI Studio с включённой оплатой.
Цена 1K-картинки (ai.google.dev/gemini-api/docs/pricing, 2026-10): gemini-3.1-flash-image $0,067,
gemini-3.1-flash-lite-image $0,034, gemini-3-pro-image $0,134 (OpenAI Gen для сравнения ~$0,009).

  .venv/Scripts/python.exe tools/image_gemini.py gen ep-13 [--shots 32,37] [--force] [--dry] [--model …]
  .venv/Scripts/python.exe tools/image_gemini.py regen ep-13 [--shots 63] [--force] [--dry]
  --dry — gen: только промты (бесплатно); regen: только анализ референса и промт, без картинки.
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

from image_generator import NO_BRANDS, _suffix
from image_regenerator import (ANALYST_PROMPT, CHECK_PROMPT, FORMAT, MAX_RETRIES, PASS_SCORE, REF_EXT,
                               _blocked_person, _task_text, is_video)
from util import CHARACTERS_DIR, EDIT_DIR, GENERATED_DIR, PRODUCTION, gemini_key, load_json, log, save_json

PAINTER = "gemini-3.1-flash-image"  # Nano Banana 2; дешевле — gemini-3.1-flash-lite-image (--model)
ANALYST = "gemini-flash-latest"     # анализ референса и проверка правдоподобия
ANALYSTS = (ANALYST, "gemini-2.5-flash", "gemini-flash-lite-latest")  # основная перегружена (503) — следующая
SIZE = (1280, 720)                  # как у OpenAI Gen / ReGen
TIMEOUT = 120                       # картинка; анализ и проверка — ANALYST_TIMEOUT
ANALYST_TIMEOUT = 45
RETRY_WAIT = (10, 30)               # паузы перед повторами при 429 / 5xx / таймауте
# $ за 1 млн токенов (ai.google.dev/gemini-api/docs/pricing, 2026-10): картинка на выходе и текст
PRICE = {"gemini-3.1-flash-image": {"in": 0.50, "out_image": 60.0, "out_text": 3.0},
         "gemini-3.1-flash-lite-image": {"in": 0.25, "out_image": 30.0, "out_text": 1.5},
         "gemini-3-pro-image": {"in": 2.0, "out_image": 120.0, "out_text": 12.0},
         ANALYST: {"in": 0.30, "out_text": 2.50}, "gemini-2.5-flash": {"in": 0.30, "out_text": 2.50},
         "gemini-flash-lite-latest": {"in": 0.10, "out_text": 0.40}}
API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class Refused(RuntimeError):
    """Gemini отказался рисовать (безопасность / нет картинки в ответе)."""


def _key() -> str:
    k = gemini_key()
    if not k:
        raise SystemExit("Нет ключа gemini в keys.json")
    return k


def _call(model: str, parts: list[dict], key: str, config: dict, timeout: int = TIMEOUT) -> dict:
    """Запрос к Gemini с повторами при перегрузке. → весь ответ."""
    body = json.dumps({"contents": [{"parts": parts}], "generationConfig": config}).encode()
    for attempt in range(len(RETRY_WAIT) + 1):
        req = urllib.request.Request(API.format(model=model), data=body, method="POST",
                                     headers={"Content-Type": "application/json", "x-goog-api-key": key})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            msg = e.read().decode(errors="ignore")
            if "limit: 0" in msg:  # бесплатный уровень: картинки недоступны вовсе — повторять бессмысленно
                raise SystemExit(f"Gemini {model}: на бесплатном уровне лимит 0 — включите оплату в Google AI Studio") from e
            if e.code in (429, 500, 502, 503, 504) and attempt < len(RETRY_WAIT):
                log(f"    · {model}: HTTP {e.code}, повтор через {RETRY_WAIT[attempt]} с")
                time.sleep(RETRY_WAIT[attempt])
                continue
            raise RuntimeError(f"{model}: HTTP {e.code}: {msg[:300]}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < len(RETRY_WAIT):
                log(f"    · {model}: нет ответа ({e!r}"[:90] + f"), повтор через {RETRY_WAIT[attempt]} с")
                time.sleep(RETRY_WAIT[attempt])
                continue
            raise RuntimeError(f"{model}: нет ответа: {e!r}") from e
    raise RuntimeError(f"{model}: нет ответа")


def _usage_cost(model: str, res: dict) -> float:
    u, p = res.get("usageMetadata") or {}, PRICE.get(model, {})
    out_img = sum(d.get("tokenCount", 0) for d in u.get("candidatesTokensDetails") or [] if d.get("modality") == "IMAGE")
    out_all = u.get("candidatesTokenCount", 0) + u.get("thoughtsTokenCount", 0)
    return (u.get("promptTokenCount", 0) * p.get("in", 0) + out_img * p.get("out_image", 0)
            + (out_all - out_img) * p.get("out_text", 0)) / 1e6


def _img_part(data: bytes, mime: str) -> dict:
    return {"inline_data": {"mime_type": mime, "data": base64.b64encode(data).decode()}}


def _mime(path: Path) -> str:
    return {".png": "image/png", ".webp": "image/webp"}.get(path.suffix.lower(), "image/jpeg")


def _ask(image: bytes, mime: str, text: str, key: str) -> tuple[dict, float]:
    """ANALYSTS по очереди: картинка + задание → JSON-ответ. → (ответ, $)."""
    err = None
    for model in ANALYSTS:
        try:
            res = _call(model, [{"text": text}, _img_part(image, mime)], key,
                        {"responseMimeType": "application/json", "temperature": 0.4}, ANALYST_TIMEOUT)
        except RuntimeError as e:  # перегружена и после повторов — пробуем следующую модель
            err = e
            log(f"    · {model} недоступна — пробую следующую")
            continue
        raw = "".join(p.get("text", "") for p in res["candidates"][0]["content"].get("parts", []))
        m = re.search(r"\{.*\}", raw, re.S)
        return (json.loads(m.group(0)) if m else {}), _usage_cost(model, res)
    raise err


def _paint(model: str, prompt: str, key: str, ref: Path | None = None) -> tuple[bytes, float]:
    """PAINTER: промт (+ референс для ReGen) → PNG 1280×720. → (байты, $)."""
    parts = ([_img_part(ref.read_bytes(), _mime(ref))] if ref else []) + [{"text": prompt}]
    res = _call(model, parts, key, {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": "16:9", "imageSize": "1K"}})
    cand = (res.get("candidates") or [{}])[0]
    imgs = [p.get("inlineData") or p.get("inline_data") for p in (cand.get("content") or {}).get("parts", [])
            if p.get("inlineData") or p.get("inline_data")]
    if not imgs:
        why = cand.get("finishReason") or (res.get("promptFeedback") or {}).get("blockReason") or "нет картинки в ответе"
        raise Refused(str(why))
    from PIL import Image, ImageOps
    im = ImageOps.fit(Image.open(io.BytesIO(base64.b64decode(imgs[0]["data"]))).convert("RGB"), SIZE, Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue(), _usage_cost(model, res)


def _best_of(model: str, prompt: str, shot: dict, key: str, ref: Path | None) -> tuple[bytes, float, list, float, float]:
    """Картинка → проверка правдоподобия; ниже PASS_SCORE — одна перегенерация по исправленному промту.
    → (лучшая картинка, её оценка, попытки, $ картинок, $ проверок)."""
    best, attempts, c_img, c_an = None, [], 0.0, 0.0
    for attempt in range(MAX_RETRIES + 1):
        img, c = _paint(model, prompt, key, ref)
        c_img += c
        check, c = _ask(img, "image/png", CHECK_PROMPT.format(task=_task_text(shot), prompt=prompt), key)
        c_an += c
        score = float(check.get("score", 0) or 0)
        attempts.append({"prompt": prompt, "score": score, "issues": check.get("issues", [])})
        log(f"    попытка {attempt + 1}: правдоподобие {score:g}/10"
            + (f" — {'; '.join(check.get('issues', []))[:160]}" if check.get("issues") else ""))
        if best is None or score > best[1]:
            best = (img, score)
        if score >= PASS_SCORE or not check.get("prompt"):
            break
        prompt = check["prompt"]
    return best[0], best[1], attempts, c_img, c_an


def run(mode: str, ep: Path, shots_filter: set[int] | None = None, force: bool = False, dry: bool = False,
        model: str = PAINTER) -> None:
    montage = ep / EDIT_DIR
    shots_path = montage / "output" / f"{ep.name}-shots.json"
    shots = load_json(shots_path)
    if not shots:
        raise SystemExit(f"Нет {shots_path}")
    refs_dir, out_dir = montage / "refs", ep / GENERATED_DIR
    cast = load_json(ep / CHARACTERS_DIR / "cast.json", {}) or {}
    journal_path = montage / "work" / "regen.json"
    journal = load_json(journal_path, []) or []
    key = None if dry and mode == "gen" else _key()
    spent, n_img = 0.0, 0
    log(f"▶ {'ImageGenerator' if mode == 'gen' else 'ImageReGen'} через Gemini {ep.name}: {model}, {SIZE[0]}x{SIZE[1]}"
        f"{' — ТОЛЬКО ' + ('ПРОМТЫ' if mode == 'gen' else 'АНАЛИЗ') + ' (--dry)' if dry else ''}")
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
        if (mode == "gen" and (refs or not shot.get("generate"))) or (mode == "regen" and not refs):
            continue  # gen — только шоты без референса; regen — только с референсом (как у OpenAI-версий)
        who = _blocked_person(shot, cast)
        if who:
            log(f"  шот {no}: пропуск — {who} (face_policy archive_only, только архив)")
            continue
        jobs = [(None, out_dir / f"{no}-g.{FORMAT}")] if mode == "gen" else \
               [(ref, out_dir / f"{no}-{k}-rg.{FORMAT}") for k, ref in enumerate(refs, 1)]
        for ref, out in jobs:
            if out.exists() and not force and not dry:
                log(f"  шот {no}: {out.name} уже есть — пропуск (--force — перезаписать)")
                continue
            entry = {"date": datetime.now().isoformat(timespec="seconds"), "tool": f"{mode}-gemini", "shot": no,
                     "out": out.name, "size": f"{SIZE[0]}x{SIZE[1]}", "model": model}
            c_an = c_img = 0.0
            t0 = time.time()
            try:
                if ref is None:
                    gen = shot["generate"].strip().rstrip(".")
                    prompt = f"{gen}. {_suffix(gen, shot.get('epoch', ''))} {NO_BRANDS}"
                    log(f"  шот {no}: {prompt[:200]}")
                else:
                    entry["ref"] = ref.name
                    analysis, c_an = _ask(ref.read_bytes(), _mime(ref), ANALYST_PROMPT.format(task=_task_text(shot)), key)
                    prompt = analysis.get("prompt", "")
                    entry["analysis"] = analysis
                    log(f"  шот {no} · {ref.name}: {analysis.get('shows', '')[:90]}")
                    log(f"    промт: {prompt[:220]}")
                entry["prompt"] = prompt
                if dry:
                    entry["status"] = "dry"
                else:
                    img, score, attempts, c_img, c = _best_of(model, prompt, shot, key, ref)
                    c_an += c
                    n_img += len(attempts)
                    out_dir.mkdir(parents=True, exist_ok=True)
                    out.write_bytes(img)
                    entry.update({"status": "ok" if score >= PASS_SCORE else "low_score", "score": score,
                                  "attempts": attempts, "seconds": round(time.time() - t0)})
                    log(f"    {'✓' if score >= PASS_SCORE else '~'} {out.name} — правдоподобие {score:g}/10, "
                        f"${c_an + c_img:.3f}, {entry['seconds']} с")
            except Refused as e:
                entry.update({"status": "refused", "error": str(e)})
                log(f"    ! шот {no}: Gemini отказался рисовать ({e}) — переписать задание нейтральнее")
            except Exception as e:  # noqa: BLE001
                entry.update({"status": "error", "error": repr(e)[:400]})
                log(f"    ! шот {no}: {e!r}"[:200])
            entry.update({"cost_analysis": round(c_an, 5), "cost_image": round(c_img, 5)})
            spent += c_an + c_img
            if not (dry and mode == "gen"):
                journal.append(entry)
                save_json(journal_path, journal)
    total = sum(x.get("cost_analysis", 0) + x.get("cost_image", 0) for x in journal)
    log(f"✔ Готово: картинок {model} {n_img} — ${spent:.2f} (за всё время по {ep.name}, все инструменты: ${total:.2f}). "
        f"Журнал: {journal_path}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Gen / ReGen через Gemini (запасной путь, когда OpenAI сбоит)")
    ap.add_argument("mode", choices=["gen", "regen"])
    ap.add_argument("episode", help="ep-13")
    ap.add_argument("--shots", help="номера шотов через запятую: 32,37")
    ap.add_argument("--force", action="store_true", help="перезаписать готовые файлы")
    ap.add_argument("--dry", action="store_true", help="gen — только промты; regen — только анализ и промт")
    ap.add_argument("--model", default=PAINTER, choices=sorted(m for m in PRICE if m != ANALYST))
    a = ap.parse_args()
    ep = PRODUCTION / a.episode
    if not ep.is_dir():
        raise SystemExit(f"Нет папки эпизода {ep}")
    shots = {int(x) for x in a.shots.split(",") if x.strip()} if a.shots else None
    run(a.mode, ep, shots, a.force, a.dry, a.model)


if __name__ == "__main__":
    sys.exit(main())
