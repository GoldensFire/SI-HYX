# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
#
# tools/check_hygiene.py — быстрые проверки, которые тесты поймать не могут.
# Гоняется в CI (.github/workflows/tests.yml) и локально: python tools/check_hygiene.py
#
# Проверок три, и каждая закрывает проблему, которая уже случалась в этом
# проекте — это не абстрактные правила стиля:
#
#   1) star-импорты. Пока в модуле есть `from X import *`, pyflakes не может
#      проверить НИ ОДНОГО имени в нём: опечатка в редко вызываемой ветке
#      доезжает до пользователя. В siquester таких «слепых» строк было 9872.
#
#   2) неявная кодировка. open()/subprocess без encoding= берут кодировку
#      системной локали: cp1251 на русской Windows, cp1252 на английской.
#      UTF-8 вывод ffmpeg превращался в кракозябры, а байт 0x98 (не определён
#      в cp1251) ронял вызов UnicodeDecodeError. Кодировка обязана быть явной.
#
#   3) голые except. Ловят KeyboardInterrupt и SystemExit — из-за этого разбор
#      тяжёлого .siq нельзя было прервать.
import ast
import glob
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATTERNS = ("*.py", "sigstats/*.py", "siquester/*.py", "tests/*.py", "tools/*.py")

# Функции, у которых текстовый режим тянет кодировку из локали.
_TEXT_CALLS = ("subprocess.run", "subprocess.Popen", "subprocess.check_output",
               "_subprocess.run", "_subprocess.Popen")


def _sources():
    files = set()
    for p in PATTERNS:
        files |= set(glob.glob(os.path.join(ROOT, p)))
    return sorted(files)


def _rel(p):
    return os.path.relpath(p, ROOT).replace("\\", "/")


def check_imports(files):
    """pyflakes: неопределённые имена и star-импорты. Предупреждения про
    неиспользуемые локальные переменные проверку НЕ валят — это шум."""
    # Пути относительные и cwd=ROOT — чтобы вывод pyflakes выглядел так же,
    # как у остальных проверок, а не абсолютными путями с чужой машины.
    out = subprocess.run([sys.executable, "-m", "pyflakes", *(_rel(f) for f in files)],
                         cwd=ROOT, capture_output=True, text=True,
                         encoding="utf-8", errors="replace").stdout
    return [ln for ln in out.splitlines()
            if "undefined name" in ln or "star imports" in ln
            or "unable to detect undefined names" in ln]


def _literal(node):
    return node.value if isinstance(node, ast.Constant) else None


def check_encoding(files):
    """open()/subprocess в текстовом режиме без явного encoding=."""
    bad = []
    for f in files:
        tree = ast.parse(open(f, encoding="utf-8").read(), filename=f)
        for n in ast.walk(tree):
            if not isinstance(n, ast.Call):
                continue
            fn = ast.unparse(n.func)
            kw = {k.arg: k.value for k in n.keywords if k.arg}
            if "encoding" in kw:
                continue

            if fn in ("open", "io.open"):
                mode = ""
                if len(n.args) > 1:
                    mode = _literal(n.args[1]) or ""
                if "mode" in kw:
                    mode = _literal(kw["mode"]) or ""
                if "b" not in mode:          # бинарный режим кодировку не использует
                    bad.append(f"{_rel(f)}:{n.lineno}: open() без encoding=")

            elif fn.endswith(_TEXT_CALLS):
                if "text" in kw or "universal_newlines" in kw:
                    bad.append(f"{_rel(f)}:{n.lineno}: {fn}(text=...) без encoding=")

            elif fn.endswith((".read_text", ".write_text")):
                bad.append(f"{_rel(f)}:{n.lineno}: {fn} без encoding=")
    return bad


def check_bare_except(files):
    """Голые `except:` — ловят в том числе KeyboardInterrupt/SystemExit."""
    bad = []
    for f in files:
        tree = ast.parse(open(f, encoding="utf-8").read(), filename=f)
        for n in ast.walk(tree):
            if isinstance(n, ast.ExceptHandler) and n.type is None:
                bad.append(f"{_rel(f)}:{n.lineno}: голый except: "
                           f"(нужен except Exception:)")
    return bad


def main():
    files = _sources()
    failed = False
    for title, fn in (("Импорты (pyflakes)", check_imports),
                      ("Явная кодировка", check_encoding),
                      ("Голые except", check_bare_except)):
        problems = fn(files)
        if problems:
            failed = True
            print(f"[ПРОВАЛ] {title}: {len(problems)}")
            for p in problems:
                print(f"    {p}")
        else:
            print(f"[ок] {title}")
    print(f"\nпроверено файлов: {len(files)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
