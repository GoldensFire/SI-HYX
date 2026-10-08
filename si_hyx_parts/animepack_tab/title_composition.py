"""One pack share for title puzzles, with independent shares inside it."""
import animepack_tab as api
from si_hyx_parts.animepack_tab.mix_slider import _MixSlider
from si_hyx_parts.animepack.title_kinds import TITLE_LABELS

LABELS = {"anagram": "Анаграммы", **TITLE_LABELS}


class TitleSlider(_MixSlider):
    KEYS = tuple(LABELS)
    OPTIONAL = KEYS
    LABELS = LABELS
    LEGACY = ()

    def __init__(self):
        super().__init__()
        self._on = {k: k == "anagram" for k in self.KEYS}
        self._vals = {k: 100 if k == "anagram" else 0 for k in self.KEYS}
        self._parts()
        self.sync_rows()

    def set_shares(self, values):
        self._normalise(values)
        self.update()


def build(tab):
    tab.chk_titles = api.QCheckBox("По названию")
    tab.box_titles = api.SettingsBox()
    grid = api.QGridLayout(tab.box_titles)
    grid.setContentsMargins(16, 0, 0, 0)
    tab.title_mix = TitleSlider()
    for row, (key, label) in enumerate(LABELS.items()):
        chk = getattr(tab, "chk_" + key, None)
        if chk is None:
            chk = api.QCheckBox(label)
            setattr(tab, "chk_" + key, chk)
        chk.blockSignals(True)
        chk.setChecked(key == "anagram")
        chk.blockSignals(False)
        chk.toggled.connect(lambda value, k=key: toggle(tab, k, value))
        grid.addWidget(chk, row, 0)
    grid.addWidget(tab.title_mix, len(LABELS), 0)
    grid.addWidget(tab.box_anagram, len(LABELS) + 1, 0)
    tab.chk_titles.toggled.connect(lambda value: refresh(tab, value))
    tab.title_mix.changed.connect(tab._recount)
    tab.box_titles.hide()


def refresh(tab, enabled=None):
    if not hasattr(tab, "chk_titles"):
        return
    enabled = tab.chk_titles.isChecked() if enabled is None else enabled
    tab.mix._set_part("titles", enabled)
    tab.box_titles.setVisible(enabled)
    tab.box_anagram.setVisible(enabled and tab.chk_anagram.isChecked())
    tab._refresh_song_opts()


def toggle(tab, key, enabled):
    tab.title_mix._set_part(key, enabled)
    refresh(tab)


def collect(tab, settings):
    enabled = tab.chk_titles.isChecked()
    shares = tab.title_mix.shares()
    settings.title_enabled = tab.title_mix.keys()
    settings.title_shares = shares
    settings.pack_titles = enabled
    settings.pct_titles = tab.mix.shares()["titles"]
    # Old fields continue to describe the actual generated question kinds.
    from si_hyx_parts.animepack.title_mix import split
    actual = split(settings.pct_titles if enabled else 0, shares)
    for key in LABELS:
        setattr(settings, "pack_" + key, enabled and getattr(tab, "chk_" + key).isChecked())
        setattr(settings, "pct_" + key, actual[key])


def apply(tab, settings):
    legacy = {k: getattr(settings, "pct_" + k) for k in LABELS}
    selected = settings.title_enabled
    if selected is None:
        selected = [k for k in LABELS if getattr(settings, "pack_" + k)]
    for key in LABELS:
        chk = getattr(tab, "chk_" + key)
        chk.blockSignals(True)
        chk.setChecked(key in selected)
        chk.blockSignals(False)
        tab.title_mix._set_part(key, key in selected)
    tab.title_mix.set_shares(settings.title_shares or legacy)
    enabled = settings.pack_titles if settings.pack_titles is not None else bool(selected)
    tab.chk_titles.setChecked(enabled)
    refresh(tab)
