"""Small packs get separate numbers and never suppress later questions."""
from types import SimpleNamespace
import zipfile

import animepack as ap
import animepack_tab

from si_hyx_parts.animepack.pack_summary import pack_title
from si_hyx_parts.animepack.test_packs import is_test_pack


def _siq(path, count):
    questions = "<question/>" * count
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("content.xml", f"<package>{questions}</package>")
    return path


def test_actual_question_count_controls_test_title_and_boundary(tmp_path):
    small = [SimpleNamespace(level=4)] * 95
    full = [SimpleNamespace(level=4)] * 96
    assert pack_title("Сгенерировано в SI-HYX", 12, small,
                      test_number=3, ignore_test_packs=True) == "Тестовый № 3"
    assert pack_title("Сгенерировано в SI-HYX", 12, full,
                      test_number=3, ignore_test_packs=True) == (
                          "Сгенерировано в SI-HYX № 12 (Ур. 4.0)")
    assert is_test_pack(_siq(tmp_path / "small.siq", 95))
    assert not is_test_pack(_siq(tmp_path / "full.siq", 96))


def test_test_counter_and_franchise_exclusions_are_separate(qapp, tmp_path):
    tab = animepack_tab.AnimePackTab()
    try:
        tab.chk_ignore_test_packs.setChecked(True)
        saved = tab.collect().to_dict()
        assert ap.PackSettings.from_dict(saved).ignore_test_packs
        tab._pack_number = 12
        settings = tab.collect()
        settings.pack_number = 13
        settings.test_pack_number = 3
        tab._active_settings = settings
        path = _siq(tmp_path / "test.siq", 95)
        tab._fill_table = lambda _: None
        tab._finish_queue = lambda: None
        tab._on_finished(SimpleNamespace(
            path=str(path), songs=[None] * 95, elapsed=0.1,
            cancelled=False, requested=120, pack_number=13))
        assert tab._pack_number == 12
        assert tab._test_pack_number == 3
        assert tab._exclude_siq == []
        assert tab._exclude_exact_siq == []
    finally:
        tab.cleanup()


def test_explicitly_listed_test_pack_is_ignored_during_generation(tmp_path):
    test_path = _siq(tmp_path / "test.siq", 2)
    generator = object.__new__(ap.AnimePackGenerator)
    generator.s = ap.PackSettings(
        ignore_test_packs=True, exclude_siq=[str(test_path)],
        exclude_exact_siq=[str(test_path)])
    generator.stopped = lambda: False
    generator.log = lambda _: None
    generator.load_exclusions()
    assert not generator._excluded_roots
    assert not generator._excluded_franchises
    assert not generator._exact_keys
