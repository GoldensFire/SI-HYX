# -*- coding: utf-8 -*-
"""Ползунок состава пака во вкладке «Генерация аниме-пака».

Долей теперь четыре: песни / ролики / кадры / персонажи. Часть «Ролики»
появляется в полосе только с галочкой «Вопрос — ролик», а снятая галочка
возвращает её проценты песням (ролик — та же песня, только видео).
"""
import pytest
from PyQt6.QtCore import Qt

from animepack import MANGA_KIND, VIDEO_KIND, PackSettings, UserList

animepack_tab = pytest.importorskip("animepack_tab")


class _FakeMain:
    """Ключи API живут в главном окне (Настройки → «Ключи API»)."""

    def __init__(self, **keys):
        self.api_keys = dict(keys)

    def get_api_key(self, name):
        return str(self.api_keys.get(name, "") or "").strip()

    def set_api_key(self, name, value, save=True):
        self.api_keys[name] = str(value or "").strip()

    def __getattr__(self, name):
        return lambda *a, **k: None


@pytest.fixture
def tab(qapp):
    widget = animepack_tab.AnimePackTab()
    yield widget
    widget.cleanup()


def test_video_part_appears_only_with_the_checkbox(tab):
    assert tab.mix.percents() == (100, 0, 0, 0, 0)
    tab.chk_video.setChecked(True)
    songs, video, frames, chars, manga = tab.mix.percents()
    assert video > 0 and songs + video + frames + chars + manga == 100
    assert tab.collect().percents == (songs, video, frames, chars, manga)
    # Настройки ролика показываются вместе с долей.
    assert tab.box_video_opts.isVisibleTo(tab)
    tab.chk_video.setChecked(False)
    assert tab.mix.percents() == (100, 0, 0, 0, 0)


def test_mix_survives_save_and_load(tab):
    tab.chk_video.setChecked(True)
    tab.mix.set_percents(40, 20, 30, 10)
    data = tab.get_settings()
    assert data["pct_videos"] == 20
    tab.apply_settings(data)
    assert tab.mix.percents() == (40, 20, 30, 10, 0)
    assert tab.collect().question_quotas[VIDEO_KIND] > 0


def test_video_share_keeps_song_settings_on_screen(tab):
    """Роликам песня нужна так же, как обычным вопросам: их настройки нужны и
    при нулевой доле обычных песен."""
    tab.chk_video.setChecked(True)
    tab.mix.set_percents(0, 100, 0, 0)
    tab._refresh_song_opts()
    assert tab.box_song_opts.isVisibleTo(tab)
    assert tab.collect().has_songs is True


def test_insert_songs_are_called_ost(tab):
    assert tab.chk_in.text() == "OST"
    assert PackSettings().question_quotas["insert"] > 0


def test_song_kinds_are_a_slider_too(tab):
    """Опенинги/эндинги/OST делятся полосой, а не счётчиками штук."""
    tab.kind_bar.set_values({"opening": 50, "ending": 30, "insert": 20})
    s = tab.collect()
    assert (s.openings, s.endings, s.inserts) == (50, 30, 20)
    # Снятая галочка убирает тип из полосы совсем.
    tab.chk_in.setChecked(False)
    assert "insert" not in tab.kind_bar.keys()
    assert tab.collect().question_quotas["insert"] == 0
    # И сумма всё равно ровно сто.
    s = tab.collect()
    assert s.openings + s.endings == 100


def test_manga_needs_its_checkbox_to_reach_the_slider(tab):
    """Без галочки «Вопрос — манга» её на ползунке нет вовсе."""
    assert not tab.box_manga.isVisibleTo(tab)
    assert "manga" not in tab.mix.keys()
    tab.mix.set_percents(50, 0, 0, 0, 50)
    # Доля ушла песням: части «Манга» на полосе просто не существует.
    assert tab.mix.percents() == (100, 0, 0, 0, 0)
    assert tab.collect().pct_manga == 0


