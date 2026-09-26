# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""EditTab: _build_timeline_panel. Public namespace: edit_tab."""
import edit_tab as _api


def _build_timeline_panel(self, center, root, sidebar):
    """Нижняя панель таймлайна (волна, субтитры) и финальная сборка вкладки."""
    # ── Timeline panel ────────────────────────────────────────────────
    # Высота полосы таймлайна фиксирована и совпадает с нижним блоком правой
    # панели («Итог» + «Обрезать»), чтобы они визуально были одной строкой.
    # Панель ужата почти до высоты самой визуализации (волна + скроллбар +
    # небольшие отступы сверху/снизу) — остальное место отдаётся видео.
    BAND_H = 116
    timeline_panel = _api.QFrame()
    timeline_panel.setObjectName("TimelinePanel")
    timeline_panel.setFixedHeight(BAND_H)
    timeline_panel.setStyleSheet(f"#TimelinePanel {{ background: {_api.C['surface']}; border-top: 1px solid {_api.C['border']}; }}")
    tp_layout = _api.QVBoxLayout(timeline_panel)
    tp_layout.setContentsMargins(12, 6, 12, 6)
    tp_layout.setSpacing(3)

    # Горизонтальная прокрутка волны — над виджетом визуализации аудио.
    # Видна только когда волна увеличена (zoom>1) и есть что прокручивать;
    # двигает «окно обзора» (view_offset) по таймлайну.
    self.wave_scroll = _api.QScrollBar(_api.Qt.Orientation.Horizontal)
    self.wave_scroll.setObjectName("WaveScroll")
    self.wave_scroll.setRange(0, 0)
    self.wave_scroll.valueChanged.connect(self.on_wave_scroll)
    self.wave_scroll.setVisible(False)
    self.wave_scroll.setStyleSheet(f"""
            QScrollBar:horizontal {{
                background: {_api.C['surface2']};
                height: 12px;
                border-radius: 6px;
                margin: 0;
            }}
            QScrollBar::handle:horizontal {{
                background: {_api.C['border2']};
                border-radius: 5px;
                min-width: 28px;
            }}
            QScrollBar::handle:horizontal:hover {{ background: {_api.C['accent']}; }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}
        """)
    tp_layout.addWidget(self.wave_scroll)

    # Waveform — невысокая полоса (амплитуда у обычного звука небольшая, при
    # большой высоте сверху/снизу остаётся пустота). Ограничиваем высоту и
    # оставляем небольшой отступ снизу (margin tp_layout).
    self.waveform = _api.WaveformWidget()
    self.waveform.setMinimumHeight(54)
    self.waveform.setMaximumHeight(104)
    self.waveform.seekRequested.connect(self.on_wave_seek)
    self.waveform.playSeekRequested.connect(self.on_wave_playseek)
    # ВНИМАНИЕ: inSetRequested/outSetRequested НЕ подключаем — selectionChanged
    # уже синхронизирует state/поля/кадры (иначе двойной вызов, баг #10).
    self.waveform.selectionChanged.connect(self.on_wave_selection_changed)
    self.waveform.viewChanged.connect(self.on_wave_view_changed)
    self.waveform.interactionStarted.connect(self.push_undo)
    # ПКМ по аудио-визуализации → меню обрезки старт/конец до плейхеда.
    self.waveform.setContextMenuPolicy(_api.Qt.ContextMenuPolicy.CustomContextMenu)
    self.waveform.customContextMenuRequested.connect(self._trim_ctx_menu)
    tp_layout.addWidget(self.waveform, stretch=1)

    # Строка «ПРОКРУТКА» убрана по запросу. pan_slider оставлен как скрытый
    # объект (без родителя, никогда не показывается) — чтобы существующий код
    # update_pan_slider_values не падал; pan_row_w намеренно НЕ создаём
    # (getattr → None → строка панорамирования не отображается).
    self.pan_slider = _api.QSlider(_api.Qt.Orientation.Horizontal)
    self.pan_slider.setRange(0, 1000)
    self.pan_slider.setEnabled(False)
    self.pan_slider.sliderMoved.connect(self.on_pan_moved)

    # Полоса воспроизведения (self.slider) перенесена в player_bar под видео.

    # Таймлайн фиксированной (небольшой) высоты — лишнее место отдаётся видео
    # (video_row = stretch 1). Нижние панели (IN/OUT) тоже stretch=0, поэтому
    # на маленьком окне ужимается именно видео, а не интерфейс под ним.
    center.addWidget(timeline_panel, stretch=0)

    # (IN/OUT перенесены на строку с кнопками плеера в player_bar; отдельной
    #  панели IN/OUT больше нет. Панель управления плеером — в player_bar под
    #  видео; «Итог» и «Обрезать» — в правой панели.)

    root.addLayout(center, stretch=1)
    root.addWidget(sidebar)

