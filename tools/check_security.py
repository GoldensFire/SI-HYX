# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
#
# tools/check_security.py — локальная копия тех правил CodeQL, что уже
# срабатывали в этом репозитории и ловятся без анализа потоков данных:
#
#   1) py/incomplete-url-substring-sanitization: `"host.com" in url`,
#      `url.startswith("https://host.com")`, `host.endswith("host.com")`.
#      Подстрока не проверяет хост: "https://evil.test/?host.com" проходит.
#      Правильно — urlsplit(url).hostname и host_matches() из config.
#
#   2) py/redos: квантификатор над неоднозначным телом — пересекающиеся
#      альтернативы `(?:\\.|.)*` или вложенный повтор `(\w+\s?)*`. На
#      неподходящей строке re перебирает 2^n разборов и зависает.
#
# Правила с потоками данных (path-injection, full-ssrf, http-response-splitting,
# clear-text-storage) проверяет только сам CodeQL на GitHub; открытые алерты
# показывает `python tools/check_security.py --alerts` (нужен gh).
#
# Запуск: python tools/check_security.py [файлы…]. Без аргументов — весь код.
# Входит в tools/check_hygiene.py (CI) и в Stop-хук Claude Code (--hook).
import ast
import json
import os
import re
import subprocess
import sys

try:
    from re import _constants as _sre, _parser as _sre_parse
except ImportError:  # Python < 3.11
    import sre_constants as _sre
    import sre_parse as _sre_parse

if __package__:
    from .check_file_sizes import source_files
else:
    from check_file_sizes import source_files

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = "GoldensFire/SI-HYX"


def _rel(path):
    return os.path.relpath(path, ROOT).replace("\\", "/")


# ── 1. Проверка URL подстрокой ──────────────────────────────────────────────
# Те же выражения, что в запросе CodeQL IncompleteUrlSubstringSanitization.
_COMMON_TLD = r"(?:com|org|edu|gov|uk|net|io)(?![a-z0-9])"
_LOOKS_LIKE_URL = (
    re.compile(r"(?i)([a-z]*:?//)?\.?([a-z0-9-]+\.)+" + _COMMON_TLD + r"(:[0-9]+)?/?"),
    re.compile(r"(?i)https?://([a-z0-9-]+\.)+([a-z]+)(:[0-9]+)?/?"),
)
_SAFE_PREFIX = re.compile(r"(?i)https?://[.a-z0-9-]+/.*")
_SAFE_SUFFIX = re.compile(r"(?i)\.([a-z0-9-]+)(\.[a-z0-9-]+)+")


def _looks_like_url(text):
    return any(rx.fullmatch(text) for rx in _LOOKS_LIKE_URL)


def _strings(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, (ast.Tuple, ast.List)):
        return [s for item in node.elts for s in _strings(item)]
    return []


def url_substring_problems(tree, label):
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            left = node.left
            for op, right in zip(node.ops, node.comparators):
                if (isinstance(op, ast.In) and isinstance(left, ast.Constant)
                        and isinstance(left.value, str) and _looks_like_url(left.value)
                        and not isinstance(right, (ast.Tuple, ast.List, ast.Set, ast.Dict))):
                    found.append(f"{label}:{node.lineno}: «{left.value!r} in …» — "
                                 "подстрока не проверяет хост; сравнивай "
                                 "urlsplit(url).hostname или host_matches()")
                left = right
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
              and node.func.attr in ("startswith", "endswith") and node.args):
            for text in _strings(node.args[0]):
                if not _looks_like_url(text):
                    continue
                if node.func.attr == "startswith" and not _SAFE_PREFIX.fullmatch(text):
                    found.append(f"{label}:{node.lineno}: startswith({text!r}) — после "
                                 "хоста нужен «/» или сравнение urlsplit(url).hostname")
                if node.func.attr == "endswith" and not _SAFE_SUFFIX.fullmatch(text):
                    found.append(f"{label}:{node.lineno}: endswith({text!r}) — без "
                                 "ведущей точки подходит «evil" + text + "»")
    return found


