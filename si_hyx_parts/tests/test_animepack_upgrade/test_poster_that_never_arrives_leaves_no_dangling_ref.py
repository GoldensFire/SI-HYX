# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""test_poster_that_never_arrives_leaves_no_dangling_ref. Public namespace: test_animepack_upgrade."""
import test_animepack_upgrade as _api


def test_poster_that_never_arrives_leaves_no_dangling_ref(tmp_path, monkeypatch):
    """Постер не дался — ссылку из вопроса надо убрать: пак не должен звать
    файл, которого в нём нет."""
    monkeypatch.setattr(_api.PackUpgrader, "_fetch", lambda self, url: b"raw")
    monkeypatch.setattr(_api.PackUpgrader, "_to_avif",
                        lambda self, raw, out, limit_kb=None: False)
    content = _api._pack(_api._q5(100, answer="Блич"))
    result = _api._run(tmp_path, content, _api._poster_settings(), api=_api.FakeApi([_api.POSTERED]))
    assert result.posters == []
    root, ns = _api._out_root(result)
    assert not [i for i in root.iter(_api.tag_fn(ns)("item"))
                if (i.get("type") or "") == "image"]
    with _api.zipfile.ZipFile(result.path) as zf:
        assert not [n for n in zf.namelist() if n.endswith(".avif")]

test_poster_that_never_arrives_leaves_no_dangling_ref.__module__ = _api.__name__
_api.test_poster_that_never_arrives_leaves_no_dangling_ref = test_poster_that_never_arrives_leaves_no_dangling_ref

def test_failed_poster_is_taken_out_of_a_v4_question(tmp_path, monkeypatch):
    monkeypatch.setattr(_api.PackUpgrader, "_fetch", lambda self, url: b"raw")
    monkeypatch.setattr(_api.PackUpgrader, "_to_avif",
                        lambda self, raw, out, limit_kb=None: False)
    content = _api._pack(_api._q4(100, answer="Блич"))
    result = _api._run(tmp_path, content, _api._poster_settings(), api=_api.FakeApi([_api.POSTERED]))
    root, ns = _api._out_root(result)
    atoms = root.find(f'.//{_api.tag_fn(ns)("scenario")}').findall(_api.tag_fn(ns)("atom"))
    assert [a.get("type") for a in atoms] == [None, "marker"]
    assert result.posters == []

test_failed_poster_is_taken_out_of_a_v4_question.__module__ = _api.__name__
_api.test_failed_poster_is_taken_out_of_a_v4_question = test_failed_poster_is_taken_out_of_a_v4_question

def test_failed_download_does_not_break_the_run(tmp_path, monkeypatch):
    def boom(self, url):
        raise OSError("сеть отвалилась")

    monkeypatch.setattr(_api.PackUpgrader, "_fetch", boom)
    content = _api._pack(_api._q5(100, answer="Блич"))
    lines = []
    result = _api._run(tmp_path, content, _api._poster_settings(),
                  api=_api.FakeApi([_api.POSTERED]), log=lines.append)
    assert result.posters == [] and result.path
    assert any("сеть отвалилась" in line for line in lines)

test_failed_download_does_not_break_the_run.__module__ = _api.__name__
_api.test_failed_download_does_not_break_the_run = test_failed_download_does_not_break_the_run

def test_remove_poster_takes_the_picture_out_of_both_formats():
    v5 = _api.ET.fromstring('<question><params><param name="answer" type="content">'
                       '<item type="image" isRef="True">p.avif</item>'
                       "</param></params></question>")
    assert _api.remove_poster(v5, "p.avif") is True
    assert not list(v5.iter("item"))
    v4 = _api.ET.fromstring('<question><scenario><atom>Текст</atom>'
                       '<atom type="marker"/><atom type="image">@p.avif</atom>'
                       "</scenario></question>")
    assert _api.remove_poster(v4, "p.avif") is True
    assert [a.get("type") for a in v4.iter("atom")] == [None, "marker"]
    assert _api.remove_poster(v4, "нет.avif") is False

test_remove_poster_takes_the_picture_out_of_both_formats.__module__ = _api.__name__
_api.test_remove_poster_takes_the_picture_out_of_both_formats = test_remove_poster_takes_the_picture_out_of_both_formats

