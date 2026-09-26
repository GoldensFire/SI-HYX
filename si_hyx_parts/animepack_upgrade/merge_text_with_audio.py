# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""merge_text_with_audio. Public namespace: animepack_upgrade."""
from __future__ import annotations
import animepack_upgrade as _api


def merge_text_with_audio(q_el: _api.ET.Element) -> list[str]:
    """Текстовому блоку, за которым СРАЗУ идёт звук, ставит «играть
    одновременно». Возвращает тексты блоков, которые пришлось поправить.

    Так это записано у SIGame: v5 — waitForFinish="False" у <item> (по
    умолчанию true, ContentItem.cs), v4 — time="-1" у <atom> (Question.cs:
    WaitForFinish = atom.AtomTime != -1). Ни новых элементов, ни <params> тут не
    заводится — правится атрибут у того, что в вопросе уже есть, поэтому обоим
    форматам это безопасно.

    Уже включённое одновременное воспроизведение не трогаем: пользователь просил
    доделать за автором, а не переписать сделанное им."""
    items = _api.question_items(q_el)
    done: list[str] = []
    for i, (_parent, el, kind, text) in enumerate(items[:-1]):
        if kind not in _api.TEXT_KINDS or items[i + 1][2] not in _api.AUDIO_KINDS:
            continue
        if _api.local(el.tag) == "atom":
            if str(el.get("time") or "").strip() == "-1":
                continue
            el.set("time", "-1")
        else:
            if str(el.get("waitForFinish") or "").strip().lower() == "false":
                continue
            el.set("waitForFinish", "False")
        done.append(text)
    return done

merge_text_with_audio.__module__ = _api.__name__
_api.merge_text_with_audio = merge_text_with_audio

# ─────────────────────────────────────────────────────────────────────────────
# Функция «Удалить пустые вопросы»
# ─────────────────────────────────────────────────────────────────────────────
def is_empty_question(q_el: _api.ET.Element) -> bool:
    """Пусто ли в САМОМ вопросе: ни текста, ни картинки, ни звука, ни ролика.

    Ответ не в счёт нарочно (просьба пользователя: «даже если есть ответ»): на
    экране такой вопрос — пустота, играть в него нечем, сколько бы вариантов
    ответа под ним ни лежало. Содержимое берётся тем же question_items, что и
    уборка повторов: у v4 всё, что стоит ПОСЛЕ маркера, показывается уже как
    ответ, и вопросом не считается."""
    return not any(text.strip() for _parent, _el, _kind, text
                   in _api.question_items(q_el))

is_empty_question.__module__ = _api.__name__
_api.is_empty_question = is_empty_question

def empty_questions(root: _api.ET.Element) -> list[tuple]:
    """Пустые вопросы пака: [(раунд, тема, номер, контейнер, вопрос)].

    Контейнер (<questions>) отдаётся вместе с вопросом: в ElementTree элемент
    не знает своего родителя, а удалять его придётся именно из него. Номер —
    порядковый номер вопроса в паке, по нему правка встаёт в общую таблицу."""
    out: list[tuple] = []
    number = 0
    for r_idx, rnd in enumerate(_api.children(_api.child(root, "rounds"), "round")):
        rname = rnd.get("name") or f"Раунд {r_idx + 1}"
        for theme in _api.children(_api.child(rnd, "themes"), "theme"):
            box = _api.child(theme, "questions")
            for q in _api.children(box, "question"):
                if _api.is_empty_question(q):
                    out.append((rname, str(theme.get("name") or ""), number,
                                box, q))
                number += 1
    return out

empty_questions.__module__ = _api.__name__
_api.empty_questions = empty_questions

def drop_empty_themes(root: _api.ET.Element) -> list[tuple[str, str]]:
    """Убирает темы, оставшиеся без единого вопроса (и раунды без тем).

    Тему без вопросов SIGame показывает пустой строкой на табло, а раунд без тем
    и вовсе некуда играть. Возвращает [(раунд, тема)] убранного."""
    gone: list[tuple[str, str]] = []
    rounds_el = _api.child(root, "rounds")
    for r_idx, rnd in enumerate(_api.children(rounds_el, "round")):
        rname = rnd.get("name") or f"Раунд {r_idx + 1}"
        themes_el = _api.child(rnd, "themes")
        for theme in _api.children(themes_el, "theme"):
            if _api.children(_api.child(theme, "questions"), "question"):
                continue
            themes_el.remove(theme)
            gone.append((rname, str(theme.get("name") or "")))
        if rounds_el is not None and not _api.children(themes_el, "theme"):
            rounds_el.remove(rnd)
    return gone

drop_empty_themes.__module__ = _api.__name__
_api.drop_empty_themes = drop_empty_themes

# ─────────────────────────────────────────────────────────────────────────────
# Функция «Удалить неиспользуемые файлы»
# ─────────────────────────────────────────────────────────────────────────────
def entry_basename(name: str) -> str:
    """Человеческое имя файла из имени записи архива: без папок и без
    percent-кодирования («Images/%D0%BA.jpg» → «к.jpg»)."""
    return _api.unquote(str(name or "").replace("\\", "/")).rsplit("/", 1)[-1]

