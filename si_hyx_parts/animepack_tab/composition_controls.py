"""Compact composition controls and shared Gemini settings."""
import animepack_tab as api
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QComboBox, QSizePolicy

from si_hyx_parts.animepack.title_kinds import TITLE_LABELS, GEMINI_TITLE_KINDS


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
    for key, label in TITLE_LABELS.items():
        chk = api.QCheckBox(label)
        setattr(tab, "chk_" + key, chk)
        chk.toggled.connect(lambda value, k=key: toggle(tab, k, value))
        tab.composition_checks[key] = chk
    for key in ("video", "manga", "pixel", "anagram", "dialogue", "plot", "ai_art",
                "pixiv_art", "sakuga", "studio"):
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
    # Сколько строк занял сам _group_songs — оттуда и продолжаем.
    row = int(getattr(tab, "_plot_grid_rows", 4))
    tab.box_plot.layout().addWidget(tab.lbl_gemini_quota, row, 0, 1, 2)
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


# Настройки каждого рода вопросов — в том порядке, в каком они идут под его
# галочкой. «Показ текста» общий для всех текстовых вопросов, поэтому стоит
# под последним из них; настройки Gemini общие для сюжета и загадок по
# названию — они под «Сюжетом», прямо над этими загадками.
_OPTIONS = {
    "songs": ("box_song_opts",),
    "video": ("box_video_opts",),
    "chars": ("box_chars",),
    "manga": ("box_manga",),
    "pixel": ("box_pixel",),
    "anagram": ("box_anagram",),
    "dialogue": ("box_dialogue",),
    "plot": ("box_plot",),
    # Под последней загадкой по названию — своя модель Gemini для них
    # (просьба пользователя) и общий для всех текстовых вопросов показ текста.
    "definitions": ("box_gemini_titles", "box_text_cps"),
    "ai_art": ("box_ai_art",),
    "pixiv_art": ("box_pixiv_art",),
    "sakuga": ("box_sakuga",),
    "studio": ("box_studio",),
}


def _display_order(tab):
    """Порядок галочек на панели: загадки по названию идут сразу за «Сюжетом».

    Тогда общий ключ Gemini стоит ровно над теми родами вопросов, которым он и
    нужен, а своя модель загадок — сразу под ними."""
    keys = [key for key in tab.mix.KEYS if key not in TITLE_LABELS]
    at = keys.index("plot") + 1
    return keys[:at] + list(TITLE_LABELS) + keys[at:]


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
    titles = any(getattr(tab, "chk_" + key).isChecked()
                 for key in GEMINI_TITLE_KINDS)
    enabled = tab.chk_plot.isChecked() or tab.chk_dialogue.isChecked() or titles
    tab.box_plot.setVisible(enabled)
    # Своя модель загадок по названию нужна только при включённых загадках.
    box = getattr(tab, "box_gemini_titles", None)
    if box is not None:
        box.setVisible(titles)
    tab.cb_plot_mode.setEnabled(tab.chk_plot.isChecked())
    # Своя рамка сложности сюжета держится на его галочке: коробка та же, но
    # показывают её ещё и ради общих настроек Gemini.
    from .level_controls import refresh_plot
    refresh_plot(tab)


def refresh_text_timing(tab):
    keys = ("anagram", "dialogue", "plot") + tuple(TITLE_LABELS)
    enabled = any(getattr(tab, "chk_" + key).isChecked() for key in keys)
    tab.box_text_cps.setVisible(enabled)


def refresh_quota(tab):
    """Сколько запросов модели ушло сегодня — и что мы знаем про её потолок.

    Считаем ОБСЛУЖЕННЫЕ запросы: 429 и 5xx Google отклоняет, и в суточный
    лимит они не идут. Потолок берётся из ответа самого сервера, когда он его
    называл («limit: 20»), — гадать за Google мы не беремся."""
    from gemini_usage import daily_cap, exhausted_today, requests_today
    key, model = tab._api_key("gemini"), tab.cb_gemini_model.currentText()
    count = requests_today(key, model)
    cap = daily_cap(key, model)
    if exhausted_today(key, model):
        left = " Квота на сегодня исчерпана — модель будет пропускаться."
    elif cap:
        left = f" Потолок по словам Google — {cap}, осталось {max(0, cap - count)}."
    else:
        left = ""
    tab.lbl_gemini_quota.setText(
        f"Gemini: сегодня обслужено запросов — {count}.{left} "
        'Точный остаток квоты: <a href="https://aistudio.google.com/rate-limit">AI Studio</a>.')


def change_quota_model(tab):
    tab._quota_model = tab.cb_gemini_model.currentText()
    refresh_quota(tab)


def collect(tab, settings):
    settings.gemini_daily_limits = dict(getattr(tab, "_gemini_daily_limits", {}))
    for key in TITLE_LABELS:
        setattr(settings, "pack_" + key, getattr(tab, "chk_" + key).isChecked())
        setattr(settings, "pct_" + key, tab.mix.shares()[key])
    settings.composition_enabled = tab.mix.keys()


def apply(tab, settings):
    tab._gemini_daily_limits = dict(settings.gemini_daily_limits)
    tab._quota_model = settings.gemini_model or api.GEMINI_DEFAULT_MODEL
    for key in ("songs", "frames", "chars"):
        enabled = (key in settings.composition_enabled if settings.composition_enabled is not None
                   else settings.mix_shares.get({"frames": api.FRAME_KIND, "chars": api.CHAR_KIND}.get(key, key), 0) > 0)
        getattr(tab, "chk_" + key).setChecked(enabled)
        tab.mix._set_part(key, enabled)
    for key in TITLE_LABELS:
        getattr(tab, "chk_" + key).setChecked(getattr(settings, "pack_" + key))
    refresh_gemini(tab)
    refresh_text_timing(tab)
