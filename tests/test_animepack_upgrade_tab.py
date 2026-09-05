# -*- coding: utf-8 -*-
"""Вкладка «Апгрейд пака»: форма, сохранение настроек и таблица правок.

Сама правка пака проверяется в test_animepack_upgrade.py — здесь только то, что
делает вкладка: галочки функций, запоминание настроек и показ изменений.

Вкладка держит одну страницу («Аниме-пак»), и форма живёт на ней, а не на
вкладке: почти всё проверяется на самой странице (фикстура tab), а вкладка
(upgrade_tab) — только там, где речь про обёртку (get_settings/apply_settings,
set_siq, cleanup)."""
import zipfile

import pytest

from animepack_upgrade import Change, UpgradeResult, UpgradeSettings

animepack_upgrade_tab = pytest.importorskip("animepack_upgrade_tab")


@pytest.fixture
def upgrade_tab(qapp):
    widget = animepack_upgrade_tab.AnimePackUpgradeTab()
    yield widget
    widget.cleanup()


@pytest.fixture
def tab(upgrade_tab):
    """Страница «Аниме-пак» — на ней и стоит почти вся форма."""
    return upgrade_tab.pages["anime"]


PACK_XML = (
    '<package name="Солянка № 2" version="5" date="17.07.2025">'
    "<info><authors><author>GoldensFire</author></authors></info>"
    '<rounds><round name="Раунд 1"><themes>'
    '<theme name="Опенинги"><questions><question price="100">'
    "<right><answer>Наруто</answer></right></question></questions></theme>"
    '<theme name="Эндинги"><questions/></theme>'
    "</themes></round></rounds></package>")


def _siq(tmp_path, name="pack.siq", xml=PACK_XML):
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("content.xml", xml)
    return str(path)


# ── Функции включаются и выключаются по отдельности ──────────────────────────
def test_all_functions_are_on_by_default(tab):
    s = tab.collect()
    assert s.strip_specials and s.add_titles and s.compress_images
    assert s.strip_repeated_text


def test_merge_group_is_on_and_toggles(tab):
    """«Текст под звук» — такая же функция, как остальные: включена и снимается
    отдельной галочкой в заголовке группы."""
    assert tab.collect().merge_text_audio is True
    tab.grp_merge.setChecked(False)
    assert tab.collect().merge_text_audio is False
    assert tab.collect().strip_repeated_text is True


def test_merge_setting_survives_a_restart(tab):
    tab.grp_merge.setChecked(False)
    data = tab.get_settings()
    tab.grp_merge.setChecked(True)
    tab.apply_settings(data)
    assert tab.grp_merge.isChecked() is False


def test_functions_toggle_independently(tab):
    tab.grp_specials.setChecked(False)
    assert tab.collect().strip_specials is False
    assert tab.collect().add_titles is True
    tab.grp_specials.setChecked(True)
    tab.grp_titles.setChecked(False)
    assert tab.collect().add_titles is False
    tab.grp_images.setChecked(False)
    assert tab.collect().compress_images is False
    tab.grp_repeats.setChecked(False)
    assert tab.collect().strip_repeated_text is False
    assert tab.collect().strip_specials is True


def test_off_function_greys_out_its_settings(tab):
    """Снятая галочка в заголовке группы гасит и её содержимое — иначе непонятно,
    работают ли настройки внутри."""
    tab.grp_titles.setChecked(False)
    assert not tab.chk_strict.isEnabled()
    tab.grp_titles.setChecked(True)
    assert tab.chk_strict.isEnabled()


def test_all_off_is_refused_before_any_work(tab, tmp_path, monkeypatch):
    warned = []
    monkeypatch.setattr(animepack_upgrade_tab, "msgbox_warning",
                        lambda *a, **k: warned.append(a))
    tab._siq = _siq(tmp_path)
    tab.grp_specials.setChecked(False)
    tab.grp_titles.setChecked(False)
    tab.grp_images.setChecked(False)
    tab.grp_repeats.setChecked(False)
    tab.grp_merge.setChecked(False)
    tab.grp_empty.setChecked(False)
    tab.grp_audio.setChecked(False)
    tab.grp_video.setChecked(False)
    tab.grp_unused.setChecked(False)
    tab.start()
    assert warned and tab._task is None


