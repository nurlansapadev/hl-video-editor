"""Референсы людей для ReGravure — сам, по реестру 02_characters/cast.json (с EP-10; на EP-09 Nurlan искал руками).

Для каждого человека из реестра (кроме типажей face_policy allowed / silhouette и тех, у кого уже есть
свой кадр <id>_NN или референс refs/s_<id>_N) собирает кандидатов:
  1) главное фото статьи Википедии (en, затем af) по имени;
  2) файлы Commons, названные в archive.where реестра (Senator_dick_clark.jpg, PW_Botha_1962.jpg …);
  3) поиск Commons по «имя + год события».
Права у референса не важны: он идёт только в ReGravure (s_ — в монтаж не попадает).
gpt-4.1-mini смотрит каждого кандидата: одно ясное лицо, примерный год снимка и возраст против года события,
водяные знаки / логотипы. Кто на фото — по подписи источника (заголовок статьи / описание файла Commons),
лица модель не опознаёт. Лучший → 02_characters/refs/s_<id>_1.<ext>, остальные → refs/cand/<id>_N.<ext>.
Лист кандидатов → 06_montage/work/person_refs.jpg (Claude смотрит глазами), журнал → work/person_refs.json.

  .venv/Scripts/python.exe tools/ve.py refs ep-10 [--ids john_mcgoff] [--dry]
  --dry — только найти и оценить кандидатов (в refs ничего не кладёт).
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from image_regenerator import ANALYST, _ask, _cost, _key
from util import CHARACTERS_DIR, EDIT_DIR, load_json, log, save_json

UA = {"User-Agent": "HonestLiesVideoEditor/2.0 (YouTube documentary channel; contact via Wikimedia talk) python-urllib"}
IMG_RE = r"[\w\-.,%()'À-ÿ]+?\.(?:jpe?g|png|webp|tiff?)"
SKIP_POLICY = ("allowed", "silhouette")
PASS = 6  # ≥ 6 из 10 — годится в референс
MAX_CANDS = 8  # больше кандидатов на человека не смотрим (расход и паузы Wikimedia)

CHECK = """This image is a candidate REFERENCE PORTRAIT of {name} ({role}) for an engraving illustration.
The story moment is around {year}; the person was born {born}.
Source caption: "{caption}"
Judge only what is visible — do not try to recognize the face. Return JSON:
{{"one_clear_face": true/false, "people_count": n, "photo_era": "e.g. 1970s / 2010s", "apparent_age": n,
"age_fits": true/false (apparent age plausible for the story year), "watermark_or_logo": true/false,
"caption_matches": true/false (caption names this person), "score": 0-10 (usefulness as a reference portrait of this person
at that time: clear single face, right era/age, caption names him/her), "note": "1 short sentence"}}"""


def _get(url: str, raw: bool = False, tries: int = 3):
    for a in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                data = r.read()
            return data if raw else json.loads(data)
        except urllib.error.HTTPError as e:
            if e.code == 429 and a < tries - 1:
                wait = e.headers.get("Retry-After") if e.headers else None
                time.sleep(int(wait) if wait and wait.isdigit() else 15 * (a + 1))  # Wikimedia просит паузу
                continue
            raise
    return None


def _clean_name(name: str) -> list[str]:
    """«Connie (Cornelius) Mulder» → ['Connie Mulder', 'Cornelius Mulder']; «B. J. (John) Vorster» → ['John Vorster', 'B. J. Vorster']."""
    out = [re.sub(r"\s*\([^)]*\)", "", name).strip()]
    m = re.search(r"\(([^)]+)\)", name)
    if m:
        last = out[0].split()[-1]
        out.insert(0, f"{m.group(1)} {last}")
    return list(dict.fromkeys(x for x in out if x))


def _wiki_lead(title: str) -> tuple[str, str] | None:
    """Главное фото статьи (en, затем af): → (url, заголовок статьи)."""
    for lang in ("en", "af"):
        q = (f"https://{lang}.wikipedia.org/w/api.php?action=query&format=json&redirects=1&prop=pageimages&piprop=original"
             f"&titles={urllib.parse.quote(title)}")
        try:
            pg = next(iter(_get(q)["query"]["pages"].values()))
        except Exception:  # noqa: BLE001
            continue
        src = (pg.get("original") or {}).get("source")
        if src and "missing" not in pg:
            return src.split("?")[0], f"Wikipedia ({lang}): {pg.get('title')}"
    return None


def _commons_file(fname: str) -> tuple[str, str] | None:
    """Файл Commons по имени → (url 1280 px — стандартный размер миниатюр Wikimedia, иначе 429; описание файла)."""
    q = ("https://commons.wikimedia.org/w/api.php?action=query&format=json&prop=imageinfo&iiprop=url|extmetadata&iiurlwidth=1280"
         f"&titles={urllib.parse.quote('File:' + fname)}")
    try:
        pg = next(iter(_get(q)["query"]["pages"].values()))
        ii = pg["imageinfo"][0]
    except Exception:  # noqa: BLE001
        return None
    desc = re.sub(r"<[^>]+>", "", (ii.get("extmetadata", {}).get("ImageDescription") or {}).get("value", ""))[:200]
    return ii.get("thumburl") or ii["url"], f"Commons: {fname} — {desc}"


def _commons_search(text: str, n: int = 3) -> list[str]:
    q = ("https://commons.wikimedia.org/w/api.php?action=query&format=json&list=search&srnamespace=6"
         f"&srlimit={n}&srsearch={urllib.parse.quote(text + ' filetype:bitmap')}")
    try:
        return [x["title"][5:] for x in _get(q).get("query", {}).get("search", [])]
    except Exception:  # noqa: BLE001
        return []


def _year(person: dict, cast: dict) -> str:
    """Год события: по era эпизода (первое число) и возрасту человека, если известен."""
    born = re.search(r"\d{4}", person.get("years", "") or "")
    age = re.search(r"\d+", str(person.get("age_at_event") or ""))  # бывает строкой: «21 (1969) · 36 (IPO 1984)»
    if born and age:
        return str(int(born.group()) + int(age.group()))
    m = re.search(r"\d{4}", cast.get("era", "") or "")
    return m.group() if m else ""


def run(ep: Path, ids_filter: set[str] | None = None, dry: bool = False) -> None:
    chars = ep / CHARACTERS_DIR
    refs_dir, cand_dir = chars / "refs", chars / "refs" / "cand"
    work = ep / EDIT_DIR / "work"
    cast = load_json(chars / "cast.json", {}) or {}
    key = _key()
    journal = load_json(work / "person_refs.json", {}) or {}
    spent, sheet = 0.0, []
    log(f"▶ Референсы людей {ep.name}: Википедия + Commons по cast.json{' — без записи (--dry)' if dry else ''}")
    for p in cast.get("people", []) or []:
        pid, name = p.get("id"), p.get("name", "")
        if not pid or (ids_filter and pid not in ids_filter):
            continue
        if p.get("face_policy") in SKIP_POLICY:
            continue
        has_own = [f for f in chars.glob(f"{pid}_*") if re.fullmatch(rf"{re.escape(pid)}_\d+", f.stem)]
        has_ref = [f for f in refs_dir.glob(f"s_{pid}*")] if refs_dir.exists() else []
        if (has_own or has_ref) and not ids_filter:
            continue
        year = _year(p, cast)
        names = _clean_name(name)
        found: list[tuple[str, str]] = []
        for n in names:
            r = _wiki_lead(n)
            if r:
                found.append(r)
                break
        for f in re.findall(IMG_RE, " ".join(p.get("archive", {}).get("where", []) or []), re.I):
            r = _commons_file(f.strip())
            if r:
                found.append(r)
        queries = [f"{names[0]} {year}".strip()]
        if year:
            y = int(year)
            queries += [f"{names[0]} {y - 3}", f"{names[0]} {y - 2}", f"{names[0]} {y + 2}", f"{names[0]} {y // 10 * 10}s photograph"]
        queries.append(f"{names[0]} portrait")
        files: list[str] = []
        for qtext in queries:
            files += [f for f in _commons_search(qtext, 3) if f not in files]
            time.sleep(0.5)
        for f in files:
            if len(found) >= MAX_CANDS:
                break
            if any(f.lower().replace(" ", "_") in urllib.parse.unquote(u).lower().replace(" ", "_") for u, _ in found):
                continue
            r = _commons_file(f)
            if r:
                found.append(r)
            time.sleep(0.5)
        seen, cands = set(), []
        for url, cap in found:
            if url in seen:
                continue
            seen.add(url)
            try:
                img = _get(url.split("?")[0], raw=True)
                time.sleep(2.0)  # не чаще одного файла в 2 с — правила Wikimedia
            except Exception as e:  # noqa: BLE001
                log(f"  {pid}: не скачалось {url[-60:]} ({e})")
                continue
            ext = Path(urllib.parse.urlparse(url).path).suffix.lower() or ".jpg"
            mime = "image/png" if ext == ".png" else "image/webp" if ext == ".webp" else "image/jpeg"
            try:
                v, u = _ask(img, mime, CHECK.format(name=name, role=p.get("role", ""), year=year or "?",
                                                    born=p.get("years", "?"), caption=cap), key)
                spent += _cost(ANALYST, u)
            except Exception as e:  # noqa: BLE001
                log(f"  {pid}: проверка не прошла ({e})")
                continue
            score = float(v.get("score", 0) or 0)
            if v.get("watermark_or_logo") or not v.get("one_clear_face") or v.get("caption_matches") is False:
                score = min(score, 4)
            elif int(v.get("people_count") or 1) > 1:
                score = min(score, 5)  # групповое фото — только если одиночного нет (EP-09: Ginsburg с Carter)
            if v.get("age_fits") is False:
                score = min(score, 5)
            cands.append({"url": url, "caption": cap, "score": score, "check": v, "ext": ext, "bytes": img})
            time.sleep(1.0)
        cands.sort(key=lambda c: -c["score"])
        best = cands[0] if cands and cands[0]["score"] >= PASS else None
        log(f"  {pid}: кандидатов {len(cands)}" + (f", лучший {best['score']:g}/10 — {best['caption'][:90]} · {best['check'].get('note', '')[:80]}"
                                                   if best else " — годного нет, искать вручную"))
        journal[pid] = {"year": year, "candidates": [{k: c[k] for k in ("url", "caption", "score", "check")} for c in cands],
                        "chosen": best["url"] if best else None}
        for k, c in enumerate(cands, 1):
            sheet.append((f"{pid} {c['score']:g}{' ✓' if c is best else ''}", c["bytes"]))
            if not dry:
                cand_dir.mkdir(parents=True, exist_ok=True)
                (cand_dir / f"{pid}_{k}{c['ext']}").write_bytes(c["bytes"])
        if best and not dry:
            refs_dir.mkdir(parents=True, exist_ok=True)
            (refs_dir / f"s_{pid}_1{best['ext']}").write_bytes(best["bytes"])
    save_json(work / "person_refs.json", journal)
    if sheet:
        _sheet(sheet, work / "person_refs.jpg")
    miss = [k for k, v in journal.items() if not v.get("chosen")]
    log(f"✔ Готово: ${spent:.3f}. Лист: {work / 'person_refs.jpg'}" + (f". Без референса: {', '.join(miss)}" if miss else ""))


def _sheet(items: list[tuple[str, bytes]], out: Path) -> None:
    import io
    from PIL import Image, ImageDraw
    w, h, cols = 300, 340, 6
    rows = (len(items) + cols - 1) // cols
    s = Image.new("RGB", (cols * w, rows * h), "black")
    d = ImageDraw.Draw(s)
    for i, (label, data) in enumerate(items):
        try:
            im = Image.open(io.BytesIO(data)).convert("RGB")
        except Exception:  # noqa: BLE001
            continue
        im.thumbnail((w - 6, h - 22))
        x, y = (i % cols) * w, (i // cols) * h
        s.paste(im, (x + 3, y + 20))
        d.text((x + 4, y + 3), label[:44], fill="yellow")
    out.parent.mkdir(parents=True, exist_ok=True)
    s.save(out, quality=85)
