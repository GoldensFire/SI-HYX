# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_UpgradePage: _fit_settings_width. Public namespace: animepack_upgrade_tab."""
from __future__ import annotations
import animepack_upgrade_tab as _api


def _fit_settings_width(self):
    """Ширина панели настроек — по её содержимому, но не больше, чем даёт
        окно (то же правило, что в «Генерации аниме-пака»)."""
    scroll = getattr(self, "scroll_settings", None)
    panel = scroll.widget() if scroll is not None else None
    if panel is None:
        return
    need = max(panel.sizeHint().width(), panel.minimumSizeHint().width(),
               self.SETTINGS_MIN_W)
    if panel.minimumWidth() != need:
        panel.setMinimumWidth(need)
    sb = max(scroll.verticalScrollBar().sizeHint().width(), 14)
    want = need + sb + 2 * scroll.frameWidth() + 4
    avail = self.width() - 24 - self.TABLE_MIN_W
    if avail > 0:
        want = min(want, max(self.SETTINGS_MIN_W, avail))
    col = getattr(self, "right_col", None) or scroll
    if want != col.width() or col.maximumWidth() != want:
        col.setFixedWidth(want)

def resizeEvent(self, event):
    super(_api._UpgradePage, self).resizeEvent(event)
    if _api._HAS_CORE:
        self._fit_settings_width()

def showEvent(self, event):
    super(_api._UpgradePage, self).showEvent(event)
    if _api._HAS_CORE:
        self._fit_settings_width()

# ── перетаскивание пака мышью ─────────────────────────────────────────
@staticmethod
def _dropped_siq(event) -> str:
    data = event.mimeData()
    if not data.hasUrls():
        return ""
    for url in data.urls():
        path = url.toLocalFile()
        if path.lower().endswith(".siq"):
            return path
    return ""

def dragEnterEvent(self, event):
    if self._dropped_siq(event):
        event.acceptProposedAction()
    else:
        super(_api._UpgradePage, self).dragEnterEvent(event)

def dropEvent(self, event):
    path = self._dropped_siq(event)
    if not path:
        super(_api._UpgradePage, self).dropEvent(event)
        return
    self.set_siq(path)
    event.acceptProposedAction()

def set_siq(self, path: str) -> bool:
    """Подставить пак снаружи — тем же путём, что и перетаскивание мышью.
        False — вкладка не собралась (нет ядра) или файла нет на диске."""
    if not _api._HAS_CORE or not path or not _api.os.path.isfile(path):
        return False
    self._siq = path
    self._refresh_siq_label()
    return True

def _apply_styles(self):
    self.setStyleSheet(f"""
            QWidget {{ color: {_api.C['text']}; }}
            QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
                background: {_api.C['surface3']}; border: 1px solid {_api.C['border']};
                border-radius: 5px; padding: 5px 7px; color: {_api.C['text']};
            }}
            QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
                border: 1px solid {_api.C['accent']};
            }}
            QPushButton, QToolButton {{
                background: {_api.C['surface3']}; border: 1px solid {_api.C['border']};
                border-radius: 5px; padding: 6px 12px; color: {_api.C['text']};
            }}
            QPushButton:hover, QToolButton:hover {{ background: {_api.C['surface2']}; }}
            QPushButton:disabled {{ color: {_api.C['text3']}; }}
            QPushButton#b_primary {{
                background: {_api.C['accent']}; color: #11111b; border: none;
                font-weight: 700;
            }}
            QPushButton#b_primary:hover {{ background: {_api.C['accent2']}; }}
            QPushButton#b_primary:disabled {{
                background: {_api.C['surface3']}; color: {_api.C['text3']};
            }}
            QGroupBox {{
                border: 1px solid {_api.C['border']}; border-radius: 6px;
                margin-top: 10px; padding-top: 8px; font-weight: bold;
                color: {_api.C['accent']};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin; left: 10px; padding: 0 4px;
            }}
            /* Выключенная функция и выглядеть должна выключенной. */
            QGroupBox:!enabled, QGroupBox::title:!enabled {{ color: {_api.C['text3']}; }}
            QTableWidget, QScrollArea#packcard {{
                background: {_api.C['surface']}; border: 1px solid {_api.C['border']};
                border-radius: 6px; outline: none;
            }}
            QScrollArea#packcard > QWidget > QWidget {{
                background: {_api.C['surface']};
            }}
            QHeaderView::section {{
                background: {_api.C['surface2']}; color: {_api.C['text2']};
                border: none; padding: 3px 3px; font-size: 11px;
            }}
            QTableWidget::item:selected {{
                background: {_api.C['surface3']}; color: {_api.C['text']};
            }}
        """)

