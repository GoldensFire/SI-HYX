# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""YtdlpTab: add_dl. Public namespace: tabs."""
import tabs as _api


def add_dl(self, audio_only=False):
    self.fetch_timer.stop()
    try:
        url = self.url_edit.text().strip()
        self.url_edit.clear()
        if not url: return
        iid = _api.uuid.uuid4().hex
        it = _api.QTreeWidgetItem(self.tree)
        it.setText(0, url); it.setText(1, "-"); it.setText(2, "-"); it.setText(3, "В очереди")
        it.setData(0, _api.Qt.ItemDataRole.UserRole, iid)
        it.setData(0, _api.ITEM_STATUS_ROLE, 'proc')  # синяя подсветка «в работе»
        self.items[iid] = {'item': it, 'url': url, 'audio_only': bool(audio_only)}
        config = self._dl_config(iid, url, audio_only)
        w = _api.YtdlpWorker(config)
        self.active_workers[iid] = w
        w.finished.connect(lambda _=None, i=iid: self._remove_worker(i))
        self._connect_worker_signals(w, iid)
        w.start()
        self._update_stop_btn()
    except Exception as e:
        self.main.log(f"add_dl error: {e}")

def _update_stop_btn(self):
    """Кнопка СТОП активна только когда есть хотя бы одна активная загрузка."""
    active = bool(self.active_workers)
    try: self.btn_stop.setEnabled(active)
    except Exception: pass
    # Зеркалим состояние на кнопку СТОП в строке «Быстрая загрузка»
    # вкладки «Обработка» — быстрые загрузки идут через этот же пул.
    try: self.main.tab_media.btn_qdl_stop.setEnabled(active)
    except Exception: pass

def _update_dl_taskbar(self):
    """Сводный прогресс загрузок на иконке в панели задач:
          • есть реальный % (v>0) — средний % (обычный режим);
          • идёт загрузка, но % неизвестен (тихий ffmpeg, v==-1) — бегущая полоса;
          • только подготовка/извлечение (v==0) или активных нет — снять индикатор,
            чтобы падающее извлечение не выглядело как «что-то грузится»."""
    try:
        vals = [v for v in self._dl_pct.values() if v is not None]
        real = [v for v in vals if v > 0]
        if real:
            self.main.set_taskbar_progress(int(sum(real) / len(real)), 100)
        elif any(v < 0 for v in vals):
            self.main.set_taskbar_progress(0, 100)  # 0 → неопределённый режим
        else:
            self.main.clear_taskbar_progress()
    except Exception:
        pass

def _remove_worker(self, iid):
    self.active_workers.pop(iid, None)
    # Сигнал finished у потока срабатывает ВСЕГДА при его завершении — даже если
    # загрузка упала, не отправив error_sig/finished_sig (тогда в _dl_pct оставался
    # бы «-1», и на иконке в панели задач навсегда зависала «бегущая полоса»
    # загрузки, хотя по факту ошибка). Снимаем элемент из прогресса здесь —
    # это гарантированно убирает индикатор после ошибочной/прерванной загрузки.
    self._dl_pct.pop(iid, None)
    self._update_dl_taskbar()
    self._update_stop_btn()

def _dl_config(self, iid, url, audio_only):
    """Конфиг загрузки из текущих настроек вкладки. Общий для add_dl и
        перезапуска (redownload), чтобы режимы не расходились."""
    return {
        'iid': iid, 'url': url, 'fmt': _api.FORMAT_OPTIONS.get(self.c_q.currentText(), 'best'),
        'outdir': self.out.text(), 'merge': self.c_c.currentText(), 'sub_lang': self.c_s.currentText(),
        'audio': self.c_a.currentText(), 'force_kf': self.chk_k.isChecked(),
        'start_s': self.get_sec(self.ts) if any(x.value() for x in self.ts) else None,
        'end_s': self.get_sec(self.te) if any(x.value() for x in self.te) else None,
        'audio_only': bool(audio_only),
        'cookie_path': self.cookie_edit.text().strip(),
        'proxy': self.proxy_edit.text().strip(),
        'kodik_episode': self._kodik_episode_value(),
        'kodik_translation': (lambda t: "" if t in ("", "—") else t)(self.kodik_trans.currentText().strip()),
    }

def redownload_sel(self):
    """Скачать выбранные заново В ТОЙ ЖЕ строке — без дубля в списке.
        Если по элементу ещё идёт воркер, СНАЧАЛА останавливаем его: иначе два
        процесса пишут один и тот же выходной файл и падают с WinError 32
        («файл занят другим процессом», 'X.m4a'->'X.m4a')."""
    for it in list(self.tree.selectedItems()):
        try:
            iid = it.data(0, _api.Qt.ItemDataRole.UserRole)
            entry = self.items.get(iid, {}) if iid else {}
            url = (entry.get('url') if isinstance(entry, dict) else "") or it.text(0)
            if not (url and url.strip().startswith('http')):
                continue
            url = url.strip()
            audio_only = bool(entry.get('audio_only', False)) if isinstance(entry, dict) else False
            # Гасим прежний воркер этого же элемента (если ещё активен) —
            # не плодим второй процесс на тот же файл.
            old = self.active_workers.pop(iid, None)
            if old:
                try: old.stop()
                except Exception: pass
            # Сброс строки в исходное состояние «в очереди»
            it.setText(1, "-"); it.setText(2, "-"); it.setText(3, "В очереди")
            it.setToolTip(3, "")
            it.setData(0, _api.ITEM_STATUS_ROLE, 'proc')
            self.tree.viewport().update()
            self.items[iid] = {'item': it, 'url': url, 'audio_only': audio_only}
            w = _api.YtdlpWorker(self._dl_config(iid, url, audio_only))
            self.active_workers[iid] = w
            w.finished.connect(lambda _=None, i=iid: self._remove_worker(i))
            self._connect_worker_signals(w, iid)
            w.start()
            self._update_stop_btn()
            self.main.log(f"Повторная загрузка: {url}")
        except Exception as e:
            self.main.log(f"redownload error: {e}")

def delete_sel(self):
    try:
        for it in list(self.tree.selectedItems()):
            iid = it.data(0, _api.Qt.ItemDataRole.UserRole)
            if iid:
                self.active_workers.pop(iid, None)
                self.items.pop(iid, None)
            self.tree.invisibleRootItem().removeChild(it)
        self._update_stop_btn()
    except Exception: pass

def set_thumb(self, iid, icon):
    try:
        entry = self.items.get(iid)
        if entry and isinstance(entry, dict):
            it = entry.get('item')
            if it and isinstance(it, _api.QTreeWidgetItem):
                it.setIcon(0, icon)
    except Exception: pass
