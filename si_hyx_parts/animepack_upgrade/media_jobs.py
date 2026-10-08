# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""media_jobs. Public namespace: animepack_upgrade."""
from __future__ import annotations
import animepack_upgrade as _api


def media_jobs(want: int) -> int:
    """Сколько кодирований гнать разом на ЭТОЙ машине: на двухъядерном ноутбуке
    шесть параллельных ffmpeg только толкались бы локтями."""
    return max(1, min(int(want), _api.os.cpu_count() or 1))

media_jobs.__module__ = _api.__name__
_api.media_jobs = media_jobs


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
