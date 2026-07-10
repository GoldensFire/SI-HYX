"""Генератор bin/.binver и manifest.json для дельта-обновлений с проверкой
целостности.

Две команды (вызываются из build.bat):

  1) python make_manifest.py binver "dist\\SI-HYX vX.Y.Z"
     • считает SHA256 по всем внешним ассетам <app>/bin + <app>/models
       (детерминированно: файлы в отсортированном порядке, в хеш идут
       '<папка>/<относит.путь>' + содержимое);
     • пишет этот хеш в <app>/bin/.binver — программа читает его, чтобы понять,
       какой набор внешних ассетов у неё сейчас стоит.
     Делается ДО упаковки full-архива (и ПОСЛЕ копирования bin+models), чтобы
     .binver попал внутрь него.

  2) python make_manifest.py manifest "dist\\SI-HYX vX.Y.Z" "dist" ^
            "dist\\...-update.zip" "dist\\...-full.zip"
     • пишет <dist>/manifest.json:
         {"version", "bin_sha", "update_sha", "full_sha", "silent"}
       где update_sha/full_sha — SHA256 готовых архивов. Апдейтер качает
       manifest первым, выбирает архив и СВЕРЯЕТ его хеш после загрузки —
       битый или подменённый zip не распаковывается. silent берётся из
       config.SILENT_UPDATE — «необязательное» обновление: релиз обычный
       (не draft/pre-release, новые скачивания получают его), но тихая
       (авто) проверка при запуске программы не показывает плашку — см.
       _check_updates в main.py.
     Делается ПОСЛЕ упаковки обоих архивов.

Файл .binver в хеш НЕ включается (иначе хеш зависел бы сам от себя).
"""
import hashlib
import json
import os
import sys

BINVER_NAME = ".binver"


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


# Внешние ассеты приложения, по которым считается хеш «версии бинарников»:
#   • bin\    — ffmpeg/yt-dlp и пр.;
#   • models\ — lama_fp32.onnx / model_uint8.onnx (подвкладки «Фото»). Тоже внешний
#               ассет рядом с .exe (НЕ внутри сборки) — чтобы не попадать в дельта-
#               апдейт. Включаем в хеш: если модель сменилась, апдейтер выберет
#               полный архив (а не код-онли) — пользователь получит новую модель.
# Папки нет → она пропускается (хеш считается по тому, что есть).
ASSET_DIRS = ("bin", "models")


def compute_bin_sha(app_dir: str) -> str:
    """SHA256 по всем внешним ассетам (ASSET_DIRS) приложения. Детерминированно:
    в хеш идут '<папка>/<относит.путь>' + содержимое в отсортированном порядке.
    .binver исключается (иначе хеш зависел бы сам от себя)."""
    h = hashlib.sha256()
    entries = []
    for sub in ASSET_DIRS:
        root_dir = os.path.join(app_dir, sub)
        if not os.path.isdir(root_dir):
            continue
        for root, _dirs, files in os.walk(root_dir):
            for name in files:
                if name == BINVER_NAME:
                    continue
                path = os.path.join(root, name)
                rel = (sub + "/" + os.path.relpath(path, root_dir)).replace("\\", "/")
                entries.append((rel, path))
    for rel, path in sorted(entries):
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
    return h.hexdigest()


def cmd_binver(app_dir: str):
    bin_dir = os.path.join(app_dir, "bin")
    if not os.path.isdir(bin_dir):
        print(f"[ERROR] bin not found: {bin_dir}")
        sys.exit(1)
    # Хеш по bin + models; пишем его в bin/.binver (его читает сама программа).
    sha = compute_bin_sha(app_dir)
    with open(os.path.join(bin_dir, BINVER_NAME), "w", encoding="ascii") as f:
        f.write(sha)
    print(f"bin_sha = {sha}")
    print(f"wrote   {os.path.join(bin_dir, BINVER_NAME)}")


def cmd_manifest(app_dir: str, dist_dir: str, update_zip: str, full_zip: str):
    # APP_VERSION берём из config.py (скрипт лежит рядом с ним)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import config

    bin_dir = os.path.join(app_dir, "bin")
    if not os.path.isdir(bin_dir):
        print(f"[ERROR] bin not found: {bin_dir}")
        sys.exit(1)
    for z in (update_zip, full_zip):
        if not os.path.isfile(z):
            print(f"[ERROR] archive not found: {z}")
            sys.exit(1)

    manifest = {
        "version": config.APP_VERSION,
        "bin_sha": compute_bin_sha(app_dir),
        "update_sha": _sha256_file(update_zip),
        "full_sha": _sha256_file(full_zip),
        "silent": bool(getattr(config, "SILENT_UPDATE", False)),
    }
    out = os.path.join(dist_dir, "manifest.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"wrote   {out}")
    for k, v in manifest.items():
        print(f"  {k} = {v}")


def main():
    args = sys.argv[1:]
    if len(args) >= 2 and args[0] == "binver":
        cmd_binver(args[1])
        return
    if len(args) >= 5 and args[0] == "manifest":
        cmd_manifest(args[1], args[2], args[3], args[4])
        return
    print("usage:")
    print("  make_manifest.py binver   <app_dir>")
    print("  make_manifest.py manifest <app_dir> <dist_dir> <update_zip> <full_zip>")
    sys.exit(2)


if __name__ == "__main__":
    main()
