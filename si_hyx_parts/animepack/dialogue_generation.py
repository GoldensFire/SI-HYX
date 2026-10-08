# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Сборка вопроса-диалога: SubDL (русские субтитры), затем Jimaku с переводом.

Gemini диалогов не сочиняет, но ВЫБИРАЕТ их всегда: читает серию целиком и
называет номера реплик, по которым узнаётся именно это аниме
(dialogue_gemini.py). Текст реплик берётся из самих субтитров; у Jimaku
Gemini ещё и переводит их."""
from __future__ import annotations

import animepack as _api


class DialogueQuestionMixin:
    """Генератор: вопрос по диалогу из субтитров."""

    def make_dialogue_question(self, cand: _api.SongCandidate) -> bool:
        from .dialogue_gemini import GEMINI_TRIES, ask
        subdl = getattr(self, "subdl", None)
        if self.gemini is None or (subdl is None and self.jimaku is None):
            self._drop_kind(_api.DIALOGUE_KIND)
            cand.rejected = True
            return False
        if str(cand.anime.get("kind") or "").casefold() == "movie":
            return False                 # у фильма нет правдивого номера серии
        episodes = self.anizip.episode_numbers(cand.mal_id)
        if not episodes:
            return False
        episodes = list(episodes)
        self.rng.shuffle(episodes)
        names = [cand.title_ru, cand.anime.get("name"), cand.anime.get("english")]
        names += list(cand.anime.get("synonyms") or [])
        # Запросов к Gemini на кандидата — не больше GEMINI_TRIES на оба источника.
        budget = {"left": GEMINI_TRIES}
        if subdl is not None:
            # Сначала SubDL, а Jimaku — только когда его квота кончилась (просьба
            # пользователя): у Jimaku Gemini ещё и переводит.
            from .dialogue_subdl import from_subdl
            done = from_subdl(self, cand, names, episodes, budget)
            if done is not None:
                return done
            if self.jimaku is None or self.gemini is None:
                self._drop_kind(_api.DIALOGUE_KIND)
                cand.rejected = True
                return False
        anilist_id = self.anizip.anilist_id(cand.mal_id)
        if not anilist_id:
            return False
        try:
            with self._timed("диалоги"):
                entry = self.jimaku.entry(anilist_id)
            if not entry:
                return False
            entry_id = int(entry.get("id") or 0)
            if not entry_id:
                return False
            for episode in episodes[:8]:
                key = (entry_id, int(episode))
                with self._dialogue_lock:
                    if key in self._dialogue_seen:
                        continue
                with self._timed("диалоги"):
                    files = self.jimaku.files(entry_id, episode)
                self.rng.shuffle(files)
                for file in files[:4]:
                    with self._timed("диалоги"):
                        data = self.jimaku.download(file)
                    picked = ask(self, cand, data, str(file.get("name") or ""),
                                 episode, names, True, budget)
                    if picked is None:
                        return False
                    lines, translated = picked
                    if not lines:
                        break               # в этой серии узнаваемого нет
                    with self._dialogue_lock:
                        if key in self._dialogue_seen:
                            return False
                        self._dialogue_seen.add(key)
                    cand.dialogue_source_text = _api.dialogue_text(lines)
                    cand.dialogue_text = _api.dialogue_text(translated)
                    cand.dialogue_episode = int(episode)
                    cand.source_link = _api.jimaku_clean_source_url(
                        str(file.get("url") or ""))
                    return True
        except _api.AnimePackApiError as error:
            if "ключ" in str(error).casefold():
                self.jimaku = None
                self._drop_kind(_api.DIALOGUE_KIND)
                cand.rejected = True
                self.log(f"Диалоги отключены: {error}")
            else:
                self._log_rare("Jimaku", f"Jimaku: {error}")
        except Exception as error:  # noqa: BLE001 — сетевой клиент подменяется в тестах
            self._log_rare("Jimaku", f"Jimaku: {error}")
        return False
