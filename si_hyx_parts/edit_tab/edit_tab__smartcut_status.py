# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""EditTab: _smartcut_status. Public namespace: edit_tab."""
import edit_tab as _api


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
