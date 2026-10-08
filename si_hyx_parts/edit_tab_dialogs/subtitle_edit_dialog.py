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
