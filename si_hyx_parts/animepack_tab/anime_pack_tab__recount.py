# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""AnimePackTab: _recount. Public namespace: animepack_tab."""
from __future__ import annotations
import animepack_tab as _api


def _recount(self, *_):
    total = self.sp_rounds.value() * self.sp_themes.value() * self.sp_quest.value()
    self.lbl_total.setText(f"Вопросов в паке: {total}")
    if getattr(self, "cb_char_roles", None) is None:
        return                       # панель ещё строится
    settings = self.collect()
    if (settings.songs_percent
            and not any(chk.isChecked() for chk in
                        (self.chk_op, self.chk_ed, self.chk_in))):
        self.lbl_left.setText("Не выбран ни один тип песни — включите "
                              "опенинги, эндинги или OST.")
        self.lbl_left.setStyleSheet(f"color:{_api.C['yellow']}; font-size:11px;")
        return
    # Ровно по одной строке на всё, что будет в паке (просьба пользователя):
    # «Кадров N, Опенингов N, Эндингов N, OST N, Персонажей N, Видео N».
    # Считает те же question_quotas, что и генератор, — цифры на вкладке и
    # в паке не расходятся.
    quotas = settings.question_quotas
    parts = ", ".join(f"{self.COUNT_LABELS[k]} — {quotas.get(k, 0)}"
                      for k in self.COUNT_ORDER if quotas.get(k, 0))
    from .composition_controls import TITLE_LABELS
    extra = [f"{label} — {quotas.get(k, 0)}" for k, label in TITLE_LABELS.items() if quotas.get(k, 0)]
    if extra:
        parts += ", " + ", ".join(extra)
    # Приписки «Цены — по индексу популярности» тут больше нет: она висела
    # зелёным над всей панелью и ничего не подсказывала (просьба пользователя).
    if not parts:
        # Состав сняли целиком — раньше строка превращалась в одинокую точку
        # («» + «.»), и наверху панели висел непонятный знак препинания.
        self.lbl_left.setText("В составе пака ничего не выбрано — включите "
                              "хотя бы один род вопросов.")
        self.lbl_left.setStyleSheet(f"color:{_api.C['yellow']}; font-size:11px;")
        return
    self.lbl_left.setText(parts + ".")
    self.lbl_left.setStyleSheet(f"color:{_api.C['green']}; font-size:11px;")

def _refresh_out_dir_label(self):
    if self._out_dir:
        self.lbl_out_dir.setText(f"Пак сохранится в: {self._out_dir}")
    else:
        try:
            from utils import default_download_dir
            where = default_download_dir()
        except Exception:
            where = "папка загрузок"
        self.lbl_out_dir.setText(f"Пак сохранится в: {where}")

def _choose_out_dir(self):
    start = self._pack_picker_start()
    path = _api.QFileDialog.getExistingDirectory(self, "Куда сохранять пак", start)
    if path:
        self._out_dir = path
        self._refresh_out_dir_label()

# ── жанры ─────────────────────────────────────────────────────────────
def _load_genres_async(self):
    if self._closing or self._genres_task is not None or self._genres_items:
        return
    task = _api._GenresTask()
    task.signals.finished.connect(self._on_genres_loaded)
    task.signals.failed.connect(self._on_genres_failed)
    self._genres_task = task
    self._pool.start(task)

def _on_genres_loaded(self, genres: list):
    self._genres_task = None
    try:
        from shikimori_api import genre_group
    except Exception:
        def genre_group(_g):
            return "genre"
    items = []
    for g in genres:
        gid = g.get("id")
        if gid is None:
            continue
        items.append((int(gid), g.get("russian") or g.get("name") or str(gid),
                      genre_group(g)))
    items.sort(key=lambda x: x[1].lower())
    self._genres_items = items
    self._apply_pending_genres()

