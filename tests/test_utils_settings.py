# -*- coding: utf-8 -*-
"""Тесты load_settings/save_settings: атомарность, .bak, защита от затирания.

SETTINGS_FILE во всех тестах подменён autouse-фикстурой isolate_settings —
реальный %APPDATA% пользователя не затрагивается.
"""
import json
import os

import utils


def _settings_path():
    return utils.SETTINGS_FILE


class TestLoadSettings:
    def test_missing_file_returns_empty(self):
        assert utils.load_settings() == {}

    def test_roundtrip(self):
        utils.save_settings({"a": 1, "папка": "C:\\Видео"})
        assert utils.load_settings() == {"a": 1, "папка": "C:\\Видео"}

    def test_corrupted_main_falls_back_to_bak(self):
        utils.save_settings({"v": 1})
        utils.save_settings({"v": 2})  # первая версия ушла в .bak
        # ломаем основной файл (обрезанная запись)
        with open(_settings_path(), "w", encoding="utf-8") as f:
            f.write('{"v": 2')
        assert utils.load_settings() == {"v": 1}

    def test_both_corrupted_returns_empty(self):
        p = _settings_path()
        for path in (p, p + ".bak"):
            with open(path, "w", encoding="utf-8") as f:
                f.write("не json")
        assert utils.load_settings() == {}

    def test_unicode_preserved(self):
        utils.save_settings({"имя": "Тест «кавычки» — тире"})
        assert utils.load_settings()["имя"] == "Тест «кавычки» — тире"


class TestSaveSettings:
    def test_creates_file(self):
        utils.save_settings({"x": True})
        assert os.path.exists(_settings_path())

    def test_bak_created_on_second_save(self):
        utils.save_settings({"n": 1})
        utils.save_settings({"n": 2})
        assert os.path.exists(_settings_path() + ".bak")
        with open(_settings_path() + ".bak", encoding="utf-8") as f:
            assert json.load(f) == {"n": 1}

    def test_empty_dict_does_not_wipe_existing(self):
        """Защита от затирания: {} не должен перезаписывать осмысленные настройки."""
        utils.save_settings({"важно": "данные", "папка": "D:\\"})
        utils.save_settings({})
        assert utils.load_settings() == {"важно": "данные", "папка": "D:\\"}

    def test_none_does_not_wipe_existing(self):
        utils.save_settings({"важно": 1})
        utils.save_settings(None)
        assert utils.load_settings() == {"важно": 1}

    def test_empty_dict_saved_when_no_previous(self):
        # если файла ещё нет — пустой словарь записать можно
        utils.save_settings({})
        assert os.path.exists(_settings_path())
        assert utils.load_settings() == {}

    def test_no_tmp_leftover(self):
        utils.save_settings({"a": 1})
        assert not os.path.exists(_settings_path() + ".tmp")

    def test_atomic_replace_keeps_valid_json(self):
        for i in range(5):
            utils.save_settings({"i": i})
        assert utils.load_settings() == {"i": 4}

    def test_save_failure_swallowed(self, monkeypatch):
        # каталог назначения не создать → функция не должна бросать
        monkeypatch.setattr(utils, "SETTINGS_FILE",
                            os.path.join(utils.SETTINGS_FILE, "impossible", "x.json"))
        utils.save_settings({"a": 1})  # не должно бросить


# ── settings_files_exist: «нечего сохранять» vs «есть, но не читается» ───────
class TestSettingsFilesExist:
    def test_no_files(self):
        assert utils.settings_files_exist() is False

    def test_after_save(self):
        utils.save_settings({"a": 1})
        assert utils.settings_files_exist() is True

    def test_unreadable_but_present(self):
        """Главный случай: файл есть (значит настройки были), но JSON битый —
        load_settings отдаёт {}, а сохранять поверх НЕЛЬЗЯ."""
        p = _settings_path()
        for path in (p, p + ".bak"):
            with open(path, "w", encoding="utf-8") as f:
                f.write("не json, но файл не пустой")
        assert utils.load_settings() == {}
        assert utils.settings_files_exist() is True

    def test_empty_file_does_not_count(self):
        with open(_settings_path(), "w", encoding="utf-8") as f:
            f.write("{}")
        assert utils.settings_files_exist() is False


