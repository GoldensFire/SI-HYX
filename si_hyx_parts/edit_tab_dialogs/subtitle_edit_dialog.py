# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""SubtitleEditDialog. Public namespace: edit_tab_dialogs."""
import edit_tab_dialogs as _api


class SubtitleEditDialog(_api.QDialog):
    """Простой редактор субтитров в формате SRT. Сохранение НЕ трогает оригинал —
    EditTab записывает результат в отдельный .srt и делает его активной дорожкой,
    так что и превью, и вшивание при обрезке используют отредактированный текст."""

    def __init__(self, srt_text, parent=None, current_time_s=None):
        super().__init__(parent)
        self.setWindowTitle("Редактирование субтитров")
        self.resize(660, 540)
        self.setStyleSheet(f"""
            QDialog {{ background: {_api.C['bg']}; }}
            QLabel {{ color: {_api.C['text2']}; font-size: 12px; }}
            QPlainTextEdit {{
                background: {_api.C['surface3']}; color: {_api.C['text']};
                border: 1px solid {_api.C['border2']}; border-radius: 6px;
                padding: 6px; selection-background-color: {_api.C['accent']};
            }}
            QPushButton {{
                background: {_api.C['surface3']}; color: {_api.C['text']};
                border: 1px solid {_api.C['border2']}; border-radius: 6px;
                padding: 6px 16px;
            }}
            QPushButton:hover {{ background: {_api.C['border2']}; border-color: {_api.C['accent']}; }}
        """)
        lay = _api.QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 12)
        lay.setSpacing(8)
        info = _api.QLabel(
            "Формат SRT: номер реплики, строка тайм-кода "
            "«00:00:01,000 --> 00:00:03,000», затем текст; реплики разделяются "
            "пустой строкой. Оригинальный файл не изменяется.")
        info.setWordWrap(True)
        lay.addWidget(info)
        self.editor = _api.QPlainTextEdit()
        self.editor.setPlainText(srt_text)
        mono = _api.QFont("Consolas" if _api.os.name == 'nt' else "Monospace")
        mono.setPointSize(10)
        self.editor.setFont(mono)
        self.editor.setLineWrapMode(_api.QPlainTextEdit.LineWrapMode.WidgetWidth)
        lay.addWidget(self.editor, 1)
        bb = _api.QDialogButtonBox(_api.QDialogButtonBox.StandardButton.Save
                              | _api.QDialogButtonBox.StandardButton.Cancel)
        bb.button(_api.QDialogButtonBox.StandardButton.Save).setText("Сохранить")
        bb.button(_api.QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        if current_time_s is not None:
            self._scroll_to_time(current_time_s)

    def _scroll_to_time(self, t):
        """Ставит курсор на реплику, которая играет в момент `t` (или ближайшую
        следующую) — чтобы диалог открывался не с начала файла, а с места,
        где сейчас находится воспроизведение в Монтаже."""
        import re
        text = self.editor.toPlainText()
        time_re = re.compile(
            r'(\d{1,2}):(\d{2}):(\d{2})[.,](\d{1,3})\s*-->\s*'
            r'(\d{1,2}):(\d{2}):(\d{2})[.,](\d{1,3})')

        def _s(h, m, s, ms):
            return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0

        items = []
        for m in time_re.finditer(text):
            start = _s(*m.groups()[0:4])
            end = _s(*m.groups()[4:8])
            items.append((start, end, m.start()))
        if not items:
            return
        pos = next((p for s, e, p in items if s <= t <= e), None)
        if pos is None:
            pos = next((p for s, e, p in items if s >= t), None)
        if pos is None:
            pos = items[-1][2]
        cursor = self.editor.textCursor()
        cursor.setPosition(pos)
        self.editor.setTextCursor(cursor)
        self.editor.ensureCursorVisible()

    def text(self):
        return self.editor.toPlainText()

SubtitleEditDialog.__module__ = _api.__name__
_api.SubtitleEditDialog = SubtitleEditDialog

class SubtitleCreatorDialog(_api.QDialog):
    """Создание субтитров с нуля — интерфейс в духе Filmora: тулбар стиля текста
    сверху, слева живое превью с транспортом, справа вкладки Субтитр/Пресет/
    Настройка/Анимация, снизу таймлайн с перетаскиваемыми блоками реплик.

    Стиль/позиция/анимация хранятся ПО РЕПЛИКЕ (self._cues[i]['style']) поверх
    общего стиля по умолчанию (self._default_style) — см. _effective_style.
    Правка тулбара/вкладок пишет в стиль ВЫБРАННОЙ реплики, а если ничего не
    выбрано — в общий стиль по умолчанию; «Применить ко всем» копирует
    эффективный стиль текущей реплики на все остальные."""

    _POS_LABELS = {
        7: "↖", 8: "↑", 9: "↗",
        4: "←", 5: "•", 6: "→",
        1: "↙", 2: "↓", 3: "↘",
    }
    _ANIM_CHOICES = [
        ('none', 'Без анимации'),
        ('fade', 'Появление (fade)'),
        ('slide', 'Выезд (slide)'),
        ('pop', 'Всплытие (pop)'),
    ]

    from si_hyx_parts.edit_tab_dialogs.subtitle_creator_dialog___init import (
        __init__,
        _register_shortcuts,
        btn_step_back_click,
        btn_step_fwd_click,
    )

    # ── Undo/redo (Ctrl+Z/Ctrl+Y, ЛЮБАЯ раскладка клавиатуры) ────────────────
    # QKeySequence/QShortcut сопоставляют события по УЖЕ переведённому раскладкой
    # Qt-коду клавиши: на кириллице физическая Z даёт Qt-код кириллической «Я», а
    # не Key_Z, и никакой QKeySequence("Ctrl+Я")-строкой это надёжно не ловится
    # (что и подтвердил повторный баг-репорт — QKeySequence-подход в Монтаже был
    # исправлен только для латиницы). Настоящее решение — как WASD-пан в photo-
    # редакторе (tabs.py, _pan_dir_from_event): читать ФИЗИЧЕСКУЮ клавишу через
    # nativeVirtualKey (Windows VK_Z=0x5A, VK_Y=0x59), это не зависит от раскладки.
    # Событие сюда доходит только если фокусный виджет его НЕ обработал сам —
    # у QPlainTextEdit/QLineEdit есть свой Ctrl+Z для текста, и они событие
    # поглощают раньше, так что предпочтение отдаётся штатному текстовому undo.
    _VK_Z = 0x5A
    _VK_Y = 0x59
    _VK_W = 0x57
    _VK_A = 0x41
    _VK_S = 0x53
    _VK_D = 0x44

    from si_hyx_parts.edit_tab_dialogs.subtitle_creator_dialog_key_press_event import (
        keyPressEvent,
        _snapshot,
        _push_undo,
        _restore_snapshot,
        undo,
        redo,
    )

    # ── Тулбар стиля текста ──────────────────────────────────────────────────
    # Все элементы тулбара — ОДНОЙ высоты (_TOOLBAR_H), иначе QFontComboBox/
    # QSpinBox (высокие по natural sizeHint из-за padding в QSS) и QToolButton
    # (раньше был ниже, 24px) выстраивались по верхнему краю неровно.
    _TOOLBAR_H = 28

    from si_hyx_parts.edit_tab_dialogs.subtitle_creator_dialog__build_toolbar import (
        _build_toolbar,
        _on_media_duration,
        _on_font_changed,
        _on_halign_clicked,
        _build_subtitle_tab,
        _rebuild_list,
        _build_row_widget,
        _on_row_text_changed,
        _on_list_current_changed,
        _build_preset_tab,
        _refresh_preset_list,
        _save_as_preset,
        _apply_selected_preset,
        _delete_selected_preset,
        _build_settings_tab,
        _pick_pos,
        _make_color_btn,
        _set_color_swatch,
        _pick_text_color,
        _pick_outline_color,
        _build_animation_tab,
        _on_anim_changed,
        _effective_style,
    )

    from si_hyx_parts.edit_tab_dialogs.subtitle_creator_dialog__style_edit import (
        _style_edit,
        _apply_style_to_all,
        _refresh_all_style_ui,
        _add_cue,
        _duplicate_cue,
        _delete_cue,
        _select_cue,
        _resync_all,
        _on_timeline_cue_changed,
        _on_timeline_view_changed,
        _on_tl_scroll_changed,
        _active_cue_at,
        _on_accept,
        last_style,
        cues,
    )

SubtitleCreatorDialog.__module__ = _api.__name__
_api.SubtitleCreatorDialog = SubtitleCreatorDialog

class _PixelizeDialog(_api.QDialog):
    """Настройка эффекта «проявление из пикселей»: число шагов и стартовый размер
    блока. Превью показывает, как блок мельчает по шагам до чёткой картинки."""

    def __init__(self, steps=6, block=64, parent=None,
                 image_mode=False, duration=5.0, fps=25):
        super().__init__(parent)
        self._image_mode = bool(image_mode)
        self.setWindowTitle("Пикселизация — проявление")
        self.setStyleSheet(f"""
            QDialog {{ background: {_api.C['bg']}; }}
            QLabel {{ color: {_api.C['text2']}; font-size: 12px; }}
            QSpinBox {{
                background: {_api.C['surface3']}; color: {_api.C['text']};
                border: 1px solid {_api.C['border2']}; border-radius: 6px;
                padding: 5px 8px; font-size: 13px; min-width: 64px;
            }}
            QSpinBox:focus {{ border-color: {_api.C['accent']}; }}
            QPushButton {{
                background: {_api.C['surface3']}; color: {_api.C['text']};
                border: 1px solid {_api.C['border2']}; border-radius: 6px;
                padding: 6px 16px;
            }}
            QPushButton:hover {{ background: {_api.C['border2']}; border-color: {_api.C['accent']}; }}
        """)
        lay = _api.QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 12); lay.setSpacing(10)
        if self._image_mode:
            info = _api.QLabel(
                "Из картинки получится ВИДЕО: кадр начнётся крупными «пикселями» и за "
                "несколько шагов прояснится. Задай длительность ролика и параметры "
                "проявления. Готовое видео сохранится кнопкой «Обрезать».")
        else:
            info = _api.QLabel(
                "Видео начнётся крупными «пикселями» и с каждым шагом будет становиться "
                "чётче, пока не прояснится полностью. Идеально для угадайки. Эффект "
                "применяется при «Обрезать» и требует перекодировки.")
        info.setWordWrap(True); lay.addWidget(info)

        # Для картинки нужна длительность результата (у изображения её нет) и FPS.
        self.sp_dur = None; self.sp_fps = None
        if self._image_mode:
            rowd = _api.QHBoxLayout(); rowd.setSpacing(8)
            rowd.addWidget(_api.QLabel("Длительность видео, сек"))
            self.sp_dur = _api.QSpinBox(); self.sp_dur.setRange(1, 120)
            self.sp_dur.setValue(max(1, int(round(float(duration)))))
            rowd.addStretch(1); rowd.addWidget(self.sp_dur)
            lay.addLayout(rowd)

            rowf = _api.QHBoxLayout(); rowf.setSpacing(8)
            rowf.addWidget(_api.QLabel("Кадров в секунду (FPS)"))
            self.sp_fps = _api.QSpinBox(); self.sp_fps.setRange(1, 60)
            self.sp_fps.setValue(max(1, int(fps)))
            rowf.addStretch(1); rowf.addWidget(self.sp_fps)
            lay.addLayout(rowf)

        row1 = _api.QHBoxLayout(); row1.setSpacing(8)
        row1.addWidget(_api.QLabel("Число шагов проявления"))
        self.sp_steps = _api.QSpinBox(); self.sp_steps.setRange(1, 20); self.sp_steps.setValue(int(steps))
        row1.addStretch(1); row1.addWidget(self.sp_steps)
        lay.addLayout(row1)

        row2 = _api.QHBoxLayout(); row2.setSpacing(8)
        row2.addWidget(_api.QLabel("Начальный размер блока, px"))
        self.sp_block = _api.QSpinBox(); self.sp_block.setRange(4, 256)
        self.sp_block.setSingleStep(4); self.sp_block.setValue(int(block))
        row2.addStretch(1); row2.addWidget(self.sp_block)
        lay.addLayout(row2)

        self.preview = _api.QLabel()
        self.preview.setWordWrap(True)
        self.preview.setStyleSheet(f"color: {_api.C['text3']}; font-size: 11px; font-weight: 700;")
        lay.addWidget(self.preview)

        self.sp_steps.valueChanged.connect(self._update_preview)
        self.sp_block.valueChanged.connect(self._update_preview)
        self._update_preview()

        bb = _api.QDialogButtonBox(_api.QDialogButtonBox.StandardButton.Ok
                              | _api.QDialogButtonBox.StandardButton.Cancel)
        bb.button(_api.QDialogButtonBox.StandardButton.Ok).setText("Применить")
        bb.button(_api.QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _update_preview(self):
        seq = _api._pixelize_block_sequence(self.sp_block.value(), self.sp_steps.value())
        parts = [f"{b}px" if b > 1 else "чётко" for b in seq]
        self.preview.setText("Блоки по шагам:   " + "   →   ".join(parts))

    def values(self):
        return int(self.sp_steps.value()), int(self.sp_block.value())

    def image_values(self):
        """Длительность (сек) и FPS — только в режиме картинки."""
        dur = int(self.sp_dur.value()) if self.sp_dur is not None else 5
        fps = int(self.sp_fps.value()) if self.sp_fps is not None else 25
        return dur, fps

_PixelizeDialog.__module__ = _api.__name__
_api._PixelizeDialog = _PixelizeDialog
