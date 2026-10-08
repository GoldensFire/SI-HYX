"""Shared percentages for ordinary songs, video and musical effects."""
import animepack_tab as api

LABELS = {"original": "Просто песни", "video": "Опенинги с видеорядом",
          "karaoke": "Караоке", "chiptune": "Chiptune", "cover": "Каверы"}
CONTROLS = {"video": ("chk_video", "sp_song_video_percent"),
            "karaoke": ("chk_karaoke", "sp_karaoke_percent"),
            "chiptune": ("chk_chiptune", "sp_chiptune_percent"),
            "cover": ("chk_cover", "sp_cover_percent")}


class SongPresentationSlider(api._ShareBar):
    KEYS = tuple(LABELS)
    LABELS = LABELS

    def __init__(self):
        super().__init__()
        self.set_parts([("original", LABELS["original"])])

    def shares(self):
        return {key: self.value_of(key) for key in self.KEYS}

    def move_share(self, key, value):
        others = [k for k in self.keys() if k != key]
        if key not in self.keys() or not others:
            return
        value = max(0, min(100, int(value)))
        total = sum(self.value_of(k) for k in others)
        weights = {k: self.value_of(k) if total else 1 for k in others}
        total = sum(weights.values())
        left = 100 - value
        values = {k: left * weights[k] // total for k in others}
        remainder = left - sum(values.values())
        for k in sorted(others, key=lambda k: -(left * weights[k] % total))[:remainder]:
            values[k] += 1
        values[key] = value
        self.set_values(values)
        self.changed.emit()


def build(tab):
    tab.song_presentation_mix = SongPresentationSlider()
    tab.song_presentation_mix.setToolTip(
        "Доли среди песенных вопросов. Ползунки делят 100% между "
        "включёнными способами подачи. Видеоряд доступен для OP/ED; "
        "если ролика нет, используется аудио песни.")
    tab.sp_song_video_percent = api.QSpinBox(tab)
    tab.sp_song_video_percent.setRange(0, 100)
    tab.sp_song_video_percent.setValue(25)
    for key, (check_name, percent_name) in CONTROLS.items():
        check, percent = getattr(tab, check_name), getattr(tab, percent_name)
        percent.setMinimum(0)
        percent.hide()
        check.toggled.connect(lambda _, k=key: toggle(tab, k))
        percent.valueChanged.connect(lambda value, k=key: move(tab, k, value))
    tab.song_presentation_mix.changed.connect(lambda: changed(tab))
    toggle(tab)
    return tab.song_presentation_mix


def toggle(tab, key=None):
    bar = tab.song_presentation_mix
    old = bar.shares()
    selected = ["original"] + [k for k, (check, _) in CONTROLS.items()
                                if getattr(tab, check).isChecked()]
    added = key in selected and key not in bar.keys()
    bar.set_parts([(k, LABELS[k]) for k in selected])
    if added:
        bar.move_share(key, getattr(tab, CONTROLS[key][1]).value() or 25)
    elif key is not None:
        bar.set_values(old)
    changed(tab)


def move(tab, key, value):
    if key in tab.song_presentation_mix.keys():
        tab.song_presentation_mix.move_share(key, value)


def changed(tab):
    bar = tab.song_presentation_mix
    for key, (_, percent_name) in CONTROLS.items():
        if key not in bar.keys():
            continue
        percent = getattr(tab, percent_name)
        percent.blockSignals(True)
        percent.setValue(bar.value_of(key))
        percent.blockSignals(False)
    if not hasattr(tab, "sp_parallel"):
        return
    tab._recount()
    if getattr(tab, "settings_columns", None) is not None:
        tab._fit_settings_width()
    saver = getattr(getattr(tab, "main", None), "_save_settings_soon", None)
    if saver:
        saver()


def collect(tab, settings):
    values = tab.song_presentation_mix.shares()
    settings.song_video_percent = values["video"]
    settings.karaoke_percent = values["karaoke"]
    settings.chiptune_percent = values["chiptune"]
    settings.cover_percent = values["cover"]


def apply(tab, settings):
    values = {key: int(getattr(settings, key + "_percent"))
              if getattr(settings, key + "_enabled") else 0
              for key in ("karaoke", "chiptune", "cover")}
    left = max(0, 100 - sum(values.values()))
    video = settings.song_video_percent
    values["video"] = (left if video is None else video) if settings.song_video else 0
    values["original"] = max(0, left - values["video"])
    tab.song_presentation_mix.set_values(values)
    changed(tab)
