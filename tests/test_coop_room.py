# -*- coding: utf-8 -*-
"""Код комнаты вкладки «Collab».

Живой баг: один соавтор ввёл «Collab», второй — «collab». На сервере комната
это ключ KV `room:<код>`, так что получились ДВЕ разные комнаты: оба честно
публиковали и опрашивали, но не видели друг друга вообще. Код комнаты обязан
нормализоваться одинаково на клиенте (coop_tab.normalize_room) и на сервере
(coop_worker.js) — иначе баг вернётся для сборок, где обновлено только одно.
"""
import re

import pytest

from coop_tab import normalize_room, normalize_url


@pytest.mark.parametrize("raw", [
    "collab", "Collab", "COLLAB", " collab ", "collab\n", "\tCollab",
])
def test_room_case_and_spaces_folded(raw):
    assert normalize_room(raw) == "collab"


def test_room_inner_spaces_collapsed():
    assert normalize_room("  Солевая   Волевая ") == "солевая волевая"


def test_room_empty_stays_empty():
    # Пустая строка не должна превращаться в комнату — на неё завязана
    # проверка «заполните поля» перед подключением.
    assert normalize_room("") == ""
    assert normalize_room(None) == ""
    assert normalize_room("   ") == ""


def test_worker_folds_room_the_same_way():
    """В coop_worker.js должна остаться та же нормализация ключа комнаты."""
    import os
    js = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "coop_worker.js"), encoding="utf-8").read()
    key = js[js.index("const room ="):js.index("const key =")]
    assert ".trim()" in key
    assert ".toLowerCase()" in key
    assert re.search(r"replace\(/\\s\+/g", key)


def test_url_normalization_unchanged():
    assert normalize_url("hyxcollab.longld342.workers.dev/") == \
        "https://hyxcollab.longld342.workers.dev"
    assert normalize_url("") == ""


def test_sync_start_stores_folded_room(monkeypatch):
    """Комната сводится к общему виду ещё до похода в сеть — адрес запроса у
    обоих соавторов должен получиться одинаковым."""
    from coop_tab import _CoopSync
    sync = _CoopSync()
    monkeypatch.setattr(sync, "_run", lambda *a, **k: None)
    sync.start("hyxcollab.longld342.workers.dev", " Collab ", "GoldensFire")
    try:
        assert sync._endpoint() == \
            "https://hyxcollab.longld342.workers.dev/coop/collab"
    finally:
        sync.stop()


def test_reconnect_does_not_leak_poller(monkeypatch):
    """Переподключение обязано гасить прежний поток: события отдаются потоку
    аргументами, иначе старый читал уже новое (несведённое) self._stop и
    оставался вторым опросчиком навсегда."""
    import threading
    from coop_tab import _CoopSync

    started = []

    def fake_run(stop_ev, wake_ev):
        started.append(stop_ev)
        stop_ev.wait(5)

    sync = _CoopSync()
    monkeypatch.setattr(sync, "_run", fake_run)
    sync.start("https://x.dev", "room", "A")
    first = sync._thread
    sync.start("https://x.dev", "room", "A")   # переподключение
    first.join(timeout=3)
    assert not first.is_alive()
    assert threading.active_count() >= 1
    sync.stop()
