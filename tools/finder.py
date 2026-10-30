"""Поиск фото и видео по сценарию — только с лицензиями, безопасными для монетизации.

Порядок: сначала свои кадры эпизода (05_footage), потом интернет.
Источники — tools/sources/, один файл на источник (контракт — в sources/__init__.py).
Какие источники и в каком порядке спрашивать для каждого вида материала — settings.json → "finder" → "sources",
выключить источник — "finder" → "off". После поиска — отчёт по источникам: 06_montage/work/find_report.txt.

Виды поиска: фото, видео, хроника (архивные/новостные кадры), любительское (съёмка очевидцев), газеты, фильм.
Эпоха, страна и люди эпизода — из паспорта (06_montage/context.json).

Лицензии: только общественное достояние, CC0, CC BY (с указанием автора), лицензии Pexels/Pixabay/Unsplash.
CC BY-SA — только если "finder": {"allowShareAlike": true}. NC и ND (некоммерческие, без изменений) — никогда.
"""
from __future__ import annotations

import base64
import io
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import sources
from scriptparse import WORDS_PER_MIN, find_slug
from sources import local as src_local
from sources._http import DL_DELAY, UA, SourceBlocked, _dl_cool, _dl_last, download, http_json, keys, strip_html
from sources._license import LICENSE_TEXT, NOT_FREE, norm_license
from util import load_json, log, run, save_json

IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff")
# признаки тяжёлых кадров в описаниях — отсеиваем ещё до просмотра глазами
SENSITIVE = ("corpse", "dead body", "bodies", "cadaver", "victim", "casualt", "funeral", "morgue", "blood", "injured",
             "bodycam", "body cam", "dashcam", "graphic content", "shooting suspect")
SOURCE_NAMES = {"list": "", **sources.labels()}  # имя источника → как писать в титрах (LABEL в tools/sources/<имя>.py)


def _flag(source: str, attr: str) -> bool:
    """Настройка источника из его файла (STRICT_TEXT, CHECK_NOT_FREE…); нет файла или настройки — False."""
    return bool(getattr(sources.all_sources().get(source), attr, False))


# ───────────────────────── 4. отбор и проверка глазами ─────────────────────────
def _diverse(cands: list[dict], n: int) -> list[dict]:
    """На проверку «глазами» отдаём лучших из КАЖДОГО источника по очереди — иначе один сток с удачными тегами
    (обычно Pixabay) занимает все места, а Wikimedia, Openverse, NASA и архивы даже не рассматриваются."""
    groups: dict = {}
    for c in cands:  # кандидаты уже отсортированы по оценке
        groups.setdefault(c["source"], []).append(c)
    out: list[dict] = []
    while len(out) < n and any(groups.values()):
        for src in list(groups):
            if groups[src] and len(out) < n:
                out.append(groups[src].pop(0))
    return out


def heuristic_score(c: dict, q: str) -> float:
    """Черновая оценка до просмотра: совпадение слов запроса с описанием, разрешение, пропорции, надёжность источника."""
    words = [w for w in re.findall(r"\w{3,}", q.lower())]
    text = f"{c.get('title', '')} {c.get('text', '')}".lower()
    match = sum(1 for w in words if w in text) / max(1, len(words))
    w, h = c.get("width") or 0, c.get("height") or 0
    res = 0.5 if not w else min(1.0, w / 1920)
    aspect_ok = 1.0 if not w or not h or 1.2 <= w / h <= 2.4 else (0.75 if c["type"] == "document" else 0.4)
    return (0.55 * match + 0.25 * res + 0.2 * sources.priority(c["source"])) * aspect_ok


def _cand_key(c: dict):
    """Чем кандидат отличается от других: ссылка на файл, а если её ещё нет — номер в архиве источника
    (asset_id — для новых источников; nasa_id, ident, dvids_id — старые)."""
    return c.get("url") or c.get("asset_id") or c.get("nasa_id") or c.get("ident") or c.get("dvids_id")


def acceptable(c: dict, allow_sa: bool) -> bool:
    """Отсев до просмотра: лицензия, тяжёлые/несвободные кадры по описанию, малый размер, длина видео."""
    if c.get("license") == "own":
        return True  # свои кадры эпизода
    if not _cand_key(c):
        return False
    lic = c.get("license")
    if lic not in ("pd", "cc0", "by", "pexels", "pixabay", "unsplash", "check-loc") and not (lic == "by-sa" and allow_sa):
        return False
    text = f"{c.get('title', '')} {c.get('text', '')} {c.get('author', '')}".lower()
    if any(s in text for s in SENSITIVE):
        return False
    if _flag(c["source"], "CHECK_NOT_FREE") and any(x in text for x in NOT_FREE):
        return False
    if c["type"] == "image" and c.get("width") and c["width"] < 1280:
        return False
    if c["type"] == "video" and c.get("duration") and not (3 <= float(c["duration"]) <= 90):
        return False
    return True


def acceptable_ref(c: dict) -> bool:
    """Кандидат-образец с несвободной лицензией (решение Nurlan, EP-08): в ролик не идёт, Nurlan перерисует его в ИИ.
    Лицензия не важна; тяжёлое по-прежнему отсеиваем, размер — от 600 px."""
    if c.get("license") in ("own", "pd", "cc0", "by", "pexels", "pixabay", "unsplash", "check-loc") or acceptable(c, True):
        return False  # свободные и свои идут обычным путём (свободный, но мелкий кадр — не образец)
    if not c.get("url") or c["type"] not in ("image", "document"):
        return False
    text = f"{c.get('title', '')} {c.get('text', '')} {c.get('author', '')}".lower()
    if any(s in text for s in SENSITIVE):
        return False
    return not (c.get("width") and c["width"] < 600)


def shot_numbers(script_path: Path) -> dict[str, int]:
    """slug запроса [НАЙТИ] / [КАРТИНКА] → номер шота из комментария «# shot N» в script.txt."""
    out, shot = {}, None
    if not script_path.exists():
        return out
    for ln in script_path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\s*#\s*shot\s+(\d+)", ln, re.I)
        if m:
            shot = int(m.group(1))
            continue
        m = re.match(r"\s*\[\s*(найти|поиск|find|картинка|генерация|ии|ai)\s*[:：]\s*([^\]]+)\]", ln, re.I)
        if m and shot is not None:
            q = m.group(2).split("|")[0].strip()
            out.setdefault(find_slug(q if m.group(1).lower() in _FIND_TAGS else "auto " + q), shot)  # общий запрос — по первому шоту
    return out


_LOG: Path | None = None
_blocked_told: set[str] = set()
VISION_VERSION = 5  # 5 — проверка по паспорту эпизода (эпоха, люди); находки старых версий перепроверяются


def flog(msg: str) -> None:
    """Подробный журнал поиска: 06_montage/work/find_log.txt (для разбора, почему что-то не нашлось)."""
    if _LOG:
        with open(_LOG, "a", encoding="utf-8") as f:
            f.write(time.strftime("%H:%M:%S ") + msg + "\n")


def context_brief(ctx: dict, era: str = "") -> str:
    """Паспорт эпизода (06_montage/context.json) → короткий текст для проверки глазами. era — эпоха сцены из [ЭПОХА]."""
    if not ctx:
        return ""
    people = "; ".join(f"{p.get('name')} ({p.get('role', '')}, {p.get('years', '')})" for p in ctx.get("people", [])[:12])
    lines = [f"Episode topic: {ctx.get('topic', '')}",
             f"Era of this scene: {era or ctx.get('era', '')}",
             f"Main country: {ctx.get('country', '')}; places: {', '.join(ctx.get('places', []))}",
             f"Key people: {people}" if people else "",
             f"Never show: {'; '.join(ctx.get('forbidden', []))}" if ctx.get("forbidden") else ""]
    return "\n".join(x for x in lines if x)


REF_NOTE = ("IMPORTANT: these candidates are only COMPOSITION REFERENCES — an artist will redraw the scene, the image itself "
            "is never shown. Watermarks, captions, logos, borders, low resolution and copyright do NOT matter: do not reject "
            "for them. You cannot verify a real person's identity from the face: if the image plausibly shows the described "
            "person or event, judge it on the scene. Still reject violence, blood, injured or dead people.\n")