def test_start_without_a_pack_is_refused(tab, monkeypatch):
    warned = []
    monkeypatch.setattr(animepack_upgrade_tab, "msgbox_warning",
                        lambda *a, **k: warned.append(a))
    tab.start()
    assert warned and tab._task is None


# ── Настройки ────────────────────────────────────────────────────────────────
def test_settings_survive_save_and_load(tab, tmp_path):
    tab.grp_specials.setChecked(False)
    tab.chk_strict.setChecked(False)
    tab.chk_poster.setChecked(False)
    tab.chk_fix_case.setChecked(False)
    tab.chk_characters.setChecked(False)
    tab.chk_book_themes.setChecked(False)
    tab.sp_max_variants.setValue(3)
    tab.sp_img_min.setValue(2.5)
    tab.sp_img_kb.setValue(300)
    tab.sp_img_speed.setValue(4)
    tab.grp_repeats.setChecked(False)
    tab.sp_repeat_len.setValue(25)
    tab._siq = _siq(tmp_path)
    tab._out_dir = str(tmp_path)
    data = tab.get_settings()

    tab.apply_settings(UpgradeSettings().to_dict())   # сбили на дефолты
    tab.apply_settings(data)
    s = tab.collect()
    assert s.strip_specials is False and s.strict_match is False
    assert s.add_poster is False and s.fix_case is False
    assert s.check_characters is False
    assert s.book_themes is False
    assert s.max_variants == 3
    assert s.image_min_mb == 2.5 and s.image_limit_kb == 300
    assert s.image_speed == 4
    assert s.strip_repeated_text is False and s.repeat_text_max_len == 25
    assert tab._siq == data["siq"] and tab._out_dir == str(tmp_path)


def test_missing_pack_is_not_restored(tab, tmp_path):
    """Путь к паку запоминается, но исчезнувший файл подставлять нельзя —
    подпись врала бы про выбранный пак."""
    tab.apply_settings({"siq": str(tmp_path / "нет-такого.siq")})
    assert tab._siq == ""
    assert "не выбран" in tab.lbl_siq.text()


def test_set_siq_takes_a_pack_from_outside(tab, tmp_path):
    """set_siq — вход для пункта ПКМ «Отправить в апгрейд пакета» на вкладке
    «Поиск пакетов» (и для перетаскивания мышью)."""
    path = _siq(tmp_path)
    assert tab.set_siq(path) is True
    assert tab._siq == path
    assert "pack.siq" in tab.lbl_siq.text()


def test_set_siq_refuses_a_missing_file(tab, tmp_path):
    assert tab.set_siq(str(tmp_path / "нет-такого.siq")) is False
    assert tab.set_siq("") is False
    assert tab._siq == ""


def test_reset_keeps_the_chosen_pack(tab, tmp_path):
    tab._siq = _siq(tmp_path)
    tab.sp_max_variants.setValue(20)
    tab.reset_settings()
    assert tab.sp_max_variants.value() == UpgradeSettings().max_variants
    assert tab._siq                       # файл сброс не теряет


# ── Таблица изменений ────────────────────────────────────────────────────────
def _result():
    return UpgradeResult(
        path="C:/паки/Пак (апгрейд).siq", questions=3,
        specials=[Change(kind="special", round_name="Раунд 1",
                         theme_name="Тема А", price=200,
                         before="с секретом", after="обычный вопрос",
                         order=1)],
        titles=[Change(kind="title", round_name="Раунд 1", theme_name="Тема А",
                       price=100, before="Наруто (2002)",
                       after="Наруто (2002) / Naruto", added=["Naruto"],
                       title="Наруто", order=0)],
        images=[Change(kind="image", theme_name="poster.jpg",
                       before="jpg, 2,4 МБ", after="avif, 412 КБ",
                       title="poster.avif", order=3)],
        skipped_specials=[Change(kind="special", round_name="Раунд 1",
                                 theme_name="Тема Б", price=300,
                                 before="с секретом без вопроса",
                                 after="оставлен как есть", order=2)])


