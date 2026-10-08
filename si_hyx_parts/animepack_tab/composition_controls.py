"""Compact composition controls and shared Gemini settings."""
import animepack_tab as api
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QComboBox, QSizePolicy

from si_hyx_parts.animepack.title_kinds import TITLE_LABELS


def rebuild(tab, group):
    grid = group.layout()
    while grid.count():
        item = grid.takeAt(0)
        if item.widget():
            item.widget().hide()
    tab.composition_checks = {}
    for key in ("songs", "frames", "chars"):
        chk = api.QCheckBox(tab.mix.LABELS[key])
        chk.setChecked(key == "songs")
        setattr(tab, "chk_" + key, chk)
        tab.mix._set_part(key, chk.isChecked())
        chk.toggled.connect(lambda value, k=key: toggle(tab, k, value))
        tab.composition_checks[key] = chk
    from .title_composition import build as build_titles
    build_titles(tab)
    tab.composition_checks["titles"] = tab.chk_titles
    for key in ("manga", "pixel", "dialogue", "plot",
                "description_audio", "ai_art",
                "pixiv_art", "sakuga", "studio", "episode"):
        tab.composition_checks[key] = getattr(tab, "chk_" + key)
    grid.addWidget(tab.mix, 0, 0, 1, 4)
    grid.addWidget(tab.lbl_left, 1, 0, 1, 4)
    tab.mix.show()
    tab.lbl_left.show()
    # Настройки рода вопросов стоят ПРЯМО ПОД его галочкой, а не общей кучей
    # в самом низу панели (просьба пользователя): раньше до «Рассуждения»
    # Gemini или языка глав манги надо было долистать через весь список.
    _wrap_loose_options(tab)
    row = 2
    for key in _display_order(tab):
        chk = tab.composition_checks[key]
        grid.addWidget(chk, row, 0, 1, 4)
        chk.show()
        row += 1
        for widget in _OPTIONS.get(key, ()):
            box = getattr(tab, widget, None)
            if box is None:
                continue
            grid.addWidget(box, row, 0, 1, 4)
            row += 1
    tab.box_chars.setVisible(tab.chk_chars.isChecked())
    tab.box_song_opts.show()
    tab.lbl_gemini_quota = tab._hint("")
    tab.lbl_gemini_quota.setOpenExternalLinks(True)
    # Строки «Лимит Gemini / сутки» здесь больше нет (просьба пользователя):
    # точный остаток квоты всё равно знает только AI Studio, а заданное руками
    # число лишь притворялось им. Расход запросов самого приложения остался.
    from .gemini_groups import build as build_gemini
    build_gemini(tab)
    tab._gemini_daily_limits = {}
    tab._quota_model = tab.cb_gemini_model.currentText()
    tab.cb_gemini_model.currentTextChanged.connect(lambda: change_quota_model(tab))
    tab._gemini_quota_timer = QTimer(tab)
    tab._gemini_quota_timer.timeout.connect(lambda: refresh_quota(tab))
    tab._gemini_quota_timer.start(1500)
    refresh_quota(tab)
    for combo in group.findChildren(QComboBox):
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(12)
        combo.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        combo.setMinimumWidth(0)


# Each question kind keeps its options below its checkbox.
_OPTIONS = {
    "songs": ("box_song_opts",),
    "frames": ("box_frames",),
    "chars": ("box_chars",),
    "manga": ("box_manga",),
    "pixel": ("box_pixel",),
    "titles": ("box_titles", "box_text_cps"),
    "dialogue": ("box_dialogue",),
    "plot": ("box_plot",),
    "description_audio": ("box_description_audio",),
    "ai_art": ("box_ai_art",),
    "pixiv_art": ("box_pixiv_art",),
    "sakuga": ("box_sakuga",),
    "episode": ("box_episode",),
    "studio": ("box_studio",),
}


def _display_order(tab):
    """Order of the outer composition categories."""
    return [key for key in tab.mix.KEYS if key != "video"]


