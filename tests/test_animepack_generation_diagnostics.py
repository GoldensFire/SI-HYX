# -*- coding: utf-8 -*-
"""В отчёте только измеренный параллелизм и непересекающиеся операции."""
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import threading

import animepack as ap
from si_hyx_parts.animepack import generation_diagnostics as gd


def test_nested_download_and_encoding_have_no_double_count(monkeypatch):
    clock = iter([0.0, 2.0, 5.0, 10.0])
    monkeypatch.setattr(gd.time, "monotonic", lambda: next(clock))
    tracker = gd.GenerationDiagnostics()
    with tracker.stage("аудио"):
        with tracker.measure("подготовка"):
            with tracker.measure("скачивание"):
                pass
    assert tracker.spans[("аудио", "скачивание")] == [(2.0, 5.0)]
    assert tracker.spans[("аудио", "подготовка")] == [(0.0, 2.0), (5.0, 10.0)]


def test_worker_report_uses_measured_peak_and_effective_low_limit():
    tracker = gd.GenerationDiagnostics()
    barrier = threading.Barrier(2)
    fetch = tracker.wrap(lambda _cand: barrier.wait(timeout=5) is not None,
                         {"opening": "Опенинг"})
    candidate = SimpleNamespace(kind="opening", title_ru="Тайтл")
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(fetch, candidate) for _ in range(2)]
        for future in futures:
            future.result()
    lines = []
    gen = SimpleNamespace(log=lines.append, _late={},
                          s=ap.PackSettings(parallel=8, generation_priority="low"),
                          _merge_spans=ap.AnimePackGenerator._merge_spans)
    tracker.report(gen)
    assert "запрошено 8, действующий лимит 2, максимум одновременно 2" in lines[0]
    assert tracker.started == 2 and tracker.active == 0


def test_adjacent_operations_are_not_reported_as_parallel():
    assert gd.peak_parallel([(0, 1), (1, 2), (2, 3)]) == 1
    assert gd.peak_parallel([(0, 2), (1, 3)]) == 2


def test_exception_restores_task_counters_and_keeps_duration():
    import pytest
    tracker = gd.GenerationDiagnostics()
    def broken(_cand):
        with tracker.measure("кодирование"):
            raise ValueError("ошибка")
    fetch = tracker.wrap(broken, {})
    with pytest.raises(ValueError):
        fetch(SimpleNamespace(kind="pixel", title_ru="Кадр"))
    assert tracker.active == 0 and tracker.peak == 1
    assert tracker.slowest[0][3].get("кодирование") is not None