# ── Style helpers ──────────────────────────────────────────────────────
def _slider_style(self, color, compact=False):
    h = "4px" if compact else "5px"
    return f"""
            QSlider::groove:horizontal {{
                background: {_api.C['surface3']};
                border-radius: 3px;
                height: {h};
            }}
            QSlider::handle:horizontal {{
                background: {color};
                border: 2px solid {_api.C['bg']};
                width: 13px; height: 13px;
                margin: -4px 0;
                border-radius: 7px;
            }}
            QSlider::sub-page:horizontal {{
                background: {color};
                border-radius: 3px;
            }}
        """

def apply_theme(self):
    # Тёмная тема редактора применяется к этому виджету и его потомкам,
    # переопределяя общий стиль приложения только в пределах вкладки.
    self.setStyleSheet(f"""
            QWidget {{
                background: {_api.C['bg']};
                color: {_api.C['text']};
                font-family: 'Segoe UI', 'SF Pro Display', 'Helvetica Neue', Arial, sans-serif;
                font-size: 13px;
            }}
            QToolTip {{
                background: {_api.C['surface3']};
                color: {_api.C['text']};
                border: 1px solid {_api.C['border2']};
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 12px;
            }}
            QLabel {{ background: transparent; }}
            QMessageBox {{ background: {_api.C['surface']}; }}
            QFileDialog {{ background: {_api.C['surface']}; }}
        """)

def _install_wheel_scroll(self, widget):
    """Заставляет виджет (комбобокс и т.п.) НЕ менять значение на колесо
        мыши, а прокручивать ближайшую QScrollArea-родителя — так колесо над
        полем прокручивает панель, как и над пустым местом."""
    def handler(event, _w=widget):
        sa = _w.parent()
        while sa is not None and not isinstance(sa, _api.QScrollArea):
            sa = sa.parent()
        if isinstance(sa, _api.QScrollArea):
            _api.QApplication.sendEvent(sa.viewport(), event)
        else:
            event.ignore()
    widget.wheelEvent = handler

def _on_cut_progress(self, p):
    self._cut_lastp = float(p)
    self._report_cut(self._cut_lastp)

def _report_cut(self, p):
    """Строка прогресса обрезки с ETA. Пока ffmpeg не дал реального прогресса
        (p<1 — фаза подготовки/перемотки), показываем счётчик «прошло», чтобы не
        выглядело зависшим. Дублируем статус в крупную метку над кнопкой
        «Обрезать» (lbl_selection) — нижняя полоса окна легко теряется, а здесь
        пользователь смотрит прямо на кнопку (см. _set_cut_status)."""
    try:
        elapsed = _api.time.time() - getattr(self, "_cut_t0", _api.time.time())
        if p >= 1.0:
            eta = max(0.0, elapsed * (100.0 - p) / p)
            txt = f"Обрезка… {int(p)}%  •  ETA {self._fmt_mmss(eta)}"
            self._report_progress(int(p), txt)
            self._set_cut_status(f"Обрезка… {int(p)}%  •  ETA {self._fmt_mmss(eta)}",
                                 icon='fa5s.cut')
        else:
            # Фаза подготовки: при обрезке с перекодированием ffmpeg сначала
            # перематывает декодер до точки реза (выходной seek) и ещё не даёт
            # ни одного out_time — реального процента нет. Включаем пульсирующий
            # («busy») режим полосы, чтобы она не выглядела зависшей на 0%.
            txt = f"Обрезка… подготовка ({self._fmt_mmss(elapsed)})"
            self._report_progress(-1, txt)
            self._set_cut_status(f"Обрезка… подготовка {self._fmt_mmss(elapsed)}",
                                 icon='fa5s.hourglass-half')
    except Exception:
        pass

