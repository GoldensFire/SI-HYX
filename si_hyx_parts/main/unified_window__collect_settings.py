# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""UnifiedWindow: _collect_settings. Public namespace: main."""
import main as _api


def _collect_settings(self):
    try:
        tm = self.tab_media; ty = self.tab_ytdlp
        s = {
            'media': {
                'audio': {
                    'remove': bool(tm.ck_no_audio.isChecked()),
                    'norm': bool(tm.ck_norm.isChecked()), 'tgt': float(tm.s_tgt.value()), 'lra': float(tm.s_lra.value()),
                    'tp': float(tm.s_tp.value()), 'fade': bool(tm.ck_fade.isChecked()), 'fade_d': float(tm.s_fade.value()),
                    'fade_in': bool(tm.ck_fade_in.isChecked()), 'fade_in_d': float(tm.s_fade_in.value()),
                    'deg': bool(tm.ck_deg.isChecked()), 'hz': int(tm.s_hz.value()), 'u8': bool(tm.ck_u8.isChecked()),
                    'lp': int(tm.s_lp.value()), 'hp': int(tm.s_hp.value()), 'deg_gain_db': float(tm.s_deg_gain.value()),
                    'bitrate': tm.c_abitrate.currentText()
                },
                'video': {
                    'enabled': bool(tm.chk_enable_video.isChecked()), 'speed': int(tm.s_spd.value()), 'crf': int(tm.s_crf.value()),
                    'pre': int(tm.s_pre.value()), 'res': _api.strip_default_tag(tm.c_res.currentText()), 'fps': tm.c_fps.currentText(),
                    'preset_mode': 'dark' if tm.btn_mode_dark.isChecked() else 'std',
                    'metric': tm._video_metric_value(), 'target_metric': float(tm.s_target_metric.value()),
                    'vfade_in': bool(tm.ck_vfade_in.isChecked()), 'vfade_in_d': float(tm.s_vfade_in.value()),
                    'vfade_out': bool(tm.ck_vfade_out.isChecked()), 'vfade_out_d': float(tm.s_vfade_out.value())
                },
                'export_dir': getattr(tm, 'export_dir', '') or ''
            },
            'ytdlp': {
                'outdir': ty.out.text(), 'quality': ty.c_q.currentText(), 'merge': ty.c_c.currentText(),
                'sub_lang': ty.c_s.currentText(), 'audio': ty.c_a.currentText(), 'force_kf': bool(ty.chk_k.isChecked()),
                'cookie_path': ty.cookie_edit.text().strip(),
                'proxy': ty.proxy_edit.text().strip(),
            },
            'avif': {
                'limit': int(tm.s_lim.value()), 'limit_on': bool(tm.ck_lim.isChecked()),
                'adim': int(tm.s_dim.value()), 'adim_on': bool(tm.ck_dim.isChecked()),
                'awidth': int(tm.s_width.value()), 'awidth_on': bool(tm.ck_width.isChecked()),
                'aheight': int(tm.s_height.value()), 'aheight_on': bool(tm.ck_height.isChecked()),
                'aspd': int(tm.sl_aspd.value()),
                'cq': int(tm.s_cq.value()),
                'overwrite_src': bool(tm.ck_overwrite_src.isChecked()) if hasattr(tm, 'ck_overwrite_src') else False,
                'fit_passes': int(tm.s_passes.value()),
                'img_fmt': _api.strip_default_tag(tm.c_img_fmt.currentText()),
                'chroma': _api.strip_default_tag(tm.c_chroma.currentText()).replace(':', '')
            },
            'server_enabled': bool(getattr(self, '_server_enabled', False)),
            'wheel_changes_values': bool(getattr(self, '_wheel_changes_values', False)),
            'video_hw_decode': bool(getattr(self, '_video_hw_decode', True)),
            'keep_models_in_ram': bool(getattr(self, '_keep_models_in_ram', False)),
            'advanced_encode_visible': bool(getattr(self, '_show_advanced_encode', False)),
            'siquester_tab_enabled': bool(getattr(self, '_siquester_tab_enabled', False)),
            'shikimori_tab_enabled': bool(getattr(self, '_shikimori_tab_enabled', False)),
            'shikimori': self._collect_shikimori_settings(),
            'leaderboard_tab_enabled': bool(getattr(self, '_leaderboard_tab_enabled', False)),
            'coop_tab_enabled': bool(getattr(self, '_coop_tab_enabled', False)),
            'coop': self._collect_coop_settings(),
            'animepack_tab_enabled': bool(getattr(self, '_animepack_tab_enabled', False)),
            'animepack': self._collect_animepack_settings(),
            'animepack_upgrade_tab_enabled': bool(
                getattr(self, '_animepack_upgrade_tab_enabled', False)),
            'animepack_upgrade': self._collect_animepack_upgrade_settings(),
            'prompt_tab_enabled': bool(getattr(self, '_prompt_tab_enabled', False)),
            'priority': tm.c_priority.currentText() if hasattr(tm, 'c_priority') else 'Обычный',
            'prompt_file': getattr(getattr(self, 'tab_prompt', None), '_prompt_path', '') or '',
            'api_keys': {k: str(v or '') for k, v in
                         (getattr(self, '_api_keys', {}) or {}).items()},
            'tab_order': list(getattr(self, '_tab_order', [])),
        }
        return s
    except Exception: return {}

