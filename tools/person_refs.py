"""Референсы людей для ReGravure — сам, по реестру 02_characters/cast.json (с EP-10; на EP-09 Nurlan искал руками).

Для каждого человека из реестра (кроме типажей face_policy allowed / silhouette и тех, у кого уже есть
свой кадр <id>_NN или референс refs/s_<id>_N) собирает кандидатов:
  1) главное фото статьи Википедии (en, затем af) по имени;
  2) файлы Commons, названные в archive.where реестра (Senator_dick_clark.jpg, PW_Botha_1962.jpg …);
  3) поиск Commons по «имя + год события»;
  4) годного среди них нет — поиск по интернету (с EP-13): DuckDuckGo (заголовки страниц) + Tavily (1 кредит).
     Подписи Tavily сочинены по запросу — проверке даём сайт и имя файла из ссылки, а не их (урок 2026-10-27).
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
{{"one_clear_face": true/false, "people_count": n,
"is_document_or_page": true/false (newspaper page, document, collage, poster, book cover, painting — not a photo of the person), "photo_era": "e.g. 1970s / 2010s", "apparent_age": n,
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


WEB_DDG = 6  # сколько лучших картинок DuckDuckGo смотреть на человека
BROWSER_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/140.0 Safari/537.36"}


def _role_words(role: str) -> str:
    """«former Noriega adviser and Panama's consul general…; Senate witness» → первые слова роли до запятой / «;»."""
    return " ".join(re.split(r"[,;(]", role or "")[0].split()[:6])


def _file_words(url: str) -> str:
    """Имя файла из ссылки — часто честнее подписи: …/jose-blandon-castillo.jpg → «jose blandon castillo»."""
    stem = Path(urllib.parse.unquote(urllib.parse.urlparse(url).path)).stem
    return re.sub(r"[-_+.]+", " ", stem)[:80]


def _web_candidates(name: str, person: dict) -> list[tuple[str, str]]:
    """Портреты из интернета: DuckDuckGo + Tavily → [(url, подпись для проверки)]."""
    import sources
    q = f"{name} {_role_words(person.get('role', ''))}".strip()
    out: list[tuple[str, str]] = []
    for src, n in (("ddg", WEB_DDG), ("tavily", 5)):
        try:
            got = sources.get(src).search(q, "image", n)[:n]
        except Exception as e:  # noqa: BLE001
            log(f"    {src}: {str(e)[:80]}")
            continue
        for c in got:
            site = urllib.parse.urlparse(c["url"]).netloc
            if src == "ddg":
                cap = f"web page «{c.get('title', '')[:140]}» (site {c.get('author') or site}); file name: {_file_words(c['url'])}"
            else:  # подпись Tavily повторяет запрос — не подпись источника
                cap = (f"web search result for «{q}» (site {site}); file name: {_file_words(c['url'])}. "
                       f"No real caption: the search engine only guessed")
            out.append((c["url"], f"[{src}] {cap}", c.get("thumb")))
    return out


def _download(url: str, web: bool) -> bytes:
    """Wikimedia — со своим UA и паузой 2 с (правила); интернет — как браузер, без пауз, до 15 МБ."""
    if not web:
        data = _get(url.split("?")[0], raw=True)
        time.sleep(2.0)  # не чаще одного файла в 2 с — правила Wikimedia
        return data
    import ssl
    import certifi  # корневые сертификаты свежее, чем у Windows-Python (army.mil не открывался, 2026-10-27)
    ctx = ssl.create_default_context(cafile=certifi.where())
    with urllib.request.urlopen(urllib.request.Request(url, headers=BROWSER_UA), timeout=30, context=ctx) as r:
        data = r.read(15 * 1024 * 1024 + 1)
    if len(data) > 15 * 1024 * 1024:
        raise RuntimeError("файл больше 15 МБ")
    return data


def _as_jpeg(data: bytes) -> bytes:
    """Сайты отдают WebP / AVIF под видом .jpg — проверка такое не принимает (HTTP 400): всё в JPEG.
    Не картинка (страница входа Facebook и т. п.) — исключение."""
    import io
    from PIL import Image
    try:
        im = Image.open(io.BytesIO(data)).convert("RGB")
    except Exception as e:  # noqa: BLE001
        raise RuntimeError("не картинка") from e
    im.thumbnail((2000, 2000))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=92)
    return buf.getvalue()


