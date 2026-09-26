# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""AnimePackGenerator: run. Public namespace: animepack."""
from __future__ import annotations
import animepack as _api


# ── всё вместе ────────────────────────────────────────────────────────
def run(self, out_path: _api.Optional[str] = None) -> _api.PackResult:
    problems = self.s.validate()
    if problems:
        raise _api.AnimePackError("\n".join(problems))
    if self.s.chiptune_enabled:
        from .music_processing import music_service
        self.log("Chiptune: проверяю окружение и модели…")
        music_service(self).preflight()
    if self.s.cover_enabled:
        # Каверы качает yt-dlp. Без него не выйдет ни одного, и узнать об этом
        # лучше сейчас, а не после получаса отбора.
        from .cover_processing import cover_service
        if not cover_service(self).ytdlp:
            raise _api.AnimePackError(
                "Каверы: не найден yt-dlp — положите его в папку bin рядом с "
                "программой или выключите каверы в настройках музыки.")
    result = _api.PackResult(
        requested=self.s.total_questions,
        pack_number=int(getattr(self.s, "pack_number", 0) or 0))
    started = _api.time.monotonic()
    with self._timed("чтение чужих паков"):
        self.load_exclusions()
    # Соседи по индексу для надбавки «в избранном» (см. favorites_norm).
    _api.install_favorites_norms(self.db_cache)
    self.prepare_dirs()
    try:
        songs = self.select_songs()
        result.songs = songs
        result.failed_media = self._failed_media
        if self.stopped():
            result.cancelled = True
            if songs:
                self.log(f"Остановлено: сохраняю {len(songs)} готовых вопросов…")
                result.path = self.write_package(songs, out_path)
                self.save_frames_history(songs)
                self.log(f"Частичный пак готов: {result.path}")
            return result
        if not songs:
            raise _api.AnimePackError(
                "Не набралось ни одного вопроса. Проверьте ошибки в журнале "
                "или ослабьте фильтры (сложность, жанры, годы, типы аниме).")
        if len(songs) < self.s.total_questions:
            self.log(f"Внимание: вопросов будет {len(songs)}, а не "
                     f"{self.s.total_questions} — кандидаты кончились.")
            if self.s.random_pool and self.s.has_songs \
                    and self._random_source == "shikimori":
                # Замерено: песня в AnisongDB находится у 59 случайных
                # тайтлов Shikimori из 150. С фильтром «Сложность пака»
                # (узнаваемость) остаётся и того меньше.
                self.log("Для песенного пака база AMQ плотнее: в каталоге "
                         "Shikimori песня есть примерно у четырёх тайтлов "
                         "из десяти, а «Сложность пака» режет ещё сильнее. "
                         "Поставьте «Случайные из базы AMQ» или ослабьте "
                         "сложность.")
        with self._timed("проверка списков"):
            self.mark_list_owners(songs)
        from .author_lookup import enrich_authors
        with self._timed("авторы"):
            enrich_authors(self.shikimori, songs, self.log)
        self.log("Собираю пакет…")
        with self._timed("сборка .siq"):
            result.path = self.write_package(songs, out_path)
        self.save_frames_history(songs)
        try:
            mb = _api.os.path.getsize(result.path) / (1024.0 * 1024.0)
            limit = int(self.s.max_pack_mb)
            self.log(f"Вес пака: {mb:.1f} МБ (потолок {limit} МБ)")
            if mb > limit:
                self.log("Внимание: пак вышел тяжелее потолка — так бывает, "
                         "когда сжатие медиа выключено и размер задаём не мы.")
        except OSError:
            pass
        return result
    finally:
        result.elapsed = _api.time.monotonic() - started
        # Цена прогона в запросах к Gemini — перед раскладкой времени: по ней
        # видно, во сколько запросов обошлись вопросы по сюжету и загадки.
        self.log_gemini_spent()
        # Раскладка времени по этапам — в самом конце, чтобы её было видно
        # последней строкой лога (просьба пользователя).
        self.log_stage_times(result.elapsed)
        self.cleanup()
