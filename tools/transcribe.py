"""Распознавание озвучки с точным временем каждого слова (faster-whisper на процессоре, модель medium)."""
from __future__ import annotations

from pathlib import Path

from util import log


def _load_audio(audio: Path):
    """Читаем звук сами через ffmpeg (16 кГц, моно) — не зависим от версии библиотеки av."""
    import subprocess

    import numpy as np
    res = subprocess.run(
        ["ffmpeg", "-v", "error", "-nostdin", "-i", str(audio), "-f", "s16le", "-ac", "1", "-ar", "16000", "-"],
        capture_output=True,
    )
    if res.returncode != 0 or not res.stdout:
        raise SystemExit(f"Не удалось прочитать озвучку: {res.stderr.decode(errors='ignore')[:300]}")
    return np.frombuffer(res.stdout, np.int16).astype(np.float32) / 32768.0


def glossary(text: str, limit: int = 200) -> str:
    """Короткая подсказка для Whisper: редкие слова и имена из сценария.
    Длинный кусок сценария в подсказке заставляет Whisper «сочинять» начало — так делать нельзя."""
    import re
    seen, out = set(), []
    for m in re.finditer(r"[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё\-]+", text):
        w = m.group(0)
        before = text[:m.start()].rstrip(" «\"'(")
        if not w[0].isupper() or len(w) < 3 or not before or before[-1] in ".!?:;—–-\n":
            continue  # пропускаем обычные слова и слова в начале предложения
        if w.lower() not in seen:
            seen.add(w.lower())
            out.append(w)
    res = ", ".join(out)
    return res[:limit].rsplit(",", 1)[0] if len(res) > limit else res


def _run(model, samples, language, prompt, vad, offset=0.0):
    segments, info = model.transcribe(
        samples,
        language=language,
        word_timestamps=True,
        vad_filter=vad,
        vad_parameters={"min_silence_duration_ms": 300} if vad else None,
        initial_prompt=prompt or None,
        beam_size=5,
        condition_on_previous_text=False,
    )
    segs = []
    for seg in segments:
        ws = [{"w": w.word.strip(), "start": round(w.start + offset, 3), "end": round(w.end + offset, 3),
               "p": round(w.probability, 3)} for w in (seg.words or []) if w.word.strip()]
        if ws:
            segs.append({"start": seg.start + offset, "end": seg.end + offset, "text": seg.text.strip(), "words": ws})
    return segs, info


def _conf(ws: list[dict]) -> float:
    return sum(w["p"] for w in ws) / len(ws) if ws else 0.0


def _repair(model, samples, language, prompt, segs, sr=16000):
    """Куски с низкой уверенностью распознаём заново другими способами и берём лучший вариант."""
    bad = [i for i, sg in enumerate(segs) if len(sg["words"]) >= 3 and _conf(sg["words"]) < 0.45]
    if not bad:
        return segs, 0
    groups, cur = [], [bad[0]]
    for i in bad[1:]:
        if i == cur[-1] + 1:
            cur.append(i)
        else:
            groups.append(cur)
            cur = [i]
    groups.append(cur)
    fixed = 0
    for g in reversed(groups):
        a = segs[g[0]]["start"]
        b = segs[g[-1]]["end"]
        lo = segs[g[0] - 1]["end"] if g[0] > 0 else 0.0
        hi = segs[g[-1] + 1]["start"] if g[-1] + 1 < len(segs) else len(samples) / sr
        a, b = max(lo, a - 0.2), min(hi, b + 0.2)
        piece = samples[int(a * sr):int(b * sr)]
        old_words = [w for i in g for w in segs[i]["words"]]
        best, best_c = None, _conf(old_words)
        for pr, vad in ((None, False), (prompt, False), (None, True)):
            try:
                cand, _ = _run(model, piece, language, pr, vad, offset=a)
            except Exception:  # noqa: BLE001
                continue
            ws = [w for sg in cand for w in sg["words"]]
            c = _conf(ws)
            if ws and c > best_c + 0.1:
                best, best_c = cand, c
        if best:
            segs[g[0]:g[-1] + 1] = best
            fixed += 1
            log(f"  Переслушал {a:.0f}–{b:.0f} с: уверенность {_conf(old_words) * 100:.0f}% → {best_c * 100:.0f}%")
    return segs, fixed


def transcribe(audio: Path, language: str = "en", prompt: str = "") -> dict:
    """Видеокарты NVIDIA нет (Intel Iris Xe): всегда процессор + модель medium."""
    samples = _load_audio(audio)
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise SystemExit("Не установлен faster-whisper: .venv/Scripts/python.exe -m pip install -r requirements.txt")
    log("  Whisper: модель medium на процессоре...")
    model = WhisperModel("medium", device="cpu", compute_type="int8")
    segs, info = _run(model, samples, language, prompt, vad=True)
    segs, _ = _repair(model, samples, language, prompt, segs)
    words = [w for sg in segs for w in sg["words"]]
    low = [sg for sg in segs if len(sg["words"]) >= 3 and _conf(sg["words"]) < 0.45]
    if low:
        log(f"  ! Неуверенно распознано: {', '.join(f'{sg['start']:.0f}–{sg['end']:.0f} с' for sg in low)} — время там подстроится по сценарию")
    return {"language": info.language, "duration": info.duration, "text": " ".join(sg["text"] for sg in segs),
            "words": words, "device": "cpu", "model": "medium", "confidence": round(_conf(words), 3)}