def vision_prompt(q: str, scene: str, region: str, specific: bool, kind: str, ctx_text: str, ref: bool = False) -> str:
    """Задание для проверки глазами: документальный канал об истории США, мягкая эпоха (EP-08), строго — люди и безопасность.
    ref — проверяем образцы для ReGen (DuckDuckGo, Tavily, закрытые права): водяные знаки и подписи не мешают."""
    return (
        "You are a pragmatic photo editor for a small American history documentary channel (true stories of deception, "
        "espionage and crime; audience 50+, monetized on YouTube).\n"
        + (ctx_text + "\n" if ctx_text else "")
        + f"Search query (the SUBJECT the shot must show): {q}\nNarration for this shot (context only): {scene[:500]}\n"
        "For each numbered image, first describe in a few words what it ACTUALLY shows, then judge it.\n"
        "Accept only if the image shows the subject of the search query. Matching mood or a loose theme is NOT enough.\n"
        "ERA: prefer shots that fit the era of the scene, but be tolerant: a modern photo of an old building, landscape, "
        "machine or place is fine, and small modern details in the background are fine (a period color grade is applied later). "
        "Set era_ok=false only when something clearly modern DOMINATES the frame (smartphones, screens, modern cars in the "
        "foreground) or a politician / public figure from a different period is shown.\n"
        "PEOPLE: if the query names a person, accept only that person (or a clearly generic, unidentifiable figure for "
        "b-roll queries). A different identifiable real person is a reject.\n"
        "Scoring: 9-10 = exactly the subject; 7-8 = same kind of subject, fits narration; "
        "5-6 = close enough to illustrate the narration; 3-4 = loosely related; 0-2 = unrelated.\n"
        "Also reject: dead bodies, injured people, blood, violence, police bodycam / dashcam footage, 'graphic content' warning "
        "cards, visible watermarks, TV channel logos, stock-agency marks, mostly text/collage/meme, very low quality. "
        "Historical newspapers and documents are fine when the query asks for them.\n"
        + ("This query names a specific person, place, object or event: it should be visible (a close equivalent of a "
           "place or object is acceptable, a different identifiable person is not).\n" if specific else
           "This is a generic b-roll query describing a TYPE of scene: any clear, good-looking, era-appropriate shot of that "
           "type scores 7-9 even if details differ.\n")
        + (f"Main country of this scene: {region}. For each image also set \"place\": \"match\" if it clearly looks like "
           f"{region}, \"neutral\" if it has no location cues, or \"other\" if it clearly shows another country "
           f"(foreign-language signs, recognisable foreign landmarks). \"other\" lowers the score but is not a reject by itself.\n" if region else "")
        + ({"news": "We need ARCHIVE / NEWS-STYLE footage: real documentary shots are best; staged stock-looking shots score lower.\n",
            "amateur": "We need AMATEUR / EYEWITNESS footage: handheld or home-video look is a plus.\n"}.get(kind, ""))
        + (REF_NOTE if ref else "")
        + "Return a JSON array: [{\"i\": index, \"shows\": \"what is in the image\", \"era_ok\": true/false, "
        "\"place\": \"match|neutral|other\", \"score\": 0-10, \"reject\": true/false, \"why\": \"short reason\"}]."
    )


def _parse_verdicts(text: str) -> list:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    data = json.loads(text)
    if isinstance(data, dict):  # {"items": [...]} или {"0": {...}}
        data = next((v for v in data.values() if isinstance(v, list)), list(data.values()))
    return [v for v in data if isinstance(v, dict)]


def _openai_verdicts(prompt: str, images: list[tuple[int, str]]) -> list | None:
    """Проверка глазами через OpenAI (основной вариант: оплата pay-as-you-go, без жёстких лимитов)."""
    k = keys()
    if not k.get("openai"):
        return None
    content = [{"type": "text", "text": prompt.replace("Return a JSON array: [", "Return a JSON object {\"items\": [...]} where items is [")}]
    for i, b64 in images:
        content.append({"type": "text", "text": f"Image {i}:"})
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}", "detail": "low"}})
    body = {"model": k.get("openaiModel") or "gpt-4.1-mini", "temperature": 0.1,
            "messages": [{"role": "user", "content": content}], "response_format": {"type": "json_object"}}
    for attempt in range(3):
        try:
            req = urllib.request.Request("https://api.openai.com/v1/chat/completions", data=json.dumps(body).encode(), method="POST",
                                         headers={"Content-Type": "application/json", "Authorization": f"Bearer {k['openai']}"})
            with urllib.request.urlopen(req, timeout=120) as r:
                return _parse_verdicts(json.loads(r.read().decode())["choices"][0]["message"]["content"])
        except urllib.error.HTTPError as e:
            flog(f"vision openai HTTP {e.code}: {e.read().decode(errors='ignore')[:300]}")
            if e.code in (429, 500, 503) and attempt < 2:
                time.sleep(10)
                continue
            return None
        except Exception as e:  # noqa: BLE001
            flog(f"vision openai error: {e!r}")
            return None
    return None


def _gemini_verdicts(prompt: str, images: list[tuple[int, str]]) -> list | None:
    """Запасной вариант: Gemini (бесплатный уровень, низкие лимиты)."""
    key = keys().get("gemini")
    if not key:
        return None
    parts = [{"text": prompt}]
    for i, b64 in images:
        parts += [{"text": f"Image {i}:"}, {"inline_data": {"mime_type": "image/jpeg", "data": b64}}]
    body = {"contents": [{"parts": parts}], "generationConfig": {"responseMimeType": "application/json", "temperature": 0.1}}
    for model in ("gemini-flash-latest", "gemini-2.5-flash", "gemini-flash-lite-latest"):
        try:
            req = urllib.request.Request(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                                         data=json.dumps(body).encode(), method="POST",
                                         headers={"Content-Type": "application/json", "x-goog-api-key": key})
            with urllib.request.urlopen(req, timeout=90) as r:
                res = json.loads(r.read().decode())
            return _parse_verdicts("".join(p.get("text", "") for p in res["candidates"][0]["content"]["parts"]))
        except urllib.error.HTTPError as e:
            flog(f"vision gemini {model} HTTP {e.code}: {e.read().decode(errors='ignore')[:300]}")
        except Exception as e:  # noqa: BLE001
            flog(f"vision gemini {model} error: {e!r}")
    return None


def _thumb_b64(c: dict) -> str | None:
    """Превью кандидата → JPEG 512 px в base64 (с паузой для сайтов, которые не любят частых запросов)."""
    from PIL import Image
    th_host = urllib.parse.urlparse(c["thumb"]).netloc
    if th_host in _dl_cool:
        return None
    wait = min(1.0, DL_DELAY.get(th_host, 0)) - (time.time() - _dl_last.get(th_host, 0))
    if wait > 0:
        time.sleep(wait)
    req = urllib.request.Request(c["thumb"], headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        im = Image.open(io.BytesIO(r.read())).convert("RGB")
    _dl_last[th_host] = time.time()
    im.thumbnail((512, 512))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=80)
    return base64.b64encode(buf.getvalue()).decode()


