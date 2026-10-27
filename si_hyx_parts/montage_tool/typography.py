# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Пословный текст по меткам word: раскладка и тексты проекта (edit op words,
lyrics). Public namespace: montage_tool.

Слова — маркеры проекта вида word (analyze --kinds word --write, Whisper),
каждое — свой TextItem: появляется в начале слова. Фразы делит пауза
длиннее gap. Раскладка:
  single — одно слово за раз в точке pos (до начала следующего слова фразы);
  line   — слова фразы копятся в строку, строка — по центру pos;
  stack  — копятся блоком шириной width (доля кадра): перенос по ширине,
           строки друг под другом, блок по центру pos.
Слово держится до конца фразы + hold. Ширина слова — по файлу шрифта
(PIL, кегль libass = высота winAscent+winDescent, а не em), шрифт без
известного файла — оценкой по числу букв.
emphasis — стиль отдельных слов (ключ — слово без знаков, без регистра;
#N — N-е слово фразы, #-1 — последнее).

lyrics — те же тексты, но слова и строки — из файла текста песни
пользователя: метки word отрезка (Whisper по вокалу) дают только время.
Все слова отрезка укладываются в кусок текста ДП (начало и конец куска в
файле свободны, неверно услышанное слово встаёт на место слова файла,
пропуски — с обеих сторон), поэтому повтор припева находит свой кусок;
слова файла без пары получают время между соседями по длине. Фраза —
строка файла, держится до начала следующей; words [a, b] — только слова
строки с a по b (половины строки разными стилями, одно слово крупно)."""
import functools
import os
import re

import montage_tool as _api

_PUNCT_RX = re.compile(r"[^\w']+")
# Строка-заголовок текста песни целиком в скобках: [Chorus], (x2).
_HEADER_RX = re.compile(r"\s*(?:\[[^\]]*\]|\([^)]*\))\s*")
# Ширина буквы в долях кегля, если файла шрифта нет: узкие шрифты и обычные.
_NARROW = ("impact", "condensed", "bahnschrift")
LAYOUTS = ("single", "line", "stack")
REVEALS = ("word", "line")
LYRICS_MAX_BYTES = 1 << 20
# Очки выравнивания текста с метками: совпало, похоже, другое слово, пропуск.
_MATCH, _NEAR, _SUB, _GAP = 2.0, 1.0, -1.0, -0.6
# Слово крайней строки без пары: непарное слово отрезка годится, если до
# соседа меньше _EDGE_GAP с; иначе слово длиной не больше _EDGE_STEP с.
_EDGE_GAP, _EDGE_STEP = 0.8, 0.35
# Пауза в пении (с) и прибавка, если с неё начинается строка файла.
_PAUSE, _LINE_BONUS = 0.25, 0.8
# Меньше этого (с) на слово без пары — промежуток между соседями тесен.
_MIN_WORD = 0.08
# Файлы шрифтов Windows для имён (и псевдонимов) текста проекта: (обычный, жирный).
_FONT_FILES = {"impact": ("impact.ttf", "impact.ttf"), "georgia": ("georgia.ttf", "georgiab.ttf"),
               "times new roman": ("times.ttf", "timesbd.ttf"),
               "segoe script": ("segoesc.ttf", "segoescb.ttf"),
               "ink free": ("Inkfree.ttf", "Inkfree.ttf"), "gabriola": ("Gabriola.ttf", "Gabriola.ttf"),
               "arial": ("arial.ttf", "arialbd.ttf"), "bahnschrift": ("bahnschrift.ttf", "bahnschrift.ttf"),
               "yu gothic": ("YuGothM.ttc", "YuGothB.ttc")}
# Хвост имени шрифта в реестре: «Bebas Neue Bold (OpenType)».
_REG_KIND_RX = re.compile(r"\s*\([^)]*\)\s*$")
_FONTS_KEY = r"Software\Microsoft\Windows NT\CurrentVersion\Fonts"


def _key(word):
    return _PUNCT_RX.sub("", word).lower()


@functools.lru_cache(maxsize=1)
def _installed_fonts():
    """Установленные шрифты Windows из реестра — общие и пользователя (их
    видит и libass): {имя начертания в нижнем регистре: путь}."""
    try:
        import winreg
    except ImportError:
        return {}
    bases = ((winreg.HKEY_CURRENT_USER,
              os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Fonts")),
             (winreg.HKEY_LOCAL_MACHINE,
              os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")))
    out = {}
    for root, base in bases:
        try:
            key = winreg.OpenKey(root, _FONTS_KEY)
        except OSError:
            continue
        with key:
            i = 0
            while True:
                try:
                    name, value, _kind = winreg.EnumValue(key, i)
                except OSError:
                    break
                i += 1
                if not isinstance(value, str):
                    continue
                path = value if os.path.isabs(value) else os.path.join(base, value)
                # Коллекция TTC — «Cambria & Cambria Math».
                for part in _REG_KIND_RX.sub("", name).lower().split(" & "):
                    out.setdefault(part.strip(), path)
    return out


def _font_path(name, bold):
    """Файл шрифта по имени: известные файлы, затем реестр (обычное или
    жирное начертание) или None."""
    if name in _FONT_FILES:
        return os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts",
                            _FONT_FILES[name][1 if bold else 0])
    fonts = _installed_fonts()
    order = (" bold", "", " regular") if bold else ("", " regular", " bold")
    return next((fonts[name + s] for s in order if name + s in fonts), None)


@functools.lru_cache(maxsize=32)
def _font(name, bold):
    """PIL-шрифт (em 100) для имени шрифта текста или None."""
    from PIL import ImageFont
    name = str(_api.montage_project.resolve_font(name) or "").strip().lower()
    if name == "karaoke rounded":
        import karaoke.style
        path = str(karaoke.style.FONT_FILE)
    else:
        path = _font_path(name, bold)
    if not path:
        return None
    try:
        return ImageFont.truetype(path, 100)
    except OSError:
        return None


def text_width(text, style):
    """Ширина текста в единицах холста ASS при кегле style.size (vertical —
    ширина самого широкого знака столбца)."""
    if style.get("vertical"):
        flat = dict(style, vertical=False)
        return max((text_width(ch, flat) for ch in text if not ch.isspace()), default=0.0)
    size = float(style.get("size", 48))
    sx = float(style.get("scale_x", 100)) / 100.0
    f = _font(style.get("font"), bool(style.get("bold")))
    if f is None:
        font = str(style.get("font") or "").lower()
        k = 0.42 if any(n in font for n in _NARROW) else 0.56
        return len(text) * size * k * sx
    asc, desc = f.getmetrics()
    return f.getlength(text) * size / float(asc + desc) * sx


def fit_size(text, style, width, px, py, res_x, res_y):
    """Кегль, при котором текст (самая широкая строка; столбец vertical — и
    по высоте) входит в блок width (доля кадра) и не вылезает за край кадра
    от центра (px, py)."""
    size = float(style.get("size", 48))
    room = min(float(width), 2.0 * min(px, 1.0 - px) * 0.96) * res_x
    ww = max((text_width(line, style) for line in str(text).split("\n")), default=0.0)
    k = room / ww if ww > room > 0 else 1.0
    if style.get("vertical"):
        n = sum(1 for ch in str(text) if not ch.isspace())
        tall = 2.0 * min(py, 1.0 - py) * 0.96 * res_y
        if n * size > tall > 0:
            k = min(k, tall / (n * size))
    return round(size * k, 2) if k < 1.0 else size


def word_items(words, opts, res_x, res_y):
    """Тексты проекта (словари для parse_texts) для слов [(t, end, текст)]."""
    layout = opts.get("layout", "stack")
    if layout not in LAYOUTS:
        raise ValueError(f"layout — одно из {', '.join(LAYOUTS)}")
    base = {"size": 48, "align": 5, "animation": "pop", "in_s": 0.12, "bold": False,
            "outline": 0, "shadow": 0}
    base.update(opts.get("style") or {})
    emph, emph_at = {}, {}
    for k, v in (opts.get("emphasis") or {}).items():
        k = str(k)
        if k.startswith("#") and k[1:].lstrip("-").isdigit():
            emph_at[int(k[1:])] = v
        else:
            emph[_key(k)] = v
    case = opts.get("case", "")
    gap = float(opts.get("gap", 0.6))
    hold = float(opts.get("hold", 0.15))
    px, py = (opts.get("pos") or [0.5, 0.5])[:2]
    width = float(opts.get("width", 0.8)) * res_x
    line_gap = float(opts.get("line_gap", 1.0))
    layer = opts.get("layer")
    phrases, cur = [], []
    for w in words:
        if cur and w[0] - cur[-1][1] > gap:
            phrases.append(cur)
            cur = []
        cur.append(w)
    if cur:
        phrases.append(cur)
    out = []
    for ph in phrases:
        end = ph[-1][1] + hold
        styled = []
        for i, (t, e, text) in enumerate(ph, 1):
            if case == "upper":
                text = text.upper()
            elif case == "lower":
                text = text.lower()
            st = dict(base)
            st.update(emph.get(_key(text), {}))
            st.update(emph_at.get(i, emph_at.get(i - len(ph) - 1, {})))
            styled.append((t, e, text, st))
        if layout == "single":
            for i, (t, e, text, st) in enumerate(styled):
                nxt = styled[i + 1][0] if i + 1 < len(styled) else end
                # Слово шире блока или кадра от своей точки — кегль меньше.
                st = dict(st, size=fit_size(text, st, width / res_x, px, py, res_x, res_y))
                out.append(_item(t, max(nxt, t + 0.05), text, st, px, py, layer))
            continue
        # Блок выше 90 % кадра или шире кадра (от точки pos до края) — кегли
        # фразы меньше шагами (с мелким кеглем в строку входит больше слов —
        # строк становится меньше).
        sized, k = styled, 1.0
        lines, heights = _lines(sized, layout, width, line_gap)
        room = 2.0 * min(px, 1.0 - px) * 0.96 * res_x
        while k > 0.25 and (sum(heights) > 0.9 * res_y
                            or max(rw for _r, rw in lines) > room):
            k *= 0.93
            sized = [(t, e, text, dict(st, size=round(float(st["size"]) * k, 2)))
                     for t, e, text, st in styled]
            lines, heights = _lines(sized, layout, width, line_gap)
        top = py * res_y - sum(heights) / 2.0
        for (r, rw), lh in zip(lines, heights):
            cy = top + lh / 2.0
            left = px * res_x - rw / 2.0
            for (t, e, text, st), x0, ww in r:
                out.append(_item(t, end, text, st, (left + x0 + ww / 2.0) / res_x, cy / res_y,
                                 layer))
            top += lh
    return out


def _lines(styled, layout, width, line_gap):
    """Строки фразы [(слова [(слово, x от начала строки, ширина)], ширина
    строки)] и высоты строк; stack переносит по ширине width."""
    lines, row, row_w = [], [], 0.0
    for item in styled:
        st = item[3]
        ww = text_width(item[2], st)
        sp = max(text_width(" ", st), 0.12 * float(st["size"])) if row else 0.0
        if layout == "stack" and row and row_w + sp + ww > width:
            lines.append((row, row_w))
            row, row_w, sp = [], 0.0, 0.0
        row.append((item, row_w + sp, ww))
        row_w += sp + ww
    if row:
        lines.append((row, row_w))
    heights = [max(float(i[0][3]["size"]) for i in r) * line_gap for r, _w in lines]
    return lines, heights


def _item(t, end, text, st, x, y, layer):
    d = {"start": round(t, 6), "end": round(max(end, t + 0.05), 6), "text": text,
         "style": st, "pos_x": round(x, 6), "pos_y": round(y, 6)}
    if layer is not None:
        d["layer"] = int(layer)
    return d


def project_words(p, t0, t1):
    """Метки word проекта на [t0, t1): [(t, конец, текст)]."""
    out = []
    for m in sorted(p.markers, key=lambda m: m.t):
        if m.kind == "word" and t0 - 1e-6 <= m.t < t1 and m.label.strip():
            out.append((m.t, m.end if m.end is not None else m.t + 0.3, m.label.strip()))
    return out


def text_canvas(p):
    """Холст текста проекта (как в графе): PlayResY 288."""
    w, h, _fps = p.output_format()
    return max(16, int(round(288 * w / float(h)))), 288


def _add_items(p, raw):
    """Тексты raw (словари parse_texts) — в проект; их id."""
    items = _api.montage_project.parse_texts(raw)
    bad = sorted({k for r, it in zip(raw, items) for k in r["style"] if k not in it.style})
    if len(items) != len(raw) or bad:
        raise ValueError(f"стиль слов: неверные ключи или значения {bad} (schema: text_style)")
    p.texts = sorted(p.texts + items, key=lambda t: (t.start, t.end))
    return [t.id for t in items]


def _window_words(p, op, resolve):
    t0 = resolve(op.get("from", 0.0))
    t1 = resolve(op["to"]) if "to" in op else float("inf")
    words = project_words(p, t0, t1 + 1e-6)
    if not words:
        raise ValueError("нет меток word в отрезке (analyze --kinds word --write)")
    return words


def add_words(p, op, resolve):
    """Операция words: тексты проекта; их id."""
    words = _window_words(p, op, resolve)
    res_x, res_y = text_canvas(p)
    return _add_items(p, word_items(words, op, res_x, res_y))


def read_lyrics(path):
    """Строки текста песни: [[(показ, ключ), …], …] — без пустых строк и
    заголовков в скобках; знаки без букв приклеиваются к соседнему слову."""
    if os.path.getsize(path) > LYRICS_MAX_BYTES:
        raise ValueError("файл текста больше 1 МБ")
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            raw = f.read()
    except UnicodeDecodeError:
        with open(path, "r", encoding="cp1251") as f:
            raw = f.read()
    lines = []
    for line in raw.splitlines():
        if not line.strip() or _HEADER_RX.fullmatch(line):
            continue
        toks, prefix = [], ""
        for w in line.split():
            if not _key(w):
                if toks:
                    toks[-1][0] += " " + w
                else:
                    prefix += w + " "
                continue
            toks.append([prefix + w, _key(w)])
            prefix = ""
        if toks:
            lines.append([tuple(t) for t in toks])
    return lines


def align_lyrics(lines, words):
    """Строки файла (read_lyrics) против слов отрезка [(t, конец, текст)]:
    ([(номер строки с 1, [(t, конец, показ)])], доля слов отрезка, нашедших
    похожее слово файла). Только строки найденного куска текста."""
    from rapidfuzz import fuzz
    toks = [(n, show, key) for n, line in enumerate(lines, 1) for show, key in line]
    heard = [_key(w[2]) for w in words]
    nf, nw = len(toks), len(heard)
    sim = [[fuzz.ratio(tk[2], h) / 100.0 for h in heard] for tk in toks]
    # Начало строки файла охотнее встаёт на слово после паузы в пении.
    starts = [i == 0 or toks[i - 1][0] != toks[i][0] for i in range(nf)]
    pauses = [j == 0 or words[j][0] - words[j - 1][1] >= _PAUSE for j in range(nw)]

    def gain(i, j):
        r = sim[i][j]
        g = _MATCH if r >= 0.85 else _NEAR if r >= 0.6 else _SUB
        return g + _LINE_BONUS if starts[i] and pauses[j] else g

    # D[i][j] — лучший счёт: слова файла до i (начало куска свободно) против
    # первых j слов отрезка; ход 0 — пара, 1 — пропуск слова файла, 2 — услышанного.
    score = [[0.0] * (nw + 1) for _ in range(nf + 1)]
    move = [[0] * (nw + 1) for _ in range(nf + 1)]
    for j in range(1, nw + 1):
        score[0][j], move[0][j] = j * _GAP, 2
    for i in range(1, nf + 1):
        for j in range(1, nw + 1):
            best, mv = score[i - 1][j - 1] + gain(i - 1, j - 1), 0
            if score[i - 1][j] + _GAP > best:
                best, mv = score[i - 1][j] + _GAP, 1
            if score[i][j - 1] + _GAP > best:
                best, mv = score[i][j - 1] + _GAP, 2
            score[i][j], move[i][j] = best, mv
    i, j = max(range(nf + 1), key=lambda k: score[k][nw]), nw
    pairs = {}
    while j > 0 and i > 0:
        mv = move[i][j]
        if mv == 0:
            pairs[i - 1] = j - 1
            i, j = i - 1, j - 1
        elif mv == 1:
            i -= 1
        else:
            j -= 1
    if not pairs:
        return [], 0.0
    first, last = min(pairs), max(pairs)
    times = {i: (words[j][0], words[j][1]) for i, j in pairs.items()}
    # Крайние строки куска — целиком: их слова до первой пары и после
    # последней (обычно ослышка в начале или конце отрезка) берут время
    # соседних непарных слов отрезка, а если их нет рядом — шаг соседа.
    lo, hi = first, last
    while lo > 0 and toks[lo - 1][0] == toks[first][0]:
        lo -= 1
        j = pairs[first] - (first - lo)
        nxt = times[lo + 1][0]
        if j >= 0 and nxt - words[j][1] < _EDGE_GAP and words[j][0] < nxt:
            times[lo] = (words[j][0], min(words[j][1], nxt))
        else:
            step = min(_EDGE_STEP, times[lo + 1][1] - nxt)
            times[lo] = (nxt - max(step, 0.05), nxt)
    while hi + 1 < nf and toks[hi + 1][0] == toks[last][0]:
        hi += 1
        j = pairs[last] + (hi - last)
        prev = times[hi - 1][1]
        if j < nw and words[j][0] - prev < _EDGE_GAP and words[j][1] > prev:
            times[hi] = (max(words[j][0], prev), words[j][1])
        else:
            step = min(_EDGE_STEP, prev - times[hi - 1][0])
            times[hi] = (prev, prev + max(step, 0.05))
    first, last = lo, hi
    span = range(first, last + 1)
    for i in span:
        if i in times:
            continue
        a = max(k for k in times if k < i)
        b = min(k for k in times if k > i)
        # Слова без пары делят промежуток между соседями по длине.
        lens = [len(toks[k][2]) for k in range(a + 1, b)]
        t0, t1 = times[a][1], times[b][0]
        if t1 - t0 < _MIN_WORD * (b - a - 1):
            # Соседи вплотную: слова без пары делят и вторую половину левого.
            t0 = min(t0, (times[a][0] + times[a][1]) / 2.0)
            t1 = max(t1, t0)
        acc = sum(lens[:i - a - 1])
        times[i] = (t0 + (t1 - t0) * acc / sum(lens),
                    t0 + (t1 - t0) * (acc + lens[i - a - 1]) / sum(lens))
    phrases = []
    for i in span:
        n, show, _k = toks[i]
        if not phrases or phrases[-1][0] != n:
            phrases.append((n, []))
        phrases[-1][1].append((times[i][0], max(times[i][1], times[i][0] + 0.05), show))
    near = sum(1 for i, j in pairs.items() if sim[i][j] >= 0.6)
    return phrases, near / float(nw)


def lyric_items(phrases, opts, res_x, res_y):
    """Тексты строк [(номер, слова)]: строка — фраза word_items; reveal line —
    все слова строки появляются в её начале. Строка держится не дольше
    начала следующей (не наезжает на неё в той же точке)."""
    reveal = opts.get("reveal", "word")
    if reveal not in REVEALS:
        raise ValueError(f"reveal — одно из {', '.join(REVEALS)}")
    o = dict(opts, gap=float("inf"))
    out = []
    for k, (_n, ws) in enumerate(phrases):
        if reveal == "line":
            ws = [(ws[0][0], e, text) for _t, e, text in ws]
        items = word_items(ws, o, res_x, res_y)
        if k + 1 < len(phrases):
            cap = phrases[k + 1][1][0][0] - 0.02
            for it in items:
                it["end"] = round(max(min(it["end"], cap), it["start"] + 0.05), 6)
        out.extend(items)
    return out


def _word_span(span):
    """words операции lyrics: [a, b] — слова строки с a по b (с 1, включительно)."""
    try:
        a, b = (int(x) for x in span)
    except (TypeError, ValueError):
        a = b = 0
    if not 1 <= a <= b:
        raise ValueError("words — [первое, последнее] слово строки, счёт с 1")
    return a, b


def add_lyrics(p, op, resolve):
    """Операция lyrics: строки файла op.file по меткам word отрезка
    [from, to) → тексты проекта; {texts, lines, match}."""
    path = os.path.abspath(str(op.get("file") or ""))
    if not os.path.isfile(path):
        raise ValueError(f"нет файла текста {path}")
    words = _window_words(p, op, resolve)
    lines = read_lyrics(path)
    if not lines:
        raise ValueError("в файле нет строк текста")
    want = op.get("lines")
    if want:
        # Выравнивание только по этим строкам: повтор припева в другом месте
        # файла и посторонние строки не перетянут кусок; номера — прежние.
        want = {int(n) for n in want}
        lines = [line if n in want else [] for n, line in enumerate(lines, 1)]
    phrases, match = align_lyrics(lines, words)
    if op.get("words"):
        a, b = _word_span(op["words"])
        phrases = [(n, ws[a - 1:b]) for n, ws in phrases if ws[a - 1:b]]
    if not phrases:
        raise ValueError("строки файла не нашлись в отрезке")
    lead = float(op.get("lead", 0.0))
    if lead:
        phrases = [(n, [(t - lead, e, text) for t, e, text in ws]) for n, ws in phrases]
    res_x, res_y = text_canvas(p)
    ids = _add_items(p, lyric_items(phrases, op, res_x, res_y))
    return {"texts": ids, "lines": [n for n, _ws in phrases], "match": round(match, 3)}
