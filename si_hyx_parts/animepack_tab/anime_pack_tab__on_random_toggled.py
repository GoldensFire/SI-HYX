# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""AnimePackTab: _on_random_toggled. Public namespace: animepack_tab."""
from __future__ import annotations
import animepack_tab as _api


def _on_random_toggled(self, checked: bool):
    if checked and self.chk_random_shiki.isChecked():
        # Две общие базы разом не бывает — включаем последнюю выбранную.
        self.chk_random_shiki.blockSignals(True)
        self.chk_random_shiki.setChecked(False)
        self.chk_random_shiki.blockSignals(False)
    self._refresh_lists_visibility()

def _on_random_shiki_toggled(self, checked: bool):
    if checked and self.chk_random.isChecked():
        self.chk_random.blockSignals(True)
        self.chk_random.setChecked(False)
        self.chk_random.blockSignals(False)
    self._refresh_lists_visibility()

def _on_mark_owners_toggled(self, _checked: bool):
    """Отметки берутся из тех же карточек списков — значит их надо показать
        даже в режиме общей базы."""
    self._refresh_lists_visibility()

def _refresh_lists_visibility(self):
    """Карточки людей нужны, когда пак собирается по чьим-то спискам — а
        также когда включены отметки «у кого из списков есть» (тогда списки не
        отбирают тайтлы, а лишь подписывают готовые вопросы)."""
    random_mode = (self.chk_random.isChecked()
                   or self.chk_random_shiki.isChecked())
    marking = random_mode and self.chk_mark_owners.isChecked()
    self.box_users.setVisible(not random_mode or marking)
    # Совпадение и доли — про отбор по спискам; при отметках их нет.
    self.box_similar.setVisible(not random_mode)
    self.box_shares.setVisible(not random_mode
                               and len(self.share_bar.keys()) > 1)
    self.chk_mark_owners.setVisible(random_mode)
    self.btn_refresh_db.setVisible(self.chk_random_shiki.isChecked())
    self._refresh_amq_available()
    self._fit_settings_width()

def _refresh_amq_available(self):
    """Мастер-лист AMQ — это перечень тайтлов с песнями, поэтому без песен
        он бесполезен. Не выбираем базу молча за пользователя: галочка гаснет и
        сама объясняет, почему."""
    pcts = self.mix.percents() if getattr(self, "mix", None) else (0, 0, 0, 0)
    songs = bool(pcts[0] or pcts[1])
    songs = songs and any(c.isChecked() for c in
                          (self.chk_op, self.chk_ed, self.chk_in))
    self.chk_random.setEnabled(songs)
    if not songs and self.chk_random.isChecked():
        self.chk_random.blockSignals(True)
        self.chk_random.setChecked(False)
        self.chk_random.blockSignals(False)
        self.chk_random_shiki.blockSignals(True)
        self.chk_random_shiki.setChecked(True)
        self.chk_random_shiki.blockSignals(False)
    if songs:
        self.chk_random.setToolTip(
            "Аниме берутся из мастер-листа AnimeMusicQuiz. Он знает только "
            "те тайтлы, у которых есть песни в AMQ, поэтому годится лишь "
            "песенным пакам: без песен база всё равно берётся с Shikimori.")
    else:
        self.chk_random.setToolTip(
            "Песен в этом паке нет, а мастер-лист AMQ — это перечень "
            "тайтлов С ПЕСНЯМИ и больше ничего. Для кадров и персонажей "
            "база берётся с Shikimori.")

def _add_user_card(self, data: _api.Optional['_api.UserList'] = None):
    card = _api._UserCard(data or _api.UserList(), self.box_cards)
    card.removed.connect(self._remove_user_card)
    # Ник уходит в адресную книгу сразу, как только дописан, — не дожидаясь
    # запуска генерации: «в сохранённых должно числиться всё, что я вообще
    # добавлял».
    card.committed.connect(lambda c: self._remember_users([c.value()]))
    card.committed.connect(lambda *_: self._refresh_share_bar())
    card.changed.connect(self._on_card_changed)
    self._disable_wheel(card)
    self.cards_layout.addWidget(card)
    self._user_cards.append(card)
    self._refresh_share_bar()
    self._fit_settings_width()
    return card

def _on_card_changed(self):
    """Карточку правили — подсказка состава могла устареть.

        Полосу долей отсюда НЕ трогаем: этот сигнал приходит на каждую букву
        ника, и доли перетасовывались бы прямо во время набора. Её пересобирает
        committed — когда ник дописан, а источник или раздел переключён."""
    self._recount()

def _remove_user_card(self, card):
    try:
        self._user_cards.remove(card)
    except ValueError:
        pass
    card.setParent(None)
    card.deleteLater()
    self._refresh_share_bar()
    self._fit_settings_width()

def _clear_user_cards(self):
    # Сначала в книгу, потом с глаз долой: кнопка «Очистить» убирает списки
    # из пака, а не забывает ники (для этого есть «Забыть отмеченных»).
    self._remember_users([c.value() for c in self._user_cards])
    for card in list(self._user_cards):
        self._remove_user_card(card)

# ── адресная книга ников ──────────────────────────────────────────────
@staticmethod
def _user_key(user) -> tuple:
    return (user.username.strip().casefold(), user.source)

def _remember_users(self, users) -> None:
    """Пополняет адресную книгу: любой ник, который вы вписали, потом
        добавляется одной кнопкой, а не набирается заново.

        Статусы тут не требуются нарочно: раньше ник запоминался только при
        запуске генерации и только со статусами, из-за чего «всё, что я вообще
        добавлял» в книге не оказывалось."""
    known = {self._user_key(u) for u in self._saved_users}
    for user in users:
        if not user.username.strip():
            continue
        key = self._user_key(user)
        if key in known:
            continue
        known.add(key)
        self._saved_users.append(_api.UserList(username=user.username.strip(),
                                          source=user.source,
                                          statuses=list(user.statuses)))

def _open_saved_users(self):
    # В книгу заодно попадает всё, что набрано прямо сейчас: иначе окно
    # открылось бы без только что вписанного ника.
    self._remember_users([c.value() for c in self._user_cards])
    have = {self._user_key(c.value()) for c in self._user_cards}
    dlg = _api._SavedUsersDialog(self._saved_users, self, used=have)
    ok = dlg.exec()
    # «Забыть» действует независимо от того, чем закрыли окно.
    self._saved_users = dlg.remaining()
    if not ok:
        return
    # Галочки — это и есть итоговый набор списков: снятая убирает карточку,
    # поставленная добавляет.
    picked = {self._user_key(u): u for u in dlg.picked()}
    for card in list(self._user_cards):
        if self._user_key(card.value()) not in picked:
            self._remove_user_card(card)
    have = {self._user_key(c.value()) for c in self._user_cards}
    for key, user in picked.items():
        if key in have:
            continue
        self._add_user_card(_api.UserList(username=user.username,
                                     source=user.source,
                                     statuses=list(user.statuses),
                                     target=getattr(user, "target", "anime"),
                                     share=int(getattr(user, "share", 0) or 0),
                                     prefer_music=bool(
                                         getattr(user, "prefer_music", False))))
