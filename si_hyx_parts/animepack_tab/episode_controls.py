"""Composition and optional Russian subtitles for episode scenes."""
import animepack_tab as api


def build_controls(tab):
    tab.chk_episode = api.QCheckBox("Отрывки серий")
    tab.chk_episode.setToolTip(
        "Случайные 20 секунд из существующей серии выбранного аниме. "
        "Оригинальная японская озвучка; опенинги и эндинги пропускаются.")
    tab.box_episode = api.SettingsBox()
    layout = api.QGridLayout(tab.box_episode)
    layout.setContentsMargins(16, 0, 0, 0)
    tab.chk_episode_ru = api.QCheckBox("Русские субтитры")
    tab.chk_episode_ru.setChecked(False)
    tab.chk_episode_ru.setToolTip(
        "SubDL → Jimaku, с ключами из настроек диалогов. Для перевода Jimaku "
        "используется настроенный Gemini. Если русских субтитров нет, отрывок "
        "всё равно попадёт в пак. Настройки качества общие с роликами.")
    layout.addWidget(tab.chk_episode_ru, 0, 0)
    crf = api.QSpinBox()
    crf.setRange(0, 63)
    crf.setValue(tab.sp_video_crf.value())
    crf.valueChanged.connect(tab.sp_video_crf.setValue)
    tab.sp_video_crf.valueChanged.connect(crf.setValue)
    preset = api.QSpinBox()
    preset.setRange(0, 13)
    preset.setValue(tab.sp_video_preset.value())
    preset.valueChanged.connect(tab.sp_video_preset.setValue)
    tab.sp_video_preset.valueChanged.connect(preset.setValue)
    layout.addWidget(tab._lab("Качество видео (CRF)"), 1, 0)
    layout.addWidget(crf, 1, 1)
    layout.addWidget(tab._lab("Скорость кодирования"), 2, 0)
    layout.addWidget(preset, 2, 1)
    preset.setToolTip("13 — быстрее, 0 — медленнее. Качество и скорость общие с видео опенингов.")
    layout.addWidget(tab._api_key_button("subdl", "Ключ SubDL"), 3, 0)
    layout.addWidget(tab._api_key_button("jimaku", "Ключ Jimaku"), 3, 1)
    tab.chk_episode_ru.toggled.connect(lambda _: tab._refresh_song_opts())
    tab.box_episode.hide()
    tab.chk_episode.toggled.connect(lambda checked: _toggle(tab, checked))


def _toggle(tab, checked):
    tab.box_episode.setVisible(checked)
    tab.mix._set_part("episode", checked)
    tab._refresh_song_opts()


def collect(tab, settings):
    settings.pack_episode = tab.chk_episode.isChecked()
    settings.pct_episode = tab.mix.shares()["episode"]
    settings.episode_ru_subtitles = tab.chk_episode_ru.isChecked()


def apply_controls(tab, settings):
    tab.chk_episode.setChecked(settings.pack_episode)
    tab.mix._set_part("episode", settings.pack_episode)
    tab.chk_episode_ru.setChecked(settings.episode_ru_subtitles)
