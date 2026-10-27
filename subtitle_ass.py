# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
# subtitle_ass.py — ASS-субтитры из реплик: стиль программы, строки стилей,
# теги анимации и сам файл; без Qt.
"""ASS-субтитры из реплик без Qt.

Жили в edit_tab_base (он импортирует Qt и реэкспортирует их под прежними
именами): «Создать субтитры» и вшивание вкладки «Монтаж» и текст проекта
montage_project (вшивается после склейки, во времени проекта) собирают .ass
одними и теми же функциями.

Программный стиль субтитров = караоке генерации паков (karaoke/style.py):
шрифт Karaoke Rounded, почти белый текст, тёмная обводка и полупрозрачная
тень; размеры — в единицах ASS при PlayResY 288 (холст, на котором ffmpeg
вшивает SRT)."""
from karaoke import style as _karaoke_style

PROG_SUB_FONTSIZE = 21          # кегль ASS: em ≈ 5.3 % высоты кадра
PROG_SUB_MARGIN_V = 14          # отступ снизу ≈ 4.9 % высоты кадра


def _style_num(style, key, default):
    """Число из стиля реплики; нет ключа (стиль сохранён до караоке-вида) или
    он пуст — прежнее значение по умолчанию."""
    try:
        value = style.get(key)
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


def _prog_sub_style():
    """Программный стиль субтитров Монтажа (см. PROG_SUB_FONTSIZE): стиль
    «Создать субтитры» по умолчанию — он и есть караоке-стиль."""
    return dict(DEFAULT_SUBTITLE_STYLE)


def prog_sub_force_style(play_res_y=None, play_res_x=None, keep_layout=False):
    """force_style ffmpeg-фильтра subtitles для программного стиля. Тот же
    список (через запятую) превью отдаёт своей libass — ass_set_style_overrides,
    — поэтому субтитры в плеере и во вшитом файле одни.

    play_res_y/play_res_x — холст самой дорожки: у SRT/VTT это 384×288 (холст,
    на котором их рендерит ffmpeg), у ASS — её PlayResY/PlayResX. Без пересчёта
    кегль 21 на холсте 1080 вышел бы вчетверо мельче.

    Поля вида из стиля ASS, которых нет у программного, сбрасываются явно:
    иначе оставались бы от оригинала — ScaleY 60 сплющивал шрифт караоке.
    ScaleX/ScaleY у force_style libass — доли (1 = 100 %), не проценты, как
    в самом файле.

    keep_layout — у дорожки своя раскладка (ASS/SSA): выравнивание и отступы
    стилей остаются её, как в оригинале (надписи сверху, реплики сбоку),
    программный только вид. Иначе — снизу по центру с отступом программы."""
    st = _prog_sub_style()
    k = float(play_res_y or _ASS_PLAYRES_Y) / _ASS_PLAYRES_Y
    kx = float(play_res_x or _ASS_PLAYRES_X) / _ASS_PLAYRES_X

    def num(v, scale=k):
        return f"{float(v) * scale:.2f}".rstrip("0").rstrip(".")

    layout = ("" if keep_layout else
              f"Alignment=2,MarginL={num(_ASS_MARGIN_L, kx)},"
              f"MarginR={num(_ASS_MARGIN_R, kx)},"
              f"MarginV={num(PROG_SUB_MARGIN_V)},")
    return (f"FontName={_karaoke_style.FONT_NAME},Fontsize={num(st['size'])},Bold=1,"
            f"Italic=0,Underline=0,StrikeOut=0,ScaleX=1,ScaleY=1,Spacing=0,Angle=0,"
            f"PrimaryColour={_hex_to_ass_color(st['color'])},"
            f"OutlineColour={_hex_to_ass_color(st['outline_color'])},"
            f"BackColour={_hex_to_ass_color('#000000', st['shadow_alpha'])},"
            f"BorderStyle=1,Outline={num(st['outline'])},Shadow={num(st['shadow'])},"
            f"{layout}ScaledBorderAndShadow=yes")


