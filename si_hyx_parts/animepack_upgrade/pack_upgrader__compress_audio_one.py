# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""PackUpgrader: _compress_audio_one. Public namespace: animepack_upgrade."""
from __future__ import annotations
import animepack_upgrade as _api


def _compress_audio_one(self, plan: _api._MediaPlan) -> _api.Optional[_api._MediaDone]:
    """Одна дорожка: opus на заданном битрейте. Пустой out — оставляем как
        было. Зовётся из потока, как и _compress_one."""
    if self.stopped():
        return None
    target = _api.nearest_bitrate(self.s.audio_kbps)
    raw, was = "", 0
    out = _api.os.path.join(_api._temp_dir(), f"siqaud_{_api.uuid.uuid4().hex}.opus")
    try:
        raw = self._extract(plan, "siqaud")
        was = self._audio_kbps(raw, plan.size)
        # С включённой нормализацией обе оговорки «не трогаю» снимаются:
        # ради неё дорожку и перекодируют, а пропущенная дорожка осталась бы
        # с прежней громкостью — то есть громче или тише всех соседних.
        norm = bool(self.s.audio_norm)
        if was and was <= target and not norm:
            # Перекод тут только испортил бы звук: opus на 192 из mp3 на 128
            # весит примерно столько же, а качества уже не вернуть.
            _api._drop(out)
            return _api._MediaDone(note=f"«{plan.decoded}»: и так {was} кбит — "
                                   f"не трогаю.")
        if not self._to_opus(raw, out):
            _api._drop(out)          # ffmpeg мог оставить недописанный файл
            return _api._MediaDone(note=f"«{plan.decoded}»: перекодировать не "
                                   f"вышло, оставляю как есть.")
        new_size = _api.os.path.getsize(out)
        if new_size >= plan.size and not norm:
            _api._drop(out)
            return _api._MediaDone(note=f"«{plan.decoded}»: после перекода не "
                                   f"легче, оставляю.")
    except (OSError, _api.zipfile.BadZipFile) as e:
        _api._drop(out)
        return _api._MediaDone(note=f"«{plan.decoded}»: {e}")
    finally:
        _api._drop(raw)
    return _api._MediaDone(out=out, size=new_size, was=was)

def _audio_kbps(self, raw: str, size: int = 0) -> int:
    """Битрейт исходной дорожки в килобитах (0 — узнать не вышло).

        Спрашиваем ffprobe: перекодировать дорожку, которая и так не богаче
        целевого битрейта, — значит просто испортить звук, ничего не выиграв."""
    code, out = _api.run_hidden(
        [_api.FFPROBE, "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=bit_rate:format=bit_rate,duration",
         "-of", "default=noprint_wrappers=1", raw],
        self._should_stop, timeout=60.0, capture=True)
    if code != 0:
        return 0
    return _api.parse_probe_kbps(out, size)

def _to_opus(self, raw: str, out: str) -> bool:
    """Кодирование звука — то же, что в генераторе паков и «Обработке»:
        libopus с переменным битрейтом и фиксом раскладки каналов (libopus не
        берёт «боковые» раскладки). Громкость трогаем, только если это включено
        настройкой: в готовом паке её уже выставил автор, и двигать её вслепую
        нельзя.

        Картинки внутри файла (обложка альбома в mp3) отбрасываются: в opus им
        всё равно не лечь, а ffmpeg на них спотыкается."""
    kbps = _api.nearest_bitrate(self.s.audio_kbps)
    code, _out = _api.run_hidden(
        [_api.FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", raw,
         "-vn", "-af", _api.audio_filter_chain(self.s), "-c:a", "libopus",
         "-b:a", f"{kbps}k", "-vbr", "on", "-application", "audio", out],
        self._should_stop)
    return code == 0 and _api.os.path.exists(out) and _api.os.path.getsize(out) > 0

# ── видео ─────────────────────────────────────────────────────────────
def _video_entries(self) -> list[tuple[str, int]]:
    """Записи архива с видео, которые надо посмотреть: [(имя, байт)].

        С галочкой «кодек не AV1» сюда идут ВСЕ ролики, сколько бы они ни
        весили: тяжёлый он или нет, решается по кодеку, а кодек виден только
        после распаковки (ffprobe читает файл, а не запись архива). Без неё —
        только те, что тяжелее порога, и лишнего никто не распаковывает."""
    limit = int(max(0.1, float(self.s.video_min_mb)) * 1024 * 1024)
    take_all = bool(self.s.video_non_av1)
    heavy: list[tuple[str, int]] = []
    try:
        with _api.zipfile.ZipFile(self.path) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                if not take_all and info.file_size <= limit:
                    continue
                name = _api.unquote(info.filename.replace("\\", "/"))
                if _api.os.path.splitext(name)[1].lower() in _api.VIDEO_EXTS:
                    heavy.append((info.filename, info.file_size))
    except (OSError, _api.zipfile.BadZipFile) as e:
        raise _api.UpgradeError(f"Файл не читается как .siq: {e}") from e
    return heavy

