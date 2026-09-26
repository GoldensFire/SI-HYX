# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""AnimePackGenerator: _media_base. Public namespace: animepack."""
from __future__ import annotations
import animepack as _api


def _media_base(self, cand: _api.SongCandidate) -> str:
    """Имя медиафайлов вопроса внутри пака — «Сгенерировано в
        SI-HYX(Название тайтла)» (просьба пользователя: чтобы файлы в архиве
        читались глазами, а не числами).

        Одноимённые вопросы (несколько песен одного тайтла при разрешённых
        дублях) разводятся номером в конце — иначе они делили бы один файл."""
    title = _api.safe_filename(cand.title_ru or str(cand.media_key), "Аниме",
                          max_len=80)
    base = f"{_api.MEDIA_NAME_PREFIX}({title})"
    with self._names_lock:
        n = self._names.get(base, 0) + 1
        self._names[base] = n
    return base if n == 1 else f"{base} {n}"

# ── шаг 4: набор пака ─────────────────────────────────────────────────
def _prefers_music(self, cand: _api.SongCandidate) -> bool:
    """Тайтл пришёл из списка с пометкой «в основном музыка»?

        Такой список человек ведёт ради песен: тайтл он может и не узнать в
        лицо, а вот опенинг угадает. Поэтому его тайтлы по возможности идут в
        песенные вопросы, а в кадры и персонажи — только если песенных мест уже
        не осталось (просьба пользователя)."""
    if not self._music_nicks:
        return False
    return any(str(n).strip().casefold() in self._music_nicks
               for n in (cand.users or []))

def _pick_kind(self, cand: _api.SongCandidate, counts, inflight, quotas):
    """Каким вопросом станет кандидат — или None, если он больше не нужен.

        В смешанном режиме песня может стать вопросом-кадром: карточка аниме у
        неё уже есть, кадр берётся оттуда же. Выбираем из доступного тот тип,
        который сильнее отстаёт от своей квоты, — так пак набирается ровно, а не
        сначала все песни, потом все кадры."""
    options = [cand.kind]
    if cand.kind != _api.MANGA_KIND:
        # Мангу не трогаем ни с какой стороны: её карточка приходит из
        # своего каталога, ни кадров, ни песен у книги нет.
        options += [k for k in _api.SILENT_KINDS
                    if k not in (_api.MANGA_KIND, cand.kind) and quotas.get(k, 0)]
        # Роликом может стать любая песня, кроме OST: их на AnimeThemes
        # нет вовсе (см. _theme_video). А вот у кандидата без песни ролику
        # взяться неоткуда.
        if (cand.kind not in _api.SILENT_KINDS and cand.kind != "insert"
                and quotas.get(_api.VIDEO_KIND, 0)):
            options.append(_api.VIDEO_KIND)
    free = [k for k in options
            if k not in self._dead_kinds
            and counts[k] + inflight[k] < quotas.get(k, 0)]
    # Рамка сложности у артов своя (просьба пользователя): тайтл, слишком
    # безвестный для арта, всё ещё годится в кадр или песню, и наоборот.
    free = [k for k in free if _level_ok(self.s, cand, k)]
    # Книжные доли: экранизованная/нет, манхва, маньхуа.
    if _api.MANGA_KIND in free and not self._manga_mix.allows(cand):
        free.remove(_api.MANGA_KIND)
    from .title_selection import TITLE_QUESTION_KINDS, short_title
    title_cand = getattr(cand, "_title_variant", cand)
    if title_cand is None or not short_title(title_cand.anime):
        free = [k for k in free if k not in TITLE_QUESTION_KINDS]
    if any(k in _api.GEMINI_TITLE_KINDS for k in free):
        from .title_eligibility import russian_title, verdict
        checked = verdict(getattr(self, "_title_eligibility", {}),
                          russian_title(title_cand))
        if not checked["eligible"]:
            free = [k for k in free if k not in _api.GEMINI_TITLE_KINDS]
        elif "antonyms" in free and not _antonyms_ok(checked, title_cand):
            # Антонимы подходят не всякому названию: одно имя собственное
            # перевернуть не во что. Такой тайтл просто получает другой род
            # вопроса, а антонимы ждут следующего кандидата (просьба
            # пользователя). Заодно берём только ТВ-сериалы и полнометражки:
            # OVA и ONA для этого слишком безвестны.
            free.remove("antonyms")
    if _api.AI_ART_KIND in free:
        from animepack_art_filter import possible_art_title
        if not possible_art_title(cand.anime):
            free.remove(_api.AI_ART_KIND)
    if _api.STUDIO_KIND in free:
        # Студии лежат в самой карточке, так что проверка бесплатная: тайтл
        # без них незачем доводить до загрузки трёх кадров.
        from .studio_question import studio_possible
        if not studio_possible(cand.anime):
            free.remove(_api.STUDIO_KIND)
    if not free:
        return None
    if self._prefers_music(cand):
        # Песенные места есть — картинки и текст этому тайтлу не предлагаем
        # вовсе.
        songs = [k for k in free if k not in _api.SILENT_KINDS]
        if songs:
            free = songs
    if len(free) == 1:
        return free[0]
    return min(free, key=lambda k: (counts[k] + inflight[k]) / max(1, quotas[k]))

# Из каких типов аниме вообще берутся антонимы (просьба пользователя):
# только ТВ-сериалы и полнометражки, без OVA, ONA и спешлов.
ANTONYM_KINDS = ("tv", "movie")


def _level_ok(settings, cand: _api.SongCandidate, kind: str) -> bool:
    """Проходит ли тайтл рамку сложности ИМЕННО этого рода вопросов."""
    low, high = settings.level_range(kind)
    return low <= cand.level <= high


