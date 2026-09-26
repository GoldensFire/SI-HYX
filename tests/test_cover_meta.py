# -*- coding: utf-8 -*-
"""Метаданный гейт каверов: каждый тест закрывает разобранный живой случай.

Проверки выросли из корпуса в 722 настоящих результата поиска YouTube
(tools/cover_probe.py --collect). Заголовки в тестах не придуманы.
"""
import cover_meta
from cover_meta import classify, normalize, screen, song_ref


def _song(name="unravel", anime="Tokyo Ghoul", kind="Opening 1",
          artist="TK from Ling tosite sigure", siblings=()):
    return song_ref({"annSongId": 1, "songName": name, "songArtist": artist,
                     "songType": kind, "animeENName": anime,
                     "animeJPName": anime, "animeAltName": []}, siblings)


def _ok(title, channel="", duration=240, song=None, views=None):
    return classify(title, channel, duration, song or _song(), views)


# ── нормализация названий ────────────────────────────────────────────────
def test_normalize_drops_punctuation_and_diacritics():
    assert normalize("Seija-tachi") == normalize("Seijatachi") == "seijatachi"
    assert normalize("Kimi no Shiranai Monogatari") == "kiminoshiranaimonogatari"
    # Кандзи и кану оставляем: японские названия ищутся той же подстрокой.
    assert "聖者たち" in normalize("Ending 「聖者たち」")


def test_similar_title_is_not_a_match():
    """«Nameless - The Forsaken Heart» — другая песня, а не «Nameless Heart».

    Самая частая ловушка корпуса; отсекается одной нормализацией, без звука."""
    song = _song("Nameless Heart", "Rokka no Yuusha", "Ending 3", "Aoi Yuki")
    assert _ok("Nameless - The Forsaken Heart", song=song)["reason"] == "name_mismatch"
    assert _ok("[cover] Nameless Heart - 六花の勇者", song=song)["state"] == "ok"


def test_long_vowel_spelling_still_matches():
    """Boukyaku / Bōkyaku / Bokyaku — одно и то же название."""
    song = _song("Uchiyoserareta Boukyaku no Zankyou ni", "Beautiful Bones",
                 "Ending 1", "TECHNOBOYS")
    verdict = _ok('"Uchiyoserareta Bokyaku no Zankyo ni" piano cover',
                  duration=123, song=song)
    assert verdict["state"] == "ok"


# ── мусор, который звук пропустил бы насквозь ────────────────────────────
def test_reaction_tutorial_and_derivatives_are_rejected():
    for title, reason in (
            ("Tokyo Ghoul Unravel REACTION", "reaction"),
            ("unravel - Tokyo Ghoul OP Piano Tutorial || Synthesia", "tutorial"),
            ("[Nightcore] Tokyo Ghoul - unravel", "derivative"),
            ("unravel - Off Vocal / Karaoke", "derivative"),
            ("Top 10 Openings Anime 2014 unravel", "compilation"),
            ("Vietsub | unravel - Tokyo Ghoul Opening", "subbed"),
            ("Tokyo Ghoul unravel 「AMV」", "clipped"),
            ("unravel (Ep 6 BGM) Tokyo Ghoul", "clipped")):
        assert _ok(title)["reason"] == reason, title


def test_official_upload_and_topic_channel_rejected():
    assert _ok('Tokyo Ghoul Opening | "Unravel" by TK',
               "Crunchyroll")["reason"] == "official_channel"
    assert _ok("unravel", "TK from Ling tosite sigure - Topic",
               )["reason"] == "official_channel"


def test_ai_voice_clone_rejected():
    assert _ok("unravel 【AI Cover】 Tokyo Ghoul")["reason"] == "derivative"


# ── маркер исполнения ────────────────────────────────────────────────────
def test_performance_marker_is_required():
    assert _ok("Tokyo Ghoul - Unravel")["reason"] == "no_performance_marker"
    for title in ("Tokyo Ghoul OP Unravel Guitar Cover",
                  "unravel / TK from 凛として時雨 歌ってみた",
                  "Unravel - Tokyo Ghoul OP [Piano]",
                  "unravel Tokyo Ghoul (russian version)",
                  "【Rainych】 Unravel - Tokyo Ghoul OP1",
                  "unravel / TK (東京喰種) COVERD BY Rika*"):
        assert _ok(title)["state"] == "ok", title


