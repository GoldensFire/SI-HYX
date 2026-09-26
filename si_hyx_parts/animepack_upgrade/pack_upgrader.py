# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""PackUpgrader. Public namespace: animepack_upgrade."""
from __future__ import annotations
import animepack_upgrade as _api


class PackUpgrader:
    """Читает .siq, правит content.xml и пишет результат отдельным файлом.

    Медиа из архива не распаковывается вовсе: записи копируются как есть, в том
    же виде и с тем же сжатием, — на паке в сотню мегабайт это секунды, а не
    минуты перекодирования. Исключение — тяжёлые картинки при включённой третьей
    функции: только они и достаются наружу, чтобы уйти в AVIF под лимит."""

    from si_hyx_parts.animepack_upgrade.pack_upgrader___init import (
        __init__,
        log,
        stopped,
        api,
        find_title,
        find_character,
        run,
        _do_empty,
        _do_repeats,
        _do_merge,
        _do_special,
    )

    from si_hyx_parts.animepack_upgrade.pack_upgrader__do_titles import (
        _do_titles,
        _do_poster,
        _poster_job,
        _poster_pool,
        _poster_bytes,
        _tmdb_url,
        _poster_file,
        _finish_posters,
    )

    from si_hyx_parts.animepack_upgrade.pack_upgrader__free_poster_name import (
        _free_poster_name,
        _url_ext,
        _fetch,
        _heavy_images,
        _plans,
        _run_jobs,
        _extract,
        _do_images,
        _compress_one,
        _to_avif,
        _heavy_audio,
        _do_audio,
    )

    from si_hyx_parts.animepack_upgrade.pack_upgrader__compress_audio_one import (
        _compress_audio_one,
        _audio_kbps,
        _to_opus,
        _video_entries,
        _do_video,
        _compress_video_one,
        _video_codec,
        _video_filter,
        _to_av1,
        _do_unused,
        _out_path,
    )

    from si_hyx_parts.animepack_upgrade.pack_upgrader__write import _write

PackUpgrader.__module__ = _api.__name__
_api.PackUpgrader = PackUpgrader

# ─────────────────────────────────────────────────────────────────────────────
# Примеры изменений («покажи по три с каждой функции»)
# ─────────────────────────────────────────────────────────────────────────────
def _shorten(text: str, limit: int = 70) -> str:
    line = " ".join(str(text or "").split())
    return line if len(line) <= limit else line[:limit - 1] + "…"

_shorten.__module__ = _api.__name__
_api._shorten = _shorten

