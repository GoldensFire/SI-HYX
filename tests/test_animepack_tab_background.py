# -*- coding: utf-8 -*-
"""Фоновые задачи вкладки «Генерация аниме-пака».

Через полторы секунды после создания вкладка уходит в QThreadPool за списком
жанров Shikimori. Пока эта задача была неотменяемой, полный прогон pytest падал
не тестом, а «Windows fatal exception: access violation»: поток сидел в
socket.getaddrinfo, а Qt в это время сносил объекты вокруг него. Здесь
проверяем оба замка — запрет сети в тестах и отмену задачи при закрытии вкладки.
"""
import time

import pytest
from PyQt6.QtCore import QThreadPool
from PyQt6.QtWidgets import QApplication

from conftest import NetworkBlocked

animepack_tab = pytest.importorskip("animepack_tab")


def _spin(msec: int):
    """Крутит цикл событий, чтобы успели сработать таймеры."""
    end = time.monotonic() + msec / 1000.0
    while time.monotonic() < end:
        QApplication.processEvents()
        time.sleep(0.005)


# ── Запрет сети ──────────────────────────────────────────────────────────────
def test_наружу_из_тестов_не_пускают(network_attempts):
    import socket
    with pytest.raises(NetworkBlocked):
        socket.getaddrinfo("shikimori.one", 443)
    with pytest.raises(NetworkBlocked):
        socket.create_connection(("shikimori.one", 443), timeout=1)
    assert [host for host, _port in network_attempts] == ["shikimori.one"] * 2


def test_петля_остаётся_разрешённой(network_attempts):
    """socket.socketpair() ходит на 127.0.0.1 — на нём держится asyncio."""
    import socket
    a, b = socket.socketpair()
    a.close(); b.close()
    assert network_attempts == []


# ── Отложенная загрузка жанров ───────────────────────────────────────────────
def test_закрытая_вкладка_не_идёт_за_жанрами(qapp, network_attempts):
    """cleanup() обязан снять отложенный запрос, а не оставить его в воздухе."""
    tab = animepack_tab.AnimePackTab()
    tab._genres_timer.start(10)          # не ждать полторы секунды вхолостую
    tab.cleanup()
    _spin(200)
    assert tab._genres_task is None
    assert network_attempts == []


def test_живая_вкладка_запрос_заводит_но_наружу_не_выходит(qapp, network_attempts):
    """Обратная сторона: у открытой вкладки задача стартует — и упирается в
    запрет сети, а не в реальный DNS."""
    tab = animepack_tab.AnimePackTab()
    try:
        tab._genres_timer.start(10)
        _spin(200)
        QThreadPool.globalInstance().waitForDone(5000)
        assert [host for host, _port in network_attempts] != []
        assert all("shikimori" in str(host) for host, _port in network_attempts)
    finally:
        tab.cleanup()


def test_отменённая_задача_молчит(qapp):
    """Ответ пришёл после закрытия вкладки — сигнал никуда лететь не должен."""
    got = []
    task = animepack_tab._GenresTask()
    task.signals.finished.connect(got.append)
    task.signals.failed.connect(got.append)
    task.stop()
    task.run()
    assert got == []


def test_cleanup_отвязывает_сигналы_генерации(qapp):
    """Задача генерации живёт минутами: ждать её нельзя, но её сигналы после
    cleanup() не должны приходить в разбираемый виджет."""
    tab = animepack_tab.AnimePackTab()
    got = []
    task = animepack_tab._GenTask(animepack_tab.PackSettings())
    task.signals.log.connect(lambda _m: got.append("log"))
    tab._task = task
    tab.cleanup()
    assert task._stop is True
    task.signals.log.emit("после закрытия")
    assert got == []