def test_manga_share_shows_its_settings(tab):
    """С галочкой доля манги появляется, включает её настройки и доезжает до
    PackSettings."""
    tab.chk_manga.setChecked(True)
    assert tab.box_manga.isVisibleTo(tab)
    tab.mix.set_percents(50, 0, 0, 0, 50)
    tab._refresh_song_opts()
    s = tab.collect()
    assert s.pack_manga is True
    assert s.pct_manga == 50 and s.question_quotas[MANGA_KIND] > 0
    assert s.manga_question == "character"
    # Снятая галочка убирает мангу с полосы, а её доля возвращается песням.
    tab.chk_manga.setChecked(False)
    assert tab.mix.percents() == (100, 0, 0, 0, 0)
    assert not tab.box_manga.isVisibleTo(tab)


def test_counts_line_lists_every_kind(tab):
    """Строка над ползунком перечисляет вопросы по родам поимённо."""
    tab.chk_video.setChecked(True)
    tab.chk_manga.setChecked(True)
    tab.mix.set_percents(40, 10, 20, 20, 10)
    tab._recount()
    text = tab.lbl_left.text()
    for word in ("Кадров", "Опенингов", "Эндингов", "OST", "Персонажей",
                 "Видео", "Манги"):
        assert word in text
    quotas = tab.collect().question_quotas
    assert f"Кадров — {quotas['frame']}" in text
    assert f"Манги — {quotas[MANGA_KIND]}" in text


def test_list_cards_carry_target_and_music(tab):
    """У карточки списка есть раздел (аниме/манга) и пометка «музыка»."""
    tab.chk_random_shiki.setChecked(False)
    card = tab._add_user_card(UserList("m", "shikimori", ["completed"]))
    assert card.value().target == "anime"
    card.btn_target.setChecked(True)
    card.btn_music.setChecked(True)
    user = card.value()
    assert user.target == "manga" and user.prefer_music is True
    assert tab.collect().users[0].prefer_music is True


def test_saved_users_can_be_forgotten_by_right_click(tab, qapp):
    """ПКМ по нику в «Сохранённых» забывает его без всяких галочек."""
    saved = [UserList("a", "shikimori", ["completed"]),
             UserList("b", "shikimori", ["completed"]),
             UserList("c", "shikimori", ["completed"])]
    dlg = animepack_tab._SavedUsersDialog(saved, tab)
    assert dlg.list.count() == 3
    dlg._forget_rows([1])                    # то же, что делает пункт «Забыть»
    assert [u.username for u in dlg.remaining()] == ["a", "c"]
    assert dlg.list.count() == 2
    # Несколько отмеченных забываются разом и не путают строки местами.
    for i in range(dlg.list.count()):
        dlg.list.item(i).setCheckState(Qt.CheckState.Checked)
    dlg._forget_checked()
    assert dlg.remaining() == [] and dlg.list.count() == 0


def test_list_shares_split_evenly_and_survive_reload(tab):
    tab.chk_random_shiki.setChecked(False)
    for nick in ("a", "b", "c"):
        tab._add_user_card(UserList(nick, "shikimori", ["completed"]))
    tab.chk_shares.setChecked(True)
    shares = sorted(c.share() for c in tab._user_cards)
    assert sum(shares) == 100 and shares[0] >= 33
    keys = tab.share_bar.keys()
    tab.share_bar.set_values({keys[0]: 60, keys[1]: 30, keys[2]: 10})
    tab._on_share_bar_changed()
    data = tab.get_settings()
    tab.apply_settings(data)
    assert [c.share() for c in tab._user_cards] == [60, 30, 10]
    assert tab.chk_shares.isChecked()


# ── Новые настройки вкладки ─────────────────────────────────────────────────
def test_new_settings_survive_save_and_load(tab):
    """Средняя сложность персонажей, картинка в ответе и отметки списков
    доезжают до settings.json и обратно."""
    tab.sp_char_avg.setValue(6)
    tab.sp_answer_img.setValue(0)              # «без ограничения»
    tab.chk_mark_owners.setChecked(True)
    tab.chk_manga.setChecked(True)
    data = tab.get_settings()
    assert data["char_level_avg"] == 6
    assert data["answer_image_time"] == 0
    assert data["mark_owners"] is True and data["pack_manga"] is True

    tab.apply_settings(PackSettings().to_dict())
    assert tab.sp_char_avg.value() == 0 and tab.sp_answer_img.value() == 3
    tab.apply_settings(data)
    assert tab.sp_char_avg.value() == 6
    assert tab.sp_answer_img.value() == 0
    assert tab.chk_mark_owners.isChecked() and tab.chk_manga.isChecked()
    assert "manga" in tab.mix.keys()


