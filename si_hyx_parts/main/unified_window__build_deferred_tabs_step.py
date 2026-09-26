# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""UnifiedWindow: _build_deferred_tabs_step. Public namespace: main."""
import main as _api


def _build_deferred_tabs_step(self):
    """Достраивает по ОДНОЙ отложенной вкладке за такт цикла событий, чтобы
        между ними окно успевало обработать ввод (см. __init__)."""
    queue = getattr(self, "_deferred_tabs", None)
    if not queue:
        return
    add_tab = queue.pop(0)
    try:
        add_tab()
    except Exception as e:
        self.log(f"Не удалось добавить отложенную вкладку: {e}")
    if queue:
        _api.QTimer.singleShot(0, self._build_deferred_tabs_step)

def _check_ffmpeg_async(self):
    """Запускает проверку ffmpeg в отдельном потоке (см. __init__): сам запуск
        процесса блокирующий, а держать на нём цикл событий незачем."""
    def worker():
        ok = False
        try:
            ok = _api.check_ffmpeg()
        except Exception:
            ok = False
        if not ok:
            try:
                self.ffmpeg_missing_sig.emit()
            except Exception:
                pass
    _api.threading.Thread(target=worker, daemon=True).start()

def _on_ffmpeg_missing(self):
    _api.msgbox_critical(self, "Error", "FFmpeg not found!")

def add_paths(self, paths):
    """Роутит файлы из общего стрипа в активную вкладку."""
    current = self.tabs.currentWidget()
    if hasattr(current, 'add_paths') and current is not self:
        current.add_paths(paths)
    else:
        self.tab_media.add_paths(paths)