def _do_video(self, heavy, root, result, base_step: int,
              steps: int) -> dict:
    """Перекодирует ролики в AV1 и переписывает ссылки на них.

        Возвращает {имя записи в архиве: (новое имя, путь к готовому mp4)} — в
        том же виде, что картинки и аудио: архив собирается позже, в _write."""
    why = f"тяжелее {self.s.video_min_mb:g} МБ"
    if self.s.video_non_av1:
        why += " или не в AV1"
    self.log(f"Роликов под перекод ({why}): {len(heavy)}.")
    plans = self._plans(heavy, ".mp4")
    made = self._run_jobs(plans, self._compress_video_one, base_step, steps,
                          "видео", _api.media_jobs(_api.VIDEO_JOBS))
    done: dict[str, tuple[str, str]] = {}
    for plan, got in zip(plans, made):
        if got is None or not got.out:
            if got is not None and got.note and not self.stopped():
                self.log(got.note)
            continue
        result.saved_video_bytes += plan.size - got.size
        height = _api.nearest_height(self.s.video_height)
        result.videos.append(_api.Change(
            kind="video", theme_name=plan.decoded, price=0,
            before=f"{plan.ext.lstrip('.') or '?'}"
                   + (f", {got.codec}" if got.codec else "")
                   + f", {_api.fmt_size(plan.size)}",
            after=f"av1 crf {max(0, min(63, int(self.s.video_crf)))}"
                  + (f", {height}p" if height else "")
                  + f", {_api.fmt_size(got.size)}",
            title=plan.new_decoded,
            # Медиа идёт в таблице после вопросов: картинки, дорожки, ролики.
            order=result.questions + result.heavy_images
            + len(result.audios) + len(result.videos)))
        done[plan.name] = (plan.new_name, got.out)
    if self.stopped():
        result.cancelled = True
    if done:
        _api.retarget_refs(root, {p.decoded: p.new_decoded for p in plans
                             if p.name in done})
    return done

def _compress_video_one(self, plan: _api._MediaPlan) -> _api.Optional[_api._MediaDone]:
    """Один ролик: AV1 + opus. Пустой out — оставляем как было.

        Зовётся из потока, как и картинки с дорожками. Решение «трогать или
        нет» принимается уже здесь: тяжёлый файл берём всегда, лёгкий — только
        если он не в AV1 и это разрешено настройкой."""
    if self.stopped():
        return None
    limit = int(max(0.1, float(self.s.video_min_mb)) * 1024 * 1024)
    raw, codec = "", ""
    out = _api.os.path.join(_api._temp_dir(), f"siqvid_{_api.uuid.uuid4().hex}.mp4")
    try:
        raw = self._extract(plan, "siqvid")
        if plan.size <= limit:
            codec = self._video_codec(raw)
            if not codec:
                return _api._MediaDone(note=f"«{plan.decoded}»: кодек не "
                                       f"опознан, не трогаю.")
            if codec == _api.VIDEO_TARGET_CODEC:
                return _api._MediaDone(note=f"«{plan.decoded}»: и так AV1, "
                                       f"легче порога — не трогаю.")
        else:
            codec = self._video_codec(raw)
        if not self._to_av1(raw, out):
            _api._drop(out)          # ffmpeg мог оставить недописанный файл
            return _api._MediaDone(note=f"«{plan.decoded}»: перекодировать не "
                                   f"вышло, оставляю как есть.")
        new_size = _api.os.path.getsize(out)
        if new_size >= plan.size:
            _api._drop(out)
            return _api._MediaDone(note=f"«{plan.decoded}»: после перекода не "
                                   f"легче, оставляю.")
    except (OSError, _api.zipfile.BadZipFile) as e:
        _api._drop(out)
        return _api._MediaDone(note=f"«{plan.decoded}»: {e}")
    finally:
        _api._drop(raw)
    return _api._MediaDone(out=out, size=new_size, codec=codec)

def _video_codec(self, raw: str) -> str:
    """Кодек первой видеодорожки файла («» — узнать не вышло)."""
    code, out = _api.run_hidden(
        [_api.FFPROBE, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=codec_name",
         "-of", "default=noprint_wrappers=1", raw],
        self._should_stop, timeout=60.0, capture=True)
    if code != 0:
        return ""
    return _api.parse_probe_codec(out)

def _video_filter(self) -> list[str]:
    """`-vf` под выбранную высоту (пусто — разрешение не трогаем).

        Ролик только уменьшается: min с высотой источника не даст растянуть
        480p до «тысячи восьмидесяти» — это был бы вес без единого лишнего
        пикселя. Ширина считается сама и остаётся чётной (-2), иначе libsvtav1
        откажется кодировать."""
    height = _api.nearest_height(self.s.video_height)
    if not height:
        return []
    return ["-vf", f"scale=-2:'min({height},ih)':flags=bicubic"]

