# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Монтаж: аргументы кодировщика, обрезка, Smart Cut и завершение экспорта."""
import edit_tab as _api
from si_hyx_parts.edit_tab.tracks import drop_audio


class EditTabExportMixin:
    """Монтаж: аргументы кодировщика, обрезка, Smart Cut и завершение экспорта."""

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

    def _set_cut_btn_cancel(self, cancel_mode, cancel_handler=None):
        """Переключает btn_cut («Обрезать») между обычным видом и «Отмена» на
        время перекодировки/обрезки — тот же приём, что _set_remove_btn_cancel
        для «Удалить объект», но с сохранением исходных текста/иконки/стиля:
        у btn_cut они меняются по режиму («Обрезать» / «Создать видео» для
        картинки), и вернуть нужно РОВНО то, что было до переключения."""
        b = self.btn_cut
        try:
            b.clicked.disconnect()
        except Exception:
            pass
        if cancel_mode:
            self._cut_btn_saved = (b.text(), b.icon(), b.styleSheet())
            b.setText("Отмена")
            b.setIcon(_api.get_icon('fa5s.times', color='#1e1e2e'))
            b.setStyleSheet(f"""
                QPushButton {{
                    background: {_api.C['red']};
                    color: #1e1e2e;
                    border: none;
                    border-radius: 6px;
                    padding: 9px 24px;
                    font-weight: 700;
                    font-size: 13px;
                    letter-spacing: 0.3px;
                }}
                QPushButton:hover {{ background: {_api.C['red2']}; }}
                QPushButton:pressed {{ background: {_api.C['red2']}; }}
                QPushButton:disabled {{ background: {_api.C['surface3']}; color: {_api.C['text3']}; }}
            """)
            b.setEnabled(True)
            b.clicked.connect(cancel_handler or self._cancel_cut)
        else:
            saved = getattr(self, '_cut_btn_saved', None)
            if saved:
                b.setText(saved[0]); b.setIcon(saved[1]); b.setStyleSheet(saved[2])
            b.setEnabled(True)
            b.clicked.connect(self.start_cut)

    def _cancel_cut(self):
        """Отменяет текущую обрезку/перекодировку/Smart Cut (self.ffmpeg_thread)."""
        th = getattr(self, "ffmpeg_thread", None)
        if th is not None and th.isRunning():
            self._set_cut_status("Отмена…", icon='fa5s.hourglass-half')
            self.btn_cut.setEnabled(False)
            th.stop()

    def _cancel_cut_and_process(self, tab_media):
        """Отменяет «Обрезать и обработать» (worker вкладки «Обработка»)."""
        w = getattr(tab_media, 'worker', None)
        if w is not None and w.isRunning():
            self._set_cut_status("Отмена…", icon='fa5s.hourglass-half')
            self.btn_cut.setEnabled(False)
            w.stop()

    # ── Export / Cut ──────────────────────────────────────────────────────
    def _available_encoders(self):
        """Строка `ffmpeg -encoders` (детект один раз, кэшируется). Пустая строка
        трактуется как «всё доступно» (не смогли опросить сборку)."""
        cache = getattr(self, "_encoders_str", None)
        if cache is not None:
            return cache
        encoders = ""
        try:
            p = _api.subprocess.run([_api.FFMPEG, "-hide_banner", "-encoders"],
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace", creationflags=_api.CREATE_NO_WINDOW)
            encoders = p.stdout or ""
        except Exception:
            encoders = ""
        self._encoders_str = encoders
        return encoders

    def _gpu_encoder_args(self, encoders, hardsub=False):
        """Первый доступный аппаратный (GPU) H.264-кодировщик, иначе None.
        При hardsub (вшивание субтитров) поджимаем качество, чтобы края текста
        не мылились."""
        q = 18 if hardsub else 20
        if "h264_nvenc" in encoders:
            return ["-c:v", "h264_nvenc", "-preset", "p5", "-cq", str(q)]
        if "h264_qsv" in encoders:
            return ["-c:v", "h264_qsv", "-global_quality", str(q)]
        if "h264_amf" in encoders:
            return ["-c:v", "h264_amf", "-quality", "balanced", "-rc", "cqp",
                    "-qp_i", str(q), "-qp_p", str(q)]
        if "h264_mf" in encoders:
            qual = 80 if hardsub else 70
            return ["-c:v", "h264_mf", "-rate_control", "quality", "-quality", str(qual)]
        return None

    def _video_encoder_args(self, hardsub=False):
        """Подбирает H.264-кодировщик в bundled ffmpeg с учётом выбора
        пользователя (combo «Кодировщик»): «Видеокарта (GPU)» — аппаратный
        кодек; «Процессор (CPU)» / «Авто» — libx264. Если выбранного варианта в
        сборке нет — мягкий откат (GPU↔CPU↔mpeg4), чтобы перекодировка всегда
        состоялась.

        hardsub=True (вшивание субтитров): берём чуть более качественный профиль —
        у текста резкие края, и на «fast»/высоком CRF они мылятся. CPU: preset
        medium + crf 17; добавляем -pix_fmt yuv420p для чёткого 8-битного вывода и
        совместимости. Аппаратные кодеки тоже поджимаем по качеству."""
        encoders = self._available_encoders()
        # 0 = Авто, 1 = Процессор (CPU), 2 = Видеокарта (GPU)
        try:
            choice = int(self.cmb_encoder.currentIndex())
        except Exception:
            choice = 0

        cpu_args = (["-c:v", "libx264", "-preset", "medium", "-crf", "17"]
                    if hardsub else ["-c:v", "libx264", "-preset", "fast", "-crf", "18"])
        cpu = cpu_args if ("libx264" in encoders or encoders == "") else None
        gpu = self._gpu_encoder_args(encoders, hardsub=hardsub)

        if choice == 2:                      # GPU — с откатом на CPU
            args = gpu or cpu
        elif choice == 1:                    # CPU — с откатом на GPU
            args = cpu or gpu
        else:                                # Авто: CPU (качество/совместимость)
            args = cpu or gpu
        if args is None:
            args = ["-c:v", "mpeg4", "-q:v", "3"]
        args = list(args)
        if hardsub and "-pix_fmt" not in args:
            args += ["-pix_fmt", "yuv420p"]
        return args

    def _subs_present_in_range(self, src, ext_sub, rel_idx, in_s, out_s):
        """True, если хотя бы одно событие субтитров видно в диапазоне [in_s, out_s].

        Через ffprobe читаем тайминги пакетов выбранной дорожки субтитров и
        проверяем пересечение [start, start+duration] с [in_s, out_s]. Если в
        отрезке субтитров нет, вшивать нечего → можно резать без перекодировки.
        При ошибке probe (или неизвестной длительности событий) возвращаем True —
        безопасный путь: вшиваем как обычно, чтобы не потерять субтитры."""
        if ext_sub:
            target, sel = str(ext_sub), "s:0"
        else:
            target, sel = str(src), f"s:{rel_idx}"
        cmd = [_api.FFPROBE, "-v", "error", "-select_streams", sel,
               "-show_entries", "packet=pts_time,duration_time",
               "-of", "csv=p=0", target]
        try:
            r = _api.subprocess.run(cmd, capture_output=True, text=True,
                               encoding="utf-8", errors="replace",
                               creationflags=_api.CREATE_NO_WINDOW, timeout=30)
        except Exception:
            return True
        if r.returncode != 0:
            return True
        for line in r.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split(",")
            try:
                start = float(parts[0])
            except Exception:
                continue
            # Неизвестная длительность (N/A — напр. у битмап-субтитров) → берём
            # запас 10 с, чтобы скорее «оставить вшивание», чем ошибочно пропустить.
            try:
                dur = float(parts[1]) if len(parts) > 1 and parts[1] not in ("", "N/A") else 10.0
            except Exception:
                dur = 10.0
            if (start + dur) >= in_s and start <= out_s:
                return True
        return False

    def start_cut(self):
        if not self.actual_source_file or not self.actual_source_file.exists():
            _api.msgbox_warning(self, "Внимание", "Файл не загружен.")
            return
        # Не запускаем вторую обрезку поверх уже идущей: иначе ссылка на прежний
        # рабочий поток терялась бы (его перетирал новый), и поток мог «висеть» —
        # отсюда баг «следующая обрезка не работает, надо перезапускать». Кнопка
        # на время обрезки и так выключена, но Ctrl+S мог обойти эту блокировку.
        # И быстрая обрезка (FfmpegWorker), и Smart Cut (SmartCutWorker) кладутся
        # в self.ffmpeg_thread — одной проверки достаточно.
        th = getattr(self, "ffmpeg_thread", None)
        if th is not None and th.isRunning():
            return

        # Режим картинки: «Обрезать» = собрать видео-проявление из картинки.
        if getattr(self, "is_still_image", False):
            self._export_still_pixelize()
            return

        in_s  = self.current_in
        out_s = self.current_out
        try:
            manual_in  = _api.time_to_s(self.in_time_edit.text())
            manual_out = _api.time_to_s(self.out_time_edit.text())
            in_s  = max(0.0, min(manual_in,  self.duration))
            out_s = max(0.0, min(manual_out, self.duration))
        except Exception:
            pass

        # Точку старта привязываем ВНИЗ к сетке кадров. Плеер (QtMultimedia) на
        # позиции IN показывает кадр, который «на экране» в этот момент — т.е.
        # кадр с pts ≤ IN (округление ВНИЗ). А ffmpeg-рез (-ss IN) оставляет
        # первый кадр с pts ≥ IN (округление ВВЕРХ). Если IN стоит между кадрами
        # (обычный случай — плейхед по звуку/мышью почти никогда не попадает ровно
        # на кадр), экспорт начинался бы на ОДИН кадр позже того, что видно в
        # превью — отсюда баг «первое слово/кадр срезается, а в монтаже он есть».
        # Пол к кадру делает export-seek WYSIWYG с превью: ffmpeg берёт ровно тот
        # кадр, что показан. Только для видео с известным fps; аудио режем как есть
        # (кадров нет — точное время верно). eps=1e-3 кадра гасит float-дрожь у
        # самой границы, не перескакивая на кадр раньше.
        if self.video_stream_index is not None and self.fps and self.fps > 0:
            frame_idx = _api.math.floor(in_s * self.fps + 1e-3)
            # Целимся на четверть кадра НИЖЕ границы кадра: ffmpeg-seek оставляет
            # первый кадр с pts ≥ ss, а при дробном fps (23.976/29.97) pts кадра
            # не ложится ровно в миллисекунды и округление строки времени (.3f)
            # могло бы перескочить на кадр ВПЕРЁД. Смещение −0.25 кадра держит ss
            # заведомо ниже pts нужного кадра (но выше предыдущего), поэтому ffmpeg
            # берёт ровно тот кадр, что показан в превью, на ЛЮБОМ fps.
            snapped = (frame_idx - 0.25) / self.fps
            in_s = max(0.0, min(snapped, self.duration))

        if out_s <= in_s:
            _api.msgbox_warning(self, "Внимание", "Конечная точка должна быть позже начальной.")
            return

        # Висит предпросмотр привязки к объекту — «Обрезать» и есть его экспорт:
        # режем выбранный отрезок и вшиваем накладку по уже посчитанному пути.
        if self.has_track_preview():
            self._render_track_overlay(in_s, out_s)
            return

        mode = self.cmb_mode.currentIndex()
        # Субтитры можно вшить, если выбрана любая дорожка (встроенная или внешний
        # файл) — пункт 0 = «Выкл».
        burn_subs = (self.chk_burn_subs.isChecked() and mode != 2
                     and self.cmb_subs.currentIndex() > 0)
        # Оптимизация: если субтитры просят вшить, но в выбранном отрезке по факту
        # нет ни одного события субтитров — вшивать нечего. Отключаем hardsub, и
        # тогда в режиме «Быстро» обрезка пойдёт без перекодировки (lossless).
        if burn_subs and not self._subs_present_in_range(
                self.actual_source_file, self.selected_sub_ext_path,
                self.cmb_subs.currentIndex() - 1, in_s, out_s):
            burn_subs = False
            self.log_label.setText(
                _api.icon_html('fa5s.info-circle', 12, _api.C['text2'])
                + " В отрезке нет субтитров — вшивание пропущено")
            self.log_label.setStyleSheet(f"color: {_api.C['text2']}; font-size: 12px;")
            if self.main is not None and hasattr(self.main, "log"):
                self.main.log("Монтаж: в выбранном отрезке нет субтитров — "
                              "вшивание пропущено, обрезка без перекодировки.")
        # Кадрирование видео несовместимо с copy-путями (Smart Cut копирует
        # середину, «Быстро» копирует поток целиком) — crop требует перекодировки.
        # При активной рамке принудительно переходим на полную перекодировку.
        crop_active = self._video_crop_filter() is not None
        # Пикселизация (эффект -vf) тоже несовместима с copy/Smart Cut — требует
        # перекодировки, как и кадрирование.
        pix_active = getattr(self, "_pixelize_active", False)
        # Наложенные картинки — такой же «фильтровый» эффект: copy/Smart Cut их
        # не умеют (путь «настройками Обработки» умеет — см. ниже).
        ovl_active = self.has_image_overlays()
        # Smart Cut несовместим с вшиванием субтитров (середина копируется): при
        # запросе hardsub откатываемся на полную перекодировку (mode 1).
        if mode in (4, 5):
            # 4 — «Перекодировать настройками «Обработки»», 5 — то же самое, но
            # ТОЛЬКО звук: точный рез + текущие настройки вкладки «Обработка»
            # одним проходом ProcessWorker (тот же путь, что кнопка «Обрезать и
            # обработать» в диалоге точности реза).
            audio_only = (mode == 5)
            # Наложенные картинки этот путь ТЕПЕРЬ умеет: их PNG уезжают в
            # item['overlays'] и вшиваются тем же единственным проходом
            # ProcessWorker (см. _execute_cut_and_process). Но только когда
            # «Обработка» реально перекодирует видео: с выключенной галочкой
            # «Перекодировать видео» поток копируется (-c:v copy), а к копии
            # никакие видеофильтры неприменимы. В аудио-режиме видеоряда нет
            # вовсе — там накладки теряются по определению режима.
            ovl_lost = ovl_active and (audio_only
                                       or not self._process_tab_encodes_video())
            # Вшивание субтитров путь ТЕПЕРЬ умеет — фильтр subtitles уезжает в
            # «Обработку» вместе с элементом очереди (см. _execute_cut_and_process
            # и ProcessWorker._build_video_filters). Теряется оно там же, где и
            # накладки: в аудио-режиме (видеоряда на выходе нет) и при выключенной
            # галочке «Перекодировать видео» (поток копируется, фильтры к копии
            # неприменимы).
            subs_lost = burn_subs and (audio_only
                                       or not self._process_tab_encodes_video())
            # Остальных своих видеофильтров путь не знает — если что-то из них
            # включено, спрашиваем, а не выкидываем молча. В аудио-режиме
            # спрашивать нечего: видеоряда на выходе нет по определению самого
            # режима — просто честно пишем в лог, что эффекты картинки к нему
            # не применяются.
            if subs_lost or crop_active or pix_active or ovl_lost:
                what = ", ".join(n for n, on in (
                    ("вшивание субтитров", subs_lost), ("кадрирование", crop_active),
                    ("пикселизация", pix_active),
                    ("наложенные картинки", ovl_lost)) if on)
                if audio_only:
                    self.log_label.setText(
                        _api.icon_html('fa5s.info-circle', 12, _api.C['text2'])
                        + " Аудио-режим: эффекты картинки не применяются")
                    self.log_label.setStyleSheet(f"color: {_api.C['text2']}; font-size: 12px;")
                    if self.main is not None and hasattr(self.main, "log"):
                        self.main.log("Монтаж: аудио-режим «Обработки» — на выходе "
                                      f"только звук, поэтому не применяются: {what}.")
                else:
                    # Закрытие окна (крестик, Esc) — ОТМЕНА, а не «Нет»: раньше
                    # любой ответ кроме «Да» запускал полную перекодировку, и
                    # закрытый вопрос молча начинал многочасовой экспорт.
                    ans = _api.msgbox_question(
                        self, "Настройки «Обработки»",
                        f"В режиме «Перекодировать настройками «Обработки»» не применяется: "
                        f"{what}.\n\nОбрезать настройками «Обработки» без этого?\n"
                        "«Нет» — обычная перекодировка средствами Монтажа (со всеми эффектами).\n"
                        "«Отмена» — не обрезать вовсе.",
                        buttons=(_api.QMessageBox.StandardButton.Yes
                                 | _api.QMessageBox.StandardButton.No
                                 | _api.QMessageBox.StandardButton.Cancel),
                        defaultButton=_api.QMessageBox.StandardButton.Yes)
                    if ans == _api.QMessageBox.StandardButton.No:
                        self._execute_cut(in_s, out_s, 1, burn_subs)
                        return
                    if ans != _api.QMessageBox.StandardButton.Yes:
                        return          # Отмена или закрытое окно — ничего не делаем
            self._execute_cut_and_process(in_s, out_s, audio_only=audio_only,
                                          burn_subs=burn_subs and not subs_lost)
            return
        if mode == 3:
            if burn_subs or crop_active or pix_active or ovl_active:
                self._execute_cut(in_s, out_s, 1, burn_subs)
            else:
                self._execute_smartcut(in_s, out_s)
            return
        if (crop_active or pix_active or ovl_active) and mode == 0:
            mode = 1  # быстрый copy не умеет crop/pixelize/накладки → перекодируем
        self._execute_cut(in_s, out_s, mode, burn_subs)

    def _export_still_pixelize(self):
        """Собирает ВИДЕО-проявление из загруженной картинки: кадр зацикливается
        (-loop 1) на заданную длительность, по нему идёт цепочка пикселизации
        (offset=0 — фильтрграф стартует с нуля) и, при наличии, кадрирование.
        Требует включённой пикселизации — в этом весь смысл режима картинки."""
        src = self.still_image_path or self.actual_source_file
        if not src or not _api.os.path.exists(str(src)):
            _api.msgbox_warning(self, "Внимание", "Картинка не загружена.")
            return
        if not getattr(self, "_pixelize_active", False):
            _api.msgbox_information(
                self, "Пикселизация",
                "Включите «Пикселизацию» (кнопка с сеткой) — для картинки именно она "
                "и создаёт видео-проявление.")
            return
        src = _api.Path(src)
        dur = max(1.0, float(self._still_duration))
        fps = max(1, int(self._still_fps))
        # Цепочка: кадрирование (если есть) → пикселизация (offset=0) → чётные
        # размеры под yuv420p/h264.
        crop_vf = self._video_crop_filter()
        pix_vf = self._video_pixelize_filter(dur, 0.0)
        chain = [p for p in (crop_vf, pix_vf) if p]
        chain.append("scale=trunc(iw/2)*2:trunc(ih/2)*2")
        vf = self._wrap_vf(",".join(chain), src)

        out_dir = (_api.Path(self.export_dir) if (self.export_dir and _api.os.path.isdir(self.export_dir))
                   else src.parent)
        final_out = str(out_dir / f"{src.stem}_пиксель.mp4")
        if _api.os.path.exists(final_out):
            final_out = _api._unique_output(final_out)

        venc = self._video_encoder_args(hardsub=False)
        cmd = [_api.FFMPEG, "-y", "-loop", "1", "-framerate", str(fps), "-i", str(src),
               "-t", _api.s_to_time(dur), "-vf", vf] + venc \
              + ["-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", final_out]

        self._report_progress(0, "Создание видео…")
        self.log_label.setText("Создание видео из картинки…")
        self._set_cut_status("Пикселизация… подготовка", icon='fa5s.hourglass-half')
        self._set_cut_btn_cancel(True)
        self._cut_t0 = _api.time.time(); self._cut_lastp = 0.0
        if getattr(self, "_cut_ticker", None) is None:
            self._cut_ticker = _api.QTimer(self); self._cut_ticker.setInterval(500)
            self._cut_ticker.timeout.connect(lambda: self._report_cut(self._cut_lastp))
        self._cut_ticker.start()

        self.ffmpeg_thread = _api.FfmpegWorker(cmd, duration=dur)
        self.ffmpeg_thread.progress.connect(self._on_cut_progress)

        def _on_finished(success, message, _final=final_out):
            try:
                if getattr(self, "_cut_ticker", None) is not None:
                    self._cut_ticker.stop()
            except Exception:
                pass
            self._set_cut_btn_cancel(False)
            if success and _api.os.path.exists(_final):
                try:
                    if self.main is not None and hasattr(self.main, "log"):
                        self.main.log(f"Видео-проявление из картинки готово: {_final}")
                except Exception:
                    pass
                self._progress_result_path = _final
                self.on_ffmpeg_finished(True, message)
            else:
                if _final and _api.os.path.exists(_final) and not success:
                    try: _api.os.remove(_final)
                    except Exception: pass
                self.on_ffmpeg_finished(success, message)

        self.ffmpeg_thread.finished.connect(_on_finished)
        self.ffmpeg_thread.start()

    def _execute_cut(self, in_s, out_s, mode, burn_subs,
                     src=None, force_overwrite=False, out_path=None):
        """Собирает и запускает ffmpeg-обрезку для диапазона [in_s, out_s].
        `src` позволяет перекодировать из ОРИГИНАЛА (для предложения «перекодировать
        с потерями» после неточной copy-обрезки), `force_overwrite` — перезаписать
        результат принудительно. `out_path` — точный путь вывода: пере-рез после
        неточной быстрой обрезки переиспользует имя ИМЕННО того файла, который он
        заменяет (его уже удалил _discard_temp_cut), а не пересобирает базовое имя
        `{stem}_обрез` — иначе перекодировка затёрла бы ДРУГУЮ, более раннюю обрезку
        того же исходника, занявшую это базовое имя."""
        src = _api.Path(src) if src else self.actual_source_file
        if not src or not src.exists():
            _api.msgbox_warning(self, "Внимание", "Файл не загружен.")
            return

        stem = src.stem; suffix = src.suffix
        if self.export_dir and _api.os.path.isdir(self.export_dir):
            out_dir = _api.Path(self.export_dir)
        else:
            out_dir = src.parent

        if out_path:
            final_out = str(out_path)
        elif mode == 2:
            final_out = str(out_dir / f"{stem}_обрез.mp3")
        else:
            final_out = str(out_dir / f"{stem}_обрез{suffix}")

        replace_original = force_overwrite or self.chk_overwrite.isChecked()
        # Повторная обрезка того же исходника НЕ затирает предыдущий клип: 2-й
        # файл сохраняется под именем с суффиксом (foo_обрез.mp4 → foo_обрез_1.mp4,
        # _2, …). Перезапись остаётся только для внутренней пере-обрезки
        # (force_overwrite / явный out_path) и правки «на месте» (цель == открытый файл).
        if _api.os.path.exists(final_out) and not force_overwrite and not out_path:
            loaded = str(self.actual_source_file) if self.actual_source_file else ""
            in_place = bool(loaded) and _api.os.path.normpath(loaded) == _api.os.path.normpath(final_out)
            if not (self.chk_overwrite.isChecked() and in_place):
                final_out = _api._unique_output(final_out)

        temp_out = self._make_temp_out(final_out)

        dur_cut = out_s - in_s
        in_str  = _api.s_to_time(in_s)
        dur_str = _api.s_to_time(dur_cut)

        # Внешняя озвучка (отдельный аудиофайл): подмешиваем её вторым входом и
        # берём звук из него. Применяется только если она выбрана и существует.
        ext_audio = self.selected_audio_ext_path
        if ext_audio and not _api.os.path.exists(ext_audio):
            ext_audio = None
        # Пункт «Нет» в списке дорожек: результат без звука (-an в конце).
        audio_off = bool(getattr(self, "audio_disabled", False))
        if audio_off:
            if mode == 2:
                _api.msgbox_warning(self, "Внимание",
                                    "Звук выключен (дорожка «Нет») — сохранять в MP3 нечего.")
                return
            ext_audio = None

        # Если в контейнере несколько аудиодорожек и выбрана конкретная —
        # сохраняем именно её (видео + выбранная аудиодорожка). Иначе поведение
        # по умолчанию (ffmpeg сам берёт по одной дорожке каждого типа).
        sel_a = self.selected_audio_abs_index
        pick_audio = (sel_a is not None and len(self._audio_streams) > 1
                      and not audio_off)
        amap = ["-map", "0:v:0", "-map", f"0:{sel_a}"] if pick_audio else []

        # Внешняя дорожка субтитров (файл рядом) — отдельный путь, иначе индекс
        # встроенной дорожки.
        ext_sub = self.selected_sub_ext_path
        burn_idx = self.cmb_subs.currentIndex() - 1
        # Кадрово-точной осталась только перекодировка; в режиме copy отслеживаем,
        # удалось ли обрезать без потерь по кадрам (для уведомления пользователю).
        exact_copy = (mode == 0 and not burn_subs and not ext_audio)
        venc = self._video_encoder_args(hardsub=burn_subs)
        # Кадрирование видео (рамка на холсте). crop умеет только перекодировка,
        # поэтому при активной рамке start_cut уже перевёл mode на 1. Здесь
        # фильтр добавляется к видеоцепочке (отдельным -vf либо в начало цепочки
        # субтитров, если идёт вшивание).
        crop_vf = self._video_crop_filter()
        # Пикселизация-проявление (эффект по времени клипа). Требует перекодировки;
        # если внутренний пере-рез вызвал _execute_cut с mode 0 при активном
        # эффекте — поднимаем до перекодировки. `pix_on` — будет ли эффект вообще
        # добавлять фильтр (от offset это не зависит), а сам фильтр строится с
        # правильным смещением времени отдельно в каждой ветке (см. _vf_args ниже).
        pix_on = self._video_pixelize_filter(dur_cut, 0.0) is not None
        # Наложенные картинки (логотип/водяной знак) — тоже фильтр: copy их не
        # умеет, поэтому при активных слоях идём перекодировкой, как с crop.
        ovl_on = self.has_image_overlays()
        if (pix_on or ovl_on) and mode == 0:
            mode = 1
        # Любой видеофильтр (crop/pixelize/накладка) — это перекодировка, а не
        # lossless-copy: не вводим в заблуждение уведомитель точности реза.
        if crop_vf or pix_on or ovl_on:
            exact_copy = False

        def _vf_args(offset):
            """Аргументы -vf для текущей ветки: наложенные картинки + crop (без
            времени) + пикселизация со смещением `offset` (время фильтрграфа в
            начале клипа — зависит от способа seek в ветке). Пустой список, если
            фильтровать нечего."""
            chain = [p for p in (crop_vf, self._video_pixelize_filter(dur_cut, offset)) if p]
            vf = self._wrap_vf(",".join(chain), src)
            return ["-vf", vf] if vf else []

        if burn_subs:
            # Hardsub всегда требует перекодировки. Используем ВЫХОДНОЙ seek
            # (-ss после -i), чтобы субтитры не разъехались по времени с кадрами.
            # Сам фильтр (стиль, шрифты контейнера) собирает _subtitles_vf — он же
            # используется путём «настройками «Обработки»».
            vf = self._subtitles_vf(src, ext_sub, burn_idx)
            if not vf:
                burn_subs = False
        if burn_subs:
            # Кадрируем ДО субтитров: libass рисует на уже обрезанном кадре, и
            # текст не уезжает за пределы кадрированной области.
            if crop_vf:
                vf = f"{crop_vf},{vf}"
            # Пикселизацию применяем ПОСЛЕ субтитров — иначе текст тоже размоется
            # в мозаику и станет нечитаемым. Обе ветки вшивания используют ВЫХОДНОЙ
            # seek, поэтому смещение времени = in_s.
            _pix = self._video_pixelize_filter(dur_cut, in_s)
            if _pix:
                vf = f"{vf},{_pix}"
            # Наложенные картинки идут ПЕРЕД кадрированием и субтитрами (см.
            # overlay_filter_graph) — так же, как их видно в плеере.
            vf = self._wrap_vf(vf, src)
            if ext_audio:
                # Видео+субтитры из исходника (вход 0), звук — из внешнего файла
                # (вход 1). Выходной seek (-ss/-t как опции вывода) равно режет оба.
                # -sn: субтитры ВШИТЫ в кадр (-vf subtitles), отдельная мягкая
                # дорожка не нужна — и, что важнее, при выходном seek её копия
                # тащит длительность всего эпизода (см. -sn ниже).
                cmd = [_api.FFMPEG, "-y", "-i", str(src), "-i", ext_audio,
                       "-ss", in_str, "-t", dur_str,
                       "-map", "0:v:0", "-map", "1:a:0", "-vf", vf] \
                      + venc + ["-c:a", "aac", "-b:a", "192k", "-sn", temp_out]
            else:
                # Аудио НЕ перекодируем (контейнер тот же → совместимо).
                # -sn ОБЯЗАТЕЛЕН: без явного -map ffmpeg авто-включает в вывод и
                # субтитровый поток исходника; при выходном seek его копия не
                # режется и сообщает длительность ВСЕГО эпизода (~11 мин вместо
                # 7 сек) — отсюда баг «обрезка с сабами даёт 11 минут». Субтитры
                # уже вшиты в кадр (-vf subtitles), мягкая дорожка не нужна.
                cmd = [_api.FFMPEG, "-y", "-i", str(src), "-ss", in_str, "-t", dur_str] \
                      + amap + ["-vf", vf] + venc + ["-c:a", "copy", "-sn", temp_out]
        elif ext_audio and mode != 2:
            # Внешняя озвучка без вшивания субтитров. Видео берём по режиму
            # (copy/перекодировка), звук — из внешнего файла (перекодируем в AAC,
            # т.к. контейнер/кодек могут не совпадать).
            vargs = (["-c:v", "copy"]
                     if (mode == 0 and not crop_vf and not pix_on and not ovl_on)
                     else venc)
            # ВХОДНОЙ seek по видео (-ss до -i src) → фильтрграф стартует с 0.
            cmd = [_api.FFMPEG, "-y", "-ss", in_str, "-i", str(src),
                   "-ss", in_str, "-i", ext_audio, "-t", dur_str,
                   "-map", "0:v:0", "-map", "1:a:0"] \
                  + _vf_args(0.0) + vargs + ["-c:a", "aac", "-b:a", "192k", temp_out]
        elif mode == 0:
            # Быстрая обрезка (copy) — ВХОДНОЙ seek к точке реза (-ss ДО -i).
            #
            # РАНЬШЕ резали ВЫХОДНЫМ seek (-ss ПОСЛЕ -i): он давал верную
            # длительность, НО видео при copy «прилипало» к СЛЕДУЮЩЕМУ ключевому
            # кадру (за точкой реза), и его PTS оставался > 0, тогда как звук
            # стартовал с 0. На AV1/MP4 это давало баг «первый кадр застывает на
            # несколько секунд в начале» (video start_time 5.7с против audio 0):
            # плеер держал первый кадр, пока звук играл в пустоту до прихода видео.
            #
            # Входной seek встаёт на ближайший ключевой кадр ≤ in_s, поэтому видео
            # И звук стартуют с НУЛЯ (выровнены) — дырки/застывания нет. На MP4
            # ffmpeg к тому же пишет edit-list и кадрово-точно показывает с in_s;
            # на MKV (edit-list нет) начало прилипает к ключевому кадру — это
            # нормальное поведение lossless-copy, его ловит _notify_cut_accuracy и
            # предлагает Smart Cut.
            #   • -fflags +genpts — демуксер генерит недостающие PTS (без него
            #     mpeg4/DivX в MKV падали с -22 «unknown timestamp», ошибка
            #     4294967274). Это и был реальный фикс -22, а не выходной seek.
            #   • рез по ДЛИТЕЛЬНОСТИ -t (НЕ входной -to: тот на mpeg4 давал 12с
            #     вместо 7с; -t считается от точки seek и надёжен).
            cmd = [_api.FFMPEG, "-y", "-fflags", "+genpts",
                   "-ss", in_str, "-i", str(src), "-t", dur_str] \
                  + amap + ["-c", "copy", temp_out]
        elif mode == 1:
            # Перекодировка с КАДРОВОЙ точностью. Точность реза целиком даёт
            # ВЫХОДНОЙ seek (-ss/-t ПОСЛЕ -i): ffmpeg режет ровно по кадру, не
            # «прилипая» к ключевому кадру и не сбиваясь на контейнерах со
            # смещённым start_time (MKV/WEB-DL); копируемый звук режется тем же
            # выходным -ss ровно до in_s.
            #
            # Раньше выходной seek шёл ОТ НАЧАЛА файла (-i src -ss in): чтобы
            # вырезать 6 c у конца 23-мин эпизода, ffmpeg сперва ~23 мин
            # декодировал «вхолостую» — медленно, и прогресс всё это время висел
            # в фазе «подготовка» (ffmpeg не шлёт time=, пока не дойдёт до реза).
            #
            # Ускорение: добавляем БЫСТРЫЙ входной pre-seek к точке за PRESEEK
            # секунд до реза — ffmpeg сам встаёт на ближайший ключевой кадр
            # ≤ pre_ss и декодирует только оттуда (секунды вместо минут, прогресс
            # сразу идёт 0→100%). ТОЧНЫЙ рез по-прежнему делает выходной -ss.
            # Проверено покадрово (framemd5 видео + md5 аудио идентичны старому
            # пути на mp4/mkv/WEB-DL +10c/edit-list, h264/hevc, у границ и в конце):
            #   • выходной -ss отсчитывается от ЗАПРОШЕННОГО pre_ss (а не от того,
            #     куда «прилип» seek) → подстройка по кадру не зависит от GOP,
            #     детектировать ключевые кадры не нужно;
            #   • выходной -ss режет и КОПИРУЕМЫЙ звук ровно до in_s — без него
            #     (чистый входной seek) звук «съезжает» на ~PRESEEK раньше видео;
            #   • входной -ss задаётся в контентной шкале (ffmpeg прибавляет
            #     start_time) → смещённый start_time рез не ломает.
            # out_ss считаем от фактической (округлённой до мс) точки pre-seek,
            # чтобы итоговая точка реза совпала с round_ms(in_s) старого пути.
            # При in_s ≤ 2*PRESEEK старый путь и так быстр (декод ≤ пары секунд) и
            # обходит особенность входного seek к самому нулю на контейнерах со
            # смещением — оставляем выходной seek от начала.
            # -sn ОБЯЗАТЕЛЕН: без явного -map ffmpeg авто-включает субтитровый
            # поток, который при выходном seek не режется и сообщает длительность
            # всего эпизода (~11 мин). Этот режим запускается в т.ч. как fallback
            # после неточной copy-обрезки (_notify_cut_accuracy) — поэтому баг
            # «11 минут» всплывал и без явного вшивания субтитров.
            PRESEEK = 3.0
            if in_s > 2 * PRESEEK:
                pre_str = _api.s_to_time(in_s - PRESEEK)
                out_ss = _api.s_to_time(in_s - _api.time_to_s(pre_str))
                # ВХОДНОЙ pre-seek (pre_str) + ВЫХОДНОЙ -ss (out_ss): клип в шкале
                # фильтрграфа начинается на t = out_ss.
                cmd = [_api.FFMPEG, "-y", "-ss", pre_str, "-i", str(src),
                       "-ss", out_ss, "-t", dur_str] \
                      + amap + _vf_args(_api.time_to_s(out_ss)) + venc + ["-c:a", "copy", "-sn", temp_out]
            else:
                # Чистый ВЫХОДНОЙ seek → фильтрграф видит исходное время, offset = in_s.
                cmd = [_api.FFMPEG, "-y", "-i", str(src), "-ss", in_str, "-t", dur_str] \
                      + amap + _vf_args(in_s) + venc + ["-c:a", "copy", "-sn", temp_out]
        elif ext_audio:
            # Только аудио (MP3) из внешней озвучки.
            cmd = [_api.FFMPEG, "-y", "-ss", in_str, "-i", ext_audio,
                   "-t", dur_str, "-map", "0:a:0",
                   "-c:a", "libmp3lame", "-q:a", "2", temp_out]
        else:
            astream = sel_a if sel_a is not None else self.audio_stream_index
            if astream is not None:
                cmd = [_api.FFMPEG, "-y", "-ss", in_str, "-i", str(src),
                       "-t", dur_str, "-map", f"0:{astream}",
                       "-c:a", "libmp3lame", "-q:a", "2", temp_out]
            else:
                cmd = [_api.FFMPEG, "-y", "-ss", in_str, "-i", str(src),
                       "-t", dur_str, "-vn", "-c:a", "libmp3lame", "-q:a", "2", temp_out]

        if audio_off:
            cmd = drop_audio(cmd, temp_out)

        self._report_progress(0, "Обрезка…")
        self.log_label.setText("Обрезка...")
        self._set_cut_status("Обрезка… подготовка", icon='fa5s.hourglass-half')
        self._set_cut_btn_cancel(True)

        # Прогресс с ETA. Тикер раз в 0.5с обновляет «прошло/ETA», чтобы строка
        # не выглядела зависшей, даже если ffmpeg редко шлёт time= (короткие
        # отрезки или фаза перемотки декодером до точки реза).
        self._cut_t0 = _api.time.time()
        self._cut_lastp = 0.0
        if getattr(self, "_cut_ticker", None) is None:
            self._cut_ticker = _api.QTimer(self)
            self._cut_ticker.setInterval(500)
            self._cut_ticker.timeout.connect(lambda: self._report_cut(self._cut_lastp))
        self._cut_ticker.start()

        self.ffmpeg_thread = _api.FfmpegWorker(cmd, duration=dur_cut)
        self.ffmpeg_thread.progress.connect(self._on_cut_progress)

        def _on_finished(success, message, _temp=temp_out, _final=final_out,
                         _exact=exact_copy, _reqdur=dur_cut, _burn=burn_subs,
                         _in=in_s, _out=out_s, _src=src):
            try:
                if getattr(self, "_cut_ticker", None) is not None:
                    self._cut_ticker.stop()
            except Exception:
                pass
            self._set_cut_btn_cancel(False)
            # Папка извлечённых шрифтов больше не удаляется сразу — она в
            # _subtitle_fonts_cache и живёт до закрытия вкладки (см. shutdown()),
            # чтобы повторный экспорт того же источника не гонял ffmpeg заново.
            if success and _temp:
                try:
                    is_loaded = (_api.os.path.normpath(str(self.actual_source_file)) ==
                                 _api.os.path.normpath(_final))
                    if replace_original and _api.os.path.exists(_final):
                        try:
                            _api.os.remove(_final)
                        except OSError:
                            # Цель занята другим процессом (её читает «Обработка») —
                            # не падаем: _replace_tolerant ниже уведёт результат на
                            # свободное имя.
                            pass
                    if _api.os.path.exists(_final) and not replace_original:
                        if _api.os.path.exists(_temp):
                            _api.os.remove(_temp)
                        self.on_ffmpeg_finished(False, "Файл уже существует (логическая ошибка)")
                        return
                    saved_final = self._replace_tolerant(_temp, _final)
                    if _api.os.path.normpath(saved_final) != _api.os.path.normpath(_final):
                        # Имя сменилось: целевой файл был занят (его читала другая
                        # вкладка). Сообщаем и дальше работаем с фактическим путём.
                        self._notify_busy_rename(_final, saved_final)
                        _final = saved_final
                        is_loaded = (_api.os.path.normpath(str(self.actual_source_file)) ==
                                     _api.os.path.normpath(_final))
                    # Точность обрезки проверяем ДО перезагрузки. Если copy-обрезка
                    # вышла не кадрово-точной — спрашиваем, что делать с фрагментом.
                    action = self._notify_cut_accuracy(_final, _reqdur, _exact, _burn,
                                                       _in, _out, _src)
                    if action == 'encode':
                        # Пользователь выбрал переделать перекодировкой — неточный
                        # файл быстрой обрезки больше не нужен, удаляем его (иначе
                        # при выключенной перезаписи останется осиротевший дубль,
                        # а результат уедет в «…_обрез_1»).
                        self._discard_temp_cut(_final, is_loaded)
                        _api.QTimer.singleShot(0, lambda: self._execute_cut(
                            _in, _out, 1, _burn, src=_src,
                            force_overwrite=True, out_path=_final))
                        return
                    if action == 'smartcut':
                        # То же и для Smart Cut: создаст точный файл под тем же
                        # именем — неточный результат быстрой обрезки удаляем.
                        self._discard_temp_cut(_final, is_loaded)
                        _api.QTimer.singleShot(0, lambda: self._execute_smartcut(
                            _in, _out, out_path=_final))
                        return
                    if action == 'process':
                        # Точный рез + «Обработка» текущими настройками одним
                        # проходом (см. _execute_cut_and_process) — неточный
                        # результат быстрой обрезки больше не нужен.
                        self._discard_temp_cut(_final, is_loaded)
                        _api.QTimer.singleShot(0, lambda: self._execute_cut_and_process(
                            _in, _out, out_path=_final, src=_src))
                        return
                    if action == 'delete':
                        # Удаляем созданный неточный файл по просьбе пользователя.
                        # Если он сейчас открыт в плеере — сперва освобождаем источник.
                        try:
                            if is_loaded:
                                # Освобождаем файл: останавливаем плеер и снимаем источник.
                                try: self.player.stop()
                                except Exception: pass
                                try: self.player.setSource(_api.QUrl())
                                except Exception: pass
                            if _api.os.path.exists(_final):
                                _api.os.remove(_final)
                            self.log_label.setText(
                                _api.icon_html('fa5s.trash', 12, _api.C['text2']) + " Файл удалён")
                            self.log_label.setStyleSheet(f"color: {_api.C['text2']}; font-size: 12px;")
                            self._report_progress(0, "Файл удалён")
                        except Exception as e:
                            _api.msgbox_warning(self, "Не удалось удалить",
                                                f"Не удалось удалить файл:\n{e}")
                        return
                    if is_loaded:
                        self.load_file(_final)
                    self._progress_result_path = _final
                    self.on_ffmpeg_finished(True, message)
                except Exception as e:
                    try:
                        if _api.os.path.exists(_temp):
                            _api.os.remove(_temp)
                    except Exception:
                        pass
                    self.on_ffmpeg_finished(False, f"Ошибка при сохранении: {e}")
            else:
                if _temp and _api.os.path.exists(_temp):
                    try:
                        _api.os.remove(_temp)
                    except Exception:
                        pass
                self.on_ffmpeg_finished(success, message)

        self.ffmpeg_thread.finished.connect(_on_finished)
        self.ffmpeg_thread.start()

    def _smartcut_status(self, s):
        try:
            self.log_label.setText(s)
            self._set_cut_status(s, icon='fa5s.cut')
            if self.main is not None and hasattr(self.main, "log"):
                self.main.log(s)
        except Exception:
            pass

    def _execute_smartcut(self, in_s, out_s, out_path=None):
        """Запускает умную обрезку (SmartCutWorker): граничные участки от точек
        реза до ближайших ключевых кадров перекодируются, середина копируется без
        потерь. Контейнер вывода = контейнер исходника (нужно для copy-склейки).
        `out_path` — точный путь вывода (пере-рез после неточной быстрой обрезки
        переиспользует имя заменяемого файла, а не пересобирает `{stem}_обрез`;
        см. _execute_cut)."""
        src = self.actual_source_file
        if not src or not src.exists():
            _api.msgbox_warning(self, "Внимание", "Файл не загружен.")
            return
        stem = src.stem; suffix = src.suffix
        out_dir = (_api.Path(self.export_dir)
                   if (self.export_dir and _api.os.path.isdir(self.export_dir)) else src.parent)
        final_out = str(out_path) if out_path else str(out_dir / f"{stem}_обрез{suffix}")
        replace_original = self.chk_overwrite.isChecked() or bool(out_path)
        # Как и в _execute_cut: повторная Smart Cut обрезка того же файла не
        # затирает прошлый клип, а уходит под именем с суффиксом. Явный out_path
        # (пере-рез) указывает на уже освобождённый файл — его не переименовываем.
        if _api.os.path.exists(final_out) and not out_path:
            loaded = str(self.actual_source_file) if self.actual_source_file else ""
            in_place = bool(loaded) and _api.os.path.normpath(loaded) == _api.os.path.normpath(final_out)
            if not (replace_original and in_place):
                final_out = _api._unique_output(final_out)
        temp_out = self._make_temp_out(final_out, suffix)

        self._report_progress(0, "Smart Cut…")
        self.log_label.setText("Smart Cut…")
        self._set_cut_status("Smart Cut… подготовка", icon='fa5s.hourglass-half')
        self._set_cut_btn_cancel(True)
        self._cut_t0 = _api.time.time(); self._cut_lastp = 0.0
        if getattr(self, "_cut_ticker", None) is None:
            self._cut_ticker = _api.QTimer(self); self._cut_ticker.setInterval(500)
            self._cut_ticker.timeout.connect(lambda: self._report_cut(self._cut_lastp))
        self._cut_ticker.start()

        venc = self._video_encoder_args()
        # Выбранная аудиодорожка (если в контейнере их несколько). None → первая.
        sc_audio = (self.selected_audio_abs_index
                    if (self.selected_audio_abs_index is not None
                        and len(self._audio_streams) > 1) else None)
        self.ffmpeg_thread = _api.SmartCutWorker(src, in_s, out_s, temp_out, venc,
                                            audio_index=sc_audio,
                                            no_audio=bool(getattr(self, "audio_disabled", False)))
        self.ffmpeg_thread.progress.connect(self._on_cut_progress)
        self.ffmpeg_thread.status.connect(self._smartcut_status)

        def _on_finished(success, message, _temp=temp_out, _final=final_out):
            try:
                if getattr(self, "_cut_ticker", None) is not None:
                    self._cut_ticker.stop()
            except Exception:
                pass
            self._set_cut_btn_cancel(False)
            if success and _temp and _api.os.path.exists(_temp) and _api.os.path.getsize(_temp) > 0:
                try:
                    is_loaded = (_api.os.path.normpath(str(self.actual_source_file)) ==
                                 _api.os.path.normpath(_final))
                    if replace_original and _api.os.path.exists(_final):
                        try:
                            _api.os.remove(_final)
                        except OSError:
                            pass  # занят другим процессом — уйдём на свободное имя
                    if _api.os.path.exists(_final) and not replace_original:
                        if _api.os.path.exists(_temp):
                            _api.os.remove(_temp)
                        self.on_ffmpeg_finished(False, "Файл уже существует (логическая ошибка)")
                        return
                    saved_final = self._replace_tolerant(_temp, _final)
                    if _api.os.path.normpath(saved_final) != _api.os.path.normpath(_final):
                        self._notify_busy_rename(_final, saved_final)
                        _final = saved_final
                        is_loaded = (_api.os.path.normpath(str(self.actual_source_file)) ==
                                     _api.os.path.normpath(_final))
                    if is_loaded:
                        self.load_file(_final)
                    self._progress_result_path = _final
                    self.on_ffmpeg_finished(True, message)
                except Exception as e:
                    try:
                        if _api.os.path.exists(_temp):
                            _api.os.remove(_temp)
                    except Exception:
                        pass
                    self.on_ffmpeg_finished(False, f"Ошибка при сохранении: {e}")
            else:
                if _temp and _api.os.path.exists(_temp):
                    try:
                        _api.os.remove(_temp)
                    except Exception:
                        pass
                self.on_ffmpeg_finished(success, message)

        self.ffmpeg_thread.finished.connect(_on_finished)
        self.ffmpeg_thread.start()

    def _process_tab_encodes_video(self):
        """Перекодирует ли «Обработка» видео прямо сейчас (её галочка
        «Перекодировать видео»). При выключенной видеопоток копируется
        (-c:v copy), и никакие видеофильтры — в том числе наложенные картинки —
        к нему не применимы. Вкладка недоступна → считаем, что перекодирует
        (обычная настройка по умолчанию)."""
        tm = getattr(self.main, 'tab_media', None) if self.main is not None else None
        try:
            return bool(tm.chk_enable_video.isChecked())
        except Exception:
            return True

    def _execute_cut_and_process(self, in_s, out_s, out_path=None, src=None,
                                 audio_only=False, burn_subs=False):
        """Кнопка «Обрезать и обработать»: режет диапазон [in_s,out_s) И сразу
        применяет вкладку «Обработка» ЕЁ ТЕКУЩИМИ настройками (CRF/preset/
        скорость/loudnorm/fps/…) — одним ffmpeg-проходом внутри
        ProcessWorker.process_media (item['trim']), без отдельного x264-реэнкода
        в Монтаже, который иначе перекодировался бы ЕЩЁ РАЗ при последующем
        прогоне через «Обработку» (двойное поколение потерь).

        audio_only=True (режим обрезки «(Аудио) Перекодировать настройками
        «Обработки»») — то же самое, но видеоряд отбрасывается и на выходе
        остаётся ТОЛЬКО звуковая дорожка (.opus) с текущими настройками звука
        «Обработки». Технически это item['audio_only'] — process_media гонит
        такой элемент своей аудио-онли веткой, той же, что и для файлов без
        видео (см. workers.py).

        Настройки НЕ копируем — вызываем тот же MediaTab._run_items(), что и
        кнопка «НАЧАТЬ» на вкладке «Обработка», поэтому любые настройки,
        добавленные туда в будущем, подхватятся автоматически.

        Имя итогового файла собираем ПОСЛЕ обработки (см. _on_finished_all), а
        не заранее фиксированным «{stem}_обрез{исходное_расширение}» — иначе
        (а) из имени пропадали суффиксы реально применённых настроек (crf/
        speed/norm/fade/noaudio — ровно то, что показывает суффикс в обычной
        «Обработке»), и (б) для источников не-.mp4 (mkv/…) итог process_media
        (всегда .mp4 для AV1) переименовывался под ЧУЖОЕ расширение источника —
        файл с mp4-содержимым получал имя «*.mkv», что вводило в заблуждение.

        Два РАЗНЫХ отрезка одного исходника получают разные файлы: имя занято —
        уходим на «…_обрез_1» (см. _unique_output), а не затираем предыдущий
        клип. Перезапись остаётся только для внутреннего пере-реза (out_path)
        и правки «на месте»."""
        src = _api.Path(src) if src else self.actual_source_file
        if not src or not src.exists():
            _api.msgbox_warning(self, "Внимание", "Файл не загружен.")
            return
        if audio_only and bool(getattr(self, "audio_disabled", False)):
            _api.msgbox_warning(self, "Внимание",
                                "Звук выключен (дорожка «Нет») — обрабатывать нечего.")
            return
        tm = getattr(self.main, 'tab_media', None)
        if tm is None:
            _api.msgbox_warning(self, "Внимание", "Вкладка «Обработка» недоступна.")
            return
        try:
            busy = bool(getattr(tm, 'worker', None) is not None and tm.worker.isRunning())
        except Exception:
            busy = False
        if busy:
            _api.msgbox_information(
                self, "«Обработка» занята",
                "Во вкладке «Обработка» уже идёт очередь — дождитесь её "
                "завершения и повторите обрезку.")
            return

        stem = src.stem
        out_dir = (_api.Path(self.export_dir)
                   if (self.export_dir and _api.os.path.isdir(self.export_dir)) else src.parent)
        # out_path приходит только от ВНУТРЕННЕГО пере-реза (предложение
        # «переделать точно» после быстрой обрезки — там неточный файл уже
        # удалён _discard_temp_cut, и его имя законно занять снова). Само имя
        # не берём: расширение результата «Обработки» может отличаться от
        # исходного (AV1 всегда .mp4), поэтому имя по-прежнему собираем по
        # факту — см. ниже. Флаг разрешает перезапись, и только её.
        force_overwrite = bool(out_path)

        self._report_progress(0, "Обработка…")
        self.log_label.setText("Отправлено в «Обработку»…"
                               + (" (только звук)" if audio_only else ""))
        self._set_cut_status(
            ("Обработка звука… подготовка" if audio_only else "Обработка… подготовка"),
            icon='fa5s.hourglass-half')
        self._set_cut_btn_cancel(True, cancel_handler=lambda: self._cancel_cut_and_process(tm))
        self._cut_t0 = _api.time.time(); self._cut_lastp = 0.0
        if getattr(self, "_cut_ticker", None) is None:
            self._cut_ticker = _api.QTimer(self); self._cut_ticker.setInterval(500)
            self._cut_ticker.timeout.connect(lambda: self._report_cut(self._cut_lastp))
        self._cut_ticker.start()

        iid = _api.uuid.uuid4().hex
        # Выбранная аудиодорожка (если в контейнере их несколько) — иначе
        # process_media брал первую по умолчанию, игнорируя выбор в Монтаже.
        sel_a = (self.selected_audio_abs_index
                 if (self.selected_audio_abs_index is not None
                     and len(self._audio_streams) > 1) else None)
        item = {'iid': iid, 'path': str(src), 'type': 'MEDIA',
                'dur': max(0.0, out_s - in_s), 'is_done': False,
                'trim': (in_s, out_s), 'audio_index': sel_a,
                'audio_only': bool(audio_only),
                # Пункт «Нет» в списке дорожек — как галочка «Удалить аудио».
                'remove_audio': bool(getattr(self, "audio_disabled", False))}
        # Наложенные картинки едут в «Обработку» готовыми PNG (уже отрисованы
        # под размер ИСХОДНОГО кадра, координаты — в его пикселях). process_media
        # подмешивает их фильтром overlay ПЕРЕД своей цепочкой (crop чёрных
        # полос/scale/fade), поэтому кадрирование и масштаб применяются уже к
        # кадру с картинкой — ровно как это видно в плеере Монтажа. Аудио-режим
        # видеоряда не выводит, поэтому там накладки не рендерим вовсе.
        if not audio_only:
            ovl = self._render_export_overlays()
            if ovl:
                item['overlays'] = ovl
                item['overlay_format'] = self._overlay_pix_fmt(src)
            # Вшивание субтитров этот путь тоже умеет: фильтр subtitles едет в
            # «Обработку» готовой строкой и встаёт в её же цепочку -vf (см.
            # _build_video_filters). Отдельной перекодировки Монтажом ради
            # субтитров больше не нужно — она была бы вторым поколением потерь.
            if burn_subs:
                spec = self._burn_subs_spec(src, in_s)
                if spec:
                    item['burn_subs'] = spec
        # _run_items сама собирает настройки со всех виджетов «Обработки» и
        # запускает ProcessWorker (тот же путь, что кнопка «НАЧАТЬ»); в очереди —
        # только наш синтетический элемент, чужие файлы не затрагиваются.
        tm._run_items([item])
        proc_worker = getattr(tm, 'worker', None)
        if proc_worker is None:
            self._set_cut_btn_cancel(False)
            self.on_ffmpeg_finished(False, "Не удалось запустить «Обработку»")
            return

        def _on_progress(p_iid, pct, _iid=iid):
            if p_iid == _iid:
                self._on_cut_progress(pct)

        def _on_status(s_iid, txt, code, _iid=iid):
            if s_iid == _iid:
                self._smartcut_status(txt)

        def _on_finished_all(_item=item):
            for sig, slot in ((proc_worker.progress, _on_progress),
                              (proc_worker.status, _on_status),
                              (proc_worker.finished_all, _on_finished_all)):
                try: sig.disconnect(slot)
                except Exception: pass
            try:
                if getattr(self, "_cut_ticker", None) is not None:
                    self._cut_ticker.stop()
            except Exception:
                pass
            self._set_cut_btn_cancel(False)
            temp_out = _item.get('out_path')
            if not _item.get('is_done') or not temp_out or not _api.os.path.exists(temp_out):
                self.on_ffmpeg_finished(
                    False, "«Обработка» не создала результат (см. лог вкладки «Обработка»)")
                return
            try:
                # process_media сам собрал имя с суффиксами применённых настроек
                # (crf/speed/norm/fade/noaudio — см. process_media в workers.py) —
                # переносим ТОЛЬКО хвост после исходного stem, добавляя «_обрез»
                # перед ним, и берём РЕАЛЬНОЕ расширение результата (для AV1 —
                # всегда .mp4, даже если источник .mkv).
                temp_stem, temp_ext = _api.os.path.splitext(_api.os.path.basename(temp_out))
                tail = temp_stem[len(stem):] if temp_stem.startswith(stem) else ("_" + temp_stem)
                final_out = str(out_dir / f"{stem}_обрез{tail}{temp_ext}")
                # Второй отрезок ИЗ ТОГО ЖЕ файла с теми же настройками даёт
                # ровно то же имя — и раньше «Перезаписать файл» (галочка
                # включена по умолчанию) молча стирала первый клип. Правило
                # здесь теперь такое же, как у обычной обрезки (_execute_cut):
                # перезаписываем ТОЛЬКО внутренний пере-рез (force_overwrite)
                # либо правку «на месте», когда цель — сам открытый файл.
                # Во всех остальных случаях уходим на «…_обрез_1», «_2», …
                loaded = str(self.actual_source_file) if self.actual_source_file else ""
                in_place = bool(loaded) and (_api.os.path.normpath(loaded) ==
                                             _api.os.path.normpath(final_out))
                replace_original = force_overwrite or (self.chk_overwrite.isChecked()
                                                       and in_place)
                if _api.os.path.exists(final_out) and not replace_original:
                    final_out = _api._unique_output(final_out)

                is_loaded = (_api.os.path.normpath(str(self.actual_source_file)) ==
                             _api.os.path.normpath(final_out))
                if replace_original and _api.os.path.exists(final_out):
                    try:
                        _api.os.remove(final_out)
                    except OSError:
                        pass  # занят другим процессом — уйдём на свободное имя
                saved_final = self._replace_tolerant(temp_out, final_out)
                if _api.os.path.normpath(saved_final) != _api.os.path.normpath(final_out):
                    self._notify_busy_rename(final_out, saved_final)
                    final_out = saved_final
                    is_loaded = (_api.os.path.normpath(str(self.actual_source_file)) ==
                                 _api.os.path.normpath(final_out))
                if is_loaded:
                    self.load_file(final_out)
                self._progress_result_path = final_out
                self.on_ffmpeg_finished(True, "Готово (Обработка)")
            except Exception as e:
                self.on_ffmpeg_finished(False, f"Ошибка при сохранении: {e}")

        proc_worker.progress.connect(_on_progress)
        proc_worker.status.connect(_on_status)
        proc_worker.finished_all.connect(_on_finished_all)

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
