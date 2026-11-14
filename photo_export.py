# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
# photo_export.py — сохранение результата «Редактирования фото»: без потерь
# (PNG/TIFF/BMP как у исходника) или сразу сжатым настройками «Обработки».
"""Экспорт фото. Без интерфейса: им пользуются вкладка «Редактирование фото»
(InpaintTab._save) и photo_tool для агента.

Режим «Настройками «Обработки»» гонит картинку тем же кодом, что вкладка
«Обработка» (ProcessWorker.process_avif): формат (avif/webp/png/jpg/ico),
лимит размера, проходы подбора, CQ, разрешение, скорость, снятие вотермарок.
Так 50-мегабайтный TIFF после правок сразу ложится AVIF'ом в 300 КБ, без
промежуточного PNG рядом с исходником."""
import os
import shutil
import tempfile
import uuid

EXPORT_LOSSLESS = "lossless"
EXPORT_PROCESS = "process"
EXPORT_MODES = (
    (EXPORT_LOSSLESS, "Без потерь (PNG / как у исходника)"),
    (EXPORT_PROCESS, "Настройками «Обработки» (сжатие)"),
)
EXPORT_MODE_KEYS = tuple(k for k, _ in EXPORT_MODES)

# Форматы, которые хранят картинку без потерь, — их сохраняем «как исходник».
_LOSSLESS_EXTS = ("png", "bmp", "tif", "tiff")
_ALPHA_LOSSLESS_EXTS = ("png", "webp", "tif", "tiff")


def lossless_ext(src_ext: str, has_alpha: bool = False) -> str:
    """Расширение сохранения без потерь: исходные png/bmp/tiff — как есть,
    остальное (jpg/webp/avif/heic…) → png, чтобы не сжимать повторно. С
    прозрачностью формат обязан её хранить (png/webp/tiff), иначе png."""
    ext = (src_ext or "").lower().lstrip(".")
    allowed = _ALPHA_LOSSLESS_EXTS if has_alpha else _LOSSLESS_EXTS
    return ext if ext in allowed else "png"


def unique_path(out_dir: str, stem: str, ext: str) -> str:
    """<out_dir>/<stem>.<ext>, а если занято — <stem>_1, _2, …"""
    ext = ext.lstrip(".")
    path = os.path.join(out_dir, f"{stem}.{ext}")
    n = 1
    while os.path.exists(path):
        path = os.path.join(out_dir, f"{stem}_{n}.{ext}")
        n += 1
    return path


def process_settings_from_saved(saved: dict) -> dict:
    """Настройки «Обработки» для ProcessWorker из settings.json приложения.

    В файле лимиты лежат парой «значение + галочка» (limit/limit_on…), а
    воркер ждёт уже выключенный лимит нулём — как MediaTab._collect_settings."""
    av = dict((saved or {}).get("avif") or {})

    def _on(key, default=0):
        return int(av.get(key, default) or 0) if av.get(key + "_on", key == "limit") else 0

    media = (saved or {}).get("media") or {}
    return {
        "avif": {
            "limit": _on("limit", 100),
            "adim": _on("adim"),
            "awidth": _on("awidth"),
            "aheight": _on("aheight"),
            "aspd": int(av.get("aspd", 2) or 0),
            "cq": int(av.get("cq", 30) or 0),
            "overwrite_src": False,
            "gemini_wm": bool(av.get("gemini_wm", True)),
            "fit_passes": int(av.get("fit_passes", 4) or 4),
            "img_fmt": str(av.get("img_fmt") or "avif"),
            "chroma": str(av.get("chroma") or "420"),
        },
        "export_dir": str(media.get("export_dir") or ""),
        "priority": "normal",
    }


def load_saved_process_settings() -> dict:
    """process_settings_from_saved по файлу настроек приложения (или
    значения по умолчанию, если файла нет)."""
    import json
    try:
        from config import SETTINGS_FILE
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            saved = json.load(f)
    except Exception:
        saved = {}
    return process_settings_from_saved(saved if isinstance(saved, dict) else {})


def apply_overrides(settings: dict, overrides: dict | None) -> dict:
    """Копия настроек с заменой полей картинки (ключи как у 'avif':
    img_fmt, limit, cq, adim, awidth, aheight, aspd, fit_passes, chroma,
    gemini_wm). Неизвестные ключи — ошибка, чтобы опечатка не терялась."""
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in (settings or {}).items()}
    av = out.setdefault("avif", {})
    known = {"img_fmt", "limit", "cq", "adim", "awidth", "aheight", "aspd",
             "fit_passes", "chroma", "gemini_wm"}
    for key, value in (overrides or {}).items():
        if key not in known:
            raise ValueError(f"неизвестная настройка картинки: {key} "
                             f"(можно: {', '.join(sorted(known))})")
        av[key] = value
    return out


class _StopSet(set):
    """removed_ids для ProcessWorker: «файл убран из очереди» = should_stop()."""

    def __init__(self, should_stop):
        super().__init__()
        self._should_stop = should_stop

    def __contains__(self, _item):
        return bool(self._should_stop and self._should_stop())


def export_with_process_settings(src_path: str, out_dir: str, stem: str,
                                 settings: dict, *, log=None, progress=None,
                                 should_stop=None) -> str:
    """Кодирует картинку src_path настройками «Обработки» и кладёт результат в
    <out_dir>/<stem>.<формат> (свободное имя). Возвращает путь результата.

    settings — словарь как у MediaTab._collect_settings() (нужны 'avif' и
    'priority'). Кодирует ProcessWorker.process_avif, но в своей временной
    папке: имя «_Сжатый», папка экспорта «Обработки» и перезапись исходника
    к фото не относятся. log(str), progress(pct, label) зовутся из того же
    потока, что и эта функция."""
    from workers import ProcessWorker
    tmp_dir = tempfile.mkdtemp(prefix="photo_export_")
    try:
        ext = os.path.splitext(src_path)[1] or ".png"
        tmp_src = os.path.join(tmp_dir, f"{stem}{ext}")
        shutil.copyfile(src_path, tmp_src)
        s = apply_overrides(settings, None)
        s["avif"]["overwrite_src"] = False
        s["export_dir"] = tmp_dir
        item = {"iid": uuid.uuid4().hex, "path": tmp_src, "type": "IMG",
                "is_done": False}
        worker = ProcessWorker([item], s, removed_ids=_StopSet(should_stop))
        if log is not None:
            worker.log.connect(log)
        cb = progress if progress is not None else (lambda *_a: None)
        result = worker.process_avif(item, cb)
        if should_stop and should_stop():
            raise RuntimeError("Отменено")
        if not result or not os.path.isfile(result) or result == tmp_src:
            raise RuntimeError("«Обработка» не создала файл")
        res_ext = os.path.splitext(result)[1].lstrip(".") or "avif"
        os.makedirs(out_dir, exist_ok=True)
        final = unique_path(out_dir, stem, res_ext)
        shutil.move(result, final)
        return final
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