entry_basename.__module__ = _api.__name__
_api.entry_basename = entry_basename

def referenced_names(root: _api.ET.Element) -> set:
    """Имена файлов, на которые в content.xml есть хоть какая-то ссылка.

    Смотрим и текст элементов, и ВСЕ значения атрибутов, а не только <item> и
    <atom>: логотип пака лежит атрибутом <package logo>, и удалить его из-за
    того, что вопросы на него не ссылаются, было бы порчей пака. Ошибаться тут
    можно только в одну сторону — лишний «занятый» файл просто останется лежать,
    а лишнее удаление это дырка в паке.

    Ключи — casefold: в архиве имя записано как записал автор, а в ссылке — как
    ему было удобно, и регистр у них расходится сплошь и рядом."""
    out: set = set()
    for el in root.iter():
        raw_values = [el.text or ""]
        raw_values += [str(v) for v in (el.attrib or {}).values()]
        for raw in raw_values:
            text = str(raw).strip().lstrip("@")
            if not text or len(text) > 400:
                continue
            name = _api.entry_basename(text)
            if name:
                out.add(name.casefold())
    return out

referenced_names.__module__ = _api.__name__
_api.referenced_names = referenced_names

def is_media_entry(name: str) -> bool:
    """Медиа ли это (по расширению). Служебные части пака — content.xml,
    Texts/authors.xml, [Content_Types].xml — сюда не попадают никогда."""
    return _api.os.path.splitext(_api.entry_basename(name))[1].lower() in _api.MEDIA_EXTS

is_media_entry.__module__ = _api.__name__
_api.is_media_entry = is_media_entry

def unused_entries(names, refs: set, keep=()) -> list[str]:
    """Записи архива, на которые в паке нет ни одной ссылки.

    keep — имена записей, которые трогать нельзя, чем бы дело ни кончилось
    (пережатые картинки и дорожки: их ссылки уже переписаны на новое имя, и по
    старому их никто не зовёт — а сами они в пак всё-таки идут)."""
    keep = {str(k) for k in (keep or ())}
    out: list[str] = []
    for name in names:
        if name in keep or not _api.is_media_entry(name):
            continue
        if _api.entry_basename(name).casefold() not in refs:
            out.append(name)
    return out

unused_entries.__module__ = _api.__name__
_api.unused_entries = unused_entries

# ─────────────────────────────────────────────────────────────────────────────
# Функция «Сжать тяжёлое аудио»
# ─────────────────────────────────────────────────────────────────────────────
def run_hidden(cmd: list, should_stop: _api.Optional[_api.Callable[[], bool]] = None,
               timeout: float = _api.AUDIO_TIMEOUT,
               capture: bool = False) -> tuple[int, str]:
    """Запускает ffmpeg/ffprobe без окна консоли и с оглядкой на «Стоп».

    Ждём короткими шагами и убиваем процесс по первому же сигналу: иначе кнопка
    «Стоп» ждала бы конца кодирования всей дорожки. Вывод забирается только
    когда он нужен (ffprobe): у ffmpeg он уходит в никуда, и переполнить трубу
    ему нечем."""
    kw = ({"creationflags": _api.CREATE_NO_WINDOW | _api._LOW_PRIORITY}
          if _api.os.name == "nt" else {})
    sink = _api.subprocess.PIPE if capture else _api.subprocess.DEVNULL
    try:
        proc = _api.subprocess.Popen(cmd, stdout=sink, stderr=_api.subprocess.DEVNULL,
                                **kw)
    except Exception as e:  # noqa: BLE001 — нет ffmpeg, нет прав и т.п.
        return 1, str(e)
    deadline = _api.time.monotonic() + max(1.0, float(timeout))
    while True:
        try:
            out, _err = proc.communicate(timeout=0.2)
            # Кодировку задаём явно: по локали Windows это была бы cp1251, и
            # ответ ffprobe пришёл бы искажённым.
            return proc.returncode, (out or b"").decode("utf-8", "replace")
        except _api.subprocess.TimeoutExpired:
            pass
        if (should_stop and should_stop()) or _api.time.monotonic() > deadline:
            try:
                proc.kill()
                proc.communicate(timeout=5)
            except Exception:  # noqa: BLE001 — процесс мог уже умереть сам
                pass
            return 1, ""

run_hidden.__module__ = _api.__name__
_api.run_hidden = run_hidden

def parse_probe_kbps(text: str, size: int = 0) -> int:
    """Битрейт (кбит/с) из ответа ffprobe. 0 — узнать не вышло.

    ffprobe печатает `ключ=значение`, сначала по дорожке, потом по контейнеру, и
    у каждого второго формата половина значений — «N/A». Берём первое настоящее
    число, а если его нет вовсе — считаем сами по размеру и длительности (так
    отвечают, например, wav и часть ogg)."""
    rates, duration = [], 0.0
    for line in str(text or "").splitlines():
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if key == "bit_rate" and value.isdigit() and int(value) > 0:
            rates.append(int(value))
        elif key == "duration":
            try:
                duration = max(duration, float(value))
            except ValueError:
                pass
    if rates:
        return int(round(rates[0] / 1000.0))
    if duration > 0.1 and size > 0:
        return int(round(size * 8 / duration / 1000.0))
    return 0

