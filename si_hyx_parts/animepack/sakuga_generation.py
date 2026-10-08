# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Вопрос-сакуга: вырезка анимации с Sakugabooru. Namespace: animepack."""
from __future__ import annotations

import os
import tempfile

import animepack as _api
from .generation_diagnostics import locked, operation


# Столько тайтлов подряд может не найтись на Sakugabooru, прежде чем род
# вопросов снимается с прогона. Там лежит хорошо если каждый десятый тайтл
# каталога Shikimori, поэтому прежний порог 10 регулярно отключал живую
# категорию. 80 совпадает с запасом карточек на одну сакугу (catalog_want.py)
# и всё ещё ограничивает бесплодный поиск по действительно пустой выборке.
MISS_GIVE_UP = 80
# Тайтлы, у которых на Sakugabooru нет ни тега, ни вырезки, помнятся между
# паками: в прогоне 26 из 28 ошибок сакуги были именно такими повторными
# поисками. Свежие тайтлы сайт ещё пополняет — их проверяем чаще.
ABSENT_MEMO = "sakuga_absent_v1"
ABSENT_TTL = 60 * 24 * 3600
FRESH_ABSENT_TTL = 7 * 24 * 3600
# Записи Shikimori, которые не тайтлы: ответом вопроса они быть не могут.
NOT_TITLE_KINDS = ("pv", "cm", "music")


def _mal(card) -> int:
    try:
        return int((card or {}).get("malId") or 0)
    except (TypeError, ValueError, AttributeError):
        return 0


def _year(card) -> int:
    try:
        return int(((card or {}).get("airedOn") or {}).get("year") or 0)
    except (TypeError, ValueError, AttributeError):
        return 0


def known_absent(generator, card) -> bool:
    """На Sakugabooru у тайтла вырезок нет — по памяти прошлых паков."""
    mal = _mal(card)
    cache = getattr(generator, "db_cache", None)
    if not mal or cache is None:
        return False
    known = generator.__dict__.setdefault("_sakuga_absent_known", {})
    if mal not in known:
        fresh = _year(card) >= _api.date.today().year - 1
        try:
            value = cache.memo(ABSENT_MEMO, mal,
                               FRESH_ABSENT_TTL if fresh else ABSENT_TTL)
        except Exception:  # noqa: BLE001 — без памяти просто спросим сайт
            value = None
        known[mal] = bool(value)
    return known[mal]


def _remember_absent(generator, card) -> None:
    """Запоминает отсутствие вырезок — только если сайт и правда их не знает."""
    mal = _mal(card)
    if not mal or getattr(generator, "db_cache", None) is None:
        return
    absent = getattr(generator.sakuga, "absent", None)
    try:
        if absent is None or not absent(card):
            return
        generator.db_cache.remember_memo(ABSENT_MEMO, mal, True)
    except Exception:  # noqa: BLE001 — не запомнили, спросим в другой раз
        return
    generator.__dict__.setdefault("_sakuga_absent_known", {})[mal] = True


def init_sakuga_service(self, client=None):
    """Клиент Sakugabooru — только при доле сакуги в паке."""
    self.sakuga = client
    if client is None and self.s.mix_shares.get(_api.SAKUGA_KIND):
        self.sakuga = _api.SakugaApi(
            self.session,
            safe_only=False,
            rng=self.rng)
    self._sakuga_misses = 0


