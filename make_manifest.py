"""Генератор bin/.binver и manifest.json для дельта-обновлений с проверкой
целостности.

Две команды (вызываются из build.bat):

  1) python make_manifest.py binver "dist\\SI-HYX vX.Y.Z"
     • считает SHA256 по всему содержимому <app>/bin (детерминированно: файлы
       в отсортированном порядке, в хеш идут относительный путь + содержимое);
     • пишет этот хеш в <app>/bin/.binver — программа читает его, чтобы понять,
       какой набор bin у неё сейчас стоит.
     Делается ДО упаковки full-архива, чтобы .binver попал внутрь него.

  2) python make_manifest.py manifest "dist\\SI-HYX vX.Y.Z" "dist" ^
            "dist\\...-update.zip" "dist\\...-full.zip"
     • пишет <dist>/manifest.json:
         {"version", "bin_sha", "update_sha", "full_sha"}
       где update_sha/full_sha — SHA256 готовых архивов. Апдейтер качает
       manifest первым, выбирает архив и СВЕРЯЕТ его хеш после загрузки —
       битый или подменённый zip не распаковывается.
     Делается ПОСЛЕ упаковки обоих архивов.

Файл .binver в хеш bin НЕ включается (иначе хеш зависел бы сам от себя).
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


def compute_bin_sha(bin_dir: str) -> str:
    h = hashlib.sha256()
    for root, _dirs, files in os.walk(bin_dir):
        for name in sorted(files):
            if name == BINVER_NAME:
                continue
            path = os.path.join(root, name)
            rel = os.path.relpath(path, bin_dir).replace("\\", "/")
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
    sha = compute_bin_sha(bin_dir)
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
        "bin_sha": compute_bin_sha(bin_dir),
        "update_sha": _sha256_file(update_zip),
        "full_sha": _sha256_file(full_zip),
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