def _warn_settings_readonly(self):
    """Один раз, уже после появления окна, сообщает, что настройки этого
        запуска не читаются и не сохраняются. Раньше это было полностью молча —
        пользователь видел «все настройки слетели» и, поработав в этом сеансе,
        получал дефолты на диске уже навсегда."""
    def _show():
        try:
            from msgbox import msgbox_warning
            msgbox_warning(
                self, "Настройки не прочитались",
                "Файл настроек существует, но открыть его сейчас не удалось "
                "(мог быть занят другой программой — например, антивирусом — "
                "или повреждён).\n\n"
                "Приложение работает на значениях по умолчанию, но НИЧЕГО не "
                "сохраняет: ваши настройки на диске не тронуты. Перезапустите "
                "программу — если файл снова читается, всё вернётся.")
        except Exception:
            pass
    try:
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(1500, _show)   # после того, как окно показано
    except Exception:
        pass

def _save_settings_now(self):
    if getattr(self, "_settings_readonly", False):
        # Настройки не прочитались при старте — см. _load_settings.
        self.log("save settings: настройки не прочитались при запуске — "
                 "сохранение отключено до перезапуска (файл не затёрт)")
        return
    try:
        data = self._collect_settings()
        # _collect_settings возвращает {} при любой ошибке (напр. после
        # изменения кода обращение к ещё не созданному виджету). НЕ пишем
        # пустой словарь — иначе settings.json затирается, и при следующем
        # запуске папка загрузчика и прочие настройки сбрасываются к дефолту.
        if not data:
            self.log("save settings: пустой результат сборки — пропуск (файл не затёрт)")
            return
        _api.save_settings(data)
    except Exception as e:
        self.log(f"save settings error: {e}")

def _save_settings_soon(self, *_args):
    """Отложенное сохранение (400 мс без изменений). Сохранение висит на
        КАЖДОМ поле, и протяжка ползунка раньше означала десятки полных
        перезаписей settings.json подряд — лишняя нагрузка на диск и лишние окна
        для сбоя ровно в момент подмены файла. Выход из программы и явные
        действия по-прежнему зовут _save_settings_now напрямую."""
    try:
        self._save_timer.start(400)
    except Exception:
        self._save_settings_now()

