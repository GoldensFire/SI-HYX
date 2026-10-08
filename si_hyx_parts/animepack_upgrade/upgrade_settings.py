# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Настройки апгрейда, ошибка, шаги битрейта/высоты и фильтры звука. Public namespace: animepack_upgrade."""
from __future__ import annotations
import animepack_upgrade as _api


class UpgradeError(Exception):
    """Ошибка апгрейда, которую не стыдно показать пользователю."""

UpgradeError.__module__ = _api.__name__
_api.UpgradeError = UpgradeError

def nearest_bitrate(kbps) -> int:
    """Ближайший битрейт из списка «Обработки». Настройки приезжают из
    settings.json, где могло оказаться что угодно, а на форме битрейт выбирают
    из списка — значения не из него выпадающий список показать не сможет."""
    try:
        want = int(float(kbps))
    except (TypeError, ValueError):
        return _api.AUDIO_KBPS
    return min(_api.AUDIO_BITRATES, key=lambda k: (abs(k - want), k))

nearest_bitrate.__module__ = _api.__name__
_api.nearest_bitrate = nearest_bitrate

def nearest_height(height) -> int:
    """Ближайшая высота из списка (0 — «не менять»). Как и с битрейтом:
    в settings.json могло оказаться что угодно, а на форме высоту выбирают из
    выпадающего списка."""
    try:
        want = int(float(height))
    except (TypeError, ValueError):
        return 0
    return min(_api.VIDEO_HEIGHTS, key=lambda h: (abs(h - want), h))

nearest_height.__module__ = _api.__name__
_api.nearest_height = nearest_height

def loudnorm_filter(s: '_api.UpgradeSettings') -> str:
    """Фильтр нормализации громкости («» — выключена).

    Ровно та же строка, что собирает «Обработка»
    (workers.ProcessWorker._build_audio_filters) и генератор паков
    (animepack.audio_filters): один и тот же loudnorm с теми же тремя числами —
    целевой громкостью, разбросом и потолком пиков."""
    if not getattr(s, "audio_norm", False):
        return ""
    return (f"loudnorm=I={float(s.audio_norm_i):g}"
            f":LRA={float(s.audio_norm_lra):g}"
            f":TP={float(s.audio_norm_tp):g}")

loudnorm_filter.__module__ = _api.__name__
_api.loudnorm_filter = loudnorm_filter

def audio_filter_chain(s: '_api.UpgradeSettings') -> str:
    """Готовая строка `-af` для перекода звука: нормализация (если включена) и
    ВСЕГДА фикс раскладки каналов под libopus.

    Фикс обязателен и сам по себе: libopus отвергает «боковые» раскладки
    (5.1(side) у AC3-дорожек) с «Invalid channel layout», а на stereo и mono он
    ничего не делает (то же правило, что в workers._af_arg)."""
    norm = _api.loudnorm_filter(s)
    return f"{norm},{_api.OPUS_LAYOUT_FIX}" if norm else _api.OPUS_LAYOUT_FIX

audio_filter_chain.__module__ = _api.__name__
_api.audio_filter_chain = audio_filter_chain

