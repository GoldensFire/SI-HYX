# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""EditTab: _subtitles_vf. Public namespace: edit_tab."""
import edit_tab as _api


def _subtitles_vf(self, src, ext_sub=None, burn_idx=-1):
    """Фильтр ffmpeg `subtitles=…` для вшивания выбранной дорожки, или None.

        Одно место на оба пути экспорта: собственную перекодировку Монтажа
        (_execute_cut) и «перекодировать настройками «Обработки»» (там тот же
        фильтр уезжает в ProcessWorker, см. _execute_cut_and_process).

        libass рендерит ASS со всеми стилями; для родных ШРИФТОВ извлекаем
        вложенные attachments контейнера и отдаём их через :fontsdir."""
    if ext_sub:
        esc = self._escape_filter_path(ext_sub)
        vf = f"subtitles='{esc}'"
        sub_codec = _api.os.path.splitext(ext_sub)[1].lower().lstrip('.')
    else:
        if burn_idx is None or burn_idx < 0:
            return None
        esc = self._escape_filter_path(src)
        vf = f"subtitles='{esc}':si={burn_idx}"
        try:
            sub_codec = (self._sub_streams[burn_idx].get('codec_name') or '').lower()
        except Exception:
            sub_codec = ''
    # Стиль вшиваемых субтитров — по выбору пользователя (cmb_sub_style):
    #   0 Авто      — стиль программы для SRT/VTT/mov_text, у ASS/SSA свой;
    #   1 Программа — насильно стиль программы даже поверх ASS/SSA;
    #   2 Оригинал  — ничего не навязываем (ASS/SSA — свой стиль, SRT/VTT —
    #                 стиль libass по умолчанию).
    try:
        style_choice = int(self.cmb_sub_style.currentIndex())
    except Exception:
        style_choice = 0
    native_styled = sub_codec in ('ass', 'ssa')
    if style_choice == 1:
        apply_prog_style = True
    elif style_choice == 2:
        apply_prog_style = False
    else:
        apply_prog_style = not native_styled
    if apply_prog_style:
        # Белый жирный шрифт с чёрной обводкой — РОВНО как в превью монтажа.
        # Превью рисует текст высотой 5.2% кадра (см. VideoCanvas.paintEvent
        # px=...*0.052). Текстовые субтитры libass рендерит в скрипте 384×288
        # (дефолт libav) и масштабирует до кадра, поэтому Fontsize=15 даёт
        # 15/288 ≈ 5.2% высоты кадра НА ЛЮБОМ разрешении. Прежний Fontsize=28
        # давал ~2× (на FullHD субтитры «огромные» — это и был баг).
        style = ("FontName=Arial,Fontsize=15,Bold=1,"
                 "PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
                 "BorderStyle=1,Outline=1,Shadow=0,MarginV=14")
        vf += f":force_style='{style}'"
    fonts_dir = self._extract_subtitle_fonts(src)
    if fonts_dir:
        fesc = self._escape_filter_path(fonts_dir)
        vf += f":fontsdir='{fesc}'"
    return vf

def _burn_subs_spec(self, src, in_s):
    """Описание вшивания субтитров для вкладки «Обработка», или None.

        Возвращает {'vf': <фильтр subtitles=…>, 'src_offset': <секунды>}.

        `src_offset` — это разница между временем ИСХОДНИКА и временем
        фильтрграфа у ProcessWorker. Он режет отрезок быстрым входным
        pre-seek'ом (см. _trim_seek_args), а входной seek обнуляет тайминги в
        своей точке — фильтр же subtitles ищет реплики по времени САМОГО файла
        субтитров. Без поправки текст уехал бы на (in_s − PRESEEK) секунд.
        Саму поправку накладывает ProcessWorker (setpts вокруг фильтра): только
        он знает, какой pre-seek выбрал."""
    vf = self._subtitles_vf(src, self.selected_sub_ext_path,
                            self.cmb_subs.currentIndex() - 1)
    if not vf:
        return None
    return {'vf': vf, 'src_in': float(max(0.0, in_s))}
