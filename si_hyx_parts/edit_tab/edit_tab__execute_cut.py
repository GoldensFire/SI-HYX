# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""EditTab: _execute_cut. Public namespace: edit_tab."""
import edit_tab as _api
from si_hyx_parts.edit_tab.edit_tab_audio_off import drop_audio


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