# ── выбор файлов ──────────────────────────────────────────────────────
def _choose_siq(self):
    start = (_api.os.path.dirname(self._siq) if self._siq
             else self._out_dir or _api.os.path.expanduser("~"))
    path, _ = _api.QFileDialog.getOpenFileName(
        self, "Пак, который надо проапгрейдить", start,
        "Пакеты SIGame (*.siq);;Все файлы (*)")
    if not path:
        return
    self._siq = path
    self._refresh_siq_label()

def _refresh_siq_label(self):
    if not self._siq:
        self.lbl_siq.setText("Пак не выбран: нажмите кнопку выше или "
                             "перетащите .siq на вкладку.")
        self.lbl_siq.setToolTip("")
        self._show_pack_card()
        return
    try:
        size = _api.os.path.getsize(self._siq) / (1024 * 1024)
        size_text = f", {size:.1f} МБ"
    except OSError:
        size_text = ""
    self.lbl_siq.setText(f"{_api.os.path.basename(self._siq)}{size_text}")
    self.lbl_siq.setToolTip(self._siq)
    self._show_pack_card()

def _choose_out_dir(self):
    start = self._out_dir or (_api.os.path.dirname(self._siq) if self._siq
                              else _api.os.path.expanduser("~"))
    folder = _api.QFileDialog.getExistingDirectory(
        self, "Куда класть готовый пак", start)
    if folder:
        self._out_dir = folder
        self._refresh_out_dir_label()

def _refresh_out_dir_label(self):
    if self._out_dir:
        self.lbl_out_dir.setText(self._out_dir)
        self.lbl_out_dir.setToolTip(self._out_dir)
    else:
        self.lbl_out_dir.setText("Рядом с исходным паком.")
        self.lbl_out_dir.setToolTip("")

# ── настройки ─────────────────────────────────────────────────────────
def collect(self) -> '_api.UpgradeSettings':
    s = _api.UpgradeSettings()
    s.profile = self.profile
    s.strip_specials = self.grp_specials.isChecked()
    s.strip_no_question = self.chk_no_question.isChecked()
    s.add_titles = self.grp_titles.isChecked()
    s.strict_match = self.chk_strict.isChecked()
    s.use_other_answers = self.chk_other_answers.isChecked()
    s.fix_case = self.chk_fix_case.isChecked()
    s.add_poster = self.chk_poster.isChecked()
    s.check_characters = self.chk_characters.isChecked()
    s.book_themes = self.chk_book_themes.isChecked()
    s.max_variants = self.sp_max_variants.value()
    s.min_query_len = self.sp_min_len.value()
    s.strip_repeated_text = self.grp_repeats.isChecked()
    s.repeat_text_max_len = self.sp_repeat_len.value()
    s.strip_known_labels = self.chk_known_labels.isChecked()
    s.merge_text_audio = self.grp_merge.isChecked()
    s.compress_images = self.grp_images.isChecked()
    s.image_min_mb = self.sp_img_min.value()
    s.image_limit_kb = self.sp_img_kb.value()
    s.image_speed = self.sp_img_speed.value()
    s.drop_empty_questions = self.grp_empty.isChecked()
    s.compress_audio = self.grp_audio.isChecked()
    s.audio_min_mb = self.sp_aud_min.value()
    s.audio_kbps = _api.nearest_bitrate(self.cb_aud_kbps.currentText())
    s.audio_norm = self.chk_aud_norm.isChecked()
    s.audio_norm_i = self.sp_norm_i.value()
    s.audio_norm_lra = self.sp_norm_lra.value()
    s.audio_norm_tp = self.sp_norm_tp.value()
    s.compress_video = self.grp_video.isChecked()
    s.video_min_mb = self.sp_vid_min.value()
    s.video_non_av1 = self.chk_vid_non_av1.isChecked()
    s.video_crf = self.sp_vid_crf.value()
    s.video_preset = self.sp_vid_preset.value()
    s.video_height = _api.nearest_height(self.cb_vid_height.currentData())
    s.drop_unused = self.grp_unused.isChecked()
    s.out_dir = self._out_dir
    return s

