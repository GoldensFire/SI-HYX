# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
# error_report.py — единый диалог ошибки с кнопкой «Сообщить об ошибке».
#
# Диалог максимально простой: показывает текст ошибки + кнопку «Сообщить об
# ошибке». По нажатию в ТОМ ЖЕ окне разворачивается поле «Описание
# (необязательно)» и чекбокс «приложить тех. данные»; «Отправить» шлёт JSON
# POST-ом на ERROR_REPORT_URL (Cloudflare Worker) в фоновом потоке, не вешая UI.

import json
import platform
import threading
import urllib.request

from PyQt6.QtCore import Qt, QObject, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QPlainTextEdit, QCheckBox, QWidget, QStyle,
)

try:
    from config import APP_VERSION, ERROR_REPORT_URL
except Exception:        # pragma: no cover — на случай частичной сборки
    APP_VERSION = "?"
    ERROR_REPORT_URL = ""


class _Emitter(QObject):
    """Мостик из фонового потока отправки обратно в GUI-поток."""
    done = pyqtSignal(bool, str)


def _post_report(url: str, payload: dict, emitter: "_Emitter"):
    ok, err = False, ""
    try:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, method="POST",
            headers={"Content-Type": "application/json",
                     "User-Agent": f"SI-HYX/{APP_VERSION}"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            ok = 200 <= getattr(resp, "status", 200) < 300
            if not ok:
                err = f"HTTP {getattr(resp, 'status', '?')}"
    except Exception as e:
        err = str(e)
    emitter.done.emit(ok, err)


class ErrorReportDialog(QDialog):
    """Диалог ошибки с встроенной отправкой отчёта.

    title   — заголовок окна;
    summary — короткий текст для пользователя («Обрезка завершилась с ошибкой…»);
    detail  — техническое описание/код/трейсбек (уходит в отчёт, пользователю
              показывается компактно);
    where   — где произошло («Монтаж: обрезка», «Критическая ошибка» …).
    """

    def __init__(self, title, summary, detail="", where="", parent=None,
                 report_detail=None):
        super().__init__(parent)
        self.setWindowTitle(title or "Ошибка")
        self.setMinimumWidth(440)
        self._summary = summary or ""
        self._detail = detail or ""
        # Что уходит в отчёт как «error» (может быть полнее показанного detail —
        # напр. полный трейсбек при краше, тогда как в окне видна короткая строка).
        self._report_detail = report_detail if report_detail is not None else (detail or summary)
        self._where = where or ""
        self._emitter = None
        self._thread = None

        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        # ── Заголовок: иконка ошибки + текст ───────────────────────────────
        top = QHBoxLayout()
        top.setSpacing(10)
        ic = QLabel()
        try:
            px = self.style().standardIcon(
                QStyle.StandardPixmap.SP_MessageBoxCritical).pixmap(40, 40)
            ic.setPixmap(px)
        except Exception:
            pass
        ic.setAlignment(Qt.AlignmentFlag.AlignTop)
        top.addWidget(ic, 0)
        msg = QLabel(self._summary)
        msg.setWordWrap(True)
        msg.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        top.addWidget(msg, 1)
        lay.addLayout(top)

        if self._detail:
            det = QLabel(self._detail)
            det.setWordWrap(True)
            det.setStyleSheet("color:#a6adc8; font-size:11px;")
            det.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            lay.addWidget(det)

        # ── Блок отчёта (скрыт до клика «Сообщить об ошибке») ───────────────
        self._report_box = QWidget()
        rb = QVBoxLayout(self._report_box)
        rb.setContentsMargins(0, 0, 0, 0)
        rb.setSpacing(6)
        rb.addWidget(QLabel("Описание (необязательно):"))
        self._desc = QPlainTextEdit()
        self._desc.setPlaceholderText(
            "Что вы делали, когда возникла ошибка? Какой файл? (можно оставить пустым)")
        self._desc.setFixedHeight(84)
        rb.addWidget(self._desc)
        self._attach = QCheckBox("Приложить тех. данные (версия, ОС, текст ошибки)")
        self._attach.setChecked(True)
        rb.addWidget(self._attach)
        self._report_box.setVisible(False)
        lay.addWidget(self._report_box)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setVisible(False)
        lay.addWidget(self._status)

        # ── Кнопки ─────────────────────────────────────────────────────────
        row = QHBoxLayout()
        self.btn_report = QPushButton("Сообщить об ошибке")
        self.btn_report.clicked.connect(self._reveal_report)
        self.btn_send = QPushButton("Отправить")
        self.btn_send.clicked.connect(self._send)
        self.btn_send.setVisible(False)
        self.btn_close = QPushButton("OK")
        self.btn_close.setDefault(True)
        self.btn_close.clicked.connect(self.accept)
        if not ERROR_REPORT_URL:
            self.btn_report.setEnabled(False)
            self.btn_report.setToolTip("Адрес приёма отчётов не настроен (ERROR_REPORT_URL).")
        row.addWidget(self.btn_report)
        row.addStretch(1)
        row.addWidget(self.btn_send)
        row.addWidget(self.btn_close)
        lay.addLayout(row)

    # ── Шаги ────────────────────────────────────────────────────────────────
    def _reveal_report(self):
        self.btn_report.setVisible(False)
        self._report_box.setVisible(True)
        self.btn_send.setVisible(True)
        self._desc.setFocus()
        self.adjustSize()

    def _set_status(self, text, color="#a6adc8"):
        self._status.setText(text)
        self._status.setStyleSheet(f"color:{color}; font-size:12px;")
        self._status.setVisible(bool(text))

    def _send(self):
        if not ERROR_REPORT_URL:
            return
        payload = {"description": self._desc.toPlainText().strip()}
        if self._attach.isChecked():
            payload.update({
                "version": APP_VERSION,
                "os": platform.platform(),
                "where": self._where,
                "error": self._report_detail,
            })
        self.btn_send.setEnabled(False)
        self._attach.setEnabled(False)
        self._desc.setReadOnly(True)
        self._set_status("Отправка отчёта…")
        self._emitter = _Emitter()
        self._emitter.done.connect(self._on_sent)
        self._thread = threading.Thread(
            target=_post_report, args=(ERROR_REPORT_URL, payload, self._emitter),
            daemon=True)
        self._thread.start()

    def _on_sent(self, ok, err):
        if ok:
            self._set_status("✓ Спасибо! Отчёт отправлен.", "#a6e3a1")
            self.btn_send.setVisible(False)
            self.btn_close.setText("Закрыть")
        else:
            self._set_status(
                "Не удалось отправить отчёт"
                + (f": {err}" if err else "") + ". Проверьте интернет и попробуйте снова.",
                "#f38ba8")
            self.btn_send.setEnabled(True)
            self._attach.setEnabled(True)
            self._desc.setReadOnly(False)


def show_error(summary, detail="", where="", title="Ошибка", parent=None):
    """Удобный шорткат: создать и показать модально ErrorReportDialog."""
    dlg = ErrorReportDialog(title, summary, detail=detail, where=where, parent=parent)
    return dlg.exec()
