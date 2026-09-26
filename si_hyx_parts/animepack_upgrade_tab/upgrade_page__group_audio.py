# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_UpgradePage: _group_audio. Public namespace: animepack_upgrade_tab."""
from __future__ import annotations
import animepack_upgrade_tab as _api


# ── группа «Аудио» ────────────────────────────────────────────────────
def _group_audio(self) -> _api.QGroupBox:
    grp = _api.QGroupBox("Сжать тяжёлое аудио")
    grp.setCheckable(True)
    grp.setChecked(True)
    grp.setToolTip(
        "Дорожки в паке тяжелее порога перекодируются в opus — тем же "
        "кодером и с теми же настройками, что во вкладке «Обработка» "
        "(libopus, переменный битрейт).\n"
        "Битрейт исходника сначала спрашивается у ffprobe: если он и так не "
        "выше выбранного, файл не трогается вовсе — перекод только испортил "
        "бы звук, ничего не выиграв.\n"
        "Громкость не трогается: в готовом паке её уже выставил автор.")
    self.grp_audio = grp
    g = _api.QGridLayout(grp); g.setHorizontalSpacing(6); g.setVerticalSpacing(8)
    r = 0
    self.sp_aud_min = _api._no_wheel(_api.QDoubleSpinBox())
    self.sp_aud_min.setRange(0.1, 500.0)
    self.sp_aud_min.setSingleStep(1.0)
    self.sp_aud_min.setDecimals(1)
    self.sp_aud_min.setValue(_api.UpgradeSettings().audio_min_mb)
    self.sp_aud_min.setSuffix(" МБ")
    self.sp_aud_min.setToolTip(
        "Дорожки легче этого не трогаются вовсе: они и так не тянут пак "
        "вниз, а каждое перекодирование — это время.")
    g.addWidget(self._lab("Сжимать, если тяжелее"), r, 0)
    g.addWidget(self.sp_aud_min, r, 1)
    r += 1
    self.cb_aud_kbps = _api._no_wheel(_api.QComboBox())
    self.cb_aud_kbps.addItems([str(k) for k in _api.AUDIO_BITRATES])
    self.cb_aud_kbps.setCurrentText(str(_api.UpgradeSettings().audio_kbps))
    self.cb_aud_kbps.setToolTip(
        "В скольки килобитах кодировать. Список — тот же, что во вкладке "
        "«Обработка»; 128 кбит — качество звука на YouTube, 192 — с запасом "
        "и заметно легче исходных mp3 и wav.")
    g.addWidget(self._lab("Битрейт, кбит/с"), r, 0)
    g.addWidget(self.cb_aud_kbps, r, 1)
    r += 1
    self.chk_aud_norm = _api.QCheckBox("Нормализовать громкость (loudnorm)")
    self.chk_aud_norm.setToolTip(
        "Тот же loudnorm и с теми же тремя числами, что во вкладке "
        "«Обработка»: целевая громкость (LUFS), допустимый разброс (LRA) и "
        "потолок пиков (TP).\n"
        "Выключено по умолчанию: в ЧУЖОМ паке громкость уже выставил автор, "
        "и двигать её вслепую нельзя.\n"
        "Включённая, она снимает обе оговорки «не трогаю»: дорожка "
        "перекодируется, даже если и так не богаче выбранного битрейта и "
        "даже если легче не станет, — иначе нормализовать было бы нечего.\n"
        "Звук роликов нормализуется той же настройкой.")
    g.addWidget(self.chk_aud_norm, r, 0, 1, 2)
    r += 1
    norm_row = _api.QHBoxLayout()
    norm_row.setSpacing(4)
    self.sp_norm_i = _api._no_wheel(_api.QDoubleSpinBox())
    self.sp_norm_i.setRange(-60.0, 20.0)
    self.sp_norm_i.setSingleStep(0.1)
    self.sp_norm_i.setValue(_api.UpgradeSettings().audio_norm_i)
    self.sp_norm_i.setToolTip("Целевая громкость, LUFS. −20 — как в "
                              "«Обработке».")
    self.sp_norm_lra = _api._no_wheel(_api.QDoubleSpinBox())
    self.sp_norm_lra.setRange(0.0, 50.0)
    self.sp_norm_lra.setSingleStep(0.1)
    self.sp_norm_lra.setValue(_api.UpgradeSettings().audio_norm_lra)
    self.sp_norm_lra.setToolTip("Допустимый разброс громкости (LRA).")
    self.sp_norm_tp = _api._no_wheel(_api.QDoubleSpinBox())
    self.sp_norm_tp.setRange(-60.0, 10.0)
    self.sp_norm_tp.setSingleStep(0.1)
    self.sp_norm_tp.setValue(_api.UpgradeSettings().audio_norm_tp)
    self.sp_norm_tp.setToolTip("Потолок пиков, dBTP.")
    for name, widget in (("LUFS:", self.sp_norm_i), ("LRA:", self.sp_norm_lra),
                         ("TP:", self.sp_norm_tp)):
        widget.setMaximumWidth(70)
        norm_row.addWidget(self._lab(name))
        norm_row.addWidget(widget)
    norm_row.addStretch(1)
    g.addLayout(norm_row, r, 0, 1, 2)
    r += 1
    g.addWidget(self._hint(
        "Ссылки в content.xml переводятся на новое имя файла (.opus), "
        "остальное медиа копируется как есть. Дорожка, которая после "
        "перекода не стала легче, остаётся исходной."), r, 0, 1, 2)
    g.setColumnStretch(1, 1)
    self.chk_aud_norm.toggled.connect(self._refresh_norm_enabled)
    self._refresh_norm_enabled(self.chk_aud_norm.isChecked())
    return grp

