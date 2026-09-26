# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""AnimePackTab: apply_settings. Public namespace: animepack_tab."""
from __future__ import annotations
import animepack_tab as _api


def apply_settings(self, data: dict):
    if not _api._HAS_CORE or not isinstance(data, dict):
        return
    s = _api.PackSettings.from_dict(data)
    self.ed_title.setText(s.title)
    self.ed_theme.setText(s.theme_title)
    # Сколько паков уже собрано: следующий получит номер на единицу больше.
    self._pack_number = max(0, int(getattr(s, "pack_number", 0) or 0))
    self.sp_rounds.setValue(s.rounds)
    self.sp_themes.setValue(s.themes)
    self.sp_quest.setValue(s.questions)
    shiki_random = bool(s.random_mode and s.random_source == "shikimori")
    for chk, value in ((self.chk_random, s.random_mode and not shiki_random),
                       (self.chk_random_shiki, shiki_random)):
        chk.blockSignals(True)
        chk.setChecked(value)
        chk.blockSignals(False)
    self._clear_user_cards()
    for u in s.users:
        self._add_user_card(u)
    self._saved_users = list(s.saved_users)
    self._exclude_siq = list(s.exclude_siq)
    self._refresh_exclude_label()
    self._exclude_exact_siq = list(getattr(s, "exclude_exact_siq", []))
    self._refresh_exact_label()
    self.sp_similar.setValue(max(1, int(s.similar_count)))
    self.chk_mark_owners.blockSignals(True)
    self.chk_mark_owners.setChecked(bool(s.mark_owners))
    self.chk_mark_owners.blockSignals(False)
    # Галочки необязательных частей — ДО долей: они решают, есть ли в полосе
    # такие части (иначе сохранённые проценты уехали бы в песни).
    self.chk_video.setChecked(s.song_video)
    self.mix.set_video(s.song_video)
    self.chk_manga.setChecked(s.pack_manga)
    self.mix.set_manga(s.pack_manga)
    self.chk_pixel.setChecked(s.pack_pixel)
    self.mix.set_pixel(s.pack_pixel)
    self.chk_anagram.setChecked(s.pack_anagram)
    self.mix.set_anagram(s.pack_anagram)
    self.chk_plot.setChecked(s.pack_plot)
    self.mix.set_plot(s.pack_plot)
    from .dialogue_controls import apply as apply_dialogue
    apply_dialogue(self, s)
    self.chk_ai_art.setChecked(s.pack_ai_art)
    self.mix.set_ai_art(s.pack_ai_art)
    self.chk_pixiv_art.setChecked(s.pack_pixiv_art)
    self.mix.set_pixiv_art(s.pack_pixiv_art)
    self.chk_sakuga.setChecked(s.pack_sakuga)
    self.mix.set_sakuga(s.pack_sakuga)
    self.chk_studio.setChecked(s.pack_studio)
    self.mix.set_studio(s.pack_studio)
    from .composition_controls import apply, TITLE_LABELS
    apply(self, s)
    shares = s.mix_shares
    self.mix.set_shares({
        "songs": shares.get("songs", 0), "video": shares.get(_api.VIDEO_KIND, 0),
        "frames": shares.get(_api.FRAME_KIND, 0),
        "chars": shares.get(_api.CHAR_KIND, 0),
        "manga": shares.get(_api.MANGA_KIND, 0),
        "pixel": shares.get(_api.PIXEL_KIND, 0),
        "anagram": shares.get(_api.ANAGRAM_KIND, 0),
        "plot": shares.get(_api.PLOT_KIND, 0),
        "dialogue": shares.get(_api.DIALOGUE_KIND, 0),
        "ai_art": shares.get(_api.AI_ART_KIND, 0),
        "pixiv_art": shares.get(_api.PIXIV_ART_KIND, 0),
        "sakuga": shares.get(_api.SAKUGA_KIND, 0),
        "studio": shares.get(_api.STUDIO_KIND, 0),
        **{k: shares.get(k, 0) for k in TITLE_LABELS}})
    from si_hyx_parts.animepack_tab.ai_art_controls import apply_controls
    apply_controls(self, s)
    from si_hyx_parts.animepack_tab.pixiv_art_controls import apply_controls
    apply_controls(self, s)
    from si_hyx_parts.animepack_tab.sakuga_controls import apply_controls
    apply_controls(self, s)
    from si_hyx_parts.animepack_tab.studio_controls import apply_controls
    apply_controls(self, s)
    self.sp_pixel_sec.setValue(max(2, int(s.pixel_seconds or _api.PIXEL_SECONDS)))
    self.sp_pixel_fps.setValue(max(1, min(60, int(s.pixel_fps or _api.PIXEL_FPS))))
    self.sp_pixel_steps.setValue(max(1, min(20, int(s.pixel_steps or _api.PIXEL_STEPS))))
    self.sp_pixel_block.setValue(max(4, min(256, int(s.pixel_block or _api.PIXEL_BLOCK))))
    from si_hyx_parts.animepack_tab.frame_effect_controls import apply_controls
    apply_controls(self, s)
    idx = self.cb_anagram_lang.findData(s.anagram_lang)
    self.cb_anagram_lang.setCurrentIndex(idx if idx >= 0 else 0)
    self.sp_anagram_max.setValue(
        max(0, min(200, int(getattr(s, "anagram_max_chars", _api.ANAGRAM_MAX_CHARS)
                            or 0))))
    try:
        cps = float(getattr(s, "anagram_cps", _api.ANAGRAM_CHARS_PER_SEC) or 0.0)
    except (TypeError, ValueError):
        cps = _api.ANAGRAM_CHARS_PER_SEC
    self.sp_anagram_cps.setValue(max(0.0, min(_api.ANAGRAM_CPS_MAX, cps)))
    idx = self.cb_plot_mode.findData(s.plot_mode)
    self.cb_plot_mode.setCurrentIndex(idx if idx >= 0 else 0)
    self._migrate_api_key("gemini", s.gemini_key)
    if s.gemini_model:
        if self.cb_gemini_model.findText(s.gemini_model) < 0:
            self.cb_gemini_model.addItem(s.gemini_model, s.gemini_model)
        self.cb_gemini_model.setCurrentText(s.gemini_model)
    # Список уровней зависит от модели (у Flash нет «минимального»), поэтому
    # сперва пересобираем его под уже выбранную модель, а недоступный уровень
    # заменяем ближайшим доступным — первым в списке.
    from si_hyx_parts.animepack_tab.gemini_model_controls import (
        refresh_thinking_levels)
    refresh_thinking_levels(self)
    idx = self.cb_gemini_think.findData(
        str(getattr(s, "gemini_thinking", "") or _api.GEMINI_THINKING_LEVEL))
    if idx < 0:
        idx = self.cb_gemini_think.findData(_api.GEMINI_THINKING_LEVEL)
    self.cb_gemini_think.setCurrentIndex(max(0, idx))
    # То же самое для своей модели загадок по названию. Пустое значение в
    # старых settings.json значит «как у сюжета».
    title_model = str(getattr(s, "gemini_title_model", "") or "") or s.gemini_model
    if title_model:
        if self.cb_gemini_title_model.findText(title_model) < 0:
            self.cb_gemini_title_model.addItem(title_model, title_model)
        self.cb_gemini_title_model.setCurrentText(title_model)
    from si_hyx_parts.animepack_tab.gemini_title_controls import refresh_levels
    refresh_levels(self)
    idx = self.cb_gemini_title_think.findData(
        str(getattr(s, "gemini_title_thinking", "") or "")
        or str(getattr(s, "gemini_thinking", "") or _api.GEMINI_THINKING_LEVEL))
    if idx < 0:
        idx = self.cb_gemini_title_think.findData(_api.GEMINI_THINKING_LEVEL)
    self.cb_gemini_title_think.setCurrentIndex(max(0, idx))
    self._migrate_api_key("tmdb", getattr(s, "tmdb_key", ""))
    self.chk_poster_cache.setChecked(bool(getattr(s, "poster_cache", True)))
    self._on_poster_cache_toggled(self.chk_poster_cache.isChecked())
    self.sp_video_cut.setValue(max(3, int(s.video_cut)))
    self.sp_video_crf.setValue(max(0, min(63, int(s.video_crf))))
    self.sp_video_preset.setValue(max(0, min(13, int(s.video_preset))))
    idx = self.cb_char_roles.findData(s.char_roles)
    self.cb_char_roles.setCurrentIndex(idx if idx >= 0 else
                                       self.cb_char_roles.findData("both"))
    idx = self.cb_manga_lang.findData(str(getattr(s, "manga_lang", "") or ""))
    self.cb_manga_lang.setCurrentIndex(idx if idx >= 0 else 0)
    self.chk_manga_erotica.setChecked(
        bool(getattr(s, "manga_allow_erotica", False)))
    from si_hyx_parts.animepack_tab.manga_gemini_controls import apply_controls as apply_manga_gemini
    apply_manga_gemini(self, s)
    for kind, chk in self.chk_manga_kinds.items():
        chk.setChecked(bool(s.manga_kinds.get(kind, False)))
    self.chk_op.setChecked(s.pick_openings)
    self.chk_ed.setChecked(s.pick_endings)
    self.chk_in.setChecked(s.pick_inserts)
    # Галочки уже переставили набор частей полосы — теперь её значения.
    self._on_song_kinds_toggled()
    self.kind_bar.set_values({"opening": s.openings, "ending": s.endings,
                              "insert": s.inserts})
    self.sp_diff_min.setValue(int(s.difficulty_min))
    self.sp_diff_max.setValue(int(s.difficulty_max))
    saved_ost_min = getattr(s, "ost_difficulty_min", None)
    saved_ost_max = getattr(s, "ost_difficulty_max", None)
    ost_min = s.difficulty_min if saved_ost_min is None else saved_ost_min
    ost_max = s.difficulty_max if saved_ost_max is None else saved_ost_max
    self.sp_ost_diff_min.setValue(int(ost_min))
    self.sp_ost_diff_max.setValue(int(ost_max))
    # Полоса рамки меняется без сигнала (set_range нарочно молчит), поэтому
    # строчку «какая рамка на какой тип песни» обновляем здесь сами.
    self._refresh_diff_bands()
    for cat, chk in self.chk_categories.items():
        chk.setChecked(bool(s.categories.get(cat, True)))
    self.chk_rebroadcast.setChecked(s.allow_rebroadcast)
    self.chk_dub.setChecked(s.allow_dub)
    self.level_range.set_range(max(1, min(_api.MAX_LEVEL, int(s.level_min))),
                               max(1, min(_api.MAX_LEVEL, int(s.level_max))))
    self.sp_level_avg.setValue(
        max(0, min(_api.MAX_LEVEL, int(s.level_avg))))
    from .level_controls import apply_controls as apply_levels
    apply_levels(self, s)
    self.sp_score_from.setValue(float(s.score_from))
    self.sp_score_to.setValue(float(s.score_to))
    for kind, chk in self.chk_kinds.items():
        chk.setChecked(bool(s.kinds.get(kind, True)))
    self.sp_year_from.setValue(int(s.year_from))
    self.sp_year_to.setValue(int(s.year_to))
    # Жанры подставим, когда придёт их список (id проверяются по нему).
    self._pending_genres = list(s.genres_include)
    self._pending_excl = list(s.genres_exclude)
    self._apply_pending_genres()
    self.chk_genres_partial.setChecked(s.genres_partial)
    self.chk_sort_index.setChecked(s.sort_by_index)
    self.chk_images.setChecked(s.images)
    self.sp_images_time.setValue(int(s.images_time))
    self.sp_answer_img.setValue(
        max(0, min(_api.ANSWER_IMAGE_MAX, int(s.answer_image_time))))
    self.chk_compress_audio.setChecked(s.compress_audio)
    from .music_effect_controls import apply_controls
    apply_controls(self, s)
    from .cover_controls import apply_controls as apply_cover_controls
    apply_cover_controls(self, s)
    self.chk_compress_images.setChecked(s.compress_images)
    self.sp_img_kb.setValue(max(20, int(s.image_limit_kb)))
    self.sp_img_speed.setValue(max(0, min(8, int(s.image_speed))))
    self.chk_shuffle.setChecked(s.shuffle_questions)
    self.sp_cut.setValue(int(s.audio_cut))
    self.sp_parallel.setValue(int(s.parallel))
    self._out_dir = s.out_dir or ""
    self._refresh_out_dir_label()
    # Доли списков: галочка включается сама, если в настройках они заданы.
    # Значения ставим на полосу из ФАЙЛА, а не из карточек: пока карточки
    # добавлялись по одной, полоса успела раздать им свои доли.
    saved_shares = {self._share_key(u): int(u.share or 0) for u in s.users}
    self.chk_shares.blockSignals(True)
    self.chk_shares.setChecked(any(saved_shares.values()))
    self.chk_shares.blockSignals(False)
    self.share_bar.setVisible(self.chk_shares.isChecked())
    self._refresh_share_bar()
    if any(saved_shares.values()):
        self.share_bar.set_values(saved_shares)
        self._on_share_bar_changed()
    self._refresh_lists_visibility()
    self._refresh_song_opts()
    self._on_compress_images_toggled(s.compress_images)
    self._on_video_toggled(s.song_video)
    self._on_manga_toggled(s.pack_manga)
    self._on_pixel_toggled(s.pack_pixel)
    self._on_anagram_toggled(s.pack_anagram)
    self._on_plot_toggled(s.pack_plot)
    self._on_song_kinds_toggled()
    self._refresh_pixel_hint()
    self._recount()

