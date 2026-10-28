# -*- coding: utf-8 -*-
"""Сверка установленного окружения с пинами requirements.txt.

Зачем: PyInstaller кладёт в сборку ТО, ЧТО СТОИТ В ОКРУЖЕНИИ, а CI ставит
зависимости из requirements.txt. Если версии разъехались, релиз и тесты
проверяют разные библиотеки — так и появились 41 алерт Dependabot на Pillow,
пока в окружении уже стояла исправленная версия.

Скрипт ничего не ставит и не меняет: он только сравнивает и, если есть
расхождение, подсказывает команду. Вызывается из build.bat перед PyInstaller,
поэтому «собралось» означает «собралось ровно на закреплённых версиях».

Запуск вручную:
    python tools/check_requirements.py
"""
import os
import re
import sys
from importlib import metadata

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REQUIREMENTS = os.path.join(ROOT, "requirements.txt")

# Пакеты-варианты: ставится ровно один. Ключ — имя из requirements.txt,
# значения — другие реализации того же пакета. Две реализации одновременно
# кладут один и тот же cv2/onnxruntime и ломают обновление (WinError 5).
VARIANT_GROUPS = {
    "onnxruntime": ("onnxruntime-gpu", "onnxruntime-directml", "onnxruntime-openvino"),
    "opencv-python": ("opencv-python-headless", "opencv-contrib-python",
                      "opencv-contrib-python-headless"),
    "opencv-python-headless": ("opencv-python", "opencv-contrib-python",
                               "opencv-contrib-python-headless"),
}

# Эти пакеты нельзя подменять другим вариантом: rapidocr 3.10 требует именно
# opencv-python-headless, иначе pip поставит второй cv2 рядом.
EXACT_VARIANTS = {"opencv-python-headless"}

# Имя и точный пин из строки requirements.txt (PEP 508, простые случаи).
REQ_RX = re.compile(
    r"(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)"
    r"(?:\[[^\]\s]+\])?"
    r"(?:==(?P<pin>[^\s#]+))?")


def canon(name):
    """Имя пакета в канонической форме PEP 503."""
    return re.sub(r"[-_.]+", "-", (name or "").lower())


def ver_tuple(text):
    """Версия → кортеж чисел; хвостовые нули не важны ('1.27' == '1.27.0')."""
    nums = re.findall(r"\d+", text or "")
    return tuple(int(n) for n in nums) if nums else (0,)


def same_version(a, b):
    ta, tb = ver_tuple(a), ver_tuple(b)
    while len(ta) > 1 and ta[-1] == 0:
        ta = ta[:-1]
    while len(tb) > 1 and tb[-1] == 0:
        tb = tb[:-1]
    return ta == tb


def read_pins(path=REQUIREMENTS):
    """requirements.txt → [(имя, пин или '')]; комментарии и опции пропускаем."""
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f.read().splitlines():
            spec = line.split("#", 1)[0].strip()
            if not spec or spec.startswith("-"):
                continue
            m = REQ_RX.fullmatch(spec)
            if m:
                rows.append((m.group("name"), m.group("pin") or ""))
    return rows


def installed_version(name):
    """Версия установленного пакета или '' (пакет не установлен)."""
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return ""


def installed_variants(name):
    """Все установленные реализации пакета: [(имя, версия)]."""
    names = (name,) + VARIANT_GROUPS.get(canon(name), ())
    found, seen = [], set()
    for candidate in names:
        key = canon(candidate)
        if key in seen:
            continue
        seen.add(key)
        version = installed_version(candidate)
        if version:
            found.append((candidate, version))
    return found


def actual_dist(name):
    """(фактическое имя, версия) с учётом пакетов-вариантов."""
    version = installed_version(name)
    if version:
        return name, version
    for variant in VARIANT_GROUPS.get(canon(name), ()):
        version = installed_version(variant)
        if version:
            return variant, version
    return name, ""


def check(rows=None):
    """Список проблем: (пакет, пин, установлено, пояснение)."""
    problems = []
    for name, pin in rows if rows is not None else read_pins():
        if not pin:
            continue                      # yt-dlp намеренно без пина
        dist, got = actual_dist(name)
        variants = installed_variants(name)
        if len(variants) > 1:
            found = ", ".join(f"{n}=={v}" for n, v in variants)
            problems.append((name, pin, got or "—",
                             f"одновременно стоят {found} — оставьте ровно один"))
        elif not got:
            problems.append((name, pin, "—", f"не установлен (нужен {name}=={pin})"))
        elif canon(name) in EXACT_VARIANTS and canon(dist) != canon(name):
            problems.append((name, pin, got,
                             f"установлен {dist}, а нужен именно {name}=={pin}"))
        elif not same_version(got, pin):
            hint = dist if canon(dist) != canon(name) else name
            problems.append((name, pin, got,
                             f"в окружении {hint}=={got}, в requirements.txt {pin}"))
    return problems


def main():
    problems = check()
    pins = [row for row in read_pins() if row[1]]
    if not problems:
        print(f"Requirements: {len(pins)} закреплённых пакетов совпадают с окружением.")
        return 0
    print(f"Requirements: расхождений {len(problems)} из {len(pins)} закреплённых пакетов:")
    width = max(len(name) for name, *_ in problems)
    for name, pin, got, why in problems:
        print(f"  {name:<{width}}  requirements={pin:<12} установлено={got:<12} {why}")
    print()
    print("Сборка кладёт в exe то, что стоит в окружении. Приведите их к одному виду:")
    print("  pip install -r requirements.txt   — вернуть версии релиза, или")
    print("  «Библиотеки (dev)» → «Проверить» → «Обновить выбранные»")
    print("  (с галочкой «Закрепить версии в requirements.txt»).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
