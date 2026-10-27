"""Анализ медиафайлов: размеры, длительность, превью и контактный лист для «режиссёра»."""
from __future__ import annotations

import json
from pathlib import Path

from util import IMAGE_EXT, VIDEO_EXT, AUDIO_EXT, files_in, log, rel, run


def probe(path: Path) -> dict:
    res = run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)], check=False)
    try:
        info = json.loads(res.stdout or "{}")
    except json.JSONDecodeError:
        info = {}
    streams = info.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    dur = float(info.get("format", {}).get("duration", 0) or 0)
    w = int(v.get("width", 0)) if v else 0
    h = int(v.get("height", 0)) if v else 0
    rot = 0
    if v:
        for sd in v.get("side_data_list", []) or []:
            if "rotation" in sd:
                rot = int(sd["rotation"])
        rot = int((v.get("tags") or {}).get("rotate", rot))
    if abs(rot) in (90, 270):
        w, h = h, w
    return {"width": w, "height": h, "duration": dur, "hasAudio": a is not None}


def scan_media(project: Path) -> list[dict]:
    media_dir = project / "media"
    items = []
    for p in files_in(media_dir, IMAGE_EXT | VIDEO_EXT):
        info = probe(p)
        kind = "video" if p.suffix.lower() in VIDEO_EXT else "image"
        if info["width"] == 0:
            log(f"  ! Не удалось прочитать файл, пропускаю: {p.name}")
            continue
        items.append(
            {
                "src": rel(p, project),
                "name": p.name,
                "type": kind,
                "width": info["width"],
                "height": info["height"],
                "aspect": round(info["width"] / max(1, info["height"]), 3),
                "duration": round(info["duration"], 3) if kind == "video" else None,
                "hasAudio": info["hasAudio"] if kind == "video" else False,
            }
        )
    return items


def scan_audio(folder: Path) -> list[dict]:
    out = []
    for p in files_in(folder, AUDIO_EXT):
        info = probe(p)
        out.append({"path": p, "duration": info["duration"]})
    return out


def make_contact_sheet(project: Path, media: list[dict], out: Path) -> None:
    """Один лист со всеми кадрами и именами файлов — чтобы быстро просмотреть материал."""
    try:
        from PIL import Image, ImageDraw, ImageFont
        Image.MAX_IMAGE_PIXELS = None  # own stock photos can be 90+ MP — not a decompression bomb
    except ImportError:
        log("  (Pillow не установлен — контактный лист пропущен)")
        return
    thumbs_dir = out.parent / "thumbs"
    thumbs_dir.mkdir(parents=True, exist_ok=True)
    tiles = []
    for m in media:
        src = project / m["src"]
        thumb = thumbs_dir / (Path(m["name"]).stem + ".jpg")
        if m["type"] == "video":
            t = min(1.0, (m["duration"] or 2) / 2)
            run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", str(src), "-frames:v", "1",
                 "-vf", "scale=480:-2", str(thumb)], check=False)
        else:
            try:
                im = Image.open(src).convert("RGB")
                im.thumbnail((480, 480))
                im.save(thumb, quality=85)
            except Exception:
                continue
        if thumb.exists():
            tiles.append((m, thumb))
    if not tiles:
        return
    cols = 4
    tw, th = 480, 300
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tw, rows * (th + 40)), (20, 18, 16))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("arial.ttf", 22)
    except Exception:
        try:
            font = ImageFont.truetype("DejaVuSans.ttf", 22)
        except Exception:
            font = ImageFont.load_default()
    for i, (m, thumb) in enumerate(tiles):
        im = Image.open(thumb)
        im.thumbnail((tw - 10, th - 10))
        x = (i % cols) * tw
        y = (i // cols) * (th + 40)
        sheet.paste(im, (x + (tw - im.width) // 2, y + (th - im.height) // 2))
        label = m["name"] + (f"  [видео {m['duration']:.1f}с]" if m["type"] == "video" else "")
        draw.text((x + 8, y + th + 6), label, fill=(230, 200, 150), font=font)
    sheet.save(out, quality=85)
