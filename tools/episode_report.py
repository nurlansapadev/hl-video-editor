"""Отчёт по эпизоду (с EP-15, Nurlan): время работы VE по шагам и деньги — OpenAI, Gemini, кредиты ElevenLabs.

  .venv/Scripts/python.exe tools/ve.py report ep-15   → 06_montage/output/ep-15_report.md (+ строка в data/episode_reports.jsonl)

Источники: work/usage.jsonl (время каждой команды ve.py + проверка кадров, описания своих кадров, подбор музыки),
work/regen.json (картинки Gen / ReGen / ReGravure, OpenAI и Gemini), data/find_history.jsonl (минуты поиска — для
эпизодов до журнала времени), 01_vo/script_tagged.txt (кредиты ElevenLabs ≈ знаки, 1 к 1 по EP-09…14).
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from util import EDIT_DIR, ROOT, VO_DIR, load_json, log

VISION_CALL_USD = 0.0015  # оценка одной проверки пачки превью gpt-4.1-mini — для эпизодов без usage.jsonl
STEP_RU = {"prepare": "подготовка", "passport": "паспорт", "refs": "портреты (поиск)", "regravure": "гравюры",
           "gen": "Gen", "regen": "ReGen", "index": "свои кадры (index)", "find": "поиск кадров", "fill": "fill (ReGen образцов)",
           "analyze": "распознавание озвучки", "empty": "пустые сцены", "music_pick": "подбор музыки", "plan": "план",
           "render": "рендер", "check": "контрольный лист", "shotrefs": "образцы шотов", "prompts": "промты", "inputs": "проверка входов"}


def fmt(secs: float) -> str:
    secs = int(round(secs))
    h, m, s = secs // 3600, secs % 3600 // 60, secs % 60
    return f"{h} ч {m:02d} мин" if h else f"{m} мин {s:02d} с" if m else f"{s} с"


def _lines(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return out


def collect(ep: Path) -> dict:
    work = ep / EDIT_DIR / "work"
    usage = _lines(work / "usage.jsonl")
    regen = load_json(work / "regen.json", []) or []
    steps: dict[str, dict] = defaultdict(lambda: {"runs": 0, "secs": 0.0, "fails": 0})
    money: dict[tuple[str, str], dict] = defaultdict(lambda: {"calls": 0, "usd": 0.0})
    fails: dict[str, int] = defaultdict(int)  # сбои OpenAI без ответа — деньги неизвестны (могли списать)
    dates = []
    for u in usage:
        st = steps[u["step"]]
        st["runs"] += 1
        st["secs"] += u.get("secs", 0)
        st["fails"] += 0 if u.get("ok", True) else 1
        dates.append(u["date"])
        for c in u.get("costs", []):
            m = money[(c["provider"], c["what"])]
            m["calls"] += c["calls"]
            m["usd"] += c["usd"]
    for r in regen:
        tool = r.get("tool") or "regen"  # до EP-15 ReGen не писал tool
        prov = "Gemini" if tool.endswith("-gemini") else "OpenAI"
        name = {"gen": "картинки Gen", "regen": "картинки ReGen", "regravure": "гравюры ReGravure"}.get(tool.replace("-gemini", ""),
                                                                                                    f"картинки {tool}")
        if r.get("fallback_for"):
            name += " (запасной, сбой OpenAI)"
        m = money[(prov, name)]
        m["calls"] += max(1, len(r.get("attempts") or [])) if r.get("status") not in ("dry",) else 0
        m["usd"] += (r.get("cost_analysis") or 0) + (r.get("cost_image") or 0)
        if r.get("date"):
            dates.append(r["date"])
        if r.get("status") == "error" and prov == "OpenAI":
            fails[name] += 1
    est = False
    if "find" not in steps:  # эпизоды до журнала времени — минуты и проверки из журнала поиска
        for f in _lines(ROOT / "data" / "find_history.jsonl"):
            if f.get("episode") == ep.name:
                st = steps["find"]
                st["runs"] += 1
                st["secs"] += f.get("minutes", 0) * 60
                money[("OpenAI", "проверка кадров (оценка)")]["calls"] += f.get("vision_calls", 0)
                money[("OpenAI", "проверка кадров (оценка)")]["usd"] += f.get("vision_calls", 0) * VISION_CALL_USD
                est = True
    tagged = ep / VO_DIR / "script_tagged.txt"
    eleven = 0
    if tagged.exists():
        text = re.sub(r"^=== .* ===$", "", tagged.read_text(encoding="utf-8"), flags=re.M)
        eleven = len("\n\n".join(p.strip() for p in text.split("\n\n") if p.strip()))
    return {"steps": dict(steps), "money": {f"{p}|{w}": v for (p, w), v in money.items()}, "dates": sorted(dates),
            "eleven_credits": eleven, "no_timing": not usage, "estimated": est, "fails": dict(fails)}


def report(ep: Path) -> None:
    d = collect(ep)
    steps, money = d["steps"], d["money"]
    by_prov = defaultdict(float)
    for k, v in money.items():
        by_prov[k.split("|")[0]] += v["usd"]
    total_usd = sum(by_prov.values())
    work_secs = sum(s["secs"] for s in steps.values())
    span = ""
    if d["dates"]:
        a, b = (datetime.fromisoformat(d["dates"][0].replace(" ", "T")), datetime.fromisoformat(d["dates"][-1].replace(" ", "T")))
        span = f"{a:%d.%m %H:%M} → {b:%d.%m %H:%M} ({fmt((b - a).total_seconds())} по часам)"
    L = [f"# Отчёт VE · {ep.name}", "",
         f"**Деньги: ${total_usd:.2f}** (OpenAI ${by_prov['OpenAI']:.2f} · Gemini ${by_prov['Gemini']:.2f})"
         + " · ElevenLabs ≈ " + f"{d['eleven_credits']:,}".replace(",", " ") + " кредитов",
         f"**Время работы программы: {fmt(work_secs)}**" + (f" · от первой до последней команды: {span}" if span else ""), ""]
    if d["no_timing"]:
        L += ["> Журнала времени `work/usage.jsonl` у эпизода нет (он ведётся с EP-15): время — только поиск по журналу поиска,"
              " проверка кадров — оценкой по числу проверок.", ""]
    L += ["## Время по шагам", "", "| Шаг | Запусков | Время |", "|---|---|---|"]
    for name, s in sorted(steps.items(), key=lambda x: -x[1]["secs"]):
        fails = f" (сбоев {s['fails']})" if s["fails"] else ""
        L.append(f"| {STEP_RU.get(name, name)} | {s['runs']}{fails} | {fmt(s['secs'])} |")
    L += ["", "## Деньги", "", "| Сервис | Что | Запросов / картинок | $ |", "|---|---|---|---|"]
    for k, v in sorted(money.items(), key=lambda x: (x[0].split("|")[0], -x[1]["usd"])):
        prov, what = k.split("|", 1)
        if v["usd"] or v["calls"]:
            L.append(f"| {prov} | {what} | {v['calls']} | {v['usd']:.2f} |")
    L.append(f"| **Итого** | | | **{total_usd:.2f}** |")
    eleven = f"{d['eleven_credits']:,}".replace(",", " ")
    L += ["", f"ElevenLabs: ≈ {eleven} кредитов (знаки размеченной озвучки, 1 кредит = 1 знак) — по подписке, в $ не входит."]
    if d["fails"]:
        L.append("Сбои OpenAI без ответа (таймаут, 5xx, обрыв): " + ", ".join(f"{k} — {v}" for k, v in d["fails"].items())
                 + ". Их стоимость неизвестна: OpenAI мог списать деньги, в сумму они не входят.")
    # сравнение с прошлыми эпизодами
    hist_path = ROOT / "data" / "episode_reports.jsonl"
    hist = [h for h in _lines(hist_path) if h.get("episode") != ep.name]
    row = {"episode": ep.name, "date": datetime.now().isoformat(timespec="seconds"), "usd": round(total_usd, 2),
           "openai": round(by_prov["OpenAI"], 2), "gemini": round(by_prov["Gemini"], 2), "work_min": round(work_secs / 60),
           "find_min": round(steps.get("find", {}).get("secs", 0) / 60), "render_min": round(steps.get("render", {}).get("secs", 0) / 60),
           "eleven": d["eleven_credits"]}
    hist.append(row)
    hist.sort(key=lambda h: int(re.sub(r"\D", "", h["episode"]) or 0))
    hist_path.write_text("".join(json.dumps(h, ensure_ascii=False) + "\n" for h in hist), encoding="utf-8")
    if len(hist) > 1:
        L += ["", "## По эпизодам", "", "| Эпизод | $ всего | OpenAI | Gemini | Работа VE | Поиск | Рендер | ElevenLabs |",
              "|---|---|---|---|---|---|---|---|"]
        for h in hist[-6:]:
            L.append(f"| {h['episode']} | {h['usd']:.2f} | {h['openai']:.2f} | {h['gemini']:.2f} | {h['work_min']} мин | "
                     f"{h['find_min']} мин | {h['render_min']} мин | {h['eleven']:,} |".replace(",", " "))
    out = ep / EDIT_DIR / "output" / f"{ep.name}_report.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    log("\n".join(L))
    log(f"\n✔ {out}")
