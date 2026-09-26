# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""MediaTab: _collect_settings. Public namespace: tabs."""
import tabs as _api


def _collect_settings(self):
    """Собирает АКТУАЛЬНОЕ состояние всех настроек «Обработки» с виджетов —
        единственное место сборки, чтобы кнопка «НАЧАТЬ» и фоновая пере-синхронизация
        настроек уже идущего воркера (_settings_sync_tick) всегда читали одно и то же
        и любая новая настройка, добавленная сюда в будущем, подхватывалась обоими
        путями сама собой."""
    try: ab = self.c_abitrate.currentText() or "128"
    except Exception: ab = "128"
    try: spd = self.s_spd.value()
    except Exception: spd = 100
    return {
        'audio': {
            'remove': bool(self.ck_no_audio.isChecked()),
            'norm': bool(self.ck_norm.isChecked()),
            'tgt': float(self.s_tgt.value()), 'lra': float(self.s_lra.value()), 'tp': float(self.s_tp.value()),
            'fade': bool(self.ck_fade.isChecked()), 'fade_d': float(self.s_fade.value()),
            'fade_in': bool(self.ck_fade_in.isChecked()), 'fade_in_d': float(self.s_fade_in.value()),
            'deg': bool(self.ck_deg.isChecked()), 'hz': int(self.s_hz.value()), 'u8': bool(self.ck_u8.isChecked()),
            'lp': int(self.s_lp.value()), 'hp': int(self.s_hp.value()), 'deg_gain_db': float(self.s_deg_gain.value()),
            'bitrate': ab
        },
        'video': {
            'enabled': bool(self.chk_enable_video.isChecked()), 'speed': int(spd), 'crf': int(self.s_crf.value()),
            'pre': int(self.s_pre.value()), 'res': _api.strip_default_tag(self.c_res.currentText()), 'fps': self.c_fps.currentText().strip().replace(',', '.'),
            'preset_mode': 'dark' if self.btn_mode_dark.isChecked() else 'std',
            'tune': self._video_tune_value(),
            'metric': self._video_metric_value(), 'target_metric': float(self.s_target_metric.value()),
            # Видна ли колонка «Оценка XPSNR»: пока она скрыта (по умолчанию),
            # ProcessWorker не тратит пробное кодирование на её заполнение —
            # см. _wants_metric_score в workers.py.
            'show_metric_col': bool(getattr(self, '_show_advanced_encode', False)),
            'vfade_in': bool(self.ck_vfade_in.isChecked()), 'vfade_in_d': float(self.s_vfade_in.value()),
            'vfade_out': bool(self.ck_vfade_out.isChecked()), 'vfade_out_d': float(self.s_vfade_out.value()),
            'crop_black': bool(self.ck_crop_black.isChecked())
        },
        'avif': {
            'limit': int(self.s_lim.value()) if self.ck_lim.isChecked() else 0,
            'adim': int(self.s_dim.value()) if self.ck_dim.isChecked() else 0,
            'awidth': int(self.s_width.value()) if self.ck_width.isChecked() else 0,
            'aheight': int(self.s_height.value()) if self.ck_height.isChecked() else 0,
            'aspd': int(self.sl_aspd.value()),
            'cq': int(self.s_cq.value()),
            'overwrite_src': bool(self.ck_overwrite_src.isChecked()),
            'fit_passes': int(self.s_passes.value()),
            'img_fmt': _api.strip_default_tag(self.c_img_fmt.currentText()),
            'chroma': _api.strip_default_tag(self.c_chroma.currentText()).replace(':', '')
        },
        'export_dir': self.export_dir or '',
        'priority': {'Низкий': 'low', 'Обычный': 'normal', 'Высокий': 'high'}.get(
            self.c_priority.currentText(), 'normal')
    }

def _settings_sync_tick(self):
    """Пока воркер работает — подсовывает ему свежий словарь настроек (см.
        _collect_settings). ProcessWorker читает self.settings заново для КАЖДОГО
        файла (self.settings.get(...) внутри process_media), поэтому уже начатый
        файл фоновым перезапросом не затрагивается — досрочно подхватывают
        изменение только ещё не стартовавшие (в т.ч. добавленные во время работы)."""
    w = getattr(self, 'worker', None)
    if w is None or not w.isRunning():
        self._settings_sync_timer.stop()
        return
    try:
        w.settings = self._collect_settings()
    except Exception:
        pass

def _run_items(self, target):
    if not target: return
    # Не запускаем второй воркер поверх активного (двойной клик во время работы)
    if getattr(self, 'worker', None) is not None:
        try:
            if self.worker.isRunning():
                self.main.log("Дождитесь завершения текущей обработки.")
                return
        except Exception: pass
    s = self._collect_settings()
    if hasattr(self.main, "clear_global_result"):
        self.main.clear_global_result()
    self.worker = _api.ProcessWorker(target, s, removed_ids=self._removed_ids)
    self.worker.status.connect(self.on_stat); self.worker.progress.connect(self.on_prog)
    self.worker.log.connect(self.main.log); self.worker.finished_all.connect(self.done)
    self.worker.global_progress.connect(self.main.update_global_progress)
    self.worker.update_item_sig.connect(self.update_item_info); self.worker.update_lufs_sig.connect(self.update_lufs_columns)
    self.worker.update_dur_sig.connect(self.update_item_dur)
    self.worker.xpsnr_sig.connect(self.update_item_xpsnr)
    self.worker.active_threads.connect(self._on_active_threads)

    try:
        for itdata in target:
            if itdata.get('is_done'): continue
            iid = itdata.get('iid')
            item = self._find_item(iid)
            if item:
                item.setData(0, _api.ITEM_STATUS_ROLE, 'proc')
                item.setText(6, "Ожидание")   # сброс прошлого «Готово»/«Ошибка»
                item.setText(7, "—")
            # Сбрасываем прошлый замер времени — новый запуск считает с нуля.
            self._proc_started.pop(iid, None)
            self._proc_running.discard(iid)
        self.tree.viewport().update()
    except Exception: pass

    self.b_run.setEnabled(False); self.b_stop.setEnabled(True)
    self.worker.start()
    self._settings_sync_timer.start()

def stop(self):
    if self.worker:
        try: self.worker.stop()
        except Exception: pass
