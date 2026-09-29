# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
#
"""Каверы одной песни целиком: найти, послушать, выбрать и вырезать.

Здесь сходятся все части: поиск (cover_search), гейт по заголовку (cover_meta),
хрома и выравнивание (cover_audio/cover_match), кладовая (cover_cache) и
политика выбора (cover_select). Наружу торчат четыре шага — эталон, пул,
выбор, резка, — и ими пользуются и генератор, и прослушивание во вкладке.

Замеренное, из чего сложены здешние решения:

* Проверка качает формат 139 (48 кбит/с m4a, ~1.5 МБ): хроме этого хватает, а
  узкое место всё равно не полоса, а ~3 с накладных расходов yt-dlp на ролик.
  ВЫБРАННЫЙ кавер качается заново и в хорошем качестве (140, AAC 128 кбит/с):
  48 кбит/с — это про проверку, а не про то, что услышит игрок.
* Кандидаты слушаются ВОЛНАМИ по числу недостающих, а не все сразу: один
  кандидат стоит ~1.2 с загрузки и 1.3 с ЦПУ, и когда трёх подтверждённых уже
  набрали, остальные восемь — потраченное впустую время пользователя.
* Процессы запускает переданный `run(cmd, timeout) -> (код, stdout, stderr)` —
  тот же killable-раннер, которым генератор зовёт ffmpeg. Поэтому «Стоп»
  убивает и загрузки каверов.

Ни Qt, ни requests: сеть — это yt-dlp отдельным процессом, а байты эталона
приносит вызывающая сторона.
"""
from __future__ import annotations

import concurrent.futures as futures
import glob
import json
import os
import threading
import time
import uuid

import cover_audio as audio
import cover_cache as cache
import cover_fingerprint as fingerprint
import cover_match as match
import cover_search
import cover_select
import media_cache
from cover_search import SLEEP_REQUESTS

# Формат для ПРОВЕРКИ и формат для того, что попадёт в пак.
PROBE_FORMAT = "139/140/251/bestaudio"
AUDIO_FORMAT = "140/251/bestaudio"
PROBE_TIMEOUT = 120
AUDIO_TIMEOUT = 240
DECODE_TIMEOUT = 180
# Сколько yt-dlp ходят на YouTube ОДНОВРЕМЕННО. Даже четыре процесса с
# --sleep-requests=1 в живом паке упёрлись в «try again later» на 53-м вопросе
# из 96: пауза действует внутри одного процесса, а четыре независимых потока
# всё равно дают всплеск. Поэтому сеть строго последовательна; разбор звука
# остаётся параллельным в рабочем пуле и по-прежнему грузит все ядра.
NET_LIMIT = 1
# Если YouTube всё-таки уже закрыл IP после прежнего прогона, не объявляем
# оставшиеся каверы мёртвыми: держим единственный сетевой слот и пережидаем.
RATE_LIMIT_COOLDOWN = 180.0
RATE_LIMIT_RETRIES = 2


def ytdlp_command(base=None):
    """yt-dlp для каверов — с куками YouTube, если они у пользователя есть.

    Без них YouTube отвечает «Sign in to confirm you’re not a bot» на часть
    запросов (в живом прогоне — на первый же), и каверы сдаются целиком, хотя
    в «Загрузчике» те же ролики качаются: там куки подставляются давно (см.
    ytdlp_worker_run). Ищем тот же файл и в том же порядке — отдельный
    cookies_youtube.txt, иначе общий cookies.txt.
    """
    cmd = list(base if base is not None else _base_cmd() or [])
    if not cmd:
        return cmd
    path = youtube_cookie_file()
    if path:
        cmd += ["--cookies", path]
    return cmd


def youtube_cookie_file() -> str:
    """Файл кук для youtube.com («» — пользователь их не клал).

    Поле «Cookies» во вкладке загрузки хранит произвольный путь в общих
    настройках. Генератор работает без ссылки на виджет, поэтому читает тот же
    сохранённый путь из settings.json между отдельным youtube-файлом и общим
    cookies.txt — ровно в порядке приоритетов обычного загрузчика.
    """
    try:
        from config import COOKIE_PATHS, SETTINGS_FILE
    except Exception:  # pragma: no cover — модуль должен жить и без конфига
        return ""
    dedicated = str(COOKIE_PATHS.get("youtube") or "")
    if dedicated and os.path.isfile(dedicated):
        return dedicated
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as stream:
            settings = json.load(stream)
        selected = str(((settings or {}).get("ytdlp") or {})
                       .get("cookie_path") or "").strip()
    except (OSError, TypeError, ValueError):
        selected = ""
    if selected and os.path.isfile(selected):
        return selected
    common = str(COOKIE_PATHS.get("default") or "")
    if common and os.path.isfile(common):
        return common
    return ""