# ── Рубежи, поставленные после потери настроек 28.07.2026 ───────────────────
class TestSettingsHistory:
    """Снимки settings.json.1…5 — последний рубеж, когда и основной файл, и
    .bak оказались непригодны (две неудачные записи подряд)."""

    def _save_apart(self, monkeypatch, *values):
        """Сохранения «в разное время»: снимок истории делается не чаще раза в
        _SETTINGS_SNAPSHOT_INTERVAL — в тесте убираем этот интервал."""
        monkeypatch.setattr(utils, "_SETTINGS_SNAPSHOT_INTERVAL", 0.0)
        for v in values:
            utils.save_settings(v)

    def test_history_snapshot_written(self, monkeypatch):
        self._save_apart(monkeypatch, {"v": 1}, {"v": 2})
        with open(_settings_path() + ".1", encoding="utf-8") as f:
            assert json.load(f) == {"v": 1}

    def test_recovers_when_main_and_bak_broken(self, monkeypatch):
        self._save_apart(monkeypatch, {"v": 1}, {"v": 2}, {"v": 3})
        p = _settings_path()
        for path in (p, p + ".bak"):          # обе основные копии — мусор
            with open(path, "w", encoding="utf-8") as f:
                f.write("{обрезано")
        data, status = utils.load_settings_ex()
        assert status == "recovered"
        assert data in ({"v": 1}, {"v": 2})   # какая-то из прошлых версий жива

    def test_snapshot_throttled(self):
        for i in range(6):                    # подряд, без сдвига часов
            utils.save_settings({"i": i})
        extra = [p for p in utils._settings_history_paths()[1:] if os.path.exists(p)]
        assert extra == []                    # снимок только один, не пять


class TestBakNeverPoisoned:
    def test_broken_main_does_not_replace_bak(self):
        """Битый settings.json больше не вытесняет рабочую копию в .bak —
        именно так терялись сразу обе копии."""
        utils.save_settings({"важно": 1})
        utils.save_settings({"важно": 2})     # .bak = {"важно": 1}
        with open(_settings_path(), "w", encoding="utf-8") as f:
            f.write("{битый")
        utils.save_settings({"важно": 3})     # запись поверх битого файла
        with open(_settings_path() + ".bak", encoding="utf-8") as f:
            assert json.load(f) == {"важно": 1}
        assert utils.load_settings() == {"важно": 3}


class TestLockedFile:
    def test_locked_main_reports_locked(self, monkeypatch):
        """Занятый файл (антивирус, второй экземпляр) — это НЕ «настроек нет»:
        данные целы, поэтому статус 'locked' и сохранять запрещено."""
        utils.save_settings({"важно": 1})
        real_open = open

        def _busy(path, *a, **k):
            if str(path) == _settings_path():
                raise PermissionError("файл занят")
            return real_open(path, *a, **k)

        monkeypatch.setattr("builtins.open", _busy)
        monkeypatch.setattr(utils.time, "sleep", lambda *_a: None)
        data, status = utils.load_settings_ex()
        assert (data, status) == ({}, "locked")

    def test_transient_lock_is_retried(self, monkeypatch):
        """Кратковременная занятость не должна выглядеть как потеря настроек."""
        utils.save_settings({"важно": 7})
        real_open = open
        calls = {"n": 0}

        def _flaky(path, *a, **k):
            if str(path) == _settings_path():
                calls["n"] += 1
                if calls["n"] == 1:
                    raise PermissionError("файл занят")
            return real_open(path, *a, **k)

        monkeypatch.setattr("builtins.open", _flaky)
        monkeypatch.setattr(utils.time, "sleep", lambda *_a: None)
        assert utils.load_settings() == {"важно": 7}


class TestSaveIsolation:
    def test_tmp_name_is_per_process(self):
        """Общий settings.json.tmp означал, что два запущенных экземпляра
        программы пишут в один файл и могут опубликовать обрывок друг друга."""
        utils.save_settings({"a": 1})
        leftovers = [n for n in os.listdir(os.path.dirname(_settings_path()))
                     if n.endswith(".tmp")]
        assert leftovers == []

    def test_foreign_tmp_is_ignored(self):
        """Чужой (недописанный) tmp рядом не попадает в настройки."""
        with open(_settings_path() + ".tmp", "w", encoding="utf-8") as f:
            f.write('{"обрывок": ')
        utils.save_settings({"мой": 1})
        assert utils.load_settings() == {"мой": 1}

    def test_unchanged_save_does_not_touch_disk(self):
        utils.save_settings({"a": 1})
        before = os.path.getmtime(_settings_path())
        utils.save_settings({"a": 1})         # ничего не изменилось
        assert os.path.getmtime(_settings_path()) == before
