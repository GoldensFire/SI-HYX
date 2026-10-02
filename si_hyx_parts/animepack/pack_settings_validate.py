# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""PackSettings: validate. Public namespace: animepack.

Метод подключается в тело PackSettings обычным импортом (см. pack_settings.py):
это одна связная задача — сказать, из-за чего запускать генерацию бессмысленно.
"""
from __future__ import annotations
import animepack as _api
from cloudflare_art_api import validate_settings
from pixiv_art_api import validate_settings as validate_pixiv_settings
from frame_reveal import EFFECT_LABELS, clean_effects


def validate(self) -> list[str]:
    """Список проблем, из-за которых генерацию запускать бессмысленно."""
    problems: list[str] = []
    from image_entrance import validate as validate_entrance
    problems.extend(validate_entrance(self))
    from music_effects import validate as validate_music
    problems.extend(validate_music(self))
    if self.total_questions <= 0:
        problems.append("Раундов, тем и вопросов должно быть хотя бы по одному.")
    # Квоты по типам песен — только для песенного режима: в режиме кадров
    # песен нет вовсе, там вопросов ровно столько, сколько тайтлов. В
    # смешанном режиме квоты ужимаются под число песенных вопросов сами,
    # поэтому достаточно, чтобы хоть один тип песни был разрешён.
    if self.only_kind or not self.songs_percent:
        pass
    elif not any(self.picked_kinds.values()):
        problems.append("Не выбран ни один тип песни: включите опенинги, "
                        "эндинги или OST — либо уведите ползунок состава "
                        "на кадры и персонажей.")
    elif self.total_quota <= 0:
        # Ролику песня нужна ровно так же, как обычному вопросу: он берётся
        # из тех же опенингов и эндингов, только видео вместо звука.
        problems.append("Опенингов, эндингов и OST ноль — песен в паке не "
                        "будет вовсе. Распределите их или уведите ползунок "
                        "состава с песен и роликов.")
    if self.percents[1] and not (self.pick_openings or self.pick_endings):
        problems.append("Ролики бывают только из опенингов и эндингов — OST "
                        "на AnimeThemes не лежат вовсе. Включите опенинги "
                        "или эндинги либо уведите долю роликов в ноль.")
    if not self.random_pool:
        live = [u for u in self.users if u.username.strip() and u.statuses]
        if not live:
            problems.append("Добавьте хотя бы одного пользователя со списком "
                            "(или включите общую базу — тогда аниме "
                            "возьмутся случайно).")
        if self.similar_count > max(1, len(live)):
            problems.append(
                f"Совпадение требуется у {self.similar_count} человек, а "
                f"списков всего {len(live)} — столько не наберётся.")
    # Песенные настройки проверяем, только пока песни в паке есть: пак из
    # одних кадров, анаграмм и сюжетов до AnisongDB не доходит вовсе, и
    # ругаться на его категории не за что.
    if self.songs_percent and not any(self.categories.get(c)
                                      for c in _api.SONG_CATEGORIES):
        problems.append("Не выбрана ни одна категория песен.")
    if not any(self.kinds.get(k) for k in _api.ANIME_KINDS):
        problems.append("Не выбран ни один тип аниме.")
    if self.manga_percent and not any(self.manga_kinds.get(k)
                                      for k in _api.MANGA_KINDS):
        problems.append("В паке есть доля манги, но не выбран ни один её "
                        "тип: задайте долю манги, манхвы или маньхуа.")
    if not any(self.mix_shares.values()):
        problems.append("Выберите хотя бы одну часть пака.")
    subdl = str(getattr(self, "subdl_key", "") or "").strip()
    # Диалог выбирает Gemini при любом источнике: он читает серию целиком и
    # берёт узнаваемое (dialogue_gemini.py), а у Jimaku ещё и переводит.
    gemini_kinds = ((_api.PLOT_KIND, _api.DIALOGUE_KIND,
                     _api.DESCRIPTION_AUDIO_KIND)
                    + _api.GEMINI_TITLE_KINDS)
    if any(self.mix_shares.get(k) for k in gemini_kinds) and not str(self.gemini_key or "").strip():
        problems.append(
            "Для сюжета, диалогов, описаний и названий нужен ключ Gemini. "
            "Введите ключ или отключите эти части пака (шифр работает без Gemini).")
    if self.mix_shares.get(_api.DESCRIPTION_AUDIO_KIND):
        from .description_question import LANGUAGE_NAMES
        languages = self.description_languages or [self.description_language]
        if not languages or any(code not in LANGUAGE_NAMES for code in languages):
            problems.append("Для вопросов по описанию выбран неизвестный язык.")
        if self.description_tts_first not in ("elevenlabs", "google", "gemini"):
            problems.append("Для описаний выбран неизвестный сервис озвучки.")
        if self.description_voice_enabled:
            from .description_gemini_tts import TTS_MODELS
            if self.description_gemini_tts_model not in TTS_MODELS:
                problems.append("Для описаний выбрана неизвестная модель Gemini TTS.")
    if (self.mix_shares.get(_api.DIALOGUE_KIND) and not subdl
            and not str(getattr(self, "jimaku_key", "") or "").strip()):
        problems.append(
            "Для вопросов по диалогам нужен ключ SubDL или Jimaku API. "
            "Введите ключ или отключите диалоги.")
    if self.mix_shares.get(_api.ANAGRAM_KIND) and self.anagram_lang not in _api.ANAGRAM_LANGS:
        problems.append("Для анаграмм выбран неизвестный язык названия.")
    if self.mix_shares.get(_api.AI_ART_KIND):
        problems.extend(validate_settings(self.cloudflare_account_id,
                                         self.cloudflare_token,
                                         self.cloudflare_model))
    if self.mix_shares.get(_api.PIXIV_ART_KIND):
        problems.extend(validate_pixiv_settings(self.pixiv_refresh_token))
        if self.pixiv_title_check_mode not in ("gemini", "local"):
            problems.append("Неизвестный способ проверки названия артов Pixiv.")
        if (getattr(self, "pixiv_gemini_check", True)
                and not str(self.gemini_key or "").strip()):
            problems.append(
                "Для визуальной проверки артов Pixiv нужен ключ Gemini. "
                "Введите ключ или отключите проверку в настройках Pixiv.")
    if self.mix_shares.get(_api.SAKUGA_KIND) and int(self.sakuga_cut or 0) < 2:
        problems.append("Отрывок сакуги короче двух секунд — смотреть в нём "
                        "нечего.")
    if self.mix_shares.get(_api.MANGA_KIND) and self.manga_lang not in _api.MANGA_LANGS:
        problems.append("Для страниц манги выбран неизвестный язык глав.")
    if self.mix_shares.get(_api.MANGA_KIND):
        from .ru_popularity_math import RuPopularityConfig
        try:
            RuPopularityConfig(**self.ru_popularity)
        except (ValueError, TypeError, OverflowError):
            problems.append("Некорректная конфигурация RU popularity.")
        from si_hyx_parts.animepack_api.manga_reader_base import clean_sources
        sources = clean_sources(self.manga_sources)
        if not any(sources.values()):
            problems.append("Выберите хотя бы один источник страниц манги.")
        elif (self.manga_lang and not sources["mangadex"]
              and not sources["mangafire"] and self.manga_lang != "en"
              and not ((sources["remanga"] or sources["mangalib"])
                       and self.manga_lang == "ru")):
            problems.append("Comix.to и WeebCentral дают страницы на английском. "
                            "Выберите английский или любой язык глав.")
    if self.mix_shares.get(_api.MANGA_KIND) and self.manga_title_check_mode not in ("gemini", "local"):
        problems.append("Неизвестный способ проверки названия страниц манги.")
    if (self.mix_shares.get(_api.MANGA_KIND)
            and (getattr(self, "manga_character_crop", True)
                 or (getattr(self, "manga_gemini_check", True)
                     and self.manga_title_check_mode == "gemini"))
            and not str(self.gemini_key or "").strip()):
        problems.append(
            "Для выбора сцен и проверки страниц манги нужен ключ Gemini. "
            "Введите ключ или отключите выбор сцен через Gemini и проверку "
            "через Gemini в настройках манги.")
    if self.mix_shares.get(_api.PIXEL_KIND) and int(self.pixel_seconds or 0) < 2:
        problems.append("Ролик-проявление короче двух секунд — проявляться "
                        "в нём нечему.")
    if self.mix_shares.get(_api.PIXEL_KIND):
        if not 0 <= self.frame_preset <= 13:
            problems.append("Пресет кадров с эффектами должен быть от 0 до 13.")
        if self.frame_effect not in (*EFFECT_LABELS, "random"):
            problems.append("Выбран неизвестный эффект раскрытия кадра.")
        if self.frame_effect == "random" and not clean_effects(self.frame_effects):
            problems.append("Отметьте хотя бы один эффект для случайного выбора.")
    if self.manga_percent and not self.random_pool:
        live = [u for u in self.users
                if u.username.strip() and u.statuses and u.target == "manga"]
        if not live:
            problems.append(
                "В паке есть доля манги, а списков манги нет: переключите "
                "хотя бы один список на «Манга/манхва/маньхуа» либо уведите долю "
                "манги в ноль.")
    if self.difficulty_min > self.difficulty_max:
        problems.append("Сложность AMQ опенингов/эндингов: «от» больше, чем «до».")
    ost_low, ost_high = _api.song_difficulty_band(self, "insert")
    if self.pick_inserts and ost_low > ost_high:
        problems.append("Сложность AMQ OST: «от» больше, чем «до».")
    if self.level_min > self.level_max:
        problems.append("Сложность пака: «от» больше, чем «до».")
    song_low, song_high = self.song_level_range
    if self.songs_percent and song_low > song_high:
        problems.append("Сложность аниме у песен: «от» больше, чем «до».")
    if self.manga_percent:
        if self.manga_level_min > self.manga_level_max:
            problems.append("Сложность манги: «от» больше, чем «до».")
        avg = int(getattr(self, "manga_level_avg", 0) or 0)
        if avg and not (self.manga_level_min <= avg <= self.manga_level_max):
            problems.append(
                f"Средняя сложность манги {avg} не попадает в рамки "
                f"«от {self.manga_level_min} до {self.manga_level_max}».")
        if int(self.manga_pct_manhwa or 0) + int(self.manga_pct_manhua or 0) > 100:
            problems.append("Доли манхвы и маньхуа в сумме больше сотни — "
                            "на японскую мангу мест не остаётся.")
        for key, label in (("manhwa", "манхвы"), ("manhua", "маньхуа")):
            if (int(getattr(self, "manga_pct_" + key) or 0)
                    and not self.manga_kinds.get(key)):
                problems.append(
                    f"Задана доля {label}, но сам её тип издания выключен — "
                    "включите его галочкой либо уведите долю в ноль.")
    if any(self.mix_shares.get(k) for k in (_api.AI_ART_KIND,
                                            _api.PIXIV_ART_KIND)):
        if self.art_level_min > self.art_level_max:
            problems.append("Сложность артов: «от» больше, чем «до».")
        avg = int(getattr(self, "art_level_avg", 0) or 0)
        if avg and not (self.art_level_min <= avg <= self.art_level_max):
            problems.append(
                f"Средняя сложность артов {avg} не попадает в рамки "
                f"«от {self.art_level_min} до {self.art_level_max}».")
    if self.level_avg and not (self.level_min <= self.level_avg <= self.level_max):
        problems.append(
            f"Средняя сложность {self.level_avg} не попадает в рамки "
            f"«от {self.level_min} до {self.level_max}».")
    if self.score_from > self.score_to:
        problems.append("Оценка: «от» больше, чем «до».")
    if self.year_from > self.year_to:
        problems.append("Год: «от» больше, чем «до».")
    if self.songs_percent and self.audio_cut < 5:
        problems.append("Отрезок песни короче 5 секунд.")
    if self.songs_percent and self.images and self.images_time >= self.audio_cut:
        problems.append(
            "Картинки должны появляться раньше, чем кончится песня: "
            f"{self.images_time} с ≥ отрезка {self.audio_cut} с.")
    return problems
