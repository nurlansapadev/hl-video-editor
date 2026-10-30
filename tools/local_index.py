"""Каталог своих кадров эпизода (05_footage, 03_generated, 02_characters): модель один раз описывает каждый файл
(подпись + теги + эпоха), чтобы поиск (finder.py, источник local) находил их по смыслу, как на стоке.

Фото из 02_characters названы по реестру (<id>_01.jpg): к ним добавляется «subject» — имя человека, места
или объекта из 02_characters/cast.json. Поиск находит их по имени, проверка глазами лицо не узнаёт —
такие фото Nurlan уже отобрал сам.

Каталог лежит в эпизоде: ep-N/06_montage/footage_index/<папка>/ (index.json + thumbs/). Сами папки не меняются.
Повторный запуск описывает только новые или изменённые файлы.
Описывает OpenAI (основной), Gemini — запасной.
  .venv/Scripts/python.exe tools/local_index.py D:/YouTube-Studio/production/honest-lies/ep-8/05_footage
"""
import base64
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import usage  # noqa: E402
from util import CHARACTERS_DIR, EDIT_DIR, ROOT, load_json, log, save_json  # noqa: E402

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv"}
BATCH = 10
MODELS = ["gemini-flash-latest", "gemini-2.5-flash", "gemini-flash-lite-latest"]
PROMPT = (
    "You are cataloguing footage for a documentary editor. For each numbered image return what it ACTUALLY shows, "
    "so the editor can find it later by a search query. Do not identify real people by name; describe them "
    "(e.g. 'older man in a suit at a podium'). Return a JSON array: "
    "[{\"i\": index, \"caption\": \"one sentence, max 25 words\", \"tags\": [\"8-15 lowercase english keywords: objects, "
    "place type, setting, mood, era\"], \"era\": \"e.g. 1980s / modern / unclear\", "
    "\"style\": \"photo|archive photo|illustration|engraving|ai render|map|document|text card\"}]"
)


def index_dir(folder: Path) -> Path:
    """ep-N/05_footage → ep-N/06_montage/footage_index/05_footage (у каждой папки свой каталог)."""
    return folder.parent / EDIT_DIR / "footage_index" / folder.name


def _key(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def is_source(name: str) -> bool:
    """Исходник Nurlan для генерации (s_12.png, s-Robert Weiss.png) — в монтаж не идёт, в каталог не попадает."""
    return name.lower().startswith(("s_", "s-"))


def cast_subjects(episode: Path) -> dict[str, tuple[str, str]]:
    """id из реестра 02_characters/cast.json → (имя, вид): люди и объекты по id, места по названию.
    frank_camper → ("Frank Camper", "person"); camp_century → ("Camp Century", "place")."""
    cast = load_json(episode / CHARACTERS_DIR / "cast.json", {}) or {}
    out = {}
    for p in cast.get("people", []) or []:
        if p.get("id") and p.get("name"):
            out[_key(p["id"])] = (p["name"], "person")
    for o in cast.get("objects", []) or []:
        if o.get("id") and o.get("name"):
            out[_key(o["id"])] = (o["name"], "object")
    for name in (cast.get("places") or {}):
        out[_key(name)] = (name, "place")
    return out


def media_info(p: Path, thumbs: Path) -> dict | None:
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    th = thumbs / f"{p.stem}.jpg"
    info = {"file": str(p), "name": p.name, "type": "video" if p.suffix.lower() in VIDEO_EXT else "image", "thumb": str(th)}
    try:
        if info["type"] == "video":
            dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                                       capture_output=True, text=True).stdout.strip() or 0)
            info["duration"] = dur
            if not th.exists():
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{dur / 2:.2f}", "-i", str(p), "-frames:v", "1",
                                "-vf", "scale=512:-2", str(th)], check=True)
            with Image.open(th) as im:
                info["width"], info["height"] = 1920, int(1920 * im.size[1] / im.size[0])
        else:
            with Image.open(p) as im:
                info["width"], info["height"] = im.size
                if not th.exists():
                    im = im.convert("RGB")
                    im.thumbnail((512, 512))
                    im.save(th, quality=82)
    except Exception as e:  # noqa: BLE001
        log(f"  ! {p.name}: {e}")
        return None
    return info