def test_format_tag_in_brackets_is_not_a_nickname():
    """«【TV】…» — пометка формата, а не подпись исполнителя."""
    assert _ok("【TV】Tokyo Ghoul Opening 1 - unravel",
               )["reason"] == "no_performance_marker"


def test_channel_words_must_not_reject_a_real_cover():
    """Регрессия: слово Sheets в НАЗВАНИИ КАНАЛА убивало кавер как туториал.

    «Animenz Piano Sheets» — канал настоящих фортепианных каверов, и мусорные
    признаки поэтому ищутся только в заголовке."""
    verdict = _ok("Unravel - Tokyo Ghoul OP [Piano]", "Animenz Piano Sheets")
    assert verdict["state"] == "ok" and verdict["type"] == "piano"


def test_sheets_alone_does_not_make_a_tutorial():
    """Исполнители сплошь дописывают ноты к настоящему каверу."""
    song = _song("Ima Koko", "Tsukigakirei", "Opening 1", "Nao Touyama")
    assert _ok("Tsuki Ga Kirei OP | Imakoko | Piano Cover with Sheets!",
               duration=107, song=song)["state"] == "ok"
    assert _ok("unravel piano sheet music")["reason"] == "tutorial"


# ── коллизии внутри одного аниме ─────────────────────────────────────────
def test_cover_of_a_sibling_song_is_rejected():
    song = _song("Secret Sky", "Rokka no Yuusha", "Ending 1", "MICHI",
                 siblings=("Nameless Heart", "Cry for the Truth"))
    assert _ok("Rokka no Yuusha ED3 - Nameless Heart Piano Cover",
               duration=101, song=song)["reason"] == "other_song"
    # Названы и наша песня, и соседняя — это медли, вопрос из него не вырезать.
    assert _ok("Cry For The Truth/Secret Sky 【VOCALOID Cover】", duration=96,
               song=song)["reason"] == "medley"


def test_sibling_named_like_the_anime_is_ignored():
    """Регрессия: у «Tsukigakirei» так зовётся ЭНДИНГ.

    Пока этот «сосед» участвовал в проверке, он находился в каждом втором
    заголовке просто потому, что там назван тайтл, — и двадцать настоящих
    каверов опенинга улетали как медли."""
    song = _song("Ima Koko", "Tsukigakirei", "Opening 1", "Nao Touyama",
                 siblings=("Tsuki ga Kirei", "Fragile"))
    assert song["sibling_keys"] == ["fragile"]
    assert _ok('Tsuki ga Kirei OP - "Ima Koko" Guitar Cover', duration=111,
               song=song)["state"] == "ok"


def test_song_named_like_the_anime_is_only_weak():
    """Совпадение по названию ничего не доказывает, если оно равно названию
    аниме: под него подходят каверы всех песен этого тайтла."""
    song = _song("Tsuki ga Kirei", "Tsukigakirei", "Ending 1", "Nao Touyama")
    assert song["degenerate"] is True
    assert _ok("Tsuki ga Kirei ED Band cover", duration=91,
               song=song)["strength"] == cover_meta.WEAK
    # А обычное название даёт полноценное совпадение.
    assert _ok("Tokyo Ghoul OP Unravel Guitar Cover")["strength"] == cover_meta.STRONG


def test_wrong_position_rejected():
    """Опенинг там, где нужен эндинг. Здесь тип песни и окупается."""
    song = _song("Tsuki ga Kirei", "Tsukigakirei", "Ending 1", "Nao Touyama")
    assert _ok('Tsuki ga Kirei OP "Imakoko" (Violin Cover)', duration=95,
               song=song)["reason"] == "wrong_position"
    # Названы оба вида — не отказываем, пусть решает звук.
    assert _ok("Tsuki ga Kirei OP and ED cover", duration=95,
               song=song)["state"] == "ok"