# ─────────────────────────────────────────────────────────────────────────────
# Настройки
# ─────────────────────────────────────────────────────────────────────────────
@_api.dataclass
class UpgradeSettings:
    """Что делать с паком. Все функции независимы и выключаются по одной."""
    # ── Профиль ───────────────────────────────────────────────────────────
    # Единственное значение — «anime» (тайтлы ищутся на Shikimori). Поле
    # оставлено ради settings.json старых версий (см. normalize_profile).
    profile: str = _api.PROFILE_ANIME

    # ── Функция 1: спецвопросы → обычные ─────────────────────────────────
    strip_specials: bool = True
    # «С секретом без вопроса» (secretNoQuestion) — это выдача денег без вопроса
    # как такового: самого вопроса в нём нет. Обычным его не сделать, поэтому по
    # умолчанию такие пропускаются (о каждом пишется в отчёт).
    strip_no_question: bool = False

    # ── Функция 2: варианты названий с Shikimori ─────────────────────────
    add_titles: bool = True
    # Только точное совпадение названия — опечатка в букву-другую сюда входит
    # (см. is_typo). Выключено — засчитывается и просто близкое название, но
    # тогда чужой ответ может утащить за собой варианты постороннего тайтла.
    strict_match: bool = True
    # Какие именно названия дописывать, выбора нет: дописываются ВСЕ (ромадзи,
    # английское, лицензионное, синонимы, русское) — по просьбе пользователя
    # галочки убраны, и в паке всегда лежит полный список.
    #
    # Переписать название так, как оно написано на Shikimori («наруто» →
    # «Наруто»). Только при точном совпадении и только если разница в регистре:
    # менять сам текст ответа иначе — это уже другой ответ.
    fix_case: bool = True
    # Поставить в ответ постер тайтла (как это делает генератор паков). Тоже
    # только при точном совпадении: чужой постер в ответе хуже, чем никакого.
    add_poster: bool = True
    # Переспрашивать базу персонажей, когда ответ похож на имя героя, а не на
    # название (латиница в одно-три слова). Совпало точно — вопрос не трогаем
    # вовсе: спрашивали персонажа, а не аниме.
    check_characters: bool = True
    # Тема про мангу («Manga (для читающих)», «Ранобэ») — искать книгу, а не
    # аниме: обложка аниме в таком вопросе неверна, а у части ответов аниме нет
    # вовсе («Soul Cartel», «Noblesse» — манхва). Книга не нашлась — названия
    # всё равно доищутся по аниме, но обложка из него уже не берётся.
    book_themes: bool = True
    # Искать тайтл и по ОСТАЛЬНЫМ вариантам ответа, а не только по первому.
    # В живых паках первый ответ сплошь и рядом записан как «Название - Песня»,
    # а голое название лежит второй строкой (проверено на паке пользователя:
    # без этого не опознавался каждый третий ответ).
    use_other_answers: bool = True
    max_variants: int = 8                # сколько строк дописывать в один ответ
    # Ответы короче этого не ищем вовсе: «Да», «1945» и прочее к аниме
    # отношения не имеют, а запрос на каждый такой ответ — это секунды.
    min_query_len: int = 3

    # ── Функция 3: пережать тяжёлые картинки ─────────────────────────────
    compress_images: bool = True
    image_min_mb: float = _api.IMAGE_MIN_MB   # тяжелее этого — пережимаем
    image_limit_kb: int = _api.IMAGE_TO_KB    # до скольки килобайт ужимать
    image_speed: int = _api.IMAGE_SPEED       # -cpu-used: 8 — самая быстрая

    # ── Функция 4: повторяющийся текст темы ──────────────────────────────
    strip_repeated_text: bool = True
    # Длиннее этого текст не убираем, даже если он стоит во всех вопросах темы:
    # короткая подпись — это указание («Назвать аниме»), а длинный текст скорее
    # сам вопрос, и удалять его вслепую нельзя.
    repeat_text_max_len: int = _api.REPEAT_TEXT_MAX_LEN
    # Убирать известные подписи (KNOWN_LABELS) и там, где в одном вопросе темы
    # их нет: правило «в КАЖДОМ вопросе» на живых паках спотыкается — хватает
    # одного вопроса-исключения, чтобы подпись осталась во всех остальных.
    strip_known_labels: bool = True
    # Текстовый блок, за которым СРАЗУ идёт звук, играть одновременно с ним
    # (waitForFinish="False", в v4 — time="-1"; SIQuester зовёт это «Объединить
    # со следующим (играть одновременно)»). Иначе игра сначала выдерживает текст
    # на экране, и только потом включает отрывок — а текст там как раз подпись к
    # нему («Назвать аниме по опенингу»).
    merge_text_audio: bool = True

    # ── Функция 5: пустые вопросы ────────────────────────────────────────
    # Вопрос без содержимого (ни текста, ни картинки, ни звука, ни ролика)
    # выкидывается из пака целиком. Ответ не в счёт: играть всё равно нечем.
    drop_empty_questions: bool = True

    # ── Функция 6: тяжёлое аудио → opus ──────────────────────────────────
    compress_audio: bool = True
    audio_min_mb: float = _api.AUDIO_MIN_MB   # тяжелее этого — перекодируем
    audio_kbps: int = _api.AUDIO_KBPS         # в скольки килобитах
    # Нормализация громкости — та же, что во вкладке «Обработка». Выключена по
    # умолчанию: в чужом паке громкость уже выставил автор. Включённая, она
    # снимает обе оговорки «не трогаю»: дорожка перекодируется, даже если и так
    # не богаче целевого битрейта и даже если легче не станет, — иначе
    # нормализовать было бы нечего, ради чего галочку и включают.
    audio_norm: bool = False
    audio_norm_i: float = _api.AUDIO_NORM_I
    audio_norm_lra: float = _api.AUDIO_NORM_LRA
    audio_norm_tp: float = _api.AUDIO_NORM_TP

    # ── Функция 7: тяжёлое видео → AV1 ───────────────────────────────────
    # Выключено по умолчанию НАРОЧНО, в отличие от остальных: перекод ролика
    # идёт минутами, а с галочкой «кодек не AV1» под него попадает вообще всё
    # видео пака — включать такое молча за пользователя нельзя.
    compress_video: bool = False
    video_min_mb: float = _api.VIDEO_MIN_MB   # тяжелее этого — перекодируем
    # Перекодировать и лёгкие ролики, если они не в AV1: mp4 с H.264 из чужого
    # пака в AV1 худеет вдвое-втрое даже без ужимания разрешения.
    video_non_av1: bool = True
    video_crf: int = _api.VIDEO_CRF           # 0–63, больше — легче и хуже
    video_preset: int = _api.VIDEO_PRESET     # 0–13, больше — быстрее и хуже
    video_height: int = 0                # 0 — не менять разрешение

    # ── Функция 8: неиспользуемые файлы ──────────────────────────────────
    # Медиа, на которое в content.xml нет ни одной ссылки, в новый пак не
    # переносится. В живых паках такого добра хватает: автор поменял картинку,
    # а старая осталась лежать в архиве и весить.
    drop_unused: bool = True

    # ── Прочее ───────────────────────────────────────────────────────────
    out_dir: str = ""                    # пусто — рядом с исходным паком

    def to_dict(self) -> dict:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, d: dict) -> '_api.UpgradeSettings':
        s = cls()
        if not isinstance(d, dict):
            return s
        for key, value in d.items():
            if value is None or not hasattr(s, key):
                continue
            try:
                setattr(s, key, type(getattr(s, key))(value))
            except (TypeError, ValueError):
                pass
        s.max_variants = max(1, min(50, int(s.max_variants)))
        s.min_query_len = max(1, min(20, int(s.min_query_len)))
        s.image_min_mb = max(0.1, min(100.0, float(s.image_min_mb)))
        s.image_limit_kb = max(50, min(20000, int(s.image_limit_kb)))
        s.image_speed = max(0, min(8, int(s.image_speed)))
        s.repeat_text_max_len = max(1, min(500, int(s.repeat_text_max_len)))
        s.audio_min_mb = max(0.1, min(500.0, float(s.audio_min_mb)))
        s.audio_kbps = _api.nearest_bitrate(s.audio_kbps)
        s.audio_norm_i = max(-60.0, min(20.0, float(s.audio_norm_i)))
        s.audio_norm_lra = max(0.0, min(50.0, float(s.audio_norm_lra)))
        s.audio_norm_tp = max(-60.0, min(10.0, float(s.audio_norm_tp)))
        s.video_min_mb = max(0.1, min(2000.0, float(s.video_min_mb)))
        s.video_crf = max(0, min(63, int(s.video_crf)))
        s.video_preset = max(0, min(13, int(s.video_preset)))
        s.video_height = _api.nearest_height(s.video_height)
        s.profile = _api.normalize_profile(s.profile)
        return s

    @property
    def source_name(self) -> str:
        """Как зовут базу названий («Shikimori»)."""
        return _api.PROFILE_SOURCES.get(_api.normalize_profile(self.profile), "Shikimori")

    def validate(self) -> list[str]:
        problems: list[str] = []
        if not (self.strip_specials or self.add_titles or self.compress_images
                or self.strip_repeated_text or self.drop_empty_questions
                or self.compress_audio or self.compress_video
                or self.drop_unused or self.merge_text_audio):
            problems.append("Все функции выключены — паку нечего менять. "
                            "Включите «Убрать спецвопросы», «Дописать варианты "
                            "названий», «Сжать тяжёлые картинки», «Убрать "
                            "повторяющийся текст», «Текст под звук», «Удалить "
                            "пустые вопросы», «Сжать тяжёлое аудио», «Сжать "
                            "тяжёлое видео» или «Удалить неиспользуемые "
                            "файлы».")
        if self.compress_images and self.image_limit_kb >= self.image_min_mb * 1024:
            problems.append(
                f"Сжимать не во что: картинки берутся от "
                f"{self.image_min_mb:g} МБ, а ужимать велено до "
                f"{self.image_limit_kb} КБ — это не меньше исходного порога.")
        return problems

