"""Общие заготовки тестов test_animepack_upgrade: пакеты, подставные клиенты и фикстуры."""
import zipfile


from animepack_upgrade import PackUpgrader, UpgradeSettings, norm_title, parse_content, tag_fn


# ── Фабрики ──────────────────────────────────────────────────────────────────
def _pack(questions: str, *, ns: str = "", version: str = "5") -> str:
    xmlns = f' xmlns="{ns}"' if ns else ""
    return (f'<?xml version="1.0" encoding="utf-8"?>\n'
            f'<package name="Пак" version="{version}"{xmlns}>'
            '<rounds><round name="Раунд 1"><themes><theme name="Тема А">'
            f'<questions>{questions}</questions>'
            "</theme></themes></round></rounds></package>")

def _q5(price: int, answer: str = "Ответ", qtype: str = "",
        params: str = "", right: str = "") -> str:
    """Вопрос формата v5 (SIGame 7)."""
    attr = f' type="{qtype}"' if qtype else ""
    body = right or f"<right><answer>{answer}</answer></right>"
    return (f'<question price="{price}"{attr}><params>'
            '<param name="question" type="content"><item>Текст</item></param>'
            f"{params}</params>{body}</question>")

def _q4(price: int, answer: str = "Ответ", qtype: str = "") -> str:
    """Вопрос формата v4 (тип — дочерним элементом)."""
    type_el = (f'<type name="{qtype}"><param name="theme">Тема кота</param>'
               f'<param name="price">300</param></type>') if qtype else ""
    return (f'<question price="{price}">{type_el}'
            "<scenario><atom>Текст</atom></scenario>"
            f"<right><answer>{answer}</answer></right></question>")

def _siq(tmp_path, content: str, name: str = "pack.siq", media=None) -> str:
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("content.xml", content)
        for arc, data in (media or {}).items():
            zf.writestr(arc, data, zipfile.ZIP_STORED)
    return str(path)


NARUTO = {
    "id": 20, "malId": 20, "russian": "Наруто", "name": "Naruto",
    "english": "Naruto", "japanese": "ナルト",
    "licenseNameRu": "Наруто. Книга первая",
    "synonyms": ["NARUTO -ナルト-", "Наруто ТВ-1"],
}
BLEACH = {"id": 269, "malId": 269, "russian": "Блич", "name": "Bleach",
          "english": "Bleach", "synonyms": [], "licenseNameRu": ""}


class FakeApi:
    """Shikimori без сети: отдаёт заранее заданные карточки и считает запросы."""

    def __init__(self, cards=None):
        self.cards = list(cards if cards is not None else [NARUTO, BLEACH])
        self.calls = []

    def search_animes_by_name(self, name, limit=0):
        self.calls.append(name)
        needle = norm_title(name)
        # Грубая имитация поиска: отдаём всё, что хоть как-то похоже.
        return [c for c in self.cards
                if any(needle in norm_title(n) or norm_title(n) in needle
                       for n in [c.get("russian"), c.get("name"),
                                 c.get("english")] if n)]

def _run(tmp_path, content, s=None, api=None, **kw):
    s = s or UpgradeSettings()
    up = PackUpgrader(_siq(tmp_path, content), s, api=api or FakeApi(), **kw)
    return up.run()

def _out_root(result):
    with zipfile.ZipFile(result.path) as zf:
        return parse_content(zf.read("content.xml"))


# Живой случай пользователя: в паке «Gokukoku no Brunhildr», на Shikimori —
# «Brynhildr». Из-за одной буквы пропадали и постер, и все варианты названия.
BRYNHILDR = {"id": 21, "malId": 21, "name": "Gokukoku no Brynhildr",
             "russian": "Тёмная кровь Брунгильды", "english": None,
             "licenseNameRu": "", "synonyms": [], "kind": "tv"}


# «Tegami bachi» в паке — «Tegamibachi» на Shikimori: то же слово, разбитое на
# слоги по вкусу писавшего.
TEGAMI = {"id": 22, "malId": 22, "name": "Tegamibachi",
          "russian": "Почтовая пчела", "english": None, "licenseNameRu": "",
          "synonyms": [], "kind": "tv"}