# ── длительность и пул ───────────────────────────────────────────────────
def test_duration_bounds():
    assert _ok("unravel guitar cover #shorts", duration=31)["reason"] == "too_short"
    assert _ok("unravel cover", duration=5300)["reason"] == "too_long"


def test_screen_orders_by_evidence_and_caps_weak():
    """Сперва качаются назвавшие песню; слабых пускаем не больше WEAK_LIMIT —
    у плодовитого исполнителя их десятки, и каждый стоит отдельной загрузки."""
    song = _song("Ima Koko", "Tsukigakirei", "Opening 1", "Nao Touyama")
    rows = [{"id": f"a{n}", "title": "Tsukigakirei band cover", "channel": "",
             "duration": 100} for n in range(9)]
    rows.append({"id": "z", "title": "Ima Koko guitar cover", "channel": "",
                 "duration": 100})
    pool, bad = screen(rows, song, limit=99)
    assert pool[0]["id"] == "z" and pool[0]["via"] == "song"
    assert [r["via"] for r in pool[1:]] == ["anime"] * cover_meta.WEAK_LIMIT
    assert len(pool) == 1 + cover_meta.WEAK_LIMIT
    assert not bad


# ── разбор расширенного корпуса (421 заголовок, 15 песен) ────────────────
def test_short_sibling_name_inside_a_word_is_not_a_sibling():
    """Регрессия, стоившая восьми настоящих каверов: у «Clannad» есть вставка
    «Ana», а у «Fullmetal Alchemist» — «Over» и «Rain». Подстрока находилась
    внутри слов Clannad, cover и Rainych, и каверы улетали как медли."""
    song = _song("Dango Daikazoku", "Clannad", "Ending 1", "Chata",
                 siblings=("Ana", "Over", "Kage Futatsu"))
    assert _ok("Dango Daikazoku Clannad - Cover", duration=92,
               song=song)["state"] == "ok"
    fma = _song("again", "Fullmetal Alchemist: Brotherhood", "Opening 1", "YUI",
                siblings=("Rain", "Hologram", "Period"))
    assert _ok("【Rainych】AGAIN - Fullmetal Alchemist : Brotherhood OP 1 (cover)",
               duration=257, song=fma)["state"] == "ok"
    # А названное целым словом имя соседней песни по-прежнему отвергается.
    assert _ok("Fullmetal Alchemist OP2 Hologram cover", duration=248,
               song=fma)["reason"] == "other_song"


def test_anime_called_by_one_of_its_words_still_counts():
    """«Evangelion» вместо «Neon Genesis Evangelion», «FMA BROTHERHOOD» вместо
    «Fullmetal Alchemist: Brotherhood» — так подписаны десятки настоящих
    каверов. Совпадение слабое: доказывать тождество слову «Evangelion» нечем."""
    song = _song("Zankoku na Tenshi no Thesis", "Neon Genesis Evangelion",
                 "Opening 1", "Yoko Takahashi")
    verdict = _ok('Evangelion - "Cruel Angel\'s Thesis" (FULL Opening) '
                  '| ENGLISH ver | AmaLee', duration=257, song=song)
    assert verdict["state"] == "ok" and verdict["strength"] == cover_meta.WEAK
    assert verdict["via"] == "anime"
    # Слово короче ANIME_WORD в ключи не идёт: «Titan» и «Ghoul» встречаются
    # в заголовках сами по себе.
    assert "titan" not in _song(anime="Attack on Titan")["anime_word_keys"]


def test_fancy_unicode_letters_still_read_as_a_marker():
    """«Torches / Aimer (𝗰𝗼𝘃𝗲𝗿)» — математические жирные буквы. Без NFKC слова
    cover в заголовке нет вовсе, и кавер улетал без маркера."""
    song = _song("Torches", "Vinland Saga", "Ending 1", "Aimer")
    assert _ok("Torches / Aimer (𝗰𝗼𝘃𝗲𝗿) | yoei.", duration=296,
               song=song)["state"] == "ok"


