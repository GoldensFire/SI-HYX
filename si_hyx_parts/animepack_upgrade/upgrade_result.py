# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""UpgradeResult. Public namespace: animepack_upgrade."""
from __future__ import annotations
import animepack_upgrade as _api


@_api.dataclass
class UpgradeResult:
    path: str = ""                       # готовый .siq
    source: str = ""                     # исходный
    questions: int = 0                   # сколько вопросов в паке
    specials: list = _api.field(default_factory=list)     # список Change (special)
    titles: list = _api.field(default_factory=list)       # список Change (title)
    recased: list = _api.field(default_factory=list)      # список Change (case)
    posters: list = _api.field(default_factory=list)      # список Change (poster)
    images: list = _api.field(default_factory=list)       # список Change (image)
    repeats: list = _api.field(default_factory=list)      # список Change (repeat)
    merged: list = _api.field(default_factory=list)       # список Change (merge)
    empties: list = _api.field(default_factory=list)      # список Change (empty)
    audios: list = _api.field(default_factory=list)       # список Change (audio)
    videos: list = _api.field(default_factory=list)       # список Change (video)
    unused: list = _api.field(default_factory=list)       # список Change (unused)
    skipped_specials: list = _api.field(default_factory=list)  # без самого вопроса
    skipped_titles: list = _api.field(default_factory=list)    # ответ — имя персонажа
    checked_answers: int = 0             # сколько ответов искали в базе названий
    not_found: int = 0                   # столько тайтлов не нашлось
    exact_titles: int = 0                # столько ответов совпало слово в слово
    typo_titles: int = 0                 # из них столько — с опечаткой в ответе
    heavy_images: int = 0                # картинок тяжелее порога нашлось
    heavy_audio: int = 0                 # дорожек тяжелее порога нашлось
    heavy_video: int = 0                 # роликов под перекод набралось
    dropped_themes: int = 0              # тем осталось без единого вопроса
    saved_bytes: int = 0                 # столько весу ушло со сжатием картинок
    saved_audio_bytes: int = 0           # столько весу ушло с перекодом звука
    saved_video_bytes: int = 0           # столько весу ушло с перекодом видео
    saved_unused_bytes: int = 0          # столько весу ушло с мусором
    added_bytes: int = 0                 # столько весу прибавили постеры
    cancelled: bool = False
    elapsed: float = 0.0

    @property
    def parts(self) -> list:
        """Списки правок по функциям — в том порядке, в каком идут в отчёте."""
        return [self.specials, self.titles, self.recased, self.posters,
                self.images, self.repeats, self.merged, self.empties,
                self.audios, self.videos, self.unused]

    @property
    def changes(self) -> list:
        """Все правки в порядке пака (все функции вперемешку)."""
        return sorted([c for part in self.parts for c in part],
                      key=lambda c: c.order)

    @property
    def total(self) -> int:
        return sum(len(part) for part in self.parts)

UpgradeResult.__module__ = _api.__name__
_api.UpgradeResult = UpgradeResult

# ─────────────────────────────────────────────────────────────────────────────
# Разбор .siq
# ─────────────────────────────────────────────────────────────────────────────
def _safe_parser() -> _api.ET.XMLParser:
    """Разбор недоверенного XML: .siq чаще всего скачан из интернета.

    Объявления сущностей запрещаем совсем — это закрывает и чтение локальных
    файлов через внешние SYSTEM-сущности (XXE), и «лавину сущностей» (billion
    laughs). Предопределённые (&amp; &lt; …) к объявлениям не относятся и
    разбираются как обычно."""
    parser = _api.ET.XMLParser()

    def _deny(*_a, **_kw):
        raise _api.UpgradeError("В content.xml объявлены XML-сущности — такой файл "
                           "разбирать небезопасно.")

    try:
        parser.parser.EntityDeclHandler = _deny
        parser.parser.UnparsedEntityDeclHandler = _deny
    except AttributeError:  # pragma: no cover — не expat
        pass
    return parser

_safe_parser.__module__ = _api.__name__
_api._safe_parser = _safe_parser

def parse_content(data: bytes) -> tuple[_api.ET.Element, str]:
    """content.xml → (корень, адрес пространства имён). BOM снимаем сами:
    ElementTree на нём спотыкается."""
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    try:
        root = _api.ET.fromstring(data, parser=_api._safe_parser())
    except _api.UpgradeError:
        raise
    except _api.ET.ParseError as e:
        raise _api.UpgradeError(f"content.xml не разбирается: {e}") from e
    ns = root.tag.split("}")[0][1:] if "{" in root.tag else ""
    return root, ns

parse_content.__module__ = _api.__name__
_api.parse_content = parse_content

def tag_fn(ns: str) -> _api.Callable[[str], str]:
    """Имя тега с пространством имён пака (у v4 его обычно нет вовсе).

    Нужен только для СОЗДАНИЯ элементов (новый <answer> обязан лечь в то же
    пространство имён). Для поиска по дереву он не используется — см. ниже."""
    if not ns:
        return lambda name: name
    return lambda name: f"{{{ns}}}{name}"

tag_fn.__module__ = _api.__name__
_api.tag_fn = tag_fn

# ── Поиск по дереву: по местному имени, без пространства имён ────────────────
# Спускаемся по известным именам детей вместо findall с путями и «.//». Это и
# быстрее (нет разбора пути и рекурсивного обхода на каждом уровне), и
# устойчивее: пространство имён у пака может быть любым, а у v4 его нет вовсе,
# и тогда одно и то же дерево пришлось бы обходить двумя разными способами.
def local(tag: str) -> str:
    """«{http://…}question» → «question»."""
    return str(tag).rsplit("}", 1)[-1]

local.__module__ = _api.__name__
_api.local = local