# Ответ «Shelter»: так зовут и знаменитый клип Porter Robinson, и никому не
# известный фильм 2015 года — в пак вставлялась обложка фильма.
SHELTER_CLIP = {"id": 31, "malId": 31, "name": "Shelter (Music)",
                "russian": "Убежище", "english": "Shelter",
                "licenseNameRu": "", "synonyms": [], "kind": "music",
                "popularity": 221562.0}
SHELTER_MOVIE = {"id": 32, "malId": 32, "name": "Shelter", "russian": None,
                 "english": None, "licenseNameRu": "", "synonyms": [],
                 "kind": "movie", "popularity": 832.0}

# ── Функция 3: сжатие тяжёлых картинок ───────────────────────────────────────
def _fake_avif(monkeypatch, size: int = 400):
    """Подменяет кодирование: ffmpeg в тестах не зовём, важно поведение вокруг."""
    def fake(self, raw, out, limit_kb=None):
        with open(out, "wb") as f:
            f.write(b"A" * size)
        return True

    monkeypatch.setattr(PackUpgrader, "_to_avif", fake)

def _img_settings(**kw):
    # Порог — самый низкий, какой принимает форма (0,1 МБ); «тяжёлая» картинка
    # в тестах чуть больше него, а кодирование подменено (_fake_avif).
    # drop_unused=False: в этих паках рядом с правленой картинкой нарочно лежат
    # файлы, на которые ссылок нет, — уборка мусора вынесла бы их, а проверяем
    # тут не её (её тесты ниже, свои).
    base = dict(strip_specials=False, add_titles=False, compress_images=True,
                image_min_mb=0.1, image_limit_kb=50, drop_unused=False)
    base.update(kw)
    return UpgradeSettings(**base)


HEAVY = b"J" * 200_000                  # «тяжёлая» картинка для тестов
HEAVY_KB = len(HEAVY)


def _q5_image(price: int, name: str) -> str:
    """Вопрос v5 с картинкой в содержимом."""
    return (f'<question price="{price}"><params>'
            '<param name="question" type="content">'
            f'<item type="image" isRef="True">{name}</item></param>'
            "</params><right><answer>Ответ</answer></right></question>")

# ── Написание названия как на Shikimori ──────────────────────────────────────
def _answers(result):
    root, ns = _out_root(result)
    tag = tag_fn(ns)
    return [a.text for a in root.findall(f'.//{tag("right")}/{tag("answer")}')]


# ── Постер тайтла в ответе ───────────────────────────────────────────────────
POSTERED = dict(BLEACH, poster={"originalUrl": "https://shikimori/x.jpg"})


def _fake_poster(monkeypatch, size: int = 1234):
    """Постер без сети и без ffmpeg: скачивание и кодирование подменены."""
    monkeypatch.setattr(PackUpgrader, "_fetch", lambda self, url: b"raw-bytes")

    def fake(self, raw, out, limit_kb=None):
        with open(out, "wb") as f:
            f.write(b"P" * size)
        return True

    monkeypatch.setattr(PackUpgrader, "_to_avif", fake)

def _poster_settings(**kw):
    base = dict(strip_specials=False, compress_images=False)
    base.update(kw)
    return UpgradeSettings(**base)


# ── Клипы и промо — не тайтлы ────────────────────────────────────────────────
# Живой случай: ответ «Mumei» (имя героя) находил вокалоид-клип «Mumei», а
# «Teto Kasane» — клип «Yababaina», у которого это лежит в синонимах.
CLIP_MUMEI = {"id": 56886, "malId": 56886, "name": "Mumei", "russian": "Мумэй",
              "english": None, "japanese": "mumei", "licenseNameRu": None,
              "synonyms": [], "kind": "music",
              "poster": {"originalUrl": "https://shikimori/m.jpg"}}
CLIP_YABA = {"id": 58640, "malId": 58640, "name": "Yababaina", "russian": None,
             "english": None, "licenseNameRu": None, "kind": "music",
             "synonyms": ["YABABAINA - Satapan P feat.Miku Hatsune",
                          "Teto Kasane", "Zundamon"]}

class CharApi(FakeApi):
    """FakeApi, который ещё и «знает» персонажей."""

    def __init__(self, cards=None, chars=None):
        super().__init__(cards)
        self.chars = list(chars or [])
        self.char_calls = []

    def search_characters_by_name(self, name):
        self.char_calls.append(name)
        return list(self.chars)


