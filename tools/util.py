"""Общие функции: пути, запуск внешних программ, чтение текста и JSON, сортировка файлов."""
from __future__ import annotations

import json
import os
import time
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # папка VideoEditor_2.0 (только код)
ENGINE = ROOT / "engine"
PRODUCTION = Path("D:/YouTube-Studio/production/honest-lies")  # эпизоды: PRODUCTION / "ep-8"

# Структура папки эпизода (создаёт hl-script: production/tools/new_episode.py N slug)
CLEAN_SCRIPT = "00-script/clean-script.txt"  # текст озвучки без тегов и фонетики — вход этапа 1 (читаем)
VO_DIR = "01_vo"               # Episode-NN.wav — цельная озвучка ElevenLabs (читаем)
CHARACTERS_DIR = "02_characters"  # cast.json (люди, места, страны) + фото Nurlan <id>_01.jpg (читаем)
GENERATED_DIR = "03_generated"  # гравюры, Veo, картинки по заданию [КАРТИНКА] (читаем)
MUSIC_DIR = "04_music"         # фоновая музыка (читаем)
FOOTAGE_DIR = "05_footage"     # архив и сток (читаем)
EDIT_DIR = "06_montage"        # работа программы + готовые версии ep-N_vK.mp4 в корне (пишем)
MONTAGE_DIR = EDIT_DIR
OWN_DIRS = (FOOTAGE_DIR, GENERATED_DIR, CHARACTERS_DIR)  # свои кадры: поиск идёт сначала здесь


def edit_dir(episode: str) -> Path:
    """Рабочая папка программы для эпизода: production/honest-lies/<episode>/06_montage."""
    return PRODUCTION / episode / EDIT_DIR

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus"}

IS_WIN = os.name == "nt"


def log(msg: str) -> None:
    print(msg, flush=True)


def die(msg: str) -> None:
    print(f"\n[ОШИБКА] {msg}\n", file=sys.stderr, flush=True)
    sys.exit(1)


def which_or_die(name: str) -> str:
    p = shutil.which(name)
    if not p:
        die(f"Не найдена программа '{name}'. Установите её через winget.")
    return p


def run(cmd: list[str], cwd: Path | None = None, capture: bool = True, check: bool = True) -> subprocess.CompletedProcess:
    res = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
    )
    if check and res.returncode != 0:
        err = (res.stderr or "")[-3000:] if capture else ""
        die(f"Команда завершилась с ошибкой ({res.returncode}): {' '.join(cmd[:4])} ...\n{err}")
    return res


def natural_key(p: Path | str):
    s = p.name if isinstance(p, Path) else str(p)
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def files_in(folder: Path, exts: set[str]) -> list[Path]:
    if not folder.exists():
        return []
    return sorted([p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in exts], key=natural_key)


def read_text(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-16", "cp1251"):
        try:
            txt = raw.decode(enc)
            if enc == "utf-16" and not raw.startswith((b"\xff\xfe", b"\xfe\xff")):
                continue
            return txt.replace("\r\n", "\n")
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def load_json(path: Path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def journal_add(path: Path, entry: dict) -> None:
    """Дописать запись в общий журнал-список (work/regen.json) под блокировкой файла: Gen, ReGen, ReGravure и Gemini
    часто идут параллельными процессами — раньше каждый перезаписывал журнал своей копией и стирал чужие записи (EP-14)."""
    lock = path.with_suffix(path.suffix + ".lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    while True:
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            if time.time() - t0 > 30 or (lock.exists() and time.time() - lock.stat().st_mtime > 60):
                lock.unlink(missing_ok=True)  # зависшая блокировка (процесс убит)
                continue
            time.sleep(0.05)
    try:
        data = load_json(path, []) or []
        data.append(entry)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    finally:
        os.close(fd)
        lock.unlink(missing_ok=True)


def rel(path: Path, base: Path) -> str:
    return path.resolve().relative_to(base.resolve()).as_posix()


def fmt_time(t: float) -> str:
    t = max(0.0, t)
    m, s = divmod(int(round(t)), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


# ───────────────────────── ключи ─────────────────────────
def gemini_key() -> str | None:
    """Ключ Google AI Studio: переменная окружения GEMINI_API_KEY или поле "gemini" в keys.json."""
    if os.environ.get("GEMINI_API_KEY"):
        return os.environ["GEMINI_API_KEY"].strip()
    key = (load_json(ROOT / "keys.json", {}) or {}).get("gemini")
    return str(key).strip() if key else None
