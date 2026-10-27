"""Источники поиска фото и видео. Один источник — один файл в этой папке.

Новый источник: положить сюда `<имя>.py` (имена с «_» — служебные, не источники) и вписать имя
в settings.json → "finder" → "sources" для нужных видов материала. finder.py трогать не нужно.

Контракт файла-источника:
  NAME           = "pixabay"          — имя в настройках, журнале, found.json
  LABEL          = "Pixabay"          — имя в титрах ("" — не упоминать)
  KINDS          = ["image", "video"] — какие виды материала умеет искать (для проверки настроек)
  KEY            = "pixabay" | None   — ключ из keys.json; без ключа источник молча пропускается
  PRIORITY       = 0.75               — надёжность для черновой оценки до проверки глазами (по умолчанию 0.7)
  STRICT_TEXT    = False              — без проверки глазами брать только при совпадении описания ≥ 75% (а не 50%)
  CHECK_NOT_FREE = False              — отсеивать кадры с «Getty», «©», «all rights reserved» в описании
  REFS_ONLY      = False              — только образцы для ReGen (права неизвестны): спрашивается, лишь когда
                                        свободных кадров на шот не хватило (DuckDuckGo)
  search(q, kind, n, lang="en") -> list[dict]   — обязательно; кандидаты в общем формате:
      {source, type, url, thumb (превью для проверки глазами), page, title, author, license, license_url,
       width, height, [duration, date, text]}
  resolve(c) -> str | None    — по желанию: ссылка на файл, если в кандидате её нет (url=None) — NASA, DVIDS, Archive
  rights_ok(c) -> bool        — по желанию: проверка прав перед скачиванием (LOC)
  on_saved(c)                 — по желанию: что сделать после скачивания (Unsplash просит отметку)

Виды материала (kind): image — фото, video — видео, news — хроника, amateur — любительское,
document — газеты и документы, film — старые фильмы целиком (кладутся в library/).
"""
from __future__ import annotations

import importlib
import pkgutil
from types import ModuleType

KINDS = ("image", "video", "news", "amateur", "document", "film")

# порядок по умолчанию — если в settings.json нет "finder" → "sources"
DEFAULT_ORDER = {
    "image": ["commons", "openverse", "unsplash", "pexels", "pixabay", "nasa", "europeana", "loc"],
    "video": ["pexels", "pixabay", "commons", "nasa", "dvids", "europeana"],
    "news": ["dvids", "nasa", "commons", "europeana"],
    "amateur": ["commons", "europeana"],
    "document": ["newspapers", "loc", "commons", "europeana"],
    "film": ["archive"],
}

_registry: dict[str, ModuleType] | None = None


def all_sources() -> dict[str, ModuleType]:
    """Все файлы-источники этой папки: имя → модуль."""
    global _registry
    if _registry is None:
        _registry = {}
        for info in pkgutil.iter_modules(__path__):
            if info.name.startswith("_"):
                continue
            mod = importlib.import_module(f"{__name__}.{info.name}")
            if not hasattr(mod, "search"):
                raise RuntimeError(f"sources/{info.name}.py: нет функции search(q, kind, n, lang)")
            _registry[getattr(mod, "NAME", info.name)] = mod
    return _registry


def get(name: str) -> ModuleType:
    return all_sources()[name]


def labels() -> dict[str, str]:
    """Имя источника → как писать в титрах."""
    return {name: getattr(m, "LABEL", name) for name, m in all_sources().items()}


def priority(name: str) -> float:
    m = all_sources().get(name)
    return float(getattr(m, "PRIORITY", 0.7)) if m else 0.7


def has_key(name: str, keys: dict) -> bool:
    key = getattr(all_sources()[name], "KEY", None)
    return not key or bool(keys.get(key))


def order(cfg: dict) -> tuple[dict[str, list[str]], list[str]]:
    """Порядок источников для каждого вида материала из settings.json → "finder":
    "sources" — {вид: [источники по важности]}, "off" — выключенные источники.
    Возвращает (порядок, предупреждения о настройках)."""
    known = all_sources()
    plan = cfg.get("sources") if isinstance(cfg.get("sources"), dict) else DEFAULT_ORDER
    off = set(cfg.get("off") or [])
    warn = [f"«{n}» в \"off\" — такого источника нет" for n in sorted(off - set(known))]
    out: dict[str, list[str]] = {}
    for kind in KINDS:
        names = plan.get(kind) if kind in plan else DEFAULT_ORDER[kind]
        out[kind] = []
        for n in names:
            if n not in known:
                warn.append(f"{kind}: источника «{n}» нет в tools/sources — пропускаю")
            elif n not in off:
                if kind not in getattr(known[n], "KINDS", KINDS):
                    warn.append(f"{kind}: «{n}» такой материал не ищет")
                out[kind].append(n)
    return out, warn