# Тайтл, который сам по себе на ответ не похож: совпадение приходит близостью
# строк, и вот тут мнение базы персонажей уже что-то значит.
LOOSE_CARD = {"id": 7, "malId": 7, "russian": None, "name": "Teto Kasanee",
              "english": None, "licenseNameRu": "", "synonyms": [], "kind": "tv"}

# ── Функция 5: повторяющийся текст темы ──────────────────────────────────────
def _q5_items(price: int, items: str, answer: str = "Ответ") -> str:
    """Вопрос v5 с произвольным содержимым (несколько <item> подряд)."""
    return (f'<question price="{price}"><params>'
            f'<param name="question" type="content">{items}</param></params>'
            f"<right><answer>{answer}</answer></right></question>")

def _shot(name: str = "кадр.jpg") -> str:
    return f'<item type="image" isRef="True">{name}</item>'


# Известные подписи тут выключены нарочно: ниже проверяется ОБЩЕЕ правило
# («текст стоит в каждом вопросе темы»), и «Назвать аниме» взято как обычный
# короткий текст. Списочные подписи проверяются отдельно, см. KNOWN_REPEATS.
ONLY_REPEATS = UpgradeSettings(strip_specials=False, add_titles=False,
                               compress_images=False,
                               strip_known_labels=False)
KNOWN_REPEATS = UpgradeSettings(strip_specials=False, add_titles=False,
                                compress_images=False)


def _themes(*themes: str, round_name: str = "Раунд 1") -> str:
    """Пак из нескольких тем: [(имя темы, вопросы)] строками."""
    body = "".join(f'<theme name="{name}"><questions>{qs}</questions></theme>'
                   for name, qs in (t.split("|", 1) for t in themes))
    return ('<?xml version="1.0" encoding="utf-8"?>\n<package name="Пак">'
            f'<rounds><round name="{round_name}"><themes>{body}'
            "</themes></round></rounds></package>")


# ── Ответ, записанный двумя названиями через косую черту ─────────────────────
UENO = {"id": 37920, "malId": 37920, "russian": "Неуклюжая Уэно",
        "name": "Ueno-san wa Bukiyou", "english": "How Clumsy you are, Miss Ueno",
        "synonyms": ["Уэно-сан, какая же Вы неуклюжая"], "licenseNameRu": ""}

# ── Несколько точных совпадений: побеждает известность ───────────────────────
def _stats(watchers: int) -> list:
    return [{"status": "completed", "count": watchers}]


KYOUKAI = {"id": 18153, "malId": 18153, "russian": "По ту сторону границы",
           "name": "Kyoukai no Kanata", "english": "Beyond the Boundary",
           "synonyms": ["За гранью", "Beyond the Horizon"], "licenseNameRu": "",
           "kind": "tv", "statusesStats": _stats(1264006)}
SWEAT = {"id": 1072, "malId": 1072, "russian": "За гранью", "name": "Sweat Punch",
         "english": "Sweat Punch", "synonyms": ["Комедия", "Kigeki"],
         "licenseNameRu": "", "kind": "ova", "statusesStats": _stats(52878)}

class RawApi(FakeApi):
    """Выдача Shikimori как есть: поиск там ищет и по синонимам тоже, а
    самодельная фильтрация FakeApi про них не знает."""

    def search_animes_by_name(self, name, limit=0):
        self.calls.append(name)
        return list(self.cards)


AKAME_MANGA = {"id": 25132, "malId": 25132, "russian": "Убийца Акамэ!",
               "name": "Akame ga Kill!", "english": "Akame ga Kill!",
               "synonyms": ["Akame ga Kiru!"], "licenseNameRu": "",
               "kind": "manga", "poster": {"originalUrl": "http://x/m.jpg"}}
AKAME_ANIME = {"id": 22199, "malId": 22199, "russian": "Убийца Акамэ!",
               "name": "Akame ga Kill!", "english": "Akame ga Kill!",
               "synonyms": ["Красноглазый убийца"], "licenseNameRu": "",
               "kind": "tv", "poster": {"originalUrl": "http://x/a.jpg"}}


class BookApi(FakeApi):
    """Shikimori с двумя базами: аниме и книги (поиск по ним раздельный)."""

    def __init__(self, animes=None, mangas=None):
        super().__init__(animes if animes is not None else [])
        self.books = list(mangas or [])
        self.manga_calls = []

    def search_mangas_by_name(self, name, limit=0):
        self.manga_calls.append(name)
        needle = norm_title(name)
        return [c for c in self.books
                if any(needle in norm_title(n) or norm_title(n) in needle
                       for n in [c.get("russian"), c.get("name"),
                                 c.get("english")] if n)]

