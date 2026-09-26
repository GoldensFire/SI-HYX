# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Вопрос-диалог из русских субтитров SubDL.

SubDL — первый источник диалогов, Jimaku — после его суточной квоты (просьба
пользователя). Реплики уже на русском, переводить их не нужно, но ВЫБИРАЕТ
отрывок всё равно Gemini: он читает серию целиком и берёт то, по чему
узнаётся именно это аниме (dialogue_gemini.py).
"""
from __future__ import annotations

import animepack as _api


def _decode(data: bytes) -> bytes:
    """Русские субтитры в UTF-8: общий разбор пробует японскую cp932 раньше
    cp1251, и кириллица в cp1251 превращалась бы в мусор."""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data
    for encoding in ("utf-8-sig", "cp1251"):
        try:
            return data.decode(encoding).encode("utf-8")
        except UnicodeError:
            continue
    return data


def from_subdl(self, cand, names, episodes, budget):
    """True — вопрос готов, False — у SubDL для тайтла ничего не вышло,
    None — квота кончилась прямо сейчас (дальше пусть решает Jimaku)."""
    from .dialogue_gemini import ask
    ids = self.anizip.external_ids(cand.mal_id)
    if not ids.get("imdb_id") and not ids.get("tmdb_id"):
        return False
    wanted = set(episodes)
    rows = [row for row in self.anizip.tv_episodes(cand.mal_id)
            if row["episode"] in wanted]
    self.rng.shuffle(rows)
    ident = ids.get("imdb_id") or ids.get("tmdb_id")
    try:
        for row in rows[:6]:
            key = ("subdl", ident, row["season"], row["episode"])
            with self._dialogue_lock:
                if key in self._dialogue_seen:
                    continue
            with self._timed("диалоги"):
                files = self.subdl.episode_files(ids, row["season"],
                                                 row["episode"])
            self.rng.shuffle(files)
            for file in files[:3]:
                with self._timed("диалоги"):
                    data, name = self.subdl.download(file)
                if not data:
                    continue
                picked = ask(self, cand, _decode(data), name, row["episode"],
                             names, False, budget)
                if picked is None:
                    return False
                lines, shown = picked
                if not lines:
                    break               # в этой серии узнаваемого нет
                with self._dialogue_lock:
                    if key in self._dialogue_seen:
                        return False
                    self._dialogue_seen.add(key)
                cand.dialogue_source_text = _api.dialogue_text(lines)
                cand.dialogue_text = _api.dialogue_text(shown)
                cand.dialogue_episode = int(row["episode"])
                cand.source_link = str(file.get("page") or "")
                return True
    except _api.SubdlQuotaError as error:
        self.subdl = None
        where = ("дальше диалоги берутся из Jimaku"
                 if self.jimaku is not None
                 else "Jimaku не настроен — диалогов больше не будет")
        self.log(f"SubDL: {error}; {where}.")
        return None
    except _api.AnimePackApiError as error:
        if "ключ" in str(error).casefold():
            self.subdl = None
            self.log(f"SubDL отключён: {error}")
            return None
        self._log_rare("SubDL", f"SubDL: {error}")
    except Exception as error:  # noqa: BLE001 — сеть и подменённые клиенты
        self._log_rare("SubDL", f"SubDL: {error}")
    return False