def vision_rank(cands: list[dict], q: str, scene: str, need: int, region: str = "", specific: bool = True,
                kind: str = "image", ctx_text: str = "", ref: bool = False) -> list[dict] | None:
    """Модель смотрит превью до 12 кандидатов и ставит оценку. Возвращает одобренных по убыванию оценки;
    None — проверка недоступна (нет ключей / ошибка). ref — проверка образцов для ReGen (см. REF_NOTE)."""
    if not cands:
        return None
    images = []
    for i, c in enumerate(cands[:12]):
        try:
            b64 = _thumb_b64(c)
            if b64:
                images.append((i, b64))
        except Exception:  # noqa: BLE001
            continue
    if not images:
        return None
    prompt = vision_prompt(q, scene, region, specific, kind, ctx_text, ref=ref)
    verdicts = _openai_verdicts(prompt, images)
    if verdicts is None:
        verdicts = _gemini_verdicts(prompt, images)
    if verdicts is None:
        log("    ! проверка глазами не удалась (OpenAI и Gemini) — отбираю без неё")
        return None
    by_i = {v.get("i"): v for v in verdicts if isinstance(v, dict)}
    ranked = []
    for i, _ in images:
        v = by_i.get(i)
        if not v:
            continue
        cands[i]["vision"] = v
        place = str(v.get("place", "")).lower()
        # мягкая проверка (решение Nurlan, EP-08): другая страна и эпоха — штраф к оценке, а не отказ
        penalty = (1.0 if region and place == "other" else 0.0) + (2.0 if v.get("era_ok") is False else 0.0)
        score = float(v.get("score", 0)) - penalty
        if not v.get("reject") and score >= 5:
            cands[i]["rank"] = score + (0.6 if place == "match" else 0.0)
            ranked.append(cands[i])
    ranked.sort(key=lambda c: -c["rank"])
    return ranked


def _is_specific(q: str) -> bool:
    """«Ronald Reagan 1985» — конкретное (имя/год): строгая проверка; «pine forest» — общий план."""
    return bool(re.search(r"\b[A-ZА-ЯЁ][\w-]+", q) or re.search(r"\b(1[89]|20)\d\d\b", q))


def _broaden(q: str) -> list[str]:
    """Запасные, более широкие запросы, если по исходному мало подходящего: «city street at night» → «city street», «at night»."""
    words = q.split()
    if len(words) < 3:
        return []
    out = [" ".join(words[:2]), " ".join(words[-2:]), " ".join(w for w in words if len(w) > 3)[:60]]
    return [x for x in dict.fromkeys(out) if x and x.lower() != q.lower()]


# ───────────────────────── 5а. подготовка запросов ─────────────────────────
def parse_find_args(args: str) -> tuple[str, str, int]:
    """«Ronald Reagan 1985 | фото | 2» → ("Ronald Reagan 1985", "image", 2). Количество 0 — посчитать по длине текста сцены."""
    parts = [p.strip() for p in args.split("|") if p.strip()]
    query = parts[0] if parts else ""
    kind, count = "image", 0
    for p in parts[1:]:
        pl = p.lower()
        if pl.isdigit():
            count = max(1, min(6, int(pl)))
        elif pl.startswith(("вид", "vid")):
            kind = "video"
        elif pl.startswith(("хрон", "новост", "архивн", "news", "archive foot")):
            kind = "news"
        elif pl.startswith(("любит", "очевид", "amateur", "eyewit")):
            kind = "amateur"
        elif pl.startswith(("док", "газет", "doc", "newsp")):
            kind = "document"
        elif pl.startswith(("фильм", "кино", "film")):
            kind = "film"
        elif pl.startswith(("фот", "кар", "img", "photo", "imag")):
            kind = "image"
    return query, kind, count


# метки, которые начинают новую сцену (текст после них к поиску уже не относится)
_SEG_RE = r"\[\s*(сцена|заголовок|глава|таймлайн|список|сч[её]тчик|цитата|карта|диаграмма|финал|scene|title|chapter|timeline|list|counter|quote|map)\b"
_FIND_TAGS = ("найти", "поиск", "find")
_ERA_RE = re.compile(r"\[\s*(?:эпоха|era)\s*[:：]\s*([^\]]+)\]", re.I)


def find_requests(script_text: str, auto_broll: bool = True, default_region: str | None = None) -> list[dict]:
    """Все метки [НАЙТИ: …] сценария + текст, который они иллюстрируют, страна и эпоха сцены.

    auto_broll — к сценам с [КАРТИНКА: …] длиннее ~6 секунд сам добавляет поиск короткого видео по описанию
    картинки (кадр «оживляет» сцену; не нашлось подходящего — ничего страшного).
    """
    from regions import scene_region
    reqs = []
    tags = list(re.finditer(r"\[\s*(найти|поиск|find|картинка|генерация|ии|ai)\s*[:：]\s*([^\]]+)\]", script_text, re.I))
    for k, m in enumerate(tags):
        is_ai = m.group(1).lower() not in _FIND_TAGS
        nxt = tags[k + 1].start() if k + 1 < len(tags) else len(script_text)
        seg = re.search(_SEG_RE, script_text[m.end():nxt], re.I)
        end = m.end() + seg.start() if seg else nxt
        era_m = _ERA_RE.search(script_text[m.end():end])
        era = era_m.group(1).strip() if era_m else ""  # [ЭПОХА: 1972] сразу после метки сцены
        own = re.sub(r"\s+", " ", re.sub(r"\[[^\]]*\]", " ", script_text[m.end():end])).strip()
        scene = own or re.sub(r"\s+", " ", re.sub(r"\[[^\]]*\]", " ", script_text[m.end(): m.end() + 900])).strip()
        if is_ai:
            if not auto_broll or len(own.split()) < 16:
                continue
            prev_gap = script_text[tags[k - 1].end():m.start()] if k else "x"
            if k and tags[k - 1].group(1).lower() in _FIND_TAGS and not re.sub(r"\[[^\]]*\]", "", prev_gap).strip():
                continue  # к этой картинке уже стоит своё [НАЙТИ] — второй поиск не нужен
            q = m.group(2).split("|")[0].strip()
            reqs.append({"query": q, "kind": "video", "count": 1, "slug": find_slug("auto " + q), "scene": scene[:450],
                         "auto": True, "era": era, "region": scene_region(own, q, default_region)})
            continue
        q, kind, count = parse_find_args(m.group(2))
        if not count:  # один кадр примерно на 6 секунд речи; темп диктора — WORDS_PER_MIN (STYLE.md)
            secs = len(own.split()) / (WORDS_PER_MIN / 60)
            count = max(1, min(4, round(secs / 6.0 + 0.3)))
        reqs.append({"query": q, "kind": kind, "count": count, "slug": find_slug(q), "scene": scene[:450],
                     "era": era, "region": scene_region(own, q, default_region)})
    return reqs


_LANG_NAMES = {"ja": "Japanese", "zh": "Chinese", "ko": "Korean", "nl": "Dutch", "it": "Italian", "es": "Spanish", "de": "German",
               "fr": "French", "pt": "Portuguese", "tr": "Turkish", "el": "Greek", "th": "Thai", "vi": "Vietnamese", "id": "Indonesian",
               "ru": "Russian", "no": "Norwegian"}


def _llm_json(prompt: str) -> object | None:
    """Короткий текстовый запрос с ответом в JSON: OpenAI (основной), Gemini (запасной)."""
    k = keys()
    if k.get("openai"):
        body = {"model": k.get("openaiModel") or "gpt-4.1-mini", "temperature": 0.2,
                "messages": [{"role": "user", "content": prompt}], "response_format": {"type": "json_object"}}
        try:
            req = urllib.request.Request("https://api.openai.com/v1/chat/completions", data=json.dumps(body).encode(), method="POST",
                                         headers={"Content-Type": "application/json", "Authorization": f"Bearer {k['openai']}"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(json.loads(r.read().decode())["choices"][0]["message"]["content"])
        except Exception as e:  # noqa: BLE001
            flog(f"openai text: {e!r}")
    if k.get("gemini"):
        body = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2}}
        for model in ("gemini-flash-lite-latest", "gemini-flash-latest"):
            try:
                req = urllib.request.Request(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                                             data=json.dumps(body).encode(), method="POST",
                                             headers={"Content-Type": "application/json", "x-goog-api-key": k["gemini"]})
                with urllib.request.urlopen(req, timeout=60) as r:
                    res = json.loads(r.read().decode())
                text = "".join(p.get("text", "") for p in res["candidates"][0]["content"]["parts"])
                return json.loads(re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip())
            except Exception as e:  # noqa: BLE001
                flog(f"gemini text {model}: {e!r}")
    return None


