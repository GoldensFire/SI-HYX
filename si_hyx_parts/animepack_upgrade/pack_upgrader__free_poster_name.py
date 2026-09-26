# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""PackUpgrader: _free_poster_name. Public namespace: animepack_upgrade."""
from __future__ import annotations
import animepack_upgrade as _api


def _free_poster_name(self, want: str) -> str:
    """Имя, которого в паке ещё нет (в архиве уже может лежать одноимённый
        файл — подменять чужую картинку нельзя)."""
    if not self._taken_names:
        try:
            with _api.zipfile.ZipFile(self.path) as zf:
                self._taken_names = {
                    _api.unquote(n.replace("\\", "/")).rsplit("/", 1)[-1].lower()
                    for n in zf.namelist()}
        except (OSError, _api.zipfile.BadZipFile):  # pragma: no cover
            self._taken_names = {""}
    base, ext = _api.os.path.splitext(want)
    name = want
    for n in range(2, 1000):
        if name.lower() not in self._taken_names:
            break
        name = f"{base} ({n}){ext}"
    return name

@staticmethod
def _url_ext(url: str, default: str = ".jpg") -> str:
    ext = _api.os.path.splitext(str(url or "").split("?")[0])[1].lower()
    return ext if ext in (".jpg", ".jpeg", ".png", ".webp") else default

def _fetch(self, url: str) -> bytes:
    """Байты картинки. Сессия — общая с клиентом Shikimori (там уже стоят
        заголовки и таймауты), своя заводится только без него."""
    session = getattr(self._api, "session", None) if self._api else None
    if session is None:
        session = getattr(self.api, "session", None)
    if session is None:  # pragma: no cover — клиент всегда с сессией
        import requests
        session = requests.Session()
    resp = session.get(url, timeout=(10, 60))
    resp.raise_for_status()
    return resp.content

# ── картинки ──────────────────────────────────────────────────────────
def _heavy_images(self) -> list[tuple[str, int]]:
    """Записи архива с картинками тяжелее порога: [(имя в архиве, байт)]."""
    limit = int(max(0.1, float(self.s.image_min_mb)) * 1024 * 1024)
    heavy: list[tuple[str, int]] = []
    try:
        with _api.zipfile.ZipFile(self.path) as zf:
            for info in zf.infolist():
                if info.is_dir() or info.file_size <= limit:
                    continue
                name = _api.unquote(info.filename.replace("\\", "/"))
                if _api.os.path.splitext(name)[1].lower() in _api.COMPRESS_EXTS:
                    heavy.append((info.filename, info.file_size))
    except (OSError, _api.zipfile.BadZipFile) as e:
        raise _api.UpgradeError(f"Файл не читается как .siq: {e}") from e
    return heavy

def _plans(self, heavy, new_ext: str) -> list[_api._MediaPlan]:
    """Что с чем делать: имена новых файлов раздаём ЗАРАНЕЕ и по порядку.

        Само кодирование идёт потом и в несколько потоков, а имена должны
        получаться те же самые, в каком бы порядке кодировки ни закончились."""
    plans: list[_api._MediaPlan] = []
    try:
        with _api.zipfile.ZipFile(self.path) as zf:
            # Занятые ИМЕНА файлов, без папок: ссылка в content.xml зовёт
            # файл по имени, и одноимённые в разных папках — это уже спор.
            taken = {_api.unquote(n.replace("\\", "/")).rsplit("/", 1)[-1].lower()
                     for n in zf.namelist()}
            # Постеры и уже пережатые картинки кладутся раньше, и в архиве
            # их ещё нет — но имена уже заняты.
            taken |= {n.rsplit("/", 1)[-1].lower() for n in self._extra}
            taken |= set(self._new_names)
    except (OSError, _api.zipfile.BadZipFile) as e:
        raise _api.UpgradeError(f"Файл не читается как .siq: {e}") from e
    for name, size in heavy:
        folder, _, raw_base = name.replace("\\", "/").rpartition("/")
        decoded = _api.unquote(raw_base)
        base, ext = _api.os.path.splitext(decoded)
        # Имя может быть занято: в паках рядом с «кадр.webp» лежит
        # «кадр.avif» (вопрос и ответ одного тайтла). Подменять чужой файл
        # нельзя — берём соседнее свободное имя, ссылка всё равно
        # переписывается на него.
        new_decoded = f"{base}{new_ext}"
        for n in range(2, 100):
            if new_decoded.lower() not in taken:
                break
            new_decoded = f"{base} ({n}){new_ext}"
        else:  # pragma: no cover — сотня одноимённых файлов в одном паке
            self.log(f"«{decoded}»: свободного имени не нашлось, пропускаю.")
            continue
        taken.add(new_decoded.lower())
        self._new_names.add(new_decoded.lower())
        plans.append(_api._MediaPlan(
            name=name, size=size, decoded=decoded, ext=ext,
            new_decoded=new_decoded, folder=folder,
            percent=(raw_base != decoded)))
    return plans

