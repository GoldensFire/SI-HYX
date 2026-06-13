"""Генератор manifest.json и bin/.binver для дельта-обновлений.

Вызывается из build.bat ПОСЛЕ копирования bin в собранную папку:

    python make_manifest.py "dist\\SI-HYX vX.Y.Z" "dist"

Что делает:
  • считает SHA256 по всему содержимому <app>/bin (детерминированно: файлы
    в отсортированном порядке, в хеш идут относительный путь + содержимое);
  • пишет этот хеш в <app>/bin/.binver — программа читает его, чтобы понять,
    какой набор bin у неё сейчас стоит;
  • пишет <dist>/manifest.json = {"version": ..., "bin_sha": ...} — крошечный
    файл, который апдейтер качает первым и сравнивает bin_sha с локальным.

Файл .binver в хеш НЕ включается (иначе хеш зависел бы сам от себя).
"""
import hashlib
import json
import os
import sys

BINVER_NAME = ".binver"


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


def main():
    if len(sys.argv) < 3:
        print("usage: make_manifest.py <app_dir> <dist_dir>")
        sys.exit(2)
    app_dir = sys.argv[1]
    dist_dir = sys.argv[2]

    # APP_VERSION берём из config.py (скрипт лежит рядом с ним)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import config

    bin_dir = os.path.join(app_dir, "bin")
    if not os.path.isdir(bin_dir):
        print(f"[ERROR] bin not found: {bin_dir}")
        sys.exit(1)

    sha = compute_bin_sha(bin_dir)

    with open(os.path.join(bin_dir, BINVER_NAME), "w", encoding="ascii") as f:
        f.write(sha)

    manifest = {"version": config.APP_VERSION, "bin_sha": sha}
    with open(os.path.join(dist_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"bin_sha = {sha}")
    print(f"wrote   {os.path.join(bin_dir, BINVER_NAME)}")
    print(f"wrote   {os.path.join(dist_dir, 'manifest.json')}")


if __name__ == "__main__":
    main()
