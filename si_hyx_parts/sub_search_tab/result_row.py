# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Строка результата «Поиска по сабам»: постер, названия с кнопками копирования,
уровень, индекс популярности и найденная реплика с серией и временем."""
import html

import sub_search_tab as _api


def level_color(level: int) -> str:
    """Цвет плашки уровня: лёгкие — зелёные, средние — жёлтые, сложные — красные."""
    if not level:
        return _api.C["text3"]
    if level <= 3:
        return _api.C["green"]
    if level <= 7:
        return _api.C["yellow"]
    return _api.C["red"]


def _fmt_int(n) -> str:
    return f"{int(round(float(n or 0))):,}".replace(",", " ")


def _highlight(text: str, matched: str) -> str:
    """Реплика в HTML: найденные куски фразы — жирным акцентом."""
    out = html.escape(text)
    for piece in [p for p in (matched or "").split(" || ") if p.strip()]:
        esc = html.escape(piece)
        pos = out.find(esc)
        if pos < 0:
            pos = out.lower().find(esc.lower())
        if pos >= 0:
            out = (out[:pos] + f"<b style='color:{_api.C['accent']}'>"
                   + out[pos:pos + len(esc)] + "</b>" + out[pos + len(esc):])
    return out.replace(" / ", "<br>").replace(" || ", "<br>")


def _match_line(m: dict) -> str:
    parts = []
    if m.get("episode"):
        ep = str(m["episode"])
        parts.append(f"Серия {ep}" if ep[:1].isdigit() else ep)
    parts.append(str(m.get("timecode") or "")[:8])
    parts.append(_api.engine.SOURCE_LABELS.get(m.get("source"), m.get("source") or ""))
    if m.get("file"):
        parts.append(str(m["file"]))
    return "  ·  ".join(p for p in parts if p)


class ResultRow(_api.QFrame):
    """Карточка одного найденного тайтла."""

    # Ссылка на Re:ANIME готова (кнопка, ссылка; "" — тайтла на сайте нет).
    watch_ready = _api.pyqtSignal(object, str)

    def __init__(self, hit, rank: int, parent=None):
        super().__init__(parent)
        self.hit = hit
        self.watch_ready.connect(self._on_watch_ready)
        self.setObjectName("subsearch_row")
        a = hit.title.anime
        self.anime = a
        row = _api.QHBoxLayout(self)
        row.setContentsMargins(8, 8, 8, 8)
        row.setSpacing(10)

        num = _api.QLabel(str(rank))
        num.setFixedWidth(22)
        num.setAlignment(_api.Qt.AlignmentFlag.AlignRight | _api.Qt.AlignmentFlag.AlignTop)
        num.setStyleSheet(f"color:{_api.C['text3']}; font-size:13px; font-weight:700; "
                          "background:transparent;")
        row.addWidget(num)

        self.poster = _api.QLabel()
        self.poster.setFixedSize(_api.POSTER_W, _api.POSTER_H)
        self.poster.setStyleSheet(f"background:{_api.C['surface3']}; border-radius:4px;")
        self.poster.setAlignment(_api.Qt.AlignmentFlag.AlignCenter)
        row.addWidget(self.poster, 0, _api.Qt.AlignmentFlag.AlignTop)

        col = _api.QVBoxLayout()
        col.setSpacing(3)
        row.addLayout(col, 1)

        # Название + копировать + открыть на Shikimori.
        line1 = _api.QHBoxLayout(); line1.setSpacing(4)
        title = _api.QLabel(a.title)
        title.setWordWrap(True)
        title.setTextInteractionFlags(_api.Qt.TextInteractionFlag.TextSelectableByMouse)
        title.setStyleSheet(f"color:{_api.C['text']}; font-size:14px; font-weight:700; "
                            "background:transparent;")
        line1.addWidget(title, 1)
        line1.addWidget(self._copy_button(a.title, "Копировать название"))
        if a.url:
            btn = self._tool_button("fa5s.external-link-alt", "Открыть на Shikimori")
            btn.clicked.connect(lambda: self.open_url(a.url))
            line1.addWidget(btn)
        col.addLayout(line1)

        if a.name and a.name != a.title:
            line2 = _api.QHBoxLayout(); line2.setSpacing(4)
            orig = _api.QLabel(a.name)
            orig.setWordWrap(True)
            orig.setTextInteractionFlags(_api.Qt.TextInteractionFlag.TextSelectableByMouse)
            orig.setStyleSheet(f"color:{_api.C['text2']}; font-size:12px; background:transparent;")
            line2.addWidget(orig, 1)
            line2.addWidget(self._copy_button(a.name, "Копировать оригинальное название"))
            col.addLayout(line2)

        # Плашки: уровень, индекс популярности, тип/год/серии.
        chips = _api.QHBoxLayout(); chips.setSpacing(6)
        level = int(hit.level or hit.title.level or 0)
        lvl = _api.QLabel(f"Уровень {level}" if level else "Уровень ?")
        color = level_color(level)
        lvl.setStyleSheet(f"color:#11111b; background:{color}; border-radius:4px; "
                          "padding:1px 6px; font-size:11px; font-weight:700;")
        lvl.setToolTip("Уровень сложности из базы ShikimoriHYX / генератора пака: "
                       "1 — самый узнаваемый тайтл.")
        chips.addWidget(lvl)
        if hit.index:
            idx = _api.QLabel()
            idx.setText(f"<span>{_fmt_int(hit.index)}</span>")
            idx.setStyleSheet(f"color:{_api.C['yellow']}; font-size:12px; font-weight:600; "
                              "background:transparent;")
            icon = _api.QLabel()
            icon.setPixmap(_api.get_icon("fa5s.fire-alt", color=_api.C["yellow"]).pixmap(
                _api.QSize(13, 13)))
            tip = self._index_tip(hit)
            for w in (icon, idx):
                w.setToolTip(tip)
            chips.addWidget(icon)
            chips.addWidget(idx)
        meta = []
        try:
            from shikimori_api import kind_label
            meta.append(kind_label("anime", a.kind))
        except Exception:  # noqa: BLE001
            meta.append(a.kind)
        if a.year:
            meta.append(str(a.year))
        if a.episodes:
            meta.append(f"{a.episodes} эп.")
        if a.score:
            meta.append(f"★ {a.score:.2f}")
        info = _api.QLabel("  ·  ".join(m for m in meta if m))
        info.setStyleSheet(f"color:{_api.C['text2']}; font-size:11px; background:transparent;")
        chips.addWidget(info)
        chips.addStretch(1)
        col.addLayout(chips)

        # Найденная реплика (первая) и остальные по кнопке.
        self._match_box = _api.QVBoxLayout()
        self._match_box.setSpacing(4)
        col.addLayout(self._match_box)
        self._extra = []
        for n, m in enumerate(hit.matches):
            w = self._match_widget(m)
            self._match_box.addWidget(w)
            if n:
                w.setVisible(False)
                self._extra.append(w)
        if self._extra:
            self.btn_more = _api.QPushButton(f"Ещё совпадений: {len(self._extra)}")
            self.btn_more.setObjectName("subsearch_more")
            self.btn_more.setCheckable(True)
            self.btn_more.toggled.connect(self._toggle_more)
            col.addWidget(self.btn_more, 0, _api.Qt.AlignmentFlag.AlignLeft)
        col.addStretch(1)

    # ── кнопки ────────────────────────────────────────────────────────────────
    @staticmethod
    def _tool_button(icon: str, tip: str):
        b = _api.QToolButton()
        b.setIcon(_api.get_icon(icon, color=_api.C["text2"]))
        b.setIconSize(_api.QSize(14, 14))
        b.setAutoRaise(True)
        b.setToolTip(tip)
        b.setFixedSize(24, 24)
        return b

    def _copy_button(self, text: str, tip: str):
        b = self._tool_button("fa5s.copy", tip)

        def copy():
            _api.QGuiApplication.clipboard().setText(text)
            b.setIcon(_api.get_icon("fa5s.check", color=_api.C["green"]))
            _api.QTimer.singleShot(_api.COPY_FEEDBACK_MS, lambda: b.setIcon(
                _api.get_icon("fa5s.copy", color=_api.C["text2"])))
        b.clicked.connect(copy)
        return b

    def _match_widget(self, m: dict):
        box = _api.QFrame()
        box.setObjectName("subsearch_quote")
        lay = _api.QVBoxLayout(box)
        lay.setContentsMargins(8, 5, 8, 5)
        lay.setSpacing(2)
        quote_row = _api.QHBoxLayout(); quote_row.setSpacing(4)
        quote = _api.QLabel(f"«{_highlight(m.get('text', ''), m.get('matched', ''))}»")
        quote.setTextFormat(_api.Qt.TextFormat.RichText)
        quote.setWordWrap(True)
        quote.setTextInteractionFlags(_api.Qt.TextInteractionFlag.TextSelectableByMouse)
        quote.setStyleSheet(f"color:{_api.C['text']}; font-size:12px; background:transparent;")
        quote_row.addWidget(quote, 1)
        plain = str(m.get("text", "")).replace(" || ", " ").replace(" / ", " ")
        quote_row.addWidget(self._copy_button(plain, "Копировать реплику"))
        lay.addLayout(quote_row)
        where_row = _api.QHBoxLayout(); where_row.setSpacing(4)
        where = _api.QLabel(_match_line(m))
        where.setWordWrap(True)
        where.setStyleSheet(f"color:{_api.C['text3']}; font-size:11px; background:transparent;")
        where_row.addWidget(where, 1)
        watch = self._tool_button("fa5s.play-circle",
                                  "Смотреть серию на Re:ANIME (reanime.to) с этого момента")
        watch.clicked.connect(lambda _=False, b=watch, mm=m: self._open_watch(b, mm))
        where_row.addWidget(watch)
        if m.get("url"):
            btn = self._tool_button("fa5s.file-alt", "Открыть файл субтитров")
            btn.clicked.connect(lambda _=False, u=m["url"]: self.open_url(u))
            where_row.addWidget(btn)
        lay.addLayout(where_row)
        return box

    def _open_watch(self, btn, m: dict):
        """Ищет тайтл на Re:ANIME в фоне (несколько запросов к сайту при первом
        клике, дальше — из кэша) и открывает серию с моментом реплики."""
        btn.setEnabled(False)
        btn.setIcon(_api.get_icon("fa5s.hourglass-half", color=_api.C["text2"]))
        a = self.anime
        names = (a.name, a.title)
        shiki_id = self.hit.title.id

        def run():
            try:
                url = _api.engine.reanime_link(shiki_id, names, m.get("episode"),
                                               float(m.get("start") or 0.0))
            except Exception:  # noqa: BLE001 — сеть/кэш: просто «не нашлось»
                url = ""
            try:
                self.watch_ready.emit(btn, url)
            except RuntimeError:   # карточку уже удалили (очистили список)
                pass
        _api.threading.Thread(target=run, name="reanime-link", daemon=True).start()

    def _on_watch_ready(self, btn, url: str):
        try:
            btn.setEnabled(True)
        except RuntimeError:
            return
        if url:
            btn.setIcon(_api.get_icon("fa5s.play-circle", color=_api.C["text2"]))
            btn.setToolTip(f"Смотреть серию на Re:ANIME с этого момента\n{url}")
            self.open_url(url)
            return
        btn.setIcon(_api.get_icon("fa5s.times-circle", color=_api.C["red"]))
        btn.setToolTip("Тайтл на Re:ANIME не нашёлся (или сайт сейчас недоступен).")

    def _toggle_more(self, on: bool):
        for w in self._extra:
            w.setVisible(on)
        self.btn_more.setText("Свернуть" if on else f"Ещё совпадений: {len(self._extra)}")
        self.updateGeometry()
        owner = self.parent()
        while owner is not None and not hasattr(owner, "_resize_row_items"):
            owner = owner.parent()
        if owner is not None:
            owner._resize_row_items()

    @staticmethod
    def _index_tip(hit) -> str:
        if hit.index_row:
            try:
                from si_hyx_parts.shikimori_tab import pack_index
                text = pack_index.tooltip(hit.index_row)
                if text:
                    return text
            except Exception:  # noqa: BLE001
                pass
        return (f"Индекс популярности — {_fmt_int(hit.index)}\n"
                "Тот же индекс, что огонёк в ShikimoriHYX.")

    @staticmethod
    def open_url(url: str):
        try:
            _api.webbrowser.open(url)
        except Exception:  # noqa: BLE001
            pass

    def set_poster(self, pm):
        if pm is None or pm.isNull():
            return
        self.poster.setPixmap(pm.scaled(
            _api.POSTER_W, _api.POSTER_H, _api.Qt.AspectRatioMode.KeepAspectRatio,
            _api.Qt.TransformationMode.SmoothTransformation))

    def copy_text(self) -> str:
        """Строка для «Копировать всё»: название / оригинал — реплика (серия, время)."""
        a = self.anime
        name = a.title + (f" / {a.name}" if a.name and a.name != a.title else "")
        m = self.hit.matches[0] if self.hit.matches else {}
        where = ", ".join(p for p in (
            (f"серия {m['episode']}" if m.get("episode") else ""),
            str(m.get("timecode") or "")[:8]) if p)
        line = str(m.get("text", "")).replace(" || ", " ").replace(" / ", " ")
        return f"{name} — «{line}»" + (f" ({where})" if where else "")
