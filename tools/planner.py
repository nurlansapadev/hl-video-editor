"""Автоматический «режиссёр»: из сценария, озвучки и материалов строит план монтажа (06_montage/plan.json).

План — это не рендер: время каждой сцены, какой кадр где, движение камеры, переходы, инфографика, плашки,
главы, музыка. Рендер (engine/) рисует видео по готовому плану — после подтверждения Nurlan.
"""
from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path

from audio import speech_intervals
from gazetteer import lookup
from scriptparse import (DASH_SPLIT, STRONG_END, TRANSITION_NAMES, WEAK_END, Block, Word, norm, parse_number,
                         split_args)

# ───────────────────────── A. константы и помощники ─────────────────────────
PACE = {  # (минимум, идеал, максимум) секунд на кадр
    "calm": (3.5, 6.0, 9.0),
    "normal": (2.8, 4.5, 7.0),
    "fast": (2.0, 3.2, 5.0),
}
# длительность сцены без текста (например, [ГЛАВА] перед первой фразой)
EMPTY_BLOCK_LEN = {"title": 3.5, "timeline": 7.0, "list": 7.0, "counter": 5.0, "quote": 5.0, "map": 7.0, "bars": 6.0,
                   "outro": 6.0, "media": 4.0}
MOTIONS = ["zoomIn", "panLeft", "zoomOut", "panRight", "zoomIn", "panUp", "zoomOut", "panDown"]  # движение камеры по фото, по кругу
# порядковые слова: пункт списка появляется, когда диктор говорит «first… second…»
ORDINALS_EN = [
    ("first", "firstly", "one"), ("second", "secondly", "two"), ("third", "thirdly", "three"), ("fourth", "four"),
    ("fifth", "five"), ("sixth", "six"), ("seventh", "seven"),
]
# экранные подписи (канал англоязычный)
UI_TEXT = {"outroTitle": "Thanks for watching!", "cta": "Subscribe", "intro": "Intro",
           "news": "Archive footage", "amateur": "Amateur footage", "photo": "Photo", "video": "Video",
           "edited": "edited", "ai": "AI illustration", "recon": "AI reconstruction"}
# архивы, автора и источник которых пишем прямо в кадре (как в документальном кино)
MUSIC_LUFS = -16.0             # до этой громкости выравнивается каждый трек (audio.normalize_music)
MUSIC_UNDER_VOICE_DB = -13.0   # музыка под голосом — на 13 дБ тише голоса (STYLE.md, «Звук»; было −10, Nurlan после ep-test)
ARCHIVE_SOURCES = {"commons": "Wikimedia Commons", "openverse": "Openverse", "nasa": "NASA", "loc": "Library of Congress",
                   "newspapers": "Chronicling America", "europeana": "Europeana", "dvids": "DVIDS", "archive": "Internet Archive"}


def stems_of(text: str) -> list[str]:
    """Основы значимых слов фразы — чтобы найти момент, когда диктор их произносит."""
    out = []
    for tok in text.split():
        n = norm(tok)
        if n.isdigit() and len(n) >= 3:
            out.append(n)
        elif len(n) >= 4:
            out.append(n[: max(4, min(6, len(n) - 2))])
    return out


def find_word(words: list[Word], stems: list[str], after: int = 0) -> int | None:
    """Индекс первого слова (начиная с after), которое начинается с одной из основ."""
    for i in range(after, len(words)):
        n = words[i].norm
        for s in stems:
            if n.startswith(s) or (len(n) >= 4 and s.startswith(n)):
                return i
    return None


def find_ordinal(words: list[Word], k: int, after: int = 0) -> int | None:
    """Индекс слова «first/second/…» для k-го пункта списка."""
    if k >= len(ORDINALS_EN):
        return None
    forms = {norm(f) for f in ORDINALS_EN[k]}
    for i in range(after, len(words)):
        if words[i].norm in forms:
            return i
    return None


def sentences(words: list[Word]) -> list[list[Word]]:
    out, cur = [], []
    for w in words:
        cur.append(w)
        if STRONG_END.search(w.text):
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def text_of(words: list[Word]) -> str:
    return " ".join(w.text for w in words).strip()


def clean_phrase(s: str) -> str:
    s = s.strip().strip("—–-:;,. ").strip()
    return s[:1].upper() + s[1:] if s else s