def _check_all(found: list[tuple], seen: set, cands: list[dict], p: dict, year: str, key: str) -> float:
    """Скачать и проверить кандидатов (gpt-4.1-mini) → в cands. → потрачено $."""
    spent, pid, name = 0.0, p.get("id"), p.get("name", "")
    for item in found:
        url, cap = item[0], item[1]
        if url in seen:
            continue
        seen.add(url)
        web = cap.startswith("[ddg]") or cap.startswith("[tavily]")
        img = None
        # не отдал файл (403, платный доступ) или отдал страницу вместо картинки (Facebook) — берём превью
        for u in [url] + ([item[2]] if len(item) > 2 and item[2] else []):
            try:
                img = _download(u, web)
                if web:
                    img = _as_jpeg(img)
                break
            except Exception as e:  # noqa: BLE001
                img = None
                log(f"  {pid}: не взялось {u[-60:]} ({str(e)[:60]})")
        if not img:
            continue
        if web:
            ext = ".jpg"
        else:
            ext = Path(urllib.parse.urlparse(url).path).suffix.lower()
            ext = ext if ext in (".jpg", ".jpeg", ".png", ".webp") else ".jpg"
        mime = "image/png" if ext == ".png" else "image/webp" if ext == ".webp" else "image/jpeg"
        try:
            v, u = _ask(img, mime, CHECK.format(name=name, role=p.get("role", ""), year=year or "?",
                                                born=p.get("years", "?"), caption=cap), key)
            spent += _cost(ANALYST, u)
        except Exception as e:  # noqa: BLE001
            log(f"  {pid}: проверка не прошла ({e})")
            continue
        score = float(v.get("score", 0) or 0)
        if v.get("caption_matches") is False and cap.startswith("[tavily]") and v.get("one_clear_face"):
            score = min(score, 6)  # у Tavily подписи нет — решают сайт, имя файла и лист глазами
        elif v.get("watermark_or_logo") and web:
            score = min(score, 7)  # водяной знак на образце не страшен: гравюру рисуют заново
        elif v.get("watermark_or_logo") or not v.get("one_clear_face") or v.get("caption_matches") is False:
            score = min(score, 4)
        if v.get("is_document_or_page"):
            score = min(score, 4)  # газетная полоса с крошечным лицом — не портрет (тест 2026-10-27: Blandón)
        if int(v.get("people_count") or 1) > 1:
            score = min(score, 5)  # групповое фото — только если одиночного нет (EP-09: Ginsburg с Carter)
        if v.get("age_fits") is False:
            score = min(score, 5)
        cands.append({"url": url, "caption": cap, "score": score, "check": v, "ext": ext, "bytes": img})
        time.sleep(1.0 if not web else 0.2)
    return spent


def _year(person: dict, cast: dict) -> str:
    """Год события: по era эпизода (первое число) и возрасту человека, если известен."""
    born = re.search(r"\d{4}", person.get("years", "") or "")
    age = re.search(r"\d+", str(person.get("age_at_event") or ""))  # бывает строкой: «21 (1969) · 36 (IPO 1984)»
    if born and age:
        return str(int(born.group()) + int(age.group()))
    # без года рождения — год из роли / одежды («trial witness… 1991–92», «suit, 1991–1992»), а не начало эпохи
    # эпизода (ep-12: Bilonick получил 1967 и «не тот возраст» у всех кандидатов)
    m = re.search(r"\b(?:19|20)\d{2}\b", f"{person.get('role', '')} {person.get('wardrobe', '')}")
    if m:
        return m.group()
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
    log(f"▶ Референсы людей {ep.name}: Википедия + Commons по cast.json, нет — DuckDuckGo + Tavily{' — без записи (--dry)' if dry else ''}")
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
        spent += _check_all(found, seen, cands, p, year, key)
        if not cands or max(c["score"] for c in cands) < PASS:  # Википедия и Commons не дали — ищем в интернете
            web = _web_candidates(names[0], p)
            log(f"  {pid}: в Википедии и Commons годного нет — интернет: {len(web)} кандидатов (DuckDuckGo + Tavily)")
            spent += _check_all(web, seen, cands, p, year, key)
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
