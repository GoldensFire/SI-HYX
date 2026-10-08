# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""AnimePackGenerator. Public namespace: animepack."""
from __future__ import annotations
import animepack as _api
from si_hyx_parts.animepack.db_source_refresh import refresh_database_sources
from si_hyx_parts.animepack.generator_catalog import GeneratorCatalogMixin
from si_hyx_parts.animepack.generator_selection import GeneratorSelectionMixin
from si_hyx_parts.animepack.generator_media import GeneratorMediaMixin
from si_hyx_parts.animepack.ai_art_generation import AiArtMixin
from si_hyx_parts.animepack.pixiv_art_generation import PixivArtMixin
from si_hyx_parts.animepack.manga_panel import MangaPanelMixin
from si_hyx_parts.animepack.sakuga_generation import SakugaMixin
from si_hyx_parts.animepack.episode_generation import EpisodeClipMixin
from si_hyx_parts.animepack.dialogue_generation import DialogueQuestionMixin
from si_hyx_parts.animepack.description_question import DescriptionQuestionMixin
from si_hyx_parts.animepack.shortage_report import ShortageReportMixin


def _refresh_catalogs(self, wanted) -> list[dict]:
    """Каталоги аниме и манги. Незатронутый раздел просто читается из кэша:
    его карточки нужны, чтобы пересчитать по ним узнаваемость франшиз."""
    cards: list[dict] = []
    for target in ("anime", "manga"):
        if self.stopped():
            break
        if target not in wanted:
            cards += self.db_cache.all_cards(target)
            continue
        from .db_settings import database_settings
        signature = _api.shiki_cache_signature(database_settings(), target == "manga")
        cursor = self.db_cache.catalog_cursor(target, signature)
        resume = not cursor["complete"] and cursor["next_page"] > 1
        if not resume:
            self.db_cache.clear_part(target)
        what = "манги" if target == "manga" else "аниме"
        self.log(f"База Shikimori: собираю каталог {what} заново — он "
                 "берётся целиком, это дольше минуты. Кнопка «Остановить» "
                 "сохранит набранное.")
        store = self._manga_cache if target == "manga" else self._card_cache
        for mal in self.fetch_full_catalog(manga=(target == "manga"), unfiltered=True,
                                           resume=resume):
            if mal in store:
                cards.append(store[mal])
    return cards


def _refresh_favorites(self) -> None:
    from .db_favorites_refresh import refresh_favorites
    refresh_favorites(self)


def _refresh_franchises(self, cards) -> None:
    from .db_franchise_refresh import refresh_franchises
    refresh_franchises(self, cards)


def _db_card_count(self) -> int:
    """Сколько карточек каталога лежит в базе (аниме + манга)."""
    counts = self.db_cache.part_counts()
    return int(counts["anime"]["count"]) + int(counts["manga"]["count"])


def _prepare(self, out_path):
    problems = self.s.validate()
    from .generation_preflight import average_problems, describe
    problems.extend(average_problems(self.s))
    if problems:
        raise _api.AnimePackError("\n".join(problems))
    from storage_guard import require_space, START_RESERVE
    import tempfile
    require_space(tempfile.gettempdir(), START_RESERVE)
    require_space(out_path or self.s.out_dir or tempfile.gettempdir(), START_RESERVE)
    if self.s.chiptune_enabled and self.s.chiptune_percent:
        from .music_processing import music_service
        self.log("Chiptune: проверяю окружение и модели…")
        music_service(self).preflight()
    if self.s.cover_enabled and self.s.cover_percent:
        from .cover_processing import cover_service
        if not cover_service(self).ytdlp:
            raise _api.AnimePackError("Каверы: не найден yt-dlp.")
    describe(self)
    with self._timed("чтение чужих паков"):
        self.load_exclusions()
    _api.install_favorites_norms(self.db_cache)
    self.prepare_dirs()