def _refresh_norm_enabled(self, on: bool) -> None:
    """Три числа нормализации без самой нормализации ничего не значат."""
    for widget in (self.sp_norm_i, self.sp_norm_lra, self.sp_norm_tp):
        widget.setEnabled(bool(on))

# ── группа «Видео» ────────────────────────────────────────────────────
def _group_video(self) -> _api.QGroupBox:
    grp = _api.QGroupBox("Сжать тяжёлое видео")
    grp.setCheckable(True)
    grp.setChecked(False)
    grp.setToolTip(
        "Ролики в паке перекодируются в AV1 — тем же кодером и с теми же "
        "флагами, что во вкладке «Обработка» и в генераторе паков "
        "(libsvtav1, keyint=-1 и scd=1: ключевые кадры только на сменах "
        "сцены). Звук ролика идёт в opus на том же битрейте и с той же "
        "нормализацией, что дорожки пака.\n"
        "Выключено по умолчанию НАРОЧНО, в отличие от остальных функций: "
        "перекод ролика идёт минутами, а с галочкой «не в AV1» под него "
        "попадает вообще всё видео пака.\n"
        "Ролик, который после перекода не стал легче, остаётся исходным.")
    self.grp_video = grp
    g = _api.QGridLayout(grp); g.setHorizontalSpacing(6); g.setVerticalSpacing(8)
    r = 0
    self.sp_vid_min = _api._no_wheel(_api.QDoubleSpinBox())
    self.sp_vid_min.setRange(0.1, 2000.0)
    self.sp_vid_min.setSingleStep(5.0)
    self.sp_vid_min.setDecimals(1)
    self.sp_vid_min.setValue(_api.UpgradeSettings().video_min_mb)
    self.sp_vid_min.setSuffix(" МБ")
    self.sp_vid_min.setToolTip(
        "Ролики тяжелее этого перекодируются всегда — каким бы кодеком они "
        "ни были закодированы, хоть тем же AV1.")
    g.addWidget(self._lab("Сжимать, если тяжелее"), r, 0)
    g.addWidget(self.sp_vid_min, r, 1)
    r += 1
    self.chk_vid_non_av1 = _api.QCheckBox("Сжимать и всё, что не в AV1")
    self.chk_vid_non_av1.setChecked(True)
    self.chk_vid_non_av1.setToolTip(
        "Лёгкие ролики тоже перекодируются, если кодек у них отличается от "
        "AV1: mp4 с H.264 из чужого пака в AV1 худеет вдвое-втрое даже без "
        "ужимания разрешения.\n"
        "Кодек виден только после распаковки (ffprobe читает файл, а не "
        "запись архива), поэтому с этой галочкой из пака достаётся каждый "
        "ролик — на паке с десятком роликов это заметное время.\n"
        "Ролик, который уже в AV1 и легче порога, не трогается.")
    g.addWidget(self.chk_vid_non_av1, r, 0, 1, 2)
    r += 1
    self.sp_vid_crf = _api._no_wheel(_api.QSpinBox())
    self.sp_vid_crf.setRange(0, 63)
    self.sp_vid_crf.setValue(_api.UpgradeSettings().video_crf)
    self.sp_vid_crf.setToolTip(
        "Качество AV1 (CRF): больше — легче и хуже. 45 стоит и в "
        "генераторе паков — для ролика на экране SIGame этого хватает.")
    g.addWidget(self._lab("CRF (0–63)"), r, 0)
    g.addWidget(self.sp_vid_crf, r, 1)
    r += 1
    self.sp_vid_preset = _api._no_wheel(_api.QSpinBox())
    self.sp_vid_preset.setRange(0, 13)
    self.sp_vid_preset.setValue(_api.UpgradeSettings().video_preset)
    self.sp_vid_preset.setToolTip(
        "Пресет libsvtav1: 13 — самый быстрый, 0 — самый медленный и чуть "
        "качественнее. Тринадцать стоит и в генераторе паков.")
    g.addWidget(self._lab("Пресет (0–13)"), r, 0)
    g.addWidget(self.sp_vid_preset, r, 1)
    r += 1
    self.cb_vid_height = _api._no_wheel(_api.QComboBox())
    for height in _api.VIDEO_HEIGHTS:
        self.cb_vid_height.addItem("Исходное" if not height else f"{height}p",
                                   height)
    self.cb_vid_height.setToolTip(
        "До какой высоты ужимать кадр. Ролик только уменьшается: 480p не "
        "растянется до 1080p, сколько ни выбирай.")
    g.addWidget(self._lab("Разрешение"), r, 0)
    g.addWidget(self.cb_vid_height, r, 1)
    r += 1
    g.addWidget(self._hint(
        "Ссылки в content.xml переводятся на новое имя файла (.mp4). "
        "Ролики кодируются по одному: libsvtav1 и сам занимает все ядра. "
        "Битрейт звука и нормализацию ролик берёт из «Сжать тяжёлое "
        "аудио» — своих у него нет, чтобы пак звучал ровно."), r, 0, 1, 2)
    g.setColumnStretch(1, 1)
    return grp

