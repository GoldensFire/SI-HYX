# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""MediaTab: on_stat. Public namespace: tabs."""
import tabs as _api


def on_stat(self, iid, txt, code):
    try:
        i = self._find_item(iid)
        if i:
            i.setData(0, _api.ITEM_STATUS_ROLE, code)
            # Не показываем промежуточные подписи «Обработка.»/«Конвертация
            # картинки» — в колонке «Статус» сразу идут проценты (on_prog)
            # и финальные «Готово»/«Ошибка»/«Остановлено».
            if code != 'proc':
                i.setText(6, txt)
            self.tree.viewport().update()
        # Подбор AVIF/WebP под лимит размера идёт несколькими проходами —
        # текст вида «Конвертация картинки N/total» несёт номер прохода,
        # который показываем рядом с временем (колонка «Время»).
        if code == 'proc':
            m = self._RE_IMG_PASS.search(txt or "")
            if m:
                self._item_pass[iid] = f"{m.group(1)}/{m.group(2)}"
                self._update_elapsed_text(iid)
        # Учёт времени перекодирования (колонка «Время»):
        #   proc      → засекаем старт (единожды) и запускаем тик-таймер;
        #   done/err  → фиксируем итог и больше не тикаем этот файл.
        if code == 'proc':
            self._start_elapsed(iid)
        elif code in ('done', 'err'):
            self._item_pass.pop(iid, None)
            self._freeze_elapsed(iid)
        if code == 'done':
            entry = self._item_data_map.get(iid)
            out_path = entry.get('out_path', '') if entry else ''
            if out_path and hasattr(self.main, "set_global_result"):
                self.main.set_global_result(out_path)
    except Exception: pass

def on_prog(self, iid, val):
    try:
        i = self._find_item(iid)
        if i:
            i.setText(6, "Готово" if val >= 100 else f"{val}%")
        if val >= 100:
            self._freeze_elapsed(iid)
    except Exception: pass

# ── Время перекодирования (колонка 7) ──────────────────────────────────────
@staticmethod
def _fmt_elapsed(sec) -> str:
    """Секунды → «мм:сс» (минуты и секунды через двоеточие)."""
    sec = max(0, int(sec))
    m, s = divmod(sec, 60)
    return f"{m:02d}:{s:02d}"

def _elapsed_text_for(self, iid, elapsed_sec) -> str:
    """мм:сс + «(x/y)» прохода подбора картинки, если он сейчас идёт."""
    txt = self._fmt_elapsed(elapsed_sec)
    p = self._item_pass.get(iid)
    return f"{txt} ({p})" if p else txt

def _update_elapsed_text(self, iid):
    """Перерисовывает колонку «Время» текущего файла (напр. когда сменился
        номер прохода, а не только тик таймера)."""
    start = self._proc_started.get(iid)
    if start is None:
        return
    i = self._find_item(iid)
    if i:
        i.setText(7, self._elapsed_text_for(iid, _api.time.monotonic() - start))

def _start_elapsed(self, iid):
    """Засекает старт перекодирования файла (если ещё не засечён) и
        включает таймер, который тикает время вверх до завершения."""
    if iid not in self._proc_started:
        self._proc_started[iid] = _api.time.monotonic()
    self._proc_running.add(iid)
    i = self._find_item(iid)
    if i:
        i.setText(7, self._elapsed_text_for(iid, _api.time.monotonic() - self._proc_started[iid]))
    if not self._elapsed_timer.isActive():
        self._elapsed_timer.start()

def _tick_elapsed(self):
    """Раз в 0.5 с обновляет время у всех кодирующихся сейчас файлов."""
    now = _api.time.monotonic()
    for iid in list(self._proc_running):
        i = self._find_item(iid)
        if i is None:
            self._proc_running.discard(iid)
            continue
        start = self._proc_started.get(iid)
        if start is not None:
            i.setText(7, self._elapsed_text_for(iid, now - start))
    if not self._proc_running:
        self._elapsed_timer.stop()

def _freeze_elapsed(self, iid):
    """Фиксирует итоговое время файла и снимает его с тиканья (идемпотентно —
        повторные сигналы done/100% не пересчитывают и не сдвигают итог)."""
    self._proc_running.discard(iid)
    self._item_pass.pop(iid, None)
    start = self._proc_started.pop(iid, None)
    if start is not None:
        i = self._find_item(iid)
        if i:
            i.setText(7, self._fmt_elapsed(_api.time.monotonic() - start))
    if not self._proc_running:
        self._elapsed_timer.stop()

def _on_active_threads(self, n, m):
    try:
        # В простое показываем 0 из всех потоков ЦП машины (а не 0/0).
        total = m if m > 0 else self._cpu_threads
        self.lbl_threads.setText(f"Параллельных задач: {n}/{total}")
    except Exception: pass

def done(self):
    self.b_run.setEnabled(True); self.b_stop.setEnabled(False)
    self._removed_ids.clear()
    # Страховка: фиксируем итоговое время по всем ещё «тикающим» файлам и
    # останавливаем таймер (на случай, если кто-то не прислал done/err).
    for iid in list(self._proc_running):
        self._freeze_elapsed(iid)
    self._elapsed_timer.stop()
    try: self.lbl_threads.setText(f"Параллельных задач: 0/{self._cpu_threads}")
    except Exception: pass
    self.main.log("Готово")
    try: _api.play_done_sound()
    except Exception: pass

