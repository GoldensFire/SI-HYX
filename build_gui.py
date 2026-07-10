# -*- coding: utf-8 -*-
"""GUI-обёртка над build.bat: правит версию и флаг «необязательного обновления»
(SILENT_UPDATE) в config.py, синхронизирует version_info.txt и README.md, затем
запускает build.bat и показывает лог сборки в реальном времени.

Инструмент для разработчика (используется вручную перед релизом) — часть
самой программы SI-HYX не задействует. Запуск: `python build_gui.py`.
"""
import os
import re
import subprocess
import sys

from PyQt6.QtCore import QProcess, QProcessEnvironment
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

from config import STYLESHEET, get_icon

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_PY = os.path.join(ROOT, "config.py")
VERSION_INFO_TXT = os.path.join(ROOT, "version_info.txt")
README_MD = os.path.join(ROOT, "README.md")
BUILD_BAT = os.path.join(ROOT, "build.bat")

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def _write(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def read_current():
    """Текущие версия и флаг SILENT_UPDATE из config.py (единственный источник правды)."""
    text = _read(CONFIG_PY)
    m = re.search(r'^APP_VERSION = "([\d.]+)"', text, re.M)
    version = m.group(1) if m else "0.0.0"
    m = re.search(r"^SILENT_UPDATE = (True|False)", text, re.M)
    silent = (m.group(1) == "True") if m else False
    return version, silent


def apply_settings(version: str, silent: bool) -> None:
    """Пишет версию + флаг во все файлы, где они должны совпадать
    (см. main.py:_check_updates / make_manifest.py про SILENT_UPDATE)."""
    text = _read(CONFIG_PY)
    text = re.sub(r'^APP_VERSION = "[\d.]+"', f'APP_VERSION = "{version}"', text, flags=re.M)
    text = re.sub(r"^SILENT_UPDATE = (True|False)", f"SILENT_UPDATE = {silent}", text, flags=re.M)
    _write(CONFIG_PY, text)

    x, y, z = version.split(".")
    text = _read(VERSION_INFO_TXT)
    text = re.sub(r"filevers=\(\d+, \d+, \d+, \d+\)", f"filevers=({x}, {y}, {z}, 0)", text)
    text = re.sub(r"prodvers=\(\d+, \d+, \d+, \d+\)", f"prodvers=({x}, {y}, {z}, 0)", text)
    text = re.sub(r"(StringStruct\('FileVersion', ')[\d.]+(')", rf"\g<1>{x}.{y}.{z}.0\g<2>", text)
    text = re.sub(r"(StringStruct\('ProductVersion', ')[\d.]+(')", rf"\g<1>{x}.{y}.{z}.0\g<2>", text)
    _write(VERSION_INFO_TXT, text)

    text = _read(README_MD)
    text = re.sub(r"Текущая версия — \*\*[\d.]+\*\*", f"Текущая версия — **{version}**", text)
    text = re.sub(r"SI-HYX-v[\d.]+-full\.zip", f"SI-HYX-v{version}-full.zip", text)
    _write(README_MD, text)


class BuildWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SI-HYX — сборка")
        self.resize(820, 600)

        c = QWidget()
        self.setCentralWidget(c)
        root = QVBoxLayout(c)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        row = QHBoxLayout()
        row.addWidget(QLabel("Версия:"))
        self.version_edit = QLineEdit()
        self.version_edit.setFixedWidth(90)
        row.addWidget(self.version_edit)
        row.addSpacing(16)
        self.silent_chk = QCheckBox(
            "Необязательное обновление (silent) — без авто-плашки, только вручную")
        row.addWidget(self.silent_chk)
        row.addStretch()
        root.addLayout(row)

        hint = QLabel(
            "Релиз на GitHub остаётся обычным (не draft/pre-release) — новые скачивания "
            "получают именно его.\nФлаг влияет только на то, всплывает ли авто-плашка "
            "у уже установленных пользователей.")
        hint.setStyleSheet("color:#6c7086;")
        root.addWidget(hint)

        btn_row = QHBoxLayout()
        self.build_btn = QPushButton("Собрать")
        self.build_btn.setObjectName("b_run")
        self.build_btn.setIcon(get_icon('fa5s.hammer', color='#1e1e2e'))
        self.build_btn.clicked.connect(self._on_build)
        btn_row.addWidget(self.build_btn)
        self.stop_btn = QPushButton("Стоп")
        self.stop_btn.setIcon(get_icon('fa5s.stop'))
        self.stop_btn.clicked.connect(self._on_stop)
        self.stop_btn.setEnabled(False)
        btn_row.addWidget(self.stop_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        self.status_lbl = QLabel("")
        root.addWidget(self.status_lbl)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        root.addWidget(self.log, stretch=1)

        version, silent = read_current()
        self.version_edit.setText(version)
        self.silent_chk.setChecked(silent)

        self.proc = None
        self._stopped = False

    # -- логирование --------------------------------------------------
    def _log(self, line: str) -> None:
        self.log.appendPlainText(line)

    # -- сборка ---------------------------------------------------------
    def _on_build(self):
        version = self.version_edit.text().strip()
        if not VERSION_RE.match(version):
            QMessageBox.critical(self, "SI-HYX", "Версия должна быть в формате X.Y.Z, например 0.5.3")
            return
        silent = self.silent_chk.isChecked()
        try:
            apply_settings(version, silent)
        except Exception as e:
            QMessageBox.critical(self, "SI-HYX", f"Не удалось обновить файлы версии: {e}")
            return

        self._stopped = False
        self.build_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.status_lbl.setText(
            f"Сборка {version}{' (необязательное обновление)' if silent else ''}…")
        self.log.clear()

        env = QProcessEnvironment.systemEnvironment()
        env.insert("NONINTERACTIVE", "1")
        self.proc = QProcess(self)
        self.proc.setWorkingDirectory(ROOT)
        self.proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.proc.setProcessEnvironment(env)
        self.proc.readyReadStandardOutput.connect(self._on_proc_output)
        self.proc.finished.connect(self._on_build_done)
        self.proc.start("cmd", ["/c", BUILD_BAT])

    def _on_proc_output(self):
        data = bytes(self.proc.readAllStandardOutput()).decode("utf-8", "replace")
        for line in data.splitlines():
            self._log(line)

    def _on_stop(self):
        if self.proc is None or self.proc.state() == QProcess.ProcessState.NotRunning:
            return
        self._stopped = True
        self._log("[СТОП] Останавливаю сборку…")
        # cmd /c + дочерние pyinstaller/powershell — обычный proc.kill() убивает
        # только cmd.exe, а не всё дерево процессов. taskkill /T добивает дерево.
        pid = self.proc.processId()
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                creationflags=subprocess.CREATE_NO_WINDOW,
                capture_output=True,
            )
        except Exception:
            self.proc.kill()

    def _on_build_done(self, exit_code: int, _exit_status):
        self.build_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        if self._stopped:
            self.status_lbl.setText("Остановлено.")
            return
        if exit_code == 0:
            self.status_lbl.setText("Готово.")
            QMessageBox.information(
                self, "SI-HYX",
                "Сборка завершена. Архивы и manifest.json — в dist\\ "
                "(список файлов для релиза — в конце лога).")
        else:
            self.status_lbl.setText(f"Сборка упала (код {exit_code}).")
            QMessageBox.critical(self, "SI-HYX", f"Сборка завершилась с ошибкой (код {exit_code}). Смотри лог.")

    def closeEvent(self, event):
        if self.proc is not None and self.proc.state() != QProcess.ProcessState.NotRunning:
            if QMessageBox.question(
                self, "SI-HYX", "Сборка ещё идёт. Всё равно закрыть окно?"
            ) != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self._on_stop()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLESHEET)
    win = BuildWindow()
    win.show()
    sys.exit(app.exec())