def test_marking_owners_brings_the_user_cards_back(tab):
    """С общей базой карточки списков спрятаны, но отметки «у кого есть» их
    возвращают: списки нужны, чтобы подписать готовые вопросы."""
    tab.chk_random_shiki.setChecked(True)
    assert not tab.box_users.isVisibleTo(tab)
    assert tab.chk_mark_owners.isVisibleTo(tab)
    tab.chk_mark_owners.setChecked(True)
    assert tab.box_users.isVisibleTo(tab)
    # Совпадение «есть у N человек» к отметкам отношения не имеет.
    assert not tab.box_similar.isVisibleTo(tab)
    tab.chk_mark_owners.setChecked(False)
    assert not tab.box_users.isVisibleTo(tab)


def test_refresh_db_button_belongs_to_the_shikimori_base(tab):
    tab.chk_random_shiki.setChecked(True)
    assert tab.btn_refresh_db.isVisibleTo(tab)
    tab.chk_random.setChecked(True)            # база AMQ — кнопка не про неё
    assert not tab.btn_refresh_db.isVisibleTo(tab)


def test_refresh_db_button_turns_into_a_stop_button(tab):
    """Каталог берётся целиком, а это долго: бросить можно той же кнопкой."""
    class _FakeTask:
        stopped = False

        def stop(self):
            _FakeTask.stopped = True

    tab._db_task = _FakeTask()
    tab._refresh_db()                          # второе нажатие = «Остановить»
    assert _FakeTask.stopped
    tab._finish_db_ui()
    assert tab.btn_refresh_db.isEnabled()
    assert tab.btn_refresh_db.text() == "Обновить базу Shikimori"


def test_anagram_length_limit_survives_save_and_load(tab):
    tab.chk_anagram.setChecked(True)
    tab.sp_anagram_max.setValue(25)
    assert tab.collect().anagram_max_chars == 25
    data = tab.get_settings()
    tab.sp_anagram_max.setValue(0)             # «без предела»
    assert tab.collect().anagram_max_chars == 0
    tab.apply_settings(data)
    assert tab.sp_anagram_max.value() == 25
    # Настройка показывается вместе с самой галочкой анаграмм.
    assert tab.sp_anagram_max.isVisibleTo(tab)
    tab.chk_anagram.setChecked(False)
    assert not tab.sp_anagram_max.isVisibleTo(tab)


def test_table_has_a_column_for_character_difficulty(tab):
    assert tab.TABLE_HEADERS[-1] == "Перс."
    assert tab.table.columnCount() == len(tab.TABLE_HEADERS)


# ── Карточка списка ─────────────────────────────────────────────────────────
def test_source_combo_does_not_eat_the_card(tab, qapp):
    """Полное «MyAnimeList» занимало две трети карточки, и ник в поле не
    помещался («Лекс Ливень» показывался как «с Ливень»)."""
    tab._add_user_card(UserList("Лекс Ливень", "myanimelist", ["completed"]))
    card = tab._user_cards[-1]
    card.resize(300, card.sizeHint().height())
    qapp.processEvents()
    assert card.cb_source.currentText() == "MAL"
    assert card.cb_source.sizeHint().width() < card.ed_name.sizeHint().width()
    # Полное имя сайта никуда не делось — оно в подсказке.
    assert "MyAnimeList" in card.cb_source.toolTip()


def test_music_button_shows_whether_it_is_on(tab):
    """Нажатое «♪» должно быть ВИДНО: раньше включённая пометка «в основном
    музыка» выглядела ровно как выключенная."""
    tab._add_user_card(UserList("morr", "shikimori", ["completed"]))
    card = tab._user_cards[-1]
    assert card.btn_music.isCheckable()
    assert not card.btn_music.isChecked()
    assert "выключено" in card.btn_music.toolTip()
    card.btn_music.setChecked(True)
    assert "ВКЛЮЧЕНО" in card.btn_music.toolTip()
    assert card.value().prefer_music is True
    # Заливка нажатого состояния — в стилях вкладки, по имени кнопки.
    assert card.btn_music.objectName() == "musicBtn"
    assert "musicBtn:checked" in tab.styleSheet()


