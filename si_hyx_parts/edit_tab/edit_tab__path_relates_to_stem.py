# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""EditTab: _path_relates_to_stem. Public namespace: edit_tab."""
import edit_tab as _api


@classmethod
def _path_relates_to_stem(cls, rel_dir, stem):
    """True, если относительный путь подпапки (от папки видео) похож на
        подпапку ИМЕННО этого фильма/серии — по имени сегмента пути или по
        типовому названию папки субтитров. Не считаем «своей» произвольную
        подпапку общего каталога с раздачами — см. _scan_external_subs."""
    if not rel_dir:
        return True
    for seg in rel_dir.replace('\\', '/').split('/'):
        seg_l = seg.lower()
        if seg_l in cls._SUB_FOLDER_NAMES:
            return True
        if stem and (stem in seg_l or seg_l in stem):
            return True
    return False

def _scan_external_subs(self, src, expanded=False):
    """Ищет внешние файлы субтитров рядом с видео и в подпапках (до 3
        уровней). По умолчанию (expanded=False) включает только «свои»:
        файлы прямо в папке видео + файлы в подпапках самого фильма/серии
        (см. _path_relates_to_stem) — иначе общая папка с чужими раздачами
        (шрифты/сабы десятков разных тайтлов лежат рядом) засоряла список
        посторонними файлами. Отфильтрованные складываются в
        self._sub_ext_hidden — доступны через пункт «Показать другие файлы»
        в списке дорожек (см. _expand_external_subs)."""
    found, hidden = [], []
    try:
        base = _api.os.path.dirname(str(src))
        if not base or not _api.os.path.isdir(base):
            self._sub_ext_hidden = []
            return []
        stem = _api.os.path.splitext(_api.os.path.basename(str(src)))[0].lower()
        for root, dirs, files in _api.os.walk(base):
            rel_dir = root[len(base):].lstrip(_api.os.sep)
            depth = rel_dir.count(_api.os.sep) + (1 if rel_dir else 0)
            if depth >= 3:
                dirs[:] = []
            related = expanded or self._path_relates_to_stem(rel_dir, stem)
            for fn in files:
                if _api.os.path.splitext(fn)[1].lower() in self._SUB_EXTS:
                    p = _api.os.path.join(root, fn)
                    (found if related else hidden).append(p)
                    if len(found) + len(hidden) >= 500:
                        self._sub_ext_hidden = self._sort_external_subs(hidden, src)
                        return self._sort_external_subs(found, src)
    except Exception:
        pass
    self._sub_ext_hidden = self._sort_external_subs(hidden, src)
    return self._sort_external_subs(found, src)

def _expand_external_subs(self):
    """«Показать другие файлы» — досыпает в cmb_subs файлы, отфильтрованные
        _scan_external_subs как не относящиеся к этому фильму/серии."""
    hidden = getattr(self, "_sub_ext_hidden", None)
    if not hidden:
        return
    self._sub_ext_hidden = []
    for p in hidden:
        if p not in self._sub_ext:
            self._sub_ext.append(p)
    self._populate_track_combos_subs_only()

def _populate_track_combos_subs_only(self):
    """Перестраивает только cmb_subs (список дорожек субтитров), не трогая
        аудио/сброс текущего показа — используется _expand_external_subs, чтобы
        клик «Показать другие файлы» не гасил уже выбранную дорожку.

        Что восстановить, берём из _sub_sel_entry (последняя РЕАЛЬНО выбранная
        дорожка), а не из текущего пункта комбобокса: «Показать другие файлы» —
        сам пункт списка, и на момент перестройки выбран именно он. Раньше
        отсюда и брали — в итоге восстанавливать было нечего (после раскрытия
        этого пункта в списке уже нет), комбобокс молча вставал на «Выкл», и
        выбор дорожки расходился с тем, что на самом деле показано."""
    cur_kind_ref = getattr(self, "_sub_sel_entry", None)
    self._loading_tracks = True
    try:
        self.cmb_subs.clear()
        self.cmb_subs.addItem("Выкл")
        self._sub_entries = []
        for i, s in enumerate(self._sub_streams):
            self.cmb_subs.addItem(self._track_label(s, i, "Субтитры", total=len(self._sub_streams)))
            self._sub_entries.append(('emb', i))
        for p in self._sub_ext:
            self.cmb_subs.addItem(_api.get_icon('fa5s.file'), _api.os.path.basename(p))
            self._sub_entries.append(('ext', p))
        if getattr(self, "_sub_ext_hidden", None):
            self.cmb_subs.addItem(_api.get_icon('fa5s.folder-open'),
                                   f"Показать другие файлы в папке… ({len(self._sub_ext_hidden)})")
            self._sub_entries.append(('more', None))
        self.cmb_subs.setEnabled(len(self._sub_entries) > 0)
        if cur_kind_ref is not None and cur_kind_ref in self._sub_entries:
            self.cmb_subs.setCurrentIndex(self._sub_entries.index(cur_kind_ref) + 1)
    finally:
        self._loading_tracks = False

