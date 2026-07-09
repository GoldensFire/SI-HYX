# -*- coding: utf-8 -*-
"""Общие фикстуры тестового набора SI-HYX.

КРИТИЧНО: тесты никогда не должны трогать реальные пользовательские файлы:
  • config.SETTINGS_FILE указывает на настоящий %APPDATA%\\unified_media_tool —
    во всех тестах он подменяется на файл во временной папке (autouse-фикстура);
  • пакет sigstats хранит БД/кэши рядом с проектом — переменные окружения
    SIGSTATS_HOME / SIGSTATS_DB выставляются во временную папку ДО первого
    импорта sigstats.config (ниже, на уровне модуля);
  • siquester.persistence пишет в Path.home() — пути подменяются фикстурой.
"""
import os
import sys
import tempfile
import zipfile

# ── Изоляция sigstats ДО любого импорта пакета ────────────────────────────────
_SIGSTATS_TMP = tempfile.mkdtemp(prefix="sihyx_test_sigstats_")
os.environ.setdefault("SIGSTATS_HOME", _SIGSTATS_TMP)
os.environ.setdefault("SIGSTATS_DB", os.path.join(_SIGSTATS_TMP, "test_sigstats.db"))

# Корень проекта в sys.path (тесты запускаются из корня, но подстрахуемся).
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pytest


# ── QApplication (одно на сессию) ─────────────────────────────────────────────
@pytest.fixture(scope="session")
def qapp():
    """Единый QApplication для тестов, которым нужен Qt (QPixmap, виджеты)."""
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        app = QApplication([sys.argv[0]])
    yield app


# ── Изоляция настроек приложения ─────────────────────────────────────────────
@pytest.fixture(autouse=True)
def isolate_settings(tmp_path, monkeypatch):
    """Подменяет SETTINGS_FILE во ВСЕХ модулях, которые его скопировали через
    `from config import *` (config, utils, workers, …). Никогда не пишем в
    реальный %APPDATA% пользователя."""
    fake = str(tmp_path / "settings.json")
    for mod_name in ("config", "utils", "workers", "tabs", "widgets"):
        mod = sys.modules.get(mod_name)
        if mod is not None and hasattr(mod, "SETTINGS_FILE"):
            monkeypatch.setattr(mod, "SETTINGS_FILE", fake, raising=True)
    yield


# ── Фабрика .siq-архивов ─────────────────────────────────────────────────────
CONTENT_XML_V5 = """<?xml version="1.0" encoding="utf-8"?>
<package name="Тестовый пак" version="5" id="pkg-1" date="01.01.2026"
         difficulty="5" logo="@logo.png" language="ru">
  <tags><tag>аниме</tag><tag>музыка</tag></tags>
  <info>
    <authors><author>Автор Один</author><author>Автор Два</author></authors>
    <comments>Комментарий пакета</comments>
  </info>
  <rounds>
    <round name="Раунд 1">
      <info><comments>Комментарий раунда</comments></info>
      <themes>
        <theme name="Тема А">
          <questions>
            <question price="100">
              <params>
                <param name="question" type="content">
                  <item>Текст вопроса 100</item>
                </param>
              </params>
              <right><answer>Ответ 100</answer></right>
            </question>
            <question price="200">
              <params>
                <param name="question" type="content">
                  <item type="image" isRef="True">pic.png</item>
                  <item>Подпись к картинке</item>
                </param>
              </params>
              <right><answer>Ответ 200</answer><answer>Второй вариант</answer></right>
            </question>
            <question price="300">
              <params>
                <param name="question" type="content">
                  <item type="audio" isRef="True">sound.mp3</item>
                </param>
                <param name="answerType">select</param>
                <param name="answerOptions" type="group">
                  <param name="A" type="content"><item>Вариант А</item></param>
                  <param name="B" type="content"><item>Вариант Б</item></param>
                </param>
              </params>
              <right><answer>B</answer></right>
            </question>
          </questions>
        </theme>
        <theme name="Тема Б">
          <questions>
            <question price="100">
              <params>
                <param name="question" type="content">
                  <item duration="00:00:26" type="video" isRef="True">clip.mp4</item>
                </param>
              </params>
              <right><answer>Видео-ответ</answer></right>
            </question>
          </questions>
        </theme>
      </themes>
    </round>
    <round name="Финал" type="final">
      <themes>
        <theme name="Финальная тема">
          <questions>
            <question price="500">
              <params>
                <param name="question" type="content"><item>Финальный вопрос</item></param>
              </params>
              <right><answer>Финальный ответ</answer></right>
            </question>
          </questions>
        </theme>
      </themes>
    </round>
  </rounds>
</package>
"""


