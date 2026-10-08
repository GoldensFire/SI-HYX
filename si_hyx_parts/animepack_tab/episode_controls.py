"""Composition and optional Russian subtitles for episode scenes."""
import animepack_tab as api
from si_hyx_parts.animepack.episode_caption_policy import mode


def build_controls(tab):
    tab.chk_episode = api.QCheckBox("Отрывки серий")
    tab.chk_episode.setToolTip(
        "Случайные 15 секунд из существующей серии выбранного аниме. "
        "AnimeLIB, AnimeGO, YummyAnime → Anizone, Anikoto, KAA, AnimeGG, AniWaves. Проверенное качество, "
        "сжатие в 720p; японская озвучка, без опенингов и эндингов.")
    tab.box_episode = api.SettingsBox()
    layout = api.QGridLayout(tab.box_episode)
    layout.setContentsMargins(16, 0, 0, 0)
    tab.chk_episode_ru = api.QCheckBox("Русские субтитры")
    tab.chk_episode_ru.setChecked(False)
    tab.chk_episode_ru.hide()  # Compatibility hook for saved controls and integrations.
    tab.cb_episode_subtitles = api.QComboBox()
    for label, value in (("Без русских субтитров", "none"), ("Русские обязательны", "required"),
                         ("Русские предпочтительны", "preferred")):
        tab.cb_episode_subtitles.addItem(label, value)
    tab.cb_episode_subtitles.setToolTip(
        "Обязательные RU: только русская дорожка самого видео или её перевод. "
        "Предпочтительные RU: допускаются проверенные английские сабы. "
        "Без RU: отдельная русская дорожка не вшивается; встроенные RU исключаются.")
    layout.addWidget(tab._lab("Субтитры"), 0, 0)
    layout.addWidget(tab.cb_episode_subtitles, 0, 1)
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
    layout.addWidget(tab._api_key_button("gemini", "Ключ Gemini для сцен и перевода"), 3, 0, 1, 2)
    layout.addWidget(tab._lab("Аккаунт AnimeLIB (необязательно)"), 4, 0)
    layout.addWidget(tab._api_key_button("animelib", "Токен AnimeLIB"), 4, 1)
    tab.chk_episode_scene = api.QCheckBox("Проверять сцену и субтитры")
    tab.chk_episode_scene.setChecked(True)
    tab.chk_episode_scene.setToolTip(
        "Проверка готового ролика: японский разговор, нужный язык сабов, без OP/ED и титров. "
        "Неудачный участок заменяется. Требуется ключ Gemini.")
    layout.addWidget(tab.chk_episode_scene, 5, 0, 1, 2)
    def selected(_index):
        tab.chk_episode_ru.setChecked(tab.cb_episode_subtitles.currentData() != "none")
        tab._refresh_song_opts()
    def legacy(checked):
        if not checked:
            tab.cb_episode_subtitles.setCurrentIndex(0)
        elif tab.cb_episode_subtitles.currentData() == "none":
            tab.cb_episode_subtitles.setCurrentIndex(1)
    tab.cb_episode_subtitles.currentIndexChanged.connect(selected)
    tab.chk_episode_ru.toggled.connect(legacy)
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
    settings.episode_subtitle_mode = tab.cb_episode_subtitles.currentData()
    settings.episode_scene_check = tab.chk_episode_scene.isChecked()
    settings.animelib_token = tab._api_key("animelib")


def apply_controls(tab, settings):
    tab.chk_episode.setChecked(settings.pack_episode)
    tab.mix._set_part("episode", settings.pack_episode)
    tab.cb_episode_subtitles.setCurrentIndex(tab.cb_episode_subtitles.findData(mode(settings)))
    tab.chk_episode_scene.setChecked(settings.episode_scene_check)
    tab._migrate_api_key("animelib", getattr(settings, "animelib_token", ""))
