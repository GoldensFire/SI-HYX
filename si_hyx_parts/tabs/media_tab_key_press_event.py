# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""MediaTab: keyPressEvent. Public namespace: tabs."""
import tabs as _api


def keyPressEvent(self, ev):
    # Резерв Ctrl+V для кириллической раскладки: физическая V шлёт Qt-код
    # кириллической буквы (М), и self.shortcut_paste (QShortcut("Ctrl+V"))
    # на ней молча не срабатывает — та же природа бага, что и Ctrl+Z/Y в
    # Монтаже (edit_tab.py) и WASD в редакторе фото (см. _pan_dir_from_event).
    # Доходит сюда, только если QShortcut его не поймал (для латиницы уже
    # сработал он — двойной вставки нет).
    if ev.modifiers() & _api.Qt.KeyboardModifier.ControlModifier:
        try:
            vk = ev.nativeVirtualKey()
        except Exception:
            vk = 0
        if vk == self._VK_V or ev.key() == _api.Qt.Key.Key_V:
            self.paste_files()
            ev.accept()
            return
    super(_api.MediaTab, self).keyPressEvent(ev)

def add(self):
    p, _ = _api.QFileDialog.getOpenFileNames(self, "Файлы")
    if p: self.add_paths(p)

def add_paths(self, paths):
    for p in paths:
        try:
            if not _api.os.path.exists(p): continue

            # Не добавляем файлы, которые сами являются результатом обработки
            stem = _api.Path(p).stem
            if stem.endswith("_Сжатый") or stem.endswith("_Compressed"):
                continue

            ext = _api.Path(p).suffix.lower()
            if ext in _api.ALLOWED_MEDIA: ft = "MEDIA"
            elif ext in _api.ALLOWED_IMG: ft = "IMG"
            else: continue

            iid = _api.uuid.uuid4().hex
            # Только быстрый getsize — ffprobe уйдёт в фоновый поток
            try: size = _api.os.path.getsize(p)
            except Exception: size = 0

            item_data = {'iid': iid, 'path': p, 'type': ft, 'dur': 0, 'is_done': False}
            self.items.append(item_data)
            self._item_data_map[iid] = item_data

            it = _api.QTreeWidgetItem(self.tree)
            name = _api.os.path.basename(p)
            # Колонка 0 (Превью): миниатюра + имя файла под ней (рисует
            # PreviewNameDelegate, длинное имя обрезается многоточием).
            # Полное имя — в тултипе.
            it.setText(0, name)
            # Тултип превью — только путь; полное имя показывается при
            # наведении на строку имени под превью (см. DraggableTreeWidget).
            it.setToolTip(0, p)
            # Колонка 1: метки Было/Стало. 2 строки [было, стало] —
            # центрируются по высоте строки как имя файла и статус (пустая
            # 1-я строка раньше сдвигала пару вниз от центра).
            it.setText(1, "Было\nСтало")
            it.setText(2, f"{_api.human_size(size)}\n—")     # Размер: было(исх) / стало
            it.setText(3, "—\n—")                       # Битрейт: исх / итог
            it.setText(4, "—\n—")                       # LUFS: до / после
            it.setText(5, "—\n—")                       # Длительность: исх / итог
            it.setText(6, "Ожидание")                   # Статус (одна строка)
            it.setText(7, "—")                          # Время перекодирования (мм:сс)
            it.setToolTip(7, "Время, потраченное на перекодирование")
            it.setText(8, "—")                          # Оценка XPSNR (заполняется после видео-кодирования)
            it.setToolTip(8, "Оценка качества результата (XPSNR, дБ) — выше значит ближе к оригиналу.\n"
                             "Только для перекодированного видео (AV1); при копировании/аудио — «—».")
            it.setData(0, _api.Qt.ItemDataRole.UserRole, iid)
            # Аудио (без видеоряда) → компактная строка без места под превью.
            if ext in _api.ALLOWED_AUDIO:
                it.setData(0, _api.ITEM_AUDIO_ROLE, True)
            self._item_map[iid] = it
            self.tree.scrollToItem(it)
            self.pool.start(_api.LocalThumbnailRunnable(p, iid, self.thumb_sig))

            if ft == "MEDIA":
                def _bg(path_local, iid_local):
                    # ffprobe + loudness — всё в фоне, UI не блокируем.
                    # Результат отдаём в GUI-поток через сигналы: QTimer.singleShot
                    # из обычного threading.Thread (без Qt event loop) НЕ
                    # срабатывает — из-за этого битрейт и длительность не
                    # появлялись при добавлении файла.
                    try:
                        dur_r, br_r, size_r, a_br_r, a_codec_r = _api.get_media_info(path_local)
                        v_r = _api.get_video_codec_label(path_local)
                        size_label_r = f"{v_r} {_api.human_size(size_r)}" if v_r else _api.human_size(size_r)
                        self.media_info_sig.emit(
                            iid_local, size_label_r,
                            _api.fmt_bitrate_with_codec(a_codec_r, a_br_r or br_r),
                            float(dur_r or 0.0))
                    except Exception: pass
                    try:
                        val = _api.measure_loudness(path_local)
                    except Exception: val = None
                    self.media_lufs_sig.emit(iid_local, val)
                _api.threading.Thread(target=_bg, args=(p, iid), daemon=True).start()

        except Exception as e:
            self.main.log(f"add_paths error: {e}")

