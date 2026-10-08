# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""SongCandidate. Public namespace: animepack."""
from __future__ import annotations
import animepack as _api
from si_hyx_parts.animepack.plot_explanation import candidate_titles, without_titles


def _expanded_plot_answer(keyword: str, explanation: str) -> str:
    """Первый ответ объясняет факт и явно называет то, что засчитывается."""
    keyword = str(keyword or "").strip()
    explanation = str(explanation or "").strip()
    if not explanation:
        return keyword
    exact = (keyword and _api.re.search(
        rf"(?<!\w){_api.re.escape(keyword)}(?!\w)", explanation,
        _api.re.IGNORECASE))
    if keyword and not exact:
        return f"{keyword} — {explanation}"
    return explanation


def _placement_title(card: dict, song: dict) -> str:
    title = str(card.get("russian") or card.get("name") or "").strip()
    try:
        year = int((card.get("airedOn") or {}).get("year") or 0)
    except (TypeError, ValueError):
        year = 0
    if year:
        title = _api.re.sub(rf"\s*\(\s*{year}\s*\)\s*$", "", title)
    tag = _api.song_tag(song.get("songType"))
    if tag:
        title += f" {tag}"
    if year:
        title += f" ({year})"
    return title.strip()


@_api.dataclass
class SongCandidate:
    """Песня, прошедшая все фильтры, вместе с карточкой аниме."""
    song: dict
    anime: dict
    users: list[str] = _api.field(default_factory=list)
    kind: str = "opening"
    trim_start: int = 0
    has_poster: bool = False
    has_collage: bool = False
    has_frame: bool = False
    # Ролик опенинга/эндинга с AnimeThemes вместо отрезка звука.
    has_video: bool = False
    video_url: str = ""
    # Персонаж вопроса «угадай персонажа»: {"name", "poster", "main"}.
    character: dict = _api.field(default_factory=dict)
    # Сколько человек добавили этого персонажа в избранное на Shikimori.
    # −1 — не спрашивали или не узнали; ноль — спросили, и он ни у кого.
    char_favorites: int = -1
    # Кандидата отвергли по сложности уже во время загрузки (средняя сложность
    # персонажей). Не то же самое, что упавшая загрузка: в счётчик «не
    # скачалось» такие не идут.
    rejected: bool = False
    # Из какого каталога карточка: "anime" или "manga" (манга, манхва, ранобэ).
    # У манги нет ни песен, ни кадров — вопросом служит персонаж или обложка.
    media: str = "anime"
    price: int = 0                   # проставляется assign_prices()
    selection_level: int | None = None
    compress_audio: bool = True      # копия одноимённых настроек пака
    compress_images: bool = True
    # Реальные имена картинок проставляет загрузчик: без сжатия расширение
    # берётся от исходника (.jpg/.png/.webp), со сжатием это всегда .avif.
    poster_name: str = ""
    frame_name: str = ""
    collage_name: str = ""
    # Ссылка на скриншот, ставший вопросом-кадром: по ней ведётся память о том,
    # какие кадры уже показывались в прошлых паках.
    frame_url: str = ""
    # None — не проверяли; только подтверждённое False даёт надбавку +2.
    frame_has_characters: bool | None = None
    # Реально выбранный эффект (в том числе при случайном выборе).
    frame_effect: str = ""
    # Исходные медиа сохраняются для памяти повторов и чистого кадра после появления.
    entrance_effect: str = ""
    entrance_frames: dict[str, str] = _api.field(default_factory=dict)
    entrance_durations: dict[str, float] = _api.field(default_factory=dict)
    entrance_video: str = ""
    # Адрес самой работы на Pixiv. Уходит последним вариантом ответа (просьба
    # пользователя): ведущему видно, что именно показано и чей это рисунок.
    art_link: str = ""
    # Перемешанные буквы названия — сам вопрос-анаграмма (см. make_anagram).
    anagram: str = ""
    # Вопрос по сюжету: текст вопроса от модели и, в режиме «деталь сюжета»,
    # варианты правильного ответа. Пустой список — отвечают названием тайтла.
    plot_question: str = ""
    plot_answers: list[str] = _api.field(default_factory=list)
    # Одно предложение с объяснением; в ответе стоит перед ссылкой на Fandom.
    plot_explanation: str = ""
    # Откуда взят пересказ: вики и страница целиком — для журнала.
    plot_source: str = ""
    # Одна лишь страница серии («Episode 12», «Тайна деревни»). Уходит в ответ
    # устной репликой: по какой серии был вопрос (просьба пользователя).
    plot_episode: str = ""
    # Настоящие реплики из Jimaku: оригинал хранится для проверки, а игрокам
    # показывается только структурно проверенный перевод Gemini.
    dialogue_text: str = ""
    dialogue_source_text: str = ""
    dialogue_episode: int = 0
    # Индекс самой популярной части франшизы: сиквел спрашивается так же, как
    # оригинал, поэтому и узнаваемость у него оригинала (0.0 — не считали).
    franchise_index: float = 0.0

    # Имя медиафайлов внутри пака. Пустое — считается по media_key (так работают
    # тесты и старые паки); генератор проставляет сюда «Сгенерировано в
    # SI-HYX(Название тайтла)», чтобы файлы в архиве читались глазами.
    media_base: str = ""
    # Append fields to preserve the positional constructor of existing callers.
    # Вырезка анимации с Sakugabooru: {"id", "url", "ext", "source"}.
    sakuga: dict = _api.field(default_factory=dict)
    music_effect: str = "original"
    music_slot: int = -1
    music_processing: dict = _api.field(default_factory=dict)
    # Почему способ подачи сломался ЦЕЛИКОМ, а не на этой песне: нет yt-dlp,
    # YouTube просит подтвердить, что ты не робот. Пустое — обычная неудача
    # («у этой песни нет подтверждённого исполнения»), её перебирают дальше.
    music_failure: str = ""
    # Карточка АНИМЕ-ЭКРАНИЗАЦИИ этой манги (пусто — экранизации нет). Такую
    # мангу узнают ровно настолько, насколько знают её аниме, поэтому и индекс,
    # и шкала сложности у неё берутся от экранизации, а цена получается на два
    # очка дороже вопроса-кадра по тому же аниме (просьба пользователя).
    adapted_from: dict = _api.field(default_factory=dict)
    # Названия ОСТАЛЬНЫХ песен этого же аниме. Приезжают тем же ответом
    # AnisongDB и ничего не стоят, а поиску каверов закрывают самую неприятную
    # коллизию: кавер другого OP/ED того же тайтла и медли из двух его песен
    # (см. cover_meta.song_ref).
    siblings: list[str] = _api.field(default_factory=list)
    # Та же песня и тот же исполнитель у других, НЕ родственных аниме.
    # В ответе показываются максимум три тайтла вместе с их постерами.
    song_alternates: list[dict] = _api.field(default_factory=list)
    # Откуда взят сам вопрос: страница главы на MangaDex, страница вики с
    # пересказом, пост на Sakugabooru. Уходит ПОСЛЕДНЕЙ
    # строкой ответа (просьба пользователя): ведущему и редактору пака видно,
    # что именно показано, а назвать такой ответ никто не назовёт. Арт Pixiv
    # живёт в своём поле (art_link) — оно появилось раньше и уже в паках.
    source_link: str = ""
    author_name: str = ""
    # Сколько человек добавили ТАЙТЛ в избранное на Shikimori (−1 — не
    # спрашивали). Вторая мера узнаваемости рядом со списками: «Ван-Пис» и
    # «Детектива Конана» смотрели немногие, а знают их все, и отличается такой
    # тайтл именно долей избранного (см. index_favorites_factor). Число живёт
    # только на странице тайтла, поэтому спрашивается не при отборе, а у
    # кандидата, дошедшего до загрузки (_title_favorites).
    favorites: int = -1
    # Из чего сложилась цена — строками, для подсказки на ячейке «Цена».
    # Заполняет assign_prices (см. price_parts.py).
    price_parts: list[str] = _api.field(default_factory=list)
    # Студии, рисовавшие тайтл, — ответ вопроса-студии (см. studio_question.py).
    studios: list[str] = _api.field(default_factory=list)
    # Три разные франшизы этой студии в порядке кадров. Из их
    # же постеров собирается горизонтальный ответ.
    studio_cards: list[dict] = _api.field(default_factory=list)
    # Уровни узнаваемости этих трёх тайтлов — из них считается цена вопроса.
    studio_levels: list[int] = _api.field(default_factory=list)
    # ОСТАЛЬНЫЕ кадры вопроса-студии: первый лежит в frame_name, как у обычного
    # вопроса-кадра, — так его видят и память повторов, и подсчёт размера.
    extra_frames: list[str] = _api.field(default_factory=list)
    extra_frame_urls: list[str] = _api.field(default_factory=list)
    description_audio_ext: str = ""     # mp3 (Eleven/Chirp) или wav (Gemini TTS)
    description_language: str = ""
    description_text: str = ""
    popular_franchise_title: str = ""
    ru_popularity: dict = _api.field(default_factory=dict)
    episode_clip: dict = _api.field(default_factory=dict)
    karaoke: dict = _api.field(default_factory=dict)
    theme_video_ready: bool = False  # AnimeThemes, до эффектов появления

    @property
    def base_kind(self) -> str:
        """Тип песни, лежащей в основе вопроса.

        У вопроса-ролика это опенинг или эндинг: сам ролик — только форма
        подачи. Подсказка и ответ берутся от песни, цена — как у кадра."""
        if self.kind == _api.VIDEO_KIND:
            return _api.song_kind(self.song.get("songType")) or "opening"
        return self.kind

    @property
    def is_video(self) -> bool:
        """Прежний вопрос-ролик или песня с готовым видео AnimeThemes."""
        return self.kind == _api.VIDEO_KIND or self.theme_video_ready

    @property
    def is_frame(self) -> bool:
        """Вопрос-кадр — картинкой или роликом-проявлением (песни в нём нет,
        даже если карточка песни осталась от отбора)."""
        return self.kind in _api.FRAME_KINDS

    @property
    def is_pixel(self) -> bool:
        """Кадр с любым эффектом раскрытия; имя сохраняет прежний API."""
        return self.kind == _api.PIXEL_KIND

    @property
    def is_sakuga(self) -> bool:
        """Вопрос-вырезка анимации: внутри это ролик без звука."""
        return self.kind == _api.SAKUGA_KIND

    @property
    def is_episode(self) -> bool:
        return self.kind == _api.EPISODE_KIND

    @property
    def is_studio(self) -> bool:
        """Вопрос-студия: несколько кадров подряд, а называют студию."""
        return self.kind == _api.STUDIO_KIND

    @property
    def question_frames(self) -> list[str]:
        """Картинки вопроса по порядку. У всех, кроме студии, она одна."""
        if not self.has_frame:
            return []
        return [self.frame_file] + [name for name in self.extra_frames if name]

    @property
    def studio_name(self) -> str:
        """Главная студия тайтла — она и есть правильный ответ («» — нет)."""
        return next((str(name).strip() for name in self.studios
                     if str(name or "").strip()), "")

    @property
    def is_text(self) -> bool:
        """Вопрос из одного текста — анаграмма или сюжет."""
        return self.kind in _api.TEXT_KINDS

    @property
    def question_text(self) -> str:
        if self.kind == _api.DESCRIPTION_AUDIO_KIND:
            return self.description_text
        if self.kind == _api.ANAGRAM_KIND:
            return self.anagram
        if self.kind == _api.DIALOGUE_KIND:
            return self.dialogue_text
        return self.plot_question

    @property
    def is_silent(self) -> bool:
        """Вопросу не нужна песня вовсе: картинка, ролик-проявление или текст."""
        return self.kind in _api.SILENT_KINDS

    @property
    def is_manga(self) -> bool:
        """Карточка из каталога манги/манхвы/ранобэ, а не аниме."""
        return self.media == "manga"

    @property
    def is_character(self) -> bool:
        """Вопрос «угадай персонажа»: показывается портрет, а не кадр.

        Вопрос по манге тоже считается таким, если персонаж для него выбран
        (настройка «Вопрос по манге: портрет персонажа») — ответ, цена и
        варианты у них общие. С обложкой персонажа нет, и вопрос остаётся
        обычным «угадай произведение по картинке»."""
        return self.kind == _api.CHAR_KIND or (self.kind == _api.MANGA_KIND
                                          and bool(self.character))

    @property
    def is_picture(self) -> bool:
        """Вопросом служит КАРТИНКА тайтла — кадр, пиксели, персонаж, обложка.

        Не то же самое, что is_silent: анаграмме и сюжету картинка не нужна
        вовсе, а этим — нужна, и без неё вопроса не будет."""
        return self.kind in _api.IMAGE_KINDS

    @property
    def char_name(self) -> str:
        return str((self.character or {}).get("name") or "").strip()

    @property
    def char_names(self) -> list[str]:
        """ВСЕ имена персонажа: русское, ромадзи и «Прочие» с его страницы на
        Shikimori (поле synonyms). Именно их и засчитываем в ответе — угадывают
        персонажа, и звать его игрок может как угодно."""
        char = self.character or {}
        names = [char.get("name"), char.get("russian"), char.get("romaji")]
        names += list(char.get("names") or [])
        # Сырые «Прочие» Shikimori бывают одной строкой через запятую («Al,
        # Armored Alchemist») — разбиваем (обычно это уже сделал animepack_api).
        for syn in (char.get("synonyms") or []):
            names += str(syn or "").split(",")
        out, seen = [], set()
        for name in names:
            text = str(name or "").strip()
            if text and text.casefold() not in seen:
                seen.add(text.casefold())
                out.append(text)
        return out

    @property
    def audio_file(self) -> str:
        return str(self.song.get("audio") or "")

    @property
    def ann_id(self) -> int:
        try:
            return int(self.song.get("annId") or 0)
        except (TypeError, ValueError):
            return 0

    @property
    def mal_id(self) -> int:
        try:
            return int(self.anime.get("malId") or 0)
        except (TypeError, ValueError):
            return 0

    @property
    def media_key(self) -> str:
        """Основа имён медиафайлов. Берём annSongId, а не annId: при разрешённых
        дублях аниме два вопроса одного тайтла иначе делили бы один файл. В
        режиме кадров песни нет вовсе — тогда ключом служит MAL id."""
        sid = (self.song.get("annSongId") or self.song.get("amqSongId")
               or self.ann_id or self.mal_id)
        return str(sid)

    @property
    def cover_link(self) -> str:
        """Адрес ролика, из которого взят кавер («» — кавера в вопросе нет).

        Уходит ОТДЕЛЬНОЙ последней строкой ответа (просьба пользователя): в
        вопросе звучит чужое исполнение, и по одному названию канала найти
        его потом нельзя. Назвать такой ответ никто не назовёт — строка нужна
        ведущему и редактору пака."""
        if self.music_effect != "cover":
            return ""
        return str((self.music_processing or {}).get("url") or "")

    @property
    def file_base(self) -> str:
        """Основа имени файлов вопроса внутри пака. Генератор кладёт сюда
        «Сгенерировано в SI-HYX(Название тайтла)»; пустое — старое поведение с
        числовым ключом."""
        return self.media_base or self.media_key

    @property
    def audio_out(self) -> str:
        """Имя дорожки ВНУТРИ пака. Со сжатием это opus, без — тот же файл, что
        приехал с CDN (mp3), просто обрезанный."""
        if self.kind == _api.DESCRIPTION_AUDIO_KIND:
            return f"{self.file_base}_description.{self.description_audio_ext or 'mp3'}"
        if self.music_effect == "chiptune":
            return f"{self.file_base}_chiptune" + (".mp3" if self.compress_audio else ".wav")
        if self.music_effect == "cover":
            # Кавер приезжает не с CDN, а с YouTube, поэтому «без сжатия»
            # копировать тут нечего: без сжатия пишем mp3 192, как chiptune.
            return f"{self.file_base}_cover" + (".opus" if self.compress_audio
                                                else ".mp3")
        if self.compress_audio:
            return f"{self.file_base}.opus"
        ext = _api.os.path.splitext(self.audio_file)[1] or ".mp3"
        return f"{self.file_base}{ext}"

    @property
    def video_out(self) -> str:
        """Имя ролика внутри пака. mp4, как и у «Обработки»: AV1 в mp4 —
        то, что она сама выдаёт на выходе."""
        suffix = "_karaoke" if self.music_effect == "karaoke" else ""
        return f"{self.file_base}{suffix}.mp4"

    @property
    def image_ext(self) -> str:
        return ".avif" if self.compress_images else ".jpg"

    @property
    def poster_file(self) -> str:
        return self.poster_name or f"{self.file_base}_poster{self.image_ext}"

    @property
    def collage_file(self) -> str:
        return self.collage_name or f"{self.file_base}{self.image_ext}"

    @property
    def frame_file(self) -> str:
        """Картинка-вопрос: кадр из аниме либо портрет персонажа."""
        return self.frame_name or f"{self.file_base}_frame{self.image_ext}"

    @property
    def difficulty(self) -> float:
        try:
            return float(self.song.get("songDifficulty") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    @property
    def title_ru(self) -> str:
        return (self.anime.get("russian") or self.anime.get("name")
                or self.song.get("animeENName") or "")

    @property
    def year(self) -> int:
        try:
            return int((self.anime.get("airedOn") or {}).get("year") or 0)
        except (TypeError, ValueError):
            return 0

    @property
    def song_name(self) -> str:
        """Название песни — у вопроса без песни его нет, даже если карточка
        песни осталась от отбора (в смешанном режиме кандидат приходит с
        песней, а вопросом становится кадр или анаграмма)."""
        if self.is_silent:
            return ""
        return str(self.song.get("songName") or "").strip()

    @property
    def artist(self) -> str:
        if self.is_silent:
            return ""
        return str(self.song.get("songArtist") or "").strip()

    @property
    def score(self) -> float:
        try:
            return float(self.anime.get("score") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    @property
    def released_year(self) -> int:
        """Год, когда тайтл ЗАКОНЧИЛСЯ (0 — неизвестно или ещё выходит).

        В карточках из старой базы поля нет вовсе — тогда и ноль: свежесть
        посчитается по одному году начала, ровно как раньше."""
        try:
            return int((self.anime.get("releasedOn") or {}).get("year") or 0)
        except (TypeError, ValueError):
            return 0

    @property
    def ongoing(self) -> bool:
        """Выходит ли тайтл прямо сейчас (Shikimori: status = ongoing)."""
        return str(self.anime.get("status") or "").strip().lower() == "ongoing"

    @property
    def own_index(self) -> float:
        """«Индекс популярности» самого тайтла — та же величина, по которой
        сортирует ShikimoriHYX: взвешенные по статусам списки, приглушённые
        возрастом тайтла и слегка — его оценкой.

        Возраст считается по обоим краям выпуска: «Ван-Пис» идёт с 1999 года и
        не кончился, и штраф за старость ему полагается мягче, чем ровеснику,
        закончившемуся тогда же (см. shikimori_api.effective_age)."""
        base = _api.index_base_from_statuses_stats(self.anime.get("statusesStats"))
        return _api.popularity_index(base, self.year or None, self.score,
                                     manga=self.is_manga,
                                     until=self.released_year or None,
                                     ongoing=self.ongoing)

    @property
    def own_base(self) -> float:
        """База индекса тайтла — взвешенные по статусам списки, без множителей."""
        return _api.index_base_from_statuses_stats(self.anime.get("statusesStats"))

    @property
    def favorites_factor(self) -> float:
        """Поправка индекса за «в избранном»: сколько избранных у тайтла
        против соседей по индексу (см. favorites_norm).

        Работает только в плюс, поэтому её не страшно накладывать и на индекс
        франшизы: сиквел, которого в избранном мало, остаётся ровно на
        узнаваемости своей серии."""
        return _api.title_favorites_factor(self.own_index, self.own_base,
                                           self.favorites,
                                           manga=self.is_manga)

    @property
    def book_index(self) -> float:
        """Узнаваемость книги в КНИЖНЫХ единицах (у аниме — ноль).

        Отдельно от index, потому что складывать её с анимешными числами
        нельзя: это разные линейки. На общую шкалу её переводит manga_reach."""
        if not self.is_manga:
            return 0.0
        return self.own_index * self.favorites_factor

    @property
    def screen_index(self) -> float:
        """Узнаваемость АНИМЕ рядом с вопросом (0 — аниме нет).

        У книги сюда попадает её экранизация (apply_adaptation) либо просто
        аниме той же франшизы: и то и другое значит «этот тайтл видели, а не
        только читали». У аниме это узнаваемость его серии; короткому
        ответвлению (фильм, спешл, OVA) она засчитывается не целиком —
        см. franchise_part_weight."""
        franchise = float(self.franchise_index or 0.0)
        if not self.is_manga:
            from .franchise_part_weight import inherited_index
            franchise = inherited_index(self.anime, self.own_index, franchise)
        return franchise * self.favorites_factor

    @property
    def effective_book_index(self) -> float:
        """Positive-only RU correction; original book_index remains public."""
        from .ru_popularity_math import number
        equivalent = number(self.ru_popularity.get("ru_equivalent_book_index"))
        return max(self.book_index, equivalent or 0.0) if self.is_manga else 0.0

    @property
    def index(self) -> float:
        """Узнаваемость вопроса на ОДНОЙ, анимешной шкале.

        У сиквела она равна узнаваемости франшизы — «Доктор Стоун: Научное
        будущее. Часть 3» знают ровно настолько же, насколько «Доктора
        Стоуна», хотя своих зрителей у части мало. Сверху — поправка за «в
        избранном» (просьба пользователя).

        У книги своё число (book_index) поднимается на общую шкалу через
        manga_reach — с потолком: книгу, которую не экранизировали, знают
        только читавшие, и выше MANGA_TOP_INDEX ей не подняться. Рядом стоит
        узнаваемость её аниме, и побеждает БОЛЬШЕЕ из двух: книгу узнают либо
        по сериалу, либо по тому, что её читали."""
        key = self._index_key()
        memo = self.__dict__.get("_index_memo")
        if memo is not None and memo[0] == key:
            return memo[1]
        value = self._compute_index()
        self.__dict__["_index_memo"] = (key, value)
        return value

    def _compute_index(self) -> float:
        """index за один проход — та же формула, что у own_index,
        favorites_factor, effective_book_index и screen_index, но own_index и
        поправка за избранное считаются по разу, а не по пять раз."""
        manga = self.is_manga
        base = _api.index_base_from_statuses_stats(self.anime.get("statusesStats"))
        own_index = _api.popularity_index(base, self.year or None, self.score,
                                          manga=manga,
                                          until=self.released_year or None,
                                          ongoing=self.ongoing)
        factor = _api.title_favorites_factor(own_index, base, self.favorites,
                                             manga=manga)
        franchise = float(self.franchise_index or 0.0)
        if manga:
            from .ru_popularity_math import number
            equivalent = number(self.ru_popularity.get("ru_equivalent_book_index"))
            own = _api.manga_reach(max(own_index * factor, equivalent or 0.0))
        else:
            from .franchise_part_weight import inherited_index
            franchise = inherited_index(self.anime, own_index, franchise)
            own = own_index * factor
        return max(own, franchise * factor)

    def _index_key(self) -> tuple:
        """Все входы формулы index — значения, а не ссылки.

        Отбор спрашивает уровень одних и тех же вопросов сотни тысяч раз
        (средняя, рамки, резерв), а полный расчёт стоит ~0,2 мс. Правка
        карточки на месте меняет ключ, и index считается заново. Новый вход
        формулы обязательно добавлять сюда."""
        anime = self.anime or {}
        stats = anime.get("statusesStats")
        ru = (self.ru_popularity or {}).get("ru_equivalent_book_index") if self.is_manga else None
        return (self.media, self.favorites, self.franchise_index,
                tuple((s.get("status"), s.get("count"))
                      for s in (stats or ()) if isinstance(s, dict)),
                self.year, self.released_year, anime.get("score"), anime.get("status"),
                anime.get("kind"), anime.get("episodes"), ru,
                _api.favorites_norms_version(), _api.date.today())

    @property
    def price_index(self) -> float:
        """Общий индекс узнаваемости (старое публичное имя сохранено).

        Раньше цена зависела от места этого индекса среди вопросов пака.
        Теперь она фиксирована уровнем 1…15, но таблицы и сторонний код всё
        ещё читают price_index для сортировки, поэтому свойство остаётся."""
        return self.index

    @property
    def level(self) -> int:
        """Сложность ТАЙТЛА 1…15 (1 — узнают все, 15 — не узнает никто).

        Считается по index, то есть по одной лесенке на весь пак. Книге это
        даёт ровно то, что нужно: без аниме она упирается в MANGA_MIN_LEVEL
        (её знают только читавшие), а с аниме получает уровень своего
        сериала — «Восхождение героя щита» узнают по нему, а не по томику."""
        return _api.index_level(self.index)

    @property
    def char_level(self) -> int:
        """Сложность вопроса-персонажа 1…15.

        Ровно совпадает со сложностью тайтла; популярность самого героя её не
        сдвигает."""
        return _api.char_question_level(self.level, self.char_favorites)

    @property
    def tag(self) -> str:
        """«OP1», «ED2», «OST» — что именно за песня. У вопроса без песни
        (картинка, анаграмма, сюжет) тега нет."""
        if self.is_silent:
            return ""
        return _api.song_tag(self.song.get("songType"))

    # ── правильный ответ ─────────────────────────────────────────────────
    @property
    def title_with_year(self) -> str:
        """«Название (год)» с тегом песни, если он есть."""
        title = self.title_ru.strip()
        year = self.year
        # У части тайтлов Shikimori сам держит год в названии («Могучий Атом
        # (2003)») — второй раз его дописывать не надо, а тег песни встаёт
        # перед годом («Могучий Атом OP1 (2003)»).
        if year:
            title = _api.re.sub(rf"\s*\(\s*{year}\s*\)\s*$", "", title)
        tag = self.tag
        if tag:
            title = f"{title} {tag}"
        if year:
            title = f"{title} ({year})".strip()
        return title

    @property
    def main_answer(self) -> str:
        """«Русское название OP1 (год) — 『Песня』». У вопроса-персонажа на месте
    песни стоит имя персонажа: «Название (2020) — 『Имя』». Без того и
    другого остаётся просто название с годом — так и просили."""
        title = self.title_with_year
        if self.is_studio and self.studio_name:
            # Три кадра уже из трёх разных франшиз, поэтому единственный
            # общий и правильный ответ — сама студия, без названия тайтла.
            return self.studio_name
        if self.is_character and self.char_name:
            return f"{title} — 『{self.char_name}』"
        if self.song_name:
            if self.song_alternates:
                placements = [(self.anime, self.song)] + [
                    (row.get("anime") or {}, row.get("song") or {})
                    for row in self.song_alternates]
                title = " / ".join(_placement_title(card, song)
                                   for card, song in placements)
            return f"{title} — 『{self.song_name}』"
        return title

    def answer_variants(self) -> list[str]:
        """Все засчитываемые варианты ответа: основной, голое русское название и
    остальные имена тайтла с Shikimori (ромадзи, английское, «лицензировано
    в РФ под названием», синонимы). Дубли схлопываются без учёта регистра —
    SIGame сверяет ответы построчно.

    Порядок: сперва основной ответ, потом ИНЫЕ названия (ромадзи,
    английское, лицензионное, синонимы), а голое русское название — в самом
    конце: сразу после основного оно смотрится копией («Повар-боец Сома
    (2014), Повар-боец Сома…»).

    Отдельные иероглифические варианты не берём: ведущему их не прочитать, а
    игроку не набрать. Но основной русский ответ сохраняется целиком, даже
    когда внутри него японскими символами написано настоящее название песни.
    """
        if self.plot_answers:
            # Вопрос по сюжету с ответом-ДЕТАЛЬЮ: тайтл в таком вопросе назван
            # прямо, а угадывают саму деталь — её написания и засчитываем.
            # Страница вики, с которой взят пересказ, идёт последней строкой:
            # ведущему видно, откуда вопрос, и спорный ответ можно свериться.
            short = self.plot_answers[0]
            expanded = without_titles(
                _expanded_plot_answer(short, self.plot_explanation),
                candidate_titles(self))
            return _api._dedup_answers([expanded] + list(self.plot_answers)
                                       + [self.source_link])
        if self.kind == _api.PLOT_KIND:
            variants = ([without_titles(self.plot_explanation, candidate_titles(self))]
                        if self.plot_explanation else []) + [self.main_answer]
        else:
            variants = [self.main_answer]
        if self.is_studio:
            # Засчитывается имя ЛЮБОЙ из студий тайтла: у совместных работ их
            # две-три, и «Студия Пьеро» там не вернее «A-1 Pictures». Названия
            # аниме среди вариантов нет вовсе — вопрос не о нём.
            variants.extend(self.studios)
            return _api._dedup_answers(variants)
        if self.is_character:
            # В вопросе-персонаже угадывают ПЕРСОНАЖА, а не тайтл: голое
            # название аниме верным ответом быть не должно, иначе вопрос
            # решается с одного взгляда на постер.
            #
            # Название произведения пишется РОВНО ОДИН РАЗ — в основном ответе,
            # а доп-варианты состоят из одних только других имён персонажа
            # (просьба пользователя). Раньше каждое имя дублировалось ещё и в
            # паре с названием, и список ответов выглядел как десять почти
            # одинаковых строк.
            variants.extend(self.char_names)
            if self.cover_link:
                variants.append(self.cover_link)
            if self.source_link:
                variants.append(self.source_link)
            return _api._dedup_answers(variants)
        variants.append(self.anime.get("name"))            # ромадзи
        variants.append(self.anime.get("english"))
        for syn in (self.anime.get("synonyms") or []):
            variants.append(syn)
        variants.append(self.anime.get("licenseNameRu"))   # «Лицензировано в РФ»
        if not self.is_character and not self.is_studio:
            variants.append(self.popular_franchise_title)
        for row in self.song_alternates:
            card = row.get("anime") or {}
            variants.extend([card.get("russian"), card.get("name"),
                             card.get("english"), card.get("licenseNameRu")])
            variants.extend(card.get("synonyms") or [])
        if self.adapted_from:
            # У вопроса по манге с экранизацией засчитываются и ВСЕ русские
            # названия самого аниме. Shikimori нередко держит привычный перевод
            # лишь в synonyms (например «Перерождение сильнейшего экзорциста в
            # другом мире»), поэтому одного поля russian недостаточно.
            variants.append(self.adapted_from.get("russian"))
            variants.append(self.adapted_from.get("licenseNameRu"))
            variants.extend(
                syn for syn in (self.adapted_from.get("synonyms") or [])
                if _api.re.search(r"[А-Яа-яЁё]", str(syn or "")))
        variants.append(self.title_ru)                     # то же, но без года
        if self.art_link:
            # Адрес арта на Pixiv — последней строкой (просьба пользователя):
            # назвать его никто не назовёт, зато в редакторе и у ведущего
            # сразу видно, откуда взята картинка.
            variants.append(self.art_link)
        if self.cover_link:
            # То же самое для кавера: последней строкой — адрес ролика, из
            # которого взято исполнение (просьба пользователя).
            variants.append(self.cover_link)
        if self.source_link:
            # И для остальных вопросов «откуда картинка»: глава на MangaDex,
            # пост на Sakugabooru, страница вики с
            # пересказом (просьба пользователя).
            variants.append(self.source_link)
        return _api._dedup_answers(variants)


SongCandidate.__module__ = _api.__name__
_api.SongCandidate = SongCandidate