def _apply_pending_genres(self):
    """Восстановленные из настроек id жанров применяем только после того,
        как пришёл их список — иначе нечем проверить, что такой жанр есть."""
    if not self._genres_items:
        return
    valid = {gid for gid, _, _ in self._genres_items}
    if self._pending_genres:
        self._sel_genres = [g for g in self._pending_genres if g in valid]
        self._pending_genres = []
    if self._pending_excl:
        self._excl_genres = [g for g in self._pending_excl if g in valid]
        self._pending_excl = []
    self._update_genres_btn()

def _on_genres_failed(self, err: str):
    self._genres_task = None
    self.log(f"Список жанров не загрузился: {err}")

def _open_genre_picker(self):
    if not self._genres_items:
        self._load_genres_async()
        _api.msgbox_information(self, "Жанры и темы",
                           "Список жанров ещё загружается — повторите через "
                           "секунду.")
        return
    from shikimori_tab import _GenrePickerDialog
    dlg = _GenrePickerDialog(self._genres_items, self._sel_genres,
                             self._excl_genres, self)
    if dlg.exec():
        self._sel_genres = dlg.selected_ids()
        self._excl_genres = dlg.excluded_ids()
        self._update_genres_btn()

def _update_genres_btn(self):
    names = {gid: label for gid, label, _ in self._genres_items}
    inc = [names.get(g, str(g)) for g in self._sel_genres]
    exc = [names.get(g, str(g)) for g in self._excl_genres]
    if not inc and not exc:
        self.btn_genres.setText("Жанры: любые")
        return
    parts = []
    if inc:
        parts.append("✓ " + ", ".join(inc[:2]) + ("…" if len(inc) > 2 else ""))
    if exc:
        parts.append("✕ " + ", ".join(exc[:2]) + ("…" if len(exc) > 2 else ""))
    self.btn_genres.setText("Жанры: " + "; ".join(parts))