def _run_jobs(self, plans: list, work, base_step: int, steps: int,
              label: str, jobs: int) -> list:
    """Гоняет work(plan) по нескольким потокам и отдаёт ответы В ПОРЯДКЕ
        plans: отчёт и имена файлов не должны зависеть от того, какое
        кодирование закончилось первым.

        Работа тут — внешний ffmpeg, поэтому потоки Python ему не мешают: они
        только ждут процессы (GIL на это время отпущен)."""
    total = len(plans)
    out: list = [None] * total
    jobs = max(1, min(int(jobs), total))
    if jobs == 1:
        for j, plan in enumerate(plans):
            self._progress(base_step + j + 1, steps, f"{label} {j + 1}/{total}")
            out[j] = work(plan)
        return out
    with _api.ThreadPoolExecutor(max_workers=jobs,
                            thread_name_prefix="siqmedia") as pool:
        futures = {pool.submit(work, plan): j for j, plan in enumerate(plans)}
        for done, fut in enumerate(_api.as_completed(futures), start=1):
            out[futures[fut]] = fut.result()
            self._progress(base_step + done, steps, f"{label} {done}/{total}")
    return out

def _extract(self, plan: _api._MediaPlan, prefix: str) -> str:
    """Достаёт запись из архива во временный файл (свой архив на поток:
        один объект ZipFile на несколько потоков не рассчитан)."""
    raw = _api.os.path.join(_api._temp_dir(),
                       f"{prefix}_{_api.uuid.uuid4().hex}{plan.ext}")
    with _api.zipfile.ZipFile(self.path) as zf, open(raw, "wb") as f:
        f.write(zf.read(plan.name))
    return raw

def _do_images(self, heavy, root, result, base_step: int,
               steps: int) -> dict:
    """Пережимает тяжёлые картинки и переписывает ссылки на них.

        Возвращает {имя записи в архиве: (новое имя, путь к готовому AVIF)} —
        сам архив собирается позже, в _write."""
    self.log(f"Картинок тяжелее {self.s.image_min_mb:g} МБ: {len(heavy)}.")
    plans = self._plans(heavy, ".avif")
    made = self._run_jobs(plans, self._compress_one, base_step, steps,
                          "картинка", _api.media_jobs(_api.IMAGE_JOBS))
    done: dict[str, tuple[str, str]] = {}
    for plan, got in zip(plans, made):
        if got is None or not got.out:
            if got is not None and got.note and not self.stopped():
                self.log(got.note)
            continue
        result.saved_bytes += plan.size - got.size
        result.images.append(_api.Change(
            kind="image", theme_name=plan.decoded, price=0,
            before=f"{plan.ext.lstrip('.') or '?'}, {_api.fmt_size(plan.size)}",
            after=f"avif, {_api.fmt_size(got.size)}",
            title=plan.new_decoded,
            # Картинки идут после всех вопросов — так они и стоят в таблице.
            order=result.questions + len(result.images)))
        done[plan.name] = (plan.new_name, got.out)
    if self.stopped():
        result.cancelled = True
    if done:
        # Ссылка в content.xml зовёт файл по имени, и после переименования
        # её надо перевести на .avif — иначе пак останется без картинок.
        _api.retarget_refs(root, {p.decoded: p.new_decoded for p in plans
                             if p.name in done})
    return done

def _compress_one(self, plan: _api._MediaPlan) -> _api.Optional[_api._MediaDone]:
    """Одна картинка: AVIF под лимит. Пустой out — оставляем как было.

        Зовётся из потока: ничего общего с соседями не трогает, всё нужное уже
        разложено по plan, а сообщение для лога отдаётся ответом."""
    if self.stopped():
        return None
    raw = ""
    out = _api.os.path.join(_api._temp_dir(), f"siqimg_{_api.uuid.uuid4().hex}.avif")
    try:
        raw = self._extract(plan, "siqimg")
        if not self._to_avif(raw, out):
            _api._drop(out)          # ffmpeg мог оставить недописанный файл
            return _api._MediaDone(note=f"«{plan.decoded}»: сжать не вышло, "
                                   f"оставляю как есть.")
        new_size = _api.os.path.getsize(out)
        if new_size >= plan.size:
            # Так бывает с крошечными PNG-скриншотами: пережатие только
            # прибавило бы весу.
            _api._drop(out)
            return _api._MediaDone(note=f"«{plan.decoded}»: после сжатия не "
                                   f"легче, оставляю.")
    except (OSError, _api.zipfile.BadZipFile) as e:
        _api._drop(out)
        return _api._MediaDone(note=f"«{plan.decoded}»: {e}")
    finally:
        _api._drop(raw)
    return _api._MediaDone(out=out, size=new_size)

