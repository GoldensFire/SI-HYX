# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""PackSettings. Public namespace: animepack."""
from __future__ import annotations
import animepack as _api
from cloudflare_art_api import DEFAULT_MODEL as ART_DEFAULT_MODEL
from frame_reveal import EFFECT_LABELS
from image_entrance import PACK_EFFECT_LABELS as ENTRANCE_EFFECT_LABELS
from gemini_api import THINKING_LEVEL as GEMINI_THINKING_LEVEL
from cloudflare_art_api import validate_settings
from pixiv_art_api import validate_settings as validate_pixiv_settings
from frame_reveal import clean_effects
from cover_meta_rules import LANGUAGE_KEYS as COVER_LANGUAGE_KEYS
from cover_meta_rules import TYPE_LABELS as COVER_TYPE_LABELS
from frame_reveal import REMOVED_EFFECTS, add_new_effects
from image_entrance import EDITOR_ONLY_EFFECTS, TARGET_LABELS, clean_keys


@_api.dataclass
class PackSettings:
    """Полный набор настроек генерации (соответствует форме ASPG)."""
    # ── Пак ──────────────────────────────────────────────────────────────
    title: str = "Сгенерировано в SI-HYX"
    rounds: int = 3
    themes: int = 5
    questions: int = 6
    theme_title: str = "SI-HYX"
    # Порядковый номер пака: к названию приписывается «№ 1», «№ 2» и так далее
    # (просьба пользователя), чтобы собранные подряд паки различались и в
    # списке SIGame, и в имени файла. Ноль — номер не приписывать.
    pack_number: int = 0
    test_pack_number: int = 0
    ignore_test_packs: bool = False
    generation_priority: str = "normal"   # low | normal | high
    # ── Списки ───────────────────────────────────────────────────────────
    random_mode: bool = True             # True — случайные аниме из общей базы
    # Откуда берутся случайные аниме: "shikimori" — каталог Shikimori запросом
    # order: random (фильтры уходят на сервер, поэтому мусора приезжает меньше),
    # "amq" — мастер-лист AnimeMusicQuiz. По умолчанию Shikimori: мастер-лист
    # AMQ знает только те тайтлы, у которых есть песни, поэтому годится он лишь
    # песенным пакам (см. has_songs и collect_anime_ids).
    random_source: str = "shikimori"
    users: list[_api.UserList] = _api.field(default_factory=list)
    # Запомненные ники: кнопка «Из сохранённых» показывает именно их. В отборе
    # НЕ участвуют — это просто адресная книга вкладки.
    saved_users: list[_api.UserList] = _api.field(default_factory=list)
    similar_count: int = 2               # у стольких человек должен быть тайтл
    # ── Состав пака ──────────────────────────────────────────────────────
    # Доли вопросов, в процентах: песни / ролики / кадры / персонажи. Ползунок
    # на вкладке двигает именно их, а прежние галочки «только кадры», «только
    # персонажи» и «ещё и кадры по N на песню» — это те же доли (100/0/0 и
    # т.п.), поэтому отдельных настроек больше нет (миграция старых — в
    # from_dict). Доля роликов участвует, только пока стоит галочка song_video
    # (см. percents).
    composition_enabled: list[str] | None = None
    pack_titles: bool | None = None
    pct_titles: int = 0
    title_enabled: list[str] | None = None
    title_shares: dict = _api.field(default_factory=dict)
    pack_synonyms: bool = False
    pack_antonyms: bool = False
    pack_ukrainian: bool = False
    pct_synonyms: int = 0
    pct_antonyms: int = 0
    pct_ukrainian: int = 0
    pack_definitions: bool = False
    pct_definitions: int = 0
    pct_songs: int = 100
    pct_videos: int = 0
    pct_frames: int = 0
    pct_chars: int = 0
    # Доля вопросов по манге/манхве/ранобэ. Своя часть ползунка: у книги нет ни
    # песен, ни кадров, поэтому подмешать её к аниме-вопросам иначе нельзя.
    # Участвует, только пока стоит галочка pack_manga — ровно как доля роликов
    # при song_video (просьба пользователя: без галочки манги на ползунке быть
    # не должно вовсе).
    pack_manga: bool = False
    pct_manga: int = 0
    # Доля кадров с эффектами: кадр становится роликом-проявлением.
    # Прежние ключи pixel сохраняют совместимость настроек и квот.
    pack_pixel: bool = False
    pct_pixel: int = 0
    # Проверка названия и наличия персонажей в исходном кадре.
    frame_gemini_check: bool = False
    pixel_gemini_check: bool = False
    pixel_steps: int = _api.PIXEL_STEPS
    pixel_block: int = _api.PIXEL_BLOCK
    pixel_seconds: int = _api.PIXEL_SECONDS
    pixel_fps: int = _api.PIXEL_FPS
    # Собственный пресет кадров с эффектами, включая DVD-заставку.
    frame_preset: int = _api.VIDEO_PRESET
    # Категория pixel сохраняется в старых настройках, внутри — все эффекты.
    frame_effect: str = "pixelize"       # ключ эффекта или random
    frame_effects: list[str] = _api.field(default_factory=lambda: list(EFFECT_LABELS))
    frame_effects_known: list[str] = _api.field(default_factory=lambda: list(EFFECT_LABELS))
    frame_effect_strength: int = 55
    # «DVD-заставка»: папка с картинками и видео для летающего прямоугольника
    # (пусто — прямоугольник просто окно в кадр).
    frame_dvd_folder: str = ""
    # Кадров/с «DVD-заставки»: 30 или 60 (своя настройка, общий «Кадров/с»
    # ступенчатых эффектов её не касается).
    frame_dvd_fps: int = 30
    # Появление — дополнительная подача выбранных составов, без своей квоты.
    entrance_enabled: bool = False
    entrance_effect: str = "random"
    entrance_effects: list[str] = _api.field(default_factory=lambda: list(ENTRANCE_EFFECT_LABELS))
    entrance_targets: list[str] = _api.field(default_factory=lambda: ["frame"])
    entrance_seconds: float = 1.2
    entrance_strength: int = 70
    entrance_fps: int = 30
    entrance_preset: int = _api.VIDEO_PRESET
    # Доля вопросов-АНАГРАММ и язык названия, которое перемешивается.
    pack_anagram: bool = False
    pct_anagram: int = 0
    anagram_lang: str = "russian"        # russian | english | romaji
    # Потолок длины названия под анаграмму (0 — без потолка): слишком длинное
    # название перемешивается в нечитаемую кашу.
    anagram_max_chars: int = _api.ANAGRAM_MAX_CHARS
    # Скорость показа всех текстовых вопросов, символов в секунду (0 — без
    # таймера). Старое имя сохраняет совместимость settings.json.
    anagram_cps: float = _api.ANAGRAM_CHARS_PER_SEC
    # Доля вопросов ПО СЮЖЕТУ (Fandom + Gemini) и что именно спрашивать.
    pack_plot: bool = False
    pct_plot: int = 0
    plot_mode: str = "title"             # title | detail
    pack_description_audio: bool = False
    pct_description_audio: int = 0
    description_language: str = "en"     # основной язык старых настроек
    description_languages: list[str] = _api.field(default_factory=list)
    description_voice_enabled: bool = True
    description_tts_first: str = "gemini"  # gemini | google | elevenlabs
    description_gemini_tts_model: str = "gemini-3.8-flash-lite-tts"
    elevenlabs_key: str = _api.field(default="", repr=False)
    elevenlabs_voice: str = "JBFqnCBsd6RMkjVDRZzb"
    google_tts_credentials: str = ""    # путь к service account JSON; пусто = ADC
    # Настоящие короткие диалоги из субтитров Jimaku. Gemini здесь только
    # переводчик: исходные реплики и номер серии приходят не от модели.
    pack_dialogue: bool = False
    pct_dialogue: int = 0
    jimaku_key: str = _api.field(default="", repr=False)
    subdl_key: str = _api.field(default="", repr=False)
    # Ключ и модель Gemini — нужны только вопросам по сюжету. Ключ всегда
    # пользовательский: зашивать общий в открытое GPL-приложение нельзя.
    gemini_key: str = ""
    gemini_model: str = ""
    gemini_image_model: str = ""
    gemini_image_thinking: str = "minimal"
    # Уровень «размышлений» модели — общий для любой выбранной модели Gemini.
    # Дороже уровень — медленнее ответ и быстрее кончается суточная квота, зато
    # аккуратнее загадки по названию и пересказы сюжета.
    gemini_thinking: str = GEMINI_THINKING_LEVEL
    # Своя модель и свой уровень рассуждения у ЗАГАДОК ПО НАЗВАНИЮ (синонимы,
    # антонимы, украинский, определения) — просьба пользователя. Работа там
    # совсем другая, чем у пересказа сюжета и перевода диалогов: сто названий
    # уходят одним запросом, и думать над ними стоит иначе. Пустое значение
    # означает «как у сюжета» — так открываются старые settings.json.
    gemini_title_model: str = ""
    gemini_title_thinking: str = ""
    gemini_daily_limits: dict = _api.field(default_factory=dict)
    pack_ai_art: bool = False
    pct_ai_art: int = 0
    cloudflare_account_id: str = ""
    cloudflare_token: str = _api.field(default="", repr=False)
    cloudflare_model: str = ART_DEFAULT_MODEL
    pack_pixiv_art: bool = False
    pct_pixiv_art: int = 0
    # Рамки сложности ОТДЕЛЬНО для артов (и нарисованных Pixiv, и сгенерённых).
    # Арт — это не кадр: по фанатскому рисунку тайтл узнают куда хуже, поэтому
    # для артов обычно берут аниме известнее, чем для остального пака.
    art_level_min: int = 1
    art_level_max: int = 15
    # Средняя сложность ВНУТРИ артовой рамки — та же мысль, что и level_avg, но
    # своим счётом (просьба пользователя). 0 — не следить: тогда арты держат
    # общую среднюю пака вместе со всеми остальными.
    art_level_avg: int = 0
    # Своя рамка у вопросов ПО СЮЖЕТУ (просьба пользователя). В режиме «ответ
    # — деталь сюжета» тайтл в вопросе назван прямо: играет не узнаваемость
    # названия, а то, помнят ли игроки сами события, — а помнят их только у
    # заметных тайтлов. 0 в средней — «не следить», как и у артов.
    plot_level_min: int = 1
    plot_level_max: int = 15
    plot_level_avg: int = 0
    # Своя рамка узнаваемости у ПЕСЕННЫХ вопросов и роликов (просьба
    # пользователя). Это НЕ сложность песни в AMQ (difficulty_min/max — та
    # другая величина, доля угадавших на сайте), а узнаваемость самого аниме
    # по той же шкале 1…15, что и общая «Сложность».
    # None означает «как общая рамка пака»: настройки, сохранённые до
    # появления этой рамки, работают ровно как работали.
    song_level_min: int | None = None
    song_level_max: int | None = None
    # Средняя узнаваемость песенной части, отдельным счётом. 0 — не следить.
    song_level_avg: int = 0
    pixiv_refresh_token: str = _api.field(default="", repr=False)
    pixiv_gemini_check: bool = True
    pixiv_gemini_model: str = ""
    pixiv_title_check_mode: str = "gemini"  # gemini | local
    # Что делать с R-18 и с работами нейросети: exclude | allow | only.
    # «Только их» — просьба пользователя собрать пак ровно из таких артов.
    # Пустая строка означает «как в старых настройках», то есть по галочкам
    # pixiv_exclude_* ниже; их же мы продолжаем писать в settings.json, чтобы
    # прежние сборки читали эти настройки как раньше.
    pixiv_r18_mode: str = ""
    pixiv_ai_mode: str = ""
    pixiv_exclude_r18: bool = True
    pixiv_exclude_ai: bool = True
    # Работы про однополые пары (BL/яой, GL/юри). Отдельным выбором и по
    # умолчанию выключено (просьба пользователя).
    pixiv_allow_same_sex: bool = False
    # Записи Pixiv с типом «манга» — это комиксы: кадры с репликами, а не
    # рисунок. По умолчанию не берутся, как и раньше, но галочка есть: в
    # верхушке тега таких работ треть (66 из 210 по замеру), и они сильно
    # сужают выбор.
    pixiv_allow_manga: bool = False
    # Планка лайков арта: работа с меньшим числом закладок в пул случайного
    # выбора не идёт. Закладка Pixiv — единственный счётчик одобрения в
    # открытом API, «лайков» отдельно там нет. Ноль снимает планку совсем.
    pixiv_min_likes: int = _api.PIXIV_MIN_LIKES
    # Списки меток-исключений, правленные пользователем (окно «Исключаемые
    # теги»): выключенные группы, снятые по одной метки и свои добавленные.
    # Пустые списки = всё как во встроенных списках (см. pixiv_art_tags).
    pixiv_groups_off: list[str] = _api.field(default_factory=list)
    pixiv_tags_off: list[str] = _api.field(default_factory=list)
    pixiv_tags_extra: list[str] = _api.field(default_factory=list)
    # Доля вопросов-САКУГА: вырезка анимации с Sakugabooru, без звука и титров.
    pack_sakuga: bool = False
    pct_sakuga: int = 0
    sakuga_cut: int = _api.SAKUGA_CUT
    # Совместимость старых настроек; фильтр по метке safe больше не применяется.
    sakuga_safe_only: bool = False
    # Пресет libsvtav1 ОТДЕЛЬНО для сакуги (просьба пользователя): у вопросов-
    # роликов своя скорость кодирования, а вырезки короткие, и на них не жалко
    # пресета помедленнее — или, наоборот, нужен самый быстрый, потому что их в
    # паке два десятка. 13 — самый быстрый.
    sakuga_preset: int = _api.VIDEO_PRESET
    # Доля вопросов-СТУДИЯ: кадры тайтла подряд, а называют студию.
    pack_studio: bool = False
    pct_studio: int = 0
    studio_frames: int = _api.STUDIO_FRAMES
    studio_seconds: int = _api.STUDIO_FRAME_SECONDS
    # Студии получают свою рамку узнаваемости: три кадра одной студии — не
    # обычный вопрос по тайтлу. None сохраняет поведение старых настроек и
    # означает «как общая сложность пака».
    studio_level_min: int | None = None
    studio_level_max: int | None = None
    studio_level_avg: int = 0
    # ── Обложки ──────────────────────────────────────────────────────────
    # Ключ themoviedb.org — ЗАПАСНОЙ источник постера: он идёт в дело только
    # там, где у карточки Shikimori постера нет вовсе или ссылка не открылась.
    # Ключ пользовательский по той же причине, что и у Gemini.
    tmdb_key: str = ""
    # Складывать скачанные обложки в общую папку и брать их оттуда в следующий
    # раз. Кладовая общая с «Апгрейдом аниме-пака» (см. poster_cache).
    poster_cache: bool = True
    # Кадры прошлых паков. Галочки на вкладке больше нет (просьба
    # пользователя): память о кадрах включается только правкой настроек.
    frames_no_repeat: bool = True
    char_roles: str = "both"             # main | supporting | both
    # Язык глав выбранных источников ("" — любой).
    manga_lang: str = ""
    manga_sources: dict = _api.field(default_factory=lambda: dict.fromkeys(
        ("mangadex", "mangafire", "comix", "weebcentral", "remanga", "mangalib"), True))
    # Stored in pack configuration for later calibration against real guesses.
    ru_popularity: dict = _api.field(default_factory=lambda: {
        "highest_weight": 0.3, "second_weight": 0.7})
    # Пускать ли главы с меткой erotica. По умолчанию нет, но без неё не
    # найдётся часть сэйнэн-классики: «Берсерк» на MangaDex помечен именно так.
    manga_allow_erotica: bool = False
    # Проверка страницы манги через Gemini: видно название — берётся другая
    # страница той же манги (как у артов Pixiv). Модель "" — как у сюжета.
    manga_gemini_check: bool = True
    # Выбор сцены применяется только к длинным вертикальным лентам вебтунов.
    manga_character_crop: bool = True
    manga_gemini_model: str = ""
    manga_title_check_mode: str = "gemini"  # gemini | local
    # Сколько процентов книжных вопросов должно достаться манге С АНИМЕ-
    # ЭКРАНИЗАЦИЕЙ. Такую книгу узнают по её сериалу, и вопрос выходит куда
    # легче неэкранизованной (просьба пользователя: доли задаются отдельно).
    manga_adapted_percent: int = 50  # -1 — любое соотношение экранизаций
    # Доли манхвы и маньхуа внутри книжной части, в процентах. Остальное —
    # японская манга. Без отдельной доли корейские и китайские
    # издания тонули: в каталоге Shikimori японской манги на порядок больше.
    manga_pct_manhwa: int = 0
    manga_pct_manhua: int = 0
    manga_strict_targets: bool = False
    manga_average_tolerance: float = 0.2
    manga_candidate_seconds: int = 180
    # Рамки сложности ОТДЕЛЬНО для книг. Индекс узнаваемости у манги считается
    # из тех же полей, что у аниме (кто читает, кто прочитал, кто бросил), но
    # читателей на порядок меньше зрителей — поэтому у книги и своя шкала
    # (MANGA_INDEX_LEVELS), и своя рамка. Манга с экранизацией меряется по
    # анимешной шкале: её индексом становится индекс самого аниме.
    manga_level_min: int = 1
    manga_level_max: int = 15
    # Средняя сложность книжной части, отдельным счётом (просьба пользователя).
    # Общая средняя книгам не годится по той же причине, что и общая рамка:
    # шкала у них своя. 0 — не следить.
    manga_level_avg: int = 0
    # Свои рамка и средняя у манхвы и маньхуа (поля манги выше — у японской
    # манги). Старые настройки их не знали: при загрузке они повторяют мангу.
    manhwa_level_min: int = 1
    manhwa_level_max: int = 15
    manhwa_level_avg: int = 0
    manhua_level_min: int = 1
    manhua_level_max: int = 15
    manhua_level_avg: int = 0
    # Типы изданий (kind у Manga): манга, манхва, манхуа, ранобэ и т.п.
    manga_kinds: dict = _api.field(
        default_factory=lambda: {k: k in ("manga", "manhwa", "manhua")
                                 for k in _api.MANGA_KINDS})
    # ── Видео ────────────────────────────────────────────────────────────
    song_video: bool = False
    # None preserves old presets: every eligible ordinary OP/ED gets video.
    song_video_percent: int | None = None
    preserve_composition: bool = True
    video_cut: int = _api.VIDEO_CUT
    video_crf: int = _api.VIDEO_CRF
    video_preset: int = _api.VIDEO_PRESET
    # Какие типы песен вообще брать. Снятая галочка = типа в паке нет, сколько
    # бы ни стояло в его счётчике.
    pick_openings: bool = True
    pick_endings: bool = True
    pick_inserts: bool = True
    openings: int = 54
    endings: int = 20
    inserts: int = 16
    difficulty_min: int = 0
    difficulty_max: int = 100
    # Отдельная рамка AMQ для OST. None = старая общая рамка OP/ED/OST.
    ost_difficulty_min: int | None = None
    ost_difficulty_max: int | None = None
    categories: dict = _api.field(default_factory=lambda: {c: True for c in _api.SONG_CATEGORIES})
    allow_rebroadcast: bool = True
    allow_dub: bool = False
    # ── Аниме ────────────────────────────────────────────────────────────
    # «Сложность пака» — 1…15 по узнаваемости тайтла (индексу популярности):
    # 1 — то, что знают все, 10 — то, что почти никто не смотрел. Работает в
    # любом режиме, в том числе когда песен нет вовсе (кадры).
    level_min: int = 1
    level_max: int = 15
    # Средняя узнаваемость пака: 0 — не следить, 1…15 — стараться держать
    # среднюю сложность около этого значения. Работает ВНУТРИ рамок level_min…
    # level_max: «от 1 до 15, в среднем 4» — это пак с редкими крайностями и
    # серединой около четвёрки (просьба пользователя).
    level_avg: int = 0
    # То же самое, но отдельно для вопросов-ПЕРСОНАЖЕЙ: их сложность считается
    # не только по узнаваемости тайтла, но и по тому, скольким людям персонаж
    # попал в избранное на Shikimori (см. char_question_level). 0 — не следить.
    char_level_avg: int = 0
    # Своя рамка сложности персонажей (просьба пользователя): узнаваемость
    # героя считается по избранному на Shikimori, и общая рамка пака ей не
    # указ. Проверяется после выбора персонажа — раньше его попросту нет.
    char_level_min: int = 1
    char_level_max: int = 15
    score_from: float = 0.0
    score_to: float = 10.0
    kinds: dict = _api.field(default_factory=lambda: {k: True for k in _api.ANIME_KINDS})
    year_from: int = 1944
    year_to: int = _api.field(default_factory=_api._current_year)
    genres_include: list[int] = _api.field(default_factory=list)
    genres_exclude: list[int] = _api.field(default_factory=list)
    genres_partial: bool = True          # достаточно одного из выбранных жанров
    # ── Прочее ───────────────────────────────────────────────────────────
    # Дубли выключены навсегда: галочек для них на вкладке больше нет (просьба
    # пользователя — «должны всегда быть выключены»). Поля оставлены, потому что
    # на них завязаны проверки отбора, но включить их неоткуда.
    dup_anime: bool = False              # несколько песен одного аниме
    dup_franchise: bool = False          # несколько аниме одной франшизы
    sort_by_index: bool = False          # порядок и цены — по индексу популярности
    images: bool = False                 # коллаж из скриншотов в вопросе
    images_time: int = 7                 # за сколько секунд до конца он появится
    # Сколько секунд висит постер в ОТВЕТЕ. 0 — без ограничения: картинка
    # остаётся на экране, пока ведущий не перейдёт дальше (просьба пользователя
    # — раньше три секунды были зашиты намертво). Потолок — ANSWER_IMAGE_MAX:
    # дольше пяти секунд разглядывать постер уже незачем, игра стоит.
    answer_image_time: int = 3
    hint: bool = True                    # подсказка «Опенинг/Эндинг/OST»
    # Общая база + списки людей разом: тайтлы берутся случайно, но если
    # выпавший тайтл есть у кого-то из добавленных списков, его ник пишется в
    # реплике ведущего (просьба пользователя). Проверяется В КОНЦЕ, когда
    # вопросы уже отобраны.
    mark_owners: bool = False
    # Паки, чьи ответы нельзя повторять: франшизы из них в новый пак не попадут.
    exclude_siq: list[str] = _api.field(default_factory=list)
    # Другой режим: исключаются сами вопросы/медиа, а не целые франшизы.
    exclude_exact_siq: list[str] = _api.field(default_factory=list)
    auto_add_to_exclusions: bool = True  # готовые паки в оба списка исключений
    compress_audio: bool = True          # opus 192 + нормализация вместо исходника
    compress_images: bool = True         # AVIF под лимит вместо исходной картинки
    image_limit_kb: int = _api.IMAGE_LIMIT_KB  # до скольки КБ ужимать картинку
    image_speed: int = _api.IMAGE_SPEED       # -cpu-used: 8 — самая быстрая
    shuffle_questions: bool = False      # вопросы в теме в разнобой, а не по цене
    audio_cut: int = 20                  # длина отрезка песни, сек
    parallel: int = 8                    # одновременных загрузок
    # Потолок веса готового .siq. Счётчика на вкладке больше нет (просьба
    # пользователя): бюджет держится по этому значению.
    max_pack_mb: int = _api.MAX_PACK_MB
    out_dir: str = ""                    # куда класть .siq (пусто — «Загрузки»)
    chiptune_enabled: bool = False
    chiptune_percent: int = 25           # доля аудиовопросов, не тип песни
    chiptune_seed: int = 0
    chiptune_version: str = "chiptune-2"
    chiptune_python: str = ""            # отдельное окружение Python 3.11
    chiptune_lead: str = "auto"
    chiptune_lead_volume: int = 85
    chiptune_bass_volume: int = 25
    # Каверы опенингов и эндингов: вместо оригинала играет чужое исполнение той
    # же композиции, найденное на YouTube и подтверждённое звуком (cover_*).
    cover_enabled: bool = False
    cover_percent: int = 25              # доля аудиовопросов, не тип песни
    # Сколько подтверждённых каверов набирать на песню, прежде чем выбирать.
    # Каждый лишний кандидат — это ~1.2 с загрузки и 1.3 с ЦПУ, а трёх хватает,
    # чтобы в следующих паках у песни звучал не один и тот же ролик.
    cover_pool: int = 3
    # Проверка композиции обязательна; галочка включает лишь рамку схожести
    # 0…100%. Имена cover_amq_* сохранены для настроек и публичного API.
    cover_similarity_enabled: bool = True
    cover_amq_from: int = 0
    cover_amq_to: int = 100
    # Планка качества исполнения: «мега плохих» каверов в паке быть не
    # должно (просьба пользователя). Ноль — не следить.
    cover_min_views: int = 1000
    cover_min_likes: int = 20
    # Разрешённые виды исполнения (TYPES из cover_meta_rules); пусто — любые.
    cover_types: list[str] = _api.field(default_factory=list)
    # Языки, на которых кавер перепет (LANGUAGE_KEYS из cover_meta_rules).
    # Пустой список — язык не отбирает вовсе; «allow» — пускать ТОЛЬКО
    # отмеченные, «exclude» — пускать всё, кроме отмеченных (просьба
    # пользователя). Записи, у которых язык в заголовке не назван, не трогает
    # ни один режим: «неизвестно» это не «другой язык».
    cover_langs: list[str] = _api.field(default_factory=list)
    cover_lang_mode: str = "allow"

    # Новые поля в конце сохраняют позиции аргументов публичного dataclass.
    pack_episode: bool = False
    pct_episode: int = 0
    episode_ru_subtitles: bool = False
    episode_subtitle_mode: str = ""  # Legacy checkbox: True -> required, False -> none.
    episode_scene_check: bool = True
    animelib_token: str = _api.field(default="", repr=False)
    karaoke_enabled: bool = False
    karaoke_translations: bool = False
    karaoke_percent: int = 25
    karaoke_ai_fallback: bool = True
    karaoke_python: str = ""
    karaoke_effect: str = "original"
    karaoke_tempo: float = 1.0
    karaoke_pitch: int = 0
    karaoke_crf: int = _api.VIDEO_CRF
    karaoke_preset: int = _api.VIDEO_PRESET
    karaoke_ai_timeout: int = 300
    karaoke_separator: str = "auto"

    # ── производные ──────────────────────────────────────────────────────
    @property
    def total_questions(self) -> int:
        return max(0, int(self.rounds)) * max(0, int(self.themes)) * max(0, int(self.questions))

    @property
    def picked_kinds(self) -> dict:
        """Какие типы песен разрешены галочками."""
        return {"opening": bool(self.pick_openings),
                "ending": bool(self.pick_endings),
                "insert": bool(self.pick_inserts)}

    @property
    def quotas(self) -> dict:
        picked = self.picked_kinds
        return {"opening": max(0, int(self.openings)) if picked["opening"] else 0,
                "ending": max(0, int(self.endings)) if picked["ending"] else 0,
                "insert": max(0, int(self.inserts)) if picked["insert"] else 0}

    @property
    def total_quota(self) -> int:
        return sum(self.quotas.values())

    @property
    def random_pool(self) -> bool:
        """Брать ли аниме из общей базы, а не из чьих-то списков.

        Отдельной галочки «Похожие» больше нет: сняты обе общие базы — значит
        пак собирается по спискам людей, это и есть единственное, что тогда
        остаётся. Сколько человек должны сойтись, задаёт similar_count."""
        return bool(self.random_mode)

    @property
    def mix_shares(self) -> dict:
        """Доли ВСЕХ родов вопросов, в сумме ровно 100: {ключ: проценты}.

    Ключи — «songs» (обычные песенные вопросы) и типы вопросов как они
    зовутся в квотах: VIDEO_KIND, FRAME_KIND, CHAR_KIND, MANGA_KIND,
    PIXEL_KIND, ANAGRAM_KIND, PLOT_KIND.

    Необязательные части считаются, только пока стоят их галочки («Вопрос —
    ролик», «— манга», «— пиксели», «— анаграмма», «— по сюжету»): снятая
    галочка убирает часть из ползунка целиком, а не оставляет молча
    работать сохранённый процент."""
        raw = {
            "songs": max(0, int(self.pct_songs)),
            _api.VIDEO_KIND: max(0, int(self.pct_videos)) if self.song_video else 0,
            _api.FRAME_KIND: max(0, int(self.pct_frames)),
            _api.CHAR_KIND: max(0, int(self.pct_chars)),
            _api.MANGA_KIND: max(0, int(self.pct_manga)) if self.pack_manga else 0,
            _api.PIXEL_KIND: max(0, int(self.pct_pixel)) if self.pack_pixel else 0,
            _api.ANAGRAM_KIND: (max(0, int(self.pct_anagram))
                           if self.pack_anagram else 0),
            _api.PLOT_KIND: max(0, int(self.pct_plot)) if self.pack_plot else 0,
            _api.DESCRIPTION_AUDIO_KIND: (max(0, int(self.pct_description_audio))
                                          if self.pack_description_audio else 0),
            _api.DIALOGUE_KIND: (max(0, int(self.pct_dialogue))
                                 if self.pack_dialogue else 0),
            _api.AI_ART_KIND: max(0, int(self.pct_ai_art)) if self.pack_ai_art else 0,
            _api.PIXIV_ART_KIND: (max(0, int(self.pct_pixiv_art))
                                  if self.pack_pixiv_art else 0),
            _api.SAKUGA_KIND: (max(0, int(self.pct_sakuga))
                               if self.pack_sakuga else 0),
            _api.EPISODE_KIND: (max(0, int(self.pct_episode))
                                if self.pack_episode else 0),
            _api.STUDIO_KIND: (max(0, int(self.pct_studio))
                               if self.pack_studio else 0),
        }
        for key in _api.TITLE_KINDS:
            raw[key] = max(0, int(getattr(self, "pct_" + key))) if getattr(self, "pack_" + key) else 0
        if self.pack_titles is not None:
            from .title_mix import KINDS
            for key in KINDS:
                raw[key] = 0
            raw["titles"] = max(0, self.pct_titles) if self.pack_titles else 0
        keys = list(raw)
        total = sum(raw.values())
        if total <= 0:
            return {k: (100 if k == "songs" and self.composition_enabled is None else 0) for k in keys}
        out = {k: v * 100 // total for k, v in raw.items()}
        rest = 100 - sum(out.values())
        for key in sorted(keys, key=lambda k: -(raw[k] * 100 % total)):
            if rest <= 0:
                break
            out[key] += 1
            rest -= 1
        if "titles" in out:
            from .title_mix import weights as title_weights
            title_total = out.pop("titles")
            inner = title_weights(self)
            denominator = sum(inner.values())
            # Keep small internal shares alive; round actual question counts later.
            out.update({k: title_total * value / denominator if denominator else 0
                        for k, value in inner.items()})
        return out

    # Порядок родов вопросов в «исторической» пятёрке percents.
    _LEGACY_MIX_ORDER = ("songs", _api.VIDEO_KIND, _api.FRAME_KIND, _api.CHAR_KIND, _api.MANGA_KIND)

    @property
    def percents(self) -> tuple[int, int, int, int, int]:
        """Доли (песни, ролики, кадры, персонажи, манга) — первые пять частей.

    Это срез mix_shares, а не отдельный расчёт: сумма его пяти чисел равна
    сотне только пока нет пикселей, анаграмм и вопросов по сюжету — они
    забирают свою долю из той же сотни. Полный состав — в mix_shares."""
        shares = self.mix_shares
        return tuple(shares.get(k, 0) for k in self._LEGACY_MIX_ORDER)

    @property
    def songs_percent(self) -> int:
        """Доля вопросов, которым нужна песня из AnisongDB: и обычных, и
    роликов (ролик — это та же песня, только видео)."""
        shares = self.mix_shares
        return shares.get("songs", 0) + shares.get(_api.VIDEO_KIND, 0)

    @property
    def manga_percent(self) -> int:
        """Доля вопросов по манге/манхве/ранобэ."""
        return self.mix_shares.get(_api.MANGA_KIND, 0)

    @property
    def silent_kinds(self) -> list[str]:
        """Роды вопросов без песни, у которых есть доля, — в порядке SILENT_KINDS."""
        shares = self.mix_shares
        return [k for k in _api.SILENT_KINDS if shares.get(k, 0)]

    @property
    def only_kind(self) -> _api.Optional[str]:
        """Режим «весь пак одним родом вопросов без песни» — кадры, персонажи,
    манга, пиксели, анаграммы или сюжет."""
        if self.songs_percent:
            return None
        picked = self.silent_kinds
        return picked[0] if len(picked) == 1 else None

    @property
    def mixed(self) -> bool:
        """Смешанный пак: больше одного рода вопросов сразу."""
        return sum(1 for p in self.mix_shares.values() if p) > 1

    @property
    def has_songs(self) -> bool:
        """Будут ли в паке вопросы, которым нужна песня (обычные или ролики).

    От этого зависит выбор общей базы: мастер-лист AMQ знает только тайтлы
    с песнями, поэтому пакам из кадров и персонажей он не годится вовсе —
    база для них всегда берётся с Shikimori."""
        return bool(self.songs_percent and any(self.picked_kinds.values()))

    @property
    def question_quotas(self) -> dict:
        """Сколько вопросов какого типа нужно набрать.

    Доли задаёт ползунок (проценты песен/роликов/кадров/персонажей), а
    заданные пользователем опенинги/эндинги/OST ужимаются пропорционально —
    их сумма становится ровно числом обычных песенных вопросов (ролики
    считаются отдельной квотой)."""
        total = self.total_questions
        shares = self.mix_shares
        songs_ok = bool(self.has_songs)
        # Вопросы без песни в словаре первыми: при делении поровну (9 вопросов
        # на две равные доли) лишний вопрос по стабильной сортировке достаётся
        # тому, кто раньше, — пусть это будут кадры, а не песня.
        weights = {k: shares.get(k, 0) for k in _api.SILENT_KINDS}
        weights[_api.VIDEO_KIND] = shares.get(_api.VIDEO_KIND, 0) if songs_ok else 0
        weights["songs"] = shares.get("songs", 0) if songs_ok else 0
        if self.pack_titles is not None:
            from .title_mix import KINDS
            weights["titles"] = round(sum(weights.pop(k, 0) for k in KINDS), 8)
        if sum(weights.values()) <= 0:
            if self.composition_enabled is not None and not any(shares.values()):
                return {k: 0 for k in _api.SONG_KINDS + (_api.VIDEO_KIND,) + _api.SILENT_KINDS}
            weights = {k: 0 for k in weights}
            weights["songs"] = 1
        counts = _api._split_total(total, weights)
        if "titles" in counts:
            from .title_mix import split, weights as title_weights
            counts.update(split(counts.pop("titles"), title_weights(self)))
        quotas = _api._scale_quotas(self.quotas, counts["songs"])
        for kind in _api.SILENT_KINDS + (_api.VIDEO_KIND,):
            quotas[kind] = counts.get(kind, 0)
        return quotas

    # ── рамки узнаваемости по родам вопросов ─────────────────────────────

    @property
    def level_bounds(self) -> dict:
        """{род вопроса: (мин, макс)} — рамки сложности по родам вопросов.

    У книг и артов рамка своя (просьба пользователя), у всего остального —
    общая «Сложность пака». Ключ None — та самая общая рамка."""
        general = (int(self.level_min), int(self.level_max))
        from .manga_editions import span
        manga = span(self)
        art = (int(self.art_level_min), int(self.art_level_max))
        plot = (int(self.plot_level_min), int(self.plot_level_max))
        out = {None: general, _api.MANGA_KIND: manga, _api.PLOT_KIND: plot}
        out[_api.STUDIO_KIND] = self.studio_level_range
        # Уровень персонажа равен уровню его тайтла, то есть известен ещё ДО
        # выбора героя. Своя рамка персонажей поэтому проверяется тут же, при
        # выборе рода вопроса: раньше тайтл 9-го уровня при рамке 3…8 доезжал до
        # запроса персонажей и только там отбрасывался (жалоба пользователя).
        out[_api.CHAR_KIND] = self.char_level_range
        out.update({k: art for k in (_api.AI_ART_KIND, _api.PIXIV_ART_KIND)})
        out.update({k: self.song_level_range
                    for k in _api.SONG_KINDS + (_api.VIDEO_KIND,)})
        return out

    @property
    def song_level_range(self) -> tuple:
        """Рамка узнаваемости песенных вопросов; None в полях — как у пака."""
        low = self.level_min if self.song_level_min is None else self.song_level_min
        high = self.level_max if self.song_level_max is None else self.song_level_max
        return (int(low), int(high))

    @property
    def char_level_range(self) -> tuple:
        """Рамка сложности вопросов-персонажей (своя, «Персонажи» на вкладке)."""
        low = int(getattr(self, "char_level_min", 1) or 1)
        high = int(getattr(self, "char_level_max", _api.MAX_LEVEL)
                   or _api.MAX_LEVEL)
        return (low, max(low, high))

    @property
    def studio_level_range(self) -> tuple:
        """Рамка узнаваемости студий; None в полях — как у всего пака."""
        low = (self.level_min if self.studio_level_min is None
               else self.studio_level_min)
        high = (self.level_max if self.studio_level_max is None
                else self.studio_level_max)
        return (int(low), int(high))

    def level_range(self, kind=None) -> tuple:
        """Рамка сложности для этого рода вопросов."""
        return self.level_bounds.get(kind) or self.level_bounds[None]

    @property
    def level_span(self) -> tuple:
        """Самая широкая рамка среди ЗАДЕЙСТВОВАННЫХ родов вопросов.

    По ней отбираются кандидаты из каталога: род вопроса выбирается позже,
    и заранее неизвестно, станет тайтл кадром (общая рамка) или артом
    (своя). Точную рамку своего рода вопрос проходит уже в _pick_kind."""
        shares = self.mix_shares
        bounds = self.level_bounds
        arts = (_api.AI_ART_KIND, _api.PIXIV_ART_KIND)
        own = arts + (_api.PLOT_KIND, _api.STUDIO_KIND, _api.CHAR_KIND)
        used = [bounds[k] for k in own if shares.get(k)]
        # Песни и ролики — та же история, что и арты: у них своя рамка.
        if shares.get("songs") or shares.get(_api.VIDEO_KIND):
            used.append(self.song_level_range)
        # Общая рамка нужна, только пока в паке есть хоть что-то, кроме родов
        # со своей рамкой и книг: у пака из одних артов их рамка и есть
        # единственная, а лишняя ширина жгла бы кандидатов впустую.
        skip = set(own) | {"songs", _api.VIDEO_KIND, _api.MANGA_KIND}
        if any(v for k, v in shares.items() if k not in skip) or not used:
            used.append(bounds[None])
        return (min(b[0] for b in used), max(b[1] for b in used))

    def validate(self) -> list[str]:
        """Список проблем, из-за которых генерацию запускать бессмысленно."""
        problems: list[str] = []
        if self.episode_subtitle_mode and self.episode_subtitle_mode not in ("none", "required", "preferred"):
            problems.append("Неизвестный режим субтитров отрывков серий.")
        if (self.mix_shares.get(_api.EPISODE_KIND) and self.episode_scene_check
                and not str(self.gemini_key or "").strip()):
            problems.append("Для проверки сцен серий укажите ключ Gemini или выключите проверку сцен.")
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
            if not 0 <= float(self.manga_average_tolerance) <= 1:
                problems.append("Допуск средней сложности комиксов должен быть от 0 до 1.")
            if not 30 <= int(self.manga_candidate_seconds) <= 1800:
                problems.append("Время подготовки комикса должно быть от 30 до 1800 секунд.")
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
        from .frame_visual_check import enabled as frame_check_enabled
        if (self.mix_shares.get(_api.STUDIO_KIND)
                and not str(self.gemini_key or "").strip()):
            problems.append("Для студий нужен ключ Gemini: берутся только проверенные "
                            "кадры с персонажами. Введите ключ в настройках API.")
        if (any(self.mix_shares.get(kind) and frame_check_enabled(self, kind)
                for kind in _api.FRAME_KINDS)
                and not str(self.gemini_key or "").strip()):
            problems.append("Для проверки кадров нужен ключ Gemini. Введите ключ "
                            "или отключите проверку кадров через Gemini.")
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
            from .manga_editions import validate_levels
            problems.extend(validate_levels(self))
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

    # ── сохранение в settings.json ───────────────────────────────────────

    def to_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items()
             if k not in ("users", "saved_users")}
        d["users"] = [u.to_dict() for u in self.users]
        d["saved_users"] = [u.to_dict() for u in self.saved_users]
        d["manga_kinds"] = {k: bool(self.manga_kinds.get(k)) for k in _api.MANGA_KINDS}
        return d

    # Как старые галочки состава превращаются в проценты ползунка. Ключи —
    # то, что могло лежать в settings.json до появления ползунка.
    _LEGACY_MIX = ("frames_only", "chars_only", "mix_frames", "mix_chars",
                   "mix_frames_per", "mix_chars_per")

    @staticmethod
    def _percents_from_legacy(d: dict) -> _api.Optional[tuple[int, int, int]]:
        """Проценты состава по старым настройкам («только кадры», «ещё и кадры
    по N на песню»). None — старых настроек в файле нет."""
        if not any(k in d for k in _api.PackSettings._LEGACY_MIX):
            return None
        if d.get("frames_only"):
            return (0, 100, 0)
        if d.get("chars_only"):
            return (0, 0, 100)
        per_f = max(1, int(d.get("mix_frames_per") or 2)) if d.get("mix_frames") else 0
        per_c = max(1, int(d.get("mix_chars_per") or 1)) if d.get("mix_chars") else 0
        if not per_f and not per_c:
            return (100, 0, 0)
        weight = 1 + per_f + per_c
        songs = int(round(100.0 / weight))
        frames = int(round(100.0 * per_f / weight))
        return (songs, frames, max(0, 100 - songs - frames))

    @classmethod
    def from_dict(cls, d: dict) -> '_api.PackSettings':
        s = cls()
        if not isinstance(d, dict):
            return s
        legacy = cls._percents_from_legacy(d)
        if legacy is not None and "pct_songs" not in d:
            s.pct_songs, s.pct_frames, s.pct_chars = legacy
        for key, value in d.items():
            if value is None:
                continue
            if key in ("users", "saved_users"):
                setattr(s, key, [_api.UserList.from_dict(u) for u in (value or [])
                                 if isinstance(u, dict)])
            elif key in ("composition_enabled", "title_enabled"):
                # Список включённых родов вопросов. Читается ОТДЕЛЬНО, потому что
                # по умолчанию здесь None: общая ветка ниже пыталась бы сделать
                # NoneType(список), молча падала — и сохранённый состав не
                # применялся вовсе. Пустой список сняли ВСЁ, и это не то же самое,
                # что «настройки без состава»: иначе после перезапуска сами собой
                # включались «Песни».
                setattr(s, key, [str(k) for k in (value or []) if k])
            elif key == "pack_titles":
                s.pack_titles = bool(value)
            elif key == "exclude_siq":
                s.exclude_siq = [str(p) for p in (value or []) if p]
            elif key == "description_languages":
                s.description_languages = [str(code) for code in (value or [])]
            elif key == "frame_effects":
                s.frame_effects = clean_effects(value)
                # Удалённые жалюзи не должны оставлять старый случайный
                # режим без единого эффекта. Явно пустой выбор сохраняем.
                if not s.frame_effects and isinstance(value, (list, tuple)) and "blinds" in value:
                    s.frame_effects = ["window"]
                # Так же и с убранными набросками, размытием, оттенками и
                # помехами: выбор из одних только них — это все оставшиеся.
                elif (not s.frame_effects and isinstance(value, (list, tuple))
                      and any(k in REMOVED_EFFECTS for k in value)):
                    s.frame_effects = list(EFFECT_LABELS)
                # Новые эффекты сразу попадают в сохранённый случайный набор
                # (просьба пользователя); снятые вручную позже не вернутся.
                # Явно пустой выбор остаётся пустым.
                if s.frame_effects:
                    s.frame_effects = add_new_effects(
                        s.frame_effects, d.get("frame_effects_known"))
            elif key == "frame_effects_known":
                continue
            elif key in ("entrance_effects", "entrance_targets"):
                labels = ENTRANCE_EFFECT_LABELS if key == "entrance_effects" else TARGET_LABELS
                setattr(s, key, clean_keys(value, labels))
                if (key == "entrance_effects" and not s.entrance_effects
                        and isinstance(value, (list, tuple))
                        and any(isinstance(k, str) and k in EDITOR_ONLY_EFFECTS for k in value)):
                    s.entrance_effects = list(ENTRANCE_EFFECT_LABELS)
            elif key == "entrance_effect" and isinstance(value, str) and value in EDITOR_ONLY_EFFECTS:
                s.entrance_effect = "random"
            elif key == "frame_effect" and value == "blinds":
                s.frame_effect = "window"
            elif key == "frame_effect" and value in REMOVED_EFFECTS:
                s.frame_effect = "pixelize"
            elif key == "manga_sources":
                from si_hyx_parts.animepack_api.manga_reader_base import clean_sources
                s.manga_sources = clean_sources(value)
            elif key in ("categories", "kinds", "manga_kinds"):
                if isinstance(value, dict):
                    getattr(s, key).update({k: bool(v) for k, v in value.items()})
            elif key in ("dup_anime", "dup_franchise"):
                # Дубли аниме и франшиз выключены навсегда (просьба
                # пользователя): сохранённое «включено» из старых настроек
                # молча игнорируем, галочек для них больше нет.
                continue
            elif key in ("genres_include", "genres_exclude"):
                out = []
                for g in (value or []):
                    try:
                        out.append(int(g))
                    except (TypeError, ValueError):
                        continue
                setattr(s, key, out)
            elif key in ("song_video_percent", "ost_difficulty_min", "ost_difficulty_max",
                         "song_level_min", "song_level_max",
                         "studio_level_min", "studio_level_max"):
                try:
                    setattr(s, key, int(value))
                except (TypeError, ValueError):
                    pass
            elif hasattr(s, key):
                try:
                    setattr(s, key, type(getattr(s, key))(value))
                except (TypeError, ValueError):
                    pass
        if s.chiptune_version == "chiptune-1":
            s.chiptune_version = "chiptune-2"
        # Старые кадры с эффектами брали общий пресет роликов. Сохраняем его
        # при миграции; после сохранения новая настройка независима.
        if "frame_preset" not in d:
            s.frame_preset = s.video_preset
        if "karaoke_crf" not in d:
            s.karaoke_crf = s.video_crf
        if "karaoke_preset" not in d:
            s.karaoke_preset = s.video_preset
        if s.song_video and "pct_videos" not in d:
            # До ползунка галочка «Вопрос — ролик» превращала в ролики ВСЕ
            # песенные вопросы разом — читаем её как «доля роликов = вся доля
            # песен», иначе сохранённая галочка молча перестала бы работать.
            s.pct_videos, s.pct_songs = int(s.pct_songs), 0
        if "pack_manga" not in d and int(s.pct_manga or 0) > 0:
            # Галочки манги раньше не было, а доля была: включаем её, иначе
            # сохранённая доля манги молча пропала бы из ползунка.
            s.pack_manga = True
        # Потолок появился позже самой настройки — подрезаем и сохранённое.
        s.answer_image_time = max(0, min(_api.ANSWER_IMAGE_MAX,
                                         int(s.answer_image_time or 0)))
        # Потолок длины названия под анаграмму: 0 — снят совсем, иначе не короче
        # самой короткой анаграммы, какая вообще бывает (иначе не прошло бы ни
        # одно название и род вопросов молча вымер бы).
        limit = max(0, int(s.anagram_max_chars or 0))
        s.anagram_max_chars = limit and max(_api.ANAGRAM_MIN_LETTERS, limit)
        # Скорость показа текстовых вопросов: 0 — таймера нет, иначе от единицы до
        # потолка (быстрее шестидесяти символов в секунду текст не прочитать).
        try:
            cps = max(0.0, float(s.anagram_cps or 0.0))
        except (TypeError, ValueError):
            cps = _api.ANAGRAM_CHARS_PER_SEC
        s.anagram_cps = cps and min(_api.ANAGRAM_CPS_MAX, max(1.0, cps))
        # FLUX.1 удалён из выбора. Старые settings.json должны молча
        # переехать на нынешнюю модель, а не ломать валидацию.
        if "flux-1-schnell" in str(s.cloudflare_model or "").lower():
            s.cloudflare_model = ART_DEFAULT_MODEL
        if s.description_gemini_tts_model == "gemini-2.5-pro-preview-tts":
            # Удалённую платную модель в старых настройках заменяем доступной.
            s.description_gemini_tts_model = cls().description_gemini_tts_model
        # Вид кавера «Живьём» убран: концертные записи не берутся вовсе. Оставить
        # его в списке значило бы отбирать по виду, которого больше не бывает, —
        # песни молча остались бы без каверов.
        s.cover_types = [k for k in (s.cover_types or ()) if k in COVER_TYPE_LABELS]
        # Язык кавера: незнакомые ключи молча выбрасываем, режим — только один из
        # двух. Пустой список сам по себе значит «язык не отбирает», поэтому
        # проверять режим отдельно не приходится.
        s.cover_langs = [k for k in (s.cover_langs or ()) if k in COVER_LANGUAGE_KEYS]
        if str(s.cover_lang_mode or "") not in ("allow", "exclude"):
            s.cover_lang_mode = "allow"
        from .manga_editions import migrate, migrate_levels
        migrate(s, d)
        migrate_levels(s, d)
        try:
            s.karaoke_ai_timeout = max(60, min(3600, int(s.karaoke_ai_timeout)))
        except (TypeError, ValueError):
            s.karaoke_ai_timeout = cls().karaoke_ai_timeout
        if s.karaoke_separator not in ("auto", "kim", "htdemucs"):
            s.karaoke_separator = "auto"
        return s


PackSettings.__module__ = _api.__name__
_api.PackSettings = PackSettings