@pytest.fixture
def make_siq(tmp_path):
    """Собирает валидный .siq (zip) во временной папке и возвращает путь.

    make_siq(content_xml=..., media={имя_в_архиве: bytes}, name=...) → str
    """
    def _make(content_xml: str = CONTENT_XML_V5, media: dict | None = None,
              name: str = "test_pack.siq") -> str:
        path = tmp_path / name
        default_media = {
            "Images/pic.png": b"\x89PNG\r\n\x1a\nfakepng",
            "Audio/sound.mp3": b"\xff\xfb\x90\x00" + b"\x00" * 100,
            "Video/clip.mp4": b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64,
        }
        if media is None:
            media = default_media
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("content.xml", content_xml)
            for arc, data in media.items():
                zf.writestr(arc, data)
        return str(path)

    return _make


# ── Временная БД sigstats на тест ────────────────────────────────────────────
@pytest.fixture
def sigstats_db(tmp_path, monkeypatch):
    """Свежая изолированная SQLite-БД sigstats + подмена всех путей пакета."""
    from sigstats import config as scfg
    from sigstats import db as sdb
    from pathlib import Path

    monkeypatch.setattr(scfg, "BASE_DIR", Path(tmp_path))
    monkeypatch.setattr(scfg, "DB_PATH", Path(tmp_path / "sigstats.db"))
    monkeypatch.setattr(scfg, "PACKAGES_DIR", Path(tmp_path / "packages"))
    monkeypatch.setattr(scfg, "MEDIA_DIR", Path(tmp_path / "media"))
    monkeypatch.setattr(scfg, "BLACKLIST_PATH", Path(tmp_path / "author_blacklist.json"))
    monkeypatch.setattr(scfg, "PLAYED_PATH", Path(tmp_path / "played_packages.json"))
    monkeypatch.setattr(scfg, "SEARCH_CACHE_PATH", Path(tmp_path / "search_page_cache.json"))
    monkeypatch.setattr(scfg, "UI_SETTINGS_PATH", Path(tmp_path / "ui_settings.json"))
    sdb.init_db()
    conn = sdb.connect()
    yield conn
    conn.close()


# ── Простейший фейковый HTTP-ответ/сессия ────────────────────────────────────
class FakeResponse:
    def __init__(self, status_code=200, json_data=None, text="", headers=None,
                 url="https://fake.local/", content=b"", raise_json=False):
        self.status_code = status_code
        self._json = json_data
        self.text = text
        self.headers = headers or {}
        self.url = url
        self.content = content or text.encode("utf-8")
        self._raise_json = raise_json

    @property
    def ok(self):
        return 200 <= self.status_code < 300

    def json(self):
        if self._raise_json or self._json is None:
            raise ValueError("no json")
        return self._json

    def raise_for_status(self):
        if not self.ok:
            import requests
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size=65536):
        data = self.content
        for i in range(0, len(data), chunk_size):
            yield data[i:i + chunk_size]

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass


class FakeSession:
    """Сессия-заглушка: отвечает по подстроке URL (первое совпадение).

    routes: список (подстрока, FakeResponse | callable(url, **kw) -> FakeResponse).
    Все запросы записываются в .calls для проверок.
    """
    def __init__(self, routes=None, default=None):
        self.routes = list(routes or [])
        self.default = default or FakeResponse(status_code=404, text="not found")
        self.calls = []
        self.headers = {}
        self.proxies = {}

    def _dispatch(self, method, url, **kw):
        self.calls.append((method, url, kw))
        for sub, resp in self.routes:
            if sub in url:
                if callable(resp):
                    return resp(url, **kw)
                return resp
        return self.default

    def get(self, url, **kw):
        return self._dispatch("GET", url, **kw)

    def post(self, url, **kw):
        return self._dispatch("POST", url, **kw)

    def close(self):
        pass


@pytest.fixture
def fake_response():
    return FakeResponse


@pytest.fixture
def fake_session():
    return FakeSession
