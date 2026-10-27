"""Образцы для ReGen по шотам-пробелам — сам (с EP-10; на EP-09 Nurlan искал 34 шота руками).

Идёт по 06_montage/output/ep-N-shots.json (или --file): шоты без образца в 06_montage/refs, кроме kind «видео».
Кандидаты (права не важны — образец идёт только в ReGen, s_ в монтаж не попадает):
  1) Википедия (en): 3 статьи по запросу шота → главное фото статьи + её картинки, у которых в имени файла
     есть слова запроса (так находятся шапки газет, постеры фильмов, обложки книг, здания редакций);
  2) Commons: поиск по запросу шота.
gpt-4.1-mini сравнивает кандидата с заданием шота (expected + query + текст диктора): подходит ли по смыслу
и эпохе, нет ли водяного знака, не мелкий ли. Лучший ≥ PASS → refs/s_<шот>_1.<ext> (+ запись в work/refs.json),
лист кандидатов → work/shot_refs.jpg (Claude смотрит глазами), журнал → work/shot_refs.json. Потом — ve.py regen.

  .venv/Scripts/python.exe tools/ve.py shotrefs ep-10 [--shots 2,51] [--dry]
"""
from __future__ import annotations

import re
import time
import urllib.parse
from pathlib import Path

from image_regenerator import ANALYST, _ask, _cost, _key, is_video
from person_refs import UA, _commons_file, _commons_search, _get, _sheet  # noqa: F401  (UA — общий User-Agent)
from util import EDIT_DIR, load_json, log, save_json

PASS = 6
MAX_CANDS = 6
STOP = {"the", "of", "and", "a", "in", "on", "at", "for", "to", "with", "photo", "photograph", "image", "front", "page"}
# общие слова, которые сбивают поиск статьи (EP-09: «… Richard Harris poster» → статья о Ричарде Аттенборо)
GENERIC = {"poster", "cover", "book", "front", "page", "photograph", "photo", "building", "street", "exterior", "interior",
           "stack", "delivery", "printing", "office", "newsroom", "text", "report", "brochure", "campaign", "election",
           "meeting", "conference", "table", "night", "aerial", "portrait", "close", "view", "archive", "footage", "old"}


MONTHS = {"january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"}


def _core(q: str) -> str:
    """«Golden Rendezvous 1977 Richard Harris poster» → «Golden Rendezvous Richard Harris»; без годов, месяцев и общих слов."""
    words = [w for w in re.findall(r"[A-Za-z0-9'’]+", q)
             if w.lower() not in GENERIC | MONTHS and not re.fullmatch(r"\d+s?", w)]
    return " ".join(words[:6])


SKIP_FILE = re.compile(r"(icon|logo|flag_of|symbol|map|locator|commons-logo|wiki|edit|question_book|padlock|\.svg$)", re.I)

CHECK = """You evaluate a REFERENCE image for one shot of a history documentary (it will be redrawn by an image model,
so licence does not matter — only whether it shows the right thing).
Shot task: {expected}
Search query: {query}
Narration over the shot: "{text}"
Era of the shot: {epoch}
Source: "{caption}"
Return JSON: {{"shows": "1 sentence", "matches_task": true/false, "era_ok": true/false,
"watermark_or_stock_overlay": true/false, "too_small_or_junk": true/false,
"score": 0-10 (how good a STARTING POINT for redrawing this shot: the same kind of object, place, publication or scene is
enough — an exact match is not required, the image model will change details; small size is fine), "note": "1 short sentence"}}"""


def _words(q: str) -> list[str]:
    return [w for w in re.findall(r"[a-z]{3,}", q.lower()) if w not in STOP and not w.isdigit()]


def _wiki_images(query: str) -> list[tuple[str, str]]:
    """Википедия: статьи по запросу → (url 1280 px, «Wikipedia: статья — файл»)."""
    api = "https://en.wikipedia.org/w/api.php?format=json&action=query"
    try:
        hits = _get(f"{api}&list=search&srlimit=3&srsearch={urllib.parse.quote(query)}")["query"]["search"]
    except Exception:  # noqa: BLE001
        return []
    words = set(_words(query))
    out: list[tuple[str, str]] = []
    for h in hits:
        title = h["title"]
        if not words & set(re.findall(r"[a-z]{3,}", title.lower())):
            continue  # статья не про то (EP-09: «Letter box», «Jacob Zuma» по запросу о Rand Daily Mail)
        try:
            pg = next(iter(_get(f"{api}&prop=pageimages|images&piprop=name&imlimit=40&titles={urllib.parse.quote(title)}")
                           ["query"]["pages"].values()))
        except Exception:  # noqa: BLE001
            continue
        lead = pg.get("pageimage")
        files = ([f"File:{lead}"] if lead else []) + [i["title"] for i in pg.get("images", [])]
        picked = []
        for f in files:
            name = f.split(":", 1)[-1]
            if SKIP_FILE.search(name) or f in picked:
                continue
            fw = set(re.findall(r"[a-z]{3,}", name.lower()))
            if (lead and name == lead) or len(words & fw) >= 2 or (len(words) <= 2 and words & fw):
                picked.append(f)
        for f in picked[:3]:
            try:
                ii = next(iter(_get(f"{api}&prop=imageinfo&iiprop=url&iiurlwidth=1280&titles={urllib.parse.quote(f)}")
                               ["query"]["pages"].values()))["imageinfo"][0]
            except Exception:  # noqa: BLE001
                continue
            out.append(((ii.get("thumburl") or ii["url"]).split("?")[0], f"Wikipedia: {title} — {f.split(':', 1)[-1]}"))
            time.sleep(0.5)
    return out


