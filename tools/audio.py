"""Звук: подготовка озвучки, громкость под стандарт YouTube, стандартные звуковые эффекты."""
from __future__ import annotations

import json
import re
from pathlib import Path

from util import log, run

# Лёгкая «студийная» обработка голоса: срез гула, мягкая компрессия, чуть присутствия, защита от перегруза
VOICE_CHAIN = (
    "highpass=f=75,"
    "lowpass=f=16000,"
    "afftdn=nf=-30:tn=1,"
    "equalizer=f=200:t=q:w=1:g=-1.5,"
    "equalizer=f=3500:t=q:w=1.2:g=2,"
    "acompressor=threshold=-20dB:ratio=2.5:attack=8:release=150:makeup=2,"
    "alimiter=limit=0.95"
)


def voice_layout(files: list[Path], plan: dict | None, gap: float) -> list[tuple[Path, float | None, float | None, float]]:
    """Куски озвучки по плану пауз 06_montage/voice_parts.json (решение Nurlan, EP-08: «воздух» между тактами):
    {"default_gap": 1.2, "gaps": {"vo_01": 3.0, …}, "splits": {"vo_12": [{"at": 57.6, "gap": 3.0}]}}.
    gaps — пауза ПОСЛЕ файла; splits — пауза ВНУТРИ файла в тишине между тактами (звук не вырезается, только раздвигается).
    → [(файл, начало, конец, пауза после)]; без плана — у всех одна пауза gap."""
    plan = plan or {}
    dflt = float(plan.get("default_gap", gap))
    out = []
    for i, f in enumerate(files):
        last = i == len(files) - 1
        after = 0.0 if last else float((plan.get("gaps") or {}).get(f.stem, dflt))
        cuts = sorted((plan.get("splits") or {}).get(f.stem, []), key=lambda c: float(c["at"]))
        start = None
        for c in cuts:
            out.append((f, start, float(c["at"]), float(c.get("gap", dflt))))
            start = float(c["at"])
        out.append((f, start, None, after))
    return out