UpgradeSettings.__module__ = _api.__name__
_api.UpgradeSettings = UpgradeSettings

# ─────────────────────────────────────────────────────────────────────────────
# Отчёт об изменениях
# ─────────────────────────────────────────────────────────────────────────────
@_api.dataclass
class Change:
    """Одна правка. Место в паке общее для всех функций, поэтому и класс один:
    таблица на вкладке показывает их вперемешку, в порядке пака. У картинки
    места в раундах нет — вместо темы стоит имя файла, цены нет вовсе."""
    # special | title | case | poster | image | repeat | merge | empty |
    # audio | video | unused | character
    kind: str = "special"
    round_name: str = ""
    theme_name: str = ""
    price: int = 0
    before: str = ""                     # что было («с секретом», ответ)
    after: str = ""                      # что стало («обычный», ответ + варианты)
    added: list[str] = _api.field(default_factory=list)   # дописанные варианты
    title: str = ""                      # найденный на Shikimori тайтл
    # Номер вопроса в паке: по нему правки обеих функций выстраиваются в общую
    # таблицу в том же порядке, в каком идут в файле.
    order: int = 0

    @property
    def place(self) -> str:
        return f"«{self.round_name}» · «{self.theme_name}» · {self.price}"

Change.__module__ = _api.__name__
_api.Change = Change