def _indented(tab, name, *widgets):
    """Коробка с отступом под галочку — как у остальных настроек рода."""
    box = api.SettingsBox()
    grid = api.QGridLayout(box)
    grid.setContentsMargins(16, 0, 0, 0)
    grid.setHorizontalSpacing(8)
    grid.setVerticalSpacing(6)
    for column, widget in enumerate(widgets):
        grid.addWidget(widget, 0, column)
        widget.show()
    grid.setColumnStretch(len(widgets) - 1, 1)
    setattr(tab, name, box)
    return box


def _wrap_loose_options(tab):
    """Настройки персонажей — коробкой под их галочкой.

    Без общей коробки их не удавалось ни поставить под свою галочку, ни
    скрыть вместе с подписью. А вот сложность персонажей уехала в группу
    «Аниме», ко всем остальным рамкам сложности (просьба пользователя)."""
    if getattr(tab, "box_chars", None) is None:
        _indented(tab, "box_chars", tab._lab("Кого спрашивать"),
                  tab.cb_char_roles)


def toggle(tab, key, value):
    tab.mix._set_part(key, value)
    refresh_gemini(tab)
    refresh_text_timing(tab)
    tab._refresh_song_opts()


def refresh_gemini(tab):
    from .frame_gemini_controls import refresh as refresh_frames
    refresh_frames(tab)
    tab.box_plot.setVisible(tab.chk_plot.isChecked())
    # Model controls now live in their own group, outside the composition.
    box = getattr(tab, "box_gemini_titles", None)
    if box is not None:
        box.setVisible(False)
    if hasattr(tab, "group_gemini"):
        tab.group_gemini.setVisible(True)
    tab.cb_plot_mode.setEnabled(tab.chk_plot.isChecked())
    # Plot difficulty follows the plot checkbox.
    from .level_controls import refresh_plot
    refresh_plot(tab)


def refresh_text_timing(tab):
    enabled = any(getattr(tab, "chk_" + key).isChecked()
                  for key in ("titles", "dialogue", "plot"))
    tab.box_text_cps.setVisible(enabled)


def refresh_quota(tab):
    """Локальная оценка расхода и суточный предел, названный сервером."""
    from gemini_usage import daily_cap, exhausted_today, requests_today
    key, model = tab._api_key("gemini"), tab.cb_gemini_model.currentText()
    count = requests_today(key, model)
    cap = daily_cap(key, model)
    if exhausted_today(key, model):
        left = " Google сообщил об исчерпании квоты — модель пока пропускается."
    elif cap:
        left = (f" Дневной предел Google — {cap}, "
                f"по этой оценке осталось {max(0, cap - count)}.")
    else:
        left = ""
    tab.lbl_gemini_quota.setText(
        f"Gemini: возможный расход квоты сегодня — {count} (оценка SI-HYX).{left} "
        'Показатели квоты: <a href="https://aistudio.google.com/rate-limit">AI Studio</a>.')


def change_quota_model(tab):
    tab._quota_model = tab.cb_gemini_model.currentText()
    refresh_quota(tab)


def collect(tab, settings):
    settings.gemini_daily_limits = dict(getattr(tab, "_gemini_daily_limits", {}))
    from .title_composition import collect as collect_titles
    collect_titles(tab, settings)
    settings.composition_enabled = tab.mix.keys()


def apply(tab, settings):
    tab._gemini_daily_limits = dict(settings.gemini_daily_limits)
    tab._quota_model = settings.gemini_model or api.GEMINI_DEFAULT_MODEL
    for key in ("songs", "frames", "chars"):
        enabled = (key in settings.composition_enabled if settings.composition_enabled is not None
                   else settings.mix_shares.get({"frames": api.FRAME_KIND, "chars": api.CHAR_KIND}.get(key, key), 0) > 0)
        getattr(tab, "chk_" + key).setChecked(enabled)
        tab.mix._set_part(key, enabled)
    from .title_composition import apply as apply_titles
    apply_titles(tab, settings)
    refresh_gemini(tab)
    refresh_text_timing(tab)
