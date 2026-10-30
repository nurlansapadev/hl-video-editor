"""Учёт времени и денег по эпизоду (с EP-15, Nurlan: «в конце — отчёт по времени и стоимости OpenAI, Gemini»).

Каждая команда ve.py (и music_pick.py) в конце пишет строку в 06_montage/work/usage.jsonl:
  {"date", "step", "secs", "ok", "costs": [{"provider", "model", "what", "calls", "usd"}]}.
Деньги сюда складывают вызовы, которых нет в work/regen.json: проверка кадров глазами (finder), описания своих кадров
(local_index), подбор музыки (music_pick). Картинки (Gen / ReGen / ReGravure, OpenAI и Gemini) — в regen.json, отчёт
берёт их оттуда, чтобы не считать дважды. Отчёт — ve.py report ep-N (tools/episode_report.py).
"""
from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path

# $ за 1 млн токенов: вход, выход (openai.com/api/pricing, ai.google.dev/gemini-api/docs/pricing — 2026-10-30)
PRICE = {
    "gpt-4.1-mini": (0.40, 1.60), "gpt-4.1": (2.00, 8.00), "gpt-4o-mini": (0.15, 0.60),
    "gpt-audio-mini": (10.0, 20.0),  # аудио-вход
    "gemini-3.8-flash": (0.75, 3.75), "gemini-3.6-flash": (0.75, 3.75),  # до 31.12.2026, потом ×2
    "gemini-3.5-flash-lite": (0.30, 2.50), "gemini-3.1-flash-lite": (0.25, 1.50),
    "gemini-flash-latest": (0.30, 2.50), "gemini-flash-lite-latest": (0.10, 0.40),
}

_lock = threading.Lock()
_acc: dict[tuple[str, str, str], dict] = {}


def price(model: str, tokens_in: int, tokens_out: int) -> float:
    pin, pout = PRICE.get(model, (0.0, 0.0))
    return (tokens_in * pin + tokens_out * pout) / 1e6


def openai_usd(model: str, usage: dict | None) -> float:
    u = usage or {}
    return price(model, u.get("prompt_tokens", 0), u.get("completion_tokens", 0))


def gemini_usd(model: str, res: dict | None) -> float:
    u = (res or {}).get("usageMetadata") or {}
    return price(model, u.get("promptTokenCount", 0), u.get("candidatesTokenCount", 0) + u.get("thoughtsTokenCount", 0))


def add(provider: str, model: str, usd: float, what: str) -> None:
    """Запомнить один платный вызов (до конца команды)."""
    with _lock:
        a = _acc.setdefault((provider, model, what), {"calls": 0, "usd": 0.0})
        a["calls"] += 1
        a["usd"] += usd


def flush(project: Path, step: str, secs: float, ok: bool) -> None:
    """Конец команды: время + накопленные деньги → work/usage.jsonl."""
    with _lock:
        costs = [{"provider": p, "model": m, "what": w, "calls": v["calls"], "usd": round(v["usd"], 5)}
                 for (p, m, w), v in _acc.items()]
        _acc.clear()
    path = project / "work" / "usage.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"date": datetime.now().isoformat(timespec="seconds"), "step": step, "secs": round(secs, 1),
                            "ok": ok, "costs": costs}, ensure_ascii=False) + "\n")