def native_queries(reqs: list[dict], work: Path) -> None:
    """Переводит запросы на язык страны сцены («jungle rescue» → вьетнамский для сцены во Вьетнаме) — местные фото
    находятся лучше. Результат запоминается в work/find_cache.json, повторно не спрашиваем."""
    from regions import region_lang
    cache_path = work / "find_cache.json"
    cache = load_json(cache_path, {}) or {}
    todo: dict[str, list[str]] = {}
    for r in reqs:
        lang = region_lang(r.get("region"))
        if not lang or lang == "en" or r["kind"] == "film":
            continue
        key = f"{lang}|{r['query']}"
        if key not in cache:
            todo.setdefault(lang, []).append(r["query"])
    for lang, qs in todo.items():
        qs = list(dict.fromkeys(qs))
        res = _llm_json(
            f"Translate these stock photo/video search queries into {_LANG_NAMES.get(lang, lang)}, the way a local photographer "
            f"would tag such a picture (2-5 words each, no quotes, no explanations). Return a JSON object mapping every original "
            f"query to its translation.\nQueries:\n" + "\n".join(qs))
        if isinstance(res, dict):
            for q in qs:
                t = res.get(q)
                if isinstance(t, str) and t.strip():
                    cache[f"{lang}|{q}"] = t.strip()[:80]
            flog(f"перевод запросов на {lang}: {len([q for q in qs if f'{lang}|{q}' in cache])} из {len(qs)}")
    save_json(cache_path, cache)
    for r in reqs:
        lang = region_lang(r.get("region"))
        if lang and f"{lang}|{r['query']}" in cache:
            r["native"], r["lang"] = cache[f"{lang}|{r['query']}"], lang


# ───────────────────────── 5б. главный цикл ─────────────────────────
def _place_local(src: Path, dst: Path) -> Path:
    """Свой кадр → в media эпизода: жёсткая ссылка (без лишнего места на диске); PNG → JPEG-копия."""
    import os
    import shutil
    if src.suffix.lower() == ".png":
        from PIL import Image
        dst = dst.with_suffix(".jpg")
        Image.open(src).convert("RGB").save(dst, quality=92)
        return dst
    dst = dst.with_suffix(src.suffix.lower())
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)
    return dst


def _downscale_huge(dst: Path) -> Path:
    """Фото больше 3840 px движок рендера не декодирует (урок ep-07) — уменьшаем до 4K.
    Если dst — жёсткая ссылка на свой кадр, оригинал не меняется: пишем новый файл и только потом убираем ссылку."""
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    with Image.open(dst) as im:
        if max(im.size) <= 3840:
            return dst
        small = dst.with_name(dst.stem + "_s.jpg")
        im = im.convert("RGB")
        im.thumbnail((3840, 3840), Image.LANCZOS)
        im.save(small, quality=92)
    dst.unlink()
    return small.replace(dst.with_suffix(".jpg"))


# ───────────────────────── 5в. отчёт по источникам ─────────────────────────
_REPORT_COLS = [("calls", "запросов"), ("found", "нашёл"), ("fit", "подошло"), ("eye", "глазам"), ("ok", "одобрено"),
                ("saved", "скачано"), ("refs", "образцов"), ("errors", "ошибок"), ("blocked", "блок"), ("secs", "время")]


class SourceStats:
    """Счётчики по каждому источнику за один запуск поиска — для find_report.txt."""

    def __init__(self):
        self.by: dict[str, dict] = {}

    def add(self, source: str, what: str, n: float = 1) -> None:
        row = self.by.setdefault(source, {k: 0 for k, _ in _REPORT_COLS})
        row[what] += n

    def write(self, path: Path, order: dict, warn: list[str], cfg: dict, have_keys: dict, found: dict,
              asked: int, skipped: int, quiet: bool = False) -> None:
        def fmt(k, v):
            return f"{int(v) // 60}:{int(v) % 60:02d}" if k == "secs" else str(int(v))
        names = sorted(self.by, key=lambda s: (-self.by[s]["saved"], -self.by[s]["found"], s))
        head = f"{'Источник':<12}" + "".join(f"{t:>10}" for _, t in _REPORT_COLS)
        rows = [f"{s:<12}" + "".join(f"{fmt(k, self.by[s][k]):>10}" for k, _ in _REPORT_COLS) for s in names]
        nokey = [s for s in sources.all_sources() if not sources.has_key(s, have_keys)]
        total: dict[str, int] = {}
        for it in found.values():
            for f in it.get("files", []):
                total[f.get("source") or "?"] = total.get(f.get("source") or "?", 0) + 1
        lines = [f"Отчёт поиска — {time.strftime('%Y-%m-%d %H:%M')} · запросов в этот запуск: {asked}"
                 f"{f' (уже готовых, пропущено: {skipped})' if skipped else ''}", "",
                 "Порядок источников (settings.json → finder → sources" + ("" if isinstance(cfg.get("sources"), dict) else
                                                                         ", не задан — по умолчанию из tools/sources") + "):"]
        lines += [f"  {k:<9} {', '.join(v) or '—'}" for k, v in order.items()]
        lines += [f"Выключены (finder → off): {', '.join(cfg.get('off') or []) or '—'}",
                  f"Без ключа в keys.json (пропускаются): {', '.join(nokey) or '—'}"]
        lines += [f"! {w}" for w in warn]
        lines += ["", head, *rows, "",
                  "Находки в found.json по источникам (все запуски): "
                  + (" · ".join(f"{s} {n}" for s, n in sorted(total.items(), key=lambda x: -x[1])) or "—"), "",
                  "Колонки: запросов — обращений к сайту; нашёл — кандидатов в ответах; подошло — после отсева по лицензии,",
                  "размеру, тяжёлому и повторам; глазам — показано на проверку глазами; одобрено — оценка ≥ 5;",
                  "скачано — легло в media/library; образцов — несвободные образцы в refs/ для ReGen;",
                  "ошибок — сбои ответа; блок — сайт закрыл доступ (403); время — сколько ждали этот источник.",
                  "Подробности по каждому запросу — find_log.txt."]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        if quiet:
            return
        log(f"  Отчёт по источникам: {path}")
        for r in [head, *rows]:
            log("    " + r)