def set_thumb(self, iid, icon):
    try:
        item = self._find_item(iid)
        if item:
            item.setIcon(0, icon)
    except Exception: pass

def _apply_media_info(self, iid, size_str, bitrate, dur):
    """GUI-поток: исходные размер/битрейт/длительность из ffprobe (верхняя
        строка «Было»). Вызывается через media_info_sig из фонового потока."""
    try:
        d = self._item_data_map.get(iid)
        if d: d['dur'] = dur
        item = self._find_item(iid)
        if item:
            if size_str:
                self._set_pair(item, 2, top=size_str)
            self._set_pair(item, 3, top=(bitrate if bitrate and bitrate != "-" else "—"))
            self._set_pair(item, 5, top=self._fmt_dur(dur))
    except Exception: pass

def _apply_media_lufs(self, iid, val):
    """GUI-поток: исходный LUFS (через media_lufs_sig из фонового потока)."""
    self.update_lufs_columns(iid, val, None)

@staticmethod
def _set_pair(item, col, top=None, bottom=None):
    """Ячейка из 2 строк: [было, стало]. Меняет только было/стало
        (top/bottom), сохраняя другую строку. Пара центрируется по высоте
        строки (как имя файла и статус)."""
    cur = (item.text(col) or "").split("\n")
    # Легаси-формат из 3 строк ([пусто, было, стало]) — отбрасываем пустую.
    if len(cur) >= 3:
        cur = cur[1:]
    t = cur[0] if len(cur) > 0 and cur[0] else "—"
    b = cur[1] if len(cur) > 1 and cur[1] else "—"
    if top is not None: t = top
    if bottom is not None: b = bottom
    item.setText(col, f"{t}\n{b}")

