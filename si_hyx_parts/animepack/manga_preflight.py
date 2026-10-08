"""Explain comic quotas and visual request demand before media preparation."""
import math

import animepack as ap


def describe(generator):
    settings = generator.s
    quota = settings.question_quotas[ap.MANGA_KIND]
    mix = ap.MangaMix(settings, quota)
    webtoons = mix.kind_target["manhwa"] + mix.kind_target["manhua"]
    manga = mix.kind_target[""]
    # Selection batches combine two page pools; crop reviews combine up to four.
    estimate = math.ceil(webtoons / 2) + math.ceil(webtoons / 4) + math.ceil(manga / 4)
    generator.log(f"Комиксы: манга {manga}, манхва {mix.kind_target['manhwa']}, "
                  f"маньхуа {mix.kind_target['manhua']}; "
                  f"строгие цели {'включены' if settings.manga_strict_targets else 'выключены'}.")
    client = generator.gemini_manga
    if client is not None:
        board = getattr(client, "board", None)
        remaining = board.left(client.model) if board is not None else -1
        known = f", известный остаток модели {remaining}" if remaining >= 0 else ""
        generator.log(f"План визуальных проверок: около {estimate} запросов "
                      f"при заполненных группах, плюс повторы{known}. "
                      "Фактическая квота зависит от проекта Gemini.")