def _load_settings(self):
    s, status = _api.load_settings_ex()
    # Прочитать не вышло, хотя сохранённые настройки на диске ЕСТЬ (файл
    # занят антивирусом/другим процессом). Дальше всё поднимется на
    # дефолтах, и первое же авто-сохранение (оно висит на КАЖДОМ
    # чекбоксе/поле, см. _attach_save_handlers, и срабатывает при выходе)
    # записало бы эти дефолты поверх настроек пользователя — насовсем,
    # вместе с .bak. Именно так «слетали все настройки». Поэтому на такой
    # запуск сохранение выключается целиком: настройки на диске остаются
    # нетронутыми, а перезапуск (когда файл снова читается) всё возвращает.
    self._settings_readonly = (status == "locked"
                               or bool(not s and _api.settings_files_exist()))
    if self._settings_readonly:
        self.log("НАСТРОЙКИ НЕ ПРОЧИТАЛИСЬ: файл настроек есть, но открыть/разобрать "
                 "его не удалось — работаем на значениях по умолчанию, СОХРАНЕНИЕ "
                 "ОТКЛЮЧЕНО до перезапуска (файл на диске не тронут).")
        self._warn_settings_readonly()
    elif status == "recovered":
        # Основной файл и .bak оказались непригодны, но настройки подняты из
        # снимка истории (см. utils._snapshot_settings_history) — работаем
        # как обычно, сохранение включено, просто сообщаем об этом.
        self.log("Настройки восстановлены из резервного снимка: основной файл "
                 "и .bak оказались повреждены.")
    tm = self.tab_media
    ty = self.tab_ytdlp
    self._server_enabled = bool(s.get("server_enabled", False))
    self._wheel_changes_values = bool(s.get("wheel_changes_values", False))
    self._video_hw_decode = bool(s.get("video_hw_decode", True))
    self._keep_models_in_ram = bool(s.get("keep_models_in_ram", False))
    try:
        self.tab_photo.inpaint.set_keep_models(self._keep_models_in_ram)
    except Exception:
        pass
    self._show_advanced_encode = bool(s.get("advanced_encode_visible", False))
    try:
        tm.set_advanced_encode_visible(self._show_advanced_encode)
    except Exception:
        pass
    self._siquester_tab_enabled = bool(s.get("siquester_tab_enabled", False))
    self._shikimori_tab_enabled = bool(s.get("shikimori_tab_enabled", False))
    self._shikimori_settings = dict(s.get("shikimori", {}) or {})
    self._leaderboard_tab_enabled = bool(s.get("leaderboard_tab_enabled", False))
    self._coop_tab_enabled = bool(s.get("coop_tab_enabled", False))
    self._coop_settings = dict(s.get("coop", {}) or {})
    self._animepack_tab_enabled = bool(s.get("animepack_tab_enabled", False))
    self._animepack_settings = dict(s.get("animepack", {}) or {})
    self._animepack_upgrade_tab_enabled = bool(
        s.get("animepack_upgrade_tab_enabled", False))
    self._animepack_upgrade_settings = dict(s.get("animepack_upgrade", {}) or {})
    self._prompt_tab_enabled = bool(s.get("prompt_tab_enabled", False))
    # Ключи внешних API (Gemini, TMDB) — общие для всех вкладок и
    # живут ТОЛЬКО тут: раньше поле ввода дублировалось в каждой вкладке,
    # которой ключ нужен (см. Настройки → «Ключи API»).
    self._api_keys = {k: str(v or "") for k, v in
                      (s.get("api_keys", {}) or {}).items()}
    self._tab_order = list(s.get("tab_order", []) or [])
    m = s.get("media", {})

    # Секции ниже НАРОЧНО в отдельных try/except каждая (а не одном общем):
    # раньше один общий try оборачивал вообще всё восстановление настроек
    # подряд (аудио → видео → папка экспорта → yt-dlp → AVIF), и исключение
    # на ЛЮБОМ раннем поле (например, из-за правки кода, сломавшей метод
    # виджета) тихо обрывало загрузку — все поля, что шли ПОСЛЕ сбойного
    # (папка загрузки, скорость AVIF, cookie_path — они ближе к концу),
    # оставались с дефолтом виджета и выглядели «сброшенными». Первое же
    # следующее изменение любой настройки тут же затирало settings.json
    # этими дефолтами через автосохранение. Изоляция по секциям гарантирует,
    # что падение одной секции не блокирует восстановление остальных.
    try:
        a = m.get("audio", {})
        tm.ck_no_audio.setChecked(a.get("remove", False))
        tm.ck_norm.setChecked(a.get("norm", True))
        tm.s_tgt.setValue(a.get("tgt", -20.0))
        tm.s_lra.setValue(a.get("lra", 11.0))
        tm.s_tp.setValue(a.get("tp", -1.5))
        tm.ck_fade.setChecked(a.get("fade", False))
        tm.s_fade.setValue(a.get("fade_d", 1.0))
        tm.ck_fade_in.setChecked(a.get("fade_in", False))
        tm.s_fade_in.setValue(a.get("fade_in_d", 1.0))
        tm.ck_deg.setChecked(a.get("deg", False))
        tm.s_hz.setValue(a.get("hz", 8000))
        tm.ck_u8.setChecked(a.get("u8", False))
        tm.s_lp.setValue(a.get("lp", 3000))
        tm.s_hp.setValue(a.get("hp", 200))
        tm.s_deg_gain.setValue(a.get("deg_gain_db", 0.0))
        tm.c_abitrate.setCurrentText(a.get("bitrate", "128"))
    except Exception as e:
        self.log(f"_load_settings(audio) error: {e}")

    try:
        v = m.get("video", {})
        tm.chk_enable_video.setChecked(v.get("enabled", True))
        tm.s_spd.setValue(v.get("speed", 100))
        tm.s_crf.setValue(v.get("crf", 45))
        tm.s_pre.setValue(v.get("pre", 2))
        _api.combo_set_value(tm.c_res, v.get("res", "1280x720"))
        tm.c_fps.setCurrentText(v.get("fps", "Исходный (max 30)"))
        tm._set_preset_mode(v.get("preset_mode", "std"))
        tm._set_tune_value(v.get("tune", 0))
        try:
            metric_saved = v.get("metric", "none")
            tm.ck_metric_xpsnr.setChecked(metric_saved == "xpsnr")
            if "target_metric" in v:
                tm.s_target_metric.setValue(int(float(v.get("target_metric", 40.0))))
            tm.s_target_metric.setEnabled(tm._video_metric_value() == 'xpsnr')
            tm.lbl_target_metric.setEnabled(tm._video_metric_value() == 'xpsnr')
        except Exception: pass
        tm.ck_vfade_in.setChecked(v.get("vfade_in", False))
        tm.s_vfade_in.setValue(v.get("vfade_in_d", 1.0))
        tm.ck_vfade_out.setChecked(v.get("vfade_out", False))
        tm.s_vfade_out.setValue(v.get("vfade_out_d", 1.0))
    except Exception as e:
        self.log(f"_load_settings(video) error: {e}")

    try:
        # Папка экспорта (пусто = рядом с исходником)
        tm.export_dir = m.get("export_dir", "") or ""
        try: tm._update_export_label()
        except Exception: pass
    except Exception as e:
        self.log(f"_load_settings(export_dir) error: {e}")

    try:
        y = s.get("ytdlp", {})
        saved_outdir = y.get("outdir", "")
        if saved_outdir and _api.os.path.isdir(saved_outdir):
            ty.out.setText(saved_outdir)
        ty.c_q.setCurrentText(y.get("quality", ty.c_q.currentText()))
        ty.c_c.setCurrentText(y.get("merge", ty.c_c.currentText()))
        ty.c_s.setCurrentText(y.get("sub_lang", ty.c_s.currentText()))
        ty.c_a.setCurrentText(y.get("audio", ty.c_a.currentText()))
        ty.chk_k.setChecked(y.get("force_kf", ty.chk_k.isChecked()))
        saved_cookie = y.get("cookie_path", "")
        if saved_cookie:
            ty.cookie_edit.setText(saved_cookie)
        saved_proxy = y.get("proxy", "")
        if saved_proxy:
            ty.proxy_edit.setText(saved_proxy)
    except Exception as e:
        self.log(f"_load_settings(ytdlp) error: {e}")

    try:
        av = s.get("avif", {})
        tm.s_lim.setValue(av.get("limit", tm.s_lim.value()))
        tm.ck_lim.setChecked(av.get("limit_on", True))
        tm.s_lim.setEnabled(tm.ck_lim.isChecked())
        tm.s_dim.setValue(av.get("adim", tm.s_dim.value()))
        tm.ck_dim.setChecked(av.get("adim_on", False))
        tm.s_dim.setEnabled(tm.ck_dim.isChecked())
        tm.s_width.setValue(av.get("awidth", tm.s_width.value()) or tm.s_width.value())
        tm.ck_width.setChecked(av.get("awidth_on", False))
        tm.s_width.setEnabled(tm.ck_width.isChecked())
        tm.s_height.setValue(av.get("aheight", tm.s_height.value()) or tm.s_height.value())
        tm.ck_height.setChecked(av.get("aheight_on", False))
        tm.s_height.setEnabled(tm.ck_height.isChecked())
        tm.sl_aspd.setValue(av.get("aspd", tm.sl_aspd.value()))
        tm.s_cq.setValue(av.get("cq", tm.s_cq.value()))
        tm.s_passes.setValue(av.get("fit_passes", 4))
        try: tm.c_priority.setCurrentText(s.get("priority", "Обычный"))
        except Exception: pass
        if hasattr(tm, "ck_overwrite_src"):
            tm.ck_overwrite_src.setChecked(av.get("overwrite_src", False))
        _api.combo_set_value(tm.c_img_fmt, av.get("img_fmt", "avif"))
        try:
            _chroma = str(av.get("chroma", "420"))
            _api.combo_set_value(tm.c_chroma, {"420": "4:2:0", "422": "4:2:2", "444": "4:4:4"}.get(_chroma, "4:2:0"))
        except Exception: pass
    except Exception as e:
        self.log(f"_load_settings(avif) error: {e}")

    # Обновляем стрип последних файлов по восстановленной папке
    try:
        self.recent_strip.refresh(ty.out.text())
    except Exception: pass