def _attach_save_handlers(self):
    try:
        self._save_timer = _api.QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._save_settings_now)
    except Exception:
        pass
    try:
        tm = self.tab_media
        ty = self.tab_ytdlp
        # Виджеты с сигналом toggled (QCheckBox, QPushButton checkable)
        toggle_widgets = [
            tm.ck_no_audio,
            tm.ck_norm, tm.ck_fade, tm.ck_fade_in, tm.ck_deg, tm.ck_u8,
            tm.chk_enable_video, tm.btn_mode_dark,
            tm.ck_overwrite_src,
            tm.ck_lim, tm.ck_dim,
            tm.ck_vfade_in, tm.ck_vfade_out,
            ty.chk_k,
        ]
        # Виджеты с сигналом valueChanged (QSpinBox, QDoubleSpinBox, QSlider)
        value_widgets = [
            tm.s_tgt, tm.s_lra, tm.s_tp, tm.s_fade, tm.s_fade_in,
            tm.s_hz, tm.s_lp, tm.s_hp, tm.s_deg_gain,
            tm.s_spd, tm.s_crf, tm.s_pre,
            tm.s_lim, tm.s_dim, tm.sl_aspd, tm.s_cq, tm.s_passes,
            tm.s_vfade_in, tm.s_vfade_out,
        ]
        # Виджеты с сигналом currentTextChanged (QComboBox)
        combo_widgets = [
            tm.c_abitrate, tm.c_res, tm.c_fps, tm.c_tune, tm.c_img_fmt, tm.c_priority,
            ty.c_q, ty.c_c, ty.c_s, ty.c_a,
        ]
        # Виджет с сигналом textChanged (QLineEdit)
        text_widgets = [ty.out, ty.cookie_edit, ty.proxy_edit]

        for w in toggle_widgets:
            w.toggled.connect(self._save_settings_soon)
        for w in value_widgets:
            w.valueChanged.connect(self._save_settings_soon)
        for w in combo_widgets:
            w.currentTextChanged.connect(self._save_settings_soon)
        for w in text_widgets:
            w.textChanged.connect(self._save_settings_soon)
    except Exception as e:
        self.log(f"_attach_save_handlers error: {e}")

def dragEnterEvent(self, e):
    if e.mimeData().hasUrls(): e.accept()
    else: e.ignore()

def dropEvent(self, e):
    try:
        self.raise_(); self.activateWindow()
        files = [u.toLocalFile() for u in e.mimeData().urls() if u.toLocalFile()]
        if files:
            self.tabs.setCurrentWidget(self.tab_media); self.tab_media.add_paths(files)
    except Exception: pass

def update_global_progress(self, val, text):
    # val < 0 → неопределённый («busy») режим: полоса пульсирует. Нужен для
    # фаз, где реального процента нет (перемотка декодера до точки реза при
    # обрезке с перекодированием), чтобы полоса не выглядела зависшей на 0%.
    if val is None or val < 0:
        if self.pbar.maximum() != 0:
            self.pbar.setRange(0, 0)
        self.pbar.setFormat(text)
        self.set_taskbar_progress(0, 0)   # indeterminate в панели задач
        return
    if self.pbar.maximum() == 0:          # вернуть из busy в обычный режим
        self.pbar.setRange(0, 100)
    self.pbar.setValue(val); self.pbar.setFormat(text)
    # Зеркалим прогресс перекодирования на иконку в панели задач.
    # ВАЖНО: val==0 — это «простаивает/завершилось/ошибка/отменено», НЕ занятость.
    # set_value(…,0,100) трактует completed<=0 как INDETERMINATE (бегущий бар),
    # из-за чего после ошибки/отмены на иконке вечно «крутился» процесс. Поэтому
    # на 0 (и на ≥100) индикатор УБИРАЕМ, а не оставляем пульсировать.
    if val >= 100 or val <= 0:
        self.clear_taskbar_progress()
    else:
        self.set_taskbar_progress(val, 100)

def _tb_hwnd(self):
    """HWND окна для ITaskbarList3 (кэшируем; winId валиден после создания окна)."""
    if not self._taskbar_hwnd:
        try: self._taskbar_hwnd = int(self.winId())
        except Exception: self._taskbar_hwnd = 0
    return self._taskbar_hwnd

def set_taskbar_progress(self, completed, total=100):
    """Показать прогресс длительной задачи на иконке приложения."""
    try: self._taskbar.set_value(self._tb_hwnd(), completed, total)
    except Exception: pass

def clear_taskbar_progress(self):
    try: self._taskbar.clear(self._tb_hwnd())
    except Exception: pass

