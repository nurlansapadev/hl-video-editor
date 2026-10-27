"""`ve.py fill ep-N` — сразу после find: пустые шоты с образцом → ReGen → в сценарий, без остановок на Nurlan.

1) Берёт шоты из 06_montage/work/refs.json (образцы, которые положил find: закрытые права, DuckDuckGo, Tavily),
   где свободных кадров не хватило (по found.json).
2) Дописывает их в 06_montage/output/ep-N-shots.json: текст диктора, запрос, эпоха, место, kind «любое»
   (фамилии людей с face_policy archive_only — нейтрально, как shots_from_script.py; иначе ReGen пропустит шот).
3) ReGen только по этим шотам (image_regenerator.py: правдоподобие ≥ 7, иначе одна перегенерация).
4) Шот был совсем пустым и ReGen принят (≥ 7) → в script.txt [НАЙТИ: …] меняется на [СЦЕНА: 14-1-rg],
   исходный запрос остаётся строкой «# найти было: …». Частично закрытые и с низкой оценкой — списком на просмотр.
5) Лист новых кадров — work/fill_sheet.jpg; итоги — work/fill.json; расход картинок по эпизоду — с предупреждением
   от $5 (решение Nurlan, 2026-10-27: лимитов нет, ~$2 обычно, $3 нормально).
Что осталось пустым — дальше в Gen, как раньше (шаг 7 «Порядка»).
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from util import CHARACTERS_DIR, EDIT_DIR, GENERATED_DIR, load_json, log, save_json

WARN_SPEND = 5.0  # $ за картинки на эпизод — предупредить (не останавливаться)
_FIND_TAG = re.compile(r"\[\s*(?:найти|поиск|find)\s*[:：]\s*([^\]]+)\]", re.I)


def episode_spend(ep: Path) -> float:
    """Сколько потрачено на картинки эпизода (Gen + ReGen + ReGravure — общий журнал work/regen.json)."""
    journal = load_json(ep / EDIT_DIR / "work" / "regen.json", []) or []
    return sum(float(x.get("cost_analysis", 0) or 0) + float(x.get("cost_image", 0) or 0) for x in journal)


def _bind(script: str, shot: int, names: list[str]) -> tuple[str, bool]:
    """В блоке «# shot N» первую метку [НАЙТИ: …] → [СЦЕНА: names]; запрос — строкой «# найти было: …»."""
    lines = script.split("\n")
    start = next((i for i, ln in enumerate(lines) if re.match(rf"\s*#\s*shot\s+{shot}\s*$", ln)), None)
    if start is None:
        return script, False
    for i in range(start + 1, len(lines)):
        if re.match(r"\s*#\s*shot\s+\d+", lines[i]):
            break
        m = _FIND_TAG.search(lines[i])
        if m:
            lines[i] = lines[i][:m.start()] + f"[СЦЕНА: {', '.join(names)}]" + lines[i][m.end():]
            lines.insert(i, f"# найти было: {m.group(1).strip()}")
            return "\n".join(lines), True
    return script, False


