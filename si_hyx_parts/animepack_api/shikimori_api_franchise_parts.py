# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""ShikimoriApi: franchise_parts. Public namespace: animepack_api."""
from __future__ import annotations
import animepack_api as _api


def franchise_parts(self, keys: _api.Iterable[str]) -> dict:
    """{ключ франшизы: [карточки её частей по убыванию популярности]}.

        Нужно, чтобы сиквел считался таким же узнаваемым, как оригинал (у
        «Доктор Стоун: Научное будущее. Часть 3» своих зрителей мало, но
        спрашивают-то по сути «Доктора Стоуна»), а заодно чтобы сериал с
        несколькими живыми сезонами получал надбавку, а старый тайтл со свежим
        продолжением — послабление по году (shikimori_api.franchise_parts_index).
        Запрос один на FRANCHISE_BATCH франшиз (алиасы в одном GraphQL-документе).
        """
    clean, seen, aliases = [], set(), {}
    for key in keys:
        original = str(key or "").strip()
        normalized = self._RE_FRANCHISE.sub("", original.lower())
        if not normalized:
            continue
        aliases.setdefault(normalized, []).append(original)
        if normalized not in seen:
            seen.add(normalized)
            clean.append(normalized)
    out: dict = {}
    for batch in (clean[i:i + self.FRANCHISE_BATCH]
                  for i in range(0, len(clean), self.FRANCHISE_BATCH)):
        parts = [f'  f{n}: animes(franchise: "{key}", '
                 f'limit: {self.FRANCHISE_PARTS}, '
                 f'order: popularity) {{ {self.FRANCHISE_FIELDS} }}'
                 for n, key in enumerate(batch)]
        self.limiter.acquire()
        try:
            data = self.client._graphql("query {\n" + "\n".join(parts) + "\n}",
                                        {})
        except Exception:  # noqa: BLE001 — без частей франшизы пак соберётся
            # Сорвавшуюся пачку НЕ отмечаем как «частей нет»: иначе разовый
            # обрыв сети навсегда осел бы в кэше нулевой узнаваемостью.
            continue
        for n, key in enumerate(batch):
            found = (data or {}).get(f"f{n}") if isinstance(data, dict) else None
            # Пустой список тоже ответ («у этой франшизы частей нет») —
            # ключ есть, значит спрашивать её снова незачем.
            rows = [r for r in (found or []) if isinstance(r, dict)]
            # В карточках Shikimori встречаются ключи с квадратными скобками
            # (например ``[oshi_no_ko]``). В GraphQL их надо убрать, но кэш
            # обязан сохранить исходный ключ: именно его потом ищет карточка.
            for original in aliases.get(key, (key,)):
                out[original] = list(rows)
    return out