def reset_settings(self):
    self._sel_genres = []
    self._excl_genres = []
    # Адресную книгу сброс настроек не трогает: ники копятся годами, а
    # кнопка обещает вернуть настройки, а не стереть накопленное.
    saved = list(self._saved_users)
    self.apply_settings(_api.PackSettings().to_dict())
    self._saved_users = saved
    self._update_genres_btn()

# ── генерация ─────────────────────────────────────────────────────────
def log(self, msg: str):
    """Всё пишем в общую консоль внизу окна — своей у вкладки нет."""
    if self.main is not None and hasattr(self.main, "log"):
        try:
            self.main.log(f"[Аниме-пак] {msg}")
        except Exception:
            pass

def _log_gap(self, lines: int = 5):
    """Пустые строки перед логами нового прогона — чтобы их было видно."""
    main = self.main
    if main is None:
        return
    try:
        if hasattr(main, "log_gap"):
            main.log_gap(lines)
        else:                              # старое главное окно без отбивки
            for _ in range(lines):
                main.txt_log.append("")
    except Exception:
        pass

def start(self):
    if self._task is not None:
        return
    if self._db_task is not None:
        _api.msgbox_information(self, "Секунду",
                           "Сейчас обновляется база Shikimori — дождитесь "
                           "конца или остановите сбор той же кнопкой, иначе "
                           "пак соберётся по полупустому каталогу.")
        return
    settings = self.collect()
    problems = settings.validate()
    if problems:
        _api.msgbox_warning(self, "Так не получится", "\n\n".join(problems))
        return
    # Каждый новый пак — следующий номер в названии (просьба пользователя).
    # Считаем ЗДЕСЬ, а не в генераторе: имя файла и название внутри пака должны
    # совпасть, а известны они генератору с самого начала. Сохраняем сразу —
    # иначе аварийное закрытие программы вернуло бы нумерацию назад.
    #
    # ОТМЕНЁННАЯ генерация номер возвращает (см. _release_pack_number): пак,
    # который бросили на середине, — не пак, и следующий не должен через него
    # перешагивать.
    self._pack_number = int(getattr(self, "_pack_number", 0) or 0) + 1
    settings.pack_number = self._pack_number
    saver = getattr(self.main, "_save_settings_soon", None)
    if saver is not None:
        try:
            saver()
        except Exception:      # noqa: BLE001 — номер важнее, чем запись
            pass
    self._remember_users(settings.users)
    if self.main is not None and hasattr(self.main, "clear_global_result"):
        self.main.clear_global_result()
    self.table.setRowCount(0)
    self._update_table_hint()
    self.btn_table.setEnabled(False)
    self.btn_table.setText("Показать таблицу")
    self._last_pack = ""
    self.btn_open.setEnabled(False)
    self.btn_start.setEnabled(False)
    self.btn_stop.setEnabled(True)
    self._started_at = _api.time.monotonic()
    self._progress(0, "Подготовка…")
    # Отбивка в пять пустых строк: журнал общий на всё приложение, и без неё
    # логи нового пака сливались с прошлыми (просьба пользователя).
    self._log_gap()
    self.log(f"Собираю пак «{settings.title}»: {settings.total_questions} "
             "вопросов.")

    task = _api._GenTask(settings)
    task.signals.log.connect(self.log)
    task.signals.progress.connect(self._on_progress)
    task.signals.finished.connect(self._on_finished)
    task.signals.failed.connect(self._on_failed)
    self._task = task
    self._pool.start(task)

