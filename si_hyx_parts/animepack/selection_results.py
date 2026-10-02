# -*- coding: utf-8 -*-
"""Принимает завершённые вопросы, возвращая места после отказов и дублей."""
def collect_finished(self, done, pending, accepted, counts, inflight, levels,
                     quotas, effect_slots, deferred, total, reserve=None):
    from .early_repeat import release as release_exact
    from .anime_pack_generator_select_songs import _busy
    for fut in done:
        cand = pending.pop(fut)
        inflight[cand.kind] -= 1
        try:
            ok = fut.result()
        except Exception as e:  # noqa: BLE001
            self.log(f"Загрузка сорвалась: {e}")
            ok = False
        if not ok:
            release_exact(self, cand)
            self._manga_mix.release(cand)
            self._release_candidate(cand)
            if cand.music_slot >= 0:
                effect_slots.release(cand)
            # Отвергнутый по средней сложности — не «не
            # скачалось»: медиа мы даже не трогали.
            if getattr(cand, "_exact_waiting", False):
                self._tries[cand.kind] -= 1
                deferred.append(cand)
            elif getattr(cand, "_exact_duplicate", False):
                self._early_repeat_attempts += 1
            elif cand.rejected:
                self._rejected_media += 1
            else:
                self._failed_media += 1
            if reserve is not None and not getattr(cand, "_exact_waiting", False):
                reserve.park(cand, failed=True)
            continue
        if len(accepted) >= total or counts[cand.kind] >= quotas.get(cand.kind, 0):
            release_exact(self, cand)
            self._late["пока качали, место занял другой"] += 1
            self._manga_mix.release(cand)
            self._release_candidate(cand)
            # Слот способа подачи возвращаем ОБЯЗАТЕЛЬНО: вопрос
            # готов, а места ему не нашлось, и это не неудача
            # эффекта. Без этого слоты утекали, и на последних
            # вопросах пака reserve оставался без свободных.
            if cand.music_slot >= 0:
                effect_slots.give_back(cand)
            if reserve is not None:
                reserve.park(cand)
            continue        # пока качали, место уже заняли
        if self._exact_keys:
            from .early_repeat import accept as accept_exact
            if not accept_exact(self, cand):
                release_exact(self, cand)
                self._late["тот же вопрос в выбранных паках"] += 1
                self._manga_mix.release(cand)
                self._release_candidate(cand)
                if cand.music_slot >= 0:
                    effect_slots.give_back(cand)
                if reserve is not None:
                    reserve.park(cand, failed=True)
                continue
        release_exact(self, cand)
        if cand.music_slot >= 0:
            effect_slots.succeed(cand)
        accepted.append(cand)
        if reserve is not None:
            reserve.accepted(cand)
        self._remember_level(cand, levels)
        self._remember_char_level(cand)
        counts[cand.kind] += 1
        self._bytes_used += self._media_size(cand)
        # Название тайтла на прогресс-баре не пишем (просьба
        # пользователя): в лог оно и так идёт, а на баре нужны
        # счётчик, оставшееся время и то, чем генератор занят
        # прямо сейчас — «Сакуга», «Кадр», «Манга».
        self._progress(len(accepted), total, _busy(inflight))
        if self._over_budget(len(accepted), total):
            return True
    return False
