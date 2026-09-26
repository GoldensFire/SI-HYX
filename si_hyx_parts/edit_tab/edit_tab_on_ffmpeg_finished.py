# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""EditTab: on_ffmpeg_finished. Public namespace: edit_tab."""
import edit_tab as _api


def on_ffmpeg_finished(self, success, message):
    if success:
        result_path = str(getattr(self, "_progress_result_path", "") or "")
        if (result_path and self.main is not None
                and hasattr(self.main, "set_global_result")):
            self.main.set_global_result(result_path)
        self._progress_result_path = ""
        self.log_label.setText(_api.icon_html('fa5s.check', 12, _api.C['green2']) + " Готово")
        self.log_label.setStyleSheet(f"color: {_api.C['green2']}; font-size: 12px; font-weight: 600;")
        self._report_progress(100, "Готово")
        # Кратко показываем «Готово» над кнопкой, затем возвращаем «Итог: …».
        self._set_cut_status("Готово", icon='fa5s.check')
        _api.QTimer.singleShot(1800, self._clear_cut_status)
        # Сразу обновляем верхнюю ленту файлов: если результат перезаписал файл
        # по тому же пути (напр. «…_обрез.mp4» переэкспортирован перекодировкой
        # и стал короче/легче), карточка иначе висела бы со старым превью.
        try:
            strip = getattr(self.main, "recent_strip", None)
            if strip is not None:
                strip.force_refresh()
        except Exception:
            pass
    elif message == "Отменено":
        self.log_label.setText("Отменено")
        self.log_label.setStyleSheet(f"color: {_api.C['text2']}; font-size: 12px;")
        self._report_progress(0, "Отменено")
        self._clear_cut_status()
    else:
        self.log_label.setText(_api.icon_html('fa5s.times', 12, _api.C['red2']) + " Ошибка")
        self.log_label.setStyleSheet(f"color: {_api.C['red2']}; font-size: 12px; font-weight: 600;")
        try:
            from error_report import ErrorReportDialog
            ErrorReportDialog(
                "Ошибка", "Обрезка завершилась с ошибкой.",
                detail=str(message), where="Монтаж: обрезка", parent=self).exec()
        except Exception:
            _api.msgbox_critical(self, "Ошибка", f"Обрезка завершилась с ошибкой:\n{message}")
        self._report_progress(0, "Ошибка")
        self._clear_cut_status()

@staticmethod
def _escape_filter_path(p):
    """Экранирует путь для libavfilter (subtitles/fontsdir): прямые слэши +
        экранированное двоеточие диска (`C\\:`) + экранированная кавычка. Без
        экранирования двоеточия на Windows фильтр не инициализируется."""
    return str(p).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")

def _extract_subtitle_fonts(self, src):
    """Извлекает вложенные шрифты (font attachments) контейнера во временную
        папку, чтобы при вшивании субтитров libass рендерил их РОДНЫМИ шрифтами
        (полная поддержка ASS-стилей). Возвращает путь к папке или None.

        Результат кешируется по (путь, mtime, размер) — повторный экспорт того же
        источника не гоняет ffmpeg заново. Папка живёт до закрытия вкладки
        (см. shutdown()), а не удаляется сразу после экспорта, как раньше."""
    stamp = self._file_cache_stamp(src)
    cache_key = (str(src), stamp) if stamp else None
    if cache_key is not None:
        cached = self._subtitle_fonts_cache.get(cache_key)
        if cached is not None and _api.os.path.isdir(cached):
            return cached
    try:
        d = _api.tempfile.mkdtemp(prefix="sihyx_fonts_")
        # -dump_attachment:t "" выгружает все attachments в текущую папку.
        # ffmpeg при этом завершается с ненулевым кодом (нет выходного файла) —
        # это ожидаемо, нас интересуют только извлечённые файлы.
        _api.subprocess.run([_api.FFMPEG, "-y", "-dump_attachment:t", "", "-i", str(src)],
                       cwd=d, capture_output=True, creationflags=_api.CREATE_NO_WINDOW)
        if _api.os.listdir(d):
            if cache_key is not None:
                self._subtitle_fonts_cache[cache_key] = d
                if len(self._subtitle_fonts_cache) > 8:
                    old_key = next(iter(self._subtitle_fonts_cache))
                    old_dir = self._subtitle_fonts_cache.pop(old_key)
                    try:
                        import shutil
                        shutil.rmtree(old_dir, ignore_errors=True)
                    except Exception:
                        pass
            return d
        _api.os.rmdir(d)
    except Exception:
        pass
    return None

