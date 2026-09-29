"""Pack composition, shares, and quotas. Public namespace: animepack."""
from __future__ import annotations

import animepack as _api


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
        _api.STUDIO_KIND: (max(0, int(self.pct_studio))
                           if self.pack_studio else 0),
    }
    for key in _api.TITLE_KINDS:
        raw[key] = max(0, int(getattr(self, "pct_" + key))) if getattr(self, "pack_" + key) else 0
    keys = list(raw)
    total = sum(raw.values())
    if total <= 0:
        return {k: (100 if k == "songs" and self.composition_enabled is None else 0) for k in keys}
    if total == 100:
        return raw                             # обычный случай — без дележа
    out = {k: v * 100 // total for k, v in raw.items()}
    rest = 100 - sum(out.values())
    for key in sorted(keys, key=lambda k: -(raw[k] * 100 % total)):
        if rest <= 0:
            break
        out[key] += 1
        rest -= 1
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
    if sum(weights.values()) <= 0:
        if self.composition_enabled is not None and not any(shares.values()):
            return {k: 0 for k in _api.SONG_KINDS + (_api.VIDEO_KIND,) + _api.SILENT_KINDS}
        weights = {k: 0 for k in weights}
        weights["songs"] = 1
    counts = _api._split_total(total, weights)
    quotas = _api._scale_quotas(self.quotas, counts["songs"])
    for kind in _api.SILENT_KINDS + (_api.VIDEO_KIND,):
        quotas[kind] = counts.get(kind, 0)
    return quotas

