# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Панель «Обновить базу»: что в базе лежит и как обновить её по частям.

Кэш каталога Shikimori копится месяцами, а увидеть его было нечем: по какому
именно индексу тайтл попал в «десятку» и почему вопрос-персонаж вышел лёгким,
приходилось догадываться по готовому паку. Панель показывает базу таблицей — с
поиском и сортировкой по любой колонке.

Кнопок про базу было две («Обновить базу Shikimori» и «Что в базе…»), и
обновление шло одним куском на десятки минут. Теперь кнопка одна и открывает
эту панель, а обновляется каждая часть базы отдельно (просьба пользователя):
каталог аниме, каталог манги, узнаваемость франшиз и «хвосты» — то, что
копится генерациями по одному запросу. У каждого блока и у каждой строки есть
подсказка, как это посчиталось.

Считает панель в РАБОЧЕМ потоке: чтение базы с диска — четыре секунды, разбор
каталога книг — ещё три, и раньше на это время замирало всё окно. Пока идёт
счёт, вкладка так и говорит; таблица встаёт целиком и сразу.
"""
from __future__ import annotations

from PyQt6.QtCore import (
    QCoreApplication, QObject, QRunnable, QThreadPool, pyqtSignal,
)
from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QPushButton, QTabWidget, QVBoxLayout, QWidget,
)

import animepack_tab as api

from .db_part_blocks import build_blocks
from .manga_refresh_controls import MANGA_PARTS
from .db_table_view import Page, build_cells

TITLE_HEADERS = ("Место", "Название", "Тип", "Год", "Оценка", "База",
                 "В избранном", "Индекс", "Ур.", "Цена")
CHAR_HEADERS = ("Место", "Персонаж", "Тайтл", "Роль", "В избранном",
                "Ур. тайтла", "Цена")


def _fmt(number) -> str:
    return f"{int(round(float(number or 0))):,}".replace(",", " ")


class _JobSignals(QObject):
    done = pyqtSignal(int, object, object)
    failed = pyqtSignal(int, object, str)


class _Job(QRunnable):
    """Один счёт в рабочем потоке: чтение базы или разбор одной вкладки."""

    def __init__(self, age: int, task, work, signals: _JobSignals):
        super().__init__()
        self._age, self._task, self._work = age, task, work
        self._signals = signals

    def run(self):                           # noqa: D102 — имя из Qt
        try:
            result = self._work(self._age, self._task)
        except Exception as exc:  # noqa: BLE001 — окно не должно падать
            self._emit(self._signals.failed, str(exc))
            return
        self._emit(self._signals.done, result)

    def _emit(self, signal, payload) -> None:
        try:
            signal.emit(self._age, self._task, payload)
        except RuntimeError:     # pragma: no cover — панель уже закрыли
            pass


class DbTableDialog(QDialog):
    """Панель базы: блоки частей сверху, таблицы разбора снизу."""

    def __init__(self, cache, tab=None, parent=None):
        # Владельцем окна может быть только виджет: вкладка им и является, но
        # в проверках на её месте стоит заглушка.
        owner = parent if parent is not None else tab
        super().__init__(owner if isinstance(owner, QWidget) else None)
        self._cache = cache
        self._tab = tab
        self._age = 0                     # счёт этого поколения, старые — вон
        self._counts: dict = {}
        self._title_rows: dict = {}
        self._filled: set = set()
        self._pending: set = set()
        self._filter_kinds = {"anime": None, "manga": None}
        self.setWindowTitle("База Shikimori: что в ней и как её обновить")
        self.resize(1050, 700)
        # Один поток на всю панель: разбор вкладок ходит по одному и тому же
        # кэшу, и считать их разом было бы гонкой без всякой выгоды.
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._signals = _JobSignals(self)
        self._signals.done.connect(self._job_done)
        self._signals.failed.connect(self._job_failed)
        layout = QVBoxLayout(self)
        self.blocks = build_blocks(self._on_part_action, self)
        blocks_row = QHBoxLayout()
        blocks_row.setSpacing(8)
        for block in self.blocks.values():
            blocks_row.addWidget(block, 1)
        layout.addLayout(blocks_row)
        filter_row = QHBoxLayout()
        filter_row.addStretch()
        self.btn_filters = QPushButton("Фильтры…")
        self.btn_filters.clicked.connect(self._open_filters)
        filter_row.addWidget(self.btn_filters)
        layout.addLayout(filter_row)
        self.tabs = QTabWidget()
        from . import db_rows
        self.anime = Page(TITLE_HEADERS, db_rows.explain_title,
                          hierarchical=True, refresh_title=self._refresh_title,
                          refresh_franchise=self._refresh_franchise)
        self.manga = Page(TITLE_HEADERS, db_rows.explain_title,
                          hierarchical=True, refresh_title=self._refresh_title,
                          refresh_franchise=self._refresh_franchise)
        self.chars = Page(CHAR_HEADERS, db_rows.explain_character,
                          refresh_title=self._refresh_character)
        self.tabs.addTab(self.anime, "Аниме")
        self.tabs.addTab(self.manga, "Манга")
        self.tabs.addTab(self.chars, "Персонажи")
        # Вкладку наполняем только когда её открыли: карточек в базе под
        # шестьдесят тысяч, и сборка всех трёх таблиц разом стоила бы секунд
        # десять на каждом открытии панели.
        self.tabs.currentChanged.connect(lambda *_: self._fill_current())
        layout.addWidget(self.tabs, 1)
        row = QHBoxLayout()
        self.btn_all = QPushButton("Обновить всю базу")
        self.btn_all.setToolTip(
            "Каталог аниме, каталог манги, популярность ReManga и MangaLib "
            "и узнаваемость франшиз подряд — то "
            "же самое, что делала прежняя кнопка «Обновить базу Shikimori». "
            "Идти может десятки минут; остановить можно там же, а набранное "
            "останется в базе.\n"
            "«В избранном» и «хвосты» этим не трогаются: каждое такое число "
            "стоит отдельного запроса к странице тайтла, и ни терять их "
            "вместе с каталогом, ни собирать заодно с ним незачем — у них "
            "свои кнопки.")
        self.btn_all.clicked.connect(lambda: self._on_part_action("all"))
        row.addWidget(self.btn_all)
        row.addStretch(1)
        refresh = QPushButton("Перечитать с диска")
        refresh.setToolTip("Перечитать базу с диска и пересчитать таблицы.")
        refresh.clicked.connect(self.refresh)
        close = QPushButton("Закрыть")
        close.clicked.connect(self.close)
        row.addWidget(refresh)
        row.addWidget(close)
        layout.addLayout(row)
        self.refresh()

    # ── обновление по частям ──────────────────────────────────────────────
    def _on_part_action(self, part: str) -> None:
        """Кнопка блока: запустить обновление этой части или остановить его."""
        if self._tab is None:
            return
        # Кнопка обещает обновить ВСЮ базу независимо от текущего состава
        # пака. ``None`` здесь оставляло мангу нетронутой, когда её доля в
        # настройках была нулевой, хотя подпись и подсказка говорили обратное.
        parts = (("anime", *MANGA_PARTS, "franchises") if part == "all" else
                 MANGA_PARTS if part == "manga_all" else (part,))
        self._tab._refresh_db(parts)
        self.sync_state()

    def sync_state(self) -> None:
        """Подписи блоков под то, что сейчас делает база."""
        running = getattr(self._tab, "_db_task", None) is not None
        active = set(getattr(self._tab, "_db_parts", ()) or ())
        for part, block in self.blocks.items():
            row = self._counts.get(part) or {}
            collecting = part in active or (part == "manga" and bool(active & set(MANGA_PARTS)))
            block.set_state(row.get("count", 0), row.get("fetched", 0.0),
                            running and collecting, running)
        self.btn_all.setEnabled(not running)

    def refresh(self):
        """Перечитать базу с диска и пересобрать таблицы."""
        self._age += 1
        self._counts = {}
        self._title_rows = {}             # разбор каталога, посчитанный разок
        self._filled = set()              # какие вкладки уже наполнены
        self._pending = set()
        for page in (self.anime, self.manga, self.chars):
            page.set_busy("Читаю базу…")
        self.sync_state()
        self._start(("counts", self._filters_snapshot()))
        self._fill_current()

    def closeEvent(self, event):             # noqa: N802 — имя из Qt
        """Закрыли окно — считать дальше некому: старые ответы не нужны."""
        self._age += 1
        super().closeEvent(event)

    def flush(self, timeout_ms: int = 60000) -> None:
        """Дождаться всех расчётов панели (тесты и «покажи прямо сейчас»)."""
        self._pool.waitForDone(int(timeout_ms))
        QCoreApplication.processEvents()

    # ── счёт в рабочем потоке ─────────────────────────────────────────────
    def _start(self, task) -> None:
        self._pool.start(_Job(self._age, task, self._work, self._signals))

    def _work(self, age: int, task):
        """Рабочий поток: ни одного виджета, только разбор кэша в строки.

        Пока считалось, панель могли перечитать заново — тогда бросаем:
        разобранные строки легли бы в уже чужой набор."""
        if age != self._age:
            return None
        # Сборщик мусора на время счёта выключен: строк таблицы десятки
        # тысяч, и его проходы по ним шли очередью по 0.1–0.3 с — главный поток
        # за это время не получал GIL ни разу, и окно «не отвечало».
        import gc
        was_on = gc.isenabled()
        gc.disable()
        try:
            if task[0] == "counts":
                return self._read_counts(task[1])
            if task[0] == "title":
                return self._read_title(task[1], task[2])
            if task[0] == "franchise":
                from .db_refresh import read_franchise
                return read_franchise(self._cache, task[1], task[2])
            if task[0] == "character":
                return self._read_character(*task[1:])
            return self._read_page(task[1], task[2])
        finally:
            if was_on:
                gc.enable()

    def _job_done(self, age: int, task, result) -> None:
        if age != self._age:
            return
        if task[0] == "counts":
            self._counts = result or {}
            self.sync_state()
            return
        if task[0] in ("title", "franchise"):
            self._pending.discard(task[:3])
            if result:
                # Карточка могла сменить франшизу, а её новый индекс влияет и
                # на соседние части. Забываем только рассчитанные строки, но
                # не очищаем видимые таблицы и не перечитываем счётчики базы.
                # Текущую вкладку заменим с сохранением прокрутки, выделения и
                # раскрытых веток; остальные лениво пересчитаются при открытии.
                self._title_rows = {}
                self._filled.difference_update(
                    (self.anime, self.manga, self.chars))
                target = task[1]
                self._pending.add(target)
                self._start(("page", target, self._filters_snapshot(), True))
            return
        if task[0] == "character":
            self._pending.discard(task)
            if result is not None:
                self._filled.discard(self.chars)
                self._pending.add("chars")
                self._start(("page", "chars", self._filters_snapshot(), True))
            return
        self._pending.discard(task[1])
        page = self._page_for(task[1])
        if page is None or not result:
            return
        rows, texts, sorts, hay, sort_by, *tail = result
        preserve = len(task) > 3 and bool(task[3])
        page.set_data(rows, texts, sorts, hay, sort_by,
                      tail[0] if tail else None, preserve_state=preserve)
        self._filled.add(page)

    def _job_failed(self, age: int, task, error: str) -> None:
        if age != self._age:
            return
        if task[0] == "counts":
            return
        if task[0] in ("title", "franchise", "character"):
            if task[0] == "character":
                self._pending.discard(task)
                page = self.chars
            else:
                self._pending.discard(task[:3])
                page = self._page_for(task[1])
            if page is not None:
                what = {"character": "Персонаж",
                        "franchise": "Франшиза"}.get(task[0], "Тайтл")
                page.count.setText(f"{what} не обновился: {error}")
            return
        self._pending.discard(task[1])
        page = self._page_for(task[1])
        if page is not None:
            if len(task) > 3 and task[3]:
                page.count.setText(f"Таблица не обновилась: {error}")
                return
            page.set_busy(f"Не прочиталось: {error}")

    def _page_for(self, target: str):
        return {"anime": self.anime, "manga": self.manga,
                "chars": self.chars}.get(target)

    def _fill_current(self) -> None:
        """Поставить открытую вкладку в очередь, если её ещё не наполняли."""
        page = self.tabs.currentWidget()
        if page is None or page in self._filled:
            return
        target = ("chars" if page is self.chars
                  else "manga" if page is self.manga else "anime")
        if target in self._pending:
            return
        self._pending.add(target)
        page.set_busy("Собираю таблицу…")
        self._start(("page", target, self._filters_snapshot()))

    # ── разбор кэша (всё это идёт в рабочем потоке) ───────────────────────
    def _read_counts(self, kinds) -> dict:
        self._cache.reload()              # базу собирает другой экземпляр кэша
        # Один рабочий поток: прежний расчёт уже завершился. Он мог вернуть
        # старые строки в кэш после refresh(), пока ещё читал прежнюю базу.
        self._title_rows = {}
        # Блоки показывают всю базу; выбранные фильтры относятся к таблицам.
        return dict(self._cache.part_counts())

    def _read_page(self, target: str, kinds):
        from . import db_rows
        if target == "chars":
            levels = db_rows.title_levels(self._rows_for("anime", kinds),
                                          "anime")
            levels.update(db_rows.title_levels(
                self._rows_for("manga", kinds), "manga"))
            rows = db_rows.character_rows(self._cache, levels)
            texts, sorts, hay = build_cells(rows, _char_cells)
            return rows, texts, sorts, hay, CHAR_HEADERS.index("В избранном")
        rows = self._rows_for(target, kinds)
        from .db_title_tree import group_title_rows
        rows, parents = group_title_rows(rows, self._cache.franchise)
        texts, sorts, hay = build_cells(rows, _title_cells)
        return (rows, texts, sorts, hay, TITLE_HEADERS.index("Индекс"),
                parents)

    def _refresh_title(self, row: dict) -> None:
        """Поставить точечное обновление карточки в рабочий поток."""
        target = "manga" if row.get("media") == "manga" else "anime"
        try:
            ident = int(row.get("id") or 0)
        except (TypeError, ValueError):
            ident = 0
        if not ident:
            return
        key = ("title", target, ident)
        if key in self._pending:
            return
        self._pending.add(key)
        page = self._page_for(target)
        if page is not None:
            page.count.setText(f"Обновляю «{row.get('title') or ident}»…")
        self._start(key)

    def _refresh_character(self, row: dict) -> None:
        """Точечно перечитать число «в избранном» у персонажа."""
        try:
            ident = int(row.get("id") or 0)
        except (TypeError, ValueError):
            ident = 0
        if not ident:
            return
        target = str(row.get("owner_media") or "anime")
        key = ("character", ident, target,
               int(row.get("owner_id") or 0), int(row.get("owner_mal") or 0))
        if key in self._pending:
            return
        self._pending.add(key)
        self.chars.count.setText(
            f"Обновляю «{row.get('name') or ident}»…")
        self._start(key)

    def _read_title(self, target: str, ident: int) -> str:
        """Перечитать одну карточку, её избранное и части франшизы."""
        from .db_refresh import read_title
        return read_title(self._cache, target, ident)

    def _refresh_franchise(self, row: dict) -> None:
        """ПКМ по франшизе: перечитать все её части, что лежат в базе."""
        target = "manga" if row.get("media") == "manga" else "anime"
        franchise = str(row.get("franchise") or "").strip()
        if not franchise:
            return
        key = ("franchise", target, franchise)
        if key in self._pending:
            return
        self._pending.add(key)
        page = self._page_for(target)
        if page is not None:
            page.count.setText(f"Обновляю франшизу «{franchise}»…")
        self._start(key)

    def _read_character(self, ident: int, target: str,
                        owner_id: int, owner_mal: int) -> int:
        """Обновить карточку персонажа, его роль и число избранного."""
        from animepack_api import ShikimoriApi
        shiki = ShikimoriApi()
        if owner_id and owner_mal:
            groups = shiki.characters_by_anime_ids([owner_id], target=target)
            people = groups.get(owner_mal)
            if people is not None:
                self._cache.remember_memo(
                    "characters", f"{target}:{owner_mal}", people)
        value = int(shiki.character_favorites(ident))
        if value < 0:
            raise RuntimeError("Shikimori не вернул число избранного")
        self._cache.remember_memo("character_favorites", ident, value)
        self._cache.save()
        return value

    def _rows_for(self, target: str, kinds) -> list:
        """Разбор каталога с оглядкой на уже посчитанное: тайтлы нужны и
        вкладке персонажей — их уровень берётся у их же тайтлов.

        Аниме и книги используют собственные независимые фильтры типов."""
        if target not in self._title_rows:
            from . import db_rows
            self._title_rows[target] = db_rows.title_rows(
                self._cache, target, kinds.get(target) if kinds else None)
        return self._title_rows[target]

    def _filters_snapshot(self):
        """Снимок собственных фильтров для расчёта таблиц в рабочем потоке."""
        return dict(self._filter_kinds)

    def _open_filters(self):
        from .db_filters import DbFiltersDialog
        dialog = DbFiltersDialog(self._filter_kinds, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._set_filters(dialog.values())

    def _set_filters(self, filters):
        self._filter_kinds = dict(filters)
        active = any(value is not None for value in filters.values())
        self.btn_filters.setText("Фильтры (включены)…" if active else "Фильтры…")
        self.refresh()


def _kind_label(kind: str) -> str:
    """Тип тайтла по-русски. Типы книг живут в своём словаре: «manga»,
    «light_novel» и «manhwa» в KIND_LABELS не значатся."""
    kind = str(kind or "")
    return (api.KIND_LABELS.get(kind)
            or api.MANGA_KIND_LABELS.get(kind) or kind)


def _title_cells(row):
    """Ячейки строки тайтла: (подпись, значение для сортировки)."""
    fav = int(row["favorites"])
    kind = "франшиза" if row.get("_franchise_header") else _kind_label(
        row["kind"])
    return (
        (str(row["place"]), row["place"]),
        (row["title"], None),
        (kind, None),
        (str(row["year"] or ""), row["year"]),
        (f"{row['score']:.2f}" if row["score"] else "", row["score"]),
        (_fmt(row["base"]), row["base"]),
        # −1 значит «не спрашивали»: ноль был бы неправдой.
        ("—" if fav < 0 else _fmt(fav), fav),
        (_fmt(row["index"]), row["index"]),
        (str(row["level"]), row["level"]),
        (str(row["price"]), row["price"]),
    )


def _char_cells(row):
    fav = int(row["favorites"])
    return (
        (str(row["place"]), row["place"]),
        (row["name"], None),
        (row["title"], None),
        (row["role"], None),
        ("—" if fav < 0 else _fmt(fav), fav),
        (str(row["title_level"]), row["title_level"]),
        (str(row["price"]), row["price"]),
    )


def open_db_table(tab):
    dialog = getattr(tab, "_db_table_dialog", None)
    if dialog is None:
        from animepack import ShikimoriDbCache
        dialog = DbTableDialog(ShikimoriDbCache(), tab)
        tab._db_table_dialog = dialog
    else:
        dialog.refresh()
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()
    return dialog