@staticmethod
def _sort_external_subs(paths, src):
    stem = _api.os.path.splitext(_api.os.path.basename(str(src)))[0].lower()

    def key(p):
        name = _api.os.path.splitext(_api.os.path.basename(p))[0].lower()
        match = 0 if (stem and (stem in name or name in stem)) else 1
        return (match, _api.os.path.basename(p).lower())

    return sorted(dict.fromkeys(paths), key=key)

# ── Кнопки «найти» (внешние аудио/субтитры с ПК) ──────────────────────────
def find_external_subs(self):
    if not self.actual_source_file:
        return
    start = str(self.actual_source_file.parent)
    fname, _ = _api.QFileDialog.getOpenFileName(
        self, "Выбрать файл субтитров", start,
        "Субтитры (*.srt *.ass *.ssa *.vtt *.sub);;Все файлы (*)")
    if fname:
        self._add_external_sub(_api.os.path.normpath(fname))

def find_external_audio(self):
    if not self.actual_source_file:
        return
    start = str(self.actual_source_file.parent)
    fname, _ = _api.QFileDialog.getOpenFileName(
        self, "Выбрать аудиофайл (озвучку)", start,
        "Аудио (*.mp3 *.aac *.m4a *.ac3 *.eac3 *.flac *.wav *.opus *.ogg "
        "*.dts *.mka *.wma);;Все файлы (*)")
    if fname:
        self._add_external_audio(_api.os.path.normpath(fname))

def _add_external_sub(self, path):
    target = ('ext', path)
    if path not in self._sub_ext:
        self._sub_ext.append(path)
        self._loading_tracks = True
        # «Показать другие файлы…», если есть, всегда должен остаться
        # последним пунктом списка — новую дорожку вставляем ПЕРЕД ним,
        # а не просто в конец (иначе выбор «Показать другие» смещался бы).
        more_at = next((i for i, e in enumerate(self._sub_entries)
                        if e[0] == 'more'), None)
        if more_at is None:
            self._sub_entries.append(target)
            self.cmb_subs.addItem(_api.get_icon('fa5s.file'), _api.os.path.basename(path))
        else:
            self._sub_entries.insert(more_at, target)
            self.cmb_subs.insertItem(more_at + 1, _api.get_icon('fa5s.file'),
                                      _api.os.path.basename(path))
        self.cmb_subs.setEnabled(True)
        self._loading_tracks = False
    try:
        idx = self._sub_entries.index(target) + 1   # +1: пункт 0 = «Выкл»
    except ValueError:
        return
    if self.cmb_subs.currentIndex() == idx:
        self.on_sub_track_changed(idx)
    else:
        self.cmb_subs.setCurrentIndex(idx)

