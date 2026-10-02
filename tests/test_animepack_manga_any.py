# -*- coding: utf-8 -*-
"""Any adaptation share survives settings and accepts the actual catalog mix."""
import pytest
from PyQt6.QtCore import QEvent

import animepack as ap
import animepack_tab
from test_animepack_manga_adaptation import _book
from test_animepack_tab_mix import _FakeMain


@pytest.mark.parametrize("adapted", [True, False])
def test_any_accepts_an_entire_book_quota_with_one_adaptation_status(adapted):
    mix = ap.MangaMix(ap.PackSettings(manga_adapted_percent=-1), 4)
    for _ in range(4):
        candidate = _book(adapted=adapted)
        assert mix.allows(candidate)
        mix.reserve(candidate)
    assert mix.bench_size == 0


def test_any_keeps_edition_shares_and_survives_quota_changes():
    settings = ap.PackSettings(manga_adapted_percent=-1, manga_pct_manhwa=50)
    mix = ap.MangaMix(settings, 2)
    first = _book(adapted=True, kind="manhwa")
    assert mix.allows(first)
    mix.reserve(first)
    assert not mix.allows(_book(kind="manhwa"))
    mix.sync(4)
    assert mix.allows(_book(kind="manhwa"))
    assert mix.allows(_book(adapted=True))


def test_any_can_be_selected_with_slider_saved_and_restored(qapp):
    tab = animepack_tab.AnimePackTab(main_window=_FakeMain())
    try:
        tab.sp_manga_adapted.slider.setValue(-1)
        assert tab.sp_manga_adapted.value() == -1
        assert tab.sp_manga_adapted.text() == "Любое"
        settings = ap.PackSettings.from_dict(tab.collect().to_dict())
        assert settings.manga_adapted_percent == -1
        tab.sp_manga_adapted.setValue(40)
        tab.apply_settings(settings.to_dict())
        assert tab.sp_manga_adapted.value() == -1
        tab.apply_settings(ap.PackSettings(manga_adapted_percent=0).to_dict())
        assert tab.sp_manga_adapted.text() == "0 %"
    finally:
        tab.cleanup()
        tab.close()
        tab.deleteLater()
        qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qapp.processEvents()
