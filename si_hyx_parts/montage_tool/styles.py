# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Стили AMV: docs/amv-styles/<имя>.json — ритм, отделка частей, роли
текста и карточки, снятые с эталона. Public namespace: montage_tool.

Стиль — JSON-объект (описание словами — <имя>.md рядом):
  name, title, summary — имя (как у файла), заголовок, суть стиля;
  rhythm   {"beats": {подпись части: долей на план, "default": …},
            "lead_frames": рез раньше доли на N кадров, "min_shot": с} —
           autofill --style: места резов по частям с этим шагом;
  sections {подпись части: {"effects": [эффекты клипа], "cycle": [[эффекты],
            …] — клипам части по очереди (тонировка разными цветами),
            "transition", "transition_s"}} — клипам части (середина клипа в
            части);
  finish   эффекты всего кадра (settings.finish);
  text     роли текста {роль: {"style": {…}, ключи операции words/lyrics/
           text по умолчанию: layout, pos, width, case, reveal, lead, gap,
           hold, line_gap, emphasis, layer}}; "font" — имя или список имён:
           берётся первый установленный (последний — запасной);
  cards    карточки op card {вид: {"text": роль, "length", "background":
           {…} (cards.card_background), "glitch": доля сбоя или 0}}.
Операции edit text/words/lyrics берут роль ключом "preset":
"provant.hook" (стиль.роль), card — вид карточки так же; свои ключи
операции и её style — поверх роли."""
import json
import os
import re

import montage_tool as _api

STYLE_MAX_BYTES = 1 << 20
# Имя стиля и роли — только так: имя склеивается с папкой стилей.
_NAME_RX = re.compile(r"[a-z0-9][a-z0-9_\-]{0,40}")
_REF_RX = re.compile(r"([a-z0-9][a-z0-9_\-]{0,40})\.([a-z0-9][a-z0-9_\-]{0,40})")


def styles_dir():
    return os.path.join(os.path.dirname(os.path.abspath(_api.__file__)), "docs", "amv-styles")


def style_path(name):
    """Файл стиля: путь к .json или имя из папки стилей."""
    name = str(name or "").strip()
    if name.lower().endswith(".json") and os.path.isfile(name):
        return os.path.abspath(name)
    if not _NAME_RX.fullmatch(name):
        raise _api.ToolError("usage", f"стиль: имя из docs/amv-styles или путь к .json, не {name!r}")
    path = os.path.join(styles_dir(), name + ".json")
    if not os.path.isfile(path):
        have = ", ".join(s["name"] for s in list_styles()) or "нет"
        raise _api.ToolError("usage", f"нет стиля {name} (есть: {have})")
    return path


def load_style(name):
    """Стиль (словарь) по имени или пути; шрифты ролей не разрешены."""
    path = style_path(name)
    if os.path.getsize(path) > STYLE_MAX_BYTES:
        raise _api.ToolError("usage", f"файл стиля больше 1 МБ: {path}")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        raise _api.ToolError("usage", f"стиль не прочитан: {e}") from e
    if not isinstance(data, dict):
        raise _api.ToolError("usage", "стиль — JSON-объект")
    data.setdefault("name", os.path.splitext(os.path.basename(path))[0])
    data["path"] = path
    return data


def list_styles():
    """Стили папки: [{name, title, summary, roles, cards}]."""
    out = []
    folder = styles_dir()
    for fn in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        stem, ext = os.path.splitext(fn)
        if ext.lower() != ".json" or not _NAME_RX.fullmatch(stem):
            continue
        try:
            st = load_style(stem)
        except _api.ToolError:
            continue
        if not isinstance(st.get("text"), dict) and not isinstance(st.get("rhythm"), dict):
            continue                     # не стиль (скелет эталона и т.п.)
        out.append({"name": stem, "title": st.get("title", ""), "summary": st.get("summary", ""),
                    "roles": sorted((st.get("text") or {}).keys()),
                    "cards": sorted((st.get("cards") or {}).keys())})
    return out


def _installed(name):
    """Шрифт есть в системе (имя или псевдоним, как его найдёт libass)."""
    from si_hyx_parts.montage_tool import typography as _ty
    low = str(_api.montage_project.resolve_font(name) or "").strip().lower()
    if not low:
        return False
    if low in _ty._FONT_FILES or low == "karaoke rounded":
        return True
    fonts = _ty._installed_fonts()
    return any(low + s in fonts for s in ("", " regular", " bold", " обычный", " полужирный"))


def _glyph(f, ch):
    from PIL import Image, ImageDraw
    img = Image.new("L", (160, 160))
    ImageDraw.Draw(img).text((10, 10), ch, font=f, fill=255)
    return img.tobytes()


def _covers(name, bold, sample):
    """В файле шрифта есть знаки sample (кроме ASCII: латиницу libass всё
    равно найдёт); файла не нашлось — считается, что есть. Нет знака —
    рисуется .notdef (пустой или квадрат), как у заведомо чужого U+10FFFD."""
    from si_hyx_parts.montage_tool import typography as _ty
    chars = sorted({ch for ch in sample if ord(ch) > 127 and not ch.isspace()})[:60]
    if not chars:
        return True
    f = _ty._font(name, bool(bold))
    if f is None:
        return True
    missing, blank = _glyph(f, "\U0010fffd"), bytes(160 * 160)
    return all(g not in (missing, blank) for g in (_glyph(f, ch) for ch in chars))


def pick_font(font, sample="", bold=False):
    """Имя шрифта: строка — как есть; список — первый установленный, в
    котором есть знаки sample (урезанный файл без кандзи libass подменил бы
    готикой), иначе первый установленный, иначе последний (запасной)."""
    if isinstance(font, str):
        return font
    names = [str(x) for x in font or [] if str(x).strip()]
    if not names:
        return None
    have = [n for n in names if _installed(n)]
    return next((n for n in have if _covers(n, bold, sample)), have[0] if have else names[-1])


def _resolved(style, sample=""):
    st = dict(style or {})
    if "font" in st:
        font = pick_font(st["font"], sample, st.get("bold", False))
        if font:
            st["font"] = font
        else:
            st.pop("font")
    return st


def style_role(ref, section="text", sample=""):
    """Роль стиля по ссылке «стиль.роль» (section — text или cards): копия
    словаря роли, шрифты разрешены под текст sample."""
    m = _REF_RX.fullmatch(str(ref or "").strip())
    if not m:
        raise ValueError(f"preset — «стиль.роль» (provant.hook), не {ref!r}")
    st = load_style(m.group(1))
    roles = st.get(section) or {}
    spec = roles.get(m.group(2))
    if not isinstance(spec, dict):
        raise ValueError(f"в стиле {m.group(1)} нет {'роли' if section == 'text' else 'карточки'} "
                         f"{m.group(2)} (есть: {', '.join(sorted(roles)) or 'нет'})")
    out = json.loads(json.dumps(spec))
    if section == "text":
        out["style"] = _resolved(out.get("style"), sample)
        for k, v in list((out.get("emphasis") or {}).items()):
            out["emphasis"][k] = _resolved(v, sample)
    else:
        out["_style"] = m.group(1)
    return out


def apply_preset(op, sample=""):
    """Операция text/words/lyrics с ключом preset → операция с ключами роли
    под своими: style и emphasis — слиянием, остальное — ключ операции важнее.
    sample — текст операции: шрифт из списка роли — с его знаками."""
    if "preset" not in op:
        return op
    spec = style_role(op["preset"], sample=sample)
    out = {k: v for k, v in spec.items() if k not in ("style", "emphasis")}
    out.update({k: v for k, v in op.items() if k not in ("preset", "style", "emphasis")})
    out["style"] = dict(spec.get("style") or {}, **_resolved(op.get("style"), sample))
    emph = dict(spec.get("emphasis") or {})
    for k, v in (op.get("emphasis") or {}).items():
        emph[k] = dict(emph.get(k) or {}, **_resolved(v, sample))
    if emph:
        out["emphasis"] = emph
    if op.get("op") == "text" and "pos" in out and "pos_x" not in out:
        out["pos_x"], out["pos_y"] = out.pop("pos")[:2]
    return out


def style_report(name):
    """Стиль для ответа команды styles: роли с выбранными шрифтами — для
    латиницы и для кандзи (не первый в списке — желанного шрифта нет)."""
    st = load_style(name)
    fonts = {}
    for r, spec in (st.get("text") or {}).items():
        style = spec.get("style") or {} if isinstance(spec, dict) else {}
        want = style.get("font")
        if not want:
            continue
        first = want if isinstance(want, str) else want[0]
        fonts[r] = {s: {"font": f, "first_choice": f == first}
                    for s, f in (("latin", pick_font(want, "", style.get("bold"))),
                                 ("kanji", pick_font(want, "幻惑の対価問う原罪", style.get("bold"))))}
    return {"style": st, "fonts": fonts}
