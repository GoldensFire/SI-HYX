# -*- coding: utf-8 -*-
"""Общие фикстуры тестового набора SI-HYX.

КРИТИЧНО: тесты никогда не должны трогать реальные пользовательские файлы:
  • config.SETTINGS_FILE указывает на настоящий %APPDATA%\\unified_media_tool —
    во всех тестах он подменяется на файл во временной папке (autouse-фикстура);
  • siquester.persistence пишет в Path.home() — пути подменяются фикстурой.

Сеть в тестах запрещена целиком (см. блок «Запрет реальной сети» ниже): HTTP
везде мокается FakeSession, а фоновые QRunnable вкладок доходили до настоящего
requests.post и роняли процесс целиком.
"""
import os
import socket
import sys
import zipfile

# Корень проекта в sys.path (тесты запускаются из корня, но подстрахуемся).
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pytest


# ── Запрет реальной сети ─────────────────────────────────────────────────────
# Полный прогон падал не тестом, а «Windows fatal exception: access violation»:
# вкладка «Генерация аниме-пака» через 1.5 с после создания запускала в
# QThreadPool задачу за списком жанров Shikimori, и поток оставался висеть в
# socket.getaddrinfo, пока Qt и интерпретатор сносили объекты вокруг него. Ловилось
# не всегда — таймер успевал сработать, только если чей-то цикл событий крутился
# достаточно долго, поэтому краш плавал от прогона к прогону.
#
# Затыкаем на уровне сокетов, а не отдельных клиентов: так запрет действует и на
# requests, и на urllib, и на любую будущую библиотеку, и — что важнее — держится
# между тестами, а не только внутри одного (фоновый поток стартует когда угодно).
# Петля (127.0.0.1/::1) разрешена: на ней держится socket.socketpair, через
# который asyncio на Windows будит свой цикл.
NETWORK_ATTEMPTS: list = []          # (host, port) всех попыток — для проверок


class NetworkBlocked(RuntimeError):
    """Тест попытался выйти в интернет. Мокайте клиента (см. FakeSession)."""


def _is_loopback(host) -> bool:
    if host in (None, "", "localhost", "::1", "0.0.0.0", "::"):
        return True
    return isinstance(host, str) and host.startswith("127.")


def _block(host, port=None):
    NETWORK_ATTEMPTS.append((host, port))
    raise NetworkBlocked(
        f"Тесты не ходят в сеть, а этот пошёл: {host}:{port}. "
        "Подмените HTTP-клиент (tests/conftest.py: FakeSession) или отмените "
        "фоновую задачу вкладки."
    )


@pytest.fixture(scope="session", autouse=True)
def block_network():
    """Рубит наружные соединения на всю сессию (в т.ч. в фоновых потоках)."""
    real_getaddrinfo = socket.getaddrinfo
    real_create_connection = socket.create_connection
    real_connect = socket.socket.connect

    def getaddrinfo(host, port, *a, **kw):
        if not _is_loopback(host):
            _block(host, port)
        return real_getaddrinfo(host, port, *a, **kw)

    def create_connection(address, *a, **kw):
        if not _is_loopback(address[0] if address else None):
            _block(*address[:2])
        return real_create_connection(address, *a, **kw)

    def connect(self, address, *a, **kw):
        # Юникс-сокеты и прочие семейства адресуются не парой (host, port) —
        # такие пропускаем, наружу они всё равно не ведут.
        if isinstance(address, tuple) and address and not _is_loopback(address[0]):
            _block(*address[:2])
        return real_connect(self, address, *a, **kw)

    socket.getaddrinfo = getaddrinfo
    socket.create_connection = create_connection
    socket.socket.connect = connect
    try:
        yield NETWORK_ATTEMPTS
    finally:
        socket.getaddrinfo = real_getaddrinfo
        socket.create_connection = real_create_connection
        socket.socket.connect = real_connect


@pytest.fixture
def network_attempts(block_network):
    """Попытки выйти в сеть за время теста (список пар host/port)."""
    block_network.clear()
    yield block_network
    block_network.clear()


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
    """Подменяет SETTINGS_FILE во ВСЕХ модулях, которые его к себе скопировали.

    `from config import SETTINGS_FILE` создаёт СВОЮ привязку имени в модуле-
    импортёре, поэтому патча одного config недостаточно — правим каждый модуль.
    Список ниже намеренно шире фактического (сейчас имя есть только у config и
    utils; hasattr-гард пропускает остальные) — чтобы фикстура продолжала
    защищать, если имя начнёт импортировать ещё какой-то модуль. Никогда не
    пишем в реальный %APPDATA% пользователя."""
    fake = str(tmp_path / "settings.json")
    for mod_name in ("config", "utils", "workers", "tabs", "widgets"):
        mod = sys.modules.get(mod_name)
        if mod is not None and hasattr(mod, "SETTINGS_FILE"):
            monkeypatch.setattr(mod, "SETTINGS_FILE", fake, raising=True)
    # Генератор аниме-паков держит рядом с настройками кэш каталога Shikimori и
    # память о показанных кадрах — они тоже в настоящем %APPDATA%.
    animepack = sys.modules.get("animepack")
    if animepack is not None:
        monkeypatch.setattr(animepack, "SHIKI_CACHE_FILE",
                            str(tmp_path / "animepack_shikimori_db.json"),
                            raising=True)
        monkeypatch.setattr(animepack, "FRAMES_HISTORY_FILE",
                            str(tmp_path / "animepack_frames_used.json"),
                            raising=True)
    # Общая кладовая обложек (генератор + апгрейд) тоже живёт рядом с
    # настройками: без подмены тесты складывали бы туда свои фальшивые картинки,
    # а следующий тест находил бы их и «скачивал» постер там, где его нет.
    pcache = sys.modules.get("poster_cache")
    if pcache is not None:
        monkeypatch.setattr(pcache, "POSTER_CACHE_DIR",
                            str(tmp_path / "animepack_posters"), raising=True)
    # Кэш миниатюр ленты «последние файлы» — тоже рядом с настройками.
    wdg = sys.modules.get("widgets")
    if wdg is not None and hasattr(wdg, "_THUMB_CACHE_DIR"):
        monkeypatch.setattr(wdg, "_THUMB_CACHE_DIR",
                            str(tmp_path / "thumb_cache"), raising=True)
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