parse_probe_kbps.__module__ = _api.__name__
_api.parse_probe_kbps = parse_probe_kbps

def parse_probe_codec(text: str) -> str:
    """Имя видеокодека из ответа ffprobe («av1», «h264»; «» — узнать не вышло).

    Ответ у ffprobe тут в одну строку `codec_name=av1`, но обложка альбома в
    mp3 тоже считается видеодорожкой, так что первое непустое значение и
    берём — поток спрашивается уже отфильтрованным (-select_streams v:0)."""
    for line in str(text or "").splitlines():
        key, _, value = line.partition("=")
        if key.strip() == "codec_name" and value.strip():
            return value.strip().lower()
    return ""

parse_probe_codec.__module__ = _api.__name__
_api.parse_probe_codec = parse_probe_codec

# ─────────────────────────────────────────────────────────────────────────────
# Апгрейд целиком
# ─────────────────────────────────────────────────────────────────────────────
@_api.dataclass
class _MediaPlan:
    """Что делаем с одной записью архива: имя нового файла раздано заранее, до
    кодирования, — оно не должно зависеть от того, чья кодировка кончилась
    первой (кодируем-то в несколько потоков)."""
    name: str                  # имя записи в архиве, как оно там лежит
    size: int                  # сколько весит сейчас
    decoded: str               # человеческое имя файла («кадр.jpg»)
    ext: str                   # расширение исходника
    new_decoded: str           # каким станет («кадр.avif»)
    folder: str                # папка в архиве («Images»)
    percent: bool              # было ли имя записи percent-кодированным

    @property
    def new_name(self) -> str:
        """Имя новой записи в архиве.

        Обычно меняется одно расширение — тогда и берём имя ИСХОДНОЙ записи как
        есть, поменяв ему хвост: так новое имя закодировано ровно так же, как
        было старое, чем бы его ни кодировал автор пака. Игра ищет файл по имени
        из content.xml, прогоняя его через Uri.EscapeUriString, и любое
        расхождение — это «File ... was not found in the game package!».

        Слепое quote(..., safe="") этим и ломалось: скобки уходили в %28/%29, а
        SIQuester и SIGame оставляют их как есть. Имя целиком кодируем только
        тогда, когда сами его изменили (занятое имя развели суффиксом « (2)»)."""
        raw_base = self.name.replace("\\", "/").rpartition("/")[2]
        if self.new_decoded == _api.os.path.splitext(self.decoded)[0] \
                + _api.os.path.splitext(self.new_decoded)[1]:
            raw = _api.os.path.splitext(raw_base)[0] \
                + _api.os.path.splitext(self.new_decoded)[1]
        else:
            raw = _api.escape_uri_string(self.new_decoded) if self.percent \
                else self.new_decoded
        return f"{self.folder}/{raw}" if self.folder else raw

_MediaPlan.__module__ = _api.__name__
_api._MediaPlan = _MediaPlan

@_api.dataclass
class _MediaDone:
    """Ответ кодировщика. Пустой out — файл остаётся прежним, а note скажет
    почему (лог пишется в основном потоке и по порядку)."""
    out: str = ""              # готовый временный файл
    size: int = 0              # сколько он весит
    was: int = 0               # битрейт исходника (только у аудио)
    codec: str = ""            # кодек исходника (только у видео)
    note: str = ""             # что сказать в лог

_MediaDone.__module__ = _api.__name__
_api._MediaDone = _MediaDone

@_api.dataclass
class _PosterJob:
    """Постер тайтла, который качается и кодируется в фоне. Имя файла известно
    сразу, поэтому ссылку в вопрос пишут, не дожидаясь самой картинки; uses —
    вопросы, куда её уже вписали (если постер не дастся, ссылку оттуда надо
    убрать)."""
    ref: str = ""              # имя файла в паке
    url: str = ""              # откуда качать
    title: str = ""            # чей постер (для лога)
    key: str = ""              # ключ в общей кладовой обложек (poster_cache)
    names: tuple = ()          # названия тайтла — по ним ищется обложка на TMDB
    year: int = 0
    movie: bool = False        # аниме-фильм (kind == "movie"), а не сериал —
                                # для порядка поиска раздела на TMDB
    out: str = ""              # временный файл с готовым AVIF
    size: int = 0              # сколько он весит (0 — не вышло)
    note: str = ""             # что сказать в лог, если не вышло
    future: _api.Optional[object] = None
    uses: list = _api.field(default_factory=list)   # [(вопрос, строка отчёта)]

_PosterJob.__module__ = _api.__name__
_api._PosterJob = _PosterJob

def _drop(path: str) -> None:
    """Убирает временный файл, если он есть."""
    if path and _api.os.path.exists(path):
        try:
            _api.os.remove(path)
        except OSError:
            pass

_drop.__module__ = _api.__name__
_api._drop = _drop
