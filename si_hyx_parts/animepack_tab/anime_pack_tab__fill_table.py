# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""AnimePackTab: _fill_table. Public namespace: animepack_tab."""
from __future__ import annotations
import animepack_tab as _api


def _fill_table(self, songs: list):
    settings = self.collect()
    per_round = max(1, settings.themes)
    # Пока идёт заполнение, сортировку выключаем: иначе строки едут
    # прямо под руками и ячейки попадают не в свои ряды.
    self.table.setSortingEnabled(False)
    self.table.setRowCount(0)
    # Раскладку (темы, порядок и цены) считает сам генератор — таблица и пак
    # обязаны совпадать до вопроса.
    row = 0
    for theme_no, theme in enumerate(_api.arrange_questions(songs, settings)):
        round_no = theme_no // per_round
        for cand in theme:
            self.table.insertRow(row)
            title_text = cand.title_ru
            if cand.is_character:
                # Имя персонажа — часть ОТВЕТА, а не название песни: в
                # колонке «Песня» ему было не место.
                song_text, difficulty = "—", ""
                if cand.char_name:
                    title_text = f"{cand.title_ru} — 『{cand.char_name}』"
            elif cand.is_silent:
                # Кадр, пиксели, анаграмма, сюжет — песни в вопросе нет,
                # даже если карточка песни осталась от отбора.
                song_text, difficulty = "—", ""
            else:
                song_text = (f"{cand.song.get('songArtist') or ''} — "
                             f"{cand.song.get('songName') or ''}")
                difficulty = f"{cand.difficulty:.0f}"
            kind_text = _api.KIND_TITLES.get(cand.kind, cand.kind)
            if cand.is_pixel and cand.frame_effect:
                from frame_reveal import EFFECT_LABELS
                kind_text = EFFECT_LABELS.get(cand.frame_effect, kind_text)
            if cand.kind == _api.VIDEO_KIND and not cand.has_video:
                # Ролика для этой песни не нашлось — вопрос вышел обычным.
                kind_text = _api.KIND_TITLES.get(cand.base_kind, kind_text)
            if cand.entrance_effect:
                from image_entrance import EFFECT_LABELS as ENTRANCE_LABELS
                kind_text += " · " + ENTRANCE_LABELS[cand.entrance_effect]
            cells = [
                _api._NumItem(str(row + 1), row + 1),
                _api._NumItem(str(round_no + 1), round_no + 1),
                _api._NumItem(str(theme_no % per_round + 1), theme_no % per_round + 1),
                _api._NumItem(str(cand.price), cand.price),
                _api.QTableWidgetItem(title_text),
                _api.QTableWidgetItem(song_text),
                _api.QTableWidgetItem(kind_text),
                _api._NumItem(difficulty, cand.difficulty),
                _api._NumItem(f"{cand.index:,.0f}".replace(",", " "), cand.index),
                _api._NumItem(str(cand.level), cand.level),
            ]
            # Из чего сложился «Индекс» — подсказкой прямо на ячейке
            # (просьба пользователя). Текст кладём в саму ячейку: окно
            # состава пака копирует ячейки через clone(), и подсказка
            # уезжает туда вместе с числом.
            from .index_tooltip import (PRICE_ROLE, TIP_ROLE, build_price_text,
                                        build_text)
            cells[8].setData(TIP_ROLE, build_text(cand))
            # То же самое для «Цены»: из каких надбавок и множителей она
            # сложилась (просьба пользователя).
            cells[3].setData(PRICE_ROLE, build_price_text(cand))
            for col, item in enumerate(cells):
                if col in self.TABLE_NUM_COLS:
                    item.setTextAlignment(_api.Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row, col, item)
            row += 1
    # Заново показываем пак в его собственном порядке: сортировка «по №»
    # и есть порядок вопросов в файле.
    self.table.horizontalHeader().setSortIndicator(0, _api.Qt.SortOrder.AscendingOrder)
    self.table.setSortingEnabled(True)
    # setSortingEnabled(True) сам включает родную стрелку — гасим её снова
    # (иначе колонки опять раздуются на 28 px каждая).
    self.table.horizontalHeader().setSortIndicatorShown(False)
    self._update_table_hint()
    # Таблица по умолчанию спрятана, поэтому кнопка сама говорит, что в ней
    # уже есть что смотреть (просьба пользователя: «после генерации кнопкой
    # посмотреть, что там выбрано»).
    button = getattr(self, "btn_table", None)
    if button is not None:
        button.setEnabled(self.table.rowCount() > 0)
        button.setText(f"Показать таблицу ({self.table.rowCount()})")
    dialog = getattr(self, "_table_dialog", None)
    if dialog is not None and dialog.isVisible():
        dialog.refresh(self.table, self.TABLE_HEADERS)

def _open_result(self):
    if not self._last_pack:
        return
    try:
        from utils import reveal_in_explorer
        reveal_in_explorer(self._last_pack)
    except Exception as e:  # noqa: BLE001
        _api.msgbox_critical(self, "Не открылось", str(e))

# ── завершение работы вкладки ─────────────────────────────────────────
@staticmethod
def _detach(task):
    """Просит задачу остановиться и отвязывает её сигналы от вкладки.

        Дождаться QRunnable мы не можем: генерация пака идёт минутами, а
        cleanup() зовут при закрытии окна. Зато можно сделать так, чтобы поток
        доработал молча — иначе сигнал прилетает в виджет, которого уже нет."""
    if task is None:
        return
    try:
        task.stop()
    except Exception:
        pass
    for name in ("log", "progress", "finished", "failed"):
        sig = getattr(task.signals, name, None)
        if sig is None:
            continue
        try:
            sig.disconnect()
        except TypeError:
            pass               # к этому сигналу никто и не подключался

def cleanup(self):
    self._closing = True
    timer = getattr(self, "_template_notice_timer", None)
    if timer is not None:
        timer.stop()
        self.template_notice.hide()
    preview = getattr(self, "entrance_preview", None)
    if preview is not None:
        preview.timer.stop()
    if getattr(self, "_gemini_quota_timer", None) is not None:
        self._gemini_quota_timer.stop()
    if getattr(self, "_ai_quota_timer", None) is not None:
        self._ai_quota_timer.stop()
    if getattr(self, "_gemini_models_timer", None) is not None:
        self._gemini_models_timer.stop()
    # Отложенная загрузка жанров: таймер мог ещё не сработать.
    if self._genres_timer is not None:
        self._genres_timer.stop()
    self._detach(self._task)
    self._task = None
    self._detach(self._db_task)
    self._db_task = None
    self._detach(self._genres_task)
    self._genres_task = None
    for name in ("_table_dialog", "_cache_dialog", "_db_table_dialog",
                 "_franchise_list_dialog",
                 "_exact_list_dialog"):
        dialog = getattr(self, name, None)
        if dialog is not None:
            try:
                dialog.close()
            except Exception:
                pass