# ───────────────────────── B. время и кадры ─────────────────────────
class Planner:
    def __init__(self, project: Path, settings: dict, media: list[dict], blocks: list[Block], words: list[Word],
                 voice_src: str | None, voice_end: float, music: list[dict], sfx: dict[str, str] | None):
        """project — рабочая папка эпизода (ep-N/06_montage)."""
        self.project = project
        self.s = settings
        # обрывки видео короче 3 с (бывают в архивах) в кадре крутятся по кругу и выглядят как повтор — не берём
        self.media = [m for m in media if not (m.get("type") == "video" and 0 < (m.get("duration") or 99) < 3)]
        self.blocks = blocks
        self.words = words
        self.voice_src = voice_src
        self.voice_end = voice_end
        self.music = music
        self.sfx_names = sfx
        self.pace = PACE.get(settings.get("pace", "calm"), PACE["calm"])
        self.scenes: list[dict] = []
        self.sfx: list[dict] = []
        self.warnings: list[str] = []
        self.motion_i = 0
        self.chapters: list[dict] = []
        self.offset = 0.0
        self.chapter_no = 0
        # «почерк» ролика: у каждого проекта свой порядок заставок глав, движений камеры, коллажей и переходов,
        # чтобы ролики канала не выглядели как один шаблон (важно для YouTube)
        self.seed = int(hashlib.md5(str(settings.get("styleSeed", project.parent.name)).encode()).hexdigest()[:8], 16)  # имя эпизода: ep-7
        self.motion_i = self.seed % len(MOTIONS)
        self.collage_i = self.seed % 3 - 1
        # что известно о найденных файлах (источник, автор, вид съёмки) — для подписей «Archive footage», «Photo: автор»
        from util import load_json
        self.found_files = {f["file"]: f for it in (load_json(project / "work" / "found.json", {}) or {}).values()
                            for f in it.get("files", []) if f.get("file")}
        self.word_by_idx = {w.idx: w for w in words}

    # ───────── тайминг блоков ─────────
    def time_blocks(self) -> list[tuple[Block, float, float]]:
        blocks = self.blocks
        # Пустые блоки в самом начале — играют до начала голоса (голос сдвигается)
        lead = []
        i = 0
        while i < len(blocks) and not blocks[i].words:
            lead.append(blocks[i])
            i += 1
        intro_len = sum(EMPTY_BLOCK_LEN.get(b.kind, 4.0) for b in lead)
        self.offset = intro_len + (0.3 if self.voice_src else 0.0)
        for w in self.words:
            w.start += self.offset
            w.end += self.offset

        timed: list[tuple[Block, float, float]] = []
        t = 0.0
        for b in lead:
            d = EMPTY_BLOCK_LEN.get(b.kind, 4.0)
            timed.append((b, t, t + d))
            t += d
        rest = blocks[i:]
        voiced = [b for b in rest if b.words]
        # Границы между озвученными блоками
        starts = {}
        for k, b in enumerate(voiced):
            first = b.words[0].start
            if k == 0:
                starts[id(b)] = t if timed else 0.0
                continue
            prev_end = voiced[k - 1].words[-1].end
            gap = max(0.0, first - prev_end)
            starts[id(b)] = first - min(0.3, gap * 0.6) if gap > 0 else first - 0.04
        last_end = (voiced[-1].words[-1].end if voiced else t) + float(self.s.get("tail", 2.0))
        # Раскладка, включая пустые блоки внутри (они «занимают» начало следующего озвученного)
        j = 0
        pending_empty: list[Block] = []
        trailing: list[Block] = []
        for b in rest:
            if not b.words:
                pending_empty.append(b)
                continue
            s = starts[id(b)]
            nxt = voiced[voiced.index(b) + 1] if voiced.index(b) + 1 < len(voiced) else None
            e = starts[id(nxt)] if nxt else last_end
            if pending_empty:
                avail = e - s
                share = min(sum(EMPTY_BLOCK_LEN.get(p.kind, 4.0) for p in pending_empty), avail * 0.45)
                each = share / len(pending_empty)
                for p in pending_empty:
                    timed.append((p, s, s + each))
                    s += each
                pending_empty = []
            timed.append((b, s, e))
            j += 1
        trailing = pending_empty
        t_end = last_end
        for p in trailing:
            d = EMPTY_BLOCK_LEN.get(p.kind, 5.0)
            timed.append((p, t_end, t_end + d))
            t_end += d
        self.total = max(t_end, last_end)
        return timed

    # ───────── распределение материалов ─────────
    def allocate_media(self, timed):
        explicit = {m for b, _, _ in timed for m in b.media}
        explicit |= {mk.args for b, _, _ in timed for mk in b.markers if mk.type == "background"}
        pool = [m for m in self.media if m["name"] not in explicit]
        auto = [(b, s, e) for b, s, e in timed if b.kind == "media" and not b.media]
        for b, s, e in auto:
            if b.find or b.ai:
                what = f"«{b.find}»" if b.find else f"сгенерированная картинка ai{b.ai[0]:02d}"
                self.warnings.append(f"Нет материала для сцены: {what} — будет текстовый кадр")
        mn, ideal, mx = self.pace
        need = [max(1, math.ceil((e - s) / mx)) for _, s, e in auto]
        A = len(pool)
        counts = need[:]
        if A >= sum(need):
            extra = A - sum(need)
            D = sum(e - s for _, s, e in auto) or 1
            caps = [max(n, int((e - s) // max(3.0, mn - 0.5))) for n, (_, s, e) in zip(need, auto)]
            # раздаём лишние материалы пропорционально длительности, не дробя кадры короче минимума
            while extra > 0:
                best, score = None, -1.0
                for k, (_, s, e) in enumerate(auto):
                    if counts[k] < caps[k]:
                        sc = (e - s) / D / (counts[k] + 1)
                        if sc > score:
                            best, score = k, sc
                if best is None:
                    break
                counts[best] += 1
                extra -= 1
            if extra > 0 and auto:
                self.warnings.append(f"Не использовано материалов: {extra} (озвучка короче, чем нужно для всех кадров)")
        elif A > 0:
            self.warnings.append(f"Материалов мало ({A} на {sum(need)} кадров) — кадры будут дольше, повторов не будет")
        elif auto and not self.media:
            self.warnings.append("В папке media нет картинок/видео — вместо кадров будет фирменный фон с текстом")
        assign = {}
        pi = 0
        for k, (b, s, e) in enumerate(auto):
            n_shots = counts[k]
            if A >= sum(need):
                items = pool[pi : pi + n_shots]
                pi += n_shots
            else:
                # мало материалов: каждый файл используется один раз, кадры просто длиннее
                share = max(1, round(A * (e - s) / max(1e-6, sum(e2 - s2 for _, s2, e2 in auto)))) if A else 0
                items = pool[pi : pi + share] if A else []
                pi = min(A, pi + share)
                n_shots = max(1, len(items))
            assign[id(b)] = (n_shots, items)
        byname = {m["name"]: m for m in self.media}
        for b, s, e in timed:
            if b.kind == "media" and b.media:
                items = _interleave([byname[n] for n in b.media if n in byname])
                n_shots = max(1, len(items))  # никаких повторов: сколько материалов — столько кадров (лишнее срежем при сборке)
                if items and (e - s) / len(items) > 12 and (e - s) / (len(items) + sum(1 for m in items if m["type"] == "image")) > 12:
                    what = b.find or (f"картинка ai{b.ai[0]:02d}" if b.ai else ", ".join(b.media))
                    self.warnings.append(f"Мало материала: «{what[:50]}» — {len(items)} кадр(а) на "
                                         f"{e - s:.0f} с. Добавьте картинки или видео в эту сцену")
                if len(items) > 1 and (e - s) / len(items) < mn * 0.85:
                    self.warnings.append(f"Сцена с {', '.join(b.media)} короткая ({e - s:.1f} с): каждый кадр всего "
                                         f"{(e - s) / len(items):.1f} с — для спокойного темпа лучше один файл или текст длиннее")
                assign[id(b)] = (n_shots, items)
        return assign

    COLLAGE_ROTATION = ["mosaic", "board", "split"]

    def collage_layout(self, b: Block, s: float, e: float, items: list[dict]) -> str | None:
        """Нужен ли коллаж: по метке [КОЛЛАЖ] или сам, когда в сцене много фото и каждое мелькало бы слишком быстро."""
        names = {"доска": "board", "board": "board", "полароид": "board", "сетка": "mosaic", "мозаика": "mosaic",
                 "mosaic": "mosaic", "grid": "mosaic", "сплит": "split", "split": "split", "панели": "split"}
        mk = next((m for m in b.markers if m.type == "collage"), None)
        if len(items) < 2:
            return None
        if mk:
            want = names.get((mk.args or "").strip().lower())
            if want:
                return want if len(items) >= 3 or want == "split" else "split"
        elif not self.s.get("collages", True):
            return None
        else:
            stills = [m for m in items if m["type"] == "image"]
            if len(items) < 3 or len(stills) < 2 or (e - s) / len(items) >= 4.8 or s - getattr(self, "last_collage", -999) < 40:
                return None
        if len(items) == 2:
            return "split"
        archive = sum(1 for m in items if (self.found_files.get(m["name"]) or {}).get("kind") in ("news", "document"))
        if archive >= 2:
            return "board"
        self.collage_i = getattr(self, "collage_i", -1) + 1
        return self.COLLAGE_ROTATION[self.collage_i % len(self.COLLAGE_ROTATION)]

    def badge_for(self, m: dict) -> dict | None:
        """Честная подпись к найденному кадру: «Archive footage · NASA», «Amateur footage», «Photo: автор / Wikimedia Commons».
        Свои кадры (05_footage) подписи не получают; сгенерированные — «AI illustration»."""
        ui = UI_TEXT
        if re.match(r"ai\d", m["name"].lower()) and self.s.get("aiBadges", True):
            # честная пометка сгенерированных картинок; реконструкции реальных событий — крупной плашкой
            if m["name"] in getattr(self, "_recon", set()):
                return {"label": ui["recon"]}
            return {"source": ui["ai"]}
        f = self.found_files.get(m["name"])
        if not f or self.s.get("sourceBadges", True) is False:
            return None
        if f.get("source") == "list":  # свои прямые ссылки (sources.txt): источник + «edited»
            who = f.get("author") or ARCHIVE_SOURCES.get(f.get("source"), "")
            credit = f"{ui['video' if m['type'] == 'video' else 'photo']}: {who} ({ui['edited']})"
            if f.get("label"):
                return {"label": f["label"], "source": " · ".join(x for x in (credit, f.get("note")) if x)}
            return {"source": credit + (f" · {f['note']}" if f.get("note") else "")}
        src = ARCHIVE_SOURCES.get(f.get("source"))
        author = re.sub(r"\s+", " ", str(f.get("author") or "")).strip()
        author = "" if not author or author.lower() in (src or "").lower() or len(author) > 40 else author
        credit = " / ".join(x for x in (author, src) if x)
        if f.get("kind") == "news":
            return {"label": ui["news"], "source": credit or src or ""}
        if f.get("kind") == "amateur":
            return {"label": ui["amateur"], "source": credit}
        if src:  # архивы и свободные лицензии — указываем автора прямо в кадре, как в документальном кино
            lic = {"by": "CC BY", "by-sa": "CC BY-SA"}.get(f.get("license"), "")
            return {"source": f"{ui['video' if m['type'] == 'video' else 'photo']}: {credit}{' · ' + lic if lic else ''}"}
        return None

    # ───────── деление блока на кадры ─────────
    def split_points(self, words: list[Word], s: float, e: float, n: int) -> list[float]:
        if n <= 1:
            return [s, e]
        mn = min(self.pace[0], (e - s) / n * 0.8)  # кадры одного блока примерно равны, без «мелькания»
        cands = []
        for k, w in enumerate(words[:-1]):
            nxt = words[k + 1]
            cut = nxt.start - min(0.25, max(0.0, nxt.start - w.end) * 0.6) if nxt.start > w.end else nxt.start - 0.03
            pen = 0.0 if STRONG_END.search(w.text) else (0.6 if WEAK_END.search(w.text) else 2.0)
            cands.append((cut, pen))
        cuts = [s]
        for j in range(1, n):
            target = s + (e - s) * j / n
            best, bscore = None, 1e9
            for cut, pen in cands:
                if cut - cuts[-1] < mn or e - cut < mn:
                    continue
                sc = abs(cut - target) + pen
                if sc < bscore:
                    best, bscore = cut, sc
            cuts.append(best if best is not None else max(target, cuts[-1] + mn))
        cuts.append(e)
        return sorted(set(round(c, 3) for c in cuts))

    def next_motion(self, m: dict | None) -> dict:
        if m and m["type"] == "video":
            return {"type": "zoomIn", "strength": 0.25}
        if m and m["aspect"] < 1.45:
            return {"type": "zoomIn", "strength": 0.6}
        if m and m["aspect"] > 2.0:
            self.motion_i += 1
            return {"type": "panLeft" if self.motion_i % 2 else "panRight", "strength": 1.4}
        mt = MOTIONS[self.motion_i % len(MOTIONS)]
        self.motion_i += 1
        return {"type": mt}

    # ───────── переходы ─────────
    def transition_for(self, prev_kind: str | None, kind: str, same_block: bool) -> dict:
        style = self.s.get("transitions", "soft")
        if style == "auto":
            style = ["soft", "cinematic", "dynamic"][self.seed % 3]
        if style == "cinematic" and prev_kind is not None and kind == "media" and prev_kind == "media":
            self.cine_i = getattr(self, "cine_i", 0) + 1
            if same_block:
                return {"type": "fade", "duration": 0.6}
            return [{"type": "fade", "duration": 1.0}, {"type": "blur", "duration": 0.8}, {"type": "dip", "duration": 0.9}][self.cine_i % 3]
        if prev_kind is None:
            return {"type": "fade", "duration": 1.2}

        if kind == "outro":
            return {"type": "dip", "duration": 1.2}

        if kind == "title":
            return {"type": "dip", "duration": 1.0}
        if kind != "media":
            return {"type": "zoom", "duration": 0.8} if style == "soft" else {"type": "push", "duration": 0.7, "direction": "left"}
        if prev_kind != "media":
            return {"type": "fade", "duration": 0.9}
        if same_block:
            if style == "dynamic":
                return {"type": "push", "duration": 0.6, "direction": "left"}
            return {"type": "fade", "duration": 0.7}
        return {"type": "fade", "duration": 1.0} if style == "soft" else {"type": "wipe", "duration": 0.8, "direction": "left"}

    # ───────────────────────── C. инфографика ─────────────────────────

    def infographic(self, b: Block, s: float, e: float) -> dict | None:
        """Данные для инфографики сцены: глава, таймлайн, список, счётчик, цитата, карта, диаграмма, финал.
        Пункты появляются («at»), когда диктор произносит соответствующее слово."""
        parts = split_args(b.args)
        words = b.words
        kind = b.kind
        if kind == "title":
            if not parts and words:
                parts = [clean_phrase(text_of(sentences(words)[0]))]
            d = {"title": parts[0] if parts else ""}
            if len(parts) > 1:
                d["subtitle"] = parts[1]
            if len(parts) > 2:
                d["kicker"] = parts[2]
            if b.raw_tag.lower().startswith(("глава", "chapter")):
                self.chapters.append({"start": s, "title": d["title"]})
                self.chapter_no += 1
                n = self.chapter_no
                word = self.s.get("chapterWord") or "Chapter"
                variants = self.s.get("chapterStyles") or _rotate(["number", "side", "tracking", "split"], self.seed)
                d["variant"] = variants[(n - 1) % len(variants)]
                d["number"] = n
                total = sum(1 for x in self.blocks if x.kind == "title" and x.raw_tag.lower().startswith(("глава", "chapter")))
                d["of"] = total
                d.setdefault("kicker", word if d["variant"] == "number" else f"{word} {n} / {total}")
            elif not self.chapter_no and not any(sc.get("kind") == "title" for sc in self.scenes):
                d["variant"] = "hero"
            return {"kind": "title", "data": d}

        if kind == "timeline":
            title = None
            if len(parts) > 2 and not re.search(r"\d", parts[0]) and not DASH_SPLIT.search(parts[0]):
                title = parts.pop(0)
            items, after = [], 0
            for p in parts:
                bits = [x.strip() for x in DASH_SPLIT.split(p, maxsplit=1) if x.strip()]
                if len(bits) == 2:
                    label, ttl = (bits[0], bits[1]) if re.search(r"\d", bits[0]) or not re.search(r"\d", bits[1]) else (bits[1], bits[0])
                else:
                    m = re.search(r"\d[\d\s]*(?:\s*(?:BC|AD|s\b))?", p)  # 1985, 1980s, 300 BC
                    if m:
                        label, ttl = m.group(0).strip(), (p[: m.start()] + p[m.end() :]).strip()
                    else:
                        label, ttl = p, ""
                it = {"label": label}
                if ttl:
                    it["title"] = clean_phrase(ttl)
                k = find_word(words, stems_of(ttl or label), after)
                if k is not None:
                    it["at"] = round(max(s + 0.4, words[k].start - 0.15), 3)
                    after = k + 1
                items.append(it)
            self._fix_times(items, s, e)
            return {"kind": "timeline", "data": {"items": items, **({"title": title} if title else {})}}

        if kind == "list":
            title = parts.pop(0) if parts else None
            items = []
            if parts:
                after = 0
                for idx, p in enumerate(parts):
                    bits = [x.strip() for x in DASH_SPLIT.split(p, maxsplit=1)]
                    it = {"text": clean_phrase(bits[0])}
                    if len(bits) > 1 and bits[1]:
                        it["detail"] = bits[1]
                    k = find_ordinal(words, idx, after)
                    if k is None:
                        k = find_word(words, stems_of(bits[0]), after)
                    if k is not None:
                        it["at"] = round(words[k].start - 0.1, 3)
                        after = k + 1
                    items.append(it)
            else:
                items = self._items_from_ordinals(words)
            if not items:
                return None
            self._fix_times(items, s, e)
            if title is None and words:
                title = clean_phrase(text_of(sentences(words)[0]))[:60]
            return {"kind": "list", "data": {"title": title, "items": items}}

        if kind == "counter":
            src = parts[0] if parts else b.args
            value, rest = parse_number(src)
            if value is None:
                value, rest = parse_number(text_of(words))
            if value is None:
                return None
            d = {"value": value}
            cur = re.match(r"\s*([$€£])", src)
            if cur:  # «$350» — знак валюты перед числом
                d["prefix"] = cur.group(1)
            if value != int(value):
                d["decimals"] = min(2, len(f"{value:.6g}".split(".")[1]) if "." in f"{value:.6g}" else 0)
                if re.search(r"\d,\d\d\b", src):
                    d["decimals"] = 2
            rest_words = rest.split()
            if len(parts) > 1:
                d["suffix"] = parts[1]
                if len(parts) > 2:
                    d["label"] = parts[2]
                elif rest:
                    d["label"] = rest
            elif rest_words:
                d["suffix"] = rest_words[0]
                if len(rest_words) > 1:
                    d["label"] = " ".join(rest_words[1:])
            d["at"] = round(s + 0.5, 3)
            return {"kind": "counter", "data": d}

        if kind == "quote":
            if parts:
                text = parts[0]
            else:
                full = text_of(words)
                m = re.search(r"[«\"“]([^»\"”]+)[»\"”]", full)
                text = m.group(1) if m else full
            d = {"text": text.strip()}
            if len(parts) > 1:
                d["author"] = parts[1]
            return {"kind": "quote", "data": d}

        if kind == "map":
            title = None
            route_part = None
            for p in parts:
                if re.search(r"[>→]", p):
                    route_part = p
                elif title is None:
                    title = p
            names = [x.strip() for x in re.split(r"\s*(?:>|→|->)\s*", route_part)] if route_part else []
            if not names:
                src = title or text_of(words)
                names = [tok for tok in re.findall(r"[A-Za-z\-]+", src) if lookup(tok) and len(tok) > 3]
                if title and names and len(parts) == 1:
                    title = None
            points, after = [], 0
            for nm in names:
                m = re.match(r"^(.+?)\(\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*\)$", nm)
                if m:
                    label, lat, lon = m.group(1).strip(), float(m.group(2)), float(m.group(3))
                else:
                    c = lookup(nm)
                    if not c:
                        self.warnings.append(f"Карта: не знаю, где «{nm}». Укажите координаты: {nm}(широта, долгота)")
                        continue
                    label, (lon, lat) = clean_phrase(nm), c
                pt = {"name": label, "lon": lon, "lat": lat}
                k = find_word(words, stems_of(nm), after)
                if k is not None:
                    pt["at"] = round(words[k].start - 0.1, 3)
                    after = k + 1
                points.append(pt)
            if len(points) < 1:
                return None
            self._fix_times(points, s, e)
            return {"kind": "map", "data": {"points": points, **({"title": title} if title else {})}}

        if kind == "bars":
            # [ДИАГРАММА: Заголовок | Тоннель = 51,8 → 108,3 | … | легенда=План / Итог | источник=…]
            # «A → B» — было/стало (план и факт): бледный столбик «было», яркий «стало»; «—» — части не было в плане
            title, source, legend = None, None, None
            items = []
            for p in parts:
                if "=" in p:
                    lab, val = p.split("=", 1)
                    key = lab.strip().lower()
                    if key in ("источник", "source"):
                        source = val.strip()
                        continue
                    if key in ("легенда", "legend"):
                        legend = [x.strip() for x in val.split("/")][:2]
                        continue
                    two = re.split(r"\s*(?:→|->|=>)\s*", val.strip())
                    if len(two) == 2:
                        v0, _ = parse_number(two[0])
                        v, _ = parse_number(two[1])
                        if v is not None:
                            it = {"label": lab.strip(), "value": v, "display": two[1].strip()}
                            if v0 is not None:
                                it["from"] = v0
                                it["fromDisplay"] = two[0].strip()
                            items.append(it)
                        continue
                    v, _ = parse_number(val)
                    if v is not None:
                        disp = val.strip()
                        disp = re.sub(r"(?<=\d)[\s\u00a0\u202f](?=\d{3}\b)", ",", disp)  # 29 457 → 29,457
                        items.append({"label": lab.strip(), "value": v, "display": disp})
                elif title is None:
                    title = p
            if not items:
                return None
            data = {"items": items, **({"title": title} if title else {})}
            if source:
                data["source"] = source
            if any("from" in it for it in items):
                data["legend"] = legend if legend and len(legend) == 2 else ["Original plan", "Final"]
            return {"kind": "bars", "data": data}

        if kind == "outro":
            q = parts[0] if parts else None
            if not q:
                qs = [text_of(x) for x in sentences(words) if text_of(x).endswith("?")]
                q = qs[-1] if qs else None
            d = {}
            if q:
                d["question"] = q
            ui = UI_TEXT
            d["cta"] = parts[1] if len(parts) > 1 else self.s.get("outroCta", ui["cta"])
            d["title"] = self.s.get("outroTitle", ui["outroTitle"])
            return {"kind": "outro", "data": d}
        return None

    def _items_from_ordinals(self, words: list[Word]) -> list[dict]:
        items, after = [], 0
        for k in range(len(ORDINALS_EN)):
            i = find_ordinal(words, k, after)
            if i is None:
                break
            sent = []
            for w in words[i + 1 :]:
                sent.append(w)
                if STRONG_END.search(w.text):
                    break
            txt = text_of(sent)
            main, _, detail = txt.partition(":")
            main = clean_phrase(main.rstrip("."))
            it = {"text": main[:48], "at": round(words[i].start - 0.1, 3)}
            if detail.strip():
                it["detail"] = detail.strip().rstrip(".")[:80]
            items.append(it)
            after = i + 1
        return items

    @staticmethod

    def _fix_times(items: list[dict], s: float, e: float) -> None:
        """Пункты без найденного времени — равномерно между соседями."""
        n = len(items)
        # найденные моменты должны идти по порядку и не слишком плотно — иначе считаем их ненадёжными
        prev = s + 0.3
        for i, it in enumerate(items):
            if "at" in it:
                if it["at"] < max(prev + 0.8, s + 0.6 + 0.9 * i) or it["at"] > e - min(2.5, (e - s) * 0.25):
                    del it["at"]
                else:
                    prev = it["at"]
        known = [(i, it["at"]) for i, it in enumerate(items) if "at" in it]
        hold = min(2.5, (e - s) * 0.25)  # последний пункт должен побыть на экране, а не мелькнуть в конце
        anchors = [(-1, s + 0.6)] + [k for k in known if k[1] <= e - hold] + [(n, e - hold)]
        for (i0, t0), (i1, t1) in zip(anchors, anchors[1:]):
            for i in range(i0 + 1, i1):
                items[i]["at"] = round(t0 + (t1 - t0) * (i - i0) / (i1 - i0), 3)
        for i in range(1, n):  # строго по порядку, с паузой между пунктами
            items[i]["at"] = round(max(items[i]["at"], items[i - 1]["at"] + 0.6), 3)
        if n:  # последний пункт должен успеть побыть на экране хотя бы ~1.2 с
            items[-1]["at"] = round(min(items[-1]["at"], e - min(2.5, (e - s) * 0.25)), 3)
            for i in range(n - 2, -1, -1):
                items[i]["at"] = round(min(items[i]["at"], items[i + 1]["at"] - 0.6), 3)

    # ───────────────────────── D. сборка плана ─────────────────────────
    @staticmethod
    def scene_key(b: Block) -> str:
        """Ключ сцены для решений по пустым сценам: запрос [НАЙТИ] или начало текста."""
        return (b.find or text_of(b.words)[:60] or b.raw_tag or "?").strip()

    def empty_scenes(self) -> list[dict]:
        """Сцены без единого кадра — до сборки плана, чтобы Nurlan решил, что с ними делать.
        Вызывать на свежем Planner (time_blocks сдвигает время слов)."""
        timed = self.time_blocks()
        assign = self.allocate_media(timed)
        out = []
        for b, s, e in timed:
            if b.kind == "media" and b.words and not assign.get(id(b), (0, []))[1]:
                out.append({"key": self.scene_key(b), "start": round(s, 1), "end": round(e, 1),
                            "text": text_of(b.words)[:160], "query": b.find or "", "choice": None})
        return out

    def build(self) -> dict:
        """План монтажа. Пустые сцены — по решению Nurlan (settings["emptyScenes"]: ключ сцены → card | nearby):
        card — текстовая карточка; nearby — деталь последнего кадра (тот же снимок крупнее, другая часть)."""
        if not self.music:
            raise SystemExit("Нет музыки: положите треки в ep-N/07_music — без музыки план не собирается (STYLE.md, «Звук»)")
        decisions = self.s.get("emptyScenes") or {}
        timed = self.time_blocks()
        self._recon = set().union(*[b.recon for b, _, _ in timed if getattr(b, "recon", None)]) if timed else set()
        assign = self.allocate_media(timed)
        last_image = None
        prev_kind = None
        sid = 0
        all_shots: list[tuple[dict, list[Word]]] = []
        for b, s, e in timed:
            if b.kind == "media":
                n_shots, items = assign.get(id(b), (1, []))
                if not items and b.words and decisions.get(self.scene_key(b)) == "nearby" and last_image:
                    near = next((m for m in self.media if m["src"] == last_image), None)
                    if near:
                        items, n_shots = [near], 1
                        b.__dict__["_nearby"] = True
                layout = self.collage_layout(b, s, e, items)
                if layout:  # документальный коллаж: несколько кадров на одном экране
                    cap = {"split": 3, "mosaic": 3, "board": 4}[layout]
                    items = items[:cap]
                    cuts = self.split_points(b.words, s, e, len(items))
                    sid += 1
                    scene = {"id": f"s{sid:02d}", "kind": "collage", "start": round(s, 3), "end": round(e, 3), "layout": layout,
                             "items": [], "captions": True}
                    for k, m in enumerate(items):
                        # кадры коллажа появляются сразу и равномерно, один за другим, без ожидания слов рассказчика
                        it = {"src": m["src"], "mediaType": m["type"], "at": round(s + 0.15 + k * 0.5, 3)}
                        if m["type"] == "video" and m.get("duration"):
                            it["duration"] = m["duration"]
                        badge = self.badge_for(m)
                        if badge:
                            it["badge"] = badge
                        scene["items"].append(it)
                    scene["transition"] = self.transition_for(prev_kind, "media", same_block=False)
                    prev_kind = "media"
                    self.scenes.append(scene)
                    all_shots.append((scene, b.words))
                    last_image = next((m["src"] for m in items if m["type"] == "image"), last_image)
                    self.last_collage = e
                    for mk in b.markers:
                        self.apply_marker(mk, b, s, e)
                    continue
                fit = max(1, int((e - s) // max(2.6, self.pace[0] * 0.85)))  # кадр не короче ~3 с — без «мелькания»
                if len(items) > fit:
                    items = items[:fit]
                    n_shots = len(items)
                # мало фото на длинный текст: после общего плана — «деталь» того же фото (крупнее, другая часть кадра),
                # как в документальном кино. Видео не повторяем.
                shots = [(m, bool(b.__dict__.get("_nearby"))) for m in items]  # nearby — сразу «деталь» прошлого кадра
                if items and (e - s) / len(items) > 15:
                    extra = min(sum(1 for m in items if m["type"] == "image"), int((e - s) // 11) - len(items))
                    if extra > 0:
                        shots = []
                        for m in items:
                            shots.append((m, False))
                            if extra > 0 and m["type"] == "image":
                                shots.append((m, True))
                                extra -= 1
                        n_shots = len(shots)
                cuts = self.split_points(b.words, s, e, n_shots)
                for k in range(len(cuts) - 1):
                    cs, ce = cuts[k], cuts[k + 1]
                    m, detail = shots[k] if k < len(shots) else (None, False)  # повторов нет: не хватило — текстовый кадр
                    sid += 1
                    shot_words = [w for w in b.words if cs - 0.05 <= w.start < ce]
                    if m is None:
                        txt = _card_text(shot_words)
                        scene = {"id": f"s{sid:02d}", "kind": "title", "start": round(cs, 3), "end": round(ce, 3),
                                 "data": {"title": "", "subtitle": txt, "variant": "quote"}}
                    else:
                        scene = {"id": f"s{sid:02d}", "kind": "media", "start": round(cs, 3), "end": round(ce, 3),
                                 "src": m["src"], "mediaType": m["type"], "motion": self.next_motion(m)}
                        if m["type"] == "image" and m["aspect"] < 1.45:
                            scene["fit"] = "blurfill"
                        if (m.get("width") or 9999) < 1100 and not re.match(r"ai\d", m["name"].lower()):
                            scene["fit"] = "inset"  # низкое разрешение — показываем в рамке, а не растягиваем на весь экран
                            scene["srcAspect"] = m["aspect"]
                            scene["motion"] = {"type": "zoomIn", "strength": 0.4}
                        badge = self.badge_for(m)
                        if badge:
                            scene["badge"] = badge
                        if detail:  # тот же снимок — деталь: крупнее и другая часть кадра
                            self.detail_i = getattr(self, "detail_i", self.seed) + 1
                            dx, dy = [(8, 3), (-8, 3), (7, -4), (-7, -4)][self.detail_i % 4]
                            z = 1.22 if scene.get("fit") == "inset" else 1.38
                            scene["fit"] = scene["fit"] if scene.get("fit") == "inset" else "cover"
                            scene["motion"] = {"type": "custom", "from": {"scale": z, "x": dx, "y": dy},
                                               "to": {"scale": z + 0.08, "x": dx * 0.6, "y": dy * 0.6}}
                        if m["type"] == "video" and m["name"] in b.media_start:
                            scene["videoStart"] = b.media_start[m["name"]]
                        if m["type"] == "video":
                            dur = ce - cs + 1.0
                            src_d = m.get("duration") or dur
                            scene["srcDuration"] = src_d
                            scene["videoRate"] = round(max(float(self.s.get("minVideoRate", 0.8)), min(1.0, src_d / dur)), 3)
                            # то же видео второй раз — продолжаем с того места, где остановились, а не с начала
                            used_v = self.__dict__.setdefault("video_used", {})
                            # длинные архивные ролики (Викисклад, госархивы) часто начинаются с титров и заставки — начинаем чуть позже
                            if ("videoStart" not in scene and m["name"] not in used_v and m["name"].startswith("find_")
                                    and src_d > 25):
                                scene["videoStart"] = round(min(12.0, src_d * 0.08), 2)
                            if "videoStart" not in scene and m["name"] in used_v:
                                nxt = used_v[m["name"]]
                                if nxt + 3 < src_d:
                                    scene["videoStart"] = round(nxt, 2)
                            st0 = float(scene.get("videoStart", 0) or 0)
                            if st0 and st0 + (ce - cs) * scene["videoRate"] > src_d:  # не хватает хвоста — чуть замедлим или начнём раньше
                                scene["videoRate"] = round(max(float(self.s.get("minVideoRate", 0.8)), min(scene["videoRate"], (src_d - st0) / max(0.1, ce - cs))), 3)
                                if st0 + (ce - cs) * scene["videoRate"] > src_d:
                                    scene["videoStart"] = round(max(0.0, src_d - (ce - cs) * scene["videoRate"] - 0.2), 2)
                            used_v[m["name"]] = scene.get("videoStart", 0) + (ce - cs) * scene["videoRate"]
                        else:
                            last_image = m["src"]
                    scene["transition"] = self.transition_for(prev_kind, scene["kind"], same_block=k > 0)
                    if scene["kind"] == "media":
                        scene["captions"] = True
                    elif len(text_of(shot_words)) <= len(scene["data"]["subtitle"]) + 3:
                        scene["captions"] = False  # вся фраза уже крупно на экране — субтитры не дублируем
                    prev_kind = scene["kind"]
                    self.scenes.append(scene)
                    all_shots.append((scene, shot_words))
            else:
                info = self.infographic(b, s, e)
                sid += 1
                if info is None:
                    self.warnings.append(f"Метка [{b.raw_tag}] не распознана — показываю как заголовок")
                    info = {"kind": "title", "data": {"title": clean_phrase(b.args)[:80] or " "}}
                scene = {"id": f"s{sid:02d}", "start": round(s, 3), "end": round(e, 3), **info}
                bg_src = last_image or next((m["src"] for m in self.media if m["type"] == "image"), None)
                byname = {m["name"]: m for m in self.media}
                bg_mk = next((mk for mk in b.markers if mk.type == "background"), None)
                if bg_mk and bg_mk.args in byname:
                    bm = byname[bg_mk.args]
                    scene["background"] = {"src": bm["src"], "mediaType": bm["type"], "dim": 0.6, "blur": 20}
                    if scene["kind"] == "map":
                        scene["background"]["dim"] = 0.75
                elif bg_src and scene["kind"] != "outro":
                    scene["background"] = {"src": bg_src, "dim": 0.62, "blur": 22}
                scene["captions"] = False
                scene["transition"] = self.transition_for(prev_kind, scene["kind"], same_block=False)
                prev_kind = scene["kind"]
                self.scenes.append(scene)
                all_shots.append((scene, b.words))
                if self.sfx_names and self.s.get("sfx", True) and scene is not self.scenes[0]:
                    self.sfx.append({"src": f"work/sfx/{self.sfx_names['whoosh']}", "at": round(max(0, s - 0.55), 3), "volume": 0.22})
                if self.sfx_names and self.s.get("sfx", True) and scene["kind"] in ("list", "timeline", "map"):
                    key = "items" if scene["kind"] != "map" else "points"
                    for it in scene["data"][key]:
                        self.sfx.append({"src": f"work/sfx/{self.sfx_names['tick']}", "at": it["at"], "volume": 0.18})
            # Встроенные метки (подписи, даты, акценты, переходы, звуки)
            for mk in b.markers:
                self.apply_marker(mk, b, s, e)
        for i, sc in enumerate(self.scenes):
            if sc.get("kind") == "title" and sc.get("data", {}).get("variant") in ("number", "side", "tracking", "split"):
                nxt = next((x for x in self.scenes[i + 1:] if x.get("kind") == "media"), None)
                if nxt:
                    sc["background"] = {"src": nxt["src"], "mediaType": nxt["mediaType"], "blur": 7, "dim": 0.58}
        if self.chapters and self.chapters[0]["start"] > 1.0:
            self.chapters.insert(0, {"start": 0.0, "title": self.s.get("introChapter", UI_TEXT["intro"])})
        return self.assemble()

    def apply_marker(self, mk, b: Block, s: float, e: float) -> None:
        w = next((x for x in self.words if x.idx >= mk.word_idx), None)
        at = w.start if w and w.start >= s - 0.01 else s
        at = round(at, 3)
        scene = next((sc for sc in self.scenes if sc["start"] - 0.01 <= at < sc["end"]), self.scenes[-1] if self.scenes else None)
        if scene is None:
            return
        parts = split_args(mk.args)
        if mk.type == "punch" and scene.get("kind") == "media":
            if at - scene["start"] < 1.0:
                return  # склейка сама по себе акцент — наезд в первую секунду кадра не нужен
            scene.setdefault("punches", []).append({"at": at, "scale": 1.12})
        elif mk.type == "transition":
            nxt = next((sc for sc in self.scenes if sc["start"] >= at - 0.01), None)
            name = (mk.args or "").strip().lower()
            ttype = TRANSITION_NAMES.get(name, "fade")
            if nxt:
                nxt["transition"] = {"type": ttype, "duration": 0.8, **({"direction": "left"} if ttype in ("push", "wipe") else {})}
        elif mk.type in ("lowerThird", "date", "label"):
            dur = {"lowerThird": 4.5, "date": 4.0, "label": 3.5}[mk.type]
            ov = {"type": mk.type, "start": at, "end": round(min(at + dur, scene["end"] + 2.0), 3)}
            if mk.type == "lowerThird":
                ov["title"] = parts[0] if parts else ""
                if len(parts) > 1:
                    ov["subtitle"] = parts[1]
            else:
                ov["text"] = parts[0] if parts else mk.args
            scene.setdefault("overlays", []).append(ov)
        elif mk.type == "sfx" and mk.args:
            self.sfx.append({"src": f"sfx/{mk.args.strip()}", "at": at, "volume": 0.4})

    # ───────── субтитры (вшитых нет — файл .srt для YouTube) ─────────
    def captions(self) -> list[dict]:
        maxc = int(self.s.get("captionLineChars", 38))
        cuts = sorted({sc["start"] for sc in self.scenes})
        cues, cur = [], []

        def flush():
            if not cur:
                return
            text = " ".join(w.text for w in cur)
            lines = _two_lines(text, maxc)
            cw = []
            for w in cur:
                for piece in w.text.split(" "):
                    cw.append({"text": piece, "start": round(w.start, 3), "end": round(w.end, 3)})
            cues.append({"start": round(cur[0].start - 0.05, 3), "end": round(cur[-1].end + 0.35, 3), "lines": lines, "words": cw})
            cur.clear()

        for w in self.words:
            if cur:
                chars = len(" ".join(x.text for x in cur))
                gap = w.start - cur[-1].end
                crosses_cut = any(cur[-1].end - 0.05 < c <= w.start + 0.05 for c in cuts)
                prev = cur[-1].text
                if (chars + len(w.text) + 1 > 2 * maxc or gap > 0.7 or crosses_cut
                        or (STRONG_END.search(prev) and chars > 18) or (WEAK_END.search(prev) and chars > maxc)):
                    flush()
            cur.append(w)
        flush()
        for a, b in zip(cues, cues[1:]):
            a["end"] = min(a["end"], b["start"])
        for c in cues:  # субтитр не переезжает через склейку
            last_word_end = c["words"][-1]["end"] if c.get("words") else c["end"]
            nxt_cut = next((x for x in cuts if last_word_end - 0.02 <= x < c["end"]), None)
            if nxt_cut is not None:
                c["end"] = round(nxt_cut, 3)
        for c in cues:
            if c["end"] - c["start"] < 0.9:
                c["end"] = c["start"] + 0.9
        for a, b in zip(cues, cues[1:]):
            a["end"] = min(a["end"], b["start"])
        return cues

    def assemble(self) -> dict:
        fps = int(self.s.get("fps", 30))
        plan = {
            "version": 1,
            "language": "en",
            "fps": fps,
            "width": int(self.s.get("width", 1920)),
            "height": int(self.s.get("height", 1080)),
            "duration": round(self.total, 3),
            "theme": self.s.get("theme", {}),
            "defaultTransition": {"type": "fade", "duration": 0.8},
            "scenes": self.scenes,
            "sfx": sorted(self.sfx, key=lambda x: x["at"]),
        }
        if self.voice_src:
            plan["voice"] = {"src": self.voice_src, "volume": 1.0, "offset": round(self.offset, 3)}
        if self.music:
            # Под голосом музыка на MUSIC_UNDER_VOICE_DB тише голоса (правило Nurlan, STYLE.md).
            # Треки заранее выровнены до MUSIC_LUFS (audio.normalize_music), громкость голоса — замер voiceLufs.
            voice_lufs = float(self.s.get("voiceLufs", MUSIC_LUFS + MUSIC_UNDER_VOICE_DB))
            duck_vol = round(min(1.0, 10 ** ((voice_lufs + MUSIC_UNDER_VOICE_DB - MUSIC_LUFS) / 20)), 4)
            open_vol = float(self.s.get("musicOpenVolume", 0.75))
            # в паузах между тактами — плавно громче (соотношение AutoEdit 0.3 / 0.1), но не громче заставки
            pause_vol = round(max(duck_vol, min(duck_vol * 3, open_vol)), 4)
            duck = speech_intervals([{"start": w.start, "end": w.end} for w in self.words]) if self.voice_src else []
            open_iv = []  # заставка до голоса и концовка после него — музыка громче
            if duck:
                if duck[0][0] > 1.5:
                    open_iv.append([0.0, round(duck[0][0] - 0.3, 3)])
                if self.total - duck[-1][1] > 1.5:
                    open_iv.append([round(duck[-1][1] + 0.5, 3), round(self.total, 3)])
            # Треки идут по порядку имён. Если музыки меньше, чем длится ролик, список повторяется по кругу,
            # и соседние куски перекрываются плавным наплывом (XF с), без «щелчка» на стыке.
            XF = 4.0
            usable = [m for m in self.music if (m.get("duration") or 0) > XF * 3]
            tracks = []
            for t0, t1, pool in self._music_segments(usable, XF):
                seq, acc, k = [], 0.0, 0
                while pool and acc < t1 - t0 and k < 200:
                    m = pool[k % len(pool)]
                    seq.append(m)
                    acc += m["duration"] - (XF if k else 0)
                    k += 1
                t = t0
                for k, m in enumerate(seq):
                    end = min(t1, t + m["duration"])
                    last = end >= t1 or k == len(seq) - 1
                    if last:
                        end = t1
                    tracks.append({"src": m["src"], "start": round(t, 3), "end": round(end, 3),
                                   "volume": pause_vol, "duckVolume": duck_vol,
                                   "fadeIn": 1.5 if not tracks else XF,
                                   "fadeOut": 3.0 if end >= self.total - 0.01 else XF, "duck": duck,
                                   "open": open_iv, "openVolume": open_vol})
                    t = end - XF
                    if last:
                        break
            plan["music"] = tracks
        plan["captions"] = {"enabled": bool(self.s.get("captions", True)), "cues": self.captions()}
        if self.s.get("captionHighlight"):
            plan["theme"] = {**plan["theme"], "captionHighlight": self.s.get("captionHighlightColor", "#E6AE5C")}
        plan["meta"] = {"chapters": self.chapters, "warnings": self.warnings, "voiceOffset": round(self.offset, 3)}
        return plan


    def _music_segments(self, usable: list[dict], xf: float) -> list[tuple[float, float, list[dict]]]:
        """Музыка по главам (решение Nurlan, EP-08): 06_montage/music_plan.json —
        {"segments": [{"at": "start", "tracks": ["60-65-dk-tension-07"]},
                      {"at": "chapter:The City Under the Ice", "tracks": [...]},
                      {"at": "text:Oh, and one more thing", "tracks": [...]}]}.
        Смена трека — чуть раньше начала главы / фразы, в паузе между тактами. Без файла — все треки по порядку имён."""
        from util import load_json
        plan = load_json(self.project / "music_plan.json", None)
        if not plan or not plan.get("segments"):
            return [(0.0, self.total, usable)]
        by_stem = {Path(m["src"]).stem.lower(): m for m in usable}
        marks = []
        for seg in plan["segments"]:
            at = str(seg.get("at", "start"))
            if at == "start":
                t = 0.0
            elif at.startswith("chapter:"):
                ch = next((c for c in self.chapters if c["title"].strip().lower() == at[8:].strip().lower()), None)
                t = ch["start"] - 1.0 if ch else None
            elif at.startswith("text:"):
                target = [norm(x) for x in at[5:].split() if norm(x)]
                ws = [w.norm for w in self.words]
                i = next((i for i in range(len(ws) - len(target) + 1) if ws[i:i + len(target)] == target), None)
                t = self.words[i].start - 2.0 if i is not None else None
            else:
                t = None
            pool = [by_stem[s.lower()] for s in seg.get("tracks", []) if s.lower() in by_stem]
            if t is None or not pool:
                self.warnings.append(f"music_plan: не найдено «{at}» или его треки — сегмент пропущен")
                continue
            marks.append((max(0.0, t), pool))
        marks.sort(key=lambda x: x[0])
        if not marks:
            return [(0.0, self.total, usable)]
        if marks[0][0] > 0:
            marks[0] = (0.0, marks[0][1])
        out = []
        for i, (t0, pool) in enumerate(marks):
            t1 = marks[i + 1][0] + xf if i + 1 < len(marks) else self.total  # наплыв на стыке глав
            out.append((t0, min(t1, self.total), pool))
        return out


# ───────────────────────── E. помощники ─────────────────────────
def _rotate(items: list, seed: int) -> list:
    """Детерминированная перестановка по «почерку» проекта."""
    import random
    out = items[:]
    random.Random(seed).shuffle(out)
    return out


def _interleave(items: list[dict]) -> list[dict]:
    """Видео и фото вперемешку — так сцена живее. Первым идёт то, что стоит первым в сценарии."""
    vids = [m for m in items if m.get("type") == "video"]
    pics = [m for m in items if m.get("type") != "video"]
    if not vids or not pics:
        return items
    first, second = (vids, pics) if items[0].get("type") == "video" else (pics, vids)
    out = []
    while first or second:
        if first:
            out.append(first.pop(0))
        if second:
            out.append(second.pop(0))
    return out


def _card_text(words: list[Word], limit: int = 210) -> str:
    """Текст для карточки без материала: целые предложения, без обрезки посреди слова."""
    full = clean_phrase(text_of(words))
    if len(full) <= limit:
        return full
    out = ""
    for sent in sentences(words):
        cand = (out + " " + text_of(sent)).strip()
        if len(cand) > limit and out:
            break
        out = cand
    if len(out) > limit:  # одно очень длинное предложение — режем по слову
        cut = out[:limit].rsplit(" ", 1)[0].rstrip(",;:—–- ")
        out = cut + "…"
    return clean_phrase(out) if not out.endswith("…") else out[:1].upper() + out[1:]


def _two_lines(text: str, maxc: int) -> list[str]:
    if len(text) <= maxc:
        return [text]
    words = text.split(" ")
    best, bscore = None, 1e9
    for i in range(1, len(words)):
        a, b = " ".join(words[:i]), " ".join(words[i:])
        score = abs(len(a) - len(b)) + (0 if re.search(r"[,.;:—–!?]$", words[i - 1]) else 6)
        if len(a) <= maxc + 4 and len(b) <= maxc + 4 and score < bscore:
            best, bscore = [a, b], score
    return best or [text]