@staticmethod
def _fmt_dur(sec):
    """Длительность для колонки: «5.72 с» (<1 мин) или «M:SS.ss»."""
    try: sec = float(sec)
    except Exception: return "—"
    if sec <= 0: return "—"
    if sec < 60: return f"{sec:.2f} с"
    m = int(sec // 60); s = sec - m * 60
    return f"{m}:{s:05.2f}"

def update_item_info(self, iid, size_new, bitrate_result):
    try:
        item = self._find_item(iid)
        if item:
            self._set_pair(item, 2, bottom=size_new)          # Размер: стало
            self._set_pair(item, 3, bottom=bitrate_result)    # Битрейт: итог
            item.setData(0, _api.ITEM_STATUS_ROLE, 'done')
            # Для обработанной картинки/видео включаем значок «сравнить» на превью
            # (аудио без видеоряда сравнивать нечем — там значок не нужен).
            entry = self._item_data_map.get(iid)
            is_video = entry and entry.get('type') == 'MEDIA' and _api.Path(entry.get('path', '')).suffix.lower() not in _api.ALLOWED_AUDIO
            if entry and (entry.get('type') == 'IMG' or is_video):
                item.setData(0, _api.ITEM_COMPARE_ROLE, True)
                item.setToolTip(0, (item.toolTip(0) or "")
                                + "\n\nЗначок в углу превью — сравнить исходник и результат.")
            self.tree.viewport().update()
    except Exception: pass

def _on_compare_clicked(self, index):
    """Клик по значку «сравнить» на превью обработанного файла: открывает
        полноэкранное сравнение исходника и результата (картинка — по форме,
        видео — плеер слева/справа с синхронной перемоткой). Если оригинал/
        результат недоступны — показывает то, что есть."""
    try:
        iid = index.data(_api.Qt.ItemDataRole.UserRole)
        entry = self._item_data_map.get(iid)
        if not entry:
            return
        src = entry.get('path', '')
        out = entry.get('out_path', '')
        src_ok = bool(src) and _api.os.path.exists(src)
        out_ok = bool(out) and _api.os.path.exists(out)
        is_video = entry.get('type') == 'MEDIA' and _api.Path(src or out).suffix.lower() not in _api.ALLOWED_AUDIO
        if src_ok and out_ok and _api.os.path.abspath(src) != _api.os.path.abspath(out):
            if is_video:
                _api.show_video_compare(src, out, self)
            else:
                _api.show_image_compare(src, out, self)
        elif out_ok:
            if is_video:
                _api.show_video_compare(out, out, self)
            else:
                _api.show_image_fullscreen(out, self)
        elif src_ok:
            if is_video:
                _api.show_video_compare(src, src, self)
            else:
                _api.show_image_fullscreen(src, self)
    except Exception as e:
        self.main.log(f"Сравнение: {e}")

def _compare_any_files(self):
    """Кнопка «Сравнить» в тулбаре списка — сравнение ЛЮБЫХ двух файлов с
        диска, а не только пары исходник/результат из очереди обработки. Тип
        (картинка или видео) определяется по расширению первого файла. Можно
        выбрать всего один файл — окно сравнения откроется сразу с ним (слева),
        а второй добавляется прямо в окне значком папки (тот же интерфейс,
        что и при обычном сравнении)."""
    try:
        video_exts = _api.ALLOWED_MEDIA - _api.ALLOWED_AUDIO
        exts = " ".join(f"*{e}" for e in sorted(_api.ALLOWED_IMG | video_exts))
        paths, _ = _api.QFileDialog.getOpenFileNames(
            self, "Выберите файл(ы) для сравнения (можно один — второй добавите в окне)", "",
            f"Изображения и видео ({exts});;Все файлы (*)")
        if not paths:
            return
        a = paths[0]
        b = paths[1] if len(paths) > 1 else None
        ext_a = _api.Path(a).suffix.lower()
        if ext_a in _api.ALLOWED_IMG:
            _api.show_image_compare(a, b, self, use_filenames=True)
        elif ext_a in video_exts:
            _api.show_video_compare(a, b, self, use_filenames=True)
        else:
            self.main.log(f"Сравнение: неподдерживаемый тип файла «{ext_a}»")
    except Exception as e:
        self.main.log(f"Сравнение: {e}")

def update_item_dur(self, iid, dur_str):
    """Длительность итогового файла (после перекодирования) — нижняя строка."""
    try:
        item = self._find_item(iid)
        if item:
            self._set_pair(item, 5, bottom=self._fmt_dur(dur_str))
    except Exception: pass

def update_item_xpsnr(self, iid, score):
    """Оценка качества результата (XPSNR, дБ) — заполняется после видео-
        кодирования (см. xpsnr_sig в workers.py). score=None — не измерялась
        (не видео, копия без перекодирования, или замер не удался)."""
    try:
        item = self._find_item(iid)
        if item:
            item.setText(8, "—" if score is None else f"{score:.1f} дБ")
    except Exception: pass

def update_lufs_columns(self, iid, before, after):
    try:
        item = self._find_item(iid)
        if item:
            self._set_pair(item, 4, top=("—" if before is None else f"{before:.2f}"))
            self._set_pair(item, 4, bottom=("—" if after is None else f"{after:.2f}"))
    except Exception: pass

def rem(self):
    try:
        for i in self.tree.selectedItems():
            iid = i.data(0, _api.Qt.ItemDataRole.UserRole)
            # Мутируем СПИСОК НА МЕСТЕ (не self.items = [...]) — ProcessWorker
            # держит ссылку на этот же объект-список как «живую» очередь
            # (см. queue_ref в _run_items); переприсваивание отвязывало бы
            # воркер от изменений, и удалённый файл всё равно обрабатывался
            # бы до конца, а не только до нажатия «СТОП».
            self.items[:] = [x for x in self.items if x['iid'] != iid]
            self._item_map.pop(iid, None)
            self._item_data_map.pop(iid, None)
            self._removed_ids.add(iid)
            self.tree.invisibleRootItem().removeChild(i)
    except Exception: pass

def clear(self):
    try:
        self.items.clear()
        self._item_map.clear()
        self._item_data_map.clear()
        self.tree.clear()
    except Exception: pass

def run(self):
    """Кнопка «НАЧАТЬ» — обрабатывает всю очередь."""
    self._run_items(self.items)