def _to_avif(self, raw: str, out: str, limit_kb: _api.Optional[int] = None) -> bool:
    """Кодирование — общее с генератором паков и «Обработкой» (avif_fit:
        libaom, tune=iq, подбор CQ под лимит, при нужде ужимание разрешения).
        Настройки те же «быстрые»: cpu-used 8, четыре прохода, сторона 1280.

        limit_kb — под сколько ужимать; по умолчанию это настройка сжатия
        картинок пака, у постера свой лимит (тот же, что у генератора)."""
    from avif_fit import fit_to_limit, start_cq_guess
    limit = max(10, int(limit_kb if limit_kb else self.s.image_limit_kb))
    start = None
    try:
        from config import Image
        with Image.open(raw) as im:
            w, h = im.size
        if max(w, h) > _api.IMAGE_MAX_SIDE:
            k = _api.IMAGE_MAX_SIDE / float(max(w, h))
            w, h = max(1, int(w * k)), max(1, int(h * k))
        start = start_cq_guess(w, h, limit)
    except Exception:  # noqa: BLE001 — без Pillow просто идём с CQ=0
        start = None
    return fit_to_limit(raw, out, limit,
                        speed=max(0, min(8, int(self.s.image_speed))),
                        passes=_api.IMAGE_FIT_PASSES, start_cq=start,
                        max_side=_api.IMAGE_MAX_SIDE,
                        should_stop=self._should_stop)

# ── аудио ─────────────────────────────────────────────────────────────
def _heavy_audio(self) -> list[tuple[str, int]]:
    """Записи архива со звуком тяжелее порога: [(имя в архиве, байт)]."""
    limit = int(max(0.1, float(self.s.audio_min_mb)) * 1024 * 1024)
    heavy: list[tuple[str, int]] = []
    try:
        with _api.zipfile.ZipFile(self.path) as zf:
            for info in zf.infolist():
                if info.is_dir() or info.file_size <= limit:
                    continue
                name = _api.unquote(info.filename.replace("\\", "/"))
                if _api.os.path.splitext(name)[1].lower() in _api.AUDIO_EXTS:
                    heavy.append((info.filename, info.file_size))
    except (OSError, _api.zipfile.BadZipFile) as e:
        raise _api.UpgradeError(f"Файл не читается как .siq: {e}") from e
    return heavy

def _do_audio(self, heavy, root, result, base_step: int,
              steps: int) -> dict:
    """Перекодирует тяжёлые дорожки в opus и переписывает ссылки на них.

        Возвращает {имя записи в архиве: (новое имя, путь к готовому opus)} — в
        том же виде, что и картинки: архив собирается позже, в _write."""
    self.log(f"Аудио тяжелее {self.s.audio_min_mb:g} МБ: {len(heavy)}.")
    target = _api.nearest_bitrate(self.s.audio_kbps)
    plans = self._plans(heavy, ".opus")
    made = self._run_jobs(plans, self._compress_audio_one, base_step, steps,
                          "аудио", _api.media_jobs(_api.AUDIO_JOBS))
    done: dict[str, tuple[str, str]] = {}
    for plan, got in zip(plans, made):
        if got is None or not got.out:
            if got is not None and got.note and not self.stopped():
                self.log(got.note)
            continue
        result.saved_audio_bytes += plan.size - got.size
        result.audios.append(_api.Change(
            kind="audio", theme_name=plan.decoded, price=0,
            before=f"{plan.ext.lstrip('.') or '?'}"
                   + (f", {got.was} кбит" if got.was else "")
                   + f", {_api.fmt_size(plan.size)}",
            after=f"opus {target} кбит, {_api.fmt_size(got.size)}",
            title=plan.new_decoded,
            # Медиа идёт в таблице после вопросов, следом за картинками.
            order=result.questions + result.heavy_images
            + len(result.audios)))
        done[plan.name] = (plan.new_name, got.out)
    if self.stopped():
        result.cancelled = True
    if done:
        _api.retarget_refs(root, {p.decoded: p.new_decoded for p in plans
                             if p.name in done})
    return done
