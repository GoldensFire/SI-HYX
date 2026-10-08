"""Общие заготовки тестов test_animepack: пакеты, подставные клиенты и фикстуры."""
import xml.etree.ElementTree as ET

import pytest


from animepack import (
    FRAME_KIND,
    AnimePackGenerator,
    SongCandidate,
    clear_user_list_cache,
    song_kind,
)


@pytest.fixture(autouse=True)
def _forget_user_lists():
    """Кэш списков пользователей живёт в модуле и переживает тест — чистим его,
    иначе ники из соседнего теста «уже спрошены» и сеть не трогается вовсе."""
    clear_user_list_cache()
    yield
    clear_user_list_cache()

# ── Заготовки данных ─────────────────────────────────────────────────────────
def make_song(**over):
    song = {
        "annId": 6592, "annSongId": 7868, "audio": "a6h06o.mp3",
        "animeENName": "Death Note", "animeJPName": "Death Note",
        "animeType": "TV", "animeCategory": "TV",
        "linked_ids": {"myanimelist": 1535},
        "songType": "Opening 1", "songName": "the WORLD",
        "songArtist": "Nightmare", "songCategory": "Standard",
        "songDifficulty": 85.0, "songLength": 79.0,
        "isDub": False, "isRebroadcast": False,
    }
    song.update(over)
    return song

def make_anime(**over):
    anime = {
        "id": 1535, "malId": 1535, "name": "Death Note",
        "russian": "Тетрадь смерти", "english": "Death Note",
        "japanese": "デスノート", "synonyms": ["DN"],
        "licenseNameRu": "Тетрадь смерти", "franchise": "death_note",
        "score": 8.6, "kind": "tv",
        "genres": [{"id": "27", "name": "Shounen"}, {"id": "40", "name": "Psychological"}],
        "poster": {"originalUrl": "https://shiki/poster.jpg"},
        "screenshots": [{"originalUrl": f"https://shiki/{i}.jpg"} for i in range(6)],
        "airedOn": {"year": 2006},
        "statusesStats": [{"status": "completed", "count": 1000},
                          {"status": "planned", "count": 500}],
    }
    anime.update(over)
    return anime

def make_candidate(**over):
    song = make_song(**over.pop("song", {}))
    anime = make_anime(**over.pop("anime", {}))
    cand = SongCandidate(song=song, anime=anime,
                         kind=song_kind(song["songType"]) or "opening",
                         **over)
    return cand

# ── content.xml ──────────────────────────────────────────────────────────────
def _parse(xml_bytes):
    root = ET.fromstring(xml_bytes)
    ns = {"s": "https://github.com/VladimirKhil/SI/blob/master/assets/siq_5.xsd"}
    return root, ns

# ── Отбор ────────────────────────────────────────────────────────────────────
def _generator(settings, songs, animes, **kw):
    """Генератор с подменёнными источниками (сети нет вовсе)."""
    class FakeAnisong:
        def songs_by_mal_ids(self, ids):
            return [s for s in songs
                    if (s.get("linked_ids") or {}).get("myanimelist") in ids]
        songs_by_ann_ids = songs_by_mal_ids

    class FakeShiki:
        def animes_by_ids(self, ids):
            ids = {int(i) for i in ids}
            return [a for a in animes if int(a["malId"]) in ids]

        def user_anime_ids(self, nick, statuses, **_kw):
            return kw.get("user_ids", {}).get(nick, [])

        def franchise_parts(self, keys):
            return kw.get("franchise_parts", {})

    class FakeMal:
        def user_anime_ids(self, nick, statuses, **_kw):
            return kw.get("user_ids", {}).get(nick, [])

    gen = AnimePackGenerator(settings, session=object(), amq=object(),
                             anisong=FakeAnisong(), mal=FakeMal(),
                             shikimori=FakeShiki(), **{
                                 k: v for k, v in kw.items() if k != "user_ids"})
    return gen

def _pair(mal_id, franchise="fr", song_over=None, anime_over=None):
    song = make_song(**{"linked_ids": {"myanimelist": mal_id},
                        "annSongId": mal_id * 10, **(song_over or {})})
    # Название у каждой франшизы своё: тайтлы с общим корнем имени генератор
    # считает частями одной серии и в один пак не пускает.
    anime = make_anime(**{"malId": mal_id, "id": mal_id, "franchise": franchise,
                          "russian": f"Тетрадь смерти {franchise}",
                          **(anime_over or {})})
    return song, anime

# ── Выбор кадра: случайный и без повторов ────────────────────────────────────
def _frame_cand(anime=None):
    return SongCandidate(song={}, anime=anime or make_anime(), kind=FRAME_KIND)