def _discard_temp_cut(self, path, is_loaded):
    """Удаляет неточный файл быстрой обрезки, когда пользователь решил
        переделать его (перекодировкой или Smart Cut). Если файл открыт в плеере —
        сперва освобождаем источник, иначе на Windows он залочен и не удалится.
        Ошибки глушим: переделка обрезки важнее уборки дубля."""
    try:
        if is_loaded:
            try: self.player.stop()
            except Exception: pass
            try: self.player.setSource(_api.QUrl())
            except Exception: pass
        if path and _api.os.path.exists(path):
            _api.os.remove(path)
    except Exception:
        pass

def _show_cut_choice_dialog(self, title, text, buttons):
    """Диалог выбора при неточной обрезке без перекодирования — кнопки
        СВЕРХУ ВНИЗ (а не в ряд, как у стандартного QMessageBox), у каждой
        значок ⓘ с объяснением, что она делает (вариантов до 5 — в ряд не
        помещались и было неясно, чем они отличаются).

        buttons — список (key, label, tip, destructive); первая кнопка — она
        же дефолтная (Enter). Возвращает key нажатой кнопки или None (Esc/крестик)."""
    dlg = _api.QDialog(self)
    dlg.setWindowTitle(title)
    dlg.setMinimumWidth(440)
    lay = _api.QVBoxLayout(dlg)
    lay.setSpacing(14)

    lbl = _api.QLabel(text)
    lbl.setWordWrap(True)
    lbl.setTextInteractionFlags(_api.Qt.TextInteractionFlag.TextSelectableByMouse)
    lay.addWidget(lbl)

    btn_col = _api.QVBoxLayout()
    btn_col.setSpacing(6)
    result = {'key': None}

    def _pick(key):
        result['key'] = key
        dlg.accept()

    for i, (key, label, tip, destructive) in enumerate(buttons):
        row = _api.QHBoxLayout()
        row.setSpacing(6)
        b = _api.QPushButton(label)
        b.setMinimumHeight(34)
        if destructive:
            b.setStyleSheet(f"QPushButton {{ color: {_api.C['red']}; }}")
        if i == 0:
            b.setDefault(True)
            b.setAutoDefault(True)
        b.clicked.connect(lambda _=False, k=key: _pick(k))
        row.addWidget(b, 1)
        row.addWidget(_api.info_badge(tip))
        btn_col.addLayout(row)
    lay.addLayout(btn_col)

    dlg.exec()
    return result['key']

