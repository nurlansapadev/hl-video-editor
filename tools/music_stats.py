"""Шаг 4, звук (с EP-08): замер характера треков 04_music → 06_montage/work/music_stats.json — для music_plan.json.

  .venv/Scripts/python.exe tools/music_stats.py ep-10

Поля: bpm, pulse (выраженность ритма 0–1), notes_per_s (плотность нот), bright_hz (яркость),
loud_db, dyn_db (размах громкости — драматичность), dur (длина трека, с).
"""
from __future__ import annotations

import subprocess
import sys

import numpy as np

from util import MUSIC_DIR, PRODUCTION, edit_dir, log, save_json

SR, HOP, WIN = 22050, 512, 2048


def measure(path) -> dict:
    raw = subprocess.run(["ffmpeg", "-v", "quiet", "-i", str(path), "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    y = np.frombuffer(raw, np.float32)
    n = 1 + (len(y) - WIN) // HOP
    frames = np.lib.stride_tricks.as_strided(y, (n, WIN), (y.strides[0] * HOP, y.strides[0]))
    spec = np.abs(np.fft.rfft(frames * np.hanning(WIN), axis=1))
    freqs = np.fft.rfftfreq(WIN, 1 / SR)
    rms_db = 20 * np.log10(np.sqrt((frames ** 2).mean(1)) + 1e-9)
    loud = rms_db > rms_db.max() - 50
    bright = (spec * freqs).sum(1)[loud].mean() / (spec.sum(1)[loud].mean() + 1e-9)
    flux = np.maximum(np.diff(np.log1p(spec), axis=0), 0).sum(1)
    flux = (flux - flux.mean()) / (flux.std() + 1e-9)
    peaks = (flux[1:-1] > flux[:-2]) & (flux[1:-1] > flux[2:]) & (flux[1:-1] > 1.0)
    dur = len(y) / SR
    fps = SR / HOP
    ac = np.correlate(flux, flux, "full")[len(flux) - 1:]
    ac /= ac[0]
    lo, hi = int(fps * 60 / 200), int(fps * 60 / 60)
    lag = lo + int(np.argmax(ac[lo:hi]))
    return {"bpm": round(60 * fps / lag), "pulse": round(float(ac[lag]), 2),
            "notes_per_s": round(float(peaks.sum() / dur), 2), "bright_hz": round(float(bright)),
            "loud_db": round(float(np.percentile(rms_db[loud], 50)), 1),
            "dyn_db": round(float(np.percentile(rms_db[loud], 95) - np.percentile(rms_db[loud], 10)), 1),
            "dur": round(dur, 1)}


def main(episode: str) -> None:
    stats = {}
    for f in sorted((PRODUCTION / episode / MUSIC_DIR).glob("*.mp3")):
        stats[f.stem] = measure(f)
        log(f"  {f.stem}: {stats[f.stem]}")
    out = edit_dir(episode) / "work" / "music_stats.json"
    save_json(out, stats)
    log(f"✔ {out}")


if __name__ == "__main__":
    main(sys.argv[1])