# ── 2. ReDoS ────────────────────────────────────────────────────────────────
# Образцы символов, на которых сравниваются множества «что может стоять
# первым». Точный NFA-анализ CodeQL не повторяем: ловим две формы, которые
# дают экспоненту наверняка.
_PROBE = [chr(c) for c in list(range(0, 0x180)) + list(range(0x400, 0x460))
          + [0x2028, 0x3042, 0x30A2, 0x4E00, 0xFF01]]
_ALL = frozenset(_PROBE)
_CATEGORY = {
    _sre.CATEGORY_DIGIT: r"\d", _sre.CATEGORY_NOT_DIGIT: r"\D",
    _sre.CATEGORY_SPACE: r"\s", _sre.CATEGORY_NOT_SPACE: r"\S",
    _sre.CATEGORY_WORD: r"\w", _sre.CATEGORY_NOT_WORD: r"\W",
}
_REPEATS = (_sre.MAX_REPEAT, _sre.MIN_REPEAT)
_RE_FUNCS = {"compile", "search", "match", "fullmatch", "findall", "finditer",
             "sub", "subn", "split"}


def _class_set(items):
    negate, chars = False, set()
    for op, av in items:
        if op is _sre.NEGATE:
            negate = True
        elif op is _sre.LITERAL:
            chars.add(chr(av))
        elif op is _sre.RANGE:
            chars.update(c for c in _PROBE if av[0] <= ord(c) <= av[1])
        elif op is _sre.CATEGORY and av in _CATEGORY:
            rx = re.compile(_CATEGORY[av])
            chars.update(c for c in _PROBE if rx.fullmatch(c))
        else:
            return _ALL  # неизвестное — считаем «что угодно»
    return _ALL - chars if negate else frozenset(chars)


def _single_char(op, av):
    """Множество символов для элемента ровно из одного символа, иначе None."""
    if op is _sre.LITERAL:
        return frozenset([chr(av)])
    if op is _sre.NOT_LITERAL:
        return _ALL - {chr(av)}
    if op is _sre.ANY:
        return _ALL
    if op is _sre.IN:
        return _class_set(av)
    if op is _sre.SUBPATTERN and len(av[-1]) == 1:
        return _single_char(*av[-1][0])
    return None


def _chars_of_seq(seq):
    """Посимвольные множества последовательности из одиночных символов
    (утверждения пропускаются); None, если там есть повторы или ветки."""
    out = []
    for op, av in seq:
        if op in (_sre.AT, _sre.ASSERT, _sre.ASSERT_NOT):
            continue
        if op is _sre.SUBPATTERN:
            inner = _chars_of_seq(av[-1])
            if inner is None:
                return None
            out += inner
            continue
        chars = _single_char(op, av)
        if chars is None:
            return None
        out.append(chars)
    return out


def _nullable(seq):
    for op, av in seq:
        if op in (_sre.AT, _sre.ASSERT, _sre.ASSERT_NOT):
            continue
        if op in _REPEATS and av[0] == 0:
            continue
        if op is _sre.SUBPATTERN and _nullable(av[-1]):
            continue
        if op is _sre.BRANCH and any(_nullable(alt) for alt in av[1]):
            continue
        return False
    return True


def _alternatives(seq):
    """Альтернативы тела повтора: (a|b) → [a, b], иначе [тело]."""
    items = [(op, av) for op, av in seq if op not in (_sre.AT, _sre.ASSERT, _sre.ASSERT_NOT)]
    if len(items) == 1:
        op, av = items[0]
        if op is _sre.BRANCH:
            return [list(alt) for alt in av[1]]
        if op is _sre.SUBPATTERN:
            return _alternatives(av[-1])
    return [list(seq)]


def _ambiguous(body):
    alts = _alternatives(body)
    # (a) Вложенный повтор: ветка = неограниченный повтор + необязательное.
    for alt in alts:
        for i, (op, av) in enumerate(alt):
            core = av
            if op is _sre.SUBPATTERN:
                inner = [(o, a) for o, a in av[-1] if o in _REPEATS]
                if len(av[-1]) != 1 or not inner:
                    continue
                op, core = inner[0]
            if (op in _REPEATS and core[1] == _sre.MAXREPEAT
                    and _nullable(alt[:i] + alt[i + 1:])):
                return "вложенный неограниченный повтор"
    # (b) Пересекающиеся альтернативы: одну ветку можно собрать из одиночных
    # символов других — строку разбирают двумя путями на каждом шаге.
    shapes = [_chars_of_seq(alt) for alt in alts]
    singles = [(i, chars[0]) for i, chars in enumerate(shapes)
               if chars is not None and len(chars) == 1]
    for index, chars in enumerate(shapes):
        if not chars:
            continue
        others = [s for j, s in singles if j != index]
        if len(chars) == 1:
            if any(s & chars[0] for s in others):
                return "альтернативы пересекаются"
        elif all(any(s & position for s in others) for position in chars):
            return "ветку можно собрать из одиночных символов других веток"
    return ""