def prepare_voice(files: list[Path], out: Path, enhance: bool = False, gap: float = 1.0, gain_db: float = 0.0,
                  plan: dict | None = None) -> None:
    """Склеивает файлы озвучки по порядку. Внутри файлов НИЧЕГО не режет и не ускоряет:
    паузы («воздух» между тактами) в озвучке ElevenLabs — часть замысла.

    Несколько файлов (например, тизер следующего эпизода отдельно) идут подряд, между ними пауза gap секунд.
    gain_db — поправка громкости голоса (0 = как в AutoEdit; итоговая громкость всё равно выравнивается до −14 LUFS).
    enhance — «студийная» обработка VOICE_CHAIN; для ElevenLabs выключена.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-v", "error"]
    for f in files:
        cmd += ["-i", str(f)]
    idx = {f: i for i, f in enumerate(files)}
    segs = voice_layout(files, plan, gap)
    n = len(segs)
    chain = (VOICE_CHAIN + "," if enhance else "") + f"volume={gain_db:.1f}dB"
    ins = ""
    for i, (f, a, b, after) in enumerate(segs):
        trim = "" if a is None and b is None else (
            f"atrim={'start=' + format(a, '.3f') if a is not None else 'start=0'}{':end=' + format(b, '.3f') if b is not None else ''},"
            "asetpts=PTS-STARTPTS,")
        pad = f",apad=pad_dur={after:.3f}" if after > 0 else ""
        ins += f"[{idx[f]}:a]{trim}aresample=48000,aformat=channel_layouts=mono{pad}[a{i}];"
    cat = "".join(f"[a{i}]" for i in range(n))
    flt = f"{ins}{cat}concat=n={n}:v=0:a=1,{chain}[out]"
    cmd += ["-filter_complex", flt, "-map", "[out]", "-ac", "1", "-c:a", "pcm_s16le", str(out)]
    run(cmd)


def speech_intervals(words: list[dict], merge_gap: float = 0.8) -> list[list[float]]:
    out: list[list[float]] = []
    for w in words:
        s, e = w["start"], w["end"]
        if out and s - out[-1][1] <= merge_gap:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return [[round(a, 3), round(b, 3)] for a, b in out]


def measure_lufs(path: Path) -> float | None:
    """Громкость файла в LUFS (как её считает YouTube) — для правила «музыка под голосом на 13 дБ тише голоса»."""
    res = run(["ffmpeg", "-hide_banner", "-i", str(path), "-af", "loudnorm=print_format=json", "-f", "null", "-"], check=False)
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", res.stderr or "", re.S)
    try:
        return float(json.loads(m.group(0))["input_i"]) if m else None
    except (ValueError, KeyError):
        return None


def loudnorm(src: Path, dst: Path, target: float = -14.0, tp: float = -1.5) -> dict:
    """Двухпроходная нормализация громкости. Видео копируется без перекодирования."""
    res = run(["ffmpeg", "-hide_banner", "-i", str(src), "-af", f"loudnorm=I={target}:TP={tp}:LRA=11:print_format=json",
               "-f", "null", "-"], check=False)
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", res.stderr or "", re.S)
    if not m:
        log("  ! Не удалось измерить громкость, копирую как есть")
        run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-map_metadata", "-1", "-c", "copy", str(dst)])
        return {}
    meas = json.loads(m.group(0))
    af = (f"loudnorm=I={target}:TP={tp}:LRA=11:measured_I={meas['input_i']}:measured_TP={meas['input_tp']}:"
          f"measured_LRA={meas['input_lra']}:measured_thresh={meas['input_thresh']}:offset={meas['target_offset']}:linear=true")
    # служебные теги программ сборки (например, «Made with Remotion») в готовый файл не переносим
    run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-map_metadata", "-1", "-c:v", "copy", "-af", af, "-ar", "48000",
         "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", str(dst)])
    return meas


def ensure_default_sfx(folder: Path) -> dict[str, str]:
    """Создаёт мягкие звуковые эффекты (если своих нет): «вжух» для переходов и «тик» для пунктов."""
    folder.mkdir(parents=True, exist_ok=True)
    whoosh = folder / "whoosh.wav"
    tick = folder / "tick.wav"
    swell = folder / "swell.wav"
    if not whoosh.exists():
        run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "anoisesrc=d=1.1:c=pink:a=0.5:r=48000",
             "-af", "highpass=f=250,lowpass=f=2600,afade=t=in:d=0.6:curve=exp,afade=t=out:st=0.6:d=0.5:curve=log,"
             "aecho=0.6:0.4:60:0.25,volume=0.9", "-ac", "2", str(whoosh)])
    if not tick.exists():
        run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=f=1250:d=0.14:r=48000",
             "-af", "afade=t=out:st=0.01:d=0.13:curve=exp,lowpass=f=4000,volume=0.6", "-ac", "2", str(tick)])
    if not swell.exists():
        run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "anoisesrc=d=2.2:c=brown:a=0.6:r=48000",
             "-af", "lowpass=f=900,afade=t=in:d=1.7:curve=exp,afade=t=out:st=1.7:d=0.5,volume=1.2", "-ac", "2", str(swell)])
    return {"whoosh": whoosh.name, "tick": tick.name, "swell": swell.name}


def normalize_music(src: Path, dst: Path, target: float = -16.0) -> Path:
    """Выравниваем громкость каждого трека заранее — любая музыка будет звучать одинаково."""
    if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
        return dst
    dst.parent.mkdir(parents=True, exist_ok=True)
    res = run(["ffmpeg", "-hide_banner", "-i", str(src), "-af", f"loudnorm=I={target}:TP=-2:LRA=11:print_format=json",
               "-f", "null", "-"], check=False)
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", res.stderr or "", re.S)
    if not m:
        return src
    meas = json.loads(m.group(0))
    af = (f"loudnorm=I={target}:TP=-2:LRA=11:measured_I={meas['input_i']}:measured_TP={meas['input_tp']}:"
          f"measured_LRA={meas['input_lra']}:measured_thresh={meas['input_thresh']}:offset={meas['target_offset']}:linear=true")
    run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-af", af, "-ar", "48000", "-ac", "2", str(dst)])
    log(f"  Музыка «{src.name}»: {float(meas['input_i']):.1f} → {target:.0f} LUFS")
    return dst
