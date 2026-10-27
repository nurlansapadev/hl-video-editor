"""Разбор сценария с метками и привязка текста к времени озвучки."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher

# ───────────────────────── Метки ─────────────────────────
SEGMENT_TAGS = {
    "сцена": "media", "scene": "media", "кадр": "media", "фото": "media", "видео": "media", "media": "media",
    "заголовок": "title", "глава": "title", "title": "title", "chapter": "title", "интро": "title",
    "таймлайн": "timeline", "хронология": "timeline", "timeline": "timeline",
    "список": "list", "list": "list",
    "счётчик": "counter", "счетчик": "counter", "цифра": "counter", "число": "counter", "counter": "counter",
    "цитата": "quote", "пословица": "quote", "quote": "quote",
    "карта": "map", "map": "map",
    "диаграмма": "bars", "график": "bars", "bars": "bars", "сравнение": "bars",
    "финал": "outro", "концовка": "outro", "outro": "outro",
    "инфографика": "infographic", "infographic": "infographic",
    "найти": "find", "поиск": "find", "find": "find",
    "картинка": "ai", "генерация": "ai", "ии": "ai", "ai": "ai",
}
INLINE_TAGS = {
    "подпись": "lowerThird", "титр": "lowerThird", "lower": "lowerThird",
    "дата": "date", "год": "date", "date": "date",
    "надпись": "label", "label": "label", "текст": "label",
    "акцент": "punch", "зум": "punch", "zoom": "punch", "наезд": "punch",
    "переход": "transition", "transition": "transition",
    "звук": "sfx", "sfx": "sfx",
    "фон": "background", "background": "background",
    "коллаж": "collage", "collage": "collage",
    "эпоха": "era", "era": "era",  # [ЭПОХА: 1972] — сцена вне основной эпохи эпизода (для поиска и проверки кадров)
}
TRANSITION_NAMES = {
    "растворение": "fade", "fade": "fade", "плавно": "fade", "наплыв": "fade",
    "затемнение": "dip", "через чёрное": "dip", "через черное": "dip", "dip": "dip",
    "сдвиг": "push", "push": "push", "слайд": "push",
    "зум": "zoom", "приближение": "zoom", "zoom": "zoom",
    "шторка": "wipe", "wipe": "wipe",
    "размытие": "blur", "blur": "blur",
    "склейка": "cut", "cut": "cut", "резко": "cut",
}

TAG_RE = re.compile(r"\[([^\[\]]+)\]")
STRONG_END = re.compile(r"[.!?…»\"]$")
WEAK_END = re.compile(r"[,;:—–-]$")


@dataclass
class Word:
    text: str  # как в сценарии, с пунктуацией
    norm: str
    idx: int
    start: float = 0.0
    end: float = 0.0
    matched: bool = False


@dataclass
class Marker:
    type: str
    args: str
    word_idx: int  # индекс первого слова после метки


@dataclass
class Block:
    kind: str
    args: str = ""
    raw_tag: str = ""
    words: list[Word] = field(default_factory=list)
    markers: list[Marker] = field(default_factory=list)
    media: list[str] = field(default_factory=list)
    media_start: dict = field(default_factory=dict)  # с какой секунды брать видео: {"film.mp4": 83.0}
    find: str = ""  # запрос [НАЙТИ: …]
    ai: list = field(default_factory=list)  # номера картинок [КАРТИНКА: …] (ai01, ai02…)
    recon: set = field(default_factory=set)  # картинки-реконструкции реальных событий (плашка «AI reconstruction»)


def find_slug(query: str) -> str:
    """Имя файлов для найденных материалов: find_<slug>_1.jpg (одинаково в поиске и в разборе сценария)."""
    s = query.split("|")[0].lower()
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    full = re.sub(r"[^a-z0-9а-я]+", "-", s).strip("-")
    short = full[:32].strip("-") or "q"
    # короткая метка + отпечаток всего запроса: разные запросы с одинаковым началом не перепутаются
    return f"{short}-{hashlib.md5(full.encode()).hexdigest()[:4]}"


def _time_to_sec(t: str) -> float | None:
    parts = t.strip().split(":")
    try:
        nums = [float(x.replace(",", ".")) for x in parts]
    except ValueError:
        return None
    sec = 0.0
    for x in nums:
        sec = sec * 60 + x
    return sec


def norm(w: str) -> str:
    w = w.lower().replace("ё", "е").replace("й", "и").replace("ß", "ss").replace("œ", "oe").replace("æ", "ae")
    w = "".join(c for c in unicodedata.normalize("NFKD", w) if not unicodedata.combining(c))
    return re.sub(r"[^0-9a-zа-я]", "", w)


def split_tag(inner: str) -> tuple[str, str, bool]:
    inner = inner.strip()
    m = re.match(r"^([A-Za-zА-Яа-яЁё\-]+)\s*([:：]?)\s*(.*)$", inner, re.S)
    if not m:
        return inner.lower(), "", False
    return m.group(1).lower(), m.group(3).strip(), bool(m.group(2))


def parse_script(text: str, media_names: list[str]) -> list[Block]:
    """Превращает сценарий в последовательность блоков (сцен)."""
    lines = [ln for ln in text.split("\n") if not ln.lstrip().startswith(("#", "//"))]
    text = "\n".join(lines)
    stems = {}
    # видео идут последними: если есть и 06.jpg, и 06.mp4 — «06» означает оживлённую версию
    video_ext = (".mp4", ".mov", ".webm", ".mkv", ".m4v")
    for n in sorted(media_names, key=lambda x: x.lower().endswith(video_ext)):
        stems[n.lower()] = n
        stems[n.rsplit(".", 1)[0].lower()] = n

    blocks: list[Block] = []
    ai_count = 0
    cur: Block | None = None
    words: list[Word] = []
    pos = 0

    def ensure_block() -> Block:
        nonlocal cur
        if cur is None:
            cur = Block(kind="media")
            blocks.append(cur)
        return cur

    def add_words(chunk: str):
        for tok in chunk.split():
            n = norm(tok)
            if not n:
                # отдельное тире/знак — приклеиваем к предыдущему слову
                if words:
                    words[-1].text += " " + tok
                continue
            w = Word(text=tok, norm=n, idx=len(words))
            words.append(w)
            ensure_block().words.append(w)

    for m in TAG_RE.finditer(text):
        add_words(text[pos : m.start()])
        pos = m.end()
        name, args, has_colon = split_tag(m.group(1))
        if name in SEGMENT_TAGS:
            kind = SEGMENT_TAGS[name]
            if kind == "infographic":
                kind, args = _classify_free_infographic(args)
            if kind == "ai":  # [КАРТИНКА: промт] — сгенерированная картинка: media/ai01.png, ai02.jpg …
                ai_count += 1
                tag = f"ai{ai_count:02d}"
                files = sorted(n for n in media_names if re.match(rf"{tag}(?![0-9])", n.lower()))
                auto = find_slug("auto " + args)  # видео, которое поиск сам подобрал к этой картинке
                files += sorted(n for n in media_names if n.lower().startswith(f"find_{auto}_"))
                recon = set(files) if re.search(r"реконстр|reconstr|recreaci", args, re.I) else set()
                if cur is not None and cur.kind == "media" and (cur.ai or cur.find or cur.media) and not cur.words:
                    cur.media += files
                    cur.ai.append(ai_count)
                    cur.recon |= recon
                    continue
                cur = Block(kind="media", args=args, raw_tag=m.group(1), media=files, ai=[ai_count], recon=recon)
                blocks.append(cur)
                continue
            if kind == "find":  # [НАЙТИ: запрос | фото | 2] — сцена из найденных материалов
                slug = find_slug(args)
                files = sorted((n for n in media_names if n.lower().startswith(f"find_{slug}_")),
                               key=lambda n: (n.lower().endswith(video_ext), n))
                q = args.split("|")[0].strip()
                if cur is not None and cur.kind == "media" and (cur.find or cur.ai or cur.media) and not cur.words:
                    cur.media += files  # несколько [НАЙТИ] подряд — одна сцена с несколькими запросами
                    cur.find = f"{cur.find} + {q}" if cur.find else q
                    continue
                cur = Block(kind="media", args=args, raw_tag=m.group(1), find=q, media=files)
                blocks.append(cur)
                continue
            if kind == "media" and cur is not None and cur.kind == "media" and not cur.words and (cur.find or cur.ai or cur.media):
                target = cur  # [НАЙТИ]/[КАРТИНКА]/[СЦЕНА] подряд без текста между ними — одна сцена с общими материалами
            else:
                target = None
            cur = target or Block(kind=kind, args=args, raw_tag=m.group(1))
            if kind == "media":
                for tok in re.split(r"[,;\s]+", args):
                    key = tok.strip().lower()
                    at = None
                    if "@" in key:
                        key, _, ts = key.partition("@")
                        at = _time_to_sec(ts)
                    if key and (has_colon or not key.isdigit()) and key in stems:
                        cur.media.append(stems[key])
                        if at is not None:
                            cur.media_start[stems[key]] = at
            if target is None:
                blocks.append(cur)
        elif name in INLINE_TAGS:
            b = ensure_block()
            kind_ = INLINE_TAGS[name]
            if kind_ == "background":
                key = args.strip().lower()
                args = stems.get(key, args.strip())
            b.markers.append(Marker(type=kind_, args=args, word_idx=len(words)))
        else:
            # Неизвестная метка — считаем режиссёрской заметкой, не озвучивается
            pass
    add_words(text[pos:])
    return [b for b in blocks if b.words or b.kind != "media" or b.markers or b.media or b.find or b.ai]


def _classify_free_infographic(args: str) -> tuple[str, str]:
    """[ИНФОГРАФИКА: таймлайн — ...] → ('timeline', '...')."""
    first = norm(args.split()[0]) if args.split() else ""
    rest = re.split(r"\s*[—–:-]\s*", args, maxsplit=1)
    body = rest[1] if len(rest) > 1 else ""
    for key, kind in SEGMENT_TAGS.items():
        if first.startswith(norm(key)[:5]) and kind not in ("media", "infographic"):
            return kind, _free_to_structured(kind, body)
    return "title", args


def _free_to_structured(kind: str, body: str) -> str:
    if kind in ("timeline", "list", "map"):
        parts = [p.strip() for p in re.split(r"\s*,\s*|\s*\|\s*", body) if p.strip()]
        return " | ".join(parts)
    return body


# ───────────────────────── Привязка к времени ─────────────────────────
def align(words: list[Word], transcript: list[dict]) -> float:
    """Переносит время слов из распознавания на текст сценария. Возвращает долю совпавших слов."""
    if not words:
        return 0.0
    if not transcript:
        _estimate_timing(words)
        return 0.0
    tnorm = [norm(t["w"]) for t in transcript]
    snorm = [w.norm for w in words]
    sm = SequenceMatcher(a=snorm, b=tnorm, autojunk=False)
    matched = 0
    for a, b, size in sm.get_matching_blocks():
        for k in range(size):
            w = words[a + k]
            t = transcript[b + k]
            w.start, w.end, w.matched = t["start"], t["end"], True
            matched += 1
    # Интерполяция несовпавших слов по длине
    i = 0
    n = len(words)
    while i < n:
        if words[i].matched:
            i += 1
            continue
        j = i
        while j < n and not words[j].matched:
            j += 1
        left = words[i - 1].end if i > 0 else (transcript[0]["start"] if transcript else 0.0)
        right = words[j].start if j < n else (transcript[-1]["end"] if transcript else left + 0.4 * (j - i))
        if right < left:
            right = left
        total_chars = sum(len(w.norm) + 1 for w in words[i:j])
        acc = left
        for w in words[i:j]:
            d = (right - left) * (len(w.norm) + 1) / max(1, total_chars)
            w.start, w.end = acc, acc + d
            acc += d
        i = j
    return matched / len(words)


WORDS_PER_MIN = 152  # темп диктора Honest Lies по таймлайну, с воздухом между тактами (замер EP-07, STYLE.md)


def _estimate_timing(words: list[Word]) -> None:
    """Нет озвучки (этап 1) — оцениваем время: длинные слова и концы фраз дольше, в сумме — темп WORDS_PER_MIN."""
    t = 0.5
    for w in words:
        d = max(0.18, len(w.norm) * 0.065)
        w.start, w.end = t, t + d
        t += d + 0.08
        if STRONG_END.search(w.text):
            t += 0.45
        elif WEAK_END.search(w.text):
            t += 0.15
    if words:  # подгоняем общую длину под реальный темп диктора
        k = (len(words) / WORDS_PER_MIN * 60) / max(0.1, t - 0.5)
        for w in words:
            w.start, w.end = 0.5 + (w.start - 0.5) * k, 0.5 + (w.end - 0.5) * k


# ───────────────────────── Разбор аргументов меток ─────────────────────────
def split_args(args: str) -> list[str]:
    if "|" in args:
        return [p.strip() for p in args.split("|") if p.strip()]
    if ";" in args:
        return [p.strip() for p in args.split(";") if p.strip()]
    return [args.strip()] if args.strip() else []


DASH_SPLIT = re.compile(r"\s+[—–-]\s+")


def parse_number(s: str) -> tuple[float | None, str]:
    """'6 000 000 тонн' → 6000000; '6,5 млн' → 6500000; '6.000.000' → 6000000; '1,80 euros' → 1.8; '3 millones' → 3e6."""
    # \u0430\u043d\u0433\u043b\u0438\u0439\u0441\u043a\u0430\u044f \u0437\u0430\u043f\u0438\u0441\u044c \u0442\u044b\u0441\u044f\u0447 \u00ab1,000,000\u00bb / \u00ab3,000\u00bb (EP-08: \u0441\u0447\u0451\u0442\u0447\u0438\u043a \u043f\u043e\u043a\u0430\u0437\u0430\u043b \u00ab1\u00bb \u0432\u043c\u0435\u0441\u0442\u043e \u043c\u0438\u043b\u043b\u0438\u043e\u043d\u0430) \u2014 \u0440\u0430\u043d\u044c\u0448\u0435 \u0434\u0435\u0441\u044f\u0442\u0438\u0447\u043d\u043e\u0439 \u0437\u0430\u043f\u044f\u0442\u043e\u0439
    m = re.search(r"(\d{1,3}(?:,\d{3})+(?![\d,])|\d{1,3}(?:[.\s\u00a0\u202f]\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?)\s*"
                  r"(тыс\w*|млн|миллион\w*|млрд|миллиард\w*|mil\s+millones|millones|millón|millon|milliarden|milliards?|millionen|millions?|mio|mrd|tsd|tausend|mil|bn|billion|million|k)?\.?(?=\W|$)", s, re.I)
    if not m:
        return None, s
    raw = m.group(1)
    if re.fullmatch(r"\d{1,3}(?:,\d{3})+", raw):
        raw = raw.replace(",", "")
    elif re.fullmatch(r"\d{1,3}(?:[.\s\u00a0\u202f]\d{3})+(?:,\d+)?", raw):
        raw = re.sub(r"[.\s\u00a0\u202f]", "", raw).replace(",", ".")  # 6.000.000 / 6 000 000,5
    else:
        raw = raw.replace(",", ".")
    num = float(raw)
    mult = (m.group(2) or "").lower()
    if mult.startswith("тыс") or mult in ("mil", "k", "tsd", "tausend"):
        num *= 1e3
    elif mult.startswith(("млрд", "миллиард", "bn", "billion", "milliard", "mrd")) or mult.startswith("mil millones") or re.match(r"mil\s+millones", mult):
        num *= 1e9
    elif mult.startswith(("млн", "миллион", "millon", "millón", "million", "mio")):
        num *= 1e6
    rest = (s[: m.start()] + " " + s[m.end() :]).strip()
    rest = re.sub(r"^(более|больше|около|почти|свыше|más de|mas de|cerca de|casi|unos|unas)(\s+|$)", "", rest, flags=re.I).strip()
    rest = re.sub(r"^de\s+", "", rest)
    return num, rest
