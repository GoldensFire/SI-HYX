# -*- coding: utf-8 -*-
"""Архивы релиза: быстрее Compress-Archive, с прогрессом и переиспользованием
неизменных внешних ассетов из прошлого full-архива.

Вызывается из build.bat (шаги 5 и 8):

    python tools\\make_release_zip.py "dist\\SI-HYX vX.Y.Z" "dist\\UpdateHYX-vX.Y.Z.zip" --step 5
    python tools\\make_release_zip.py "dist\\SI-HYX vX.Y.Z" "dist\\SI-HYX-vX.Y.Z-full.zip" --step 8 --reuse-assets-from dist

Зачем не Compress-Archive:
  • PowerShell-конвейер и пересжатие ВСЕГО заново, даже если bin/models не
    менялись с прошлого релиза;
  • нет прогресса — build_gui.py мог рисовать только шаги;
  • на замере 124 МБ PyQt6: Compress-Archive Optimal — 3.9 с / 48.8 МБ,
    Python zipfile level=6 — 3.4 с / 48.8 МБ, level=4 — 2.8 с / 49.5 МБ
    (на 1.4% больше, зато примерно на 30% быстрее). level=1 — 1.4 с, но
    архив на 27% больше, поэтому это только опция «быстрые архивы».

Переиспользование ассетов: full-архив на 2/3 состоит из bin/ и models/,
которые меняются редко. Если SHA256, записанный в bin/.binver, совпадает с
прошлым full-архивом, записи bin/ и models/ переносятся из него КАК ЕСТЬ
(без распаковки и повторного сжатия, см. zip_fastcopy.copy_zip_entry). Это
честно: хеш считается по путям и содержимому всех файлов. Не совпало или
архив битый — молча сжимаем всё заново.

Архив пишется во временный файл и подменяет целевой только после успеха:
неудачная сборка больше не оставляет dist без прошлого архива.
"""
import argparse
import os
import sys
import time
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from zip_fastcopy import copy_zip_entry  # noqa: E402 — нужен sys.path выше

DEFAULT_LEVEL = 4
ASSET_DIRS = ("bin/", "models/")
BINVER_NAME = ".binver"


