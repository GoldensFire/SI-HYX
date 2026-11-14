# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""PhotoExportDialog, PhotoExportWorker. Public namespace: photo_tab."""
import photo_tab as _api
import photo_export
from process_mirror import ProcessMirrorMixin
from PyQt6.QtWidgets import QDialog, QDialogButtonBox


class PhotoExportDialog(ProcessMirrorMixin, QDialog):
    """Шестерёнка у «Сохранить» во вкладке «Редактирование фото»: тип экспорта
    и настройки группы «Изображения» вкладки «Обработка». Как окно настроек
    экспорта Монтажа (_ExportSettingsDialog): не копия, а зеркало виджетов
    «Обработки» — правка здесь меняет их и там, и наоборот.

    Окно одно на вкладку и живёт вместе с ней (скрывается, а не удаляется)."""

    def __init__(self, photo_tab, media_tab, parent=None):
        super().__init__(parent)
        self._photo = photo_tab
        self._tm = media_tab
        self._pairs = []
        self._syncing = True
        self.setWindowTitle("Настройки экспорта фото")
        lay = _api.QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 12); lay.setSpacing(10)

        row = _api.QHBoxLayout(); row.setSpacing(8)
        row.addWidget(_api.QLabel("Тип экспорта"))
        self.cmb_mode = _api.QComboBox()
        for key, title in photo_export.EXPORT_MODES:
            self.cmb_mode.addItem(title, key)
        self.cmb_mode.setToolTip(
            "Без потерь — PNG/TIFF/BMP как у исходника (jpg/avif/heic → png).\n"
            "Настройками «Обработки» — сразу сжатый файл (AVIF/WebP/JPG/PNG/ICO) с "
            "лимитом размера, разрешением и прочим из вкладки «Обработка»: TIFF на "
            "50 МБ сразу ложится AVIF'ом в сотни килобайт, без промежуточного PNG.")
        self.cmb_mode.currentIndexChanged.connect(self._on_mode)
        row.addWidget(self.cmb_mode, 1)
        lay.addLayout(row)

        info = _api.QLabel(
            "Ниже — те же настройки, что в группе «Изображения» вкладки «Обработка»: "
            "правка здесь меняет их и там, и наоборот. Перезапись исходника и папка "
            "экспорта «Обработки» к фото не относятся — файл <имя>_photo ложится в "
            "папку сохранения этой вкладки.")
        info.setWordWrap(True)
        info.setStyleSheet("color:#a6adc8; font-size:11px;")
        lay.addWidget(info)

        self._box = self._build_images()
        lay.addWidget(self._box, 1)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save)
        btn_save = bb.button(QDialogButtonBox.StandardButton.Save)
        btn_save.setText("Сохранить")
        btn_save.setCursor(_api.Qt.CursorShape.PointingHandCursor)
        btn_save.setStyleSheet("""
            QPushButton { background: #a6e3a1; color: #11111b; border: none;
                border-radius: 6px; padding: 6px 16px; font-weight: 600; }
            QPushButton:hover { background: #94e2d5; }
        """)
        bb.accepted.connect(self.hide)
        lay.addWidget(bb)
        self._syncing = False
        self.pull_all()

    @staticmethod
    def _row(*widgets):
        h = _api.QHBoxLayout(); h.setSpacing(6)
        for w in widgets:
            h.addWidget(_api.QLabel(w) if isinstance(w, str) else w)
        h.addStretch(1)
        return h

    def _build_images(self):
        tm = self._tm
        g = _api.QGroupBox("Изображения"); f = _api.QVBoxLayout(g); f.setSpacing(6)
        self.c_img_fmt = self._mirror(tm.c_img_fmt)
        self.c_chroma = self._mirror(tm.c_chroma)
        self.ck_lim = self._mirror(tm.ck_lim)
        self.s_lim = self._mirror(tm.s_lim)
        self.s_passes = self._mirror(tm.s_passes)
        self.s_cq = self._mirror(tm.s_cq)
        self.ck_dim = self._mirror(tm.ck_dim)
        self.s_dim = self._mirror(tm.s_dim)
        self.ck_width = self._mirror(tm.ck_width)
        self.s_width = self._mirror(tm.s_width)
        self.ck_height = self._mirror(tm.ck_height)
        self.s_height = self._mirror(tm.s_height)
        self.sl_aspd = self._mirror(tm.sl_aspd)
        self.sl_aspd.setMinimumWidth(160)
        self.ck_gemini_wm = self._mirror(tm.ck_gemini_wm)
        f.addLayout(self._row("Формат:", self.c_img_fmt))
        f.addLayout(self._row("Субдискретизация:", self.c_chroma))
        f.addLayout(self._row(self.ck_lim, self.s_lim))
        f.addLayout(self._row("Проходы подбора:", self.s_passes))
        f.addLayout(self._row("--cq-level (без лимита):", self.s_cq))
        f.addLayout(self._row(self.ck_dim, self.s_dim, "(макс. сторона)"))
        f.addLayout(self._row(self.ck_width, self.s_width))
        f.addLayout(self._row(self.ck_height, self.s_height))
        f.addLayout(self._row("Скорость:", self.sl_aspd))
        f.addLayout(self._row(self.ck_gemini_wm))
        return g

    def pull_all(self):
        self._pull_pairs()
        idx = self.cmb_mode.findData(getattr(self._photo, "export_mode",
                                             photo_export.EXPORT_LOSSLESS))
        self.cmb_mode.blockSignals(True)
        self.cmb_mode.setCurrentIndex(max(0, idx))
        self.cmb_mode.blockSignals(False)
        self._refresh_states()

    def _on_mode(self, _idx):
        if self._syncing:
            return
        self._photo.set_export_mode(self.cmb_mode.currentData())
        self._refresh_states()

    def _refresh_states(self):
        """Как в «Обработке»: лимит открывает своё поле и проходы, а CQ
        работает только без лимита; субдискретизация — только у AVIF. Без
        режима «Обработки» вся группа не действует."""
        self._box.setEnabled(self.cmb_mode.currentData() == photo_export.EXPORT_PROCESS)
        lim = self.ck_lim.isChecked()
        self.s_lim.setEnabled(lim)
        self.s_passes.setEnabled(lim)
        self.s_cq.setEnabled(not lim)
        self.s_dim.setEnabled(self.ck_dim.isChecked())
        self.s_width.setEnabled(self.ck_width.isChecked())
        self.s_height.setEnabled(self.ck_height.isChecked())
        self.c_chroma.setEnabled(self.c_img_fmt.currentText().lower().startswith("avif"))

    def showEvent(self, ev):
        self.pull_all()
        super().showEvent(ev)


class PhotoExportWorker(_api.QThread):
    """Фоновое кодирование фото настройками «Обработки» (photo_export)."""
    progress = _api.pyqtSignal(int, str)
    log = _api.pyqtSignal(str)
    done = _api.pyqtSignal(str)
    failed = _api.pyqtSignal(str)

    def __init__(self, src_path, out_dir, stem, settings, parent=None):
        super().__init__(parent)
        self._src = src_path
        self._out_dir = out_dir
        self._stem = stem
        self._settings = settings
        self._stop = False

    def cancel(self):
        self._stop = True

    def run(self):
        try:
            out = photo_export.export_with_process_settings(
                self._src, self._out_dir, self._stem, self._settings,
                log=self.log.emit,
                progress=lambda pct, label=None: self.progress.emit(
                    int(pct), str(label or "Сжатие фото")),
                should_stop=lambda: self._stop)
            self.done.emit(out)
        except Exception as exc:
            self.failed.emit(str(exc))


PhotoExportDialog.__module__ = _api.__name__
_api.PhotoExportDialog = PhotoExportDialog
PhotoExportWorker.__module__ = _api.__name__
_api.PhotoExportWorker = PhotoExportWorker