def _base_cmd():
    try:
        from config import ytdlp_base_cmd
    except Exception:  # pragma: no cover — то же
        return None
    return ytdlp_base_cmd()


def run_capture(command, timeout=PROBE_TIMEOUT, *, stopped=lambda: False):
    """Killable-раннер по умолчанию: (код, stdout, stderr).

    Генератор передаёт СВОЙ (у него реестр процессов и общая кнопка «Стоп»);
    этот нужен вкладке. Вывод идёт во временные файлы, а не в PIPE: ответ
    `ytsearch20 --dump-json` — это десятки килобайт, и обрезать его нельзя (в
    нём построчный JSON), а недренированный PIPE на таком объёме встаёт колом.
    """
    import subprocess
    import tempfile
    import time
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        try:
            process = subprocess.Popen(command, stdout=out, stderr=err,
                                       creationflags=flags)
        except OSError as error:
            return 1, "", str(error)
        deadline = time.monotonic() + max(1.0, float(timeout))
        try:
            while process.poll() is None:
                if stopped() or time.monotonic() >= deadline:
                    process.kill()
                    process.wait(timeout=15)
                    return 1, "", "остановлено"
                time.sleep(0.1)
        finally:
            if process.poll() is None:  # pragma: no cover — только при сбое
                process.kill()
                process.wait(timeout=15)
        out.seek(0)
        err.seek(0)
        return (process.returncode,
                out.read().decode("utf-8", "replace"),
                err.read().decode("utf-8", "replace")[-2000:])