def run_finder(project: Path, settings: dict, script_text: str, ctx: dict | None = None,
               own_dirs: list[Path] | None = None, force: bool = False) -> None:
    """Поиск по всем [НАЙТИ] сценария.
    project — рабочая папка эпизода (06_montage); ctx — паспорт эпизода (context.json);
    own_dirs — свои кадры эпизода (05_footage, 03_generated, 02_characters)."""
    global _LOG
    ctx = ctx or {}
    cfg = settings.get("finder") or {}
    allow_sa = bool(cfg.get("allowShareAlike", False))
    order, order_warn = sources.order(cfg)  # какие источники спрашивать для каждого вида материала
    local_dirs = [d for d in (own_dirs or []) if d.is_dir()]
    src_local.DIRS[:] = local_dirs
    stats = SourceStats()
    from regions import project_region
    default_region = str(ctx.get("country") or cfg.get("region") or "").strip() or project_region(script_text)
    reqs = find_requests(script_text, auto_broll=bool(cfg.get("autoBroll", True)), default_region=default_region)
    if not reqs:
        log("  В сценарии нет меток [НАЙТИ: …] — искать нечего")
        return
    media = project / "media"
    library = project / "library"
    work = project / "work"
    media.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    found_path = work / "found.json"
    found = load_json(found_path, {}) or {}
    _LOG = work / "find_log.txt"
    flog(f"=== поиск: {len(reqs)} запросов")
    # старые находки от прошлых версий сценария — в папку media/_old (не удаляем, но в ролик они не попадут)
    current = {r["slug"] for r in reqs}
    old_dir = media / "_old"
    for p in list(media.glob("find_*")):
        slug = p.stem.rsplit("_", 1)[0][5:]
        if slug not in current:
            old_dir.mkdir(exist_ok=True)
            p.replace(old_dir / p.name)
    found = {k: v for k, v in found.items() if k in current or k.startswith("src:")}
    used = {f.get("url") for it in found.values() for f in it.get("files", [])}
    # свои кадры, уже стоящие в шотах ([СЦЕНА: 12, 12_2]), в другие шоты не подставляем — иначе повторы
    # (гравюры людей из реестра подставляются по имени и остаются доступными везде)
    raw = (project / "script.txt").read_text(encoding="utf-8") if (project / "script.txt").exists() else ""
    bound = {t.strip().split("@")[0].lower() for m in re.finditer(r"\[\s*(?:сцена|scene)\s*:\s*([^\]]+)\]", raw, re.I)
             for t in re.split(r"[,;]+", m.group(1)) if t.strip()}
    for d in local_dirs:
        used |= {p.as_uri() for p in d.iterdir() if p.is_file() and p.stem.lower() in bound}
    shot_of = shot_numbers(project / "script.txt")
    refs_dir = project / "refs"  # образцы с закрытыми правами: s_<шот>_N.jpg — Nurlan перерисует их в ИИ
    refs_path = work / "refs.json"
    refs = load_json(refs_path, {}) or {}
    have_keys = keys()
    can_see = bool(have_keys.get("openai") or have_keys.get("gemini"))
    autos = sum(1 for r in reqs if r.get("auto"))
    in_use = [s for s in dict.fromkeys(n for names in order.values() for n in names) if sources.has_key(s, have_keys)]
    log(f"▶ Поиск материалов: {len(reqs) - autos} запросов{f' + {autos} видео к картинкам' if autos else ''}. "
        f"Страна эпизода: {default_region or 'не определена'}. Свои кадры: {', '.join(d.name for d in local_dirs) or 'нет'}. "
        f"Источники: {', '.join(in_use)}")
    for w in order_warn:
        log(f"  ! настройки поиска: {w}")
    report_path = work / "find_report.txt"
    asked = skipped = 0
    started = time.time()
    tally = {"vision": 0}  # сколько раз смотрели глазами (деньги OpenAI)
    outcomes: list[dict] = []  # итоги по каждому запросу → журнал поиска (find_history.py)

    def report(quiet: bool = True) -> None:
        stats.write(report_path, order, order_warn, cfg, have_keys, found, asked, skipped, quiet=quiet)
    native_queries(reqs, work)
    if not can_see:
        log("  (нет ключа OpenAI/Gemini — отбор по описаниям, без просмотра картинок)")
    for r in reqs:
        existing = sorted(p for p in media.glob(f"find_{r['slug']}_*") if not p.name.endswith(".part"))
        stale = can_see and (found.get(r["slug"]) or {}).get("v", 1) < VISION_VERSION
        if existing and stale and not force:
            log(f"  «{r['query']}»: найдено прошлой, более мягкой проверкой — перепроверяю")
        elif existing and not force:
            log(f"  «{r['query']}»: уже есть {len(existing)} файл(а) — пропускаю")
            skipped += 1
            continue
        asked += 1
        for p in existing:
            p.unlink()
        used -= {f.get("url") for f in (found.get(r["slug"]) or {}).get("files", [])}  # свои прошлые находки снова допустимы
        kind_name = {'image': 'фото', 'video': 'видео', 'news': 'хроника', 'amateur': 'любительское видео',
                     'document': 'газеты', 'film': 'кинохроника'}[r['kind']]
        if r.get("auto"):
            kind_name = "видео к картинке"
        log(f"  «{r['query']}» ({kind_name}, нужно {r['count']}{', ' + r['region'] if r.get('region') else ''}"
            f"{', ' + r['era'] if r.get('era') else ''})")
        region = r.get("region") or ""
        specific = _is_specific(r["query"])
        ctx_text = context_brief(ctx, r.get("era", ""))
        ok_types = {"image": ("image",), "video": ("video",), "news": ("video", "image"), "amateur": ("video",),
                    "document": ("document", "image"), "film": ("film",)}[r["kind"]]
        seen: set = set()
        ranked = None
        nonfree: list[dict] = []  # кандидаты, отсеянные только из-за лицензии
        fit_n = [0]  # сколько свободных кандидатов прошло отсев (для «почему пусто»)
        rejects: list[str] = []  # причины отказа глазами
        hit = [None]  # какой вариант запроса первым дал одобренный кадр

        def gather(query: str, lang: str = "en", refs_only: bool = False, only: str | None = None) -> list[dict]:
            """Спросить источники этого вида материала (порядок — settings.json) и отсеять неподходящее.
            refs_only — спросить только источники образцов (REFS_ONLY: DuckDuckGo, Tavily); иначе — все, кроме них.
            only — спросить один этот источник."""
            cands = []
            for name in order[r["kind"]]:
                if not sources.has_key(name, have_keys) or _flag(name, "REFS_ONLY") != refs_only or (only and name != only):
                    continue
                if not sources.fits_region(name, region):
                    continue
                t0 = time.time()
                try:
                    got = sources.get(name).search(query, r["kind"], max(r["count"], 5), lang)
                    stats.add(name, "calls")
                    stats.add(name, "found", len(got))
                    cands += got
                except SourceBlocked as e:
                    stats.add(name, "blocked")
                    if str(e) not in _blocked_told:
                        _blocked_told.add(str(e))
                        log(f"    · {name}: сайт {e} сейчас не пускает автоматический поиск — пропускаю его до конца поиска")
                    flog(f"{name}: {e} заблокирован (403)")
                except Exception as e:  # noqa: BLE001
                    stats.add(name, "errors")
                    log(f"    ! {name}: {str(e)[:90]}")
                stats.add(name, "secs", time.time() - t0)
            out = []
            for c in cands:
                k = _cand_key(c)
                if c["type"] not in ok_types:
                    continue
                if k and k not in seen and k not in used and acceptable(c, allow_sa):
                    seen.add(k)
                    out.append(c)
                    stats.add(c["source"], "fit")
                    fit_n[0] += 1
                elif k and k not in seen and acceptable_ref(c):
                    seen.add(k)
                    nonfree.append(c)
            for c in out:
                c["score"] = heuristic_score(c, r["query"])
            out.sort(key=lambda c: -c["score"] - (0.15 if c["type"] == "video" and r["kind"] == "news" else 0))
            return out

        def judge(pool: list[dict], label: str, count: bool = True) -> list[dict]:
            """Проверка глазами; без неё — только кандидаты, чьё описание действительно совпадает с запросом.
            count=False — образцы с закрытыми правами (в отчёт идут отдельной колонкой «образцов»)."""
            nonlocal ranked
            ranked = vision_rank(pool, r["query"], r["scene"], r["count"], region=region, specific=specific,
                                 kind=r["kind"], ctx_text=ctx_text, ref=not count) if r["kind"] != "film" else None
            if ranked is None:
                words = [w for w in re.findall(r"\w{3,}", r["query"].lower())]

                def text_match(c):
                    t = f"{c.get('title', '')} {c.get('text', '')}".lower()
                    return sum(1 for w in words if w in t) / max(1, len(words))
                ok = [c for c in pool if text_match(c) >= (0.75 if _flag(c["source"], "STRICT_TEXT") else 0.5)]
                flog(f"«{r['query']}» [{label}]: без проверки глазами, по описанию подходят {len(ok)} из {len(pool)}")
                return ok
            tally["vision"] += 1
            if count:
                for c in pool:
                    if c.get("vision"):
                        stats.add(c["source"], "eye")
                        if c not in ranked and c["vision"].get("why"):
                            rejects.append(str(c["vision"]["why"])[:80])
                for c in ranked:
                    stats.add(c["source"], "ok")
            flog(f"«{r['query']}» [{label}]: одобрено {len(ranked)} из {len(pool)}: " +
                 "; ".join(f"{c.get('title', '')[:40]}={c['vision'].get('score')}" for c in ranked[:6]))
            for c in pool:
                v = c.get("vision")
                if v:
                    flog(f"    {v.get('score')}{' ✗' if c not in ranked else ''} era_ok={v.get('era_ok')} {v.get('place', '')} "
                         f"[{c['source']}] {str(c.get('title', ''))[:50]} → видно: {str(v.get('shows', ''))[:80]}"
                         + (f" · отказ: {str(v.get('why', ''))[:80]}" if c not in ranked else ""))
            return ranked

        chosen_from: list[dict] = []
        # 1) свои кадры эпизода — интернет только для того, что свои папки не закрывают
        if local_dirs and r["kind"] in src_local.TYPES:
            # портрет из реестра по имени — во все шоты этого человека, повтор допустим (EP-09)
            t0 = time.time()
            local_found = src_local.search(r["query"], r["kind"], 12)
            stats.add("local", "calls")
            stats.add("local", "found", len(local_found))
            stats.add("local", "secs", time.time() - t0)
            local_pool = [c for c in local_found
                          if (c.get("trusted") or c["url"] not in used) and c["type"] in ok_types and acceptable(c, allow_sa)]
            stats.add("local", "fit", len(local_pool))
            trusted = [c for c in local_pool if c.get("trusted")]
            for c in trusted:  # фото из реестра по имени — без проверки глазами
                c["rank"] = 12.0
            if trusted:
                flog(f"«{r['query']}» [02_characters]: по имени из реестра — {', '.join(Path(c['url']).name for c in trusted)}")
            chosen_from += trusted
            rest = [c for c in local_pool if not c.get("trusted")]
            if rest and len(chosen_from) < r["count"]:
                ok = judge(rest, "свои кадры")
                if ranked is None:
                    ok = [c for c in rest if c["match"] >= 0.6]
                for c in ok:
                    c["rank"] = float(c.get("rank", 9)) + 1.0  # свой кадр выигрывает при равной оценке
                chosen_from += ok
        if chosen_from:
            hit[0] = "свои кадры"
        # 2) интернет: со страной → на языке страны → как есть → шире
        variants: list[tuple[str, str]] = []
        label_of: dict = {}  # вариант запроса → как он назван в журнале поиска
        if region and region.lower() not in r["query"].lower() and (not specific or r["kind"] in ("news", "amateur")):
            variants.append((f"{r['query']} {region}", "en"))
            label_of[variants[-1]] = "со страной"
        if r.get("native"):
            variants.append((r["native"], r.get("lang") or "en"))
            label_of[variants[-1]] = "на языке страны"
        variants.append((r["query"], "en"))
        label_of.setdefault(variants[-1], "как есть")
        # год в запросе помогает проверке, но мешает архивам («Rajiv Gandhi 1985 portrait» на Wikimedia — пусто):
        # запасной вариант без года; эпоху всё равно проверяют глазами (context_brief)
        no_year = re.sub(r"\s+", " ", re.sub(r"\b(1[89]|20)\d\ds?\b", " ", r["query"])).strip()
        if no_year and no_year != r["query"]:
            variants.append((no_year, "en"))
            label_of.setdefault(variants[-1], "без года")
        wider = [] if specific else [(w, "en") for w in _broaden(r["query"])]
        for w in wider:
            label_of.setdefault(w, "шире")
        vision_ok = True
        for vq, lang in variants + wider:
            if len(chosen_from) >= r["count"]:
                break
            if (vq, lang) in wider and not vision_ok:
                break  # расширять поиск без проверки глазами опасно — наберём случайного
            pool = _diverse(gather(vq, lang), 12)
            if not pool:
                continue
            ok = judge(pool, f"поиск: {vq}")
            vision_ok = ranked is not None
            if ok and not hit[0]:
                hit[0] = label_of.get((vq, lang), "как есть")
            chosen_from += ok
        chosen_from.sort(key=lambda c: -float(c.get("rank", c.get("score", 0))))
        # 3) скачивание лучших
        saved = []
        for c in chosen_from:
            if len(saved) >= r["count"]:
                break
            mod = sources.all_sources().get(c["source"])
            if hasattr(mod, "rights_ok") and not mod.rights_ok(c):  # проверка прав у самого источника (LOC)
                continue
            if not c.get("url") and hasattr(mod, "resolve"):  # ссылку на файл источник даёт отдельно (NASA, DVIDS, Archive)
                try:
                    c["url"] = mod.resolve(c)
                except Exception as e:  # noqa: BLE001
                    flog(f"{c['source']}: ссылка на файл не получена: {e!r}")
            if not c.get("url"):
                continue
            ext = Path(urllib.parse.urlparse(c["url"]).path).suffix.lower()
            if c["type"] in ("video", "film"):
                ext = ext if ext in (".mp4", ".webm", ".mov") else ".mp4"
            elif ext not in IMAGE_EXT:
                ext = ".jpg"
            n = len(saved) + 1
            folder = library if c["type"] == "film" else media
            folder.mkdir(exist_ok=True)
            dst = folder / f"find_{r['slug']}_{n}{'.tmp' if ext in ('.tif', '.tiff', '.webp', '.png') else ext}"
            if c["source"] == "local":
                dst = _place_local(Path(urllib.request.url2pathname(urllib.parse.urlparse(c["url"]).path)), dst)
            elif not download(c["url"], dst):
                continue
            if c["type"] in ("video", "film"):  # обрывок в пару секунд в ролике крутится по кругу — не нужен
                try:
                    from media import probe
                    if 0 < float(probe(dst).get("duration") or 99) < 4:
                        dst.unlink(missing_ok=True)
                        flog(f"слишком короткое видео, пропускаю: {c.get('title', '')}")
                        continue
                except Exception:  # noqa: BLE001
                    pass
            if dst.suffix == ".tmp":  # приводим к JPEG — движку так проще
                try:
                    from PIL import Image
                    final = dst.with_suffix(".jpg")
                    Image.open(dst).convert("RGB").save(final, quality=92)
                    dst.unlink()
                    dst = final
                except Exception:  # noqa: BLE001
                    dst.unlink(missing_ok=True)
                    continue
            if c["type"] in ("image", "document"):
                try:
                    from PIL import Image
                    Image.MAX_IMAGE_PIXELS = None
                    with Image.open(dst) as im:
                        c["width"], c["height"] = im.size
                    if c["width"] < 1000 and c["type"] == "image":
                        dst.unlink()
                        continue
                    dst = _downscale_huge(dst)
                except Exception:  # noqa: BLE001
                    dst.unlink(missing_ok=True)
                    continue
            if hasattr(mod, "on_saved"):  # Unsplash просит отмечать скачивания (правила их API)
                mod.on_saved(c)
            entry = {k: c.get(k) for k in ("source", "type", "url", "page", "title", "author", "license", "license_url", "date",
                                           "license_name", "pageid")}
            entry["kind"] = "auto" if r.get("auto") else r["kind"]
            entry["region"] = region
            entry["file"] = dst.name
            entry["folder"] = folder.name
            if c.get("vision"):
                entry["check"] = c["vision"]
            saved.append(entry)
            stats.add(c["source"], "saved")
            used.add(c.get("url"))
            log(f"    ✓ {dst.name} — {c['source']}, {LICENSE_TEXT.get(c['license'], c['license'])}: {str(c.get('title'))[:60]}")
        # 4) не хватило свободных кадров — лучшие несвободные как образцы для перерисовки (refs/s_<шот>_N.jpg)
        shot = shot_of.get(r["slug"])
        want_refs = len(saved) < r["count"] and shot is not None and not r.get("auto") and not refs.get(r["slug"])
        if want_refs:  # источники только для образцов (DuckDuckGo, Tavily) — спрашиваем лишь сейчас, когда образец нужен,
            # по очереди из settings.json: следующий — только если предыдущий не дал ни одного кандидата (Tavily — запасной)
            for name in [n for n in order[r["kind"]] if _flag(n, "REFS_ONLY")]:
                before = len(nonfree)
                gather(r["query"], refs_only=True, only=name)
                if len(nonfree) > before:
                    break
        if want_refs and nonfree:
            for c in nonfree:
                c["score"] = heuristic_score(c, r["query"])
            pool = _diverse(sorted(nonfree, key=lambda c: -c["score"]), 12)
            ok = judge(pool, "образцы с закрытыми правами", count=False) or []
            got = []
            for c in ok[:max(1, min(2, r["count"] - len(saved)))]:
                refs_dir.mkdir(exist_ok=True)
                ext = Path(urllib.parse.urlparse(c["url"]).path).suffix.lower()
                dst = refs_dir / f"s_{shot}_{len(got) + 1}{ext if ext in ('.jpg', '.jpeg', '.png') else '.jpg'}"
                if download(c["url"], dst):
                    got.append({"file": dst.name, "url": c["url"], "page": c.get("page"), "title": c.get("title"),
                                "author": c.get("author"), "license": c.get("license"), "source": c["source"]})
                    stats.add(c["source"], "refs")
                    log(f"    ◆ образец {dst.name} — {c['source']}, права закрыты: {str(c.get('title'))[:60]}")
            if got:
                refs[r["slug"]] = {"shot": shot, "query": r["query"], "files": got}
                save_json(refs_path, refs)
        if len(saved) < r["count"] and r.get("auto"):
            log("    · подходящего видео нет — сцена останется с картинкой")
        elif len(saved) < r["count"]:
            log(f"    ! нашлось только {len(saved)} из {r['count']} — заменить своими кадрами или [КАРТИНКА]")
        found[r["slug"]] = {"query": r["query"], "kind": r["kind"], "files": saved,
                            "v": VISION_VERSION if (ranked is not None or r["kind"] == "film") else 1}
        save_json(found_path, found)
        reason = None
        if len(saved) < r["count"]:
            reason = ("никто не нашёл" if not fit_n[0] else "отклонено глазами" if rejects
                      else "найдено, но не скачалось / мало подходящих")
        outcomes.append({"shot": shot, "query": r["query"], "kind": r["kind"], "auto": bool(r.get("auto")),
                         "region": region, "era": r.get("era", ""), "need": r["count"], "got": len(saved),
                         "sources": [f["source"] for f in saved], "variant": hit[0] if saved else None,
                         "refs": [f["source"] for f in (refs.get(r["slug"]) or {}).get("files", [])] if want_refs else [],
                         "empty_reason": reason, "rejects": list(dict.fromkeys(rejects))[:3]})
        report()  # после каждого запроса — если поиск прервётся, отчёт за сделанное останется
    report(quiet=False)
    import find_history
    find_history.record(project.parent.name, time.time() - started, asked, skipped, stats.by, outcomes, tally["vision"])
    write_credits(project, found)
    found_sheet(project, found)