def describe_openai(batch: list[dict], key: str, model: str) -> list[dict] | None:
    content = [{"type": "text", "text": PROMPT.replace("Return a JSON array: [", "Return a JSON object {\"items\": [...]} where items is [")}]
    for i, it in enumerate(batch):
        content.append({"type": "text", "text": f"Image {i}:"})
        content.append({"type": "image_url", "image_url": {
            "url": "data:image/jpeg;base64," + base64.b64encode(Path(it["thumb"]).read_bytes()).decode(), "detail": "low"}})
    body = {"model": model, "messages": [{"role": "user", "content": content}], "response_format": {"type": "json_object"}}
    for attempt in range(4):
        try:
            req = urllib.request.Request("https://api.openai.com/v1/chat/completions", data=json.dumps(body).encode(), method="POST",
                                         headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
            with urllib.request.urlopen(req, timeout=120) as r:
                res = json.loads(r.read().decode())
            usage.add("OpenAI", model, usage.openai_usd(model, res.get("usage")), "описание своих кадров")
            data = json.loads(res["choices"][0]["message"]["content"])
            items = data.get("items") if isinstance(data, dict) else data
            return [v for v in items or [] if isinstance(v, dict)]
        except urllib.error.HTTPError as e:
            msg = e.read().decode(errors="ignore")
            if e.code in (429, 500, 503) and attempt < 3:
                time.sleep(10)
                continue
            log(f"  ! openai {model}: HTTP {e.code} {msg[:200]}")
            return None
        except Exception as e:  # noqa: BLE001
            log(f"  ! openai {model}: {str(e)[:100]}")
            return None
    return None


def describe(batch: list[dict], key: str) -> list[dict] | None:
    parts = [{"text": PROMPT}]
    for i, it in enumerate(batch):
        parts.append({"text": f"Image {i}:"})
        parts.append({"inline_data": {"mime_type": "image/jpeg",
                                      "data": base64.b64encode(Path(it["thumb"]).read_bytes()).decode()}})
    body = {"contents": [{"parts": parts}], "generationConfig": {"responseMimeType": "application/json", "temperature": 0.1}}
    for model in MODELS:
        for attempt in range(4):
            try:
                req = urllib.request.Request(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                                             data=json.dumps(body).encode(), method="POST",
                                             headers={"Content-Type": "application/json", "x-goog-api-key": key})
                with urllib.request.urlopen(req, timeout=120) as r:
                    res = json.loads(r.read().decode())
                usage.add("Gemini", model, usage.gemini_usd(model, res), "описание своих кадров")
                text = "".join(p.get("text", "") for p in res["candidates"][0]["content"]["parts"])
                data = json.loads(re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip())
                return [v for v in data if isinstance(v, dict)]
            except urllib.error.HTTPError as e:
                msg = e.read().decode(errors="ignore")
                if e.code == 429 and "limit: 0" not in msg:
                    m = re.search(r'"retryDelay":\s*"(\d+)', msg)
                    time.sleep(min(70, int(m.group(1)) + 1) if m else 20)
                    continue
                if e.code in (500, 503) and attempt < 2:
                    time.sleep(5)
                    continue
                log(f"  ! {model}: HTTP {e.code}")
                break
            except Exception as e:  # noqa: BLE001
                log(f"  ! {model}: {str(e)[:100]}")
                break
    return None


def build(folder: Path) -> dict:
    keys = load_json(ROOT / "keys.json", {}) or {}
    key = keys.get("gemini")
    oa_key, oa_model = keys.get("openai"), keys.get("openaiModel") or "gpt-4.1-mini"
    if not key and not oa_key:
        raise SystemExit("No OpenAI or Gemini key in keys.json")
    out = index_dir(folder)
    thumbs = out / "thumbs"
    thumbs.mkdir(parents=True, exist_ok=True)
    idx_path = out / "index.json"
    idx = load_json(idx_path, {}) or {}
    files = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXT | VIDEO_EXT
                   and not is_source(p.name))
    todo = []
    for p in files:
        old = idx.get(p.name)
        if old and old.get("caption") and old.get("mtime") == p.stat().st_mtime:
            continue
        info = media_info(p, thumbs)
        if info:
            info["mtime"] = p.stat().st_mtime
            todo.append(info)
    log(f"▶ Каталог своих кадров {folder}: файлов {len(files)}, описать новых: {len(todo)}")
    for b in range(0, len(todo), BATCH):
        batch = todo[b:b + BATCH]
        # OpenAI (pay-as-you-go, быстро) — основной; Gemini (бесплатный уровень) — запасной
        verdicts = (describe_openai(batch, oa_key, oa_model) if oa_key else None) or (describe(batch, key) if key else None) or []
        by_i = {v.get("i"): v for v in verdicts}
        for i, it in enumerate(batch):
            v = by_i.get(i) or {}
            it.update({"caption": v.get("caption", ""), "tags": v.get("tags", []), "era": v.get("era", ""),
                       "style": v.get("style", "")})
            idx[it["name"]] = it
        save_json(idx_path, idx)
        log(f"  описано {min(b + BATCH, len(todo))}/{len(todo)}")
    return idx


def load(folder: Path) -> dict:
    """Каталог папки + «subject» из реестра для файлов вида <id>_01.jpg (реестр читается заново — правки сразу видны)."""
    idx = load_json(index_dir(folder) / "index.json", {}) or {}
    idx = {k: v for k, v in idx.items() if not is_source(v["name"])}
    subjects = cast_subjects(folder.parent)
    for it in idx.values():
        sid = _key(re.sub(r"[_\-\s]*\d+$", "", Path(it["name"]).stem))
        if sid in subjects:
            it["subject"], it["subject_kind"] = subjects[sid]
    return idx


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    build(Path(sys.argv[1]))
