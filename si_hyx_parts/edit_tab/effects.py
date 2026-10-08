# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Монтаж: кадрирование, пикселизация, накладки, удаление объекта и трекинг."""
import edit_tab as _api


class EditTabEffectsMixin:
    """Монтаж: кадрирование, пикселизация, накладки, удаление объекта и трекинг."""

    def _update_mode_combo_for_media(self, has_video):
        """Для аудиофайла оставляем только применимые режимы обрезки: «Быстро
        (без потерь)» (0) и «Только аудио (MP3)» (2). «Перекодировать» (1, гонит
        видеокодек) и «Smart Cut» (3, работает по ключевым кадрам ВИДЕО) к аудио
        неприменимы — гасим их в списке, чтобы их нельзя было выбрать. Индексы
        режимов фиксированы (их читает start_cut), поэтому пункты не удаляем, а
        отключаем через модель комбобокса."""
        cmb = getattr(self, "cmb_mode", None)
        if cmb is None:
            return
        try:
            # Гасим режимы только когда РЕАЛЬНО загружено аудио без видео; без
            # файла (или с видео) — все режимы доступны.
            src = getattr(self, "actual_source_file", None)
            audio_only = (bool(src) and not has_video
                          and getattr(self, "duration", 0) > 0.1)
            model = cmb.model()
            # 4 («настройками «Обработки»») и 5 («(Аудио) …») аудио НЕ ломают:
            # ProcessWorker сам умеет аудио-онли (Pass-1 в opus), а 5 в него же
            # и целится, поэтому их не гасим.
            audio_invalid = (1, 3)   # «Перекодировать», «Smart Cut»
            for i in range(cmb.count()):
                item = model.item(i)
                if item is None:
                    continue
                item.setEnabled((not audio_only) or i not in audio_invalid)
            # Если для аудио выбран теперь недоступный режим — переводим на
            # «Быстро (без потерь)» (точная lossless-обрезка по времени).
            if audio_only and cmb.currentIndex() in audio_invalid:
                cmb.setCurrentIndex(0)
        except Exception:
            pass

    def _toggle_frame_crop(self, on):
        """Вкл/выкл режим правки рамки кадрирования на холсте (как в «Редактировании
        фото»): появляется рамка с ручками и кнопки «Применить/Отмена»."""
        vw = getattr(self, "video_widget", None)
        if isinstance(vw, _api.VideoCanvas):
            vw.set_crop_mode(bool(on))
        if on:
            try:
                if self.main is not None and hasattr(self.main, "log"):
                    self.main.log("Кадрирование видео: правьте рамку ручками "
                                  "(углы/стороны), затем «Применить» (Enter) или "
                                  "«Отмена» (Esc). Применится при «Обрезать» "
                                  "(перекодирование).")
            except Exception:
                pass

    def _toggle_pixelize(self, on):
        """Вкл/выкл эффект «проявление из пикселей». При включении открывается
        диалог с параметрами (число шагов, стартовый блок); отмена снимает чек.
        Эффект применяется при «Обрезать» и виден только в итоговом файле (живого
        превью нет — мозаика считается при перекодировке)."""
        if on:
            is_image = bool(getattr(self, "is_still_image", False))
            dlg = _api._PixelizeDialog(self._pixelize_steps, self._pixelize_block, self,
                                  image_mode=is_image, duration=self._still_duration,
                                  fps=self._still_fps)
            if dlg.exec():
                self._pixelize_steps, self._pixelize_block = dlg.values()
                self._pixelize_active = True
                if is_image:
                    self._still_duration, self._still_fps = dlg.image_values()
                    # Длительность ролика обновилась — отражаем в таймингах.
                    self.duration = float(self._still_duration)
                    self.current_out = self.duration
                    try:
                        self.lbl_duration.setText(_api.s_to_time(self.duration))
                        self._update_total_time()
                    except Exception:
                        pass
                try:
                    if self.main is not None and hasattr(self.main, "log"):
                        seq = _api._pixelize_block_sequence(self._pixelize_block, self._pixelize_steps)
                        extra = (f", {self._still_duration}с @ {self._still_fps}fps"
                                 if is_image else "")
                        self.main.log(
                            f"Пикселизация задана ({self._pixelize_steps} шаг(ов), "
                            f"старт {self._pixelize_block}px{extra}) — применится при "
                            f"«Обрезать». Блоки: "
                            + " → ".join(f"{b}px" if b > 1 else "чётко" for b in seq))
                except Exception:
                    pass
            else:
                # Отмена диалога — снимаем чек, не трогая прежнее состояние.
                self._pixelize_active = False
                b = self.btn_pixelize
                b.blockSignals(True); b.setChecked(False); b.blockSignals(False)
        else:
            self._pixelize_active = False
            try:
                if self.main is not None and hasattr(self.main, "log"):
                    self.main.log("Пикселизация отключена.")
            except Exception:
                pass
        self._sync_pixelize_icon()

    def _sync_pixelize_icon(self):
        """Цвет значка кнопки пикселизации по состоянию: тёмный на акцентной
        заливке (включено), обычный — выключено. Иначе светлый значок на светло-
        голубом фоне «included» сливался."""
        b = getattr(self, "btn_pixelize", None)
        if b is None:
            return
        try:
            b.setIcon(_api.get_icon('fa5s.th', color='#11111b' if b.isChecked() else _api.C['text']))
        except Exception:
            pass

    def _video_pixelize_filter(self, dur, offset=0.0):
        """Цепочка ffmpeg-фильтров «проявление из пикселей» для клипа длительностью
        `dur` секунд, либо None если эффект выключен/нечего применять. Делит клип на
        N равных окон; в каждом окне `pixelize` с уменьшающимся блоком (через
        enable='between(t,…)'), пока картинка не станет чёткой.

        ВАЖНО про `offset`: фильтрграф видит ВРЕМЯ ИСХОДНИКА, а не время обрезанного
        клипа (setpts на таймлайн `enable` не влияет — проверено). Поэтому окна
        смещаются на `offset` — время фильтрграфа, на котором начинается клип:
          • выходной seek (-ss после -i): offset = начало реза in_s;
          • входной seek (-ss до -i):       offset = 0;
          • входной pre-seek + выходной -ss: offset = величина выходного -ss.
        """
        if not getattr(self, "_pixelize_active", False) or dur is None or dur <= 0:
            return None
        # Сама цепочка собирается общим модулем pixelize (им же пользуется
        # генератор аниме-паков) — эффект в обеих вкладках один и тот же.
        return _api._pixelize_filter(dur,
                                max(1, int(getattr(self, "_pixelize_steps", 6))),
                                max(2, int(getattr(self, "_pixelize_block", 64))),
                                offset)

    def _on_crop_applied(self):
        """Холст: нажата «Применить» — снимаем чек с кнопки (режим правки закрыт),
        рамка остаётся «вооружённой» для «Обрезать»."""
        b = getattr(self, "btn_crop_frame", None)
        if b is not None and b.isChecked():
            b.blockSignals(True); b.setChecked(False); b.blockSignals(False)
        armed = self._video_crop_filter() is not None
        try:
            if self.main is not None and hasattr(self.main, "log"):
                self.main.log("Кадрирование задано — применится при «Обрезать»."
                              if armed else "Кадрирование снято (рамка = весь кадр).")
        except Exception:
            pass

    def _on_crop_cancelled(self):
        """Холст: нажата «Отмена»/Esc — снимаем чек с кнопки, рамка сброшена."""
        b = getattr(self, "btn_crop_frame", None)
        if b is not None and b.isChecked():
            b.blockSignals(True); b.setChecked(False); b.blockSignals(False)

    def _video_crop_filter(self):
        """ffmpeg-фильтр crop=… по рамке кадрирования на холсте, либо None, если
        рамка не задана/слишком мелкая. Координаты — выражения от iw/ih (не
        зависят от прокси-превью), размеры/смещения чётные (требование кодеков)."""
        vw = getattr(self, "video_widget", None)
        if not isinstance(vw, _api.VideoCanvas):
            return None
        n = vw.crop_norm()
        if n is None:
            return None
        x = max(0.0, min(1.0, n.left()))
        y = max(0.0, min(1.0, n.top()))
        w = max(0.0, min(1.0 - x, n.width()))
        h = max(0.0, min(1.0 - y, n.height()))
        if w < 0.02 or h < 0.02:
            return None
        return (f"crop=trunc(iw*{w:.6f}/2)*2:trunc(ih*{h:.6f}/2)*2:"
                f"trunc(iw*{x:.6f}/2)*2:trunc(ih*{y:.6f}/2)*2")

    # ── Наложение картинки поверх видео ──────────────────────────────────────
    #
    # Слои живут на холсте (VideoCanvas), правятся мышью, а в файл попадают
    # фильтром overlay=… при «Обрезать». Порядок фильтров: НАКЛАДКИ → кадрирование
    # → субтитры → пикселизация (см. edit_tab_overlay.overlay_filter_graph) —
    # ровно как это видно в плеере.
    def _overlay_frame_size(self):
        """Размер кадра в пикселях ИСХОДНИКА (в плеере может идти прокси меньшего
        разрешения — по нему координаты считать нельзя). Для картинки-исходника
        берём её собственный размер, для видео — ffprobe, а если не вышло —
        размер кадра на холсте."""
        if getattr(self, "is_still_image", False) and self.still_image_path:
            img = _api.QImage(str(self.still_image_path))
            if not img.isNull():
                return (img.width(), img.height())
        src = self.actual_source_file or self.filepath
        if src and _api.os.path.exists(str(src)):
            w, h = _api.probe_frame_size(str(src))
            if w > 0 and h > 0:
                return (w, h)
        vw = getattr(self, "video_widget", None)
        if isinstance(vw, _api.VideoCanvas):
            img = vw.current_frame_image()
            if img is not None and not img.isNull():
                return (img.width(), img.height())
        return (0, 0)

    def image_overlays(self):
        """Список наложенных картинок (пустой, если холст без них)."""
        vw = getattr(self, "video_widget", None)
        if not isinstance(vw, _api.VideoCanvas):
            return []
        return vw.image_overlays()

    def has_image_overlays(self):
        return bool(self.image_overlays())

    def add_image_overlay(self):
        """Кнопка «Наложить картинку»: выбор файла → новый слой поверх кадра."""
        vw = getattr(self, "video_widget", None)
        if not isinstance(vw, _api.VideoCanvas):
            _api.msgbox_information(
                self, "Недоступно",
                "Наложение картинки работает только с собственным холстом видео "
                "(Настройки → Монтаж → метод субтитров «в кадр»).")
            return
        if not (getattr(self, "video_stream_index", None) is not None
                or getattr(self, "is_still_image", False)):
            _api.msgbox_information(self, "Нет видео",
                               "Сначала загрузите видео или картинку.")
            return
        path, _ = _api.QFileDialog.getOpenFileName(
            self, "Выберите картинку для наложения", "",
            "Изображения (*.png *.jpg *.jpeg *.webp *.bmp *.gif *.avif);;"
            "Все файлы (*.*)")
        if not path:
            return
        img = _api.load_overlay_image(path)
        if img is None:
            _api.msgbox_warning(self, "Не удалось открыть",
                           "Файл не похож на картинку или формат не поддерживается.")
            return
        fw, fh = self._overlay_frame_size()
        if fw <= 0 or fh <= 0:
            _api.msgbox_warning(self, "Не удалось определить кадр",
                           "Не получилось узнать размер кадра видео — "
                           "перезагрузите файл и попробуйте снова.")
            return
        vw.add_image_overlay(_api.ImageOverlay(path, img, fw, fh))
        self._refresh_overlay_panel()
        try:
            if self.main is not None and hasattr(self.main, "log"):
                self.main.log(
                    f"Наложена картинка {_api.os.path.basename(path)}: двигайте мышью, "
                    "тяните за уголки, крутите за кружок сверху (Shift — шаг 15°), "
                    "Ctrl+стрелки — точная сдвижка, Delete — убрать. "
                    "Вшивается при «Обрезать» (перекодировка).")
        except Exception:
            pass

    def _refresh_overlay_panel(self, current=None):
        """Пересобирает список слоёв в боковой панели по состоянию холста."""
        panel = getattr(self, "overlay_panel", None)
        if panel is None:
            return
        vw = getattr(self, "video_widget", None)
        items = vw.image_overlays() if isinstance(vw, _api.VideoCanvas) else []
        if current is None:
            current = (vw.selected_overlay_index()
                       if isinstance(vw, _api.VideoCanvas) else -1)
        panel.refresh(items, int(current))

    def _on_overlays_changed(self):
        """Холст: слой подвинули/растянули/удалили — обновляем список."""
        self._refresh_overlay_panel()

    def _on_overlay_picked(self, idx):
        """Холст: слой выбрали мышью — подсвечиваем строку в списке."""
        panel = getattr(self, "overlay_panel", None)
        if panel is not None:
            panel.list.setCurrentRow(int(idx))

    def _on_overlay_selected(self, idx):
        """Список: выбрана строка — тот же слой выделяем на холсте."""
        vw = getattr(self, "video_widget", None)
        if isinstance(vw, _api.VideoCanvas) and idx >= 0:
            vw.set_selected_overlay(int(idx))
            vw.set_overlay_edit(True)

    def _delete_image_overlay(self, idx):
        vw = getattr(self, "video_widget", None)
        if isinstance(vw, _api.VideoCanvas):
            vw.remove_image_overlay(int(idx))
            self._refresh_overlay_panel()

    def _set_overlay_opacity(self, idx, value):
        items = self.image_overlays()
        if 0 <= idx < len(items):
            items[idx].opacity = max(0.05, min(1.0, float(value)))
            self.video_widget.update()

    def _reset_image_overlay(self, idx):
        """Сброс слоя к исходному виду: без поворота, без обрезки, стандартный
        размер/место (удобно, когда картинку «закрутили» и потеряли)."""
        items = self.image_overlays()
        if not (0 <= idx < len(items)):
            return
        it = items[idx]
        it.angle = 0.0
        it.set_crop(_api.QRectF(0.0, 0.0, 1.0, 1.0), keep_width=False)
        cw, ch = it.cropped_size()
        it.rect = _api.fit_rect_norm(cw, ch, it.frame_w, it.frame_h)
        self.video_widget.update()
        self._refresh_overlay_panel(idx)

    def _crop_image_overlay(self, idx):
        """Кадрирование самой картинки (отдельное окно с рамкой обрезки)."""
        items = self.image_overlays()
        if not (0 <= idx < len(items)):
            return
        it = items[idx]
        dlg = _api.OverlayCropDialog(it, self)
        if dlg.exec() != _api.QDialog.DialogCode.Accepted:
            return
        if it.set_crop(dlg.crop_norm()):
            self.video_widget.update()
            self._refresh_overlay_panel(idx)

    def _clear_image_overlays(self):
        """Убирает все слои (новый файл начинается чистым, как и пикселизация)."""
        vw = getattr(self, "video_widget", None)
        if isinstance(vw, _api.VideoCanvas):
            vw.clear_image_overlays()
        self._refresh_overlay_panel()

    def _render_export_overlays(self):
        """Готовит PNG всех накладок под размер ИСХОДНОГО кадра. Возвращает
        список (путь, x, y) для overlay_filter_graph (пустой — накладок нет).

        PNG кладутся во временную папку вкладки и переписываются на каждом
        экспорте; папку убирает shutdown()."""
        items = self.image_overlays()
        if not items:
            return []
        fw, fh = self._overlay_frame_size()
        if fw <= 0 or fh <= 0:
            return []
        d = getattr(self, "_overlay_tmp_dir", None)
        if not d or not _api.os.path.isdir(d):
            d = _api.tempfile.mkdtemp(prefix="sihyx_overlay_")
            self._overlay_tmp_dir = d
        return _api.render_overlays(items, d, fw, fh)

    def _paint_overlays_on_image(self, img):
        """Впечатывает наложенные картинки в готовый кадр (QImage) — тем же
        порядком и в тех же долях, что и экспорт. Возвращает новый QImage (или
        исходный, если накладок нет)."""
        items = self.image_overlays()
        if not items or img is None or img.isNull():
            return img
        out = img.convertToFormat(_api.QImage.Format.Format_ARGB32)
        p = _api.QPainter(out)
        try:
            for it in items:
                ovl, x, y = it.rendered(out.width(), out.height())
                if ovl is not None:
                    p.drawImage(int(x), int(y), ovl)
        finally:
            p.end()
        return out

    def _static_overlays_bgra(self, frame_w, frame_h):
        """Наложенные картинки в виде (BGRA, x, y) под размер кадра — для путей,
        которые правят кадры сами (TrackOverlayWorker), а не через -vf."""
        out = []
        for it in self.image_overlays():
            img, x, y = it.rendered(frame_w, frame_h)
            if img is None:
                continue
            bgra = _api.qimage_to_bgra(img)
            if bgra is not None:
                out.append((bgra, int(x), int(y)))
        return out

    def _wrap_vf(self, chain, src=None):
        """Оборачивает готовую цепочку -vf графом с накладками (если они есть).
        `chain` — строка фильтров Монтажа (может быть пустой), `src` — файл, из
        которого идёт кодирование (по умолчанию открытый в Монтаже).

        Формат работы overlay берём ПО ИСХОДНИКУ (см. overlay_chroma_format):
        при `format=auto` граф с RGBA-накладкой уводил ВЕСЬ кадр в RGB, libx264
        писал gbrp — и итог получался кислотно-зелёным/малиновым."""
        rendered = self._render_export_overlays()
        if not rendered:
            return chain or ""
        return _api.overlay_filter_graph(chain or "", rendered,
                                    self._escape_filter_path,
                                    pix_fmt=self._overlay_pix_fmt(src))

    def _overlay_pix_fmt(self, src=None):
        """Значение `format=` для overlay под pix_fmt исходника (кэшируется на
        файл: ffprobe на каждый экспорт тут ни к чему)."""
        path = str(src or getattr(self, "actual_source_file", "") or "")
        if not path or not _api.os.path.exists(path):
            return "yuv420"
        cache = getattr(self, "_ovl_fmt_cache", None)
        if cache is None:
            cache = self._ovl_fmt_cache = {}
        stamp = self._file_cache_stamp(path)
        key = (path, stamp)
        got = cache.get(key)
        if got is None:
            got = cache[key] = _api.overlay_chroma_format(_api.get_pix_fmt(path))
        return got

    @staticmethod
    def _apply_frame_crop(img, n):
        """Обрезает QImage по нормализованной рамке n (QRectF 0..1). Координаты
        зажимаются в границы изображения."""
        if img is None or img.isNull() or n is None:
            return img
        w, h = img.width(), img.height()
        x = max(0, min(w - 1, int(round(n.left() * w))))
        y = max(0, min(h - 1, int(round(n.top() * h))))
        cw = max(1, min(w - x, int(round(n.width() * w))))
        ch = max(1, min(h - y, int(round(n.height() * h))))
        return img.copy(x, y, cw, ch)

    # ── Сохранение текущего кадра ────────────────────────────────────────────
    def save_frame(self):
        """Сохраняет кадр на текущей позиции воспроизведения в PNG (полное
        разрешение, извлекается из исходника через ffmpeg). Без диалога —
        файл сразу кладётся в папку сохранения (или рядом с исходником)."""
        src = self.actual_source_file or self.filepath
        if not src or not _api.os.path.exists(src) or self.duration <= 0:
            return
        # Рамка кадрирования (если задана на холсте) — сохраняем только её.
        crop_n = None
        _vw = getattr(self, "video_widget", None)
        if isinstance(_vw, _api.VideoCanvas):
            crop_n = _vw.crop_norm()
        # Время кадра, который на экране (см. _clock_pos_s) — им же назван файл,
        # и по нему же идёт резервное извлечение через ffmpeg.
        pos = max(0.0, self._clock_pos_s())
        base = _api.os.path.splitext(_api.os.path.basename(src))[0]
        stamp = _api.s_to_time(pos).replace(':', '-').replace('.', '_')
        save_dir = (self.export_dir if (self.export_dir and _api.os.path.isdir(self.export_dir))
                    else _api.os.path.dirname(src))
        fname = _api._unique_output(_api.os.path.join(save_dir, f"{base}_{stamp}.png"))
        ok = False
        # 1) В painted-режиме (VideoCanvas) сохраняем РОВНО тот кадр, что показан
        #    на холсте — без пере-извлечения через ffmpeg. Иначе seek по позиции
        #    на HEVC отдавал следующий кадр (out_time приходился между кадрами →
        #    ffmpeg брал первый PTS ≥ позиции = следующий).
        # (Если активен превью-прокси, кадр на холсте уменьшён — тогда лучше
        #  полноразмерный кадр из оригинала через ffmpeg, см. ниже.)
        if isinstance(self.video_widget, _api.VideoCanvas) and not self.is_proxy_active:
            try:
                img = self.video_widget.current_frame_image()
                if img is not None and not img.isNull():
                    img = self._paint_overlays_on_image(img)
                    if crop_n is not None:
                        img = self._apply_frame_crop(img, crop_n)
                    ok = bool(img.save(fname, "PNG"))
            except Exception:
                ok = False
        # 2) Резерв (overlay-режим / нет кадра на холсте): извлекаем через ffmpeg.
        #    -ss перед -i точен, но позиция может прийтись между кадрами; вычитаем
        #    половину интервала кадра, чтобы попасть в текущий, а не следующий.
        if not ok:
            # Целимся четвертью кадра НИЖЕ его pts: ffmpeg отдаёт первый кадр с
            # pts ≥ -ss, значит это ровно наш кадр (см. FrameGrid.seek_of).
            if self._grid.valid:
                seek = self._grid.seek_of(self._grid.index_at(pos))
            else:
                seek = max(0.0, pos - 0.02)
            cmd = [_api.FFMPEG, "-y", "-ss", f"{seek:.3f}", "-i", src,
                   "-frames:v", "1", "-update", "1", fname]
            kw = {}
            if _api.os.name == 'nt':
                kw['creationflags'] = _api.CREATE_NO_WINDOW
            try:
                r = _api.subprocess.run(cmd, stdout=_api.subprocess.DEVNULL,
                                   stderr=_api.subprocess.DEVNULL, timeout=60, **kw)
                ok = (r.returncode == 0 and _api.os.path.exists(fname)
                      and _api.os.path.getsize(fname) > 0)
            except Exception:
                ok = False
            # Полноразмерный кадр из ffmpeg обрезаем под рамку кадрирования.
            if ok and (crop_n is not None or self.has_image_overlays()):
                try:
                    _qi = _api.QImage(fname)
                    if not _qi.isNull():
                        _qi = self._paint_overlays_on_image(_qi)
                        if crop_n is not None:
                            _qi = self._apply_frame_crop(_qi, crop_n)
                        _qi.save(fname, "PNG")
                except Exception:
                    pass
        msg = (f"🖼 Кадр сохранён: {_api.os.path.basename(fname)}" if ok
               else "Не удалось сохранить кадр")
        try:
            if self.main is not None and hasattr(self.main, "log"):
                self.main.log(msg)
        except Exception:
            pass
        try:
            gp = self.btn_save_frame.mapToGlobal(
                _api.QPoint(0, -self.btn_save_frame.height()))
            _api.QToolTip.showText(gp, msg, self.btn_save_frame)
        except Exception:
            pass

    # ── Удаление объекта с видео (LaMa, покадрово) ───────────────────────────
    def _ensure_inpainter(self):
        """Лениво создаёт движок LaMa (ТОТ ЖЕ, что в фоторедакторе) и
        переиспользует его между запусками. Сессия живёт в дочернем процессе
        (см. lama_inpaint.py), поэтому загрузка 200-МБ модели не морозит UI."""
        inp = getattr(self, "_inpainter", None)
        if inp is not None:
            return inp
        try:
            from lama_inpaint import LaMaProcessInpainter
        except Exception:
            return None
        self._inpainter = LaMaProcessInpainter()
        return self._inpainter

    def _grab_source_frame_bgr(self, src):
        """Извлекает кадр оригинала на текущей позиции воспроизведения в ПОЛНОМ
        разрешении (через ffmpeg) и возвращает numpy BGR. Способ совпадает с тем,
        как VideoInpaintWorker позже извлечёт все кадры, поэтому нарисованная маска
        попадает в кадры попиксельно (то же разрешение и дисплейная ориентация)."""
        pos = max(0.0, self._clock_pos_s())
        # -ss перед -i точен, но позиция может прийтись между кадрами — целимся
        # четвертью кадра ниже pts нужного кадра (см. FrameGrid.seek_of), иначе
        # ffmpeg отдаст СЛЕДУЮЩИЙ кадр и маска ляжет не на тот кадр.
        if self._grid.valid:
            seek = self._grid.seek_of(self._grid.index_at(pos))
        else:
            seek = max(0.0, pos - 0.02)
        tmp = _api.os.path.join(_api.tempfile.gettempdir(),
                           f"sihyx_vmask_{_api.os.getpid()}_{int(_api.time.time() * 1000)}.png")
        cmd = [_api.FFMPEG, "-y", "-ss", f"{seek:.3f}", "-i", src,
               "-frames:v", "1", "-update", "1", tmp]
        kw = {}
        if _api.os.name == 'nt':
            kw['creationflags'] = _api.CREATE_NO_WINDOW
        try:
            r = _api.subprocess.run(cmd, stdout=_api.subprocess.DEVNULL,
                               stderr=_api.subprocess.DEVNULL, timeout=60, **kw)
            if r.returncode != 0 or not _api.os.path.exists(tmp):
                return None
            from lama_inpaint import load_bgr
            return load_bgr(tmp)
        except Exception:
            return None
        finally:
            try:
                if _api.os.path.exists(tmp):
                    _api.os.remove(tmp)
            except Exception:
                pass

    def remove_object_from_video(self):
        """Удаляет объект (водяной знак/эмодзи/логотип) со ВСЕГО видео: пользователь
        закрашивает объект кистью на текущем кадре, затем ТЕМ ЖЕ движком LaMa, что и
        в фоторедакторе, объект убирается с каждого кадра, и видео собирается
        обратно с исходными FPS/разрешением/ориентацией/аудио. Тяжёлая работа — в
        отдельном потоке (VideoInpaintWorker) с возможностью отмены.

        Поведение для одиночного изображения НЕ меняется: эта кнопка активна только
        при загруженном видео (см. _update_media_buttons)."""
        # Пока идёт обработка — кнопка работает как «Отмена».
        if getattr(self, "_vinp_running", False):
            self._cancel_video_inpaint()
            return

        src = self.actual_source_file or self.filepath
        if not src or not _api.os.path.exists(str(src)) or self.duration <= 0:
            return
        if getattr(self, "video_stream_index", None) is None:
            _api.msgbox_information(
                self, "Только для видео",
                "Удаление объекта доступно для видео. Для одиночного изображения "
                "используйте вкладку «Фото».")
            return
        src = str(src)

        # Доступность движка LaMa (numpy/opencv/модель).
        inp = self._ensure_inpainter()
        if inp is None or not inp.is_available():
            _api.msgbox_warning(
                self, "Удаление объекта недоступно",
                "Не найдены необходимые компоненты (numpy/opencv или файл модели "
                "LaMa). Удаление объекта с видео недоступно в этой сборке.")
            return

        # Кадр для рисования маски — из оригинала на текущей позиции, полный размер.
        frame = self._grab_source_frame_bgr(src)
        if frame is None:
            _api.msgbox_warning(
                self, "Ошибка",
                "Не удалось получить кадр видео для рисования маски.")
            return

        dlg = _api._VideoMaskDialog(frame, self)
        if dlg.exec() != _api.QDialog.DialogCode.Accepted:
            return
        mask = dlg.get_mask()
        if mask is None or int(mask.max()) == 0:
            return

        # Имя результата — в папке сохранения/рядом с исходником; контейнер
        # исходника, если он поддерживает H.264, иначе .mp4 (h264 в webm недопустим).
        base = _api.Path(src)
        out_dir = (_api.Path(self.export_dir)
                   if (self.export_dir and _api.os.path.isdir(self.export_dir))
                   else base.parent)
        suffix = base.suffix.lower()
        if suffix not in (".mp4", ".mkv", ".mov", ".m4v"):
            suffix = ".mp4"
        out_path = str(out_dir / f"{base.stem}_без_объекта{suffix}")
        if _api.os.path.exists(out_path):
            out_path = _api._unique_output(out_path)

        # Пункт «Нет» в списке дорожек — результат без звука.
        has_audio = (getattr(self, "audio_stream_index", None) is not None
                     and not bool(getattr(self, "audio_disabled", False)))
        venc = self._video_encoder_args(hardsub=False)

        # Запуск фоновой обработки + перевод кнопки в режим «Отмена».
        self._vinp_running = True
        self.btn_cut.setEnabled(False)
        self._set_remove_btn_cancel(True)
        self._report_progress(-1, "Удаление объекта…")
        self._set_cut_status("Удаление объекта… подготовка",
                             icon='fa5s.hourglass-half')
        self.log_label.setText("Удаление объекта с видео…")

        self._vinp_worker = _api.VideoInpaintWorker(
            inp, src, mask, self.fps, out_path, venc, has_audio)
        self._vinp_worker.progress.connect(self._on_vinp_progress)
        self._vinp_worker.done.connect(self._on_vinp_done)
        self._vinp_worker.failed.connect(self._on_vinp_failed)
        self._vinp_worker.start()

    def _set_remove_btn_cancel(self, cancel_mode):
        """Переключает кнопку «Удалить объект» между обычным видом и «Отмена» на
        время обработки видео."""
        b = getattr(self, "btn_remove_object", None)
        if b is None:
            return
        if cancel_mode:
            b.setIcon(_api.get_icon('fa5s.times'))
            b.setToolTip("Отменить удаление объекта")
            b.setEnabled(True)
        else:
            b.setIcon(_api.get_icon('fa5s.magic'))
            b.setToolTip(
                "Удалить объект с видео (водяной знак, эмодзи, логотип): закрасьте "
                "его кистью на кадре — нейросеть LaMa уберёт его со всех кадров")

    def _cancel_video_inpaint(self):
        """Просит фоновый воркер прерваться (временные файлы он уберёт сам)."""
        w = getattr(self, "_vinp_worker", None)
        if w is not None and w.isRunning():
            self._set_cut_status("Отмена…", icon='fa5s.hourglass-half')
            if getattr(self, "btn_remove_object", None) is not None:
                self.btn_remove_object.setEnabled(False)
            w.cancel()

    def _on_vinp_progress(self, pct, text):
        self._report_progress(pct, text)
        self._set_cut_status(text, icon='fa5s.magic' if pct >= 0
                             else 'fa5s.hourglass-half')

    def _finish_video_inpaint(self):
        """Общая уборка состояния UI после завершения/отмены/ошибки обработки."""
        self._vinp_running = False
        self._vinp_worker = None
        self._set_remove_btn_cancel(False)
        self.btn_cut.setEnabled(True)
        self._update_media_buttons()

    def _on_vinp_done(self, final_path):
        self._finish_video_inpaint()
        try:
            if self.main is not None and hasattr(self.main, "log"):
                self.main.log(f"Объект удалён с видео: {final_path}")
        except Exception:
            pass
        # Переиспользуем стандартное завершение «Монтажа» (статус «Готово»,
        # обновление верхней ленты файлов и т.п.).
        self._progress_result_path = final_path
        self.on_ffmpeg_finished(True, "Готово")

    def _on_vinp_failed(self, message):
        self._finish_video_inpaint()
        self.on_ffmpeg_finished(False, message)

    # ── Привязка текста/картинки к движущемуся объекту ───────────────────────
    def track_object_overlay(self):
        """Привязывает текст или картинку к ДВИЖУЩЕМУСЯ объекту: пользователь
        обводит объект рамкой на текущем кадре, трекер DyHiT (нейросеть, ONNX;
        без модели — запасной CSRT из OpenCV) находит его на каждом следующем
        кадре, и накладка едет вместе с ним. Результат — новый файл; исходник не
        трогаем. Вся тяжёлая работа в TrackOverlayWorker, с отменой.

        Доступно только для видео: у одиночной картинки нечему двигаться."""
        # Пока идёт обработка — кнопка работает как «Отмена».
        if getattr(self, "_trk_running", False):
            self._cancel_track_overlay()
            return
        # Накладка уже висит в плеере — второе нажатие её снимает (отдельной
        # кнопки «Отмена» на холсте нет, экспортом занимается «Обрезать»).
        if self.has_track_preview():
            self._clear_track_preview()
            return
        self._clear_track_preview()

        src = self.actual_source_file or self.filepath
        if not src or not _api.os.path.exists(str(src)) or self.duration <= 0:
            return
        if getattr(self, "video_stream_index", None) is None:
            _api.msgbox_information(
                self, "Только для видео",
                "Привязка к объекту работает с видео: нужно движение, за которым "
                "можно следить.")
            return
        src = str(src)

        try:
            import dyhit_tracker
        except Exception as e:
            _api.msgbox_warning(
                self, "Отслеживание недоступно",
                f"Не удалось загрузить движок отслеживания (нужны numpy/opencv):\n{e}")
            return
        if not (dyhit_tracker.dyhit_available()
                or dyhit_tracker.opencv_tracker_available()):
            _api.msgbox_warning(
                self, "Отслеживание недоступно",
                "Не найден ни один трекер. Для нейросетевого варианта положите "
                "файл модели DyHiT/HiT (.onnx) в папку models — ожидается "
                f"{dyhit_tracker.expected_model_path()} — либо установите "
                "opencv-python с трекерами (CSRT).")
            return

        # Кадр для выбора области — из оригинала на текущей позиции, полный размер
        # (тот же способ, что у маски удаления объекта, поэтому рамка попадает в
        # кадры воркера попиксельно).
        frame = self._grab_source_frame_bgr(src)
        if frame is None:
            _api.msgbox_warning(self, "Ошибка",
                           "Не удалось получить кадр видео для выбора объекта.")
            return

        fps = float(self.fps) if getattr(self, "fps", None) else 25.0
        pos = max(0.0, self._ui_time_s())
        start_s = max(0.0, pos - 0.5 / fps)
        zone_end = float(self.current_out) if getattr(self, "current_out", 0) else 0.0

        dlg = _api._TrackAttachDialog(frame, self, start_s=start_s,
                                 end_s=float(self.duration), zone_end_s=zone_end)
        if dlg.exec() != _api.QDialog.DialogCode.Accepted:
            return
        spec = dlg.values()
        if not spec.get("box") or spec.get("overlay_bgra") is None:
            return

        h, w = frame.shape[:2]
        self._trk_spec = dict(spec)
        self._trk_spec.update({"src": src, "fps": fps, "src_w": w, "src_h": h})

        # Шаг 1 — только путь объекта, без кодирования: он считается в разы
        # быстрее полного рендера, и по нему сразу показываем предпросмотр.
        self._trk_running = True
        self._set_track_export_busy(True)
        self._report_progress(-1, "Привязка к объекту…")
        self._set_cut_status("Привязка к объекту… подготовка",
                             icon='fa5s.hourglass-half')
        self.log_label.setText("Отслеживание объекта на видео…")

        self._trk_worker = _api.TrackPathWorker(
            src, fps, (w, h), spec["box"], spec["start_s"], spec["end_s"],
            smooth=spec["smooth"])
        self._trk_worker.progress.connect(self._on_trk_progress)
        self._trk_worker.done.connect(self._on_track_path_ready)
        self._trk_worker.failed.connect(self._on_trk_failed)
        self._trk_worker.start()

    def _on_track_path_ready(self, boxes):
        """Путь объекта посчитан — показываем накладку прямо в плеере. Ничего
        никуда не записано: в файл накладка попадёт обычным экспортом, то есть
        кнопкой «Обрезать» (см. start_cut)."""
        self._finish_track_overlay()
        spec = getattr(self, "_trk_spec", None)
        if not spec or not boxes:
            return
        spec["boxes"] = boxes
        canvas = self.video_widget
        if not isinstance(canvas, _api.VideoCanvas):
            # Классический QVideoWidget не умеет рисовать поверх кадра — там
            # предпросмотра нет, сразу рендерим (как раньше).
            self._render_track_overlay()
            return

        from photo_tab import np_bgra_to_qimage
        qimg = np_bgra_to_qimage(spec["overlay_bgra"])
        canvas.set_track_preview({
            "overlay": qimg, "boxes": boxes,
            "src_w": spec["src_w"], "src_h": spec["src_h"], "fps": spec["fps"],
            "start_s": spec["start_s"], "end_s": spec["end_s"],
            "anchor": spec["anchor"], "off": (spec["off_x"], spec["off_y"]),
            "scale_with_box": spec["scale_with_box"],
        })
        canvas.set_track_time(max(0.0, self._ui_time_s()))
        self._connect_track_preview_signals(canvas)
        self._set_cut_status("Накладка привязана — сохранит её «Обрезать»",
                             icon='fa5s.crosshairs')
        self.log_label.setText(
            "Смотрите, как накладка едет за объектом. «Обрезать» сохранит видео "
            "с накладкой, кнопка привязки — уберёт её.")

    def _connect_track_preview_signals(self, canvas):
        """Подключает сигналы предпросмотра ровно один раз на КАЖДЫЙ холст (при
        смене способа показа видео в настройках виджет пересоздаётся)."""
        if getattr(self, "_trk_signals_canvas", None) is canvas:
            return
        canvas.trackCancelled.connect(self._clear_track_preview)
        self._trk_signals_canvas = canvas

    def has_track_preview(self):
        """Есть ли посчитанная накладка, ждущая экспорта («Обрезать»)."""
        spec = getattr(self, "_trk_spec", None)
        return bool(spec and spec.get("boxes"))

    def _clear_track_preview(self):
        """Убирает накладку из плеера (Esc, повторное нажатие кнопки привязки,
        новый файл)."""
        canvas = getattr(self, "video_widget", None)
        if isinstance(canvas, _api.VideoCanvas) and canvas.has_track_preview():
            canvas.set_track_preview(None)
            self._set_cut_status("")
            self.log_label.setText("Готово")
        self._trk_spec = None

    def _render_track_overlay(self, trim_in=None, trim_out=None):
        """Экспорт видео с накладкой по УЖЕ посчитанной траектории (отслеживать
        заново нечего, этап только кодирующий). trim_in/trim_out — выделенный в
        Монтаже отрезок: «Обрезать» с активной накладкой и режет, и вшивает."""
        spec = getattr(self, "_trk_spec", None)
        if not spec or getattr(self, "_trk_running", False):
            return
        src = spec["src"]
        if not _api.os.path.exists(src):
            return
        base = _api.Path(src)
        out_dir = (_api.Path(self.export_dir)
                   if (self.export_dir and _api.os.path.isdir(self.export_dir))
                   else base.parent)
        suffix = base.suffix.lower()
        if suffix not in (".mp4", ".mkv", ".mov", ".m4v"):
            suffix = ".mp4"
        out_path = str(out_dir / f"{base.stem}_привязка{suffix}")
        if _api.os.path.exists(out_path):
            out_path = _api._unique_output(out_path)

        # Пункт «Нет» в списке дорожек — результат без звука.
        has_audio = (getattr(self, "audio_stream_index", None) is not None
                     and not bool(getattr(self, "audio_disabled", False)))
        # hardsub-профиль: у текста и краёв картинки резкие границы, на «fast»/
        # высоком CRF они мылятся — берём тот же профиль, что при вшивании субтитров.
        venc = self._video_encoder_args(hardsub=True)
        # Экспорт накладки идёт своим путём (кадры собираются в python), поэтому
        # фильтры обычной обрезки к нему не применяются — честно предупреждаем,
        # а не делаем вид, что кадрирование/пикселизация учтены.
        if (self._video_crop_filter() is not None
                or getattr(self, "_pixelize_active", False)):
            _api.msgbox_information(
                self, "Только накладка",
                "Сейчас в файл уйдёт видео с привязанной накладкой — "
                "кадрирование и пикселизация в этот экспорт не попадут. "
                "Сначала сохраните их обычной обрезкой, а привязку сделайте "
                "уже по готовому файлу.")

        self._trk_running = True
        self._set_track_export_busy(True)
        self._report_progress(-1, "Привязка к объекту…")
        self._set_cut_status("Привязка к объекту… подготовка",
                             icon='fa5s.hourglass-half')
        self.log_label.setText("Наложение на кадры…")

        self._trk_worker = _api.TrackOverlayWorker(
            src, out_path, venc, has_audio, spec["fps"],
            (spec["src_w"], spec["src_h"]), float(self.duration),
            spec["box"], spec["start_s"], spec["end_s"], spec["overlay_bgra"],
            anchor=spec["anchor"], off_x=spec["off_x"], off_y=spec["off_y"],
            scale_with_box=spec["scale_with_box"], smooth=spec["smooth"],
            boxes=spec.get("boxes"), trim_in=trim_in, trim_out=trim_out,
            static_overlays=self._static_overlays_bgra(spec["src_w"],
                                                       spec["src_h"]))
        self._trk_worker.progress.connect(self._on_trk_progress)
        self._trk_worker.done.connect(self._on_trk_done)
        self._trk_worker.failed.connect(self._on_trk_failed)
        self._trk_worker.start()

    def _cancel_track_overlay(self):
        """Просит фоновый воркер прерваться (временные файлы он уберёт сам)."""
        w = getattr(self, "_trk_worker", None)
        if w is not None and w.isRunning():
            self._set_cut_status("Отмена…", icon='fa5s.hourglass-half')
            if getattr(self, "btn_track_object", None) is not None:
                self.btn_track_object.setEnabled(False)
            w.cancel()

    def _on_trk_progress(self, pct, text):
        self._report_progress(pct, text)
        self._set_cut_status(text, icon='fa5s.crosshairs' if pct >= 0
                             else 'fa5s.hourglass-half')

    def _set_track_export_busy(self, busy):
        """На время отслеживания/рендера «Обрезать» превращается в «Отмена» (как
        при обычном экспорте), а кнопка привязки выключается."""
        b = getattr(self, "btn_track_object", None)
        if b is not None:
            b.setEnabled(not busy)
        self._set_cut_btn_cancel(busy, self._cancel_track_overlay)

    def _finish_track_overlay(self):
        self._trk_running = False
        self._trk_worker = None
        self._set_track_export_busy(False)
        self._update_media_buttons()

    def _on_trk_done(self, final_path):
        self._finish_track_overlay()
        # Файл готов — накладка-предпросмотр больше не нужна.
        self._clear_track_preview()
        try:
            if self.main is not None and hasattr(self.main, "log"):
                self.main.log(f"Накладка привязана к объекту: {final_path}")
        except Exception:
            pass
        self._progress_result_path = final_path
        self.on_ffmpeg_finished(True, "Готово")

    def _on_trk_failed(self, message):
        self._finish_track_overlay()
        self.on_ffmpeg_finished(False, message)

    # ── Удаление исходного файла ─────────────────────────────────────────────
    def delete_source_file(self):
        """Удаляет загруженный исходный файл с диска (с подтверждением). Перед
        удалением освобождает файл (останавливает плеер и снимает источник),
        иначе Windows не даст удалить открытый файл."""
        src = self.actual_source_file or self.filepath
        if not src or not _api.os.path.exists(str(src)):
            return
        src = str(src)
        name = _api.os.path.basename(src)
        reply = _api.msgbox_question(
            self, "Удалить исходный файл?",
            "Файл будет удалён с диска без возможности восстановления:\n\n"
            f"{name}\n\nПродолжить?",
            _api.QMessageBox.StandardButton.Yes | _api.QMessageBox.StandardButton.No,
            _api.QMessageBox.StandardButton.No)
        if reply != _api.QMessageBox.StandardButton.Yes:
            return
        # Останавливаем фоновую сборку прокси (если идёт): иначе её ffmpeg будет
        # держать temp-файл, а finished-слот выстрелит уже после очистки. Сам слот
        # дополнительно защищён проверкой actual_source_file is None.
        try:
            if self.proxy_thread and self.proxy_thread.isRunning():
                self.proxy_thread.stop(); self.proxy_thread.wait()
        except Exception: pass
        self.proxy_thread = None
        # Освобождаем файл: останавливаем воспроизведение и снимаем источник.
        try: self.player.stop()
        except Exception: pass
        try: self.player.setSource(_api.QUrl())
        except Exception: pass
        try:
            if getattr(self, "seek_preview", None) is not None:
                self.seek_preview.set_source(None)
        except Exception: pass
        try: _api.QApplication.processEvents()
        except Exception: pass
        try:
            _api.os.remove(src)
        except Exception as e:
            _api.msgbox_critical(self, "Ошибка", f"Не удалось удалить файл:\n{e}")
            return
        # Сбрасываем состояние редактора (файл больше не загружен).
        self.actual_source_file = None
        self.filepath = None
        self.duration = 0.0
        try:
            if hasattr(self.video_widget, "clear_frame"):
                self.video_widget.clear_frame()
        except Exception: pass
        try: self.waveform.set_data([], 0.0)
        except Exception: pass
        try: self._update_media_buttons()
        except Exception: pass
        try:
            if self.main is not None and hasattr(self.main, "log"):
                self.main.log(f"🗑 Исходный файл удалён: {name}")
        except Exception: pass