def _on_ipc_connection(self):
    try:
        conn = self._ipc_server.nextPendingConnection()
        if conn:
            conn.readyRead.connect(lambda: self._on_ipc_data(conn))
            conn.disconnected.connect(conn.deleteLater)
    except Exception: pass

def _on_ipc_data(self, conn):
    try:
        data = bytes(conn.readAll()).decode('utf-8', errors='replace')
        files = [f.strip() for f in data.splitlines() if f.strip() and _api.os.path.exists(f.strip())]
        if files:
            self.raise_(); self.activateWindow()
            self.tabs.setCurrentWidget(self.tab_media)
            self.tab_media.add_paths(files)
            self.log(f"Добавлено через контекстное меню: {', '.join(_api.os.path.basename(f) for f in files)}")
    except Exception: pass

# ------------------------------------------------------------------
# HTTP-сервер для браузерного расширения
# ------------------------------------------------------------------
def _on_url_from_browser(self, url: str, audio: bool):
    """Вызывается в Qt-потоке: URL от браузерного расширения или служебный сигнал скриншота."""
    try:
        if url.startswith("__screenshot_saved__"):
            fpath = url[len("__screenshot_saved__"):]
            self.log(f"📷 Скриншот сохранён: {fpath}")
            return
        self.tabs.setCurrentWidget(self.tab_ytdlp)
        self.tab_ytdlp.add_dl_direct(url, audio_only=audio)
        self.log(f"URL из браузера ({'аудио' if audio else 'видео'}): {url}")
    except Exception as e:
        self.log(f"_on_url_from_browser error: {e}")