def _to_av1(self, raw: str, out: str) -> bool:
    """Перекод ролика — те же флаги, что во вкладке «Обработка»
        (workers.ProcessWorker._av1_encoder_args) и в генераторе паков:
        libsvtav1, keyint=-1 и scd=1 (ключевые кадры только на сменах сцены),
        crf и пресет из настроек. Звук — тот же opus и с той же нормализацией,
        что у дорожек пака, иначе ролик звучал бы громче соседних вопросов."""
    crf = max(0, min(63, int(self.s.video_crf)))
    preset = max(0, min(13, int(self.s.video_preset)))
    kbps = _api.nearest_bitrate(self.s.audio_kbps)
    cmd = ([_api.FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", raw,
            # 0:V? — только настоящее видео: обложки и вложения в av1 не
            # переложить, а ffmpeg на них спотыкается (то же, что
            # workers._map_av_args).
            "-map", "0:V?", "-map", "0:a?",
            "-c:v", "libsvtav1", "-crf", str(crf), "-preset", str(preset),
            "-svtav1-params", f"tune={_api.VIDEO_TUNE}:keyint=-1:scd=1",
            "-pix_fmt", _api.VIDEO_PIX_FMT]
           + self._video_filter()
           + ["-af", _api.audio_filter_chain(self.s), "-c:a", "libopus",
              "-b:a", f"{kbps}k", "-vbr", "on", "-application", "audio",
              "-movflags", "+faststart", out])
    code, _out = _api.run_hidden(cmd, self._should_stop, timeout=_api.VIDEO_TIMEOUT)
    return code == 0 and _api.os.path.exists(out) and _api.os.path.getsize(out) > 0

# ── неиспользуемые файлы ──────────────────────────────────────────────
def _do_unused(self, root, result, media: dict) -> set:
    """Находит медиа, на которое в паке нет ни одной ссылки, и возвращает
        имена записей, которые в новый архив писать не надо.

        Зовётся ПОСЛЕ всех правок content.xml: ссылки к этому моменту уже
        переписаны на пережатые файлы, а постеры уже вписаны в ответы. media —
        то, что пережато: старое имя записи там сменилось на новое, и по
        старому её, конечно, никто не зовёт."""
    refs = _api.referenced_names(root)
    # Имена, которые пак получит взамен пережатых, тоже считаются занятыми:
    # ссылка на них есть, просто зовут они другой файл.
    try:
        with _api.zipfile.ZipFile(self.path) as zf:
            names = [i.filename for i in zf.infolist() if not i.is_dir()]
            sizes = {i.filename: int(i.file_size) for i in zf.infolist()}
    except (OSError, _api.zipfile.BadZipFile) as e:
        raise _api.UpgradeError(f"Файл не читается как .siq: {e}") from e
    doomed = _api.unused_entries(names, refs, keep=set(media or {}))
    if not doomed:
        self.log("Неиспользуемых файлов в паке нет.")
        return set()
    # Весь пак разом не сносим никогда: если «неиспользуемым» вышло всё
    # медиа, значит ссылки записаны как-то иначе, а не пак из одного мусора.
    media_total = sum(1 for n in names if _api.is_media_entry(n))
    if media_total and len(doomed) >= media_total:
        self.log(f"Неиспользуемыми выглядят все {media_total} файл(ов) "
                 f"медиа — не трогаю ни одного: так не бывает.")
        return set()
    for name in doomed:
        size = sizes.get(name, 0)
        result.saved_unused_bytes += size
        result.unused.append(_api.Change(
            kind="unused", theme_name=_api.entry_basename(name), price=0,
            before=_api.fmt_size(size), after="файл удалён (ссылок на него нет)",
            title=name,
            order=result.questions + result.heavy_images
            + len(result.audios) + len(result.videos) + len(result.unused)))
    self.log(f"Неиспользуемых файлов удалено: {len(doomed)} "
             f"({_api.fmt_size(result.saved_unused_bytes)}).")
    return set(doomed)

# ── запись ────────────────────────────────────────────────────────────
def _out_path(self, out_path: _api.Optional[str]) -> str:
    if out_path:
        target = out_path
    else:
        folder = (self.s.out_dir or "").strip() or _api.os.path.dirname(self.path)
        base = _api.os.path.splitext(_api.os.path.basename(self.path))[0]
        name = _api.safe_filename(f"{base}{_api.OUT_SUFFIX}", "Пак") + ".siq"
        target = _api.os.path.join(folder, name)
    _api.os.makedirs(_api.os.path.dirname(target) or ".", exist_ok=True)
    return str(_api.unique_path(target))