def test_table_shows_changes_in_pack_order(tab):
    tab._fill_table(_result())
    assert tab.table.rowCount() == 4
    assert [tab.table.item(r, 4).text() for r in range(4)] == [
        "Названия", "Спецвопрос", "Спецвопрос", "Картинка"]
    assert tab.table.item(0, 5).text() == "Наруто (2002)"
    # Пропущенные тоже видны: молчать о них нельзя, файл-то не изменился.
    assert tab.table.item(2, 6).text() == "оставлен как есть"
    # У картинки вместо вопроса имя файла — во всю ширину «Раунда», «Темы» и
    # «Цены» разом: раунда и цены у файла в архиве нет.
    assert tab.table.item(3, 1).text() == "poster.jpg"
    assert tab.table.columnSpan(3, 1) == 3
    assert tab.table.item(3, 2).text() == ""
    assert tab.table.item(3, 3).text() == ""


def test_table_names_the_new_functions(tab):
    """Написание и постер — отдельные строки: в таблице должно быть видно, что
    именно поменялось в вопросе."""
    result = UpgradeResult(
        questions=2,
        recased=[Change(kind="case", round_name="Раунд 1", theme_name="Тема А",
                        price=100, before="наруто", after="Наруто", order=0)],
        posters=[Change(kind="poster", round_name="Раунд 1",
                        theme_name="Тема А", price=100,
                        before="в ответе не было картинки",
                        after="постер, 96 КБ", title="Наруто", order=1)],
        repeats=[Change(kind="repeat", round_name="Раунд 1",
                        theme_name="Тема А", price=200, before="Назвать аниме",
                        after="убран (стоял в каждом вопросе темы)", order=2)])
    tab._fill_table(result)
    assert [tab.table.item(r, 4).text() for r in range(3)] == [
        "Написание", "Постер", "Повтор"]
    assert tab.table.item(0, 6).text() == "Наруто"
    assert tab.table.item(1, 6).text() == "постер, 96 КБ"
    assert tab.table.item(2, 5).text() == "Назвать аниме"


def test_table_shows_answers_left_alone_as_characters(tab):
    """Про нетронутый вопрос молчать нельзя: иначе непонятно, почему у ответа
    «Mumei» ничего не поменялось."""
    result = UpgradeResult(
        questions=1,
        skipped_titles=[Change(kind="character", round_name="Раунд 1",
                               theme_name="Gachi girls", price=50,
                               before="Mumei",
                               after="это имя персонажа, не тайтл",
                               title="Mumei", order=0)])
    tab._fill_table(result)
    assert tab.table.rowCount() == 1
    assert tab.table.item(0, 4).text() == "Персонаж"
    assert tab.table.item(0, 5).text() == "Mumei"


# ── Карточка выбранного пака (на месте таблицы) ──────────────────────────────
def test_chosen_pack_is_shown_as_a_card(tab, tmp_path):
    """Выбрали файл — на месте таблицы видно, что это за пак."""
    tab._siq = _siq(tmp_path)
    tab._refresh_siq_label()
    assert tab.left_stack.currentIndex() == 0
    assert tab.lbl_pack_name.text() == "Солянка № 2"
    assert "GoldensFire" in tab.lbl_pack_author.text()
    assert "1 вопрос(ов)" in tab.lbl_pack_meta.text()
    themes = tab.lbl_pack_themes.text()
    assert "Опенинги" in themes and "Эндинги" in themes


def test_pack_card_without_author_says_so(tab, tmp_path):
    tab._siq = _siq(tmp_path, xml='<package name="Пак"><rounds/></package>')
    tab._refresh_siq_label()
    assert tab.lbl_pack_name.text() == "Пак"
    assert "не указан" in tab.lbl_pack_author.text()


def test_broken_pack_shows_the_reason_not_a_crash(tab, tmp_path):
    path = tmp_path / "битый.siq"
    path.write_bytes(b"not a zip at all")
    tab._siq = str(path)
    tab._refresh_siq_label()
    assert tab.lbl_pack_name.text() == "битый"
    assert "не читается" in tab.lbl_pack_meta.text()