def children(el, name: str) -> list:
    """Прямые дети с таким местным именем (пустой список, если el — None)."""
    if el is None:
        return []
    return [c for c in el if _api.local(c.tag) == name]

children.__module__ = _api.__name__
_api.children = children

def child(el, name: str):
    """Первый прямой ребёнок с таким местным именем или None."""
    if el is None:
        return None
    for c in el:
        if _api.local(c.tag) == name:
            return c
    return None

child.__module__ = _api.__name__
_api.child = child

def read_content(path: str) -> tuple[str, bytes]:
    """(имя записи в архиве, содержимое) для content.xml пака."""
    try:
        with _api.zipfile.ZipFile(path) as zf:
            name = next((n for n in _api._CONTENT_CANDIDATES if n in zf.namelist()),
                        None)
            if not name:
                name = next((n for n in zf.namelist()
                             if n.lower().endswith("content.xml")), None)
            if not name:
                raise _api.UpgradeError("В архиве нет content.xml — это не пакет "
                                   "SIGame.")
            return name, zf.read(name)
    except _api.UpgradeError:
        raise
    except (OSError, _api.zipfile.BadZipFile) as e:
        raise _api.UpgradeError(f"Файл не читается как .siq: {e}") from e

read_content.__module__ = _api.__name__
_api.read_content = read_content

def iter_themes(root: _api.ET.Element) -> _api.Iterator[tuple[str, str, list]]:
    """(имя раунда, имя темы, все её вопросы) по всему паку, в порядке файла.

    Спуск по известным именам — package → rounds → round → themes → theme →
    questions → question.
    Темой, а не отдельным вопросом, работает уборка повторяющегося текста: там
    правило — «стоит в КАЖДОМ вопросе темы»."""
    for r_idx, rnd in enumerate(_api.children(_api.child(root, "rounds"), "round")):
        rname = rnd.get("name") or f"Раунд {r_idx + 1}"
        for theme in _api.children(_api.child(rnd, "themes"), "theme"):
            yield (rname, theme.get("name") or "",
                   _api.children(_api.child(theme, "questions"), "question"))

iter_themes.__module__ = _api.__name__
_api.iter_themes = iter_themes

def iter_questions(root: _api.ET.Element) -> _api.Iterator[tuple[str, str, _api.ET.Element]]:
    """(имя раунда, имя темы, вопрос) по всему паку, в порядке файла."""
    for rname, tname, questions in _api.iter_themes(root):
        for q in questions:
            yield rname, tname, q

iter_questions.__module__ = _api.__name__
_api.iter_questions = iter_questions

@_api.dataclass
class PackInfo:
    """Что показать про выбранный пак до того, как его начали править."""
    name: str = ""
    authors: list[str] = _api.field(default_factory=list)
    date: str = ""
    version: str = ""
    questions: int = 0
    specials: int = 0
    # [(имя раунда, [темы])] — списком, чтобы карточка шла в порядке пака.
    rounds: list = _api.field(default_factory=list)

    @property
    def themes(self) -> list[str]:
        return [t for _r, names in self.rounds for t in names]

    @property
    def author(self) -> str:
        return ", ".join(self.authors)

PackInfo.__module__ = _api.__name__
_api.PackInfo = PackInfo

def read_pack_info(path: str) -> _api.PackInfo:
    """Название, автор и темы пака — из одного content.xml.

    Медиа не трогается вовсе: из архива читается ровно один файл, так что даже
    на паке в сотню мегабайт это доли секунды."""
    _cname, data = _api.read_content(path)
    root, _ns = _api.parse_content(data)
    info = _api.PackInfo(name=str(root.get("name") or ""),
                    date=str(root.get("date") or ""),
                    version=str(root.get("version") or ""))
    authors = _api.child(_api.child(root, "info"), "authors")
    info.authors = [str(a.text or "").strip()
                    for a in _api.children(authors, "author")
                    if str(a.text or "").strip()]
    for r_idx, rnd in enumerate(_api.children(_api.child(root, "rounds"), "round")):
        rname = rnd.get("name") or f"Раунд {r_idx + 1}"
        names = []
        for theme in _api.children(_api.child(rnd, "themes"), "theme"):
            names.append(str(theme.get("name") or "").strip() or "без имени")
            for q in _api.children(_api.child(theme, "questions"), "question"):
                info.questions += 1
                if _api.special_key(q):
                    info.specials += 1
        info.rounds.append((str(rname), names))
    return info

read_pack_info.__module__ = _api.__name__
_api.read_pack_info = read_pack_info

def retarget_refs(root: _api.ET.Element, renames: dict) -> int:
    """Переводит ссылки на медиа с прежних имён на новые.

    Ссылка живёт в тексте <item> (v5) или <atom> (v4); у v4 перед именем стоит
    «@» — признак файла в архиве, у v5 то же самое сказано атрибутом isRef.
    Само имя бывает percent-кодированным — сравниваем и пишем в том же виде,
    в каком оно там лежало, и кодируем так же, как это делает игра
    (escape_uri_string). Возвращает число переписанных ссылок."""
    changed = 0
    for el in root.iter():
        if _api.local(el.tag) not in ("item", "atom"):
            continue
        raw = (el.text or "").strip()
        if not raw:
            continue
        ref, body = raw.startswith("@"), raw.lstrip("@")
        decoded = _api.unquote(body).replace("\\", "/").rsplit("/", 1)[-1]
        new = renames.get(decoded)
        if not new:
            continue
        el.text = ("@" if ref else "") + (_api.escape_uri_string(new)
                                          if body != _api.unquote(body) else new)
        changed += 1
    return changed

retarget_refs.__module__ = _api.__name__
_api.retarget_refs = retarget_refs
