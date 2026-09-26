"""Actual Qt form persistence and preview lifecycle."""
import animepack_tab as ui
from si_hyx_parts.animepack_tab.music_preview import MusicPreview


def test_controls_roundtrip(qapp):
    tab = ui.AnimePackTab()
    tab.apply_settings({"chiptune_enabled": True, "chiptune_percent": 65,
                        "chiptune_seed": 781, "chiptune_lead": "other",
                        "chiptune_lead_volume": 75, "chiptune_bass_volume": 0,
                        "chiptune_python": "C:/worker/python.exe"})
    saved = tab.get_settings()
    assert saved["chiptune_enabled"]
    assert saved["chiptune_percent"] == 65
    assert saved["chiptune_seed"] == 781
    assert saved["chiptune_lead"] == "other"
    assert saved["chiptune_bass_volume"] == 0
    assert saved["chiptune_python"] == "C:/worker/python.exe"
    tab.cleanup()
    tab.close()


def test_preview_without_source_and_cleanup(qapp):
    dialog = MusicPreview(ui.PackSettings())
    directory = dialog.directory
    dialog.launch(False)
    assert "выберите" in dialog.label.text()
    assert dialog.job is None
    dialog.reject()
    assert not directory.exists()