def test_poster_threads_do_not_outlive_the_run(tmp_path, monkeypatch):
    """Потоки постеров закрываются вместе с прогоном: висящий пул держал бы
    приложение открытым и после выхода."""
    _api._fake_poster(monkeypatch)
    up = _api.PackUpgrader(_api._siq(tmp_path, _api._pack(_api._q5(100, answer="Блич"))),
                      _api._poster_settings(), api=_api.FakeApi([_api.POSTERED]))
    up.run()
    assert up._pool is None
    assert not [t for t in _api.threading.enumerate()
                if t.name.startswith("siqposter")]

test_poster_threads_do_not_outlive_the_run.__module__ = _api.__name__
_api.test_poster_threads_do_not_outlive_the_run = test_poster_threads_do_not_outlive_the_run

def test_stop_in_the_middle_of_media_leaves_nothing_behind(tmp_path,
                                                           monkeypatch):
    """«Стоп» посреди пачки кодировок: пак не пишется, временные файлы убраны,
    потоки закрыты. Кодируется теперь по нескольку файлов разом — важно, что
    остановка добирается до каждого."""
    started = []

    def slow(self, raw, out, limit_kb=None):
        started.append(raw)
        with open(out, "wb") as f:
            f.write(b"A" * 400)
        return True

    monkeypatch.setattr(_api.PackUpgrader, "_to_avif", slow)
    names = [f"кадр{i}.jpg" for i in range(6)]
    media = {f"Images/{n}": _api.HEAVY for n in names}
    content = _api._pack("".join(_api._q5_image(100, n) for n in names))
    up = _api.PackUpgrader(_api._siq(tmp_path, content, media=media), _api._img_settings(),
                      api=_api.FakeApi(), should_stop=lambda: True)
    result = up.run()
    assert result.cancelled and not result.path
    assert result.images == [] and started == []       # кодировать не начали
    assert list(tmp_path.glob("*апгрейд*")) == []
    assert not [t for t in _api.threading.enumerate()
                if t.name.startswith("siqmedia")]

test_stop_in_the_middle_of_media_leaves_nothing_behind.__module__ = _api.__name__
_api.test_stop_in_the_middle_of_media_leaves_nothing_behind = test_stop_in_the_middle_of_media_leaves_nothing_behind

def test_stop_during_posters_closes_the_threads(tmp_path, monkeypatch):
    _api._fake_poster(monkeypatch)
    up = _api.PackUpgrader(_api._siq(tmp_path, _api._pack(_api._q5(100, answer="Блич"))),
                      _api._poster_settings(), api=_api.FakeApi([_api.POSTERED]),
                      should_stop=lambda: True)
    result = up.run()
    assert result.cancelled and not result.path
    assert up._pool is None
    assert not [t for t in _api.threading.enumerate()
                if t.name.startswith("siqposter")]

test_stop_during_posters_closes_the_threads.__module__ = _api.__name__
_api.test_stop_during_posters_closes_the_threads = test_stop_during_posters_closes_the_threads

def test_no_temp_files_are_left_behind(tmp_path, monkeypatch):
    """Ни одна ветка не забывает свой временный файл — ни удачная, ни «после
    сжатия не легче», ни сорвавшаяся кодировка. Раньше в %TEMP% копились
    недоеденные siqimg_*/siqaud_* с каждого прогона."""
    import animepack_upgrade as U

    def picky(self, raw, out, limit_kb=None):
        size = _api.os.path.getsize(raw)
        if size == len(_api.HEAVY) + 1:              # «битая» — кодировка сорвалась
            return False
        with open(out, "wb") as f:              # «толстая» — стала тяжелее
            f.write(b"A" * (len(_api.HEAVY) + 2 if size == len(_api.HEAVY) + 2 else 400))
        return True

    monkeypatch.setattr(_api.PackUpgrader, "_to_avif", picky)
    media = {"Images/ок.jpg": _api.HEAVY, "Images/битая.jpg": _api.HEAVY + b"J",
             "Images/толстая.jpg": _api.HEAVY + b"JJ"}
    content = _api._pack(_api._q5_image(100, "ок.jpg") + _api._q5_image(200, "битая.jpg")
                    + _api._q5_image(300, "толстая.jpg"))
    before = set(_api.os.listdir(U._temp_dir()))
    result = _api.PackUpgrader(_api._siq(tmp_path, content, media=media),
                          _api._img_settings(), api=_api.FakeApi()).run()
    assert [c.theme_name for c in result.images] == ["ок.jpg"]
    assert set(_api.os.listdir(U._temp_dir())) - before == set()

