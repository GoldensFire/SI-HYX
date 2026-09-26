# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""EditTab: shutdown. Public namespace: edit_tab."""
import edit_tab as _api


# ── Cleanup (вызывается из главного окна при закрытии) ──────────────────
def shutdown(self):
    if not self._ready:
        return
    try:
        self.save_settings()
    except Exception:
        pass
    try:
        self.sync_timer.stop()
    except Exception:
        pass
    try:
        self.player.stop()
    except Exception:
        pass
    # Останавливаем звук покадровой перемотки: устройство вывода и фоновый
    # декодер окон PCM (он держит запущенный ffmpeg).
    try:
        self._release_scrub_sink()
    except Exception:
        pass
    try:
        eng = getattr(self, "_audio_scrub", None)
        if eng is not None:
            eng.stop()
            eng.wait(1500)
            self._audio_scrub = None
    except Exception:
        pass
    # Останавливаем фоновый поток превью кадров полосы воспроизведения.
    try:
        if getattr(self, 'seek_preview', None) is not None:
            self.seek_preview.shutdown()
    except Exception:
        pass
    # …и поток предекодера точных кадров (он держит запущенный ffmpeg).
    try:
        eng = getattr(self, '_frames', None)
        if eng is not None:
            eng.stop(); eng.wait(1500)
    except Exception:
        pass
    # Убиваем все фоновые ffmpeg-процессы, чтобы не остались зомби (баг #3).
    for attr in ('ffmpeg_thread', 'proxy_thread', 'audio_worker',
                 '_vinp_worker', '_trk_worker'):
        w = getattr(self, attr, None)
        if w is None:
            continue
        try:
            if hasattr(w, 'stop'):
                w.stop()
            if w.isRunning():
                if not w.wait(2000):
                    w.terminate(); w.wait()
        except Exception:
            pass
    try:
        if getattr(self, 'audio_worker', None) and self.audio_worker.tmp_wav \
                and _api.os.path.exists(self.audio_worker.tmp_wav):
            _api.os.remove(self.audio_worker.tmp_wav)
    except Exception:
        pass
    try:
        if self.tmp_proxy_file and _api.os.path.exists(self.tmp_proxy_file):
            _api.os.remove(self.tmp_proxy_file)
    except Exception:
        pass
    # Дожидаемся фоновых извлечений субтитров.
    for ex in list(getattr(self, '_sub_threads', [])):
        try:
            if ex.isRunning():
                if not ex.wait(2000):
                    ex.terminate(); ex.wait()
        except Exception:
            pass
    # Останавливаем ASS-рендер (таймер + libass + временный файл).
    try:
        self._stop_ass()
    except Exception:
        pass
    # Закрываем полноэкранное окно, если открыто.
    try:
        if getattr(self, '_fs_window', None) is not None:
            self.exit_fullscreen()
    except Exception:
        pass
    # Закрываем окно-оверлей субтитров.
    try:
        if self.sub_overlay is not None:
            self.sub_overlay.close()
            self.sub_overlay.deleteLater()
            self.sub_overlay = None
    except Exception:
        pass
    # Чистим временные папки извлечённых шрифтов, накопленные кэшем (см.
    # _extract_subtitle_fonts) — они больше не удаляются сразу после экспорта.
    try:
        import shutil
        for d in self._subtitle_fonts_cache.values():
            shutil.rmtree(d, ignore_errors=True)
        self._subtitle_fonts_cache.clear()
    except Exception:
        pass
    # …и временные PNG наложенных картинок (см. _render_export_overlays).
    try:
        import shutil
        d = getattr(self, "_overlay_tmp_dir", None)
        if d:
            shutil.rmtree(d, ignore_errors=True)
        self._overlay_tmp_dir = None
    except Exception:
        pass

def closeEvent(self, ev):
    # На случай использования вкладки как самостоятельного окна.
    self.shutdown()
    super(_api.EditTab, self).closeEvent(ev)