def stop(self):
    if self._task is not None:
        self._task.stop()
        self._progress(0, "Останавливаюсь…")
        self.btn_stop.setEnabled(False)

def _progress(self, pct: int, text: str) -> None:
    """Своей полосы у вкладки нет — пишем в общую, внизу окна. Она же и
        строка состояния вкладки: отдельной подписи над таблицей больше нет."""
    if self.main is None or not hasattr(self.main, "update_global_progress"):
        return
    try:
        self.main.update_global_progress(max(0, min(100, int(pct))), text)
    except Exception:
        pass

def _on_progress(self, done: int, total: int, msg: str):
    """Счётчик, чем генератор занят прямо сейчас и оставшееся время.

        Названия тайтлов на полосе по-прежнему нет — они мелькали слишком
        быстро, чтобы их прочитать, и для них есть журнал. А вот РОД вопроса
        («Сакуга», «Кадр», «Манга») там нужен: по нему сразу видно, на чём
        генерация встала (просьба пользователя)."""
    total = max(1, total)
    if done <= 0:
        self._progress(0, msg or f"0/{total}")
        return
    text = f"{done}/{total}"
    if msg:
        text += f" · {msg}"
    eta = self._eta(done, total)
    if eta:
        text += f" — осталось {eta}"
    self._progress(int(done * 100 / total), text)