# ── Правка текста субтитров ──────────────────────────────────────────────
@staticmethod
def _cues_to_srt(cues):
    def _ts(t):
        if t < 0:
            t = 0.0
        h = int(t // 3600); m = int((t % 3600) // 60); s = t - h * 3600 - m * 60
        return f"{h:02d}:{m:02d}:{s:06.3f}".replace('.', ',')
    out = []
    for i, (start, end, body) in enumerate(cues, 1):
        out.append(str(i))
        out.append(f"{_ts(start)} --> {_ts(end)}")
        out.append(body)
        out.append("")
    return "\n".join(out)

def _current_subs_as_srt(self):
    """Текст активной дорожки субтитров в виде SRT для редактора. Если cues уже
        разобраны (текстовая дорожка) — берём их; иначе (ASS/ещё грузится) —
        извлекаем SRT из источника синхронно. None — текст недоступен (битмап)."""
    if getattr(self, "_sub_cues", None):
        return self._cues_to_srt(self._sub_cues)
    src = getattr(self, "_cur_sub_src", None)
    idx = getattr(self, "_cur_sub_index", -1)
    if getattr(self, "selected_sub_ext_path", None):
        src = self.selected_sub_ext_path; idx = 0
    if not src or idx is None or idx < 0:
        return None
    tmp = None
    try:
        tf = _api.tempfile.NamedTemporaryFile(delete=False, suffix=".srt")
        tmp = tf.name; tf.close()
        cmd = [_api.FFMPEG, "-y", "-i", str(src), "-map", f"0:s:{idx}", tmp]
        kw = {'creationflags': _api.CREATE_NO_WINDOW} if _api.os.name == 'nt' else {}
        _api.subprocess.run(cmd, stdout=_api.subprocess.DEVNULL,
                       stderr=_api.subprocess.DEVNULL, timeout=60, **kw)
        if _api.os.path.exists(tmp) and _api.os.path.getsize(tmp) > 0:
            with open(tmp, 'r', encoding='utf-8', errors='replace') as f:
                return f.read()
    except Exception:
        return None
    finally:
        if tmp:
            try: _api.os.remove(tmp)
            except Exception: pass
    return None

def _extract_srt_for_entry(self, kind, ref):
    """Текст произвольной дорожки (self._sub_entries) в виде SRT — не
        трогает текущий выбор в cmb_subs/состояние плеера, в отличие от
        _current_subs_as_srt (та работает только с АКТИВНОЙ дорожкой). Нужен
        для «Создать субтитры» → «Редактировать существующую», где дорожка,
        которую правит пользователь, может отличаться от активной."""
    if kind == 'emb':
        src, idx = self.actual_source_file, ref
    else:
        src, idx = ref, 0
        if str(ref).lower().endswith('.srt'):
            try:
                with open(ref, 'r', encoding='utf-8', errors='replace') as f:
                    return f.read()
            except Exception:
                pass
    if not src:
        return None
    tmp = None
    try:
        tf = _api.tempfile.NamedTemporaryFile(delete=False, suffix=".srt")
        tmp = tf.name; tf.close()
        cmd = [_api.FFMPEG, "-y", "-i", str(src), "-map", f"0:s:{idx}", tmp]
        kw = {'creationflags': _api.CREATE_NO_WINDOW} if _api.os.name == 'nt' else {}
        _api.subprocess.run(cmd, stdout=_api.subprocess.DEVNULL,
                       stderr=_api.subprocess.DEVNULL, timeout=60, **kw)
        if _api.os.path.exists(tmp) and _api.os.path.getsize(tmp) > 0:
            with open(tmp, 'r', encoding='utf-8', errors='replace') as f:
                return f.read()
    except Exception:
        return None
    finally:
        if tmp:
            try: _api.os.remove(tmp)
            except Exception: pass
    return None

def edit_subtitles(self):
    if self.cmb_subs.currentIndex() <= 0:
        _api.msgbox_information(self, "Субтитры",
                                "Сначала выберите дорожку субтитров.")
        return
    srt = self._current_subs_as_srt()
    if not srt or not srt.strip():
        _api.msgbox_information(
            self, "Субтитры",
            "Не удалось получить текст субтитров для редактирования "
            "(возможно, это субтитры-картинки).")
        return
    try:
        cur_t = self._ui_time_s()
    except Exception:
        cur_t = None
    dlg = _api.SubtitleEditDialog(srt, self, current_time_s=cur_t)
    if dlg.exec() != _api.QDialog.DialogCode.Accepted:
        return
    new_text = dlg.text()
    if not _api._parse_srt(new_text):
        _api.msgbox_warning(self, "Субтитры",
                            "После правки не осталось ни одной реплики.")
        return
    try:
        _api.os.makedirs(_api.CONFIG_DIR, exist_ok=True)
        base = self.actual_source_file.stem if self.actual_source_file else "subs"
        path = _api.os.path.join(_api.CONFIG_DIR, f"{base}_edited.srt")
        n = 1
        while _api.os.path.exists(path) and _api.os.path.normpath(path) not in self._sub_ext:
            path = _api.os.path.join(_api.CONFIG_DIR, f"{base}_edited_{n}.srt"); n += 1
        with open(path, 'w', encoding='utf-8') as f:
            f.write(new_text if new_text.endswith("\n") else new_text + "\n")
    except Exception as e:
        _api.msgbox_warning(self, "Субтитры", f"Не удалось сохранить: {e}")
        return
    path = _api.os.path.normpath(path)
    # Делаем отредактированный файл активной дорожкой (превью + вшивание).
    if path in self._sub_ext:
        self._sub_cues = []
        try:
            idx = self._sub_entries.index(('ext', path)) + 1
        except ValueError:
            self._add_external_sub(path); return
        if self.cmb_subs.currentIndex() == idx:
            self.on_sub_track_changed(idx)
        else:
            self.cmb_subs.setCurrentIndex(idx)
    else:
        self._add_external_sub(path)
