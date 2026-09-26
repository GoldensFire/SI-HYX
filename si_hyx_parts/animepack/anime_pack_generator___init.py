# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""AnimePackGenerator: __init__. Public namespace: animepack."""
from __future__ import annotations
import animepack as _api


def __init__(self, settings: _api.PackSettings, *,
             session=None, amq=None, anisong=None, mal=None, shikimori=None,
             anilist=None, kitsu=None, themes=None, fandom=None, gemini=None,
             tmdb=None, cloudflare=None, pixiv=None, anizip=None,
             mangadex=None, sakuga=None,
             jimaku=None, subdl=None,
             log: _api.Optional[_api.Callable[[str], None]] = None,
             progress: _api.Optional[_api.Callable[[int, int, str], None]] = None,
             should_stop: _api.Optional[_api.Callable[[], bool]] = None,
             rng: _api.Optional[_api.random.Random] = None,
             frames_history_path: str = _api.FRAMES_HISTORY_FILE,
             db_cache: _api.Optional[_api.ShikimoriDbCache] = None):
    self.s = settings
    # Эти обратные вызовы нужны клиентам, создаваемым ниже. В частности Pixiv
    # сразу получает rng; поэтому они должны существовать до init_*_service.
    self._log = log or (lambda msg: None)
    self._progress = progress or (lambda done, total, msg: None)
    self._should_stop = should_stop or (lambda: False)
    self.rng = rng or _api.random.Random()
    self.session = session or _api.make_session()
    self.amq = amq or _api.AmqApi(self.session)
    self.anisong = anisong or _api.AnisongApi(self.session)
    self.mal = mal or _api.MalApi(self.session)
    self.shikimori = shikimori or _api.ShikimoriApi(self.session)
    self.anilist = anilist or _api.AniListApi(self.session)
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
    self.gemini_board = None
    # Загадки по названию ходят к Gemini СВОИМ клиентом: модель и уровень
    # рассуждения у них отдельные от сюжета и диалогов (просьба
    # пользователя). Подменённый в тестах клиент один на всё.
    self.gemini_titles = gemini
    self.gemini_pixiv = gemini
    needs_general = any(settings.mix_shares.get(k)
                        for k in (_api.PLOT_KIND, _api.DIALOGUE_KIND))
    needs_titles = any(settings.mix_shares.get(k)
                       for k in _api.GEMINI_TITLE_KINDS)
    needs_pixiv = bool(settings.mix_shares.get(_api.PIXIV_ART_KIND)
                        and getattr(settings, "pixiv_gemini_check", True))
    # Страницы манги Gemini проверяет на название тайтла (manga_panel);
    # без галочки клиента нет — и проверки тоже.
    needs_manga = bool(settings.mix_shares.get(_api.MANGA_KIND)
                       and getattr(settings, "manga_gemini_check", True))
    self.gemini_manga = gemini if needs_manga else None
    if needs_general or needs_titles or needs_pixiv or needs_manga:
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

            def _client(model, thinking):
                return GeminiClient(
                    key, model=(model or DEFAULT_MODEL),
                    thinking=str(thinking or ""),
                    log=lambda msg: self.log(msg),
                    stopped=lambda: self.stopped(),
                    board=self.gemini_board)

            think = str(getattr(settings, "gemini_thinking", "") or "")
            if needs_general and self.gemini is None:
                self.gemini = _client(settings.gemini_model, think)
            if needs_titles and self.gemini_titles is None:
                # Пустая своя модель значит «как у сюжета»: так открываются
                # настройки, сохранённые до появления второго выбора.
                self.gemini_titles = _client(
                    str(getattr(settings, "gemini_title_model", "") or "")
                    or settings.gemini_model,
                    str(getattr(settings, "gemini_title_thinking", "") or "")
                    or think)
            if needs_pixiv and self.gemini_pixiv is None:
                self.gemini_pixiv = _client(
                    str(getattr(settings, "pixiv_gemini_model", "") or "")
                    or settings.gemini_model, "minimal")
            if needs_manga and self.gemini_manga is None:
                self.gemini_manga = _client(
                    str(getattr(settings, "manga_gemini_model", "") or "")
                    or settings.gemini_model, "minimal")
    self.jimaku = jimaku
    if settings.mix_shares.get(_api.DIALOGUE_KIND) and self.jimaku is None:
        key = str(getattr(settings, "jimaku_key", "") or "").strip()
        if key:
            self.jimaku = _api.JimakuApi(key, self.session)
    # SubDL — первый источник диалогов (русские субтитры, без Gemini);
    # Jimaku остаётся на время, когда суточная квота SubDL кончится.
    self.subdl = subdl
    if settings.mix_shares.get(_api.DIALOGUE_KIND) and self.subdl is None:
        key = str(getattr(settings, "subdl_key", "") or "").strip()
        if key:
            self.subdl = _api.SubdlApi(key, self.session)
    self._dialogue_lock = _api.threading.Lock()
    self._dialogue_seen: set[tuple[int, int]] = set()
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
    # Роды вопросов, у которых кончились КАНДИДАТЫ, а не сама возможность:
    # каталог манги свой и куда меньше аниме, и когда он вычерпан, вопросов
    # по манге больше не будет. Отличается от _dead_kinds тем, что загрузки
    # его не смотрят: уже запущенные качаются до конца.
    self._spent_kinds: set[str] = set()
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
    # Сколько книг каталог уже отдал (см. _close_spent_streams).
    self._manga_seen = 0
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
    self._procs_lock = _api.threading.Lock()
    self._procs: set = set()
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
    # Ролики качаются строго по одному (см. VIDEO_RETRIES).
    self._video_lock = _api.threading.Lock()
    # {url ролика: его длительность в секундах} — нужна, чтобы взять из
    # ролика случайный отрезок (_video_start).
    self._video_len: dict[str, float] = {}
    self._video_len_lock = _api.threading.Lock()
    # Сколько времени ушло на каждый этап — итог печатается в конце (просьба
    # пользователя). Храним не сумму, а сами отрезки «с какой по какую
    # секунду шёл этап»: загрузки идут в несколько потоков, и сумма их
    # длительностей запросто больше всей генерации (те самые «картинки:
    # 17 мин, 487%» при трёх с половиной минутах работы). Проценты считаются
    # по СКЛЕЕННЫМ отрезкам — сколько времени на часах этап реально занимал.
    self._stage_lock = _api.threading.Lock()
    self._stage_spans: dict[str, list[tuple[float, float]]] = {}
    self._stage_order: list[str] = []
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