def _eta(self, done: int, total: int) -> str:
    """Оценка остатка по средней скорости с начала генерации. Первые
        несколько вопросов не в счёт: пока качается база и разгоняется пул
        загрузок, средняя скорость врёт в разы."""
    if not self._started_at or done < 3 or done >= total:
        return ""
    spent = _api.time.monotonic() - self._started_at
    if spent <= 0:
        return ""
    return _api.fmt_elapsed(spent / done * (total - done))

def _finish_ui(self):
    self._task = None
    self.btn_start.setEnabled(True)
    self.btn_stop.setEnabled(False)

def _release_pack_number(self, number) -> None:
    """Возвращает номер, выданный в start(), — пака под ним не вышло.

        Отменённый и упавший прогон нумерацию не двигают (просьба
        пользователя): иначе после пары остановок следующий собранный пак
        получал «№ 7» вместо «№ 4». Возвращаем ТОЛЬКО свой, последний выданный
        номер: пока генерация шла, человек мог сменить его руками в настройках,
        и затирать чужое значение нельзя."""
    try:
        issued = int(number or 0)
    except (TypeError, ValueError):
        return
    if issued <= 0 or int(getattr(self, "_pack_number", 0) or 0) != issued:
        return
    self._pack_number = issued - 1
    saver = getattr(self.main, "_save_settings_soon", None)
    if saver is not None:
        try:
            saver()
        except Exception:      # noqa: BLE001 — номер важнее, чем запись
            pass