def test_table_replaces_the_card_when_the_run_is_over(tab, tmp_path):
    tab._siq = _siq(tmp_path)
    tab._refresh_siq_label()
    tab._fill_table(_result())
    assert tab.left_stack.currentIndex() == 1
    # Новый файл — снова карточка.
    tab._refresh_siq_label()
    assert tab.left_stack.currentIndex() == 0


def test_finish_reports_examples_to_the_log(tab, monkeypatch):
    lines = []
    monkeypatch.setattr(tab, "log", lines.append)
    monkeypatch.setattr(tab, "_progress", lambda *a: None)
    tab._on_finished(_result())
    assert any("Спецвопросов расколдовано: 1." in l for l in lines)
    assert any("Ответов дополнено названиями: 1." in l for l in lines)
    assert any(l.startswith("Картинок сжато: 1") for l in lines)
    assert tab.btn_open.isEnabled() and tab.btn_start.isEnabled()


def test_cancelled_run_writes_nothing_and_says_so(tab, monkeypatch):
    lines = []
    monkeypatch.setattr(tab, "log", lines.append)
    monkeypatch.setattr(tab, "_progress", lambda *a: None)
    tab._on_finished(UpgradeResult(cancelled=True))
    assert any("исходный пак цел" in l for l in lines)
    assert not tab.btn_open.isEnabled()


# ── Пустые вопросы и аудио ───────────────────────────────────────────────────
def test_new_functions_are_on_by_default(tab):
    s = tab.collect()
    assert s.drop_empty_questions and s.compress_audio
    assert s.audio_min_mb == 5.0 and s.audio_kbps == 192


def test_new_functions_toggle_independently(tab):
    tab.grp_empty.setChecked(False)
    assert tab.collect().drop_empty_questions is False
    assert tab.collect().compress_audio is True
    tab.grp_audio.setChecked(False)
    assert tab.collect().compress_audio is False
    assert tab.collect().drop_empty_questions is False


def test_audio_bitrates_are_the_ones_from_the_process_tab(tab):
    """Список битрейтов — тот же, что во вкладке «Обработка» (без «auto»)."""
    from config import AUDIO_BITRATES as PROCESS_BITRATES
    shown = [tab.cb_aud_kbps.itemText(i)
             for i in range(tab.cb_aud_kbps.count())]
    assert shown == [b for b in PROCESS_BITRATES if b != "auto"]


def test_audio_settings_survive_save_and_load(tab, tmp_path):
    tab.grp_empty.setChecked(False)
    tab.sp_aud_min.setValue(12.5)
    tab.cb_aud_kbps.setCurrentText("96")
    data = tab.get_settings()

    tab.apply_settings(UpgradeSettings().to_dict())     # сбили на дефолты
    assert tab.collect().audio_kbps == 192
    tab.apply_settings(data)
    s = tab.collect()
    assert s.drop_empty_questions is False
    assert s.audio_min_mb == 12.5 and s.audio_kbps == 96


def test_odd_saved_bitrate_snaps_to_the_list(tab):
    """В settings.json могло оказаться что угодно, а список показать это не
    сможет: подставляется ближайшее значение из списка."""
    tab.apply_settings(dict(UpgradeSettings().to_dict(), audio_kbps=200))
    assert tab.cb_aud_kbps.currentText() == "192"


def test_table_names_empty_and_audio_rows(tab):
    result = UpgradeResult(
        questions=1,
        empties=[Change(kind="empty", round_name="Раунд 1",
                        theme_name="Тема А", price=100,
                        before="пусто, ответ «Наруто»",
                        after="вопрос удалён", order=0)],
        audios=[Change(kind="audio", theme_name="песня.mp3", price=0,
                       before="mp3, 320 кбит, 8,0 МБ",
                       after="opus 192 кбит, 2,1 МБ",
                       title="песня.opus", order=1)])
    tab._fill_table(result)
    assert [tab.table.item(r, 4).text() for r in range(2)] == ["Пустой", "Аудио"]
    assert tab.table.item(0, 6).text() == "вопрос удалён"
    # У дорожки имя файла тоже занимает три колонки — как у картинки.
    assert tab.table.item(1, 1).text() == "песня.mp3"
    assert tab.table.columnSpan(1, 1) == 3
    assert tab.table.item(1, 3).text() == ""
    # А у вопроса объединения нет: раунд, тема и цена стоят каждый на месте.
    assert tab.table.columnSpan(0, 1) == 1