def _antonyms_ok(checked: dict, title_cand) -> bool:
    """Годится ли название под антонимы: тип тайтла и вердикт модели."""
    if str((title_cand.anime or {}).get("kind") or "").lower() not in ANTONYM_KINDS:
        return False
    return bool(checked.get("antonyms"))


def _level_fits(self, cand: _api.SongCandidate, levels: list,
                kind: _api.Optional[str] = None, flying=()) -> bool:
    """Держит среднюю сложность пака около level_avg.

        Рамки «от … до» задают, что вообще пускать, а это — на что должна
        выйти СЕРЕДИНА (просьба пользователя): пока набранная средняя выше
        цели, берём только тайтлы полегче, и наоборот. Первые несколько вопросов
        пропускаем без проверки — по одному-двум средняя ещё ничего не значит.

        У артов и книг середина своя (см. level_avg.py). Такой вопрос считается
        в СВОЕЙ корзине и в общую среднюю не идёт вовсе: у книг своя шкала
        узнаваемости, и два десятка их иначе утащили бы среднюю всего пака.
        Своя средняя не задана (ноль) — вопрос считается вместе со всеми,
        ровно как раньше.

        flying — кандидаты, которые прямо сейчас качаются. Их уровень
        считается вместе с набранным: в работе одновременно до двух десятков
        загрузок, и без них середина проверялась по устаревшему списку —
        паки при просимой четвёрке выходили в среднем 4.5.

        Клапан на случай, когда подходящих просто нет: после
        LEVEL_AVG_GIVE_UP подряд отвергнутых кандидат проходит любой, иначе пак
        остался бы недобранным."""
    bucket = _api.own_bucket(self.s, kind if kind is not None else cand.kind)
    target = _api.level_avg_target(self.s, bucket)
    if not target:
        return True
    # Каталог кончился, а пак не набран: середина больше не сторожится вовсе
    # (см. _take_level_bench). Полный пак важнее точного попадания в неё.
    if self._level_relaxed:
        return True
    seen = list(levels if bucket is None
                else self._bucket_levels.setdefault(bucket, []))
    seen += [int(c.level) for c in flying
             if _api.own_bucket(self.s, c.kind) == bucket]
    if len(seen) < 3:
        return True
    if self._level_skips[bucket] >= self.LEVEL_AVG_GIVE_UP:
        if bucket not in self._level_warned:
            self._level_warned.add(bucket)
            where = (" " + _api.BUCKET_TITLES[bucket]) if bucket else ""
            self.log(f"Средняя сложность{where} {target} не выдерживается — "
                     "подходящих тайтлов не хватает, беру что есть.")
        self._level_skips[bucket] = 0
        return True
    avg = sum(seen) / len(seen)
    if avg > target + 0.25 and cand.level > target:
        self._level_skips[bucket] += 1
        return False
    if avg < target - 0.25 and cand.level < target:
        self._level_skips[bucket] += 1
        return False
    self._level_skips[bucket] = 0
    return True


def _remember_level(self, cand: _api.SongCandidate, levels: list) -> None:
    """Запоминает узнаваемость принятого вопроса в его корзине."""
    bucket = _api.own_bucket(self.s, cand.kind)
    if bucket is None:
        levels.append(cand.level)
    else:
        self._bucket_levels.setdefault(bucket, []).append(cand.level)


# ── отложенные ради средней сложности ─────────────────────────────────
def _bench_candidate(self, cand) -> None:
    """Откладывает кандидата, который прямо сейчас увёл бы среднюю.

        Раньше такой выбрасывался навсегда: за прогон так сгорел 321 кандидат,
        а пак всё равно остался недобранным (116 вопросов из 144). Клапан
        LEVEL_AVG_GIVE_UP тут не спасал — любой случайно прошедший кандидат
        обнулял счётчик подряд отвергнутых.

        Бронь на франшизу отпускается: пока кандидат ждёт, серия должна
        оставаться доступной другим тайтлам. Ключи брони запоминаются, и при
        возврате со скамейки франшиза занимается заново (_rebook_candidate)."""
    self._level_benched += 1
    if len(self._level_bench) < self._level_bench_cap:
        self._level_bench.append(cand)
    self._release_candidate(cand)


def _take_level_bench(self) -> list:
    """Отложенные ради средней — и дальше середина не сторожится.

        Зовётся, когда основной поток кандидатов иссяк, а мест в паке ещё
        полно. Ближайшие к просимой середине идут первыми: так средняя
        уезжает настолько мало, насколько это вообще возможно."""
    if self._level_relaxed or not self._level_bench:
        return []
    bench, self._level_bench = self._level_bench, []
    self._level_relaxed = True
    self._level_reused = len(bench)
    target = int(getattr(self.s, "level_avg", 0) or 0)
    if target:
        bench.sort(key=lambda c: abs(c.level - target))
    self.log(f"Кандидаты кончились, а пак не набран — беру отложенных ради "
             f"средней сложности ({len(bench)} шт.): полный пак важнее "
             "точной середины.")
    return bench


def _rebook_candidate(self, cand) -> bool:
    """Снова занимает франшизу кандидата, вернувшегося со скамейки.

        Пока он ждал, его серию мог занять другой тайтл — тогда кандидат
        больше не нужен, иначе в паке оказалась бы пара вопросов из одной
        серии. Свежему кандидату (бронь при нём) проверка ничего не стоит."""
    keys = getattr(cand, "_bench_keys", None)
    if not keys:
        return True
    cand._bench_keys = None
    if not self.s.dup_franchise and any(k in self._used_franchise
                                        for k in keys if k):
        return False
    self._used_franchise.update(k for k in keys if k)
    cand._reserved = keys
    return True