def test_answer_image_time_is_capped_at_five(tab):
    """Дольше пяти секунд постер в ответе висеть не должен."""
    assert tab.sp_answer_img.maximum() == 5
    tab.sp_answer_img.setValue(99)
    assert tab.sp_answer_img.value() == 5
    tab.apply_settings({"answer_image_time": 30})
    assert tab.sp_answer_img.value() == 5


# ── Анаграммы, пиксели и сюжет ──────────────────────────────────────────────
@pytest.mark.parametrize("attr,part,box", [
    ("chk_pixel", "pixel", "box_pixel"),
    ("chk_anagram", "anagram", "box_anagram"),
    ("chk_plot", "plot", "box_plot"),
])
def test_new_kinds_need_their_checkbox_to_reach_the_slider(tab, attr, part, box):
    """Как у роликов и манги: без галочки части на ползунке нет вовсе, а её
    настройки не занимают место на панели."""
    assert part not in tab.mix.keys()
    assert not getattr(tab, box).isVisibleTo(tab)
    getattr(tab, attr).setChecked(True)
    assert part in tab.mix.keys()
    assert getattr(tab, box).isVisibleTo(tab)
    assert tab.mix.shares()[part] > 0
    # Снятая галочка возвращает долю песням.
    getattr(tab, attr).setChecked(False)
    assert tab.mix.percents() == (100, 0, 0, 0, 0)


def test_new_shares_reach_pack_settings_and_survive_reload(tab):
    tab.chk_pixel.setChecked(True)
    tab.chk_anagram.setChecked(True)
    tab.chk_plot.setChecked(True)
    tab.mix.set_shares({"songs": 40, "video": 0, "frames": 0, "chars": 0,
                        "manga": 0, "pixel": 20, "anagram": 20, "plot": 20})
    tab.sp_pixel_sec.setValue(12)
    tab.sp_pixel_steps.setValue(8)
    tab.cb_anagram_lang.setCurrentIndex(
        tab.cb_anagram_lang.findData("romaji"))
    tab.main = _FakeMain()
    tab.main.set_api_key("gemini", "secret")
    s = tab.collect()
    assert (s.pct_pixel, s.pct_anagram, s.pct_plot) == (20, 20, 20)
    quotas = s.question_quotas
    assert quotas["pixel"] and quotas["anagram"] and quotas["plot"]
    data = tab.get_settings()
    tab.apply_settings(data)
    assert tab.mix.shares()["pixel"] == 20
    assert tab.sp_pixel_sec.value() == 12 and tab.sp_pixel_steps.value() == 8
    assert tab.cb_anagram_lang.currentData() == "romaji"
    # Ключ во вкладке не хранится: он общий для программы (Настройки → «Ключи
    # API»), поэтому и в сохранённые настройки вкладки не попадает.
    assert "gemini_key" not in data
    assert s.gemini_key == "secret"


def test_counts_line_mentions_the_new_kinds(tab):
    tab.chk_pixel.setChecked(True)
    tab.chk_anagram.setChecked(True)
    tab.chk_plot.setChecked(True)
    tab._recount()
    text = tab.lbl_left.text()
    for word in ("Пикселей", "Анаграмм", "По сюжету"):
        assert word in text


def test_pixel_hint_shows_the_same_blocks_as_the_effect(tab):
    """Подсказка о ступенях считается той же функцией, что и сам эффект."""
    from pixelize import block_sequence
    tab.chk_pixel.setChecked(True)
    tab.sp_pixel_block.setValue(64)
    tab.sp_pixel_steps.setValue(6)
    text = tab.lbl_pixel_steps.text()
    for block in block_sequence(64, 6)[:-1]:
        assert f"{block}px" in text
    assert "чётко" in text