class SakugaMixin:
    """Генератор: отрывок Sakugabooru."""

    @operation("поиск")
    def download_sakuga(self, cand) -> bool:
        """Режет вырезку анимации в ролик пака («ложь» — не вышло).

    Звук не пишем вовсе: у вырезок его чаще всего и нет, а где есть — это
    голоса и музыка, которые выдали бы тайтл мимо самой анимации."""
        if self.stopped():
            return False
        if _api.SAKUGA_KIND in self._dead_kinds or self.sakuga is None:
            cand.rejected = True
            self._drop_kind(_api.SAKUGA_KIND)
            return False
        if known_absent(self, cand.anime):
            # Промахом не считается: сайт не спрашивали.
            return False
        try:
            # Сеть не держит общий замок. Резерв проверяется ещё раз после
            # ответа сервера: два потока могут одновременно найти один клип.
            with self._frames_lock:
                excluded = set(self._frames_used)
            clip = self.sakuga.clip(cand.anime, excluded)
            with locked(self, self._sakuga_lock):
                if clip:
                    with self._frames_lock:
                        key = _api.frame_url_key(clip["url"])
                        if key in self._frames_used:
                            return False
                        self._frames_used.add(key)
                    # Это счётчик именно ПОДРЯД не найденных клипов, а не успешно
                    # закодированных. Кодирование сериализовано отдельным замком и
                    # может ждать минуты; при восьми потоках быстрые промахи раньше
                    # успевали добить лимит, пока уже найденные клипы стояли в
                    # очереди на ffmpeg.
                    self._sakuga_misses = 0
                    misses = 0
                else:
                    # Увеличиваем счётчик под ТЕМ ЖЕ замком, что и выбор клипа.
                    # Иначе поток со старым промахом мог проснуться уже после
                    # найденного клипа и превратить его в первый промах новой
                    # серии, хотя фактический порядок поиска был обратным.
                    self._sakuga_misses += 1
                    misses = self._sakuga_misses
        except _api.AnimePackApiError as e:
            self._log_rare("Сакуга", f"Sakugabooru «{cand.title_ru}»: {e}")
            return False
        if not clip:
            _remember_absent(self, cand.anime)
            return _miss(self, cand, misses)
        if self.stopped():
            return False
        newer = _newest_tagged(self, cand, clip)
        if newer:
            _answer_with(self, cand, newer)
        # Страница поста, а не файла: на ней видно, из какой сцены вырезка и кто
        # её анимировал (просьба пользователя — ссылка на источник в ответе).
        cand.source_link = _api.sakuga_post_link(clip.get("id"))
        from .early_repeat import reserve
        if not reserve(self, cand):
            return False
        if not _encode(self, cand, clip):
            return False
        cand.sakuga = dict(clip)
        cand.frame_url = clip["url"]
        cand.has_video = True
        return True


def _newest_tagged(self, cand, clip: dict) -> dict:
    """Самая поздняя часть франшизы, к которой относятся теги вырезки ({} — нет).

    Тег `dororo` подходит и «Дороро и Хяккимару» (1969, английское «Dororo»),
    и ремейку «Дороро» (2019), а вырезки под ним почти всегда из ремейка. Когда
    теги подходят нескольким тайтлам, ответом становится самый поздний
    (просьба пользователя). Смотрим только части той же франшизы Shikimori:
    чужой тайтл с похожим названием ответом не станет."""
    key = str((cand.anime or {}).get("franchise") or "").strip()
    own_year, own = cand.year, _mal(cand.anime)
    if not key or not own_year or self.sakuga is None:
        return {}
    this_year = _api.date.today().year
    newer = []
    for row in (self.db_cache.franchise(key) or []):
        if not isinstance(row, dict) or _api.is_announced(row):
            continue
        if str(row.get("kind") or "").lower() in NOT_TITLE_KINDS:
            continue
        mal = _mal(row)
        if mal and mal != own and own_year < _year(row) <= this_year:
            newer.append(mal)
    if not newer:
        return {}
    tag_for = getattr(self.sakuga, "tag_for", None)
    tags = set(clip.get("tags") or ())
    try:
        if tag_for is not None:
            tags.add(tag_for(cand.anime))
        cards = self._animes_by_ids(newer)
    except _api.AnimePackApiError:
        return {}
    matched = [card for card in cards
               if isinstance(card, dict) and not _api.is_announced(card)
               and str(card.get("kind") or "").lower() not in NOT_TITLE_KINDS
               and own_year < _year(card) <= this_year
               and _api.SakugaApi.card_tagged(card, tags)]
    return max(matched, key=_year, default={})


def _answer_with(self, cand, card: dict) -> None:
    """Ответ вопроса — более поздняя часть франшизы; средняя пака прежняя.

    Уровень, под который вопрос отбирали, сохраняется в selection_level: по
    нему пак держит среднюю. Цена считается по новой карточке — ведь
    спрашивается именно она."""
    if cand.selection_level is None:
        cand.selection_level = cand.level
    old = cand.title_ru
    cand.anime = card
    self._load_franchise_indexes([card])
    cand.franchise_index = self._franchise_index(card)
    cand.favorites = self._title_favorites(cand)
    if getattr(cand, "media_base", ""):
        cand.media_base = self._media_base(cand)
    self.log(f"Сакуга: теги вырезки подходят и «{old}», и более позднему "
             f"«{cand.title_ru}» — в ответе поздний.")


# Потолок на кодирование одной вырезки. Кодируется уже скачанный файл, так
# что это чистое время ЦП: при медленном пресете и восьми потоках десять
# секунд 720p у libsvtav1 идут минутами.
ENCODE_TIMEOUT = 900


