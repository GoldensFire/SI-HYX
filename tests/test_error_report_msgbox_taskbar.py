# -*- coding: utf-8 -*-
"""Тесты error_report.py, msgbox.py, taskbar.py (Qt-диалоги и нативные обёртки)."""
import pytest

import error_report
import taskbar


# ── _post_report (сетевая отправка отчёта) ───────────────────────────────────
class _FakeUrlResp:
    def __init__(self, status=200):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass


@pytest.mark.qt
class TestPostReport:
    def _collect(self, qapp):
        results = []
        emitter = error_report._Emitter()
        emitter.done.connect(lambda ok, err: results.append((ok, err)))
        return emitter, results

    def test_success(self, qapp, monkeypatch):
        monkeypatch.setattr(error_report.urllib.request, "urlopen",
                            lambda req, timeout=None: _FakeUrlResp(200))
        emitter, results = self._collect(qapp)
        error_report._post_report("https://report.example/", {"a": 1}, emitter)
        qapp.processEvents()
        assert results[0][0] is True

    def test_http_error_status(self, qapp, monkeypatch):
        monkeypatch.setattr(error_report.urllib.request, "urlopen",
                            lambda req, timeout=None: _FakeUrlResp(500))
        emitter, results = self._collect(qapp)
        error_report._post_report("https://report.example/", {}, emitter)
        qapp.processEvents()
        ok, err = results[0]
        assert not ok and "500" in err

    def test_network_exception(self, qapp, monkeypatch):
        def boom(req, timeout=None):
            raise OSError("нет соединения")
        monkeypatch.setattr(error_report.urllib.request, "urlopen", boom)
        emitter, results = self._collect(qapp)
        error_report._post_report("https://report.example/", {}, emitter)
        qapp.processEvents()
        ok, err = results[0]
        assert not ok and "нет соединения" in err

    def test_payload_serialized_as_json(self, qapp, monkeypatch):
        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["data"] = req.data
            captured["headers"] = req.headers
            return _FakeUrlResp(200)
        monkeypatch.setattr(error_report.urllib.request, "urlopen", fake_urlopen)
        emitter, _ = self._collect(qapp)
        error_report._post_report("https://report.example/",
                                  {"описание": "тест"}, emitter)
        import json
        assert json.loads(captured["data"].decode("utf-8")) == {"описание": "тест"}
        assert "Content-type" in captured["headers"]


# ── ErrorReportDialog ────────────────────────────────────────────────────────
@pytest.mark.qt
class TestErrorReportDialog:
    def test_construction(self, qapp):
        dlg = error_report.ErrorReportDialog(
            "Заголовок", "Что-то сломалось", detail="код 42", where="Тест")
        try:
            assert dlg.windowTitle() == "Заголовок"
            assert dlg._summary == "Что-то сломалось"
            assert dlg._report_detail == "код 42"
            # блок отчёта скрыт до клика
            assert dlg._report_box.isVisibleTo(dlg) is False
            assert dlg.btn_send.isVisibleTo(dlg) is False
        finally:
            dlg.deleteLater()

    def test_report_detail_defaults_to_detail(self, qapp):
        dlg = error_report.ErrorReportDialog("t", "summary", detail="деталь")
        assert dlg._report_detail == "деталь"
        dlg.deleteLater()

    def test_report_detail_falls_back_to_summary(self, qapp):
        dlg = error_report.ErrorReportDialog("t", "только сводка")
        assert dlg._report_detail == "только сводка"
        dlg.deleteLater()

    def test_explicit_report_detail(self, qapp):
        dlg = error_report.ErrorReportDialog(
            "t", "s", detail="кратко", report_detail="полный трейсбек")
        assert dlg._report_detail == "полный трейсбек"
        dlg.deleteLater()

    def test_reveal_report(self, qapp):
        dlg = error_report.ErrorReportDialog("t", "s")
        try:
            dlg._reveal_report()
            assert dlg._report_box.isVisibleTo(dlg) is True
            assert dlg.btn_send.isVisibleTo(dlg) is True
            assert dlg.btn_report.isVisibleTo(dlg) is False
        finally:
            dlg.deleteLater()

    def test_report_button_disabled_without_url(self, qapp, monkeypatch):
        monkeypatch.setattr(error_report, "ERROR_REPORT_URL", "")
        dlg = error_report.ErrorReportDialog("t", "s")
        try:
            assert dlg.btn_report.isEnabled() is False
        finally:
            dlg.deleteLater()

    def test_send_no_url_noop(self, qapp, monkeypatch):
        monkeypatch.setattr(error_report, "ERROR_REPORT_URL", "")
        dlg = error_report.ErrorReportDialog("t", "s")
        try:
            dlg._send()  # не должно бросить и не должно запускать поток
            assert dlg._thread is None
        finally:
            dlg.deleteLater()

    def test_send_starts_thread(self, qapp, monkeypatch):
        monkeypatch.setattr(error_report, "ERROR_REPORT_URL", "https://r.example/")
        started = {}

        def fake_post(url, payload, emitter):
            started["url"] = url
            started["payload"] = payload
            emitter.done.emit(True, "")
        monkeypatch.setattr(error_report, "_post_report", fake_post)
        dlg = error_report.ErrorReportDialog("t", "s", where="Монтаж")
        try:
            dlg._reveal_report()
            dlg._desc.setPlainText("моё описание")
            dlg._send()
            if dlg._thread:
                dlg._thread.join(timeout=2)
            qapp.processEvents()
            assert started["url"] == "https://r.example/"
            assert started["payload"]["description"] == "моё описание"
            assert started["payload"]["where"] == "Монтаж"
        finally:
            dlg.deleteLater()

    def test_send_without_attach(self, qapp, monkeypatch):
        monkeypatch.setattr(error_report, "ERROR_REPORT_URL", "https://r.example/")
        captured = {}
        monkeypatch.setattr(error_report, "_post_report",
                            lambda u, p, e: captured.update(p) or e.done.emit(True, ""))
        dlg = error_report.ErrorReportDialog("t", "s")
        try:
            dlg._reveal_report()
            dlg._attach.setChecked(False)
            dlg._send()
            if dlg._thread:
                dlg._thread.join(timeout=2)
            assert "version" not in captured  # тех. данные не приложены
            assert "description" in captured
        finally:
            dlg.deleteLater()

    def test_on_sent_success(self, qapp):
        dlg = error_report.ErrorReportDialog("t", "s")
        try:
            dlg._on_sent(True, "")
            assert "Спасибо" in dlg._status.text()
            assert dlg.btn_close.text() == "Закрыть"
        finally:
            dlg.deleteLater()

    def test_on_sent_failure(self, qapp):
        dlg = error_report.ErrorReportDialog("t", "s")
        try:
            dlg._reveal_report()
            dlg._on_sent(False, "таймаут")
            assert "Не удалось" in dlg._status.text()
            assert "таймаут" in dlg._status.text()
            assert dlg.btn_send.isEnabled() is True
        finally:
            dlg.deleteLater()


