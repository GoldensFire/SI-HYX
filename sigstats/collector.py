"""Сбор данных: sibrowser → БД → статистика → (опционально) .siq."""
from __future__ import annotations
import json
from typing import Callable

from . import config, db, sibrowser, stats_api, siq, steam_workshop

ProgressCB = Callable[[int, int, str], None]


def _noop(done: int, total: int, msg: str) -> None:
    pass


def _never_stop() -> bool:
    return False


def _is_blacklisted(authors: list[str], blacklist: set[str] | None) -> bool:
    if not blacklist:
        return False
    return any(a.strip().lower() in blacklist for a in authors)


def collect(
    min_downloads: int = 150,
    max_new: int = 50,
    download_siq: bool = False,
    mode: str = "downloads",
    cutoff_date: str | None = None,
    min_started: int = 0,
    category_slug: str | None = None,
    category_min_pct: int = 0,
    author_blacklist: set[str] | None = None,
    start_page: int = 1,
    on_new_package: Callable[[int], None] | None = None,
    progress_cb: ProgressCB | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> dict:
    """Главный проход. Возвращает сводку результата.

    mode='downloads' — по скачиваниям (порог min_downloads).
    mode='date' — по дате: собираются паки с датой >= cutoff_date.
    min_started — минимум реально начатых игр; паки ниже порога пропускаются
        (скачивания легко накрутить, начатые игры — нет).
    category_slug/category_min_pct — доп. фильтр по теме (например, «Аниме»
        со слагом 'anime'): собираются только паки, где доля этой категории
        не ниже category_min_pct (по умолчанию фильтр выключен).
    author_blacklist — множество никнеймов (в нижнем регистре); паки этих
        авторов пропускаются и не попадают в БД.
    start_page — с какой страницы каталога начинать обход (см. sibrowser.
        iter_cards) — используется для продолжения предыдущего сбора.
    on_new_package — вызывается с id пакета сразу после его сохранения в БД
        (для «живого» добавления строк в таблицу интерфейса по мере сбора).
    should_stop — вызывается между паками; при True обход останавливается
        (уже собранное в БД сохранено — не откатывается).

    В summary возвращаются также last_page (последняя просмотренная страница
    каталога — для кэша, чтобы в следующий раз начать оттуда) и last_date/
    last_name (дата публикации и название последнего рассмотренного пака —
    чтобы понимать, докуда дошёл обход).
    """
    cb = progress_cb or _noop
    stop = should_stop or _never_stop
    db.init_db()
    session = sibrowser.make_session()

    summary = {"new": 0, "with_stats": 0, "with_siq": 0, "skipped_existing": 0,
               "no_stats": 0, "skipped_low_games": 0, "skipped_blacklisted": 0,
               "last_page": start_page, "last_date": None, "last_name": None}

    with db.connect() as conn:
        skip_norms = db.existing_name_norms(conn)
        before = len(skip_norms)

        done = 0
        page_state: dict = {}
        for card in sibrowser.iter_cards(
            session, min_downloads=min_downloads,
            skip_norms=skip_norms, mode=mode, cutoff_date=cutoff_date,
            category_slug=category_slug, category_min_pct=category_min_pct,
            start_page=start_page, state=page_state,
            progress_cb=lambda m: cb(done, max_new, m), should_stop=stop,
        ):
            if stop():
                break
            if _is_blacklisted(card.authors, author_blacklist):
                summary["skipped_blacklisted"] += 1
                continue
            # статистику тянем первой, чтобы отсеять накрученные по скачиваниям
            stats = stats_api.get_package_stats(session, card.name, card.authors)
            s = stats_api.summarize(stats)
            if min_started > 0 and s["started"] < min_started:
                summary["skipped_low_games"] += 1
                stats_api.throttle()
                continue

            pid = db.upsert_package(conn, card.as_package())
            db.replace_themes(conn, pid, card.themes)

            # .siq (опционально)
            if download_siq and card.sibrowser_id:
                cb(done, max_new, f"Скачиваю .siq: {card.name}")
                path = siq.download_siq(session, card.sibrowser_id, card.name,
                                        should_stop=stop)
                if path:
                    try:
                        themes_siq, questions = siq.parse_siq(path, pid)
                        if themes_siq:
                            db.replace_themes(conn, pid, themes_siq)
                        db.replace_questions(conn, pid, questions)
                        db.mark_siq(conn, pid, str(path))
                        summary["with_siq"] += 1
                    except Exception:
                        db.mark_siq(conn, pid, None)

            db.set_stats(conn, pid, stats)   # после вопросов — заполнит постатейную
            if stats:
                summary["with_stats"] += 1
            else:
                summary["no_stats"] += 1

            conn.commit()
            if on_new_package:
                try:
                    on_new_package(pid)
                except Exception:
                    pass
            summary["new"] += 1
            done += 1
            rate = f" — завершено {s['rate']*100:.0f}%" if s["rate"] is not None else ""
            cat_note = ""
            if category_min_pct > 0:
                pct = sibrowser._category_pct(card, category_slug)
                if pct is not None:
                    cat_note = f" · тема {pct}%"
            cb(done, max_new, f"[{done}/{max_new}] {card.name}{rate}{cat_note}")
            stats_api.throttle()
            if done >= max_new:
                # Настоящая проверка «набрали нужное количество» — здесь, а не в
                # sibrowser.iter_cards: там курсор просто выдаёт кандидатов, часть
                # которых мы только что могли отсеять (мин. игр/чёрный список) —
                # если бы генератор считал «выдали N — хватит», при отсеве часть
                # запросов оставалась бы недобрана (баг: искали 50, находили 16).
                break

        summary["skipped_existing"] = before
        last_card = page_state.get("last_card")
        if last_card is not None:
            summary["last_date"] = last_card.date_published
            summary["last_name"] = last_card.name
        summary["last_page"] = page_state.get("last_page", start_page)

    return summary


def collect_author(author: str, download_siq: bool = False,
                   on_new_package: Callable[[int], None] | None = None,
                   progress_cb: ProgressCB | None = None,
                   should_stop: Callable[[], bool] | None = None) -> dict:
    """Собирает ВСЕ паки указанного автора со страницы /authors/<author>.

    Обновляет уже собранные (upsert по названию), добавляет новые.

    БЕЗ author_blacklist: вызов этой функции — явный, целевой запрос «собери
    мне паки конкретно этого автора», и чёрный список (нужен, чтобы ФОНОВЫЙ
    автосбор — collect()/collect_steam_workshop() — сам пропускал неугодных
    авторов) тут же его вместо этого молча блокировал бы — весь результат
    уходил в отсеянные, а «новых: 0» выглядело как будто сбор вообще не работает.
    """
    cb = progress_cb or _noop
    stop = should_stop or _never_stop
    db.init_db()
    session = sibrowser.make_session()
    summary = {"new": 0, "with_stats": 0, "with_siq": 0, "no_stats": 0}
    cards = list(sibrowser.iter_author_cards(
        session, author, progress_cb=lambda m: cb(0, 1, m), should_stop=stop))
    total = len(cards) or 1
    with db.connect() as conn:
        for i, card in enumerate(cards, 1):
            if stop():
                break
            stats = stats_api.get_package_stats(session, card.name, card.authors)
            pid = db.upsert_package(conn, card.as_package())
            db.replace_themes(conn, pid, card.themes)
            if download_siq and card.sibrowser_id:
                path = siq.download_siq(session, card.sibrowser_id, card.name,
                                        should_stop=stop)
                if path:
                    try:
                        themes_siq, questions = siq.parse_siq(path, pid)
                        if themes_siq:
                            db.replace_themes(conn, pid, themes_siq)
                        db.replace_questions(conn, pid, questions)
                        db.mark_siq(conn, pid, str(path))
                        summary["with_siq"] += 1
                    except Exception:
                        db.mark_siq(conn, pid, None)
            db.set_stats(conn, pid, stats)
            summary["new"] += 1
            summary["with_stats" if stats else "no_stats"] += 1
            conn.commit()
            if on_new_package:
                try:
                    on_new_package(pid)
                except Exception:
                    pass
            cb(i, total, f"[{i}/{total}] {card.name}")
            stats_api.throttle()
    return summary


def collect_steam_workshop(
    api_key: str,
    max_new: int = 50,
    min_subscriptions: int = 0,
    author_blacklist: set[str] | None = None,
    on_new_package: Callable[[int], None] | None = None,
    progress_cb: ProgressCB | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> dict:
    """Импортирует метаданные паков из Steam Workshop SIGame (app 3553500) через
    Steam Web API (steam_workshop.py). ТОЛЬКО метаданные — depot-файлы воркшопа
    не скачиваются (для этого нужен SteamCMD, отдельная задача). Импортированные
    паки помечаются source='steam' (sibrowser_id=None), кнопка «Скачать .siq» их
    автоматически пропускает (см. sigstats_tab.py::_bulk_download).

    Дедупликация — как и у sibrowser, по name_norm: пак с уже известным названием
    (собранный откуда угодно) не дублируется.
    """
    cb = progress_cb or _noop
    stop = should_stop or _never_stop
    db.init_db()
    session = steam_workshop.make_session()
    summary = {"new": 0, "with_stats": 0, "no_stats": 0, "skipped_existing": 0,
               "skipped_low_subs": 0, "skipped_blacklisted": 0}
    with db.connect() as conn:
        skip_norms = db.existing_name_norms(conn)
        before = len(skip_norms)
        done = 0
        for item in steam_workshop.iter_items(
            session, api_key, skip_norms=skip_norms,
            progress_cb=lambda m: cb(done, max_new, m), should_stop=stop,
        ):
            if stop():
                break
            if min_subscriptions > 0 and (item.subscriptions or 0) < min_subscriptions:
                summary["skipped_low_subs"] += 1
                continue
            if _is_blacklisted(item.authors, author_blacklist):
                summary["skipped_blacklisted"] += 1
                continue
            stats = stats_api.get_package_stats(session, item.name, item.authors)
            pid = db.upsert_package(conn, item.as_package())
            db.replace_themes(conn, pid, [])
            db.set_stats(conn, pid, stats)
            if stats:
                summary["with_stats"] += 1
            else:
                summary["no_stats"] += 1
            conn.commit()
            if on_new_package:
                try:
                    on_new_package(pid)
                except Exception:
                    pass
            summary["new"] += 1
            done += 1
            cb(done, max_new, f"[{done}/{max_new}] {item.name}")
            stats_api.throttle()
            if done >= max_new:
                break
        summary["skipped_existing"] = before
    return summary


def refresh_stats(only_missing: bool = True,
                  progress_cb: ProgressCB | None = None,
                  should_stop: Callable[[], bool] | None = None) -> dict:
    """Перезапрашивает статистику игр для УЖЕ собранных паков (без перескрейпа).

    Нужно, чтобы заполнить новые метрики (% попыток/правильных) у паков,
    собранных до их появления.
    only_missing=True — только те, где этих метрик ещё нет.
    """
    cb = progress_cb or _noop
    stop = should_stop or _never_stop
    db.init_db()
    session = sibrowser.make_session()
    summary = {"checked": 0, "updated": 0}
    with db.connect() as conn:
        where = " WHERE answer_rate IS NULL" if only_missing else ""
        rows = conn.execute(
            f"SELECT id, name, authors_json FROM packages{where}").fetchall()
        total = len(rows)
        for i, r in enumerate(rows, 1):
            if stop():
                break
            authors = json.loads(r["authors_json"] or "[]")
            stats = stats_api.get_package_stats(session, r["name"], authors)
            db.set_stats(conn, r["id"], stats)
            conn.commit()
            summary["checked"] += 1
            if stats:
                summary["updated"] += 1
            cb(i, total, f"[{i}/{total}] {r['name']}")
            stats_api.throttle()
    return summary


def recompute_durations(progress_cb: ProgressCB | None = None,
                        should_stop: Callable[[], bool] | None = None) -> dict:
    """Пересчитывает длительность для уже скачанных паков из локальных .siq.

    Не качает заново и не трогает статистику вопросов — только длительности.
    """
    from pathlib import Path
    cb = progress_cb or _noop
    stop = should_stop or _never_stop
    db.init_db()
    summary = {"checked": 0, "updated": 0}
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT id, name, siq_path FROM packages WHERE siq_downloaded=1"
        ).fetchall()
        total = len(rows)
        for i, r in enumerate(rows, 1):
            if stop():
                break
            summary["checked"] += 1
            cb(i, total, f"[{i}/{total}] {r['name']}")
            path = r["siq_path"]
            if not path or not Path(path).exists():
                continue
            try:
                _themes, questions = siq.parse_siq(Path(path), r["id"])
                db.set_durations(conn, r["id"], questions)
                conn.commit()
                summary["updated"] += 1
            except Exception:
                continue
    return summary


def download_one(package_id: int, sibrowser_id: str, name: str,
                 progress_cb=None, should_stop=None) -> bool:
    """Скачивает и разбирает .siq одного уже собранного пакета (для кнопки в UI).

    progress_cb(done_bytes, total_bytes) — прогресс именно СКАЧИВАНИЯ файла
    (разбор/статистика после него не покрываются), пробрасывается в download_siq.
    should_stop() — пробрасывается в download_siq, проверяется между чанками.
    """
    session = sibrowser.make_session()
    path = siq.download_siq(session, sibrowser_id, name, progress_cb=progress_cb,
                            should_stop=should_stop)
    if not path:
        return False
    with db.connect() as conn:
        try:
            themes_siq, questions = siq.parse_siq(path, package_id)
            if themes_siq:
                db.replace_themes(conn, package_id, themes_siq)
            db.replace_questions(conn, package_id, questions)
            db.mark_siq(conn, package_id, str(path))
            # переналожить постатейную статистику, если она уже есть
            row = conn.execute(
                "SELECT name, authors_json FROM packages WHERE id=?",
                (package_id,)).fetchone()
            if row:
                import json
                authors = json.loads(row["authors_json"] or "[]")
                stats = stats_api.get_package_stats(session, row["name"], authors)
                db.set_stats(conn, package_id, stats)
            conn.commit()
            return True
        except Exception:
            return False


def delete_siq(package_id: int) -> bool:
    """Удаляет скачанный .siq пакета и извлечённый из него медиаконтент, сбрасывая
    отметку siq_downloaded. Сам пакет и его статистика в БД остаются — удаляются
    только скачанные с диска файлы (кнопка «Удалить пак» в UI)."""
    import shutil
    from pathlib import Path
    with db.connect() as conn:
        row = conn.execute(
            "SELECT siq_path FROM packages WHERE id=?", (package_id,)).fetchone()
        siq_path = row["siq_path"] if row else None
        if siq_path:
            try:
                Path(siq_path).unlink(missing_ok=True)
            except Exception:
                pass
        media_dir = config.MEDIA_DIR / str(package_id)
        try:
            if media_dir.exists():
                shutil.rmtree(media_dir, ignore_errors=True)
        except Exception:
            pass
        db.mark_siq(conn, package_id, None)
        conn.commit()
    return True
