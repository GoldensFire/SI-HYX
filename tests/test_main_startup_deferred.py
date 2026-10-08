# -*- coding: utf-8 -*-
"""Запуск главного окна: тяжёлые вкладки строятся ПОСЛЕ показа окна, и
сохранение настроек не трогает диск, если настройки не прочитались.

Полноценное UnifiedWindow тут не создаётся (это секунды и весь Qt-интерфейс) —
методы вызываются на подставном объекте с теми же полями.
"""
import pytest

import main


class _FakeWindow:
    """Минимум полей, которые нужны проверяемым методам."""
    def __init__(self, **kw):
        self.logs = []
        self.__dict__.update(kw)

    def log(self, msg):
        self.logs.append(msg)


class TestDeferredTabs:
    def test_builds_one_tab_per_tick(self, qapp):
        calls = []
        w = _FakeWindow(_deferred_tabs=[lambda: calls.append("шикимори"),
                                        lambda: calls.append("аниме-пак")])
        w._build_deferred_tabs_step = lambda: None      # следующий такт не нужен
        main.UnifiedWindow._build_deferred_tabs_step(w)
        assert calls == ["шикимори"], "за один такт — ровно одна вкладка"
        assert len(w._deferred_tabs) == 1

    def test_broken_tab_does_not_stop_the_queue(self, qapp):
        calls = []

        def _boom():
            raise RuntimeError("вкладка сломалась")

        w = _FakeWindow(_deferred_tabs=[_boom, lambda: calls.append("вторая")])
        w._build_deferred_tabs_step = lambda: None
        main.UnifiedWindow._build_deferred_tabs_step(w)      # первая падает
        assert w.logs and "отложенную вкладку" in w.logs[0]
        main.UnifiedWindow._build_deferred_tabs_step(w)      # вторая всё равно строится
        assert calls == ["вторая"]

    def test_empty_queue_is_noop(self, qapp):
        w = _FakeWindow(_deferred_tabs=[])
        main.UnifiedWindow._build_deferred_tabs_step(w)      # не должно бросить


class TestReadonlySettings:
    def test_readonly_run_never_writes(self, monkeypatch):
        """Настройки не прочитались при запуске → на диск не пишем ничего."""
        written = []
        monkeypatch.setattr(main, "save_settings", lambda data: written.append(data))
        w = _FakeWindow(_settings_readonly=True)
        w._collect_settings = lambda: pytest.fail("сборку настроек звать незачем")
        main.UnifiedWindow._save_settings_now(w)
        assert written == []
        assert any("сохранение отключено" in m.lower() for m in w.logs)

    def test_empty_collect_is_not_written(self, monkeypatch):
        written = []
        monkeypatch.setattr(main, "save_settings", lambda data: written.append(data))
        w = _FakeWindow(_settings_readonly=False)
        w._collect_settings = lambda: {}
        main.UnifiedWindow._save_settings_now(w)
        assert written == []

    def test_normal_run_writes(self, monkeypatch):
        written = []
        monkeypatch.setattr(main, "save_settings", lambda data: written.append(data))
        w = _FakeWindow(_settings_readonly=False)
        w._collect_settings = lambda: {"a": 1}
        main.UnifiedWindow._save_settings_now(w)
        assert written == [{"a": 1}]

    def test_debounced_save_uses_timer(self, qapp):
        """Правка поля не пишет файл немедленно — сохранение откладывается."""
        from PyQt6.QtCore import QTimer
        w = _FakeWindow(_save_timer=QTimer())
        w._save_timer.setSingleShot(True)
        fired = []
        w._save_timer.timeout.connect(lambda: fired.append(1))
        main.UnifiedWindow._save_settings_soon(w)
        assert w._save_timer.isActive() and fired == []


class TestConsoleGap:
    """Логи нового прогона отбиваются от прошлых пятью пустыми строками."""

    def _console(self, qapp):
        from PyQt6.QtWidgets import QTextEdit

        class Window:
            log = main.UnifiedWindow.log
            log_gap = main.UnifiedWindow.log_gap

        window = Window()
        window.txt_log = QTextEdit()
        return window

    def test_gap_separates_two_runs(self, qapp):
        window = self._console(qapp)
        window.log("прошлый прогон")
        window.log_gap()
        window.log("новый прогон")
        head, tail = window.txt_log.toPlainText().split("прошлый прогон")
        assert tail.startswith("\n" * 6)          # свой перевод строки + пять

    def test_an_empty_console_is_not_padded(self, qapp):
        window = self._console(qapp)
        window.log_gap()
        assert window.txt_log.toPlainText() == ""

    def test_the_gap_scrolls_the_console_to_the_bottom(self, qapp):
        """Иначе окно выглядит пустым, пока его не прокрутят руками."""
        window = self._console(qapp)
        window.txt_log.resize(300, 60)
        for i in range(80):
            window.log(f"строка {i}")
        window.log_gap()
        window.log("новый прогон")
        bar = window.txt_log.verticalScrollBar()
        assert bar.value() == bar.maximum()


class TestGlobalResult:
    def test_result_button_tracks_a_created_file(self, qapp, tmp_path):
        from PyQt6.QtWidgets import QProgressBar, QToolButton

        result = tmp_path / "ready.mp4"
        result.write_bytes(b"video")
        bar = QProgressBar()
        bar.resize(300, 22)
        button = QToolButton(bar)
        button.setText("")
        button.setFixedSize(20, 20)
        window = _FakeWindow(btn_open_progress=button,
                             pbar=bar, _global_result_path="")
        main.UnifiedWindow._position_progress_button(window)
        assert button.parent() is bar
        assert button.text() == ""
        assert button.pos().x() == 277
        assert button.pos().y() == 1

        main.UnifiedWindow.set_global_result(window, str(result))
        assert button.isEnabled()
        assert window._global_result_path == str(result.resolve())
        assert str(result.resolve()) in button.toolTip()

        main.UnifiedWindow.set_global_result(window, "")
        assert not button.isEnabled()