def _walk(seq):
    for op, av in seq:
        yield op, av
        if op in _REPEATS:
            yield from _walk(av[2])
        elif op is _sre.SUBPATTERN:
            yield from _walk(av[-1])
        elif op is _sre.BRANCH:
            for alt in av[1]:
                yield from _walk(alt)
        elif op in (_sre.ASSERT, _sre.ASSERT_NOT):
            yield from _walk(av[1])
        elif op is _sre.GROUPREF_EXISTS:
            for part in av[1:]:
                if part:
                    yield from _walk(part)


def redos_reason(pattern):
    try:
        parsed = _sre_parse.parse(pattern)
    except (re.error, TypeError, ValueError, OverflowError):
        return ""
    for op, av in _walk(parsed):
        if op in _REPEATS and av[1] == _sre.MAXREPEAT:
            reason = _ambiguous(list(av[2]))
            if reason:
                return reason
    return ""


def redos_problems(tree, label):
    found = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in _RE_FUNCS and node.args
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in ("re", "_re", "regex")):
            continue
        pattern = node.args[0]
        if not (isinstance(pattern, ast.Constant) and isinstance(pattern.value, str)):
            continue
        reason = redos_reason(pattern.value)
        if reason:
            found.append(f"{label}:{node.lineno}: ReDoS — {reason}: {pattern.value!r}")
    return found


# ── Запуск ──────────────────────────────────────────────────────────────────
def check_files(files):
    problems = []
    for path in files:
        try:
            with open(path, encoding="utf-8") as stream:
                tree = ast.parse(stream.read(), filename=path)
        except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
            continue
        label = _rel(path)
        problems += url_substring_problems(tree, label)
        problems += redos_problems(tree, label)
    return problems


def all_files():
    return [str(path) for path in source_files(ROOT) if path.suffix == ".py"]


def open_alerts():
    """Открытые алерты CodeQL на GitHub (по последнему анализу main)."""
    result = subprocess.run(
        ["gh", "api", f"repos/{REPO}/code-scanning/alerts?state=open&per_page=100",
         "--paginate", "--jq",
         '.[] | "\\(.rule.id) \\(.most_recent_instance.location.path):'
         '\\(.most_recent_instance.location.start_line)"'],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode:
        print("gh недоступен: " + (result.stderr.strip() or "ошибка"))
        return 2
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    print(f"Открытых алертов CodeQL: {len(lines)}")
    for line in lines:
        print("    " + line)
    return 1 if lines else 0


def hook():
    """Stop-хук Claude Code: проблемы → код 2, чтобы агент их исправил."""
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        payload = {}
    problems = check_files(all_files())
    if not problems:
        return 0
    text = ("Проверка безопасности (tools/check_security.py) нашла проблемы "
            "уровня CodeQL — исправь их до конца сессии:\n" + "\n".join(problems))
    if payload.get("stop_hook_active"):
        print(text, file=sys.stderr)
        return 0  # уже просили исправить — не зацикливаемся
    print(text, file=sys.stderr)
    return 2


def main(argv):
    # Хук и консоль Windows читают вывод не в cp1251 — иначе кириллица в «?».
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    if "--hook" in argv:
        return hook()
    if "--alerts" in argv:
        return open_alerts()
    files = [os.path.abspath(a) for a in argv if a.endswith(".py")] or all_files()
    problems = check_files(files)
    for problem in problems:
        print("    " + problem)
    print(f"{'[ПРОВАЛ]' if problems else '[ок]'} Безопасность (CodeQL-правила): "
          f"{len(problems)} проблем, файлов: {len(files)}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
