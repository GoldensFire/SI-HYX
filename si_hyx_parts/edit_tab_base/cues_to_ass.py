# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_cues_to_ass. Public namespace: edit_tab_base."""
import edit_tab_base as _api


def _cues_to_ass(cues):
    """Собирает реплики в .ass. `cues` — список словарей {start,end,text,style};
    `style` уже разрешён (переопределение реплики или общий стиль по умолчанию —
    см. SubtitleCreatorDialog._effective_style). У каждой реплики СВОЙ именованный
    Style (без де-дупликации: так проще и надёжнее, чем сравнивать стили).
    Позиция/анимация — часть самого файла (Alignment + override-теги), а не
    «стиля вшивания», поэтому действует и в превью (libass), и при вшивании
    (ffmpeg -vf subtitles), независимо от выбора «Стиль вшитых субтитров»."""
    styles_txt = []
    events = []
    for i, c in enumerate(cues):
        name = f"Cue{i}"
        style = c['style']
        styles_txt.append(_api._style_line(name, style))
        txt = c['text'].replace("{", "｛").replace("}", "｝")
        txt = txt.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\N")
        align = int(style.get('align') or 2)
        anim_tag = _api._animation_override_tags(
            style.get('animation', 'none'), align, max(0.01, c['end'] - c['start']))
        events.append(f"Dialogue: 0,{_api._ass_timestamp(c['start'])},{_api._ass_timestamp(c['end'])},"
                       f"{name},,0,0,0,,{anim_tag}{txt}")
    return _api._ASS_TEMPLATE.format(styles="\n".join(styles_txt), events="\n".join(events))

_cues_to_ass.__module__ = _api.__name__
_api._cues_to_ass = _cues_to_ass
