# -*- coding: utf-8 -*-
"""Тесты siquester/persistence.py — файлы состояния (пути подменены на tmp)."""
import json
import time
from pathlib import Path

import pytest

from siquester import persistence as ps


@pytest.fixture(autouse=True)
def isolated_paths(tmp_path, monkeypatch):
    """Никогда не трогаем реальные ~/.sigame_stats_*.json."""
    monkeypatch.setattr(ps, "SAVE_FILE", Path(tmp_path / "save.json"))
    monkeypatch.setattr(ps, "TABS_FILE", Path(tmp_path / "tabs.json"))
    monkeypatch.setattr(ps, "SETTINGS_FILE", Path(tmp_path / "settings.json"))
    monkeypatch.setattr(ps, "_SAVE_LAST_HASH", 0)
    yield


class TestSettings:
    def test_missing_returns_empty(self):
        assert ps.load_settings() == {}

    def test_roundtrip(self):
        ps.save_settings({"тема": "тёмная", "n": 5})
        assert ps.load_settings() == {"тема": "тёмная", "n": 5}

    def test_corrupted_returns_empty(self):
        ps.SETTINGS_FILE.write_text("не json", encoding="utf-8")
        assert ps.load_settings() == {}

    def test_save_error_swallowed(self, monkeypatch):
        monkeypatch.setattr(ps, "SETTINGS_FILE",
                            Path("Z:/несуществующий/путь/settings.json"))
        ps.save_settings({"a": 1})  # не должно бросить


class TestTabs:
    def test_default(self):
        assert ps.load_tabs() == [{"id": 0, "name": "Все"}]

    def test_roundtrip(self):
        tabs = [{"id": 0, "name": "Все"}, {"id": 1, "name": "Аниме"}]
        ps.save_tabs(tabs)
        assert ps.load_tabs() == tabs

    def test_corrupted_default(self):
        ps.TABS_FILE.write_text("{битый", encoding="utf-8")
        assert ps.load_tabs() == [{"id": 0, "name": "Все"}]


def _dataset(name="Пак", tab=0):
    return {"pkg_name": name, "stats": {"tries": 1}, "rounds": [],
            "pkg_size": "10 МБ", "tab_id": tab, "total_duration_sec": 120,
            "siq_path": "C:/p.siq", "лишнее_поле": "выкидывается"}


def _wait_file(path, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if path.exists() and path.stat().st_size > 0:
            return True
        time.sleep(0.02)
    return False


class TestDatasets:
    def test_missing_returns_empty(self):
        assert ps.load_datasets() == []

    def test_save_and_load(self):
        ps.save_datasets([_dataset("Пак 1"), _dataset("Пак 2", tab=3)])
        assert _wait_file(ps.SAVE_FILE), "фоновый писатель не записал файл"
        data = ps.load_datasets()
        assert [d["pkg_name"] for d in data] == ["Пак 1", "Пак 2"]
        assert data[1]["tab_id"] == 3
        assert data[0]["_view_mode"] == "tile"
        assert "лишнее_поле" not in data[0]

    def test_identical_payload_skipped(self, monkeypatch):
        """Повторное сохранение того же содержимого не пишет файл заново."""
        ds = [_dataset()]
        ps.save_datasets(ds)
        assert _wait_file(ps.SAVE_FILE)
        mtime1 = ps.SAVE_FILE.stat().st_mtime_ns
        # второй вызов с тем же payload — хеш совпал, записи нет
        ps.save_datasets(ds)
        time.sleep(0.15)
        assert ps.SAVE_FILE.stat().st_mtime_ns == mtime1

    def test_corrupted_returns_empty(self):
        ps.SAVE_FILE.write_text("<xml?>", encoding="utf-8")
        assert ps.load_datasets() == []
