# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""SongCandidate. Public namespace: animepack."""
from __future__ import annotations
import animepack as _api


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
    # Реально выбранный эффект (в том числе при случайном выборе).
    frame_effect: str = ""
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

    @property
    def base_kind(self) -> str:
        """Тип песни, лежащей в основе вопроса.

        У вопроса-ролика это опенинг или эндинг: сам ролик — только форма
        подачи, а подсказка, надбавка к цене и ответ берутся от песни, как у
        обычного песенного вопроса."""
        if self.kind == _api.VIDEO_KIND:
            return _api.song_kind(self.song.get("songType")) or "opening"
        return self.kind

    @property
    def is_video(self) -> bool:
        """Вопрос-ролик (ролика могло и не найтись — тогда играет звук)."""
        return self.kind == _api.VIDEO_KIND

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
        return f"{self.file_base}.mp4"

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
        только читали». У аниме это узнаваемость его серии."""
        return float(self.franchise_index or 0.0) * self.favorites_factor

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
        own = (_api.manga_reach(self.book_index) if self.is_manga
               else self.own_index * self.favorites_factor)
        return max(own, self.screen_index)

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

    # ── правильный ответ ───────────────────────────────────────
    from si_hyx_parts.animepack.song_answer import (
        title_with_year,
        main_answer,
        answer_variants,
    )

SongCandidate.__module__ = _api.__name__
_api.SongCandidate = SongCandidate