def _download(self, clip: dict) -> str:
    """Скачивает вырезку во временный файл и возвращает путь («» — не вышло).

    Раньше ffmpeg читал вырезку прямо с сайта, и под сетевым замком шло всё
    кодирование целиком: при пресете 3 одна вырезка держала замок минутами,
    остальные сакуги стояли в очереди, а зависшее чтение ffmpeg обрывал только
    таймаут в 600 с — и так трижды, с повторами. На 140 из 144 пак стоял
    сорок минут, а журнал молчал: одинаковая ошибка у сакуги уже была
    «приглушена» (_log_rare). Теперь под замком только загрузка — requests с
    таймаутом чтения, — а кодирование идёт параллельно с остальными."""
    with locked(self, self._sakuga_net_lock):
        data = self._get_bytes(clip["url"], timeout=(10, 60))
    if not data:
        return ""
    ext = str(clip.get("ext") or "mp4").strip(".") or "mp4"
    handle, path = tempfile.mkstemp(prefix="sihyx_sakuga_", suffix="." + ext)
    with os.fdopen(handle, "wb") as stream:
        stream.write(data)
    return path


def _encode(self, cand, clip: dict) -> bool:
    """Кодирует отрывок в ролик пака тем же libsvtav1, что и все видео.

    Режем с начала: вырезку выложили ровно ради этой сцены, и первые кадры в
    ней — не заставка студии, а сама анимация."""
    final = _api.os.path.join(self.folder, "Video", cand.video_out)
    # Потолок в двадцать секунд стоит и здесь, и в настройках (просьба
    # пользователя): вырезка длиннее перестаёт быть загадкой по рисовке.
    duration = max(2, min(_api.SAKUGA_MAX_CUT,
                          int(getattr(self.s, "sakuga_cut", _api.SAKUGA_CUT))))
    # Скорость кодирования у сакуги своя (просьба пользователя): вырезок в
    # паке бывает два десятка, и пресет для них выбирается отдельно от
    # вопросов-роликов. Всё остальное — те же флаги libsvtav1.
    preset = getattr(self.s, "sakuga_preset", None)
    try:
        source = _download(self, clip)
    except (_api.AnimePackError, OSError) as exc:
        if not self.stopped():
            self._log_rare("Сакуга", f"Отрывок «{cand.title_ru}» не "
                                     f"скачался: {str(exc)[:160]}")
        return False
    if not source:
        return False
    cmd = ([_api.FFMPEG, "-y", "-loglevel", "error", "-i", source,
            "-t", str(duration), "-an"]
           + self.video_encode_args(preset)
           + ["-movflags", "+faststart", final])
    try:
        if self.stopped():
            return False
        # Файл уже на диске: сбой ffmpeg здесь не случайность сети, и
        # повторять то же кодирование незачем.
        code, err = self._run_killable(cmd, timeout=ENCODE_TIMEOUT)
    finally:
        try:
            os.remove(source)
        except OSError:
            pass
    size = _api.os.path.getsize(final) if _api.os.path.exists(final) else 0
    if code == 0 and size >= _api.MIN_VIDEO_BYTES:
        return True
    try:
        if _api.os.path.exists(final):
            _api.os.remove(final)
    except OSError:
        pass
    if not self.stopped():
        # SVT-AV1 печатает баннер Svt[info] в stderr при любом -loglevel:
        # раньше причиной отказа в журнале был он, а не настоящая ошибка.
        reason = " ".join(line.strip() for line in str(err or "").splitlines()
                          if line.strip() and not line.lstrip().startswith("Svt["))
        if code == 0:
            reason = f"готовый файл слишком мал ({size} байт)"
        self._log_rare("Сакуга",
                       f"Отрывок «{cand.title_ru}» не собрался: "
                       f"{(reason or 'пустой файл')[:160]}")
    return False


def _miss(self, cand, misses: int) -> bool:
    """Тайтла на Sakugabooru нет — считаем промахи и вовремя сдаёмся."""
    self._log_rare("Сакуга",
                   f"«{cand.title_ru}»: вырезок на Sakugabooru нет — беру "
                   "следующий тайтл")
    if misses == MISS_GIVE_UP:
        self.log(f"Сакуга: подряд не нашлось {misses} тайтлов — категорию "
                 "пропускаю, её места отдам остальным родам вопросов. На "
                 "Sakugabooru лежат в основном заметные ТВ-сериалы и фильмы.")
        self._drop_kind(_api.SAKUGA_KIND)
    if misses >= MISS_GIVE_UP:
        cand.rejected = True
    return False
