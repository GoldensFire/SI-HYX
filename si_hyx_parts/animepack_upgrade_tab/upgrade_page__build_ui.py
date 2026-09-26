# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_UpgradePage: _build_ui. Public namespace: animepack_upgrade_tab."""
from __future__ import annotations
import animepack_upgrade_tab as _api


def _build_ui(self):
    root = _api.QVBoxLayout(self)
    root.setContentsMargins(12, 12, 12, 12)
    root.setSpacing(10)

    body = _api.QHBoxLayout(); body.setSpacing(12)
    root.addLayout(body, 1)

    # ── Слева: что именно поменялось ──────────────────────────────────
    left = _api.QVBoxLayout(); left.setSpacing(6)
    self.table = _api.QTableWidget(0, len(self.TABLE_HEADERS))
    self.table.setHorizontalHeaderLabels(list(self.TABLE_HEADERS))
    self.table.verticalHeader().setVisible(False)
    self.table.setEditTriggers(_api.QAbstractItemView.EditTrigger.NoEditTriggers)
    self.table.setSelectionBehavior(
        _api.QAbstractItemView.SelectionBehavior.SelectRows)
    self.table.setAlternatingRowColors(False)
    self.table.setWordWrap(False)
    # Колонку двигаем горизонтальной полосой, а не режем: «Стало» стояло
    # Stretch и забирало ровно остаток ширины, из-за чего длинный текст
    # обрывался многоточием, а полосы прокрутки не появлялось вовсе —
    # прочитать правку было нечем. Теперь ширина колонок — по содержимому
    # (как в «Генерации аниме-пака»), а таблица прокручивается вбок.
    self.table.setHorizontalScrollMode(
        _api.QAbstractItemView.ScrollMode.ScrollPerPixel)
    self.table.setHorizontalScrollBarPolicy(
        _api.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    hh = self.table.horizontalHeader()
    hh.setSectionResizeMode(_api.QHeaderView.ResizeMode.ResizeToContents)
    # «Раунд» — руками: в его колонке начинается имя файла, растянутое на
    # три клетки, а объединённые клетки Qt меряет по-своему (см.
    # _fit_round_column).
    hh.setSectionResizeMode(1, _api.QHeaderView.ResizeMode.Interactive)
    hh.setStretchLastSection(False)
    hh.setMinimumSectionSize(24)
    hh.setDefaultAlignment(_api.Qt.AlignmentFlag.AlignCenter)
    # До запуска на месте таблицы стоит карточка выбранного пака: имя, автор
    # и темы. Таблица правок появляется там же, когда апгрейд закончится.
    self.left_stack = _api.QStackedWidget()
    self.left_stack.addWidget(self._build_pack_card())
    self.left_stack.addWidget(self.table)
    left.addWidget(self.left_stack, 1)
    body.addLayout(left, 1)

    self._build_settings_panel(body)
    self._apply_styles()
    self._fit_settings_width()
    self._refresh_siq_label()
    self._refresh_out_dir_label()

# ── карточка выбранного пака ──────────────────────────────────────────
def _build_pack_card(self) -> _api.QWidget:
    """Что за пак сейчас выбран: название крупно, автор и список тем.

        Стоит на месте таблицы правок до запуска — чтобы было видно, тот ли
        файл взяли, ещё до того, как что-то в нём поменяется."""
    box = _api.QScrollArea()
    box.setWidgetResizable(True)
    box.setObjectName("packcard")
    inner = _api.QWidget()
    v = _api.QVBoxLayout(inner)
    v.setContentsMargins(18, 16, 18, 16)
    v.setSpacing(8)

    self.lbl_pack_name = _api.QLabel()
    self.lbl_pack_name.setWordWrap(True)
    self.lbl_pack_name.setTextInteractionFlags(
        _api.Qt.TextInteractionFlag.TextSelectableByMouse)
    self.lbl_pack_name.setStyleSheet(
        f"color:{_api.C['text']}; font-size:24px; font-weight:800;")
    v.addWidget(self.lbl_pack_name)

    self.lbl_pack_author = _api.QLabel()
    self.lbl_pack_author.setWordWrap(True)
    self.lbl_pack_author.setStyleSheet(
        f"color:{_api.C['accent']}; font-size:14px;")
    v.addWidget(self.lbl_pack_author)

    self.lbl_pack_meta = _api.QLabel()
    self.lbl_pack_meta.setWordWrap(True)
    self.lbl_pack_meta.setStyleSheet(
        f"color:{_api.C['text3']}; font-size:12px;")
    v.addWidget(self.lbl_pack_meta)

    self.lbl_pack_themes = _api.QLabel()
    self.lbl_pack_themes.setWordWrap(True)
    self.lbl_pack_themes.setTextFormat(_api.Qt.TextFormat.RichText)
    self.lbl_pack_themes.setAlignment(_api.Qt.AlignmentFlag.AlignTop)
    self.lbl_pack_themes.setStyleSheet(
        f"color:{_api.C['text2']}; font-size:13px;")
    v.addWidget(self.lbl_pack_themes)
    v.addStretch(1)
    box.setWidget(inner)
    return box

@staticmethod
def _esc(text) -> str:
    return (str(text or "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))

def _show_pack_card(self):
    """Заполняет карточку по выбранному файлу и показывает её."""
    self.left_stack.setCurrentIndex(0)
    if not self._siq:
        self.lbl_pack_name.setText("Пак не выбран")
        self.lbl_pack_author.setText("")
        self.lbl_pack_meta.setText(
            "Нажмите «Выбрать .siq…» справа или перетащите файл сюда мышью.")
        self.lbl_pack_themes.setText("")
        return
    base = _api.os.path.splitext(_api.os.path.basename(self._siq))[0]
    try:
        info = _api.read_pack_info(self._siq)
    except Exception as e:  # noqa: BLE001 — битый файл тоже надо показать
        self.lbl_pack_name.setText(base)
        self.lbl_pack_author.setText("")
        self.lbl_pack_meta.setText(f"Пак не читается: {e}")
        self.lbl_pack_themes.setText("")
        return
    self.lbl_pack_name.setText(info.name or base)
    self.lbl_pack_author.setText(f"Автор: {info.author}" if info.author
                                 else "Автор не указан")
    bits = [f"{info.questions} вопрос(ов)", f"{len(info.themes)} тем"]
    if info.specials:
        bits.append(f"спецвопросов: {info.specials}")
    if info.date:
        bits.append(info.date)
    if info.version:
        bits.append(f"формат {info.version}")
    self.lbl_pack_meta.setText(" · ".join(bits))
    self.lbl_pack_themes.setText(self._themes_html(info))

def _themes_html(self, info) -> str:
    """Темы пака по раундам. Раунд подписывается, только если их несколько:
        у пака из одного раунда заголовок над списком лишний."""
    many = len(info.rounds) > 1
    out = []
    for rname, names in info.rounds:
        if many:
            out.append(f"<p style='margin:10px 0 2px 0; color:{_api.C['text3']};"
                       f" font-size:11px;'>{self._esc(rname).upper()}</p>")
        for name in names:
            out.append(f"<p style='margin:1px 0;'>• {self._esc(name)}</p>")
    return "".join(out) or "<p>Тем в паке нет.</p>"

def _lab(self, text):
    l = _api.QLabel(text)
    l.setStyleSheet(f"color:{_api.C['text2']}; font-size:12px;")
    l.setWordWrap(True)
    return l

def _hint(self, text):
    l = _api.QLabel(text)
    l.setStyleSheet(f"color:{_api.C['text3']}; font-size:11px;")
    l.setWordWrap(True)
    return l

def _build_settings_panel(self, body):
    # Правая колонка = прокручиваемые настройки + НЕподвижная полоса кнопок
    # под ними (как в «Генерации аниме-пака»): прокрутка настроек не должна
    # уносить кнопку запуска.
    self.right_col = _api.QWidget()
    col = _api.QVBoxLayout(self.right_col)
    col.setContentsMargins(0, 0, 0, 0)
    col.setSpacing(8)
    self.scroll_settings = scroll = _api.QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(_api.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    panel = _api.QWidget()
    pv = _api.QVBoxLayout(panel)
    pv.setContentsMargins(2, 2, 8, 2)
    pv.setSpacing(12)

    pv.addWidget(self._group_pack())
    pv.addWidget(self._group_specials())
    pv.addWidget(self._group_titles())
    pv.addWidget(self._group_repeats())
    pv.addWidget(self._group_merge())
    pv.addWidget(self._group_empty())
    pv.addWidget(self._group_images())
    pv.addWidget(self._group_audio())
    pv.addWidget(self._group_video())
    pv.addWidget(self._group_unused())

    self.btn_reset = _api.QPushButton("Сбросить настройки")
    self.btn_reset.setIcon(_api.get_icon('fa5s.undo'))
    self.btn_reset.clicked.connect(self.reset_settings)
    pv.addWidget(self.btn_reset)
    pv.addStretch(1)

    scroll.setWidget(panel)
    self._disable_wheel(panel)
    col.addWidget(scroll, 1)
    col.addWidget(self._build_actions())
    body.addWidget(self.right_col)

# ── группа «Пак» ──────────────────────────────────────────────────────
def _group_pack(self) -> _api.QGroupBox:
    grp = _api.QGroupBox("Пак")
    g = _api.QGridLayout(grp); g.setHorizontalSpacing(6); g.setVerticalSpacing(8)
    r = 0
    self.btn_pick = _api.QPushButton("Выбрать .siq…")
    self.btn_pick.setIcon(_api.get_icon('fa5s.file-import'))
    self.btn_pick.setToolTip("Пак, который надо доработать. Файл можно "
                             "просто перетащить мышью на вкладку.")
    self.btn_pick.clicked.connect(self._choose_siq)
    g.addWidget(self.btn_pick, r, 0, 1, 2)
    r += 1
    self.lbl_siq = self._hint("")
    g.addWidget(self.lbl_siq, r, 0, 1, 2)
    r += 1
    self.btn_out_dir = _api.QPushButton("Папка для результата…")
    self.btn_out_dir.setIcon(_api.get_icon('fa5s.folder'))
    self.btn_out_dir.clicked.connect(self._choose_out_dir)
    g.addWidget(self.btn_out_dir, r, 0, 1, 2)
    r += 1
    self.lbl_out_dir = self._hint("")
    g.addWidget(self.lbl_out_dir, r, 0, 1, 2)
    r += 1
    g.setColumnStretch(1, 1)
    return grp

# ── группа «Спецвопросы» ──────────────────────────────────────────────
def _group_specials(self) -> _api.QGroupBox:
    # Галочка в заголовке группы и есть выключатель функции: снятая гасит
    # всю группу разом.
    grp = _api.QGroupBox("Убрать спецвопросы")
    grp.setCheckable(True)
    grp.setChecked(True)
    grp.setToolTip(
        "Вопросы со ставкой, с секретом, для себя, для всех и для всех со "
        "ставкой становятся обычными: сам вопрос, ответы и цена остаются на "
        "месте, снимается только особый режим.\n"
        "Названия типов — те же, какими их зовёт SIQuester.\n"
        "Понимает оба формата: и старый v4 (<type name=\"cat\">), и v5 "
        "SIGame 7 (type=\"secret\" плюс параметры темы/цены/режима выбора).")
    self.grp_specials = grp
    g = _api.QGridLayout(grp); g.setHorizontalSpacing(6); g.setVerticalSpacing(8)
    r = 0
    self.chk_no_question = _api.QCheckBox("Трогать и «с секретом без вопроса»")
    self.chk_no_question.setToolTip(
        "«С секретом без вопроса» (secretNoQuestion) — это выдача денег "
        "сразу, самого вопроса в нём нет. Обычным он станет пустым, поэтому "
        "по умолчанию такие вопросы остаются как есть (о каждом пишется в "
        "отчёт).")
    g.addWidget(self.chk_no_question, r, 0, 1, 2)
    r += 1
    g.addWidget(self._hint(
        "Вопросы, у которых вообще нет содержимого, здесь пропускаются в "
        "любом случае: обычным делать нечего. Их убирает «Удалить пустые "
        "вопросы»."), r, 0, 1, 2)
    g.setColumnStretch(1, 1)
    return grp