def _book_pack(theme: str, answer: str) -> str:
    return ('<?xml version="1.0" encoding="utf-8"?>\n<package name="Пак">'
            f'<rounds><round name="Раунд 1"><themes><theme name="{theme}">'
            f"<questions>{_q5(100, answer=answer)}</questions>"
            "</theme></themes></round></rounds></package>")


# ── Функция «Текст под звук» ─────────────────────────────────────────────────
ONLY_MERGE = UpgradeSettings(strip_specials=False, add_titles=False,
                             compress_images=False, strip_repeated_text=False,
                             drop_empty_questions=False, compress_audio=False,
                             drop_unused=False)


def _sound(name: str = "опенинг.mp3") -> str:
    return f'<item type="audio" isRef="True">{name}</item>'

def _items_of(q, ns):
    tag = tag_fn(ns)
    return q.find(f'{tag("params")}/{tag("param")}').findall(tag("item"))


# ── Функция «Удалить пустые вопросы» ─────────────────────────────────────────
ONLY_EMPTY = UpgradeSettings(strip_specials=False, add_titles=False,
                             compress_images=False, strip_repeated_text=False,
                             compress_audio=False)


def _q5_empty(price: int, answer: str = "Ответ") -> str:
    """Вопрос v5, в котором нет ничего, кроме ответа."""
    return (f'<question price="{price}"><params>'
            '<param name="question" type="content"/></params>'
            f"<right><answer>{answer}</answer></right></question>")


# ── Функция «Сжать тяжёлое аудио» ────────────────────────────────────────────
BIG_AUDIO = b"S" * 300_000              # «тяжёлая» дорожка для тестов


def _aud_settings(**kw):
    base = dict(strip_specials=False, add_titles=False, compress_images=False,
                strip_repeated_text=False, drop_empty_questions=False,
                compress_audio=True, audio_min_mb=0.1, audio_kbps=192,
                drop_unused=False)
    base.update(kw)
    return UpgradeSettings(**base)

def _fake_opus(monkeypatch, size: int = 5000, kbps: int = 320):
    """ffmpeg и ffprobe в тестах не зовём: важно поведение вокруг них."""
    def fake_encode(self, raw, out):
        with open(out, "wb") as f:
            f.write(b"O" * size)
        return True

    monkeypatch.setattr(PackUpgrader, "_to_opus", fake_encode)
    monkeypatch.setattr(PackUpgrader, "_audio_kbps",
                        lambda self, raw, size=0: kbps)

def _q5_audio(price: int, name: str) -> str:
    return (f'<question price="{price}"><params>'
            '<param name="question" type="content">'
            f'<item type="audio" isRef="True">{name}</item></param>'
            "</params><right><answer>Ответ</answer></right></question>")


# ── Неиспользуемые файлы ─────────────────────────────────────────────────────
ONLY_UNUSED = UpgradeSettings(strip_specials=False, add_titles=False,
                              compress_images=False, strip_repeated_text=False,
                              drop_empty_questions=False, compress_audio=False,
                              drop_unused=True)


# ── Сжатие видео ─────────────────────────────────────────────────────────────
BIG_VIDEO = b"V" * 400_000              # «тяжёлый» ролик для тестов


def _vid_settings(**kw):
    base = dict(strip_specials=False, add_titles=False, compress_images=False,
                strip_repeated_text=False, drop_empty_questions=False,
                compress_audio=False, drop_unused=False, compress_video=True,
                video_min_mb=0.3)
    base.update(kw)
    return UpgradeSettings(**base)

def _fake_av1(monkeypatch, size: int = 9000, codec: str = "h264"):
    def fake_encode(self, raw, out):
        with open(out, "wb") as f:
            f.write(b"A" * size)
        return True

    monkeypatch.setattr(PackUpgrader, "_to_av1", fake_encode)
    monkeypatch.setattr(PackUpgrader, "_video_codec", lambda self, raw: codec)

def _q5_video(price: int, name: str) -> str:
    return (f'<question price="{price}"><params>'
            '<param name="question" type="content">'
            f'<item type="video" isRef="True">{name}</item></param>'
            "</params><right><answer>Ответ</answer></right></question>")
