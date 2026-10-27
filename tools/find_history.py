"""Журнал поиска по всем эпизодам — для самоанализа и улучшения поиска.

  data/find_history.jsonl  — одна строка на запуск find: эпизод, время, итоги по шотам, таблица по источникам
  data/find_requests.jsonl — одна строка на каждый запрос: что искали, какой вариант запроса сработал,
                             какой источник дал кадр, почему шот остался пустым

Пишет finder.py в конце поиска; читает `ve.py findstats` (таблица по эпизодам и подсказки, что улучшить).
"""
from __future__ import annotations

import json
import time

from util import ROOT, log

HISTORY = ROOT / "data" / "find_history.jsonl"
REQUESTS = ROOT / "data" / "find_requests.jsonl"


def _append(path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _read(path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return out


def record(episode: str, secs: float, asked: int, skipped: int, by_source: dict, requests: list[dict],
           vision_calls: int) -> None:
    """Итоги одного запуска find → журнал. requests — итоги по каждому запросу (см. finder.run_finder)."""
    if not asked:
        return
    date = time.strftime("%Y-%m-%d %H:%M")
    need = [q for q in requests if not q.get("auto")]
    run = {"date": date, "episode": episode, "minutes": round(secs / 60, 1), "asked": asked, "skipped": skipped,
           "auto_video": sum(1 for q in requests if q.get("auto")),
           "full": sum(1 for q in need if q["got"] >= q["need"]),
           "partial": sum(1 for q in need if 0 < q["got"] < q["need"]),
           "empty": sum(1 for q in need if q["got"] == 0),
           "with_ref": sum(1 for q in need if q.get("refs")),
           "vision_calls": vision_calls,
           "sources": {s: {k: round(v, 1) if k == "secs" else int(v) for k, v in row.items()}
                       for s, row in by_source.items()}}
    _append(HISTORY, [run])
    _append(REQUESTS, [{"date": date, "episode": episode, **q} for q in requests])
    log(f"  Журнал поиска: {HISTORY.name} (+1 запуск), {REQUESTS.name} (+{len(requests)} запросов)")


def stats(last: int = 10) -> None:
    """`ve.py findstats`: последние запуски по эпизодам, вклад источников, подсказки для улучшения."""
    runs = _read(HISTORY)[-last:]
    if not runs:
        log("Журнал поиска пуст — появится после первого find с этой версией.")
        return
    log(f"Последние запуски поиска ({len(runs)}):")
    log(f"  {'дата':<17}{'эпизод':<18}{'мин':>6}{'запр':>6}{'полно':>7}{'частич':>7}{'пусто':>7}{'образец':>8}{'глаза':>7}")
    for r in runs:
        log(f"  {r['date']:<17}{r['episode']:<18}{r['minutes']:>6}{r['asked']:>6}{r['full']:>7}{r['partial']:>7}"
            f"{r['empty']:>7}{r['with_ref']:>8}{r['vision_calls']:>7}")
    total: dict[str, dict] = {}
    for r in runs:
        for s, row in r["sources"].items():
            t = total.setdefault(s, {"runs": 0, "calls": 0, "saved": 0, "refs": 0, "blocked": 0, "errors": 0, "secs": 0.0,
                                     "blocked_runs": 0})
            t["runs"] += 1
            t["blocked_runs"] += 1 if row.get("blocked") else 0
            for k in ("calls", "saved", "refs", "blocked", "errors", "secs"):
                t[k] += row.get(k, 0)
    log("\nИсточники за эти запуски (скачано в ролик / образцов для ReGen):")
    log(f"  {'источник':<12}{'запусков':>9}{'запросов':>9}{'скачано':>9}{'образцов':>9}{'блок':>6}{'ошибок':>7}{'мин':>6}")
    for s, t in sorted(total.items(), key=lambda x: -(x[1]["saved"] + x[1]["refs"])):
        log(f"  {s:<12}{t['runs']:>9}{t['calls']:>9}{t['saved']:>9}{t['refs']:>9}{t['blocked']:>6}{t['errors']:>7}"
            f"{t['secs'] / 60:>6.1f}")
    # подсказки — не решения: решает Nurlan
    hints = []
    for s, t in total.items():
        if t["runs"] >= 3 and t["calls"] and not (t["saved"] + t["refs"]):
            hints.append(f"{s}: {t['runs']} запуска подряд ничего не дал — выключить (settings.json → finder → off)?")
        if t["blocked_runs"] >= 2:
            hints.append(f"{s}: сайт закрывал доступ в {t['blocked_runs']} запусках из {t['runs']} — проверить доступ, "
                         f"паузы или выключить (settings.json → finder → off)")
    reqs = [q for q in _read(REQUESTS) if q.get("episode") in {r["episode"] for r in runs} and not q.get("auto")]
    if reqs:
        wins: dict[str, int] = {}
        for q in reqs:
            if q.get("variant"):
                wins[q["variant"]] = wins.get(q["variant"], 0) + 1
        if wins:
            log("\nКакой вариант запроса дал кадр: " + " · ".join(f"{k} {v}" for k, v in sorted(wins.items(), key=lambda x: -x[1])))
        reasons: dict[str, int] = {}
        for q in reqs:
            if q.get("empty_reason"):
                reasons[q["empty_reason"]] = reasons.get(q["empty_reason"], 0) + 1
        if reasons:
            log("Почему шоты остались без свободного кадра: " + " · ".join(f"{k} {v}" for k, v in reasons.items()))
    log("\nПодсказки для улучшения:" if hints else "\nПодсказок нет.")
    for h in hints:
        log(f"  · {h}")
    log(f"\nПодробно по запросам: {REQUESTS}")