def get_settings(self) -> dict:
    """Настройки вкладки для settings.json."""
    if not _api._HAS_CORE:
        return dict(self._initial)
    data = self.collect().to_dict()
    # Сам пак тоже запоминаем: обычно дорабатывают тот же файл, что и в
    # прошлый раз, и искать его в проводнике заново незачем.
    data["siq"] = self._siq
    return data

def apply_settings(self, data: dict):
    if not _api._HAS_CORE or not isinstance(data, dict):
        return
    s = _api.UpgradeSettings.from_dict(data)
    self.grp_specials.setChecked(s.strip_specials)
    self.chk_no_question.setChecked(s.strip_no_question)
    self.grp_titles.setChecked(s.add_titles)
    self.chk_strict.setChecked(s.strict_match)
    self.chk_other_answers.setChecked(s.use_other_answers)
    self.chk_fix_case.setChecked(s.fix_case)
    self.chk_poster.setChecked(s.add_poster)
    self.chk_characters.setChecked(s.check_characters)
    self.chk_book_themes.setChecked(s.book_themes)
    self.sp_max_variants.setValue(max(1, min(50, int(s.max_variants))))
    self.sp_min_len.setValue(max(1, min(20, int(s.min_query_len))))
    self.grp_repeats.setChecked(s.strip_repeated_text)
    self.sp_repeat_len.setValue(max(1, min(500, int(s.repeat_text_max_len))))
    self.chk_known_labels.setChecked(s.strip_known_labels)
    self.grp_merge.setChecked(s.merge_text_audio)
    self.grp_images.setChecked(s.compress_images)
    self.sp_img_min.setValue(max(0.1, min(100.0, float(s.image_min_mb))))
    self.sp_img_kb.setValue(max(50, min(20000, int(s.image_limit_kb))))
    self.sp_img_speed.setValue(max(0, min(8, int(s.image_speed))))
    self.grp_empty.setChecked(s.drop_empty_questions)
    self.grp_audio.setChecked(s.compress_audio)
    self.sp_aud_min.setValue(max(0.1, min(500.0, float(s.audio_min_mb))))
    self.cb_aud_kbps.setCurrentText(str(_api.nearest_bitrate(s.audio_kbps)))
    self.chk_aud_norm.setChecked(s.audio_norm)
    self.sp_norm_i.setValue(max(-60.0, min(20.0, float(s.audio_norm_i))))
    self.sp_norm_lra.setValue(max(0.0, min(50.0, float(s.audio_norm_lra))))
    self.sp_norm_tp.setValue(max(-60.0, min(10.0, float(s.audio_norm_tp))))
    self.grp_video.setChecked(s.compress_video)
    self.sp_vid_min.setValue(max(0.1, min(2000.0, float(s.video_min_mb))))
    self.chk_vid_non_av1.setChecked(s.video_non_av1)
    self.sp_vid_crf.setValue(max(0, min(63, int(s.video_crf))))
    self.sp_vid_preset.setValue(max(0, min(13, int(s.video_preset))))
    height = _api.nearest_height(s.video_height)
    self.cb_vid_height.setCurrentIndex(
        max(0, self.cb_vid_height.findData(height)))
    self.grp_unused.setChecked(s.drop_unused)
    self._out_dir = s.out_dir or ""
    siq = str(data.get("siq") or "")
    # Пропавший файл не подставляем: подпись врала бы про выбранный пак.
    self._siq = siq if siq and _api.os.path.isfile(siq) else ""
    self._refresh_siq_label()
    self._refresh_out_dir_label()

def reset_settings(self):
    # Сброс — про настройки, а не про выбранный файл: терять путь к паку
    # ради галочек пользователь не просил.
    siq = self._siq
    self.apply_settings(_api.UpgradeSettings(profile=self.profile).to_dict())
    self._siq = siq
    self._refresh_siq_label()

# ── работа ────────────────────────────────────────────────────────────
def log(self, msg: str):
    """Всё пишем в общую консоль внизу окна — своей у вкладки нет.

        Профиль в подписи обязателен: страниц две, а консоль на них одна, и без
        него было бы не понять, чей это апгрейд идёт."""
    if self.main is not None and hasattr(self.main, "log"):
        try:
            self.main.log(f"[{_api.PROFILE_LABELS.get(self.profile, 'Апгрейд')}]"
                          f" {msg}")
        except Exception:
            pass
