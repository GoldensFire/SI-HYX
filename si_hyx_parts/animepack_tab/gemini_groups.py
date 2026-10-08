"""Three Gemini choices, separate from the pack composition controls."""
import animepack_tab as api
from gemini_api import model_thinking_levels
from PyQt6.QtWidgets import QComboBox, QSizePolicy


def refresh_voice(tab):
    enabled = tab.chk_description_audio.isChecked() and tab.chk_description_voice.isChecked()
    tab.lab_description_gemini_model.setVisible(enabled)
    tab.cb_description_gemini_model.setVisible(enabled)


def refresh_image_levels(tab):
    box = tab.cb_gemini_image_think
    want = box.currentData()
    box.clear()
    for level in model_thinking_levels(tab.cb_gemini_image_model.currentText()):
        box.addItem(api.GEMINI_THINKING_LABELS[level], level)
    box.setCurrentIndex(max(0, box.findData(want)))


def build(tab):
    group = tab.group_gemini = api.QGroupBox("Модели ИИ · Gemini")
    grid = api.QGridLayout(group)
    grid.addWidget(tab.btn_gemini_key, 0, 0, 1, 2)
    tab.cb_gemini_image_model = api.QComboBox()
    for model in api.GEMINI_MODELS:
        tab.cb_gemini_image_model.addItem(model, model)
    tab.cb_gemini_image_model.setCurrentText(api.GEMINI_DEFAULT_MODEL)
    tab.cb_gemini_image_think = api.QComboBox()
    tab.cb_gemini_image_model.currentTextChanged.connect(
        lambda: refresh_image_levels(tab))
    refresh_image_levels(tab)
    tab.cb_gemini_image_model.setToolTip(
        "Модель для проверки изображений и отрывков серий. "
        "Используется выбранная модель; при перегрузке или исчерпании квоты "
        "автоматической замены другой моделью нет.")
    groups = (
        ("Изображения", "Кадры, студии, кадры с эффектами, манга, проверка артов Pixiv, "
         "а также отрывки серий: проверка сцены по видео и перевод их субтитров",
         tab.cb_gemini_image_model, tab.cb_gemini_image_think),
        ("Сюжет/Диалоги", "Сюжет, диалоги и перевод описания",
         tab.cb_gemini_model, tab.cb_gemini_think),
        ("Названия", "Синонимы, антонимы, украинский и определения; анаграммы создаются локально",
         tab.cb_gemini_title_model, tab.cb_gemini_title_think),
    )
    row = 1
    for label, tip, model, think in groups:
        heading = tab._lab(label)
        heading.setToolTip(tip)
        grid.addWidget(heading, row, 0, 1, 2)
        grid.addWidget(model, row + 1, 0, 1, 2)
        grid.addWidget(think, row + 2, 0, 1, 2)
        model.show()
        think.show()
        row += 3
        if label == "Сюжет/Диалоги":
            tab.lab_description_gemini_model = tab._lab("Озвучка описания · Gemini")
            grid.addWidget(tab.lab_description_gemini_model, row, 0, 1, 2)
            grid.addWidget(tab.cb_description_gemini_model, row + 1, 0, 1, 2)
            row += 2
    grid.addWidget(tab.lbl_gemini_quota, row, 0, 1, 2)
    # Historical names remain available to existing settings collectors.
    for name in ("cb_pixiv_gemini_model", "cb_manga_gemini_model"):
        getattr(tab, name).hide()
        setattr(tab, name, tab.cb_gemini_image_model)
    tab.box_gemini_titles.hide()
    for widget in (tab.btn_gemini_key, tab.lbl_gemini_quota):
        widget.show()
    for combo in group.findChildren(QComboBox):
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(12)
        combo.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        combo.setMinimumWidth(0)
    tab.chk_description_audio.toggled.connect(lambda _: refresh_voice(tab))
    tab.chk_description_voice.toggled.connect(lambda _: refresh_voice(tab))
    refresh_voice(tab)


def apply(tab, settings):
    from si_hyx_parts.animepack.gemini_settings import image_model
    model = image_model(settings) or api.GEMINI_DEFAULT_MODEL
    box = tab.cb_gemini_image_model
    if box.findText(model) < 0:
        box.addItem(model, model)
    box.setCurrentText(model)
    refresh_image_levels(tab)
    think = tab.cb_gemini_image_think
    think.setCurrentIndex(max(0, think.findData(settings.gemini_image_thinking)))
