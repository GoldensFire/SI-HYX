# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""PackSettings: перенос настроек в settings.json и обратно.

Здесь же живёт весь переезд СТАРЫХ настроек: галочки состава, ставшие
процентами ползунка, «Вопрос — ролик» до появления доли роликов, удалённая
модель картинок и потолки, появившиеся позже самих настроек. Читатель,
которому нужен состав пака, сюда не заглядывает, а файл настроек упёрся в
предел размера — поэтому блок вынесен целиком.

Public namespace: animepack (методы подключаются в теле PackSettings).
"""
from __future__ import annotations
import animepack as _api
from cloudflare_art_api import DEFAULT_MODEL as ART_DEFAULT_MODEL
from cover_meta_rules import LANGUAGE_KEYS as COVER_LANGUAGE_KEYS
from cover_meta_rules import TYPE_LABELS as COVER_TYPE_LABELS
from frame_reveal import EFFECT_LABELS, REMOVED_EFFECTS, add_new_effects, clean_effects
from image_entrance import (
    PACK_EFFECT_LABELS as ENTRANCE_EFFECT_LABELS, EDITOR_ONLY_EFFECTS,
    TARGET_LABELS, clean_keys)


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
        elif key == "composition_enabled":
            # Список включённых родов вопросов. Читается ОТДЕЛЬНО, потому что
            # по умолчанию здесь None: общая ветка ниже пыталась бы сделать
            # NoneType(список), молча падала — и сохранённый состав не
            # применялся вовсе. Пустой список сняли ВСЁ, и это не то же самое,
            # что «настройки без состава»: иначе после перезапуска сами собой
            # включались «Песни».
            s.composition_enabled = [str(k) for k in (value or []) if k]
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
        elif key in ("ost_difficulty_min", "ost_difficulty_max",
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
    from .manga_editions import migrate
    migrate(s, d)
    return s