def _sync_console_visibility(self, index=None):
    """Нижняя консоль и прогрессбар. Консоль скрыта на «Монтаж» и
        «SiQuesterHYX» (там она лишь занимает место). Прогрессбар скрыт на
        «SiQuesterHYX» (на «Монтаж» он нужен для прогресса экспорта).

        Принимает индекс явно (а не только через currentChanged), чтобы можно
        было спрятать консоль ДО фактического показа страницы — иначе видео на
        «Монтаж» сперва рисуется в старой (с консолью) высоте и тут же
        дёргается на новую, бóльшую — см. _on_tab_bar_clicked."""
    try:
        cur = self.tabs.widget(index) if isinstance(index, int) else self.tabs.currentWidget()
        is_edit = cur is self.tab_edit
        tsq = getattr(self, "tab_siquester", None)
        is_siq = tsq is not None and cur is tsq
        tsh = getattr(self, "tab_shikimori", None)
        is_shiki = tsh is not None and cur is tsh
        tlb = getattr(self, "tab_leaderboard", None)
        is_lb = tlb is not None and cur is tlb
        tcp = getattr(self, "tab_coop", None)
        is_coop = tcp is not None and cur is tcp
        is_photo = cur is getattr(self, "tab_photo", None)
        self.console_panel.setVisible(not (is_edit or is_siq or is_shiki or is_lb or is_coop or is_photo))
        show_progress = not (is_siq or is_shiki or is_lb or is_coop or is_photo)
        self.pbar.setVisible(show_progress)
    except Exception:
        pass

def _on_tab_bar_clicked(self, index):
    """Вызывается ДО того, как QTabBar реально переключит страницу.
        Прячем/показываем консоль здесь же, но с отключённой перерисовкой окна —
        иначе старая вкладка (например «Обработка», где консоль видна) успевает
        на мгновение перерисоваться в увеличенной высоте ДО самого переключения
        на «Монтаж» (это отдельный кадр, который тот же currentChanged/showEvent
        уже не поймать), и глаз ловит этот промежуточный прыжок холста."""
    self.setUpdatesEnabled(False)
    try:
        self._sync_console_visibility(index)
    finally:
        _api.QTimer.singleShot(0, lambda: self.setUpdatesEnabled(True))

def eventFilter(self, obj, event):
    # Держим кнопку-значок «развернуть консоль» прижатой к правому верхнему
    # углу консоли при её ресайзе/показе.
    if obj is getattr(self, "txt_log", None) and event.type() in (
            _api.QEvent.Type.Resize, _api.QEvent.Type.Show):
        self._reposition_console_btn()
    if obj is getattr(self, "pbar", None) and event.type() in (
            _api.QEvent.Type.Resize, _api.QEvent.Type.Show):
        self._position_progress_button()
    bar = self.tabs.tabBar() if getattr(self, "tabs", None) is not None else None
    if bar is not None and obj is bar:
        et = event.type()
        if et == _api.QEvent.Type.MouseMove:
            try: self._update_tab_tip(event.position().toPoint())
            except Exception: pass
        elif et in (_api.QEvent.Type.Leave, _api.QEvent.Type.Hide,
                    _api.QEvent.Type.WindowDeactivate):
            self._hide_tab_tip()
        elif et == _api.QEvent.Type.DragEnter:
            if self._tab_drag_has_files(event):
                event.acceptProposedAction(); return True
        elif et == _api.QEvent.Type.DragMove:
            if self._tab_drag_has_files(event):
                try: self._tab_drag_hover(bar, event.position().toPoint())
                except Exception: pass
                event.acceptProposedAction(); return True
        elif et == _api.QEvent.Type.DragLeave:
            self._tab_drag_idx = -1
            self._tab_drag_timer.stop()
        elif et == _api.QEvent.Type.Drop:
            if self._tab_drag_has_files(event):
                try: self._tab_drag_drop(bar, event)
                except Exception as e:
                    try: self.log(f"tab drop error: {e}")
                    except Exception: pass
                event.acceptProposedAction(); return True
        elif et == _api.QEvent.Type.Wheel:
            self._tab_wheel_scroll(event)
            return True
    return super(_api.UnifiedWindow, self).eventFilter(obj, event)