class CoverService:
    """Поиск, проверка и резка каверов. Ничего не хранит между песнями, кроме
    пула потоков и счётчика типов (для разнообразия внутри одного пака)."""

    def __init__(self, run, ffmpeg, ytdlp, *, stopped=lambda: False,
                 log=lambda text: None, workers: int = 6,
                 thread_initializer=None,
                 cache_enabled: bool = True,
                 rate_limit_cooldown: float = RATE_LIMIT_COOLDOWN,
                 rate_limit_retries: int = RATE_LIMIT_RETRIES,
                 net_limit: int = NET_LIMIT):
        self.run, self.ffmpeg = run, str(ffmpeg)
        self.ytdlp = list(ytdlp or [])
        self.stopped, self.log = stopped, log
        self.workers = max(1, int(workers))
        self.thread_initializer = thread_initializer
        self.cache_enabled = bool(cache_enabled)
        self.seen_types: dict[str, int] = {}
        self.rate_limit_cooldown = max(0.0, float(rate_limit_cooldown))
        self.rate_limit_retries = max(0, int(rate_limit_retries))
        self._pool = None
        self._lock = threading.Lock()
        self._reference_data = {}  # только на время этой генерации
        self.net_limit = max(1, min(int(net_limit), self.workers))
        self._net = threading.Semaphore(self.net_limit)

    # ── потоки ───────────────────────────────────────────────────────────
    def pool(self):
        """Один пул на всю генерацию: вложенные пулы на каждый вопрос дали бы
        под сотню одновременных yt-dlp."""
        with self._lock:
            if self._pool is None:
                self._pool = futures.ThreadPoolExecutor(
                    max_workers=self.workers, thread_name_prefix="cover",
                    initializer=self.thread_initializer)
            return self._pool

    def net_run(self, command, timeout):
        """Запустить yt-dlp, дождавшись очереди у ограничителя.

        Всё, что ходит на YouTube, обязано идти через этот вызов: пауза внутри
        процесса (--sleep-requests) держит частоту одного yt-dlp, а ограничитель
        — общее их число. Порознь не помогает ни то, ни другое."""
        with self._net:
            for attempt in range(self.rate_limit_retries + 1):
                result = self.run(command, timeout)
                _code, out, error = result
                limited = (not out and cover_search.fatal_reason(error)
                           == cover_search.RATE_LIMIT)
                if not limited or attempt >= self.rate_limit_retries:
                    return result
                seconds = self.rate_limit_cooldown
                self.log("Каверы: YouTube ограничил частоту — жду "
                         f"{seconds / 60:g} мин и повторяю запрос "
                         f"({attempt + 1}/{self.rate_limit_retries}).")
                deadline = time.monotonic() + seconds
                while time.monotonic() < deadline:
                    if self.stopped():
                        return result
                    time.sleep(min(0.25, deadline - time.monotonic()))
            return result

    def close(self):
        with self._lock:
            pool, self._pool = self._pool, None
        if pool is not None:
            pool.shutdown(wait=False, cancel_futures=True)

    # ── звук ─────────────────────────────────────────────────────────────
    def fetch(self, video_id, stem, fmt=PROBE_FORMAT, timeout=PROBE_TIMEOUT) -> str:
        """Качает звук ролика в `stem.<ext>` и возвращает путь."""
        cache_key = f"{video_id}|{fmt}"
        # Проверочные 48-кбитные копии одноразовые: после вердикта хранится
        # сама хрома. А выбранный хороший звук понадобится снова, когда этот
        # кавер выпадет в следующем паке, поэтому держим только его.
        if self.cache_enabled and fmt == AUDIO_FORMAT:
            ready = media_cache.find_path("cover-audio", cache_key)
            if ready:
                return ready
        if not self.ytdlp:
            raise RuntimeError("yt-dlp не найден — каверы качать нечем.")
        if self.stopped():
            raise RuntimeError("остановлено")
        cmd = list(self.ytdlp) + [
            "-f", fmt, "-o", f"{stem}.%(ext)s", "--no-part", "--no-playlist",
            "--no-warnings", "--sleep-requests", str(SLEEP_REQUESTS),
            "--socket-timeout", "20", "--retries", "3",
            f"https://www.youtube.com/watch?v={video_id}"]
        _code, _out, err = self.net_run(cmd, timeout)
        # По коду возврата не судим: yt-dlp ругается на мелочи (обложка,
        # подписи), отдав при этом годный звук. Судим по файлу.
        found = sorted(glob.glob(f"{glob.escape(stem)}.*"))
        if not found:
            raise RuntimeError(cover_search.trim_error(err or "yt-dlp не отдал звук"))
        if self.cache_enabled and fmt == AUDIO_FORMAT:
            try:
                with open(found[0], "rb") as stream:
                    media_cache.put("cover-audio", cache_key, stream.read())
            except OSError:
                pass
        return found[0]

    def fetch_many(self, video_ids, work, fmt=PROBE_FORMAT,
                   timeout=PROBE_TIMEOUT) -> dict:
        """Звук НЕСКОЛЬКИХ роликов одним процессом: {id ролика: путь}.

        Замер (bin/yt-dlp.exe, Windows): пустой запуск — 1.6 с, один ролик —
        5.3 с, три в одном процессе — 8.6 с. Порознь те же три стоили бы 15.9 с
        процессорного времени: во время генерации потоки пула заняты другими
        вопросами, а не простаивают, поэтому считается именно оно. Заодно
        втрое падает число одновременных yt-dlp на один IP — с них и начинался
        отказ YouTube «подтвердите, что вы не робот».

        Неудача одного ролика видна по отсутствию файла: судить по коду
        возврата нельзя (yt-dlp ругается и на мелочи, отдав годный звук).
        """
        ids = [str(v) for v in video_ids if str(v or "")]
        if not ids:
            return {}
        if not self.ytdlp:
            raise RuntimeError("yt-dlp не найден — каверы качать нечем.")
        if self.stopped():
            raise RuntimeError("остановлено")
        cmd = list(self.ytdlp) + [
            "-f", fmt, "-o", os.path.join(str(work), "cand_%(id)s.%(ext)s"),
            "--no-part", "--no-playlist", "--no-warnings", "--ignore-errors",
            "--sleep-requests", str(SLEEP_REQUESTS),
            "--socket-timeout", "20", "--retries", "3"]
        cmd += [f"https://www.youtube.com/watch?v={vid}" for vid in ids]
        _code, _out, err = self.net_run(cmd, float(timeout) * len(ids))
        got = {}
        for vid in ids:
            stem = os.path.join(str(work), f"cand_{vid}")
            found = sorted(glob.glob(f"{glob.escape(stem)}.*"))
            if found:
                got[vid] = found[0]
        if not got:
            raise RuntimeError(cover_search.trim_error(err or "yt-dlp не отдал звук"))
        return got

    def features(self, source, work):
        """Один разбор файла -> (хрома, созвездие пиков, сколько кадров).

        Оба признака считаются из ОДНОГО декода: ffmpeg и чтение WAV стоят
        дороже самих признаков, а нужны они всегда вместе — хрома отвечает
        «та же композиция», созвездие — «не сам ли это оригинал внутри»
        (см. cover_fingerprint)."""
        wav = os.path.join(str(work), f"{uuid.uuid4().hex}.wav")
        try:
            code, _out, err = self.run(
                audio.decode_args(self.ffmpeg, source, wav), DECODE_TIMEOUT)
            if code or not os.path.isfile(wav):
                raise RuntimeError(cover_search.trim_error(
                    err or "ffmpeg не разобрал звук"))
            sound = audio.read_wav(wav)
            points, frames = fingerprint.marks(sound)
            return audio.chroma(sound), points, frames
        finally:
            try:
                os.remove(wav)
            except OSError:
                pass

    def chroma(self, source, work):
        """Хрома файла: ffmpeg -> моно WAV 22 050 Гц -> признак (0.8 с)."""
        return self.features(source, work)[0]

    def reference(self, song_id, fetch_bytes, work):
        """Хрома песни живёт только в памяти текущей генерации."""
        with self._lock:
            ready = self._reference_data.get(song_id)
        if ready is not None:
            return ready[0]
        data = fetch_bytes()
        if not data:
            raise RuntimeError("эталон не скачался")
        source = os.path.join(str(work), f"ref_{uuid.uuid4().hex}.audio")
        with open(source, "wb") as f:
            f.write(data)
        try:
            chroma, points, _frames = self.features(source, work)
        finally:
            try:
                os.remove(source)
            except OSError:
                pass
        with self._lock:
            self._reference_data[song_id] = (chroma, points)
        return chroma

    # ── пул подтверждённых ───────────────────────────────────────────────
    def search(self, song, entry, *, limit: int = 12) -> dict:
        """Ищет заново, если кэш устарел. Возвращает запись кладовой."""
        if not cache.stale(entry):
            return entry
        found = cover_search.gather(song, self.net_run, self.ytdlp, limit=limit,
                                    stopped=self.stopped, log=self.log)
        return cache.remember_search(song["song_id"], found["rows"],
                                     queries=found["queries"],
                                     found=found["found"], song=song.get("song"))

    def audit(self, song_id, ref, row, work, seconds=match.WANT_SECONDS) -> bool:
        """Один кандидат: скачать, послушать, запомнить вердикт.

        `seconds` — длина отрезка пака (audio_cut): окна ищутся ровно под неё."""
        stem = os.path.join(str(work), f"cand_{row['id']}")
        try:
            path = self.fetch(row["id"], stem)
        except (RuntimeError, OSError, ValueError) as error:
            # Отказ «не роликом, а YouTube целиком» в кладовую не пишем: иначе
            # один заблокированный прогон пометил бы негодными все двенадцать
            # кандидатов каждой песни, и после починки их не переслушали бы.
            if cover_search.fatal_reason(error):
                raise
            cache.remember_failure(song_id, row["id"], str(error))
            return False
        return self._listen(song_id, ref, row, path, work, seconds)

    def ensure(self, song, ref, work, *, want: int = 3, limit: int = 12,
               seconds: float = match.WANT_SECONDS, keep=None) -> list:
        """Подтверждённые каверы песни — докачивая недостающих волнами.

        Волна ровно на столько кандидатов, скольких не хватает: когда нужные
        уже набраны, каждый лишний стоит пользователю ~1.2 с загрузки и 1.3 с
        ЦПУ ни за что.

        `keep` — рамка пользователя (сложность кавера и разрешённые виды
        исполнения). Считается ЗДЕСЬ, а не после: иначе на узкой рамке мы
        набирали бы три подходящих под порог кавера и все три выбрасывали."""
        song_id = song["song_id"]
        entry = self.search(song, cache.load(song_id), limit=limit)
        pool, _bad = cache.screened(entry, song, limit=limit)
        ready = self._fit(cache.confirmed(pool, want=seconds), keep)
        todo = cache.unchecked(pool, want=seconds)
        while todo and len(ready) < want and not self.stopped():
            need = max(1, want - len(ready))
            wave, todo = todo[:need], todo[need:]
            broken = self._audit_wave(song_id, ref, wave, work, seconds)
            if broken is not None:
                # Поломку всего поиска несём наверх, чтобы каверы сдались
                # сразу, а не через сотни тайтлов.
                raise broken
            pool, _bad = cache.screened(cache.load(song_id), song, limit=limit)
            ready = self._fit(cache.confirmed(pool, want=seconds), keep)
        return ready

    def _audit_wave(self, song_id, ref, wave, work, seconds):
        """Одна волна кандидатов. Возвращает поломку ВСЕГО поиска (иначе None).

        Качаются все разом (fetch_many), а слушаются в потоках: загрузка у
        yt-dlp последовательная, а хрома — чистый ЦПУ, и на ней пул как раз
        нужен."""
        try:
            paths = self.fetch_many([row["id"] for row in wave], work)
        except (RuntimeError, OSError, ValueError) as error:
            # Отказ «не роликом, а YouTube целиком» несём наверх, чтобы каверы
            # сдались сразу, а не через сотни тайтлов.
            if cover_search.fatal_reason(error):
                return error
            # Ни один ролик волны не скачался — судить по этому о роликах
            # нельзя, и в кладовую не пишем ничего. Режущий по частоте YouTube
            # отвечает «Video unavailable» и вполне живому ролику: живой прогон
            # так пометил 362 кандидата, у 18 песен — все двенадцать разом, и
            # они отчитались «подходящих исполнений не нашлось». Осечка ролика
            # видна только когда соседи по волне скачались (ниже, `if not path`).
            return None
        jobs = []
        for row in wave:
            path = paths.get(row["id"])
            if not path:
                cache.remember_failure(song_id, row["id"], "yt-dlp не отдал звук")
                continue
            jobs.append(self.pool().submit(self._listen, song_id, ref, row,
                                           path, work, seconds))
        for job in jobs:
            try:
                job.result()
            except Exception as error:  # noqa: BLE001 — кандидат, а не пак
                self.log(f"Кавер не проверился: {error}")
        return None

    def _listen(self, song_id, ref, row, path, work, seconds) -> bool:
        """Скачанный кандидат: послушать, сравнить с эталоном, запомнить."""
        try:
            chroma, points, frames = self.features(path, work)
        except (RuntimeError, OSError, ValueError) as error:
            cache.remember_failure(song_id, row["id"], str(error))
            return False
        finally:
            try:
                os.remove(path)
            except OSError:
                pass
        verdict = match.verify(ref, chroma, strength=row.get("strength"),
                               want=seconds)
        # Внутри записи может играть сам оригинал — гитарист или барабанщик
        # поверх мастера. Хрома такого не видит вовсе (у точного band-кавера
        # выравнивание такое же), поэтому считаем отдельный признак.
        with self._lock:
            reference_marks = self._reference_data.get(song_id, (None, None))[1]
        played, score = fingerprint.inside(reference_marks, points, frames)
        verdict = dict(verdict, inside=score)
        if played:
            verdict = dict(verdict, ok=False, reason="original_inside")
        cache.remember_audio(song_id, row["id"], verdict, verdict["good"],
                             want=seconds)
        return bool(verdict["ok"])

    @staticmethod
    def _fit(rows, keep):
        return [row for row in rows if keep is None or keep(row)]

    # ── выбор и резка ────────────────────────────────────────────────────
    def choose(self, song, rows, *, rng=None, prefer=None) -> dict:
        """Один кавер с участком; заодно считает типы внутри пака."""
        entry = cache.load(song["song_id"])
        with self._lock:
            seen = dict(self.seen_types)
        got = cover_select.pick(rows, rng=rng, skip=cache.last_used(entry),
                                seen_types=seen, prefer=prefer)
        if got:
            with self._lock:
                kind = str(got.get("type") or "")
                self.seen_types[kind] = self.seen_types.get(kind, 0) + 1
        return got

    def cut(self, video_id, at: float, length: float, target, work,
            encode_args) -> str:
        """Вырезает участок кавера в `target`. Возвращает путь («» — не вышло).

        Качается ЗАНОВО и в хорошем качестве: то, что слушал алгоритм, и то,
        что услышит игрок, — разные требования."""
        stem = os.path.join(str(work), f"pick_{video_id}")
        source = self.fetch(video_id, stem, AUDIO_FORMAT, AUDIO_TIMEOUT)
        cmd = [self.ffmpeg, "-y", "-v", "error", "-ss", f"{float(at):.2f}",
               "-i", source, "-t", f"{float(length):.2f}", "-vn"]
        cmd += list(encode_args) + [str(target)]
        code, _out, err = self.run(cmd, DECODE_TIMEOUT)
        if code or not os.path.isfile(str(target)):
            raise RuntimeError((err or "ffmpeg не вырезал отрезок").strip()[-200:])
        return str(target)