# ── msgbox.py ────────────────────────────────────────────────────────────────
@pytest.mark.qt
class TestMsgbox:
    def _patch_exec(self, monkeypatch):
        import msgbox
        from PyQt6.QtWidgets import QMessageBox
        captured = {}

        def fake_exec(self):
            captured["icon"] = self.icon()
            captured["title"] = self.windowTitle()
            captured["text"] = self.text()
            captured["buttons"] = self.standardButtons()
            captured["flags"] = self.textInteractionFlags()
            # _selectable_box теперь читает clickedButton()/standardButton() после
            # exec() (не полагается на возвращаемое exec() значение напрямую —
            # нужно, чтобы отличить клик по «Копировать» от реальной кнопки), так
            # что здесь ЖМЁМ настоящую кнопку Ok — это реально вызывает Qt-логику
            # clickedButton(), а не просто подделывает return value.
            ok_btn = self.button(QMessageBox.StandardButton.Ok)
            if ok_btn is not None:
                ok_btn.click()
            return QMessageBox.StandardButton.Ok
        monkeypatch.setattr(QMessageBox, "exec", fake_exec)
        return captured

    def test_critical(self, qapp, monkeypatch):
        import msgbox
        from PyQt6.QtWidgets import QMessageBox
        from PyQt6.QtCore import Qt
        cap = self._patch_exec(monkeypatch)
        msgbox.msgbox_critical(None, "Ошибка", "Текст ошибки")
        assert cap["icon"] == QMessageBox.Icon.Critical
        assert cap["title"] == "Ошибка"
        assert cap["text"] == "Текст ошибки"
        # текст выделяем мышью (главная фича обёрток)
        assert cap["flags"] & Qt.TextInteractionFlag.TextSelectableByMouse

    def test_warning(self, qapp, monkeypatch):
        import msgbox
        from PyQt6.QtWidgets import QMessageBox
        cap = self._patch_exec(monkeypatch)
        msgbox.msgbox_warning(None, "Внимание", "предупреждение")
        assert cap["icon"] == QMessageBox.Icon.Warning

    def test_information(self, qapp, monkeypatch):
        import msgbox
        from PyQt6.QtWidgets import QMessageBox
        cap = self._patch_exec(monkeypatch)
        msgbox.msgbox_information(None, "Инфо", "сообщение")
        assert cap["icon"] == QMessageBox.Icon.Information

    def test_question_default_buttons(self, qapp, monkeypatch):
        import msgbox
        from PyQt6.QtWidgets import QMessageBox
        cap = self._patch_exec(monkeypatch)
        msgbox.msgbox_question(None, "Вопрос", "продолжить?")
        assert cap["icon"] == QMessageBox.Icon.Question
        assert cap["buttons"] & QMessageBox.StandardButton.Yes
        assert cap["buttons"] & QMessageBox.StandardButton.No

    def test_returns_clicked_button(self, qapp, monkeypatch):
        import msgbox
        from PyQt6.QtWidgets import QMessageBox
        self._patch_exec(monkeypatch)
        assert msgbox.msgbox_critical(None, "t", "x") == \
            QMessageBox.StandardButton.Ok

    def test_critical_has_copy_button(self, qapp, monkeypatch):
        # msgbox_critical/msgbox_warning получают кнопку «Копировать» — клик по
        # ней копирует текст ошибки в буфер обмена и НЕ закрывает диалог
        # (переоткрывает то же окно), в отличие от остальных кнопок.
        import msgbox
        from PyQt6.QtWidgets import QMessageBox, QApplication

        calls = {"n": 0}

        def fake_exec(self):
            calls["n"] += 1
            if calls["n"] == 1:
                copy_btn = next(b for b in self.buttons() if b.text() == "Копировать")
                copy_btn.click()
            else:
                self.button(QMessageBox.StandardButton.Ok).click()
            return QMessageBox.StandardButton.Ok
        monkeypatch.setattr(QMessageBox, "exec", fake_exec)

        result = msgbox.msgbox_critical(None, "Ошибка", "текст ошибки для копирования")
        assert calls["n"] == 2  # диалог реально переоткрылся после клика «Копировать»
        assert QApplication.clipboard().text() == "текст ошибки для копирования"
        assert result == QMessageBox.StandardButton.Ok

    def test_information_has_no_copy_button(self, qapp, monkeypatch):
        # Кнопка «Копировать» — только у критических/предупреждающих окон (это
        # окна ОШИБОК), не у обычных информационных диалогов.
        from PyQt6.QtWidgets import QMessageBox
        seen = {}

        def fake_exec(self):
            seen["texts"] = [b.text() for b in self.buttons()]
            self.button(QMessageBox.StandardButton.Ok).click()
            return QMessageBox.StandardButton.Ok
        monkeypatch.setattr(QMessageBox, "exec", fake_exec)
        import msgbox
        msgbox.msgbox_information(None, "Инфо", "сообщение")
        assert "Копировать" not in seen["texts"]

    def test_warning_has_copy_button_present(self, qapp, monkeypatch):
        from PyQt6.QtWidgets import QMessageBox
        seen = {}

        def fake_exec(self):
            seen["texts"] = [b.text() for b in self.buttons()]
            self.button(QMessageBox.StandardButton.Ok).click()
            return QMessageBox.StandardButton.Ok
        monkeypatch.setattr(QMessageBox, "exec", fake_exec)
        import msgbox
        msgbox.msgbox_warning(None, "Внимание", "предупреждение")
        assert "Копировать" in seen["texts"]

    def test_question_has_no_copy_button(self, qapp, monkeypatch):
        from PyQt6.QtWidgets import QMessageBox
        seen = {}

        def fake_exec(self):
            seen["texts"] = [b.text() for b in self.buttons()]
            btn = self.button(QMessageBox.StandardButton.Yes)
            btn.click()
            return QMessageBox.StandardButton.Yes
        monkeypatch.setattr(QMessageBox, "exec", fake_exec)
        import msgbox
        msgbox.msgbox_question(None, "Вопрос", "продолжить?")
        assert "Копировать" not in seen["texts"]