def _on_failed(self, err: str):
    self._release_pack_number(getattr(self, "_pack_number", 0))
    self._finish_ui()
    self._progress(0, "Не получилось")
    self.log(f"Ошибка: {err}")
    _api.msgbox_critical(self, "Генерация не удалась", err)

def _on_finished(self, result):
    self._finish_ui()
    self._fill_table(result.songs)
    spent = _api.fmt_elapsed(getattr(result, "elapsed", 0.0))
    if result.cancelled:
        self._release_pack_number(getattr(result, "pack_number", 0))
        if result.path:
            self._last_pack = result.path
            self.btn_open.setEnabled(True)
            if self.main is not None and hasattr(self.main, "set_global_result"):
                self.main.set_global_result(result.path)
            self._progress(100, f"Частичный пак: {len(result.songs)} вопросов")
            self.log(f"Генерация остановлена; сохранено {len(result.songs)} "
                     f"вопросов из {result.requested}: {result.path}")
        else:
            self._progress(0, "Остановлено")
            self.log("Генерация остановлена до первого готового вопроса.")
        return
    self._last_pack = result.path
    self.btn_open.setEnabled(bool(result.path))
    if self.main is not None and hasattr(self.main, "set_global_result"):
        self.main.set_global_result(result.path)
    # Итог пишем прямо на полосу вместо голого «Готово»: своей строки
    # состояния у вкладки больше нет (просьба пользователя).
    self._progress(100, f"Готово за {spent}: "
                        f"{_api.os.path.basename(result.path)}")
    self.log(f"Пак собран за {spent}: {result.path}")
    if len(result.songs) < result.requested:
        self.log(f"Вопросов получилось {len(result.songs)} из "
                 f"{result.requested} — кандидатов не хватило.")