test_no_temp_files_are_left_behind.__module__ = _api.__name__
_api.test_no_temp_files_are_left_behind = test_no_temp_files_are_left_behind

# ── Известные подписи («Назвать персонажа») ──────────────────────────────────
def test_known_label_goes_even_if_one_question_lacks_it(tmp_path):
    """Живой случай из «Anime by Hinoriku 6», тема «Hayami Saori»: «Назвать
    персонажа» стоит в семи вопросах из восьми, а восьмой спрашивает совсем
    другое — по правилу «в каждом» подпись оставалась во всех семи."""
    qs = "".join(_api._q5_items(p, "<item>Назвать персонажа</item>" + _api._shot())
                 for p in (100, 200, 300))
    qs += _api._q5_items(400, "<item>А сколько их было в зимнем сезоне?</item>")
    result = _api._run(tmp_path, _api._themes(f"Hayami Saori|{qs}"), _api.KNOWN_REPEATS)
    assert len(result.repeats) == 3
    assert {c.before for c in result.repeats} == {"Назвать персонажа"}
    assert all("известная подпись" in c.after for c in result.repeats)
    root, _ns = _api._out_root(result)
    texts = [el.text for el in root.iter()
             if el.text and "персонажа" in str(el.text)]
    assert texts == []                       # подписи в паке не осталось
    # А чужой вопрос — тот, что спрашивал своё, — цел.
    assert any("зимнем сезоне" in (el.text or "") for el in root.iter())

test_known_label_goes_even_if_one_question_lacks_it.__module__ = _api.__name__
_api.test_known_label_goes_even_if_one_question_lacks_it = test_known_label_goes_even_if_one_question_lacks_it

def test_known_label_can_be_switched_off(tmp_path):
    qs = "".join(_api._q5_items(p, "<item>Назвать персонажа</item>" + _api._shot())
                 for p in (100, 200))
    qs += _api._q5_items(300, "<item>Своё</item>" + _api._shot())
    assert _api._run(tmp_path, _api._themes(f"Тема|{qs}"), _api.ONLY_REPEATS).repeats == []

test_known_label_can_be_switched_off.__module__ = _api.__name__
_api.test_known_label_can_be_switched_off = test_known_label_can_be_switched_off

def test_known_label_never_empties_a_question(tmp_path):
    """Кроме подписи в вопросе ничего нет — не трогаем: играть станет нечем."""
    qs = (_api._q5_items(100, "<item>Назвать аниме</item>")
          + _api._q5_items(200, "<item>Назвать аниме</item>" + _api._shot())
          + _api._q5_items(300, "<item>Своё</item>" + _api._shot()))
    result = _api._run(tmp_path, _api._themes(f"Тема|{qs}"), _api.KNOWN_REPEATS)
    assert [c.price for c in result.repeats] == [200]

test_known_label_never_empties_a_question.__module__ = _api.__name__
_api.test_known_label_never_empties_a_question = test_known_label_never_empties_a_question

def test_known_labels_are_matched_without_case_and_punctuation():
    q = _api.ET.fromstring('<question><params><param name="question">'
                      "<item>назвать ПЕРСОНАЖА:</item></param></params>"
                      "</question>")
    assert _api.known_labels_in([q]) == ["назвать ПЕРСОНАЖА:"]
    assert "Назвать персонажа" in _api.KNOWN_LABELS

test_known_labels_are_matched_without_case_and_punctuation.__module__ = _api.__name__
_api.test_known_labels_are_matched_without_case_and_punctuation = test_known_labels_are_matched_without_case_and_punctuation

def test_known_label_and_repeated_text_live_together(tmp_path):
    """Одна подпись стоит везде (общее правило), другая — не везде (список)."""
    qs = (_api._q5_items(100, "<item>Назвать персонажа</item>"
                    "<item>Скрин ниже</item>" + _api._shot())
          + _api._q5_items(200, "<item>Скрин ниже</item>" + _api._shot()))
    result = _api._run(tmp_path, _api._themes(f"Тема|{qs}"), _api.KNOWN_REPEATS)
    assert {c.before for c in result.repeats} == {"Назвать персонажа",
                                                  "Скрин ниже"}
    assert len(result.repeats) == 3

test_known_label_and_repeated_text_live_together.__module__ = _api.__name__
_api.test_known_label_and_repeated_text_live_together = test_known_label_and_repeated_text_live_together