def run(ep: Path, shots_filter: set[int] | None = None, dry: bool = False, file: str | None = None) -> None:
    montage = ep / EDIT_DIR
    refs_dir, work = montage / "refs", montage / "work"
    shots = load_json(Path(file) if file else montage / "output" / f"{ep.name}-shots.json", []) or []
    if isinstance(shots, dict):  # to-find-manually.json: {"README": …, "shots": […]}
        shots = shots.get("shots", [])
    key = _key()
    journal = load_json(work / "shot_refs.json", {}) or {}
    refs_log = load_json(work / "refs.json", {}) or {}
    spent, sheet, got, miss = 0.0, [], [], []
    log(f"▶ Образцы для шотов {ep.name}: Википедия + Commons{' — без записи (--dry)' if dry else ''}")
    for s in shots:
        no = s.get("shot_no")
        if no is None or (shots_filter and no not in shots_filter) or is_video(s):
            continue
        if not shots_filter and refs_dir.exists() and any(refs_dir.glob(f"s_{no}_*")):
            continue
        query = (s.get("query") or s.get("query_google") or "").strip()
        expected = s.get("expected") or s.get("what_to_find") or ""
        if not query:
            continue
        core = _core(query)
        short = " ".join(core.split()[:3])  # только название: «Rand Daily Mail», «The Citizen newspaper» (EP-09)
        found = _wiki_images(core) + (_wiki_images(query) if core.lower() != query.lower() else [])
        if short.lower() != core.lower():
            found += _wiki_images(short)
        files = _commons_search(core, 4) + [f for f in _commons_search(query, 3)]
        for f in dict.fromkeys(files):
            if len(found) >= MAX_CANDS + 2:
                break
            r = _commons_file(f)
            if r:
                found.append(r)
            time.sleep(0.5)
        cands, seen = [], set()
        for url, cap in found:
            if url in seen or len(cands) >= MAX_CANDS:
                continue
            seen.add(url)
            try:
                img = _get(url, raw=True)
                time.sleep(2.0)  # правила Wikimedia
            except Exception as e:  # noqa: BLE001
                log(f"  шот {no}: не скачалось ({str(e)[:60]})")
                continue
            ext = Path(urllib.parse.urlparse(url).path).suffix.lower() or ".jpg"
            mime = "image/png" if ext == ".png" else "image/webp" if ext == ".webp" else "image/jpeg"
            try:
                v, u = _ask(img, mime, CHECK.format(expected=expected, query=query, text=s.get("scenario_text", "")[:300],
                                                    epoch=s.get("epoch", ""), caption=cap), key)
                spent += _cost(ANALYST, u)
            except Exception as e:  # noqa: BLE001
                log(f"  шот {no}: проверка не прошла ({str(e)[:60]})")
                continue
            score = float(v.get("score", 0) or 0)
            if v.get("watermark_or_stock_overlay"):
                score = min(score, 4)  # ReGen не чистит чужие водяные знаки (CLAUDE.md, ImageReGen)
            cands.append({"url": url, "caption": cap, "score": score, "check": v, "ext": ext, "bytes": img})
        cands.sort(key=lambda c: -c["score"])
        best = cands[0] if cands and cands[0]["score"] >= PASS else None
        (got if best else miss).append(no)
        log(f"  шот {no} «{query[:50]}»: кандидатов {len(cands)}" +
            (f", лучший {best['score']:g}/10 — {best['caption'][:80]} · {best['check'].get('shows', '')[:70]}" if best else " — годного нет"))
        journal[str(no)] = {"query": query, "candidates": [{k: c[k] for k in ("url", "caption", "score", "check")} for c in cands],
                            "chosen": best["url"] if best else None}
        if best:  # на листе — только выбранный образец, крупно: Claude проверяет глазами до ReGen
            sheet.append((f"шот {no} · {best['score']:g}/10 · {best['caption'][:30]}", best["bytes"]))
        if best and not dry:
            refs_dir.mkdir(parents=True, exist_ok=True)
            name = f"s_{no}_1{best['ext']}"
            (refs_dir / name).write_bytes(best["bytes"])
            refs_log[f"shotrefs-{no}"] = {"shot": no, "query": query, "files": [{"file": name, "url": best["url"], "title": best["caption"]}]}
    save_json(work / "shot_refs.json", journal)
    if not dry:
        save_json(work / "refs.json", refs_log)
    if sheet:
        _sheet(sheet, work / "shot_refs.jpg")
    log(f"✔ Готово: образцов {len(got)}, без образца {len(miss)}{(' (' + ', '.join(map(str, miss)) + ')') if miss else ''} — "
        f"${spent:.3f}. Лист: {work / 'shot_refs.jpg'}")