# ───────────────────────── 6. свои прямые ссылки (06_montage/sources.txt) ─────────────────────────
SOURCES_HELP = """# Свои материалы по прямым ссылкам — скачиваются в media при поиске.
# Формат строки:  имя | ссылка | credit=кто автор | license=pd/cc0/by | page=страница | label=плашка | note=пояснение
# Брать только материалы с явным разрешением; license обязателен.
# Пример: reagan_gandhi | https://…/photo.jpg | credit=Reagan Library | license=pd | page=https://…
# В сценарии файл вставляется меткой [СЦЕНА: reagan_gandhi].
"""


def _parse_sources(path: Path) -> list[dict]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [x.strip() for x in line.split("|")]
        if len(parts) < 2 or not parts[1].startswith("http"):
            continue
        item = {"name": re.sub(r"[^\w\-]+", "_", parts[0]).strip("_").lower(), "url": parts[1]}
        for p in parts[2:]:
            if "=" in p:
                k, v = p.split("=", 1)
                item[k.strip().lower()] = v.strip()
        out.append(item)
    return out


def fetch_sources(project: Path, force: bool = False) -> None:
    """Скачивает материалы из 06_montage/sources.txt и записывает авторство. Без license= строка пропускается."""
    path = project / "sources.txt"
    if not path.exists():
        return
    items = _parse_sources(path)
    if not items:
        return
    media = project / "media"
    media.mkdir(parents=True, exist_ok=True)
    found_path = project / "work" / "found.json"
    found_path.parent.mkdir(parents=True, exist_ok=True)
    found = load_json(found_path, {}) or {}
    log(f"▶ Свои ссылки (sources.txt): {len(items)}")
    for it in items:
        lic = (it.get("license") or "").lower()
        if lic not in ("pd", "cc0", "by", "by-sa"):
            log(f"    ! {it['name']}: не указана лицензия (license=pd/cc0/by) — пропускаю")
            continue
        key = f"src:{it['name']}"
        existing = [p for p in media.glob(f"{it['name']}.*") if not p.name.endswith(".part")]
        if existing and not force and key in found:
            continue
        ext = Path(urllib.parse.urlparse(it["url"]).path).suffix.lower() or ".jpg"
        raw = media / f"{it['name']}.download{ext}"
        if not download(it["url"], raw, headers={"Referer": it.get("page") or it["url"]}):
            continue
        is_video = ext in (".mp4", ".mov", ".webm", ".wmv", ".avi", ".mpg", ".mpeg", ".m4v")
        final = media / f"{it['name']}{'.mp4' if is_video else '.jpg'}"
        for p in existing:
            p.unlink(missing_ok=True)
        try:
            if is_video:  # единый формат для движка: H.264 MP4, без звука
                run(["ffmpeg", "-y", "-v", "error", "-i", str(raw), "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                     "-pix_fmt", "yuv420p", "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", str(final)])
            else:
                from PIL import Image
                Image.open(raw).convert("RGB").save(final, quality=93)
                final = _downscale_huge(final)
            raw.unlink(missing_ok=True)
        except Exception as e:  # noqa: BLE001
            log(f"    ! {it['name']}: не удалось преобразовать ({str(e)[:80]})")
            raw.unlink(missing_ok=True)
            continue
        found[key] = {"query": it["name"], "kind": "source", "v": VISION_VERSION, "files": [{
            "source": "list", "type": "video" if is_video else "image", "url": it["url"], "page": it.get("page") or it["url"],
            "title": it.get("note") or it["name"], "author": it.get("credit") or "", "license": lic, "license_url": "",
            "file": final.name, "folder": "media", "kind": "news" if it.get("label") else "source",
            "label": it.get("label"), "note": it.get("note")}]}
        log(f"    ✓ {final.name} — {it.get('credit') or 'свой источник'}, {LICENSE_TEXT.get(lic, lic)}")
    save_json(found_path, found)
    write_credits(project, found)


# ───────────────────────── 7. авторство и обзор ─────────────────────────
def refresh_commons_meta(found: dict) -> bool:
    """Для находок с Wikimedia дозапрашиваем точную лицензию (с версией) и номер страницы для короткой ссылки."""
    need = [f for it in found.values() for f in it.get("files", [])
            if f.get("source") == "commons" and (not f.get("license_name") or not f.get("pageid")) and f.get("title")]
    changed = False
    for i in range(0, len(need), 10):
        chunk = need[i:i + 10]
        try:
            url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode({
                "action": "query", "format": "json", "prop": "imageinfo", "iiprop": "extmetadata",
                "iiextmetadatafilter": "LicenseShortName|LicenseUrl", "titles": "|".join("File:" + f["title"] for f in chunk)})
            data = http_json(url).get("query") or {}
        except Exception as e:  # noqa: BLE001
            flog(f"commons meta: {e!r}")
            continue
        norm = {x.get("to"): x.get("from") for x in data.get("normalized", [])}
        for p in (data.get("pages") or {}).values():
            title = norm.get(p.get("title"), p.get("title", "")).replace("File:", "")
            md = ((p.get("imageinfo") or [{}])[0].get("extmetadata") or {})
            for f in chunk:
                if f["title"].replace("_", " ") == title.replace("_", " "):
                    f["pageid"] = p.get("pageid")
                    f["license_name"] = strip_html((md.get("LicenseShortName") or {}).get("value", "")) or f.get("license_name")
                    f["license_url"] = strip_html((md.get("LicenseUrl") or {}).get("value", "")) or f.get("license_url")
                    changed = True
    return changed


def _used_files(project: Path) -> set | None:
    """Файлы, которые реально стоят в плане монтажа (None — плана ещё нет, этап 1)."""
    plan = load_json(project / "plan.json")
    if not plan:
        return None
    used = set()
    for s in plan.get("scenes", []):
        if s.get("src"):
            used.add(Path(s["src"]).name)
        for it in s.get("items", []) or []:
            used.add(Path(it.get("src", "")).name)
    return used


_ROLE_WORDS = r"(creator|author|photographer|artist|contributor|uploader)"
_ARCHIVE_NAMES = {"loc.gov": "Library of Congress", "nara": "National Archives", "archives.gov": "National Archives",
                  "nasa.gov": "NASA", "dvidshub": "DVIDS"}


def clean_author(raw: str, source: str = "", fixes: dict | None = None) -> str:
    """Имя автора для блока авторства — как его прочтёт зритель:
    «Elfelt &amp; Co.» → «Elfelt & Co.»; ссылка вместо имени → название архива; «Lowe, Jet, creator» → «Jet Lowe»;
    «Unknown author Unknown author» → ''; длинная подпись коллекции LoC → «Library of Congress»; без обрезки посреди слова.
    fixes — ручные поправки опечаток из данных Wikimedia (06_montage/credits_fix.json)."""
    import html
    a = re.sub(r"\s+", " ", html.unescape(strip_html(raw or ""))).strip(" ,;")
    if fixes and a in fixes:
        return fixes[a]
    if re.match(r"https?://", a):
        return next((v for k, v in _ARCHIVE_NAMES.items() if k in a), SOURCE_NAMES.get(source, ""))
    if "library of congress" in a.lower():
        return "Library of Congress"
    if re.fullmatch(r"(unknown( author)?\s*)+|anonymous|n/?a", a, re.I):
        return ""
    a = re.sub(rf",?\s*\(?{_ROLE_WORDS}\)?\s*$", "", a, flags=re.I).strip(" ,")
    m = re.fullmatch(r"([A-ZÀ-ÖØ-Þ][\w'\-]+),\s*([A-ZÀ-ÖØ-Þ][\w'.\-]+(?: [A-ZÀ-ÖØ-Þ][\w'.\-]+)?)", a)
    if m:  # «Lowe, Jet» — каталожный порядок → «Jet Lowe»
        a = f"{m.group(2)} {m.group(1)}"
    if fixes and a in fixes:
        return fixes[a]
    if len(a) > 70:
        a = a[:70].rsplit(" ", 1)[0].rstrip(" ,;")
    return a


def clean_title(raw: str) -> str:
    """Название файла Wikimedia как название работы: без расширения и номеров Flickr «(50366994537)», «testK7927»."""
    t = re.sub(r"\.(jpe?g|png|tiff?|webm|ogv|mp4|gif)$", "", strip_html(raw or ""), flags=re.I)
    t = re.sub(r"\s*\(\d{6,}\)", "", t)              # (50366994537)
    t = re.sub(r"(?<=[a-z])[A-Z]\d{3,}\b", "", t)    # testK7927 → test
    t = re.sub(r"\s+", " ", t).strip()
    return t[:70].rsplit(" ", 1)[0] if len(t) > 70 else t


def write_credits(project: Path, found: dict, used: set | None = None) -> Path:
    """Блок «авторы и лицензии» для описания YouTube (английский). После монтажа — только то, что реально в ролике.
    CC BY: название, автор, точная лицензия с версией и короткая постоянная ссылка (curid) — так требует лицензия
    и так блок помещается в лимит описания YouTube. Свои кадры (own) в блок не попадают.
    Файл чистый и полный — его вставляют в описание как есть, без ручной правки (договорённость с Video-Wrapper).
    Опечатки в данных Wikimedia, которые код не угадает, — 06_montage/credits_fix.json: {"как в данных": "как надо"}."""
    if used is None:
        used = _used_files(project)
    if refresh_commons_meta(found):
        save_json(project / "work" / "found.json", found)
    fixes = load_json(project / "credits_fix.json", {}) or {}
    files = [f for it in found.values() for f in it.get("files", []) if used is None or f.get("file") in used]
    lines = ["IMAGE & FOOTAGE CREDITS"]
    lic_urls: dict = {}
    by = [f for f in files if f.get("license") in ("by", "by-sa")]
    seen = set()
    if by:
        lines += ["", "Via Wikimedia Commons and other free archives:"]
        for f in by:
            key = f.get("page") or f.get("url")
            if key in seen:
                continue
            seen.add(key)
            name = f.get("license_name") or LICENSE_TEXT.get(f.get("license"), "CC BY")
            if f.get("license_url"):
                lic_urls[name] = f["license_url"]
            link = (f"https://commons.wikimedia.org/w/index.php?curid={f['pageid']}" if f.get("pageid") and f.get("source") == "commons"
                    else (f.get("page") or f.get("url") or ""))
            title = clean_title(f.get("title") or "")
            author = clean_author(f.get("author") or "", f.get("source", ""), fixes) or "unknown author"
            lines.append(f"• \"{title}\" — {author}, {name}: {link}")
    pd = [f for f in files if f.get("license") in ("pd", "cc0")]
    if pd:
        names = []
        for f in pd:
            a = clean_author(f.get("author") or "", f.get("source", ""), fixes) or SOURCE_NAMES.get(f.get("source"), "")
            if a and a.lower() not in {n.lower() for n in names}:
                names.append(a)
        lines.append(f"Public domain, courtesy of: {'; '.join(names)}.")
    stock = sorted({SOURCE_NAMES.get(f.get("source"), f.get("source")) for f in files if f.get("license") in ("pixabay", "pexels", "unsplash")})
    if stock:
        lines.append(f"Stock footage: {', '.join(stock)}.")
    if lic_urls:
        lines.append("License texts: " + "; ".join(f"{k} {v}" for k, v in lic_urls.items()))
    out = project / "output" / f"{project.parent.name}_credits.txt"  # 06_montage/output/ep-7_credits.txt
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log(f"  Авторство для описания: {out}")
    return out


def found_sheet(project: Path, found: dict) -> None:
    """Обзорный лист всего найденного (06_montage/work/found_sheet.jpg): кадр, файл, источник и оценка проверки — для просмотра глазами."""
    try:
        from PIL import Image, ImageDraw
        Image.MAX_IMAGE_PIXELS = None
    except ImportError:
        return
    tiles = []
    for item in found.values():
        for f in item.get("files", []):
            p = project / f.get("folder", "media") / f["file"]
            if not p.exists():
                continue
            try:
                if f["type"] in ("video", "film"):
                    frame = project / "work" / "found_frame.jpg"
                    run(["ffmpeg", "-y", "-v", "error", "-ss", "1", "-i", str(p), "-frames:v", "1", str(frame)], check=False)
                    im = Image.open(frame).convert("RGB")
                else:
                    im = Image.open(p).convert("RGB")
                im.thumbnail((480, 270))
                tile = Image.new("RGB", (480, 300), (24, 20, 16))
                tile.paste(im, ((480 - im.width) // 2, (270 - im.height) // 2))
                score = (f.get("check") or {}).get("score")
                label = f"{f['file'][:44]}  [{f.get('source', '')}{f' {score}' if score is not None else ''}]"
                ImageDraw.Draw(tile).text((8, 276), label, fill=(240, 230, 210))
                tiles.append(tile)
            except Exception:  # noqa: BLE001
                continue
    if not tiles:
        return
    cols = 4
    sheet = Image.new("RGB", (cols * 480, ((len(tiles) + cols - 1) // cols) * 300), (0, 0, 0))
    for k, t in enumerate(tiles):
        sheet.paste(t, ((k % cols) * 480, (k // cols) * 300))
    out = project / "work" / "found_sheet.jpg"
    sheet.save(out, quality=85)
    log(f"  Обзор найденного: {out}")


def _selftest() -> None:  # проверка разбора лицензий: python tools/finder.py
    assert norm_license("CC BY 4.0") == "by"
    assert norm_license("CC BY-SA 3.0") == "by-sa"
    assert norm_license("CC BY-NC 2.0") is None
    assert norm_license("Public domain") == "pd"
    assert norm_license("cc0") == "cc0"
    assert norm_license("by-nd") is None
    assert norm_license("pdm") == "pd"


if __name__ == "__main__":
    _selftest()
    print("ok")
