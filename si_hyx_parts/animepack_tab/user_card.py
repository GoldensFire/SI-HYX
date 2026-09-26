# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_UserCard. Public namespace: animepack_tab."""
from __future__ import annotations
import animepack_tab as _api


# ─────────────────────────────────────────────────────────────────────────────
# Карточка одного пользователя (ник + источник + статусы списков)
# ─────────────────────────────────────────────────────────────────────────────
class _UserCard(_api.QFrame):
    removed = _api.pyqtSignal(object)
    changed = _api.pyqtSignal()
    # Ник дописан (Enter или уход фокуса) — момент, когда его можно запомнить в
    # адресную книгу. По каждому нажатию клавиши этого делать нельзя: в книгу
    # попали бы «m», «m4», «m46…».
    committed = _api.pyqtSignal(object)

    # Высота строки внутри карточки: ник, источник и статусы одинаково низкие.
    ROW_H = 22

    def __init__(self, data: '_api.UserList', parent=None):
        super().__init__(parent)
        self.setObjectName("userCard")
        # Карточка нарочно тесная: ник, источник и статусы — три коротких
        # элемента, а прежние отступы съедали в панели настроек по полсотни
        # пикселей на каждый список.
        v = _api.QVBoxLayout(self)
        v.setContentsMargins(4, 3, 4, 3)
        v.setSpacing(3)

        top = _api.QHBoxLayout()
        top.setSpacing(4)
        self.ed_name = _api.QLineEdit(data.username)
        self.ed_name.setPlaceholderText("Ник")
        # Ширину ника больше ничем не режем: всё, что осталось от источника и
        # крестика, достаётся ему. Раньше тут стоял потолок в 96 px, и «Лекс
        # Ливень» показывался как «с Ливень» (просьба пользователя).
        self.ed_name.setMinimumWidth(90)
        self.ed_name.textChanged.connect(lambda *_: self.changed.emit())
        self.ed_name.editingFinished.connect(lambda: self.committed.emit(self))
        self.cb_source = _api.QComboBox()
        for src in _api.LIST_SOURCES:
            self.cb_source.addItem(_api.SOURCE_SHORT.get(src, _api.SOURCE_LABELS[src]), src)
        idx = self.cb_source.findData(data.source)
        if idx >= 0:
            self.cb_source.setCurrentIndex(idx)
        self.cb_source.setToolTip("С какого сайта брать список: "
                                  + ", ".join(_api.SOURCE_LABELS[s] for s in _api.LIST_SOURCES))
        self.cb_source.setSizeAdjustPolicy(
            _api.QComboBox.SizeAdjustPolicy.AdjustToContents)
        # Ключевое: без Maximum по горизонтали QComboBox растягивается на всё
        # свободное место карточки — «Shikimori» занимал две трети её ширины, а
        # нику оставались крохи.
        self.cb_source.setSizePolicy(_api.QSizePolicy.Policy.Maximum,
                                     _api.QSizePolicy.Policy.Fixed)
        self.cb_source.currentIndexChanged.connect(lambda *_: self.changed.emit())
        self.cb_source.currentIndexChanged.connect(
            lambda *_: self.committed.emit(self))
        self.btn_del = _api.QToolButton()
        self.btn_del.setIcon(_api.get_icon('fa5s.times'))
        self.btn_del.setToolTip("Убрать этот список")
        self.btn_del.clicked.connect(lambda: self.removed.emit(self))
        top.addWidget(self.ed_name, 1)
        top.addWidget(self.cb_source)
        top.addWidget(self.btn_del)
        v.addLayout(top)

        # Статусы — выпадающее меню с галочками: пять отдельных чекбоксов в
        # узкую панель настроек не влезают.
        self.btn_status = _api.QToolButton()
        self.btn_status.setObjectName("statusBtn")
        self.btn_status.setPopupMode(_api.QToolButton.ToolButtonPopupMode.InstantPopup)
        self.btn_status.setToolButtonStyle(_api.Qt.ToolButtonStyle.ToolButtonTextOnly)
        # Во всю ширину карточки: у кнопки-с-меню стрелка рисуется у правого
        # края, и на кнопке по размеру текста она наезжала на сам текст.
        self.btn_status.setSizePolicy(_api.QSizePolicy.Policy.Expanding,
                                      _api.QSizePolicy.Policy.Fixed)
        menu = _api.QMenu(self.btn_status)
        self._actions = {}
        for st in _api.LIST_STATUSES:
            act = menu.addAction(_api.STATUS_LABELS[st])
            act.setCheckable(True)
            act.setChecked(st in data.statuses)
            act.toggled.connect(self._on_status_toggled)
            self._actions[st] = act
        self.btn_status.setMenu(menu)

        # Раздел списка (аниме/манга) и пометка «в основном музыка» — кнопками
        # рядом со статусами, чтобы карточка осталась в две строки.
        self.btn_target = _api.QToolButton()
        self.btn_target.setCheckable(True)
        self.btn_target.setChecked(
            str(getattr(data, "target", "anime")) == "manga")
        self.btn_target.setToolTip(
            "Какой раздел списка брать: аниме или мангу/манхву/ранобэ. У всех "
            "трёх сайтов это отдельные списки.\n"
            "Манга идёт в свою долю ползунка состава — песен и кадров у книги "
            "нет, вопросом служит портрет персонажа либо обложка.")
        self.btn_target.toggled.connect(self._on_target_toggled)
        self.btn_music = _api.QToolButton()
        self.btn_music.setObjectName("musicBtn")
        self.btn_music.setCheckable(True)
        self.btn_music.setText("♪")
        self.btn_music.setChecked(bool(getattr(data, "prefer_music", False)))
        self.btn_music.toggled.connect(lambda *_: self.changed.emit())
        self.btn_music.toggled.connect(self._refresh_music_tip)
        self._refresh_music_tip(self.btn_music.isChecked())
        row2 = _api.QHBoxLayout(); row2.setSpacing(4)
        row2.addWidget(self.btn_status, 1)
        row2.addWidget(self.btn_target)
        row2.addWidget(self.btn_music)
        v.addLayout(row2)

        # Высоты фиксируем: без этого поля растут от общих отступов вкладки
        # (padding: 5px 7px у полей и 6px 12px у кнопок) и карточка выходит
        # вдвое выше нужного.
        for w in (self.ed_name, self.cb_source, self.btn_del, self.btn_status,
                  self.btn_target, self.btn_music):
            w.setFixedHeight(self.ROW_H)
        self._on_target_toggled(self.btn_target.isChecked())
        self._share = int(getattr(data, "share", 0) or 0)
        self._refresh_status_text()

    # ── доля списка в паке (её двигает общий ползунок «Доли списков») ─────
    def share(self) -> int:
        return int(self._share)

    def set_share(self, pct: int) -> None:
        self._share = max(0, min(100, int(pct or 0)))

    def _refresh_music_tip(self, on: bool):
        """Подсказка «♪» говорит, включена ли пометка ПРЯМО СЕЙЧАС.

        Нажатое состояние теперь и видно (кнопка заливается акцентом — см.
        _apply_styles): раньше включённая и выключенная выглядели одинаково, и
        понять, помечен ли список, было нельзя вовсе."""
        state = "ВКЛЮЧЕНО" if on else "выключено"
        self.btn_music.setToolTip(
            f"«В основном музыка» — {state}. Нажмите, чтобы переключить.\n"
            "Тайтлы из этого списка по возможности идут в песенные вопросы, а "
            "не в кадры и персонажей.\n"
            "Для списков, где человек угадывает музыку, но сам тайтл в лицо не "
            "узнаёт.")

    def _on_status_toggled(self, *_):
        self._refresh_status_text()
        self.changed.emit()

    def _on_target_toggled(self, manga: bool):
        self.btn_target.setText(_api.TARGET_LABELS["manga" if manga else "anime"])
        self.changed.emit()
        # Раздел входит в ключ списка на полосе долей — значит, это смена
        # «личности» карточки, как ник или источник.
        self.committed.emit(self)

    def target(self) -> str:
        return "manga" if self.btn_target.isChecked() else "anime"

    def _refresh_status_text(self):
        picked = [_api.STATUS_LABELS[s] for s in _api.LIST_STATUSES
                  if self._actions[s].isChecked()]
        # Текст держим коротким: перечисление всех пяти статусов раздувало
        # кнопку шире панели настроек, и её правый край срезало.
        if not picked:
            text = "не выбраны"
        elif len(picked) == len(_api.LIST_STATUSES):
            text = "все"
        elif len(picked) <= 2:
            text = ", ".join(picked)
        else:
            text = f"{len(picked)} из {len(_api.LIST_STATUSES)}"
        self.btn_status.setText(f"Статусы: {text}")
        self.btn_status.setToolTip(
            "Какие списки пользователя брать. Без единого статуса список "
            "игнорируется.")

    def value(self) -> '_api.UserList':
        return _api.UserList(
            username=self.ed_name.text().strip(),
            source=self.cb_source.currentData() or "myanimelist",
            statuses=[s for s in _api.LIST_STATUSES if self._actions[s].isChecked()],
            target=self.target(),
            share=self.share(),
            prefer_music=self.btn_music.isChecked())

_UserCard.__module__ = _api.__name__
_api._UserCard = _UserCard