def _ass_timestamp(t):
    """Секунды → таймкод ASS «H:MM:SS.cc» (сотые доли, без ведущего нуля у часов)."""
    t = max(0.0, float(t))
    h = int(t // 3600); m = int((t % 3600) // 60); s = t - h * 3600 - m * 60
    return f"{h:d}:{m:02d}:{s:05.2f}"

def _hex_to_ass_color(hex_color, alpha=0x00):
    """«#RRGGBB» → цвет ASS «&HAABBGGRR» (порядок байт обратный HTML)."""
    hc = (hex_color or "#FFFFFF").lstrip('#')
    if len(hc) != 6:
        hc = "FFFFFF"
    r, g, b = hc[0:2], hc[2:4], hc[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


# Стиль субтитров по умолчанию (используется, пока у реплики нет собственного
# переопределения — см. SubtitleCreatorDialog._effective_style). Это же —
# программный стиль Монтажа (_prog_sub_style): караоке-вид из karaoke/style.py
# с кеглем субтитров. Обводка и тень у караоке заданы для кегля BASE_SIZE —
# здесь пропорционально меньше. 'outline'/'shadow' — в единицах ASS; у старых
# сохранённых стилей их нет, и там действуют прежние 1 и 0 (см. _style_line).
DEFAULT_SUBTITLE_STYLE = {
    'font': _karaoke_style.FONT_NAME, 'size': PROG_SUB_FONTSIZE, 'bold': True,
    'italic': False, 'underline': False, 'align': 2, 'spacing': 0,
    'color': '#' + _karaoke_style.TEXT_COLOUR,
    'outline_color': '#' + _karaoke_style.OUTLINE_COLOUR,
    'outline': round(PROG_SUB_FONTSIZE * _karaoke_style.OUTLINE
                     / _karaoke_style.BASE_SIZE, 2),
    'shadow': round(PROG_SUB_FONTSIZE * _karaoke_style.SHADOW
                    / _karaoke_style.BASE_SIZE, 2),
    'shadow_alpha': _karaoke_style.SHADOW_ALPHA,
    'animation': 'none',
}
_ASS_PLAYRES_X, _ASS_PLAYRES_Y = 384, 288
_ASS_MARGIN_L, _ASS_MARGIN_R, _ASS_MARGIN_V = 10, 10, 20


def _animation_override_tags(anim, align, duration_s, play_res=None, margins=None):
    """Строит override-теги ASS ({\\...}) для простой анимации появления —
    fade/slide/pop. Тайминг анимации — треть длительности реплики (но не больше
    300мс и не меньше 50мс), чтобы короткие реплики не «залипали» в анимации.
    play_res/margins — холст и отступы файла (по умолчанию свои 384×288)."""
    if anim not in ('fade', 'slide', 'pop'):
        return ''
    res_x, res_y = play_res or (_ASS_PLAYRES_X, _ASS_PLAYRES_Y)
    m_l, m_r, m_v = margins or (_ASS_MARGIN_L, _ASS_MARGIN_R, _ASS_MARGIN_V)
    dur_ms = max(10, int(round(duration_s * 1000)))
    t = min(300, max(50, dur_ms // 3))
    if anim == 'fade':
        return f"{{\\fad({t},{t})}}"
    if anim == 'pop':
        return f"{{\\fscx0\\fscy0\\t(0,{t},\\fscx100\\fscy100)}}"
    # slide: анкер — точка, куда libass поместил бы текст по Alignment (см.
    # обычные формулы ASS для \pos/\move), старт — со смещением за пределы
    # кадра со стороны, соответствующей горизонтали/вертикали выравнивания.
    row = (align - 1) // 3; col = (align - 1) % 3
    x = res_x / 2 if col == 1 else (m_l if col == 0 else res_x - m_r)
    y = res_y - m_v if row == 0 else (res_y / 2 if row == 1 else m_v)
    off_x, off_y = 60 * res_x / _ASS_PLAYRES_X, 40 * res_y / _ASS_PLAYRES_Y
    if col == 0:
        x0, y0 = -off_x, y
    elif col == 2:
        x0, y0 = res_x + off_x, y
    elif row == 0:
        x0, y0 = x, res_y + off_y
    elif row == 2:
        x0, y0 = x, -off_y
    else:
        x0, y0 = x, y
    return f"{{\\move({x0:.0f},{y0:.0f},{x:.0f},{y:.0f},0,{t})}}"

def _style_line(name, style):
    font = style.get('font') or DEFAULT_SUBTITLE_STYLE['font']
    size = int(style.get('size') or DEFAULT_SUBTITLE_STYLE['size'])
    bold = 1 if style.get('bold') else 0
    italic = 1 if style.get('italic') else 0
    underline = 1 if style.get('underline') else 0
    spacing = int(style.get('spacing') or 0)
    align = int(style.get('align') or 2)
    primary = _hex_to_ass_color(style.get('color') or '#FFFFFF')
    outline = _hex_to_ass_color(style.get('outline_color') or '#000000')
    # Толщина обводки и тень: у стилей, сохранённых до караоке-вида, ключей
    # нет — им остаются прежние Outline 1 и Shadow 0.
    border = f"{_style_num(style, 'outline', 1):g},{_style_num(style, 'shadow', 0):g}"
    back = _hex_to_ass_color('#000000', int(_style_num(style, 'shadow_alpha', 0)))
    # Растяжение — у реплик, взятых из стилей ASS при правке (см.
    # subtitle_style.editor_style); у своих стилей его нет — 100 %.
    scale = f"{_style_num(style, 'scale_x', 100):g},{_style_num(style, 'scale_y', 100):g}"
    return (f"Style: {name},{font},{size},{primary},&H000000FF,{outline},{back},"
            f"{bold},{italic},{underline},0,{scale},{spacing},0,1,{border},{align},"
            f"{_ASS_MARGIN_L},{_ASS_MARGIN_R},{_ASS_MARGIN_V},1")


_ASS_TEMPLATE = (
    "[Script Info]\n"
    "ScriptType: v4.00+\n"
    f"PlayResX: {_ASS_PLAYRES_X}\n"
    f"PlayResY: {_ASS_PLAYRES_Y}\n"
    "WrapStyle: 0\n"
    "ScaledBorderAndShadow: yes\n\n"
    "[V4+ Styles]\n"
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
    "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, "
    "ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
    "MarginL, MarginR, MarginV, Encoding\n"
    "{styles}\n\n"
    "[Events]\n"
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    "{events}\n"
)


def _cues_to_ass(cues, play_res=None):
    """Собирает реплики в .ass. `cues` — список словарей {start,end,text,style};
    `style` уже разрешён (переопределение реплики или общий стиль по умолчанию —
    см. SubtitleCreatorDialog._effective_style). У каждой реплики СВОЙ именованный
    Style (без де-дупликации: так проще и надёжнее, чем сравнивать стили).
    Позиция/анимация — часть самого файла (Alignment + override-теги), а не
    «стиля вшивания», поэтому действует и в превью (libass), и при вшивании
    (ffmpeg -vf subtitles), независимо от выбора «Стиль вшитых субтитров».

    play_res — холст (PlayResX, PlayResY) вместо своих 384×288: у кадра
    другой формы (9:16) libass растягивал бы буквы. У реплики может быть
    'tags' — готовые override-теги вместо анимации стиля (позиция текста
    проекта, montage_project); 'raw' — готовый текст реплики с тегами
    (кинетический текст проекта, экранирован там же)."""
    styles_txt = []
    events = []
    for i, c in enumerate(cues):
        name = f"Cue{i}"
        style = c['style']
        styles_txt.append(_style_line(name, style))
        if 'raw' in c:
            events.append(f"Dialogue: 0,{_ass_timestamp(c['start'])},{_ass_timestamp(c['end'])},"
                          f"{name},,0,0,0,,{c['raw']}")
            continue
        txt = c['text'].replace("{", "｛").replace("}", "｝")
        txt = txt.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\N")
        align = int(style.get('align') or 2)
        anim_tag = c.get('tags') or _animation_override_tags(
            style.get('animation', 'none'), align, max(0.01, c['end'] - c['start']),
            play_res=play_res)
        events.append(f"Dialogue: 0,{_ass_timestamp(c['start'])},{_ass_timestamp(c['end'])},"
                       f"{name},,0,0,0,,{anim_tag}{txt}")
    text = _ASS_TEMPLATE.format(styles="\n".join(styles_txt), events="\n".join(events))
    if play_res:
        text = text.replace(f"PlayResX: {_ASS_PLAYRES_X}\n", f"PlayResX: {int(play_res[0])}\n", 1)
        text = text.replace(f"PlayResY: {_ASS_PLAYRES_Y}\n", f"PlayResY: {int(play_res[1])}\n", 1)
    return text