def test_japanese_and_credit_markers_count_as_performance():
    fma = _song("again", "Fullmetal Alchemist: Brotherhood", "Opening 1", "YUI")
    tank = _song("Tank!", "Cowboy Bebop", "Opening 1", "Seatbelts")
    for song, title in (
            (fma, "again / YUI 【弾き語り】【鋼の錬金術師】"),
            (tank, "Tank! - Cowboy Bebop Opening Theme - Performed By DA Jazz Alumni"),
            (tank, "Tank! (from Cowboy Bebop) by Yoko Kanno | Arr. John Wasson "
                   "| Jazz Ensemble"),
            (None, "unravel Tokyo Ghoul (Versión Español Latino)"),
            (None, "unravel • english - ver. by Jenny (Tokyo Ghoul OP)"),
            (None, 'unravel "Beautiful Cruel World" (English Version)')):
        assert _ok(title, duration=253, song=song)["state"] == "ok", title


def test_vocal_lesson_is_a_tutorial():
    """Школа «シアーミュージック» встретилась так на трёх песнях подряд: поют
    по-настоящему, но вперемешку с разбором, как это делать."""
    assert _ok("【ボイストレーナーが歌う】unravel / TK【歌い方解説付き by シアーミュージック】",
               duration=208)["reason"] == "tutorial"


def test_karaoke_is_rejected_even_with_a_performance_marker():
    """Караоке не берём вовсе (просьба пользователя): аранжировка там
    оригинальная, а поверх неё — посторонний голос и зал."""
    assert _ok("Minato Aqua - unravel (Karaoke Cover) (Tokyo Ghoul OP)",
               duration=288)["reason"] == "karaoke"
    assert _ok("unravel Tokyo Ghoul - Karaoke ver.")["reason"] == "karaoke"
    # «off vocal» и «минус» остались жёсткими: так подписывают дорожку без голоса.
    assert _ok("unravel - Off Vocal / Караоке")["reason"] == "derivative"


def test_live_recordings_are_rejected():
    """Живьём — мимо: та же аранжировка, зал в микрофоне и худший звук."""
    for title in ("unravel - Tokyo Ghoul OP cover (Live)",
                  "TK from Ling tosite sigure - unravel [Live Session]",
                  "unravel — кавер на концерте"):
        assert _ok(title, duration=240)["reason"] == "live", title


def test_playing_along_to_the_original_is_rejected():
    """Барабаны и бас играют ПОВЕРХ записи: оригинальный вокал слышно целиком."""
    for title in ("unravel - Tokyo Ghoul OP [Drum Cover]",
                  "Tokyo Ghoul - unravel | Bass Cover",
                  "unravel - guitar playthrough (Tokyo Ghoul)",
                  "unravel Tokyo Ghoul guitar cover with backing track"):
        assert _ok(title, duration=240)["reason"] == "playalong", title


def test_the_author_admitting_a_bad_recording_is_rejected():
    for title in ("unravel Tokyo Ghoul cover (bad quality, sorry)",
                  "unravel - Tokyo Ghoul cover [practice]",
                  "unravel Tokyo Ghoul cover — first take"):
        assert _ok(title, duration=240)["reason"] == "low_quality", title


def test_a_barely_watched_upload_is_rejected():
    """Десяток просмотров — это запись с телефона, спетая мимо нот."""
    assert _ok("unravel - Tokyo Ghoul OP Cover", duration=240,
               views=12)["reason"] == "low_views"
    assert _ok("unravel - Tokyo Ghoul OP Cover", duration=240,
               views=50_000)["state"] == "ok"
    # Просмотров нет в записи вовсе — это «неизвестно», а не «ноль».
    assert _ok("unravel - Tokyo Ghoul OP Cover", duration=240)["state"] == "ok"


def test_meme_and_drawing_videos_are_not_performances():
    for title, reason in (
            ("猫が歌ってみた「unravel」Cat singing \"unravel\"", "derivative"),
            ("Eren and Mikasa sing unravel | Tokyo Ghoul animatic", "clipped"),
            ("【unravel - Speeddraw (C.V; Yuuki Aoi) - Tokyo Ghoul】", "clipped")):
        assert _ok(title, duration=145)["reason"] == reason, title
