# -*- coding: utf-8 -*-
"""Автодобавление готового пака в два списка «не повторять»."""
from types import SimpleNamespace

import pytest

import animepack as ap
import animepack_tab


def _result(path, cancelled=False):
    return SimpleNamespace(
        path=str(path), songs=[], elapsed=1.0, cancelled=cancelled,
        aborted=False, requested=0, pack_number=0)


def test_checkbox_is_saved_and_restored(qapp):
    tab = animepack_tab.AnimePackTab()
    try:
        assert tab.chk_auto_add_exclusions.isChecked()
        tab.chk_auto_add_exclusions.click()
        saved = tab.collect().to_dict()
        assert saved["auto_add_to_exclusions"] is False
        assert ap.PackSettings.from_dict(saved).auto_add_to_exclusions is False
        tab.chk_auto_add_exclusions.setChecked(True)
        tab.apply_settings(saved)
        assert not tab.chk_auto_add_exclusions.isChecked()
    finally:
        tab.cleanup()


@pytest.mark.parametrize("cancelled", [False, True])
def test_unchecked_does_not_add_saved_pack(qapp, tmp_path, cancelled):
    tab = animepack_tab.AnimePackTab()
    try:
        tab.chk_auto_add_exclusions.setChecked(False)
        tab._active_settings = tab.collect()
        path = tmp_path / "generated.siq"
        path.write_bytes(b"pack")
        tab._on_finished(_result(path, cancelled))
        assert tab._exclude_siq == []
        assert tab._exclude_exact_siq == []
    finally:
        tab.cleanup()


def test_running_pack_uses_checkbox_value_at_start(qapp, tmp_path):
    tab = animepack_tab.AnimePackTab()
    try:
        tab.chk_auto_add_exclusions.setChecked(False)
        tab._active_settings = tab.collect()
        tab.chk_auto_add_exclusions.setChecked(True)
        first = tmp_path / "first.siq"
        first.write_bytes(b"pack")
        tab._on_finished(_result(first))
        assert tab._exclude_siq == []
        assert tab._exclude_exact_siq == []

        tab._active_settings = tab.collect()
        second = tmp_path / "second.siq"
        second.write_bytes(b"pack")
        tab._on_finished(_result(second))
        assert tab._exclude_siq == [str(second)]
        assert tab._exclude_exact_siq == [str(second)]
    finally:
        tab.cleanup()