def _iter_files(root):
    """Все файлы под root в стабильном порядке (для повторяемых архивов)."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        filenames.sort()
        for name in filenames:
            yield os.path.join(dirpath, name)


def _rel(path, root):
    return os.path.relpath(path, root).replace(os.sep, "/")


def _read_binver(app_dir):
    path = os.path.join(app_dir, "bin", BINVER_NAME)
    try:
        with open(path, encoding="ascii") as f:
            value = f.read().strip()
    except OSError:
        return ""
    return value if len(value) == 64 and all(c in "0123456789abcdef" for c in value) else ""


def _find_assets_source(dist_dir, binver):
    """Прошлый full-архив, у которого bin/.binver совпадает с текущим.

    Возвращает (путь, префикс_внутри_архива) или None. Целевой архив тоже
    может быть кандидатом: новый пишется во временный файл, поэтому читать
    старый можно.
    """
    if not binver:
        return None
    try:
        entries = [e for e in os.scandir(dist_dir)
                   if e.is_file() and e.name.lower().endswith("-full.zip")]
    except OSError:
        return None
    entries.sort(key=lambda e: e.stat().st_mtime, reverse=True)
    for entry in entries:
        try:
            with zipfile.ZipFile(entry.path) as zf:
                info = next((i for i in zf.infolist()
                             if i.filename.endswith("/bin/" + BINVER_NAME)), None)
                if info is None:
                    continue
                if zf.read(info).decode("ascii", "replace").strip() != binver:
                    continue
                prefix = info.filename[:-len("bin/" + BINVER_NAME)]
                return entry.path, prefix
        except (OSError, RuntimeError, zipfile.BadZipFile, KeyError):
            continue
    return None


def _progress(step, done, total, state):
    """Печатает процент только при изменении: файлов тысячи, и строка на
    каждый — лишний шум в консоли и в QProcess-канале build_gui.py."""
    pct = int(done * 100 / total) if total else 100
    if state.get(step) == pct:
        return
    state[step] = pct
    print(f"[PROGRESS {step} {pct}]", flush=True)


def _copy_assets(src_path, dst, src_prefix, dst_prefix, app_dir, step, total, done,
                 progress_state):
    """Переносит bin/ и models/ из прошлого архива без пересжатия.

    Возвращает (copied_rel_paths, done_bytes). Неудачные записи (zip64,
    шифрование, битый заголовок) не попадают в copied и будут сжаты обычным
    путём из исходной папки.
    """
    copied = set()
    try:
        src = zipfile.ZipFile(src_path)
    except (OSError, RuntimeError, zipfile.BadZipFile):
        return copied, done
    with src:
        print(f"[INFO] assets reuse: {os.path.basename(src_path)}", flush=True)
        for info in src.infolist():
            if info.is_dir() or not info.filename.startswith(src_prefix):
                continue
            rel = info.filename[len(src_prefix):]
            if not rel.startswith(ASSET_DIRS):
                continue
            parts = rel.split("/")
            if any(part in ("", ".", "..") for part in parts):
                continue
            # Хеш совпал, но лишняя проверка дешёвая: файл должен быть на месте.
            if not os.path.isfile(os.path.join(app_dir, *parts)):
                continue
            if copy_zip_entry(src, dst, info, name=dst_prefix + rel):
                copied.add(rel)
                done += info.file_size
                _progress(step, done, total, progress_state)
            else:
                print(f"[WARN] assets reuse failed for {rel}, recompressing", flush=True)
    return copied, done


def _write_archive(source_dir, dest_zip, step, level, reuse_dir=None):
    source_dir = os.path.abspath(source_dir)
    dest_zip = os.path.abspath(dest_zip)
    if not os.path.isdir(source_dir):
        print(f"[ERROR] source not found: {source_dir}")
        return 1
    root_name = os.path.basename(os.path.normpath(source_dir))
    dst_prefix = root_name + "/"

    files = list(_iter_files(source_dir))
    sizes = {path: os.path.getsize(path) for path in files}
    total = sum(sizes.values())
    if not files:
        print(f"[ERROR] nothing to archive in {source_dir}")
        return 1

    os.makedirs(os.path.dirname(dest_zip), exist_ok=True)
    tmp_zip = dest_zip + ".tmp"
    try:
        os.remove(tmp_zip)
    except OSError:
        pass

    started = time.monotonic()
    done = 0
    copied = set()
    reuse = None
    progress_state = {}
    if reuse_dir and os.environ.get("SIHYX_REUSE_ASSETS", "1") != "0":
        reuse = _find_assets_source(reuse_dir, _read_binver(source_dir))

    try:
        with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED,
                             compresslevel=level, allowZip64=True) as dst:
            if reuse is not None:
                copied, done = _copy_assets(reuse[0], dst, reuse[1], dst_prefix,
                                            source_dir, step, total, done,
                                            progress_state)
            for path in files:
                rel = _rel(path, source_dir)
                if rel in copied:
                    continue
                dst.write(path, dst_prefix + rel)
                done += sizes[path]
                _progress(step, done, total, progress_state)
        os.replace(tmp_zip, dest_zip)
    except Exception:
        try:
            os.remove(tmp_zip)
        except OSError:
            pass
        raise

    elapsed = time.monotonic() - started
    print(f"[INFO] wrote {dest_zip} ({os.path.getsize(dest_zip) / 1024 / 1024:.1f} MB, "
          f"{elapsed:.1f} s, reuse={'yes' if reuse else 'no'})", flush=True)
    return 0


def main():
    parser = argparse.ArgumentParser(description="Создать zip-архив релиза SI-HYX")
    parser.add_argument("source", help="папка приложения (в архив попадёт её имя)")
    parser.add_argument("dest", help="путь к zip-архиву")
    parser.add_argument("--step", type=int, default=0,
                        help="номер шага build.bat для строк [PROGRESS n/100]")
    parser.add_argument("--level", type=int, default=None,
                        help=f"уровень deflate 0..9 (по умолчанию {DEFAULT_LEVEL})")
    parser.add_argument("--reuse-assets-from", default="",
                        help="папка dist с прошлыми full-архивами (bin/models)")
    args = parser.parse_args()

    level = args.level
    if level is None:
        try:
            level = int(os.environ.get("SIHYX_ZIP_LEVEL", DEFAULT_LEVEL))
        except ValueError:
            level = DEFAULT_LEVEL
    if not 0 <= level <= 9:
        print(f"[ERROR] invalid zip level: {level}")
        return 2

    return _write_archive(args.source, args.dest, args.step, level,
                          args.reuse_assets_from or None)


if __name__ == "__main__":
    sys.exit(main())