# ── настройки ─────────────────────────────────────────────────────────
def collect(self) -> '_api.PackSettings':
    s = _api.PackSettings()
    s.title = self.ed_title.text().strip() or "Сгенерировано в SI-HYX"
    s.rounds = self.sp_rounds.value()
    s.themes = self.sp_themes.value()
    s.questions = self.sp_quest.value()
    s.theme_title = self.ed_theme.text().strip()
    # Сколько паков уже собрано: следующий получит номер на единицу больше
    # (см. start и pack_summary.numbered_title).
    s.pack_number = int(getattr(self, "_pack_number", 0) or 0)
    s.test_pack_number = int(getattr(self, "_test_pack_number", 0) or 0)
    s.random_mode = (self.chk_random.isChecked()
                     or self.chk_random_shiki.isChecked())
    s.random_source = ("shikimori" if self.chk_random_shiki.isChecked()
                       else "amq")
    s.users = [c.value() for c in self._user_cards]
    # Заодно пополняем книгу: collect() зовётся и при сохранении настроек,
    # так что ник не потеряется, даже если генерацию ни разу не запускали.
    self._remember_users(s.users)
    s.saved_users = list(self._saved_users)
    s.exclude_siq = list(self._exclude_siq)
    s.exclude_exact_siq = list(self._exclude_exact_siq)
    s.auto_add_to_exclusions = self.chk_auto_add_exclusions.isChecked()
    s.ignore_test_packs = self.chk_ignore_test_packs.isChecked()
    s.similar_count = self.sp_similar.value()
    from .composition_controls import collect
    collect(self, s)
    shares = self.mix.shares()
    (s.pct_songs, s.pct_videos, s.pct_frames,
     s.pct_chars, s.pct_manga) = self.mix.percents()
    s.pct_pixel = shares["pixel"]
    s.pct_anagram = shares["anagram"]
    s.pct_plot = shares["plot"]
    from .description_controls import collect as collect_description
    collect_description(self, s)
    from .dialogue_controls import collect as collect_dialogue
    collect_dialogue(self, s)
    s.pct_ai_art = shares["ai_art"]
    s.pack_ai_art = self.chk_ai_art.isChecked()
    s.pct_pixiv_art = shares["pixiv_art"]
    s.pack_pixiv_art = self.chk_pixiv_art.isChecked()
    s.pixiv_refresh_token = self._api_key("pixiv")
    s.pixiv_r18_mode = self.cb_pixiv_r18.currentData() or "exclude"
    s.pixiv_ai_mode = self.cb_pixiv_ai.currentData() or "exclude"
    # Старые галочки пишем рядом: прежние сборки читают только их.
    s.pixiv_exclude_r18 = s.pixiv_r18_mode == "exclude"
    s.pixiv_exclude_ai = s.pixiv_ai_mode == "exclude"
    s.pixiv_allow_same_sex = self.chk_pixiv_same_sex.isChecked()
    s.pixiv_gemini_check = self.chk_pixiv_gemini.isChecked()
    s.pixiv_gemini_model = self.cb_pixiv_gemini_model.currentText().strip()
    # Комиксы Pixiv (type=manga) не берутся никогда: это кадры с
    # репликами, а не рисунок (просьба пользователя — галочку убрали).
    s.pixiv_allow_manga = False
    s.pixiv_min_likes = self.sp_pixiv_likes.value()
    s.pixiv_groups_off = list(self._pixiv_groups_off)
    s.pixiv_tags_off = list(self._pixiv_tags_off)
    s.pixiv_tags_extra = list(self._pixiv_tags_extra)
    from si_hyx_parts.animepack_tab.sakuga_controls import collect as collect_sakuga
    collect_sakuga(self, s)
    from si_hyx_parts.animepack_tab.studio_controls import collect as collect_studio
    collect_studio(self, s)
    s.cloudflare_account_id = self._api_key("cloudflare_account_id")
    s.cloudflare_token = self._api_key("cloudflare")
    s.cloudflare_model = self.cb_cloudflare_model.currentData()
    s.pack_pixel = self.chk_pixel.isChecked()
    s.pixel_seconds = self.sp_pixel_sec.value()
    s.pixel_fps = self.sp_pixel_fps.value()
    s.pixel_steps = self.sp_pixel_steps.value()
    s.pixel_block = self.sp_pixel_block.value()
    from si_hyx_parts.animepack_tab.frame_effect_controls import selected_effects
    s.frame_effect = self.cb_frame_effect.currentData() or "pixelize"
    s.frame_effects = selected_effects(self)
    s.frame_effect_strength = self.sp_frame_effect_strength.value()
    s.frame_dvd_folder = self.ed_dvd_folder.text().strip()
    s.frame_dvd_fps = int(self.cb_dvd_fps.currentData() or 30)
    s.pack_anagram = self.chk_anagram.isChecked()
    s.anagram_lang = self.cb_anagram_lang.currentData() or "russian"
    s.anagram_max_chars = self.sp_anagram_max.value()
    s.anagram_cps = self.sp_anagram_cps.value()
    s.pack_plot = self.chk_plot.isChecked()
    s.plot_mode = self.cb_plot_mode.currentData() or "title"
    s.gemini_key = self._api_key("gemini")
    s.gemini_model = self.cb_gemini_model.currentText().strip()
    s.gemini_thinking = (self.cb_gemini_think.currentData()
                         or _api.GEMINI_THINKING_LEVEL)
    # Загадки по названию ходят к своей модели (просьба пользователя).
    s.gemini_title_model = self.cb_gemini_title_model.currentText().strip()
    s.gemini_title_thinking = (self.cb_gemini_title_think.currentData()
                               or _api.GEMINI_THINKING_LEVEL)
    s.tmdb_key = self._api_key("tmdb")
    s.poster_cache = self.chk_poster_cache.isChecked()
    s.mark_owners = self.chk_mark_owners.isChecked()
    s.char_roles = self.cb_char_roles.currentData() or "both"
    s.pack_manga = self.chk_manga.isChecked()
    s.manga_lang = self.cb_manga_lang.currentData() or ""
    s.manga_allow_erotica = self.chk_manga_erotica.isChecked()
    from si_hyx_parts.animepack_tab.manga_gemini_controls import collect as collect_manga_gemini
    collect_manga_gemini(self, s)
    s.manga_kinds = {k: chk.isChecked()
                     for k, chk in self.chk_manga_kinds.items()}
    s.song_video = self.chk_video.isChecked()
    s.video_cut = self.sp_video_cut.value()
    s.video_crf = self.sp_video_crf.value()
    s.video_preset = self.sp_video_preset.value()
    s.pick_openings = self.chk_op.isChecked()
    s.pick_endings = self.chk_ed.isChecked()
    s.pick_inserts = self.chk_in.isChecked()
    # Опенинги/эндинги/OST — это ДОЛИ песенных вопросов (полоса), а не
    # штуки: генератор всё равно ужимает их под число песен в паке.
    s.openings = self.kind_bar.value_of("opening")
    s.endings = self.kind_bar.value_of("ending")
    s.inserts = self.kind_bar.value_of("insert")
    s.difficulty_min = self.sp_diff_min.value()
    s.difficulty_max = self.sp_diff_max.value()
    s.ost_difficulty_min = self.sp_ost_diff_min.value()
    s.ost_difficulty_max = self.sp_ost_diff_max.value()
    s.categories = {c: chk.isChecked() for c, chk in self.chk_categories.items()}
    s.allow_rebroadcast = self.chk_rebroadcast.isChecked()
    s.allow_dub = self.chk_dub.isChecked()
    s.level_min = self.sp_level_from.value()
    s.level_max = self.sp_level_to.value()
    s.level_avg = self.sp_level_avg.value()
    from .level_controls import collect as collect_levels
    collect_levels(self, s)
    s.score_from = self.sp_score_from.value()
    s.score_to = self.sp_score_to.value()
    s.kinds = {k: chk.isChecked() for k, chk in self.chk_kinds.items()}
    s.year_from = self.sp_year_from.value()
    s.year_to = self.sp_year_to.value()
    s.genres_include = list(self._sel_genres)
    s.genres_exclude = list(self._excl_genres)
    s.genres_partial = self.chk_genres_partial.isChecked()
    # dup_anime/dup_franchise не трогаем: они выключены навсегда.
    s.sort_by_index = self.chk_sort_index.isChecked()
    s.images = self.chk_images.isChecked()
    s.images_time = self.sp_images_time.value()
    s.answer_image_time = self.sp_answer_img.value()
    # Подсказка о типе песни есть всегда: своей галочки у неё больше нет
    # (просьба пользователя), и сохранённое «выключено» из старых
    # настроек тоже не должно её гасить.
    s.hint = True
    s.compress_audio = self.chk_compress_audio.isChecked()
    from .music_effect_controls import collect_controls
    collect_controls(self, s)
    from .cover_controls import collect_controls as collect_cover_controls
    collect_cover_controls(self, s)
    s.compress_images = self.chk_compress_images.isChecked()
    s.image_limit_kb = self.sp_img_kb.value()
    s.image_speed = self.sp_img_speed.value()
    s.shuffle_questions = self.chk_shuffle.isChecked()
    s.audio_cut = self.sp_cut.value()
    s.parallel = self.sp_parallel.value()
    s.generation_priority = self.cb_generation_priority.currentData() or "normal"
    s.out_dir = self._out_dir
    return s

def get_settings(self) -> dict:
    """Настройки вкладки для settings.json."""
    if not _api._HAS_CORE:
        return dict(self._initial)
    data = self.collect().to_dict()
    # Ключи API хранятся в общих настройках программы (Настройки → «Ключи
    # API»), а не здесь: иначе стёртый там ключ возвращался бы из этой
    # копии при следующем запуске.
    for k in ("gemini_key", "elevenlabs_key", "jimaku_key", "subdl_key", "tmdb_key",
              "cloudflare_token",
              "cloudflare_account_id", "pixiv_refresh_token"):
        data.pop(k, None)
    return self._templates_to_settings(data)