# ─────────────────────────────────────────────────────────────────────────────
# Генератор
# ─────────────────────────────────────────────────────────────────────────────
class AnimePackGenerator(
    GeneratorCatalogMixin,
    GeneratorSelectionMixin,
    GeneratorMediaMixin,
    AiArtMixin,
    PixivArtMixin,
    MangaPanelMixin,
    SakugaMixin,
    EpisodeClipMixin,
    DialogueQuestionMixin,
    DescriptionQuestionMixin,
    ShortageReportMixin,
):
    """Полный цикл: списки аниме → песни → медиа → .siq.

    Все длительные шаги зовут log()/progress() и проверяют should_stop(), чтобы
    вкладка могла показывать ход дела и останавливать генерацию.
    """

    def __init__(self, settings: _api.PackSettings, *,
                 session=None, amq=None, anisong=None, mal=None, shikimori=None,
                 anilist=None, kitsu=None, themes=None, fandom=None, gemini=None,
                 tmdb=None, cloudflare=None, pixiv=None, anizip=None,
                 mangadex=None, sakuga=None,
                 jimaku=None, subdl=None, kuhi=None, episode_ru=None,
                 log: _api.Optional[_api.Callable[[str], None]] = None,
                 progress: _api.Optional[_api.Callable[[int, int, str], None]] = None,
                 should_stop: _api.Optional[_api.Callable[[], bool]] = None,
                 rng: _api.Optional[_api.random.Random] = None,
                 frames_history_path: str = _api.FRAMES_HISTORY_FILE,
                 db_cache: _api.Optional[_api.ShikimoriDbCache] = None,
                 generation_runtime=None):
        self.s = settings
        # Эти обратные вызовы нужны клиентам, создаваемым ниже. В частности Pixiv
        # сразу получает rng; поэтому они должны существовать до init_*_service.
        self._log = log or (lambda msg: None)
        self._progress = progress or (lambda done, total, msg: None)
        self._should_stop = should_stop or (lambda: False)
        from .generation_runtime import GenerationRuntime
        self._runtime = generation_runtime or GenerationRuntime(settings, self.stopped)
        self.rng = rng or _api.random.Random()
        self.session = session or _api.make_session()
        from .karaoke_processing import init_service as init_karaoke
        init_karaoke(self)
        self.amq = amq or _api.AmqApi(self.session)
        from .anisong_cache import CachedAnisong
        self.anisong = anisong or CachedAnisong(_api.AnisongApi(self.session))
        self.mal = mal or _api.MalApi(self.session)
        self.shikimori = shikimori or _api.ShikimoriApi(self.session)
        self.anilist = anilist or _api.AniListApi(self.session, log=self.log)
        self.kitsu = kitsu or _api.KitsuApi(self.session)
        # AniZip — третий источник кадров эпизодов рядом с AniList и Kitsu: у него
        # превью КАЖДОЙ серии с TheTVDB, поэтому один тайтл даёт десятки разных
        # сцен вместо трёх скриншотов Shikimori (см. _frame_urls).
        self.anizip = anizip or _api.AniZipApi(self.session)
        self.themes = themes or _api.AnimeThemesApi(self.session)
        # Фэндом-вики и Gemini нужны ровно одному роду вопросов — «по сюжету».
        # Без его доли клиенты не создаются вовсе: лишний ключ и лишняя сессия
        # ни к чему, а Gemini без ключа и не заработал бы.
        self.fandom = fandom
        self.gemini = gemini
        self.gemini_episode = gemini
        self.gemini_board = None
        # Загадки по названию ходят к Gemini СВОИМ клиентом: модель и уровень
        # рассуждения у них отдельные от сюжета и диалогов (просьба
        # пользователя). Подменённый в тестах клиент один на всё.
        self.gemini_titles = gemini
        self.gemini_pixiv = gemini
        self.gemini_frames = gemini
        self._visual_spare = None
        from .frame_visual_check import enabled as frame_check_enabled
        needs_frames = any(settings.mix_shares.get(kind) and frame_check_enabled(settings, kind)
                           for kind in (*_api.FRAME_KINDS, _api.STUDIO_KIND))
        needs_general = any(settings.mix_shares.get(k)
                            for k in (_api.PLOT_KIND, _api.DIALOGUE_KIND,
                                      _api.DESCRIPTION_AUDIO_KIND))
        needs_episode_subtitles = bool(settings.mix_shares.get(_api.EPISODE_KIND)
                                      and (settings.episode_ru_subtitles
                                           or getattr(settings, "episode_subtitle_mode", "") in ("required", "preferred")
                                           or getattr(settings, "episode_scene_check", True)))
        needs_titles = any(settings.mix_shares.get(k)
                           for k in _api.GEMINI_TITLE_KINDS)
        key_available = bool(str(settings.gemini_key or "").strip())
        needs_pixiv = bool(settings.mix_shares.get(_api.PIXIV_ART_KIND)
                           and getattr(settings, "pixiv_gemini_check", True))
        # Gemini chooses the character scene on the original page and can also
        # check the final crop for title lettering.
        needs_manga = bool(settings.mix_shares.get(_api.MANGA_KIND)
                           and (getattr(settings, "manga_character_crop", True)
                                or (getattr(settings, "manga_gemini_check", True)
                                    and (settings.manga_title_check_mode == "gemini"
                                         or key_available))))
        self.gemini_manga = gemini if needs_manga else None
        if (needs_general or needs_episode_subtitles or needs_titles or needs_pixiv
                or needs_manga or needs_frames):
            if settings.mix_shares.get(_api.PLOT_KIND) and self.fandom is None:
                self.fandom = _api.FandomApi(self.session)
            key = str(settings.gemini_key or "").strip()
            if key:
                from gemini_api import DEFAULT_MODEL, GeminiClient
                from gemini_quota import QuotaBoard

                # Доска на обоих клиентов ОДНА: ключ у них общий, а значит общие и
                # минутный предел, и суточный. С раздельной они вдвое превышали RPM
                # и слали запросы в модель, про которую сосед уже знал, что она
                # кончилась. Потолки из настроек («сколько запросов в сутки»)
                # проверяются до отправки: 0 значит «не знаю, спроси у сервера».
                self.gemini_board = QuotaBoard(
                    key, dict(getattr(settings, "gemini_daily_limits", {}) or {}))

                def _client(model, thinking, **extra):
                    return GeminiClient(
                        key, model=(model or DEFAULT_MODEL),
                        thinking=str(thinking or ""), **extra,
                        log=lambda msg: self.log(msg),
                        stopped=lambda: self.stopped(),
                        board=self.gemini_board)

                think = str(getattr(settings, "gemini_thinking", "") or "")
                if needs_general and self.gemini is None:
                    self.gemini = _client(settings.gemini_model, think)
                    self.log(f"Gemini: модель {self.gemini.model}, "
                             f"уровень рассуждения {self.gemini.thinking}")
                # Отрывки серий — проверка сцены по видео и перевод их субтитров —
                # идут своим клиентом с моделью группы «Изображения»: проверка
                # смотрит готовый ролик, а свой клиент нужен ради её дедлайна
                # (episode_scene_check.initialize подменяет stopped).
                from .gemini_settings import image_model as selected_image_model
                image_model = selected_image_model(settings)
                if needs_episode_subtitles and self.gemini_episode is None:
                    self.gemini_episode = _client(image_model, settings.gemini_image_thinking,
                                                  timeout=45, fallback_gemma=False)
                if needs_titles and self.gemini_titles is None:
                    # Пустая своя модель значит «как у сюжета»: так открываются
                    # настройки, сохранённые до появления второго выбора.
                    self.gemini_titles = _client(
                        str(getattr(settings, "gemini_title_model", "") or "")
                        or settings.gemini_model,
                        str(getattr(settings, "gemini_title_thinking", "") or "")
                        or think)
                # Проверке картинки хватает минуты: дольше отвечает только
                # перегруженный сервер (см. visual_batch.READ_TIMEOUT).
                from .visual_batch import READ_TIMEOUT as visual_timeout
                image_client = gemini
                if (needs_frames or needs_pixiv or needs_manga) and image_client is None:
                    image_client = _client(image_model, settings.gemini_image_thinking,
                                           timeout=visual_timeout, fallback_gemma=False)
                    self.log(f"Gemini: изображения — модель {image_client.model}, "
                             f"рассуждение {image_client.thinking}; "
                             "при отказе — замена на другую модель Gemini")
                if needs_frames:
                    self.gemini_frames = image_client
                if (needs_frames or needs_manga) and gemini is None:
                    # Часть проверок кадров и названий манги снимает с общей
                    # очереди Gemma со своей квотой (см. visual_spare).
                    from .visual_spare import create as create_spare
                    self._visual_spare = create_spare(self, _client, image_client)
                if needs_pixiv:
                    self.gemini_pixiv = image_client
                if needs_manga:
                    self.gemini_manga = image_client
        for client, purpose in ((self.gemini, "Сюжет/Диалоги"),
                                (self.gemini_episode, "Отрывки серий"),
                                (self.gemini_titles, "Названия"),
                                (self.gemini_frames, "Изображения"),
                                (self.gemini_pixiv, "Изображения"),
                                (self.gemini_manga, "Изображения")):
            if client is not None and gemini is None:
                client.purpose = purpose
        # Держим ссылки для итоговой статистики даже после отключения Gemini.
        self._gemini_clients = (self.gemini, self.gemini_titles,
                                self.gemini_pixiv, self.gemini_manga, self.gemini_frames, self.gemini_episode,
                                getattr(self._visual_spare, "client", None))
        from .visual_batch import initialize as initialize_visual_batches
        initialize_visual_batches(self)
        from .local_visual_ocr import initialize as initialize_local_ocr
        initialize_local_ocr(self)
        from .plot_batch import initialize as initialize_plot_batches
        initialize_plot_batches(self)
        self.jimaku = jimaku
        needs_subtitles = bool(settings.mix_shares.get(_api.DIALOGUE_KIND) or needs_episode_subtitles)
        if needs_subtitles and self.jimaku is None:
            key = str(getattr(settings, "jimaku_key", "") or "").strip()
            if key:
                self.jimaku = _api.JimakuApi(key, self.session)
        # SubDL — первый источник диалогов (русские субтитры, без Gemini);
        # Jimaku остаётся на время, когда суточная квота SubDL кончится.
        self.subdl = subdl
        if needs_subtitles and self.subdl is None:
            key = str(getattr(settings, "subdl_key", "") or "").strip()
            if key:
                self.subdl = _api.SubdlApi(key, self.session)
        self._dialogue_lock = _api.threading.Lock()
        self._dialogue_seen: set[tuple[int, int]] = set()
        from .episode_generation import initialize as initialize_episode
        initialize_episode(self, kuhi, episode_ru)
        # Запасной источник обложек. Без ключа клиент всё равно создаётся —
        # просто ничего не умеет (enabled=False), и проверок по всему коду не
        # нужно.
        self.tmdb = tmdb if tmdb is not None else _api.TmdbApi(
            self.session, key=str(getattr(settings, "tmdb_key", "") or ""))
        # Пересказы уже спрошенных тайтлов и вики, у которых сюжета не нашлось:
        # медиа качается в несколько потоков, поэтому под замком.
        self._plot_lock = _api.threading.Lock()
        self._plot_seen: set[str] = set()
        # Чем кончилось каждое обращение к Gemini за вопросом по сюжету — для
        # итоговой строки расхода (log_gemini_spent).
        self._plot_calls = _api.Counter()
        # Роды вопросов, которые в этом прогоне больше не получатся (кончился
        # ключ Gemini и т.п.): их места отдаются оставшимся, а не жгут
        # кандидатов впустую — см. _drop_kind и select_songs.
        self._dead_kinds: set[str] = set()
        from .description_tts import DescriptionSpeech
        self.description_tts = DescriptionSpeech(
            settings, self.session, self.log, self.stopped)
        from .description_batch import DescriptionBatcher
        from .generation_priority import parallel_limit
        self.description_batch = (DescriptionBatcher(
            self.gemini, min(32, parallel_limit(settings)), self.stopped)
            if self.gemini is not None else None)
        # Роды вопросов, у которых кончились КАНДИДАТЫ, а не сама возможность:
        # каталог манги свой и куда меньше аниме, и когда он вычерпан, вопросов
        # по манге больше не будет. Отличается от _dead_kinds тем, что загрузки
        # его не смотрят: уже запущенные качаются до конца.
        self._spent_kinds: set[str] = set()
        # Сколько мест умерших родов осталось пустыми при «сохранять состав».
        self._closed_kinds: dict[str, int] = {}
        from si_hyx_parts.animepack.ai_art_generation import init_art_service
        init_art_service(self, cloudflare)
        from si_hyx_parts.animepack.pixiv_art_generation import init_pixiv_service
        init_pixiv_service(self, pixiv)
        self._pixiv_lock = _api.threading.Lock()
        # Страницы манги и вырезки анимации: каждый род вопросов
        # выбирает картинку из общего списка «уже показанного», поэтому у каждого
        # свой замок вокруг «выбрал → занял».
        from si_hyx_parts.animepack.manga_panel import init_mangadex_service
        init_mangadex_service(self, mangadex)
        self._manga_lock = _api.threading.Lock()
        from si_hyx_parts.animepack.sakuga_generation import init_sakuga_service
        init_sakuga_service(self, sakuga)
        self._sakuga_lock = _api.threading.Lock()
        # Отдельный замок на саму загрузку вырезки: ffmpeg тянет её прямо с сайта,
        # и десяток параллельных чтений там встречают хуже одного.
        self._sakuga_net_lock = _api.threading.Lock()
        # Сколько обложек взято из общей кладовой, а сколько пришло с TMDB —
        # печатается в итогах прогона. Считается из рабочих потоков, поэтому
        # под замком.
        self._poster_lock = _api.threading.Lock()
        self._poster_hits = 0
        self._poster_tmdb = 0
        # Попадания в новую кладовую показываем в итогах: так видно, ускорил ли
        # повторный прогон именно кэш, а не случайно быстрая сеть.
        self._media_cache_hits: _api.Counter = _api.Counter()
        self._media_cache_lock = _api.threading.Lock()
        from .one_use_cache import purge as purge_one_use_cache
        purge_one_use_cache()
        self.folder: str = ""
        self._failed_media = 0
        # Карточки каталога и части франшиз, пережившие перезапуск программы.
        self.db_cache = db_cache if db_cache is not None else _api.ShikimoriDbCache()
        # Части спрашиваются по ключу Shikimori один раз, но индекс считается по
        # ветке названия: Shikimori порой склеивает две серии одним кроссовером.
        self._fr_parts: dict[str, list] = {}
        self._fr_index: dict[tuple[str, str], float] = {}
        # Кадры, уже показанные в прошлых паках (галочка «не повторять»), плюс
        # взятые в этом паке. Медиа качается из нескольких потоков — выбор и
        # резервирование кадра идут под замком.
        self.frames_history_path = frames_history_path
        self._frames_lock = _api.threading.Lock()
        self._frames_used: set[str] = set()
        if settings.frames_no_repeat:
            self._frames_used = {_api.frame_url_key(u)
                                 for u in _api.load_frame_history(frames_history_path)}
            self._frames_used.discard("")
        # Одна студия — один вопрос в паке. Кадры качаются в нескольких
        # потоках, поэтому выбор и бронь делаются под одним замком.
        self._studio_lock = _api.threading.Lock()
        self._used_studios: set[str] = set()
        self._studio_catalog = None
        # Имена медиафайлов внутри пака («Сгенерировано в SI-HYX(Тайтл)») —
        # раздаются из нескольких потоков, поэтому счётчик под замком.
        self._names_lock = _api.threading.Lock()
        self._names: dict[str, int] = {}
        # Франшизы, уже спрошенные в чужих паках (список .siq в настройках).
        self._excluded_roots: set[str] = set()
        # Франшизы тех же чужих паков: корень названия закрывает только одинаково
        # названные части, а франшиза — всю серию (просьба пользователя).
        self._excluded_franchises: set[str] = set()
        # Студии из паков в списке «не повторять франшизы». Список точных
        # вопросов сюда намеренно не относится.
        self._excluded_studios: set[str] = set()
        self._exact_keys: set[tuple] = set()
        self._exact_seen: set[tuple] = set()
        self._exact_lock = _api.threading.Lock()
        self._exact_pending: dict = {}
        self._early_repeats = 0
        self._early_repeat_attempts = 0
        # Франшизы, уже взятые В ЭТОМ паке. Набор ОДИН на оба потока кандидатов:
        # у каждого потока был свой, и пак выдавал кадр из франшизы, а следом
        # страницу манги оттуда же (просьба пользователя — повторов быть не должно).
        self._used_franchise: set[str] = set()
        # Что забронировал последний принятый тайтл — цикл отбора вешает это
        # на карточку кандидата и возвращает франшизу, если вопросом он не
        # стал (см. _release_candidate).
        self._last_reserved: tuple = ()
        # Потоки кандидатов, которые больше не нужны: их каталог не
        # спрашивается вовсе (см. _close_spent_streams).
        self._closed_streams: set[str] = set()
        # Потоки, которым сейчас нечего дать паку: их не спрашивают, пока
        # отдают другие (см. _rest_anime_streams и _merge_streams).
        self._idle_streams: set[str] = set()
        # Сколько книг каталог уже отдал (см. _close_spent_streams).
        self._manga_seen = 0
        # Конец каталога книг ждёт, пока его последние книги пройдут очередь
        # проверок: отдано потоком / получено отбором (_close_spent_streams).
        self._manga_catalog_end = ""
        self._manga_yielded = 0
        self._manga_drawn = 0
        # Карточки аниме-экранизаций книг: {id Shikimori: карточка}. Пустая
        # карточка значит «спрашивали, аниме не нашлось».
        self._adapt_cache: dict[int, dict] = {}
        # Первые части франшиз: {ключ франшизы: карточка первого сезона}. Нужны
        # поиску артов на Pixiv — там теги висят на первом сезоне, а не на
        # продолжении (см. _first_season_card).
        self._first_season: dict[str, dict] = {}
        # Доли внутри книжной части пака (экранизованная манга, манхва, маньхуа).
        # Нулевая квота значит «книг в паке нет» — тогда счётчик пропускает всех.
        self._manga_mix = _api.MangaMix(settings, 0, log=lambda m: self.log(m))
        # Запущенные ffmpeg: по «Стоп» их надо убить, иначе вкладка ждёт
        # окончания кодирования (до нескольких секунд на вопрос).
        self._procs_lock = self._runtime.lock
        self._procs = self._runtime.processes
        # Карточки, уже приехавшие из каталога Shikimori (order: random).
        self._card_cache: dict[int, dict] = {}
        # То же для манги — отдельным словарём: id манги и аниме на MAL живут в
        # разных пространствах и совпадают сплошь и рядом.
        self._manga_cache: dict[int, dict] = {}
        # Вес пака: бюджет в байтах и то, что уже набрано. Ничего под лимит не
        # подгоняется — по среднему весу вопроса виден прогноз на весь пак, и
        # как только он вылезает за потолок, отбор останавливается.
        self._byte_budget = (max(1, int(getattr(settings, "max_pack_mb", _api.MAX_PACK_MB)
                                        or _api.MAX_PACK_MB))
                             * 1024 * 1024 * _api.PACK_OVERHEAD)
        self._bytes_used = 0
        # Ролики опенингов с AnimeThemes: {MAL id: {«OP1»: {...}}}, спрашиваются
        # пачками по ходу отбора.
        self._themes_cache: dict[int, dict] = {}
        self._themes_lock = _api.threading.Lock()
        # Защита совместимой пробы длительности; сетевые загрузки всех
        # генераторов дополнительно сериализует общий theme_http.GATE.
        self._video_lock = _api.threading.Lock()
        # {url ролика: его длительность в секундах} — нужна, чтобы взять из
        # ролика случайный отрезок (_video_start).
        self._video_len: dict[str, float] = {}
        self._video_len_lock = _api.threading.Lock()
        self._theme_protocol_args: dict[str, list[str] | None] = {}
        # Сколько времени ушло на каждый этап — итог печатается в конце (просьба
        # пользователя). Храним не сумму, а сами отрезки «с какой по какую
        # секунду шёл этап»: загрузки идут в несколько потоков, и сумма их
        # длительностей запросто больше всей генерации (те самые «картинки:
        # 17 мин, 487%» при трёх с половиной минутах работы). Проценты считаются
        # по СКЛЕЕННЫМ отрезкам — сколько времени на часах этап реально занимал.
        self._stage_lock = _api.threading.Lock()
        self._stage_spans: dict[str, list[tuple[float, float]]] = {}
        self._stage_order: list[str] = []
        from .generation_diagnostics import GenerationDiagnostics
        self._diagnostics = GenerationDiagnostics()
        # Ники, чьи списки просили «в основном музыку»: их тайтлы по возможности
        # становятся песенными вопросами, а не кадрами и персонажами.
        self._music_nicks = {u.username.strip().casefold()
                             for u in (settings.users or [])
                             if u.prefer_music and u.username.strip()}
        # Счётчик подряд отвергнутых ради средней сложности (см. _level_fits) —
        # по корзинам: общая средняя пака (ключ None) и свои у артов и книг.
        self._level_skips: dict = _api.Counter()
        self._level_warned: set = set()
        # Скамейка кандидатов, временно не подходящих под просимую середину.
        # Выбрасывать их навсегда нельзя: за прогон так сгорел 321 кандидат при
        # недобранном паке (см. _bench_candidate и _take_level_bench).
        self._level_bench: list = []
        self._level_bench_cap = max(200, int(settings.total_questions or 0) * 20)
        self._level_relaxed = False
        # Каталог аниме кончился раньше книжного: середина не сторожится для
        # аниме-вопросов, книги ещё отбираются под неё (см. _take_anime_bench).
        self._anime_level_relaxed = False
        self._anime_bench: list = []
        self._level_benched = 0
        self._level_reused = 0
        # Списки заводятся по РЕЕСТРУ корзин, а не перечислением: «сюжет» добавили
        # в level_avg.py, а сюда вписать забыли — и пак из одних сюжетных вопросов
        # падал с KeyError: 'plot' на первом же кандидате.
        self._bucket_levels: dict[str, list[int]] = {
            bucket: [] for bucket in _api.LEVEL_BUCKETS}
        # То же самое, но для средней сложности ПЕРСОНАЖЕЙ. Уровень равен уровню
        # тайтла, а отдельная настройка держит нужный состав именно этой доли.
        self._char_levels: list[int] = []
        self._char_lock = _api.threading.Lock()
        self._char_skips = 0
        self._char_warned = False
        # Сложность, которую реально держим: ноль — ту, что просили. Просимая
        # бывает недостижима в принципе (см. _char_reach), и тогда генератор
        # переезжает на ближайшую достижимую, а не «берёт что есть».
        self._char_target_eff = 0
        # Какие персонажи в этом паке реально попадались (по их сложности) и по
        # скольким кандидатам это уже видно.
        self._char_reach_lo = _api.MAX_LEVEL
        self._char_reach_hi = 1
        self._char_seen = 0
        # А это теоретический размах: что вообще возможно при таких тайтлах.
        # Нужен только для формулировки — «таких не бывает» или «не попадались».
        self._char_floor = _api.MAX_LEVEL
        self._char_ceil = 1
        # Сколько раз уже жаловались на одну и ту же беду (см. _log_rare).
        self._warn_lock = _api.threading.Lock()
        self._warn_counts: dict[str, int] = {}
        # Отчёт «почему кандидатов не хватило»: сколько тайтлов база вообще
        # дала, сколько из них прошло проверки и на чём отсеялись остальные
        # (см. _accept_anime и _log_shortage).
        self._seen_titles = 0
        self._good_titles = 0
        self._skips: _api.Counter = _api.Counter()
        # То же самое порознь по каталогам: «база дала 6 627 тайтлов» одной
        # строкой скрывало, что там 5 778 книг и 849 аниме с подходящей песней.
        self._seen_by_media: _api.Counter = _api.Counter()
        self._good_by_media: _api.Counter = _api.Counter()
        # Сколько раз мы и правда пробовали собрать вопрос (по родам вопросов) и
        # на чём попытка сорвалась уже после начала загрузки.
        self._tries: _api.Counter = _api.Counter()
        self._late: _api.Counter = _api.Counter()
        self._rejected_media = 0
        # Каталог аниме, разобранный один раз на оба потока кандидатов.
        self._card_feed = None
        # Годный тайтл вопросом всё равно не стал: мест под его род уже нет или
        # он утащил бы среднюю сложность. Раньше такие уходили молча, и в отчёте
        # зияла дыра — «годных 1674», а попыток загрузки 257 (просьба
        # пользователя: «почему не хватило кандидатов»).
        self._drops: _api.Counter = _api.Counter()

    # ── служебное ─────────────────────────────────────────────────────────
    def log(self, msg: str) -> None:
        self._log(msg)

    # Сколько раз подряд можно повторить в логе одну и ту же жалобу.
    WARN_REPEATS = 3

    def _log_rare(self, tag: str, message: str) -> None:
        """Пишет повторяющуюся жалобу не больше WARN_REPEATS раз за прогон.

        Когда сервер начинает отказывать, ошибка приходит на КАЖДЫЙ вопрос, и
        консоль превращается в простыню из одинаковых строк — по ней уже не
        видно, что вообще происходит с паком."""
        with self._warn_lock:
            n = self._warn_counts.get(tag, 0) + 1
            self._warn_counts[tag] = n
        if n > self.WARN_REPEATS:
            from diagnostic_logging import archive
            import re
            archive(f"{tag}: " + re.sub(r"https?://\S+", "[URL]", str(message)))
        if n <= self.WARN_REPEATS:
            self.log(message)
        elif n == self.WARN_REPEATS + 1:
            self.log(f"{tag}: та же ошибка повторяется — дальше молчу, "
                     "итог будет в конце.")

    def _log_warn_totals(self) -> None:
        """Итог по замолчанным жалобам: сколько раз каждая из них случилась."""
        with self._warn_lock:
            rows = [(tag, n) for tag, n in self._warn_counts.items()
                    if n > self.WARN_REPEATS]
        for tag, n in rows:
            self.log(f"{tag}: всего таких ошибок за прогон — {n}.")

    def stopped(self) -> bool:
        runtime = getattr(self, "_runtime", None)
        event = getattr(runtime.local, "candidate_stop", None) if runtime else None
        return (bool(self._should_stop()) or bool(event and event.is_set())
                or bool(runtime and runtime.current_task_cancelled()))

    # ── сколько времени ушло на что ───────────────────────────────────────
    @_api.contextmanager
    def _timed(self, stage: str):
        """Запоминает отрезок работы этапа: «с какой по какую секунду».

        Зовётся и из рабочих потоков, поэтому под замком; порядок первых
        появлений запоминаем — по нему потом печатается итог."""
        started = _api.time.monotonic()
        try:
            with self._diagnostics.stage(stage):
                yield
        finally:
            ended = _api.time.monotonic()
            with self._stage_lock:
                if stage not in self._stage_spans:
                    self._stage_spans[stage] = []
                    self._stage_order.append(stage)
                self._stage_spans[stage].append((started, ended))

    @staticmethod
    def _merge_spans(spans) -> float:
        """Длина СКЛЕЕННЫХ отрезков — сколько времени на часах этап шёл хоть в
        одном потоке. Восемь картинок, качавшихся одновременно по десять секунд,
        это десять секунд работы, а не восемьдесят."""
        rows = sorted((a, b) for a, b in spans if b > a)
        total, cur_start, cur_end = 0.0, None, None
        for start, end in rows:
            if cur_end is None or start > cur_end:
                if cur_end is not None:
                    total += cur_end - cur_start
                cur_start, cur_end = start, end
            elif end > cur_end:
                cur_end = end
        if cur_end is not None:
            total += cur_end - cur_start
        return total

    def log_stage_times(self, total: float = 0.0) -> None:
        """Печатает в лог, сколько заняла каждая часть работы.

        Время этапа — по часам, а не в человеко-секундах: сумма длительностей
        параллельных загрузок раньше давала «картинки: 17 мин, 487%» при трёх
        минутах работы. Сумма по потокам всё же остаётся в строке — по ней
        видно, насколько плотно этап был загружен."""
        with self._stage_lock:
            stages = [(name, list(self._stage_spans[name]))
                      for name in self._stage_order]
        if not stages:
            return
        from .generation_diagnostics import peak_parallel
        self._diagnostics.report(self)
        if total > 0:
            self.log(f"Время по этапам (всего {_api.fmt_elapsed(total)}):")
        else:
            self.log("Время по этапам:")
        for name, spans in stages:
            wall = self._merge_spans(spans)
            summed = sum(max(0.0, b - a) for a, b in spans)
            share = f", {min(100.0, wall / total * 100):.0f}%" if total > 0 else ""
            tail = ""
            if summed > wall * 1.2:
                tail = (f" (суммарно по задачам {_api.fmt_elapsed(summed)}, "
                        f"максимум одновременно {peak_parallel(spans)})")
            self.log(f"  • {name}: {_api.fmt_elapsed(wall)}{share}{tail}")

    def log_gemini_spent(self) -> None:
        """HTTP-попытки, коды ответов и оценка расхода квоты данного ключа."""
        # Клиент в тестах бывает заглушкой — считаем только настоящие счётчики.
        clients = {id(c): c for c in (getattr(self, "gemini", None),
                                      getattr(self, "gemini_titles", None),
                                      getattr(self, "gemini_pixiv", None),
                                      getattr(self, "gemini_manga", None),
                                      *getattr(self, "_gemini_clients", ()))
                   if isinstance(getattr(c, "spent", None), dict)}
        spent: _api.Counter = _api.Counter()
        quota_estimate = 0
        codes: _api.Counter = _api.Counter()
        for client in clients.values():
            spent.update(client.spent)
            quota_estimate += int(getattr(client, "requests_made", 0) or 0)
            codes.update(getattr(client, "response_codes", {}) or {})
        if not spent:
            return
        parts = ", ".join(f"{name}: {count}"
                          for name, count in sorted(spent.items()))
        total = sum(spent.values())
        ok = sum(count for code, count in codes.items()
                 if isinstance(code, int) and 200 <= code < 300)
        labels = {"network": "сеть", "timeout": "таймаут"}
        errors = ", ".join(f"{labels.get(code, code)}: {count}" for code, count in sorted(
            codes.items(), key=lambda item: str(item[0]))
            if not isinstance(code, int) or not 200 <= code < 300)
        tail = f"; успешных HTTP-ответов {ok}"
        if errors:
            tail += f"; ошибки ({errors})"
        tail += f"; возможный расход квоты {quota_estimate} (локальная оценка)"
        # Куда ушли обращения за сюжетом: без этой расшифровки «16 вопросов —
        # 23 запроса» выглядело необъяснимо (просьба пользователя).
        plot = getattr(self, "_plot_calls", None) or {}
        if plot:
            tail += "; сюжет: " + ", ".join(
                f"{name} — {count}" for name, count in sorted(plot.items()))
        self.log(f"Gemini: HTTP-попыток за прогон {total} ({parts}){tail}.")
        purposes = _api.Counter()
        for client in clients.values():
            purpose = getattr(client, "purpose", "Прочее")
            if isinstance(purpose, str):
                purposes[purpose] += sum(client.spent.values())
        self.log("Gemini по назначению: " + ", ".join(
            f"{name} — {count}" for name, count in sorted(purposes.items())) + ".")
        for batcher in getattr(self, "_visual_batches", {}).values():
            stats = getattr(batcher, "purpose_stats", {})
            if stats:
                self.log("Gemini, изображения: " + ", ".join(
                    f"{purpose}: {size} изображений × {count} пачек"
                    for (purpose, size), count in sorted(stats.items())) + ".")
        from .visual_spare import log_summary as log_spare
        log_spare(self)

    def _over_budget(self, done: int, total: int) -> bool:
        """Пора ли останавливаться из-за веса.

        Ждать, пока пак реально перевалит за потолок, поздно — половина работы
        к тому моменту уже сделана впустую. Поэтому смотрим на средний вес
        набранного вопроса и прикидываем, во что выльется весь пак; первые
        BUDGET_WARMUP вопросов в расчёт не берём — на них разброс слишком велик
        (у одного тайтла ролик, у другого один постер)."""
        if self._bytes_used >= self._byte_budget:
            return True
        if done < _api.BUDGET_WARMUP or done >= total:
            return False
        # A heavy first batch is not evidence that the remaining text/images
        # will have the same size. Stop on actual bytes, not that extrapolation.
        return False

    def _media_size(self, cand: _api.SongCandidate) -> int:
        """Сколько байт занимает медиа этого вопроса в готовом паке."""
        names = []
        if cand.has_video:
            names.append(_api.os.path.join("Video", cand.entrance_video or cand.video_out))
        elif not cand.is_silent or (cand.kind == _api.DESCRIPTION_AUDIO_KIND
                                    and cand.description_audio_ext):
            names.append(_api.os.path.join("Audio", cand.audio_out))
        for flag, name in ((cand.has_poster, cand.poster_file),
                           (cand.has_collage, cand.collage_file),
                           (cand.has_frame and cand.frame_file not in cand.entrance_frames,
                            cand.frame_file)):
            if flag and name:
                names.append(_api.os.path.join("Images", name))
        # Остальные кадры вопроса-студии весят столько же, сколько первый, и в
        # бюджет пака обязаны входить наравне с ним.
        for name in cand.extra_frames:
            if name and name not in cand.entrance_frames:
                names.append(_api.os.path.join("Images", name))
        names.extend(_api.os.path.join("Video", name) for name in cand.entrance_frames.values())
        total = 0
        # Через set: у вопроса-обложки картинка вопроса и постер ответа — это
        # ОДИН файл, и считать его дважды нельзя.
        for rel in dict.fromkeys(names):
            try:
                total += _api.os.path.getsize(_api.os.path.join(self.folder, rel))
            except OSError:
                pass
        return total

    # Сколько карточек тянем из каталога Shikimori на один вопрос пака: часть
    # отсеют фильтры (оценка, жанры, дубли франшиз), часть не переживёт загрузку
    # медиа, так что запас нужен изрядный.
    RANDOM_OVERSHOOT = 8
    # Песенному паку запас нужен куда больше: песня в AnisongDB нашлась лишь у
    # 59 случайных тайтлов Shikimori из 150 (у ТВ-сериалов — у 31 из 52), а
    # мастер-лист AMQ по определению состоит из одних только «песенных».
    RANDOM_OVERSHOOT_SONGS = 20
    # У манги отсев самый длинный, и запаса «как у аниме» ей мало. Случайная
    # манга из каталога — это почти всегда безвестный тайтл: из 100 карточек,
    # набранных прежним запасом, рамку сложности не прошла НИ ОДНА сама по себе
    # (проходят только те, у кого есть популярная аниме-экранизация), а из
    # прошедших ещё часть не находится на MangaDex. Сотня карточек на пак
    # оставляла долю манги пустой ещё до первого запроса к MangaDex.
    RANDOM_OVERSHOOT_MANGA = 40
    RANDOM_MAX_PAGES = 60

    # Обход каталога ЦЕЛИКОМ (кнопка «Обновить базу»). Порядок тут нужен
    # устойчивый: при order: random сервер тасует выборку на каждый запрос,
    # страницы накладываются друг на друга, и обход упирался в «страницу без
    # новых id» на первых же сотнях карточек, сколько бы их ни было в каталоге
    # на самом деле. С order: id каждая страница отдаёт свой кусок ровно один
    # раз, и каталог по-настоящему кончается.
    FULL_ORDER = "id"
    # Предохранитель от бесконечного цикла, если сервер вдруг перестанет
    # слушаться page: 50 карточек на страницу — это четверть миллиона тайтлов,
    # больше всего каталога Shikimori.
    FULL_MAX_PAGES = 5000

    # Сколько книг просматриваем ради книжных долей, прежде чем перейти на
    # отложенные. Каталог книг вчетверо больше каталога аниме, а подходящих по
    # долям (экранизованные, манхва, маньхуа) в нём немного: перебирать его до
    # конца — только время, отложенных на скамейке к тому моменту с запасом.
    BOOK_SCAN_PER_SLOT = 100
    BOOK_SCAN_MIN = 200

    # Столько кандидатов подряд можно отвергнуть ради средней сложности.
    LEVEL_AVG_GIVE_UP = 60
    # То же для персонажей. Порог ниже: каждый отвергнутый персонаж — это уже
    # сделанный запрос к Shikimori, и полсотни таких подряд заняли бы минуту.
    CHAR_LEVEL_GIVE_UP = 20

    # «В избранном у всех на свете»: с таким числом char_question_level даёт
    # самый лёгкий уровень, какой у персонажа этого тайтла вообще возможен.
    _FAV_ALL = 10 ** 9
    # Со стольких увиденных персонажей верим границам достижимого. Раньше
    # недостижимость вскрывалась только после двух десятков впустую перебранных
    # кандидатов — а каждый из них это ещё и запрос к Shikimori. Меньше десятка
    # брать не стоит: границы ещё гуляют, и генератор объявляет о переезде
    # несколько раз подряд.
    CHAR_REACH_SAMPLE = 10

    # Обновление базы по частям: каталог аниме, каталог манги, узнаваемость
    # франшиз и «хвосты» кэша обновляются порознь (панель «Что в базе»).

    def refresh_db(self, parts=None) -> int:
        """Собирает заново выбранные части базы Shikimori.

        Каталог берётся ЦЕЛИКОМ, а не «сколько нужно на пак»: кнопка на то и
        нужна, чтобы база потом хватала на любой пак с этими фильтрами (просьба
        пользователя — раньше обход останавливался на нескольких сотнях
        карточек). Идёт это долго, поэтому на каждой странице проверяется
        «Остановить», а набранное сохраняется по ходу дела.

        parts — какие части обновлять (см. db_refresh_parts); None значит
        полный обход аниме, книг, внешней популярности, избранного и франшиз,
        независимо от настроек генерации. Возвращает, сколько карточек
        каталога лежит в кэше после обновления."""
        wanted = _api.db_refresh_parts(parts, self.s)
        started = _api.time.time()
        if wanted:
            from pathlib import Path
            from .db_backup import backup_database
            self.db_cache.save()
            backup_database(self.db_cache, Path(self.db_cache.path).parent / "db_backups"
                            / str(_api.time.time_ns()))
        if "extras" in wanted:
            gone = self.db_cache.clear_part("extras")
            self.log(f"База Shikimori: забыто {gone} запомненных ответов "
                     "(персонажи, кадры, пригодность тайтлов) — спросятся заново "
                     "при следующей генерации.")
        cards = refresh_database_sources(self, wanted, _refresh_catalogs, _refresh_favorites)
        if self.stopped():
            from .db_refresh_report import finish_report
            finish_report(self, wanted, started)
            self.log("База Shikimori: остановлено, набранное всё же сохранено.")
            return _db_card_count(self)
        if "franchises" in wanted:
            _refresh_franchises(self, cards)
        from .db_refresh_report import finish_report
        report = finish_report(self, wanted, started)
        if report["status"] == "ERROR":
            detail = "Полученные данные сохранены." if report.get("saved") else "Не все данные записаны."
            raise _api.AnimePackError("Обновление базы не завершено. " + detail + "\n"
                                     + "\n".join(report["failures"]))
        total = _db_card_count(self)
        self.log(f"Сбор базы: {report['status']}; {total} карточек, "
                 f"{len(self._fr_parts)} франшиз; недоступных счётчиков "
                 f"{report['restricted']}, неизвестных {report['unknown']}.")
        return total

    # ── всё вместе ────────────────────────────────────────────────────────
    def run(self, out_path: _api.Optional[str] = None) -> _api.PackResult:
        result = _api.PackResult(
            requested=self.s.total_questions,
            pack_number=int(getattr(self.s, "pack_number", 0) or 0))
        started = _api.time.monotonic()
        self._run_started = started
        result.planned = dict(self.s.question_quotas)
        readable_log = None
        songs = []
        self._selected_songs = songs
        try:
            from .run_log import start as start_log
            readable_log = start_log(self)
            result.log_path = str(readable_log.path)
            _prepare(self, out_path)
            songs = self.select_songs()
            result.songs = songs
            result.actual = dict(_api.Counter(c.kind for c in songs))
            result.failed_media = self._failed_media
            if self.stopped():
                result.cancelled = True
                if songs:
                    self.log(f"Остановлено: сохраняю {len(songs)} готовых вопросов…")
                    result.path = self.write_package(songs, out_path)
                    self.save_frames_history(songs)
                    from .title_rotation import record as record_titles
                    record_titles(songs)
                    self.log(f"Частичный пак готов: {result.path}")
                return result
            if not songs:
                raise _api.AnimePackError(
                    "Не набралось ни одного вопроса. Проверьте ошибки в журнале "
                    "или ослабьте фильтры (сложность, жанры, годы, типы аниме).")
            if len(songs) < self.s.total_questions:
                from .shortage_report import short_reason
                self.log(f"Внимание: вопросов будет {len(songs)}, а не "
                         f"{self.s.total_questions} — {short_reason(self)}.")
                exhausted = (getattr(self, "_selection_end", None) or {}).get("exhausted")
                if exhausted and self.s.random_pool and self.s.has_songs \
                        and self._random_source == "shikimori":
                    # Замерено: песня в AnisongDB находится у 59 случайных
                    # тайтлов Shikimori из 150. С фильтром «Сложность пака»
                    # (узнаваемость) остаётся и того меньше.
                    self.log("Для песенного пака база AMQ плотнее: в каталоге "
                             "Shikimori песня есть примерно у четырёх тайтлов "
                             "из десяти, а «Сложность пака» режет ещё сильнее. "
                             "Поставьте «Случайные из базы AMQ» или ослабьте "
                             "сложность.")
            self._assemble_or_keep(songs, out_path, result)
            return result
        except Exception as error:
            if getattr(self, "_preserve_media", False):
                raise
            from .pack_completion import after_error
            after_error(self, songs or self._selected_songs, out_path, result, error)
            return result
        finally:
            from .pack_completion import finish
            finish(self, result, started, readable_log)

    def assemble(self, songs: list, out_path, result) -> None:
        """Готовые вопросы → .siq: проверка средней, списки, авторы, упаковка."""
        from .pack_completion import report_targets, optional
        report_targets(self, songs, result)
        with self._timed("проверка списков"):
            optional(self, result, 'Проверка списков', lambda: self.mark_list_owners(songs))
        from .author_lookup import enrich_authors
        with self._timed("авторы"):
            optional(self, result, 'Авторы', lambda: enrich_authors(self.shikimori, songs, self.log))
        self.log("Собираю пакет…")
        with self._timed("сборка .siq"):
            result.path = self.write_package(songs, out_path)
        optional(self, result, 'История кадров', lambda: self.save_frames_history(songs))
        from .title_rotation import record as record_titles
        optional(self, result, 'История названий', lambda: record_titles(songs))
        try:
            mb = _api.os.path.getsize(result.path) / (1024.0 * 1024.0)
            limit = int(self.s.max_pack_mb)
            self.log(f"Вес пака: {mb:.1f} МБ (потолок {limit} МБ)")
            if mb > limit:
                self.log("Внимание: пак вышел тяжелее потолка — так бывает, "
                         "когда сжатие медиа выключено и размер задаём не мы.")
        except OSError:
            pass

    def _assemble_or_keep(self, songs: list, out_path, result) -> None:
        """Упаковка; при её ошибке готовые вопросы и медиа не пропадают."""
        try:
            self.assemble(songs, out_path, result)
        except Exception as error:
            from .pack_completion import after_error
            after_error(self, songs, out_path, result, error)

    def rebuild(self, path: str, out_path: _api.Optional[str] = None) -> _api.PackResult:
        """Собирает пак из сохранённой попытки с ТЕКУЩИМИ настройками."""
        from . import assembly_recovery
        songs, parts = assembly_recovery.load(path)
        self._recovery_source = _api.os.path.realpath(path)
        result = _api.PackResult(
            requested=self.s.total_questions, songs=songs,
            pack_number=int(getattr(self.s, "pack_number", 0) or 0))
        started = _api.time.monotonic()
        self._run_started = started
        for key, rows in parts.items():
            self._fr_parts.setdefault(key, rows)
        self._selected_songs = songs
        result.planned = dict(_api.Counter(c.kind for c in songs))
        readable_log = None
        try:
            from .run_log import start as start_log
            readable_log = start_log(self)
            result.log_path = str(readable_log.path)
            self.log(f"Собираю сохранённую попытку: {len(songs)} вопросов…")
            _api.install_favorites_norms(self.db_cache)
            import tempfile
            import shutil
            self.folder = tempfile.mkdtemp(prefix='si-hyx-rebuild-')
            shutil.copytree(path, self.folder, dirs_exist_ok=True)
            hook = getattr(self, '_prepare_recovery', None)
            if hook is not None:
                hook(songs)
            # A selection failure may precede the final title-riddle batch.
            # Finish only missing texts; ready questions need no new requests.
            from .title_questions import KINDS, generate_titles
            missing = [c for c in songs if c.kind in KINDS and not c.plot_question]
            if missing:
                finished = generate_titles(self, missing)
                pending = {id(c) for c in missing}
                ready = {id(c) for c in finished}
                songs = [c for c in songs if id(c) not in pending or id(c) in ready]
                result.songs = songs
            from .recovery_average import repair
            repair(self, songs)
            result.actual = dict(_api.Counter(c.kind for c in songs))
            self._assemble_or_keep(songs, out_path, result)
        except Exception as error:
            if getattr(self, '_preserve_media', False):
                raise
            from .pack_completion import after_error
            after_error(self, songs, out_path, result, error)
        finally:
            from .pack_completion import finish
            finish(self, result, started, readable_log)
        # Retain the original snapshot until the user removes it; another retry
        # must remain possible even after publishing the verified archive.
        return result


AnimePackGenerator.__module__ = _api.__name__
_api.AnimePackGenerator = AnimePackGenerator