def example_lines(result: _api.UpgradeResult, limit: int = 3) -> list[str]:
    """Готовые строки отчёта: по нескольку примеров с каждой функции.

    Пустая функция тоже отчитывается — «ничего не нашлось» это ответ, а не
    повод промолчать."""
    lines: list[str] = []

    lines.append(f"Спецвопросов расколдовано: {len(result.specials)}.")
    for change in result.specials[:limit]:
        lines.append(f"  • {change.place}: «{change.before}» → {change.after}")
    if not result.specials:
        lines.append("  • примеров нет: спецвопросов в паке не нашлось.")
    if result.skipped_specials:
        lines.append(f"  • пропущено {len(result.skipped_specials)}: "
                     f"{_api._shorten(result.skipped_specials[0].after)}.")

    lines.append(f"Ответов дополнено названиями: {len(result.titles)}.")
    for change in result.titles[:limit]:
        added = ", ".join(change.added)
        lines.append(f"  • {change.place}: «{_api._shorten(change.before)}» "
                     f"+ {len(change.added)} вариант(ов) — {_api._shorten(added, 90)}")
    if not result.titles:
        lines.append("  • примеров нет: названий аниме в ответах не опознано.")
    elif result.not_found:
        lines.append(f"  • не нашлось на Shikimori: {result.not_found} из "
                     f"{result.checked_answers} проверенных ответов.")
    if getattr(result, "typo_titles", 0):
        lines.append(f"  • опознано с опечаткой в ответе: {result.typo_titles} "
                     f"(в паке название написано с ошибкой).")
    if result.skipped_titles:
        first = result.skipped_titles[0]
        lines.append(f"  • пропущено как имена персонажей: "
                     f"{len(result.skipped_titles)} (например «{first.before}» "
                     f"— {_api._shorten(first.after, 60)})")

    lines.append(f"Названий переписано как на Shikimori: {len(result.recased)}.")
    for change in result.recased[:limit]:
        lines.append(f"  • {change.place}: «{_api._shorten(change.before)}» → "
                     f"«{_api._shorten(change.after)}»")
    if not result.recased:
        lines.append("  • примеров нет: написание везде и так совпадает.")

    lines.append(f"Постеров поставлено в ответ: {len(result.posters)}"
                 + (f" (пак тяжелее на {_api.fmt_size(result.added_bytes)})."
                    if result.added_bytes > 0 else "."))
    for change in result.posters[:limit]:
        lines.append(f"  • {change.place}: «{_api._shorten(change.title)}» — "
                     f"{change.after}")
    if not result.posters:
        lines.append("  • примеров нет: точных совпадений названия не было."
                     if not result.exact_titles else
                     "  • примеров нет: в ответах уже стояли свои картинки "
                     "либо постера у тайтла на Shikimori нет.")

    repeats = list(getattr(result, "repeats", []))
    lines.append(f"Повторяющихся подписей убрано: {len(repeats)}.")
    for change in repeats[:limit]:
        lines.append(f"  • {change.place}: «{_api._shorten(change.before)}» — убран")
    if not repeats:
        lines.append("  • примеров нет: одинакового текста во всех вопросах "
                     "темы не нашлось.")

    merged = list(getattr(result, "merged", []))
    lines.append(f"Текстов, включённых вместе со звуком: {len(merged)}.")
    for change in merged[:limit]:
        lines.append(f"  • {change.place}: «{_api._shorten(change.before)}» — "
                     f"{change.after}")
    if not merged:
        lines.append("  • примеров нет: текста прямо перед отрывком в паке нет "
                     "(или он уже играл одновременно).")

    empties = list(getattr(result, "empties", []))
    lines.append(f"Пустых вопросов удалено: {len(empties)}"
                 + (f" (и {result.dropped_themes} тем(ы) без вопросов)."
                    if result.dropped_themes else "."))
    for change in empties[:limit]:
        lines.append(f"  • {change.place}: {_api._shorten(change.before)}")
    if not empties:
        lines.append("  • примеров нет: вопросов без содержимого в паке нет.")

    lines.append(f"Картинок сжато: {len(result.images)}"
                 + (f" (пак легче на {_api.fmt_size(result.saved_bytes)})."
                    if result.saved_bytes > 0 else "."))
    for change in result.images[:limit]:
        lines.append(f"  • {_api._shorten(change.theme_name)}: {change.before} → "
                     f"{change.after}")
    if not result.images:
        lines.append("  • примеров нет: картинок тяжелее порога в паке нет."
                     if not result.heavy_images else
                     f"  • примеров нет: ни одну из {result.heavy_images} "
                     f"тяжёлых картинок сжать не вышло.")

    audios = list(getattr(result, "audios", []))
    lines.append(f"Дорожек перекодировано в opus: {len(audios)}"
                 + (f" (пак легче на {_api.fmt_size(result.saved_audio_bytes)})."
                    if result.saved_audio_bytes > 0 else "."))
    for change in audios[:limit]:
        lines.append(f"  • {_api._shorten(change.theme_name)}: {change.before} → "
                     f"{change.after}")
    if not audios:
        lines.append("  • примеров нет: аудио тяжелее порога в паке нет."
                     if not getattr(result, "heavy_audio", 0) else
                     f"  • примеров нет: ни одну из {result.heavy_audio} "
                     f"тяжёлых дорожек перекодировать не пришлось.")

    videos = list(getattr(result, "videos", []))
    lines.append(f"Роликов перекодировано в AV1: {len(videos)}"
                 + (f" (пак легче на {_api.fmt_size(result.saved_video_bytes)})."
                    if result.saved_video_bytes > 0 else "."))
    for change in videos[:limit]:
        lines.append(f"  • {_api._shorten(change.theme_name)}: {change.before} → "
                     f"{change.after}")
    if not videos:
        lines.append("  • примеров нет: видео под перекод в паке нет."
                     if not getattr(result, "heavy_video", 0) else
                     f"  • примеров нет: ни один из {result.heavy_video} "
                     f"роликов перекодировать не пришлось.")

    unused = list(getattr(result, "unused", []))
    lines.append(f"Неиспользуемых файлов удалено: {len(unused)}"
                 + (f" (пак легче на {_api.fmt_size(result.saved_unused_bytes)})."
                    if result.saved_unused_bytes > 0 else "."))
    for change in unused[:limit]:
        lines.append(f"  • {_api._shorten(change.theme_name)}: {change.before} — "
                     f"ссылок нет")
    if not unused:
        lines.append("  • примеров нет: на каждый файл в паке есть ссылка.")
    return lines

example_lines.__module__ = _api.__name__
_api.example_lines = example_lines