def test_long_file_name_widens_the_spanned_cells(tab):
    """Имя файла не должно обрезаться: на три объединённые колонки ему хватает
    места, а «Раунд» Qt считает по вопросам — про объединение он не знает."""
    long_name = "Onii-chan Dakedo Ai Sae Areba Kankeinai yo ne!_1.jpg"
    result = UpgradeResult(
        questions=1,
        specials=[Change(kind="special", round_name="Р1", theme_name="Тема",
                         price=100, before="с секретом", after="обычный",
                         order=0)],
        unused=[Change(kind="unused", theme_name=long_name,
                       before="30 КБ", after="удалён", order=1)])
    tab._fill_table(result)
    table = tab.table
    width = sum(table.columnWidth(c) for c in (1, 2, 3))
    assert width >= table.fontMetrics().horizontalAdvance(long_name)


def test_spans_do_not_survive_the_next_report(tab):
    """Объединение живёт по номеру строки: не снять его — и следующий отчёт
    слепит колонки не тем правкам."""
    tab._fill_table(UpgradeResult(
        questions=1,
        unused=[Change(kind="unused", theme_name="мусор.jpg", before="1 КБ",
                       after="удалён", order=0)]))
    assert tab.table.columnSpan(0, 1) == 3
    tab._fill_table(UpgradeResult(
        questions=1,
        specials=[Change(kind="special", round_name="Р1", theme_name="Тема",
                         price=100, before="с секретом", after="обычный",
                         order=0)]))
    assert tab.table.columnSpan(0, 1) == 1
    assert tab.table.item(0, 1).text() == "Р1"


def test_changes_table_can_be_scrolled_sideways(tab):
    """Длинное «Стало» больше не режется: колонки — по содержимому, а таблица
    ездит горизонтальной полосой (просьба пользователя)."""
    from PyQt6.QtWidgets import QHeaderView
    header = tab.table.horizontalHeader()
    assert header.stretchLastSection() is False
    last = len(tab.TABLE_HEADERS) - 1
    assert header.sectionResizeMode(last) == QHeaderView.ResizeMode.ResizeToContents


# ── Вкладка-обёртка вокруг единственной страницы ─────────────────────────────
def test_tab_holds_a_single_anime_page(upgrade_tab):
    """Раньше тут было две подвкладки («Аниме-пак» и «Кино-пак»); кино-пак
    убрали — осталась одна страница без видимой полосы вкладок."""
    assert list(upgrade_tab.pages) == ["anime"]
    assert upgrade_tab.pages["anime"].collect().profile == "anime"
    assert upgrade_tab.current_profile == "anime"
    assert upgrade_tab.current_page is upgrade_tab.pages["anime"]


def test_settings_round_trip_through_the_tab(upgrade_tab):
    upgrade_tab.pages["anime"].sp_max_variants.setValue(3)
    data = upgrade_tab.get_settings()
    assert data["profiles"]["anime"]["max_variants"] == 3
    upgrade_tab.pages["anime"].sp_max_variants.setValue(8)
    upgrade_tab.apply_settings(data)
    assert upgrade_tab.pages["anime"].sp_max_variants.value() == 3


def test_old_profiles_settings_ignore_the_movie_page(upgrade_tab):
    """Сохранённые с версии с двумя подвкладками настройки читаются как есть —
    записи про «movie» просто ни на что больше не влияют."""
    upgrade_tab.apply_settings({"profiles": {"anime": {"max_variants": 5},
                                             "movie": {"max_variants": 11}},
                                "current": "movie"})
    assert upgrade_tab.pages["anime"].sp_max_variants.value() == 5


def test_old_flat_settings_are_read_as_the_anime_pack(upgrade_tab):
    """До подвкладок настройки лежали одним плоским словарём: терять их при
    обновлении нельзя."""
    upgrade_tab.apply_settings({"max_variants": 5, "audio_kbps": 96})
    assert upgrade_tab.pages["anime"].sp_max_variants.value() == 5
    assert upgrade_tab.pages["anime"].cb_aud_kbps.currentText() == "96"


