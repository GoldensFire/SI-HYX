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
