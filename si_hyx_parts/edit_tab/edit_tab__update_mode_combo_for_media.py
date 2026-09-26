# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""EditTab: _update_mode_combo_for_media. Public namespace: edit_tab."""
import edit_tab as _api


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