def _notify_cut_accuracy(self, final_path, requested_dur, exact_copy, burn_subs,
                         in_s=None, out_s=None, src=None):
    """Сообщает, удалось ли обрезать БЕЗ перекодировки точно по кадрам.

        В режиме «Быстро (копирование потоков)» начало прилипает к ближайшему
        ключевому кадру, поэтому итоговая длительность может оказаться больше
        запрошенной. Сравниваем фактическую длительность результата с заданной.

        Возвращает строку с выбором пользователя:
          'encode'   — перекодировать диапазон заново (точно, с потерями);
          'smartcut' — умная обрезка (точные границы + lossless-середина);
          'delete'   — удалить созданный неточный файл;
          None       — оставить файл как есть."""
    try:
        if burn_subs:
            _api.msgbox_information(
                self, "Готово",
                "Субтитры вшиты в видео (с перекодировкой).")
            return None
        if not exact_copy:
            # Режимы перекодировки/MP3 — всегда кадрово-точные, отдельное
            # уведомление не нужно.
            return None
        meta = _api.run_ffprobe(final_path)
        actual = 0.0
        try:
            actual = float((meta or {}).get('format', {}).get('duration', 0.0))
        except Exception:
            actual = 0.0
        # У аудиофайла кадров нет — точность меряем/формулируем по времени.
        audio_only = (self.video_stream_index is None)
        # Допуск ~1 кадр (или 0.05 c, если FPS неизвестен / это аудио).
        tol = (1.5 / self.fps) if (self.fps and self.fps > 0
                                   and not audio_only) else 0.05
        diff = abs(actual - requested_dur) if actual > 0 else 0.0
        if actual <= 0 or diff <= tol:
            _api.msgbox_information(
                self, "Готово — точная обрезка",
                "Обрезано без перекодировки, точно по заданным меткам времени."
                if audio_only else
                "Обрезано без перекодировки, точно по заданным кадрам.")
            return None
        keep_btn = ("keep", "Оставить как есть",
                    "Оставить уже готовый файл с небольшим расхождением от "
                    "заданных меток времени — обрезка быстрая и без потери "
                    "качества.", False)
        del_btn = ("delete", "Удалить файл",
                   "Удалить с диска уже созданный неточный файл — если "
                   "результат не нужен.", True)
        if audio_only:
            # Для аудио Smart Cut неприменим (он про ключевые кадры видео).
            # Предлагаем только перекодировку, удаление или «оставить как есть».
            text = (
                "Быстрая обрезка (копирование) НЕ попала точно по времени: "
                "начало сдвинулось к ближайшей границе аудиокадра.\n\n"
                f"Запрошено: {_api.s_to_time(requested_dur)}\n"
                f"Получилось: {_api.s_to_time(actual)}\n"
                f"Расхождение: {_api.s_to_time(diff)}\n\n"
                "Что сделать с фрагментом?")
            buttons = [keep_btn]
            if in_s is not None and out_s is not None:
                buttons.append(("encode", "Перекодировать (точно)",
                                "Вырезать фрагмент заново с перекодировкой — точно "
                                "по заданному времени, но с потерей качества "
                                "(повторное сжатие аудио).", False))
            buttons.append(del_btn)
            key = self._show_cut_choice_dialog(
                "Не получилось точно без потерь", text, buttons)
            return key if key != "keep" else None
        # Не кадрово-точно → предлагаем варианты: Smart Cut (точно + почти без
        # потерь), полную перекодировку (точно, с потерями), удалить файл или
        # оставить как есть.
        can_retry = (in_s is not None and out_s is not None)
        text = (
            "Обрезка без перекодировки (быстро) НЕ кадрово-точная: начало "
            "сдвинулось к ближайшему ключевому кадру.\n\n"
            f"Запрошено: {_api.s_to_time(requested_dur)}\n"
            f"Получилось: {_api.s_to_time(actual)}\n"
            f"Расхождение: {_api.s_to_time(diff)}\n\n"
            "Что сделать с фрагментом?")
        buttons = []
        if can_retry:
            buttons.append(("smartcut", "Smart Cut (точно, почти без потерь)",
                            "Точно нарезать по заданным меткам: копирует потоки "
                            "везде, где можно, и перекодирует только короткий "
                            "кусочек у точек реза. Почти без потери качества, "
                            "быстрее полной перекодировки.", False))
            buttons.append(("encode", "Перекодировать (точно, с потерями)",
                            "Перекодировать весь вырезанный фрагмент заново — точно "
                            "по заданным меткам времени, но с повторным сжатием "
                            "(заметнее теряется качество).", False))
            # Режет диапазон И сразу применяет «Обработку» (её текущие настройки
            # CRF/скорость/loudnorm/…) ОДНИМ проходом — без промежуточного x264-
            # реэнкода, который иначе перекодировался бы ещё раз при последующем
            # прогоне через «Обработку» (двойное поколение потерь). См.
            # EditTab._execute_cut_and_process.
            if hasattr(self.main, 'tab_media'):
                buttons.append(("process", "Обрезать и обработать",
                                "Точно вырезать диапазон и сразу применить текущие "
                                "настройки вкладки «Обработка» (CRF/скорость/"
                                "громкость) одним проходом — без двойной "
                                "перекодировки.", False))
        if not can_retry:
            buttons.append(keep_btn)   # без смещения меток — дефолт безопасный, не «Удалить»
        buttons.append(del_btn)
        if can_retry:
            buttons.append(keep_btn)
        key = self._show_cut_choice_dialog(
            "Не получилось точно без потерь", text, buttons)
        return key if key != "keep" else None
    except Exception:
        pass
    return None