def _sheet(items: list[tuple[Path, str]], out: Path) -> None:
    """Лист новых кадров ReGen с подписями «шот · оценка» — посмотреть глазами за раз."""
    from PIL import Image, ImageDraw
    if not items:
        return
    w, h, cols = 480, 270, 4
    rows = (len(items) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * w, rows * (h + 24)), "white")
    draw = ImageDraw.Draw(sheet)
    for k, (path, label) in enumerate(items):
        x, y = (k % cols) * w, (k // cols) * (h + 24)
        try:
            im = Image.open(path).convert("RGB")
            im.thumbnail((w, h))
            sheet.paste(im, (x + (w - im.width) // 2, y))
        except Exception:  # noqa: BLE001
            pass
        draw.text((x + 6, y + h + 4), label, fill="black")
    sheet.save(out, quality=85)


def run(ep: Path) -> None:
    from finder import find_requests
    from image_regenerator import REF_EXT
    from image_regenerator import run as regen
    from shots_from_script import archive_only_surnames, neutral

    montage, work = ep / EDIT_DIR, ep / EDIT_DIR / "work"
    script_path = montage / "script.txt"
    if not script_path.exists():
        raise SystemExit(f"Нет {script_path}")
    refs = load_json(work / "refs.json", {}) or {}
    found = load_json(work / "found.json", {}) or {}
    script = script_path.read_text(encoding="utf-8")
    reqs = {r["slug"]: r for r in find_requests(script, auto_broll=False)}
    cast = load_json(ep / CHARACTERS_DIR / "cast.json", {}) or {}
    surnames = archive_only_surnames(cast)
    ctx = load_json(montage / "context.json", {}) or {}  # паспорт эпизода — эпоха, если в cast.json её нет
    era = (cast.get("era") or ctx.get("era") or "").split("(")[0].strip()

    targets = []  # (шот, запрос, сколько нужно, сколько свободных нашлось)
    for slug, it in refs.items():
        r, shot = reqs.get(slug), it.get("shot")
        if not r or shot is None:
            continue  # запрос из сценария убран или уже переделан в [СЦЕНА]
        got = len((found.get(slug) or {}).get("files", []))
        if got >= r["count"]:
            continue
        if not any(p.suffix.lower() in REF_EXT for p in (montage / "refs").glob(f"s_{shot}_*")):
            continue
        targets.append((shot, r, got))
    if not targets:
        log("▶ fill: шотов с образцами без свободных кадров нет — дальше Gen для пустых, как обычно")
        return
    log(f"▶ fill {ep.name}: {len(targets)} шотов с образцами → ReGen → сценарий")

    # 2) задания шотов для ReGen
    shots_path = montage / "output" / f"{ep.name}-shots.json"
    shots = {s["shot_no"]: s for s in (load_json(shots_path, []) or [])}
    for shot, r, _ in targets:
        s = shots.get(shot) or {"shot_no": shot, "expected": "", "day_time": ""}
        scene = re.split(r"\s*#\s*shot\s+\d+", r["scene"])[0].strip()  # текст до следующего шота, без комментариев
        s.update({"scenario_text": neutral(scene, surnames), "query": neutral(r["query"], surnames),
                  "epoch": r.get("era") or s.get("epoch") or era, "place": s.get("place") or r.get("region") or ""})
        if str(s.get("kind", "")).strip().lower() in ("", "видео", "video"):
            s["kind"] = "любое"  # ReGen видео-шоты пропускает; картинка по образцу лучше пустоты
        shots[shot] = s
    shots_path.parent.mkdir(parents=True, exist_ok=True)
    save_json(shots_path, sorted(shots.values(), key=lambda s: s["shot_no"]))

    # 3) ReGen только по этим шотам
    regen(ep, {t[0] for t in targets})

    # 4) результаты → сценарий
    journal = load_json(work / "regen.json", []) or []
    last = {x.get("out"): x for x in journal if x.get("out")}  # последняя запись по каждому файлу
    out_dir = ep / GENERATED_DIR
    bound, review, none, sheet = [], [], [], []
    for shot, r, got in targets:
        outs = sorted(out_dir.glob(f"{shot}-*-rg.png"))
        good = []
        for p in outs:
            e = last.get(p.name) or {}
            score = e.get("score")
            # подпись латиницей: стандартный шрифт PIL не знает кириллицы
            sheet.append((p, f"shot {shot} | {p.stem}" + (f" | {score:g}/10" if score is not None else "")))
            if e.get("status") in (None, "ok"):  # без записи — файл был раньше и уже просмотрен
                good.append(p.stem)
        if not outs:
            none.append({"shot": shot, "query": r["query"]})
        elif got == 0 and good:
            script, ok = _bind(script, shot, good)
            (bound if ok else review).append({"shot": shot, "files": good, "query": r["query"],
                                              **({} if ok else {"why": "метка [НАЙТИ] не найдена в блоке шота"})})
        else:
            review.append({"shot": shot, "files": [p.stem for p in outs], "query": r["query"],
                           "why": "часть свободных кадров уже есть — добавить ReGen рядом?" if got
                           else "оценка правдоподобия ниже 7 — посмотреть"})
    script_path.write_text(script, encoding="utf-8")
    _sheet(sheet, work / "fill_sheet.jpg")
    spend = episode_spend(ep)
    save_json(work / "fill.json", {"date": datetime.now().isoformat(timespec="seconds"), "bound": bound,
                                   "review": review, "no_result": none, "episode_spend": round(spend, 2)})
    log(f"✔ fill: в сценарий вписано {len(bound)} шотов"
        + (f": {', '.join(str(b['shot']) for b in bound)}" if bound else "")
        + f"; на просмотр {len(review)}; без результата {len(none)}. Лист: {work / 'fill_sheet.jpg'}")
    for x in review:
        log(f"  ? шот {x['shot']}: {x['why']} ({', '.join(x['files'])})")
    for x in none:
        log(f"  · шот {x['shot']}: ReGen не дал кадра (пропуск или ошибка — см. regen.json) → Gen")
    log(f"  Картинки эпизода всего: ${spend:.2f}"
        + (f"  ⚠ больше ${WARN_SPEND:.0f} — сказать Nurlan" if spend >= WARN_SPEND else ""))
