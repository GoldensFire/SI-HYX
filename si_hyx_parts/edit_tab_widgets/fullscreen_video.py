# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""FullscreenVideo. Public namespace: edit_tab_widgets."""
import edit_tab_widgets as _api


# ─── Полноэкранное окно видео ──────────────────────────────────────────────────
class FullscreenVideo(_api.QWidget):
    """Отдельное полноэкранное окно для видео вкладки «Монтаж».

    Внизу — панель управления как в обычных видеоплеерах: кнопка play/pause,
    текущее/общее время и полоса воспроизведения. Панель и курсор авто-скрываются
    при бездействии и снова появляются при движении мыши. Esc / F / двойной клик —
    выход из полноэкранного режима."""

    def __init__(self, edit_tab):
        super().__init__()
        self.edit = edit_tab
        self.setWindowTitle("SI-HYX — Полный экран")
        self.setStyleSheet("background:#000;")
        self.setMouseTracking(True)
        self.setFocusPolicy(_api.Qt.FocusPolicy.StrongFocus)

        # Видео занимает всё окно; панель управления накладывается поверх снизу.
        # Субтитры рисует общий оверлей EditTab (отдельное окно), он подгоняется
        # под видео этого окна — см. EditTab._position_overlay.
        self._video = None

        # ── Панель управления ────────────────────────────────────────────
        # ВАЖНО: QVideoWidget рисует видео через нативную поверхность и
        # перекрывает обычные дочерние виджеты (та же причина, по которой не было
        # видно субтитров). Поэтому панель — отдельное БЕЗРАМОЧНОЕ окно «поверх
        # всех», но КЛИКАБЕЛЬНОЕ (кнопки/полоса), привязанное к этому окну.
        self.bar = _api.QFrame(self, _api.Qt.WindowType.FramelessWindowHint
                          | _api.Qt.WindowType.Tool
                          | _api.Qt.WindowType.WindowStaysOnTopHint)
        self.bar.setAttribute(_api.Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.bar.setFocusPolicy(_api.Qt.FocusPolicy.StrongFocus)
        self.bar.setObjectName("FsBar")
        self.bar.setStyleSheet(
            "#FsBar { background: #0f0f12; border-top: 1px solid #27272a; }"
            # Та же тёмная подсказка, что и во вкладке (см. EditTab.apply_theme) —
            # чтобы штатные tooltip'ы кнопок панели выглядели одинаково.
            f"QToolTip {{ background: {_api.C['surface3']}; color: {_api.C['text']}; "
            f"border: 1px solid {_api.C['border2']}; border-radius: 4px; "
            f"padding: 4px 8px; font-size: 12px; }}")
        # Подсказки кнопок панели — СВОИМ лейблом, ребёнком self.bar, а НЕ
        # штатным QToolTip.showText: тот рисует ОТДЕЛЬНОЕ нативное окно
        # (popup), и на некоторых системах/раскладках экранов оно упорно
        # оказывалось «за пределами экрана» (или под fullscreen-видео),
        # НЕЗАВИСИМО от того, какую позицию мы ему передавали. Дочерний
        # QLabel гарантированно живёт в ТОМ ЖЕ окне, что и сама панель
        # (а она уже точно видна) — так надёжнее. См. eventFilter/_show_fs_tip.
        self._tip = _api.QLabel(self.bar)
        self._tip.setAttribute(_api.Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._tip.setStyleSheet(
            f"background: {_api.C['surface3']}; color: {_api.C['text']}; "
            f"border: 1px solid {_api.C['border2']}; border-radius: 4px; "
            f"padding: 4px 8px; font-size: 12px;")
        self._tip.hide()
        bl = _api.QVBoxLayout(self.bar)
        bl.setContentsMargins(22, 10, 22, 12)
        bl.setSpacing(8)

        # Полоса воспроизведения + тайминги в одной строке (клик по полосе —
        # мгновенная перемотка; SeekSlider это уже умеет).
        seek_row = _api.QHBoxLayout()
        seek_row.setContentsMargins(0, 0, 0, 0)
        seek_row.setSpacing(12)
        _mono = _api.QFont("Courier New" if _api.os.name == 'nt' else "Courier")
        _mono.setBold(True); _mono.setPointSize(12)
        self.lbl_cur = _api.QLabel("00:00:00.000", self.bar)
        self.lbl_cur.setFont(_mono)
        self.lbl_cur.setStyleSheet("color:#a6e3a1; background:transparent;")
        seek_row.addWidget(self.lbl_cur)
        self.slider = _api.SeekSlider(_api.Qt.Orientation.Horizontal, self.bar)
        self.slider.setRange(0, 1000)
        self.slider.setStyleSheet(self._fs_slider_style())
        # Полоса не должна перехватывать фокус — иначе Пробел уходит ей, а не окну.
        self.slider.setFocusPolicy(_api.Qt.FocusPolicy.NoFocus)
        self.slider.sliderMoved.connect(self._on_slider_moved)
        # Тот же контроллер превью кадров, что и у полосы в окне.
        try:
            pv = getattr(self.edit, "seek_preview", None)
            if pv is not None:
                self.slider.attach_preview(pv)
        except Exception:
            pass
        seek_row.addWidget(self.slider, 1)
        self.lbl_tot = _api.QLabel("00:00:00.000", self.bar)
        self.lbl_tot.setFont(_mono)
        self.lbl_tot.setStyleSheet("color:#bac2de; background:transparent;")
        seek_row.addWidget(self.lbl_tot)
        bl.addLayout(seek_row)

        row = _api.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        _fsbtn_css = (
            f"QPushButton {{ background: {_api.C['surface3']}; border: none;"
            " border-radius: 7px; } "
            f"QPushButton:hover {{ background: {_api.C['border']}; }} "
            f"QPushButton:pressed {{ background: {_api.C['border2']}; }}")
        _fsbtn_accent_css = (
            f"QPushButton {{ background: {_api.C['accent']}; border: none;"
            " border-radius: 7px; } "
            f"QPushButton:hover {{ background: {_api.C['accent2']}; }} "
            f"QPushButton:pressed {{ background: {_api.C['accent']}; }}")

        def _fsbtn(icon_std, tip, slot, size=(42, 34), accent=False, icon=None):
            b = _api.QPushButton(self.bar)
            b.setIcon(icon if icon is not None
                      else self.style().standardIcon(icon_std))
            b.setIconSize(_api.QSize(18, 18))
            b.setFixedSize(*size)
            b.setCursor(_api.Qt.CursorShape.PointingHandCursor)
            # Подсказка — ШТАТНЫМ механизмом Qt (setToolTip), ровно как у кнопки
            # «Сохранить кадр» на боковой панели. Раньше здесь была самописная
            # подсказка через QToolTip.showText на Enter/Leave (см. eventFilter):
            # она МЕРЦАЛА (повторные show/hide при каждом входе курсора) и рисовала
            # инородную рамку. НЕ ВОЗВРАЩАТЬ — стиль подсказки задаётся через
            # QToolTip в self.bar.setStyleSheet (тёмная тема, как во вкладке).
            b.setToolTip(tip)
            b.setStyleSheet(_fsbtn_accent_css if accent else _fsbtn_css)
            # Кнопки не держат фокус: после клика по «Стоп» Пробел должен идти
            # окну (воспроизведение/пауза), а не повторно жать ту же кнопку.
            b.setFocusPolicy(_api.Qt.FocusPolicy.NoFocus)
            b.clicked.connect(slot)
            # Панель (self.bar) — отдельное топ-левел окно у самого низа экрана,
            # чей QScreen иногда остаётся привязан к чужому монитору (см.
            # _relayout) — штатный клэмп QToolTip тогда считает границы не того
            # экрана, и подсказка рисуется «за пределами экрана» (невидимой).
            # Перехватываем QEvent.ToolTip (единичное событие показа, НЕ
            # Enter/Leave — значит, без мерцания) и сами ставим позицию рядом
            # с РЕАЛЬНЫМ экраном под курсором — см. eventFilter.
            b.installEventFilter(self)
            row.addWidget(b)
            return b

        self.btn_stop = _fsbtn(_api.QStyle.StandardPixmap.SP_MediaStop,
                               "Стоп — к началу зоны", self.edit.stop_playback)
        self.btn_step_back = _fsbtn(_api.QStyle.StandardPixmap.SP_MediaSeekBackward,
                                    "Кадр назад (←)",
                                    _api.partial(self.edit.step_frame_scrub, -1))
        self.btn_play = _fsbtn(_api.QStyle.StandardPixmap.SP_MediaPlay,
                               "Воспроизвести / пауза (Пробел)",
                               self.edit.toggle_play, size=(50, 34), accent=True)
        self.btn_step_fwd = _fsbtn(_api.QStyle.StandardPixmap.SP_MediaSeekForward,
                                   "Кадр вперёд (→)",
                                   _api.partial(self.edit.step_frame_scrub, 1))
        self.btn_jump_end = _fsbtn(_api.QStyle.StandardPixmap.SP_MediaSkipForward,
                                   "Перейти к концу зоны (OUT)",
                                   lambda: self.edit.seek_to(self.edit.current_out))

        row.addSpacing(10)
        self.btn_save_frame = _fsbtn(None,
                                     "Сохранить текущий кадр в PNG",
                                     self.edit.save_frame,
                                     icon=_api.get_icon('fa5s.save', color='#ffffff'))

        row.addStretch(1)

        # Громкость — связана с основным ползунком вкладки (он управляет звуком).
        self.vol_lbl = _api.VolumeLabel(lambda: getattr(self, "vol_slider", None), self.bar)
        self.vol_lbl.setStyleSheet("color:#cdd6f4; font-size:15px; background:transparent;")
        # Mute/unmute — общий с вкладкой (он же вернёт прежний уровень и сюда:
        # _on_volume_changed вкладки синхронизирует этот ползунок, см. sync_volume).
        self.vol_lbl.clicked.connect(self.edit.toggle_mute)
        row.addWidget(self.vol_lbl)
        self.vol_slider = _api.VolumeSlider(_api.Qt.Orientation.Horizontal, self.bar)
        self.vol_slider.setRange(0, 100)
        self.vol_slider.setValue(int(self.edit.vol_slider.value()))
        self.vol_slider.setFixedWidth(120)
        # Прозрачный жёлоб (а не тёмный surface3) и белый бегунок без чёрной
        # окантовки — чтобы за ползунком громкости не было чёрного прямоугольника.
        self.vol_slider.setStyleSheet(
            "QSlider { background: transparent; }"
            "QSlider::groove:horizontal { background: rgba(255,255,255,0.22);"
            " height: 6px; border-radius: 3px; }"
            "QSlider::sub-page:horizontal { background: #cdd6f4; border-radius: 3px; }"
            "QSlider::add-page:horizontal { background: rgba(255,255,255,0.22);"
            " border-radius: 3px; }"
            "QSlider::handle:horizontal { background: #ffffff; width: 13px;"
            " height: 13px; margin: -4px 0; border-radius: 7px; }")
        self.vol_slider.setFocusPolicy(_api.Qt.FocusPolicy.NoFocus)
        self.vol_slider.valueChanged.connect(self._on_volume_changed)
        row.addWidget(self.vol_slider)

        row.addSpacing(10)
        self.btn_exit = _fsbtn(_api.QStyle.StandardPixmap.SP_TitleBarNormalButton,
                               "Выйти из полноэкранного режима (Esc)",
                               self.edit.exit_fullscreen,
                               icon=_api._fullscreen_icon(expand=False))

        bl.addLayout(row)

        # Авто-скрытие панели/курсора при бездействии.
        self._hide_timer = _api.QTimer(self)
        self._hide_timer.setInterval(2500)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._hide_bar)
        # Панель — отдельное окно, поэтому ей тоже нужен общий набор сочетаний.
        self.edit.register_shortcuts(self)
        self.edit.register_shortcuts(self.bar)
        self.bar.installEventFilter(self)

    @staticmethod
    def _fs_slider_style():
        """Полоса воспроизведения для полноэкранного режима: высокий жёлоб с
        закруглёнными концами, видимая заполненная часть и заметный бегунок."""
        ph = _api.C["playhead"]
        return f"""
            QSlider {{ min-height: 18px; background: transparent; }}
            QSlider::groove:horizontal {{
                background: rgba(255,255,255,0.22);
                border-radius: 4px;
                height: 8px;
            }}
            QSlider::sub-page:horizontal {{
                background: {ph};
                border-radius: 4px;
            }}
            QSlider::add-page:horizontal {{
                background: rgba(255,255,255,0.22);
                border-radius: 4px;
            }}
            QSlider::handle:horizontal {{
                background: #ffffff;
                border: 2px solid {ph};
                width: 16px; height: 16px;
                margin: -5px 0;
                border-radius: 9px;
            }}
            QSlider::handle:horizontal:hover {{ background: {ph}; }}
        """

    # ── Видео ──────────────────────────────────────────────────────────────
    def attach_video(self, video_widget):
        self._video = video_widget
        video_widget.setParent(self)
        video_widget.show()
        self._relayout()
        self._show_bar()

    def _relayout(self):
        if self._video is not None:
            self._video.setGeometry(0, 0, self.width(), self.height())
        # Субтитры рисует общий оверлей EditTab — переподгоняем под это окно.
        try:
            self.edit._position_overlay()
        except Exception:
            pass
        # Панель — отдельное окно: позиционируем в ГЛОБАЛЬНЫХ координатах внизу.
        bar_h = max(64, self.bar.sizeHint().height())
        tl = self.mapToGlobal(_api.QPoint(0, self.height() - bar_h))
        self.bar.setGeometry(tl.x(), tl.y(), self.width(), bar_h)
        if self.bar.isVisible():
            self.bar.raise_()   # поверх оверлея субтитров
        # self.bar — WindowType.Tool получает нативный
        # хэндл сразу при создании (до первого setGeometry), поэтому его QScreen
        # застревает на том экране, где он появился на свет (обычно первичный
        # монитор) — даже когда полноэкранное окно реально открыто на ДРУГОМ
        # мониторе. Из-за этого стандартный hover-tooltip кнопок панели считает
        # границы экрана по чужому монитору и получается «за пределами экрана».
        # Перепривязываем окно панели к экрану, где она физически оказалась.
        try:
            scr = _api.QApplication.screenAt(tl)
            wh = self.bar.windowHandle()
            if scr is not None and wh is not None and wh.screen() is not scr:
                wh.setScreen(scr)
        except Exception:
            pass

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._relayout()

    # ── Синхронизация со плеером ─────────────────────────────────────────────
    def sync_from_player(self):
        e = self.edit
        dur = e.duration or 0.0
        pos_s = e.player.position() / 1000.0
        self.lbl_cur.setText(_api.s_to_time(pos_s))
        self.lbl_tot.setText(_api.s_to_time(dur))
        if dur > 0 and not self.slider.is_user_seeking():
            # Плеер авто-паузится за кадр до конца, поэтому у самого конца
            # «дотягиваем» полосу до 100%, чтобы она доходила до края.
            frac = 1.0 if pos_s >= (dur - 0.08) else (pos_s / dur)
            self.slider.blockSignals(True)
            self.slider.setValue(int(frac * 1000))
            self.slider.blockSignals(False)

    def update_play_icon(self, playing):
        ic = _api.QStyle.StandardPixmap.SP_MediaPause if playing else _api.QStyle.StandardPixmap.SP_MediaPlay
        self.btn_play.setIcon(self.style().standardIcon(ic))

    def _on_slider_moved(self, value):
        dur = self.edit.duration or 0.0
        if dur > 0:
            self.edit.seek_to((value / 1000.0) * dur)
        self._show_bar()

    def _on_volume_changed(self, v):
        # Звуком управляет основной ползунок вкладки — отражаем туда значение
        # (он применит его к audio_output и обновит свой значок).
        try:
            self.edit.vol_slider.setValue(int(v))
        except Exception:
            pass
        try:
            self.vol_lbl.update_glyph(int(v))
        except Exception:
            pass
        self._show_bar()

    def sync_volume(self):
        """Подтягивает текущую громкость из основного ползунка вкладки."""
        try:
            v = int(self.edit.vol_slider.value())
            self.vol_slider.blockSignals(True)
            self.vol_slider.setValue(v)
            self.vol_slider.blockSignals(False)
            self.vol_lbl.update_glyph(v)
        except Exception:
            pass

    # ── Авто-скрытие панели/курсора ──────────────────────────────────────────
    def _show_bar(self):
        self._relayout()
        self.bar.show(); self.bar.raise_()
        self.unsetCursor()
        self._hide_timer.start()

    def _hide_bar(self):
        # Не прячем, пока курсор над самой панелью (пользователь ей пользуется).
        # geometry() панели теперь в глобальных координатах (отдельное окно).
        if self.bar.geometry().contains(self.cursor().pos()):
            self._hide_timer.start()
            return
        self.bar.hide()
        self.setCursor(_api.Qt.CursorShape.BlankCursor)

    def mouseMoveEvent(self, ev):
        self._show_bar()
        super().mouseMoveEvent(ev)

    def mouseDoubleClickEvent(self, ev):
        self.edit.exit_fullscreen()

    def eventFilter(self, obj, ev):
        # Физические клавиши и Esc из активного окна панели перенаправляем сюда.
        if obj is self.bar and ev.type() == _api.QEvent.Type.KeyPress:
            self.keyPressEvent(ev)
            if ev.isAccepted():
                return True
        # Подсказки кнопок панели — СВОИМ лейблом (self._tip, дочерний виджет
        # self.bar), см. _show_fs_tip. Штатный QToolTip.showText здесь себя не
        # оправдал: это ОТДЕЛЬНОЕ нативное popup-окно, и подобранная позиция
        # всё равно не помогала — подсказка стабильно оказывалась невидимой
        # (за экраном / под fullscreen-видео). Дочерний QLabel гарантированно
        # рисуется в ТОМ ЖЕ окне, что и сама панель, а она уже точно видна.
        # QEvent.ToolTip — штатное ОДНОКРАТНОЕ событие показа (не Enter/Leave,
        # то мерцало раньше); Leave только прячет лейбл, показ им не управляет.
        if (ev.type() == _api.QEvent.Type.ToolTip and isinstance(obj, _api.QPushButton)
                and obj.toolTip()):
            self._show_fs_tip(obj, obj.toolTip())
            return True
        if ev.type() == _api.QEvent.Type.Leave and isinstance(obj, _api.QPushButton):
            self._tip.hide()
            return super().eventFilter(obj, ev)
        return super().eventFilter(obj, ev)

    def _show_fs_tip(self, btn, text):
        self._tip.setText(text)
        self._tip.adjustSize()
        x = btn.x() + (btn.width() - self._tip.width()) // 2
        x = max(4, min(x, self.bar.width() - self._tip.width() - 4))
        y = btn.y() - self._tip.height() - 8
        self._tip.move(x, max(0, y))
        self._tip.show()
        self._tip.raise_()

    def keyPressEvent(self, ev):
        if ev.key() == _api.Qt.Key.Key_Escape:
            self.edit.exit_fullscreen()
            ev.accept()
        else:
            # WASD/F/I/O и Ctrl+буква учитывают раскладку и модификаторы
            # ровно так же, как в обычном режиме вкладки.
            self.edit.keyPressEvent(ev)

    def closeEvent(self, ev):
        # Панель — отдельное окно: прячем явно, чтобы не зависла на экране.
        try: self.bar.hide()
        except Exception: pass
        # Если окно закрыли системно (Alt+F4) — аккуратно вернём видео обратно.
        if getattr(self.edit, "_fs_window", None) is self:
            self.edit.exit_fullscreen()
        super().closeEvent(ev)

FullscreenVideo.__module__ = _api.__name__
_api.FullscreenVideo = FullscreenVideo
