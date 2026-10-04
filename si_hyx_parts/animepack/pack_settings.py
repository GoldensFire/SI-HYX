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
    # Брать только вырезки с меткой «safe». Снятая галочка пускает и
    # «questionable» — там сплошь драки и кровь, но не порно.
    sakuga_safe_only: bool = True
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
    # Типы изданий (kind у Manga): манга, манхва, манхуа, ранобэ и т.п.
    manga_kinds: dict = _api.field(
        default_factory=lambda: {k: k in ("manga", "manhwa", "manhua")
                                 for k in _api.MANGA_KINDS})
    # ── Видео ────────────────────────────────────────────────────────────
    song_video: bool = False             # включает долю роликов в ползунке
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

    from si_hyx_parts.animepack.pack_settings_mix import (
        mix_shares, _LEGACY_MIX_ORDER, percents, songs_percent,
        manga_percent, silent_kinds, only_kind, mixed, has_songs,
        question_quotas,
    )

    # ── рамки узнаваемости по родам вопросов ─────────────────────────────
    from si_hyx_parts.animepack.pack_settings_levels import (
        level_bounds,
        song_level_range,
        studio_level_range,
        char_level_range,
        level_range,
        level_span,
    )

    from si_hyx_parts.animepack.pack_settings_validate import validate

    # ── сохранение в settings.json ───────────────────────────────────────
    from si_hyx_parts.animepack.pack_settings_io import (
        _LEGACY_MIX,
        to_dict,
        _percents_from_legacy,
        from_dict,
    )


PackSettings.__module__ = _api.__name__
_api.PackSettings = PackSettings
