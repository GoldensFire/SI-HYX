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
