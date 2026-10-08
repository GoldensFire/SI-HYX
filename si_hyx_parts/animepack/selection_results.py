# -*- coding: utf-8 -*-
"""Принимает завершённые вопросы, возвращая места после отказов и дублей."""
def collect_finished(self, done, pending, accepted, counts, inflight, levels,
                     quotas, effect_slots, deferred, total, reserve=None):
    from .early_repeat import release as release_exact
    from si_hyx_parts.animepack.generator_selection import _busy
    for fut in done:
        cand = pending.pop(fut)
        inflight[cand.kind] -= 1
        try:
            ok = fut.result()
        except Exception as e:  # noqa: BLE001
            from storage_guard import raise_if_full
            raise_if_full(e, self.folder)
            self.log(f"Загрузка сорвалась: {e}")
            ok = False
        if not ok:
            release_exact(self, cand)
            self._manga_mix.release(cand)
            self._release_candidate(cand)
            if cand.music_slot >= 0:
                effect_slots.release(cand)
                for note in effect_slots.take_notes():
                    self.log(note)
            temporary = (getattr(cand, "_music_temporary", False)
                         or getattr(cand, "_network_temporary", False))
            # Отвергнутый по средней сложности — не «не
            # скачалось»: медиа мы даже не трогали.
            if getattr(cand, "_music_temporary", False):
                self._late["временный отказ музыкального источника"] += 1
            elif temporary:
                self._late["временный сбой сети — тайтл отложен на повтор"] += 1
            elif getattr(cand, "_exact_waiting", False):
                self._tries[cand.kind] -= 1
                deferred.append(cand)
            elif getattr(cand, "_exact_duplicate", False):
                self._early_repeat_attempts += 1
            elif cand.rejected:
                self._rejected_media += 1
            else:
                self._failed_media += 1
            if reserve is not None and not getattr(cand, "_exact_waiting", False):
                retries = getattr(cand, "_technical_retries", 0) + 1
                cand._technical_retries = retries
                if temporary and retries <= 2:
                    import time
                    cand._retry_after = time.monotonic() + 60
                reserve.park(cand, failed=not temporary or retries > 2)
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
        # Favorites/franchise enrichment during downloading may change the
        # level. Check before committing repeat keys to the accepted pack.
        from si_hyx_parts.animepack.generator_selection import _level_ok
        if not _level_ok(self.s, cand, cand.kind) or not self._level_fits(
                cand, levels, cand.kind, pending.values()):
            release_exact(self, cand)
            cand._ready_media = (cand.kind, cand.music_effect)
            self._late["после уточнения уровня не подходит средняя"] += 1
            self._manga_mix.release(cand)
            if cand.music_slot >= 0:
                effect_slots.give_back(cand)
            self._bench_candidate(cand)
            continue
        size = self._media_size(cand)
        if self._bytes_used + size > self._byte_budget - min(65536, self._byte_budget // 100):
            release_exact(self, cand)
            self._manga_mix.release(cand)
            self._release_candidate(cand)
            self._late['медиа не помещается в оставшийся размер пака'] += 1
            if cand.music_slot >= 0:
                effect_slots.give_back(cand)
            if reserve is not None:
                reserve.park(cand, failed=True)
            continue
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
        self._bytes_used += size
        # Название тайтла на прогресс-баре не пишем (просьба
        # пользователя): в лог оно и так идёт, а на баре нужны
        # счётчик, оставшееся время и то, чем генератор занят
        # прямо сейчас — «Сакуга», «Кадр», «Манга».
        self._progress(len(accepted), total, _busy(inflight))
        if self._over_budget(len(accepted), total):
            return True
    return False