# ── taskbar.py ───────────────────────────────────────────────────────────────
class TestTaskbarProgress:
    def test_construction_no_crash(self):
        tb = taskbar.TaskbarProgress()
        assert isinstance(tb.available, bool)

    def test_noop_without_hwnd(self):
        tb = taskbar.TaskbarProgress()
        # nullptr hwnd → методы просто выходят, не бросая
        tb.set_value(0, 50, 100)
        tb.set_state(0, taskbar.TaskbarProgress.NORMAL)
        tb.clear(0)

    def test_states_constants(self):
        assert taskbar.TaskbarProgress.NOPROGRESS == 0x0
        assert taskbar.TaskbarProgress.INDETERMINATE == 0x1
        assert taskbar.TaskbarProgress.NORMAL == 0x2
        assert taskbar.TaskbarProgress.ERROR == 0x4
        assert taskbar.TaskbarProgress.PAUSED == 0x8

    def test_set_value_when_unavailable(self, monkeypatch):
        tb = taskbar.TaskbarProgress()
        monkeypatch.setattr(tb, "_ok", False)
        # даже с валидным hwnd при недоступном COM — no-op без исключения
        tb.set_value(12345, 40, 100)
        tb.clear(12345)

    def test_set_value_indeterminate_branch(self, monkeypatch):
        tb = taskbar.TaskbarProgress()
        calls = []
        monkeypatch.setattr(tb, "_ok", True)
        monkeypatch.setattr(tb, "_set_state",
                            lambda *a: calls.append(("state", a)))
        monkeypatch.setattr(tb, "_set_value",
                            lambda *a: calls.append(("value", a)))
        tb._taskbar = object()
        tb.set_value(999, 0)   # completed<=0 → неопределённый режим
        assert calls and calls[0][0] == "state"

    def test_set_value_normal_branch(self, monkeypatch):
        tb = taskbar.TaskbarProgress()
        calls = []
        monkeypatch.setattr(tb, "_ok", True)
        monkeypatch.setattr(tb, "_set_state", lambda *a: calls.append("state"))
        monkeypatch.setattr(tb, "_set_value", lambda *a: calls.append("value"))
        tb._taskbar = object()
        tb.set_value(999, 40, 100)
        assert "value" in calls
