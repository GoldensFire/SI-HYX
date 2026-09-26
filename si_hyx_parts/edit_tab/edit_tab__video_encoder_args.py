# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""EditTab: _video_encoder_args. Public namespace: edit_tab."""
import edit_tab as _api


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
