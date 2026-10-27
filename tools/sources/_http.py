"""Сеть для всех источников: запросы к API, скачивание файлов, паузы между запросами, «сайт закрыл доступ».

Состояние (кто заблокирован, когда был последний запрос) общее на весь запуск поиска.
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from util import ROOT, load_json, log

UA = "VideoEditor/2.0 (personal documentary editing tool; contact: local user)"
BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"

_last_call: dict[str, float] = {}
_blocked: set[str] = set()  # сайты, которые в этот запуск закрыли доступ (403) — больше их не трогаем


class SourceBlocked(RuntimeError):
    pass


def http_json(url: str, headers: dict | None = None, host_delay: float = 0.6, timeout: int = 30):
    """GET-запрос к API источника: пауза между запросами к одному сайту, повторы при 429/5xx, «браузер» при 403."""
    host = urllib.parse.urlparse(url).netloc
    if host in _blocked:
        raise SourceBlocked(host)
    wait = host_delay - (time.time() - _last_call.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    ua = UA
    for attempt in range(4):
        req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept": "application/json", **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                _last_call[host] = time.time()
                return json.loads(r.read().decode("utf-8", errors="ignore"))
        except urllib.error.HTTPError as e:
            _last_call[host] = time.time()
            if e.code == 403:
                if ua != BROWSER_UA:  # некоторые архивы пускают только «браузер»
                    ua = BROWSER_UA
                    time.sleep(1.5)
                    continue
                _blocked.add(host)
                raise SourceBlocked(host) from e
            if e.code == 429 or e.code >= 500:
                time.sleep(4 * (attempt + 1))
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"нет ответа: {host}")


_dl_last: dict = {}
_dl_429: dict = {}
_dl_cool: set = set()
DL_DELAY = {"upload.wikimedia.org": 2.0}  # Wikimedia просит не качать подряд без пауз (иначе ошибка 429)


def _wikimedia_variants(url: str) -> list[str]:
    """Для видео с Wikimedia сначала берём готовую уменьшенную копию 720p/480p — она легче и реже упирается в лимит."""
    u = url.split("?")[0]
    m = re.match(r"(https://upload\.wikimedia\.org/wikipedia/commons)/(\w/\w\w)/([^/]+\.(?:webm|ogv|ogg|mpg|mpeg))$", u, re.I)
    if not m:
        return [u]
    t = f"{m.group(1)}/transcoded/{m.group(2)}/{m.group(3)}/{m.group(3)}"
    return [t + ".720p.vp9.webm", t + ".480p.vp9.webm", u]


def _download_one(url: str, dst: Path, max_mb: int, headers: dict | None, host: str):
    tmp = dst.with_suffix(dst.suffix + ".part")
    for attempt in range(3):
        wait = DL_DELAY.get(host, 0) - (time.time() - _dl_last.get(host, 0))
        if wait > 0:
            time.sleep(wait)
        req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
                size = 0
                while True:
                    chunk = r.read(1 << 16)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > max_mb * 1024 * 1024:
                        raise RuntimeError("файл слишком большой")
                    f.write(chunk)
            tmp.replace(dst)
            _dl_last[host] = time.time()
            _dl_429[host] = 0
            return True
        except urllib.error.HTTPError as e:
            tmp.unlink(missing_ok=True)
            _dl_last[host] = time.time()
            if e.code in (429, 503):
                _dl_429[host] = _dl_429.get(host, 0) + 1
                if _dl_429[host] >= 8:  # сайт упорно просит паузу — не тратим время, повторим при следующем поиске
                    _dl_cool.add(host)
                    log(f"    · {host} просит сделать паузу — остальные файлы с него пропускаю. "
                        f"Запустите поиск ещё раз через 10–15 минут: докачаются только недостающие")
                    return "cool"
                try:
                    ra = int(e.headers.get("Retry-After") or 0)
                except (TypeError, ValueError):
                    ra = 0
                time.sleep(min(45, ra or 8 * (attempt + 1)))
                continue
            return f"HTTP {e.code}"
        except Exception as e:  # noqa: BLE001
            tmp.unlink(missing_ok=True)
            return str(e)[:80]
    return "сайт просит паузу (429)"


def download(url: str, dst: Path, max_mb: int = 400, headers: dict | None = None) -> bool:
    """Скачать файл в dst (через .part, чтобы не оставлять обрывков). False — не получилось, причина в журнале."""
    host = urllib.parse.urlparse(url).netloc
    if host in _dl_cool:
        return False
    urls = _wikimedia_variants(url) if host == "upload.wikimedia.org" else [url]
    err = None
    for u in urls:
        r = _download_one(u, dst, max_mb, headers, host)
        if r is True:
            return True
        err = r
        if r == "cool":
            return False
    log(f"    ! не скачалось ({err}): {url.split('?')[0][:90]}")
    return False


def keys() -> dict:
    return load_json(ROOT / "keys.json", {}) or {}


def strip_html(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or "")).strip()


def urls_in(obj, exts: tuple[str, ...]) -> list[str]:
    """Все ссылки на файлы нужного типа в ответе API (структура ответов у разных архивов своя)."""
    found = []
    if isinstance(obj, dict):
        for v in obj.values():
            found += urls_in(v, exts)
    elif isinstance(obj, list):
        for v in obj:
            found += urls_in(v, exts)
    elif isinstance(obj, str) and obj.startswith("http") and re.search(r"\.(" + "|".join(exts) + r")(\?|$)", obj, re.I):
        found.append(obj)
    return found