# ── группа «Неиспользуемые файлы» ─────────────────────────────────────
def _group_unused(self) -> _api.QGroupBox:
    grp = _api.QGroupBox("Удалить неиспользуемые файлы")
    grp.setCheckable(True)
    grp.setChecked(True)
    grp.setToolTip(
        "Медиа, на которое в content.xml нет ни одной ссылки, в новый пак "
        "не переносится: автор поменял картинку, а старая осталась лежать "
        "в архиве и весить.\n"
        "Занятым считается файл, чьё имя встретилось где угодно в "
        "content.xml — и в тексте, и в любом атрибуте: логотип пака, "
        "например, записан атрибутом, а не ссылкой в вопросе.\n"
        "Служебные части пака (content.xml, Texts/, [Content_Types].xml) "
        "не трогаются вовсе. Если «неиспользуемым» вышло ВСЁ медиа пака, "
        "не удаляется ни один файл: так не бывает.")
    self.grp_unused = grp
    g = _api.QGridLayout(grp); g.setHorizontalSpacing(6); g.setVerticalSpacing(8)
    g.setColumnStretch(1, 1)
    return grp

def _build_actions(self) -> _api.QWidget:
    box = _api.QWidget()
    v = _api.QVBoxLayout(box)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(6)
    self.btn_start = _api.QPushButton("Проапгрейдить пак")
    self.btn_start.setIcon(_api.get_icon('fa5s.magic', color='#11111b'))
    self.btn_start.setIconSize(_api.QSize(16, 16))
    self.btn_start.setObjectName("b_primary")
    self.btn_start.clicked.connect(self.start)
    self.btn_stop = _api.QPushButton("Стоп")
    self.btn_stop.setIcon(_api.get_icon('fa5s.stop'))
    self.btn_stop.setEnabled(False)
    self.btn_stop.setToolTip("Остановить апгрейд (готовый файл не пишется, "
                             "исходный пак не тронут).")
    self.btn_stop.clicked.connect(self.stop)
    self.btn_open = _api.QPushButton("Открыть папку")
    self.btn_open.setIcon(_api.get_icon('fa5s.folder-open'))
    self.btn_open.setEnabled(False)
    self.btn_open.clicked.connect(self._open_result)
    v.addWidget(self.btn_start)
    row = _api.QHBoxLayout(); row.setSpacing(6)
    row.addWidget(self.btn_stop, 1)
    row.addWidget(self.btn_open, 1)
    v.addLayout(row)
    return box

@staticmethod
def _disable_wheel(root) -> None:
    for cls in (_api.QSpinBox, _api.QDoubleSpinBox, _api.QComboBox):
        for widget in root.findChildren(cls):
            _api._no_wheel(widget)