def test_set_siq_goes_to_the_page(upgrade_tab, tmp_path):
    path = _siq(tmp_path)
    assert upgrade_tab.set_siq(path) is True
    assert upgrade_tab.pages["anime"]._siq == path


# ── Новые функции на форме ───────────────────────────────────────────────────
def test_video_is_off_by_default_but_the_rest_is_on(tab):
    s = tab.collect()
    assert s.compress_video is False        # перекод ролика идёт минутами
    assert s.drop_unused is True
    assert s.strip_known_labels is True
    assert s.audio_norm is False            # чужую громкость молча не двигаем


def test_video_and_garbage_toggle_independently(tab):
    tab.grp_video.setChecked(True)
    assert tab.collect().compress_video is True
    assert tab.collect().drop_unused is True
    tab.grp_unused.setChecked(False)
    assert tab.collect().drop_unused is False
    assert tab.collect().compress_video is True
    tab.chk_known_labels.setChecked(False)
    assert tab.collect().strip_known_labels is False


def test_video_settings_survive_save_and_load(tab):
    tab.grp_video.setChecked(True)
    tab.sp_vid_min.setValue(50.0)
    tab.chk_vid_non_av1.setChecked(False)
    tab.sp_vid_crf.setValue(30)
    tab.sp_vid_preset.setValue(6)
    tab.cb_vid_height.setCurrentIndex(tab.cb_vid_height.findData(720))
    data = tab.get_settings()
    tab.reset_settings()
    assert tab.collect().compress_video is False
    tab.apply_settings(data)
    s = tab.collect()
    assert (s.compress_video, s.video_min_mb, s.video_non_av1) == (True, 50.0,
                                                                   False)
    assert (s.video_crf, s.video_preset, s.video_height) == (30, 6, 720)


def test_norm_numbers_are_greyed_out_without_the_norm(tab):
    tab.chk_aud_norm.setChecked(False)
    assert not tab.sp_norm_i.isEnabled()
    tab.chk_aud_norm.setChecked(True)
    assert tab.sp_norm_i.isEnabled() and tab.sp_norm_tp.isEnabled()


def test_norm_settings_survive_save_and_load(tab):
    tab.chk_aud_norm.setChecked(True)
    tab.sp_norm_i.setValue(-16.0)
    tab.sp_norm_lra.setValue(7.0)
    tab.sp_norm_tp.setValue(-2.0)
    data = tab.get_settings()
    tab.reset_settings()
    tab.apply_settings(data)
    s = tab.collect()
    assert s.audio_norm is True
    assert (s.audio_norm_i, s.audio_norm_lra, s.audio_norm_tp) == (-16.0, 7.0,
                                                                   -2.0)


def test_video_heights_are_the_ones_from_the_list(tab):
    from animepack_upgrade import VIDEO_HEIGHTS
    got = [tab.cb_vid_height.itemData(i)
           for i in range(tab.cb_vid_height.count())]
    assert got == list(VIDEO_HEIGHTS)
    assert tab.cb_vid_height.itemText(0) == "Исходное"


def test_table_names_video_and_garbage_rows(tab):
    result = UpgradeResult(path="p.siq", questions=1)
    result.videos.append(Change(kind="video", theme_name="ролик.mp4",
                                before="mkv, h264, 40,0 МБ",
                                after="av1 crf 45, 720p, 9,0 МБ", order=1))
    result.unused.append(Change(kind="unused", theme_name="лишняя.jpg",
                                before="500 КБ",
                                after="файл удалён (ссылок на него нет)",
                                order=2))
    tab._fill_table(result)
    assert tab.table.rowCount() == 2
    assert [tab.table.item(i, 4).text() for i in range(2)] == ["Видео", "Мусор"]
    # У файла в архиве цены нет: это не вопрос.
    assert [tab.table.item(i, 3).text() for i in range(2)] == ["", ""]


def test_log_says_which_profile_is_running(tab, tmp_path, monkeypatch):
    seen = []

    class FakeMain:
        def log(self, msg):
            seen.append(msg)

    tab.main = FakeMain()
    tab.log("проба")
    assert seen == ["[Аниме-пак] проба"]