def _set_cut_status(self, text, icon='fa5s.cut'):
    """Показывает текст прогресса обрезки в крупной метке над кнопкой
        «Обрезать» (вместо «Итог: …»). Видно прямо на месте действия, в отличие
        от полосы внизу окна. Снимается через _clear_cut_status → восстанавливает
        обычный «Итог: …»."""
    lbl = getattr(self, "lbl_selection", None)
    if lbl is None:
        return
    try:
        lbl.setText(f"{_api.icon_html(icon, 13, _api.C['accent'])}  {text}")
    except Exception:
        pass

def _clear_cut_status(self):
    """Возвращает метку над кнопкой к обычному виду «Итог: …» после обрезки."""
    try:
        self.update_selection_label()
    except Exception:
        pass

@staticmethod
def _make_temp_out(final_out, suffix=None):
    """Создаёт временный файл для результата РЯДОМ с финальным путём, а не в
        системном %TEMP%. Две причины: (1) os.replace не умеет переносить файл
        между дисками (WinError 17 «cannot move the file to a different disk
        drive»), а сохранять на D:\\ при temp на C:\\ — обычный сценарий;
        (2) не гоняем гигабайты между дисками. Если каталог назначения недоступен
        на запись — откатываемся в системный temp (перенос вытянет _move_tolerant).
        Возвращает путь к пустому файлу."""
    if suffix is None:
        suffix = _api.Path(final_out).suffix
    out_dir = _api.os.path.dirname(_api.os.path.abspath(final_out))
    try:
        tf = _api.tempfile.NamedTemporaryFile(delete=False, suffix=suffix,
                                         prefix=".sihyx_tmp_", dir=out_dir)
        tf.close()
        return tf.name
    except OSError:
        tf = _api.tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        tf.close()
        return tf.name

@staticmethod
def _move_tolerant(temp, final):
    """os.replace, но с откатом на копирование, если temp и final лежат на
        РАЗНЫХ дисках: os.replace тогда падает с WinError 17 / EXDEV. shutil.move
        в этом случае копирует и удаляет источник. Все прочие ошибки (в т.ч.
        WinError 32 «занят») пробрасываются наверх — их разбирает
        _replace_tolerant."""
    try:
        _api.os.replace(temp, final)
    except OSError as e:
        cross = (getattr(e, "winerror", None) == 17
                 or e.errno == getattr(_api.errno, "EXDEV", 18))
        if not cross:
            raise
        # Цель может уже существовать — shutil.move на непустой файл ругается,
        # поэтому убираем её сами (занятую цель отловит WinError 32 выше).
        if _api.os.path.exists(final):
            _api.os.remove(final)
        _api.shutil.move(temp, final)
    return final

@staticmethod
def _replace_tolerant(temp, final):
    """Переносит temp → final атомарным os.replace. Если файл назначения занят
        ДРУГИМ процессом (например, его прямо сейчас читает вкладка «Обработка»,
        перекодируя только что сделанную обрезку) — Windows возвращает
        WinError 32 и os.replace падает. Раньше это роняло всю обрезку с ошибкой
        «не может получить доступ к файлу». Теперь в таком случае сохраняем
        готовый результат под соседним свободным именем (foo_обрез_1.mkv, _2…),
        а не теряем работу. Перенос между дисками (temp в %TEMP% на C:, результат
        на D:) идёт копированием — см. _move_tolerant. Возвращает фактический путь
        сохранения."""
    candidate = final
    last_err = None
    for _ in range(128):
        try:
            return _api.EditTab._move_tolerant(temp, candidate)
        except OSError as e:
            # WinError 32 (sharing violation) приходит как PermissionError или
            # OSError с winerror==32 — цель занята, пробуем соседнее имя.
            busy = isinstance(e, PermissionError) or getattr(e, "winerror", None) == 32
            if not busy:
                raise
            last_err = e
            candidate = _api._unique_output(candidate)
    # Крайне маловероятно (128 занятых имён подряд) — пробрасываем ошибку.
    if last_err:
        raise last_err
    return candidate
