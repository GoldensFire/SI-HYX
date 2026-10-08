# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""ProcessWorker, цепочка atempo и пул картинок. Public namespace: workers."""
import workers as _api
from si_hyx_parts.workers.process_filters import ProcessFiltersMixin
from si_hyx_parts.workers.process_images import ProcessImagesMixin


def _build_atempo_chain(speed_factor: float) -> list:
    """Строит цепочку atempo-фильтров для FFmpeg.
    FFmpeg ограничивает atempo диапазоном [0.5, 2.0], поэтому
    большие/малые значения разбиваются на несколько звеньев.
    """
    chain = []
    t = speed_factor
    while t > 2.0:
        chain.append("atempo=2.0")
        t /= 2.0
    while t < 0.5:
        chain.append("atempo=0.5")
        t *= 2.0
    if abs(t - 1.0) > 0.001:
        chain.append(f"atempo={t:.6f}")
    return chain

_build_atempo_chain.__module__ = _api.__name__
_api._build_atempo_chain = _build_atempo_chain

class _ImgRunnable(_api.QRunnable):
    """Обёртка для параллельной обработки одного изображения в QThreadPool.
    Потоки QThreadPool — настоящие потоки Qt: эмит сигналов из них безопасен,
    а очистка корректна (в отличие от обычных threading.Thread)."""
    def __init__(self, worker, item, start):
        super().__init__()
        self.worker = worker
        self.item = item
        self.start = start

    def run(self):
        try:
            self.worker._process_item(self.item, False, self.start)
        except Exception:
            pass

_ImgRunnable.__module__ = _api.__name__
_api._ImgRunnable = _ImgRunnable

class ProcessWorker(ProcessFiltersMixin, ProcessImagesMixin, _api.QThread):
    progress = _api.pyqtSignal(str, int)
    status = _api.pyqtSignal(str, str, str)
    log = _api.pyqtSignal(str)
    global_progress = _api.pyqtSignal(int, str)
    finished_all = _api.pyqtSignal()
    update_item_sig = _api.pyqtSignal(str, str, str)
    update_lufs_sig = _api.pyqtSignal(str, object, object)
    update_dur_sig = _api.pyqtSignal(str, str)   # iid, длительность итогового файла (сек, строкой)
    active_threads = _api.pyqtSignal(int, int)  # (активных воркеров, максимум) — счётчик в UI
    xpsnr_sig = _api.pyqtSignal(str, object)     # iid, оценка XPSNR в дБ (float) | None

    # Нижняя граница preset для пробных кодирований в _metric_crf_search —
    # не даём поиску унаследовать очень медленный (0-4) preset финального
    # кодирования, иначе один пробный энкод 1080p может идти минутами.
    _SEARCH_PRESET_FLOOR = 6

    def __init__(self, queue_ref, settings, removed_ids=None):
        super().__init__()
        self.queue = queue_ref
        self.settings = settings
        self.stop_flag = False
        # Живой набор iid'ов, удалённых пользователем из очереди во время
        # обработки (тот же объект-множество, что и у MediaTab._removed_ids) —
        # позволяет прервать УЖЕ идущий ffmpeg для конкретного файла, а не
        # только не начинать ещё не стартовавшие (см. cancel_check в
        # run_ffmpeg_capture).
        self.removed_ids = removed_ids if removed_ids is not None else set()
        self.svt_available = _api.require_svt()
        self._img_pool = None  # QThreadPool для параллельной обработки изображений
        self._active_count = 0
        self._active_lock = _api.threading.Lock()
        self._max_threads = 1
        self._priority_flag = self._priority_creationflag(settings.get('priority', 'normal'))

    _AI_BRANDS = ('gemini', 'chatgpt')
    _RAND_CHARS = 'abcdefghijklmnopqrstuvwxyz0123456789'

    @staticmethod
    def _sanitize_name(name: str) -> str:
        """Если имя содержит AI-бренд — заменяет на 6 случайных символов."""
        if any(b in name.lower() for b in _api.ProcessWorker._AI_BRANDS):
            return ''.join(_api.random.choices(_api.ProcessWorker._RAND_CHARS, k=6))
        return name

    def stop(self): self.stop_flag = True

    def measure_loudness(self, path, start=None, dur=None):
        return _api.measure_loudness(path, should_stop=lambda: self.stop_flag, start=start, dur=dur)

    @staticmethod
    def _priority_creationflag(priority):
        """Windows priority-class флаг для creationflags по выбору пользователя.
        Низкий = Low (IDLE), Обычный = Normal, Высокий = High — как в Диспетчере задач.
        На не-Windows возвращает 0."""
        if not _api.IS_WIN:
            return 0
        p = (priority or 'normal').lower()
        if p in ('low', 'низкий', 'idle'):
            return getattr(_api.subprocess, 'IDLE_PRIORITY_CLASS', 0)
        if p in ('high', 'высокий'):
            return getattr(_api.subprocess, 'HIGH_PRIORITY_CLASS', 0)
        return getattr(_api.subprocess, 'NORMAL_PRIORITY_CLASS', 0)

    def _inc_active(self, weight=1):
        with self._active_lock:
            self._active_count += weight
            n = self._active_count
        self.active_threads.emit(n, max(1, self._max_threads))

    def _dec_active(self, weight=1):
        with self._active_lock:
            self._active_count = max(0, self._active_count - weight)
            n = self._active_count
        self.active_threads.emit(n, max(1, self._max_threads))

    def _out_dir_for(self, path):
        """Каталог экспорта: выбранная пользователем папка (если задана и
        существует), иначе — рядом с исходным файлом."""
        d = self.settings.get('export_dir') or ''
        if d and _api.os.path.isdir(d):
            return d
        return _api.os.path.dirname(path) or "."

    @staticmethod
    def _source_has_alpha(path: str) -> bool:
        """True только если в изображении есть пиксели с реальной прозрачностью."""
        ext = _api.os.path.splitext(path)[1].lower()
        if ext in {'.png', '.gif', '.tiff', '.tif', '.webp', '.bmp',
                   '.ico', '.avif', '.heic', '.heif'}:
            if _api.Image:
                try:
                    with _api.Image.open(path) as im:
                        # Палитра с tRNS — есть прозрачность
                        if im.mode == 'P' and 'transparency' in im.info:
                            return True
                        # LA / RGBa — всегда с альфой
                        if im.mode in ('LA', 'RGBa'):
                            return True
                        # RGBA — проверяем реальные пиксели
                        if im.mode == 'RGBA':
                            r, g, b, a = im.split()
                            return a.getextrema()[0] < 255  # есть хоть один непрозрачный пиксель
                        return False
                except Exception:
                    pass
        # Видео — ffprobe
        try:
            p = _api.subprocess.run(
                [_api.FFPROBE, "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=pix_fmt",
                 "-of", "default=noprint_wrappers=1:nokey=1", path],
                stdout=_api.subprocess.PIPE, stderr=_api.subprocess.DEVNULL,
                text=True, encoding="utf-8", errors="replace", creationflags=_api.CREATE_NO_WINDOW,
            )
            fmt = p.stdout.strip().lower()
            _NO_ALPHA = {'gray', 'grayf32le', 'grayf32be', 'rgb24', 'bgr24',
                         'rgb48le', 'rgb48be', 'bgr48le', 'bgr48be'}
            return 'a' in fmt and fmt not in _NO_ALPHA
        except Exception:
            return False

    @staticmethod
    def _bt709_color_args(path: str) -> list:
        """-color_primaries/-color_trc/-colorspace bt709 — тегирует поток BT.709,
        чтобы плееры не гадали и не показывали SDR-видео «вымытым»/пересвеченным
        из-за неизвестного цветового пространства. Не меняет пиксели — только
        метаданные контейнера.

        БЕЗОПАСНО только для обычных SDR-источников: у настоящего HDR (PQ/HLG,
        BT.2020) эти теги были бы НЕВЕРНЫМИ и испортили бы цвет при просмотре —
        поэтому сперва читаем теги исходника через ffprobe и тегируем BT.709
        лишь когда он сам уже BT.709 или вообще без тегов (частый случай для
        обычных SDR-рипов) — то есть только ДОБАВЛЯЕМ то, что и так верно, а не
        переопределяем реально другое цветовое пространство."""
        try:
            p = _api.subprocess.run(
                [_api.FFPROBE, "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=color_primaries,color_transfer,color_space",
                 "-of", "default=noprint_wrappers=1:nokey=1", path],
                stdout=_api.subprocess.PIPE, stderr=_api.subprocess.DEVNULL,
                text=True, encoding="utf-8", errors="replace", creationflags=_api.CREATE_NO_WINDOW, timeout=15,
            )
            vals = [v.strip().lower() for v in (p.stdout or "").splitlines()]
        except Exception:
            return []
        _SAFE = {"", "unknown", "unspecified", "n/a", "bt709", "bt470bg", "smpte170m"}
        _HDR_MARKERS = ("bt2020", "smpte2084", "arib-std-b67")
        if any(any(m in v for m in _HDR_MARKERS) for v in vals):
            return []  # настоящий HDR/BT.2020 — не трогаем
        if any(v not in _SAFE for v in vals):
            return []  # что-то нестандартное — на всякий случай не тегируем
        return ["-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709"]

    # ── Обрезка чёрных полос ────────────────────────────────────────────────
    # Ярче этого (0..255) пиксель уже не «чёрный»: в сжатом видео полосы не
    # идеально нулевые.
    _CROP_LUMA_LIMIT = 24
    # Сколько ярких пикселей в линии списываем на шум — доля её длины (0.5%, но
    # не меньше 4 пикселей): полосы в сжатом видео звенят у края содержимого, и
    # пара засветок не должна отменять обрезку целой полосы. Выше поднимать
    # нельзя — у реальной «тонкой» строки содержимого (край панели задач) ярких
    # пикселей было 18 из 1920, то есть меньше процента. Именно этим детект и
    # отличается от cropdetect: тот считает СРЕДНЮЮ яркость линии, поэтому
    # строка, чёрная везде, кроме мелкого яркого элемента, для него «чёрная».
    _CROP_NOISE_SHARE = 0.005
    _CROP_NOISE_MIN = 4
    _CROP_WINDOW_SEC = 12.0     # длина анализируемого отрезка
    _CROP_SAMPLE_BYTES = 40_000_000   # сколько памяти отдаём под кадры выборки

    # pix_fmt для AVIF (всегда 10-бит; при альфе цвет идёт yuva420p10le, а сама
    # альфа выносится alphaextract'ом отдельным потоком) — общий с avif_fit.
    _avif_pix_fmt = staticmethod(_api.avif_pix_fmt)

    def process_media(self, item, cb):
        path = item['path']
        base, ext = _api.os.path.splitext(path)
        out_dir = self._out_dir_for(path)
        sv = self.settings.get('video', {})
        sa = self.settings.get('audio', {})
        crf = sv.get('crf', 35)

        speed_percent = sv.get('speed', 100)
        speed_factor = float(speed_percent) / 100.0
        video_enabled = sv.get('enabled', True)

        # Обрезка + «Обработка» одним проходом (кнопка «Обрезать и обработать» в
        # Монтаже после неточной copy-обрезки): item['trim'] = (in_s, out_s) —
        # режем диапазон исходника ПРЯМО в этом же кодировании, без отдельного
        # x264-реэнкода перед «Обработкой» (которое раньше давало двойное
        # поколение потерь). trim_pre/trim_post вставляются туда, где команда
        # ПЕРВЫЙ раз читает оригинальный `path` (Pass-1, если он есть, иначе
        # Pass-2/прямой проход) — при video_enabled=True Pass-1 архитектурно не
        # запускается (см. step1_needed ниже), так что почти всегда это Pass-2.
        trim = item.get('trim')
        if trim:
            trim_pre, trim_post, t0 = self._trim_seek_args(trim[0], trim[1], speed_factor)
        else:
            trim_pre, trim_post, t0 = [], [], 0.0
        # Выбранная в Монтаже аудиодорожка (кнопка «Обрезать и обработать» на
        # многодорожечном источнике) — иначе -map "0:a?" всегда брал первую
        # дорожку контейнера, игнорируя выбор пользователя.
        audio_index = item.get('audio_index')
        a_map_sel = f"0:{audio_index}" if audio_index is not None else "0:a?"
        # t0 сдвинут видеофильтрам через setpts (он стоит РАНЬШЕ fade в vf_list —
        # к моменту fade PTS уже поделены на speed_factor), а аудиофильтрам —
        # БЕЗ деления (atempo в audio_filters добавляется В КОНЦЕ списка, после
        # fade-фильтров, так что на момент afade PTS ещё исходные).
        t0_video = (t0 / speed_factor) if speed_factor else t0

        vcodec = _api.get_video_codec(path)
        # «(Аудио) Перекодировать настройками «Обработки»» из Монтажа: видеоряд
        # источника игнорируем целиком и гоним ТОЛЬКО звук теми же настройками
        # (битрейт/loudnorm/fade/скорость), что и обычная «Обработка» — итог
        # .opus. Технически это ровно тот же путь, что и для файла БЕЗ видео,
        # поэтому просто гасим is_video: ниже он уже разводит аудио-онли ветку
        # (Pass-1 в opus + перенос) от видеокодирования.
        audio_only = bool(item.get('audio_only'))
        is_video = (vcodec is not None) and not audio_only

        out_ext = ".mp4" if is_video else ".opus"
        out_name = _api.os.path.basename(base)
        sanitized = self._sanitize_name(out_name)
        if sanitized != out_name:
            self.log.emit(f"Имя переименовано (AI-бренд): «{out_name}» → «{sanitized}»")
            out_name = sanitized

        # Удалить аудио — при видео полностью вырезаем звуковую дорожку (-an),
        # остальные аудио-настройки (loudnorm/fade/degrade/битрейт) тогда не
        # имеют смысла. Для аудио-файлов (is_video=False) галочка игнорируется —
        # вырезать звук из чистого аудио значило бы получить пустой файл.
        remove_audio = (bool(sa.get('remove')) or bool(item.get('remove_audio'))) and is_video

        suffix = self._out_suffix(is_video, video_enabled, sv.get('metric'), crf,
                                  speed_percent, remove_audio,
                                  sa.get('norm'), sa.get('fade'))
        out_name = out_name + suffix + out_ext
        out = _api.os.path.join(out_dir, out_name)

        sel_br = self.settings.get('audio', {}).get('bitrate', '128')
        audio_bitrate = self.get_target_bitrate_str(path, sel_br)

        before_lufs = None
        if not remove_audio:
            try:
                before_lufs = (self.measure_loudness(path, start=trim[0], dur=item.get('dur'))
                                if trim else self.measure_loudness(path))
            except Exception: pass
        # Замер громкости делается всегда (для «Было LUFS») и для длинных файлов
        # длится минуты — если за это время нажали «Стоп», прерываемся здесь же.
        if self.stop_flag:
            raise Exception("StoppedByUser")

        if is_video and video_enabled and not self.svt_available:
            raise Exception("libsvtav1 не доступен в вашей сборке ffmpeg — скрипт настроен работать ТОЛЬКО с svt (libsvtav1).")

        audio_filters = []
        if not remove_audio:
            # Длительность нужна только ветке fade-out — считаем её лениво (и
            # только когда fade включён), чтобы не дёргать ffprobe зря. dur мог не
            # посчитаться при добавлении (кириллица в пути, ffprobe упал) — тогда
            # читаем сейчас, когда файл точно доступен.
            fade_out_dur = 0.0
            if sa.get('fade'):
                fade_out_dur = item.get('dur') or 0.0
                if fade_out_dur <= 0.0:
                    try:
                        fade_out_dur, *_ = _api.get_media_info(path)
                    except Exception:
                        fade_out_dur = 0.0
            audio_filters = self._build_audio_filters(sa, t0, fade_out_dur, speed_factor)

        temp_files = []
        attempted_out = out

        try:
            current_input = path
            audio_codec = "libopus"  # opus в mp4
            # is_video уже учитывает audio_only (см. выше): для аудио-режима
            # кодек видео не важен вовсе — иначе HEVC-источник уводил бы звук в
            # лишний Pass-1 (результат тот же .opus, но проход впустую).
            is_hevc = bool(is_video and vcodec and ('hevc' in vcodec or 'h265' in vcodec))
            # Когда видео ВСЁ РАВНО перекодируется (step2), отдельный Pass-1 (аудио +
            # copy видео в .mkv) ВРЕДЕН: круговой проход через .mkv ломает тайминги —
            # видео становится CFR-30 (длиннее исходника), а задержка loudnorm/opus
            # превращается в стартовый сдвиг аудио (баг «итог длиннее исходника»).
            # Поэтому при перекодировании видео делаем ОДИН проход (аудиофильтры — в
            # step2). Pass-1 нужен только для аудио-онли/копии видео (вывод формирует
            # ветка else ниже).
            single_pass_video = bool(is_video and video_enabled)
            # Видео-КОПИЯ (перекодирование ВЫКЛ) с аудиофильтрами тоже обязана идти
            # ОДНИМ прямым проходом в .mp4. Прогон через .mkv-посредник ретаймит
            # видео в CFR-30 (177к×1/30=5.900 вместо VFR 5.702 → итог длиннее) и
            # навешивает opus CodecDelay на старт аудио (start_time=0.194 →
            # контейнер 6.02). Прямой `-c:v copy` mp4→mp4 сохраняет исходные PTS
            # пакетов, а aresample=async=1 подрезает хвост loudnorm до длины
            # источника. Только при нормальной скорости: смена скорости требует
            # setpts и несовместима с копией видео.
            single_pass_copy = bool(is_video and not video_enabled
                                    and abs(speed_factor - 1.0) <= 0.01)
            step1_needed = (not single_pass_video) and (not single_pass_copy) and (
                is_hevc or bool(audio_filters) or (is_video and abs(speed_factor - 1.0) > 0.01))
            # Сохранять исходный тайминг кадров: VFR-источники (TikTok, записи экрана)
            # иначе растягиваются кодером до CFR-30 и итог становится длиннее. Только
            # при нормальной скорости и без принудительного fps.
            keep_timing = ((single_pass_video or single_pass_copy)
                           and abs(speed_factor - 1.0) <= 0.01
                           and str(sv.get('fps', 'Исходный')) == 'Исходный')

            # Кап длительности вывода = длине источника. Звук после loudnorm +
            # добивки Opus-кадров оказывается на ~50–70 мс длиннее видеодорожки
            # (audio.start_time 0.014 + dur 12.606 = 12.62 при video 12.554), и
            # контейнер (max по дорожкам) растёт. `-t` обрезает только лишний
            # аудиохвост: последний видеокадр PTS < длительности, поэтому видео не
            # теряется. Применяем, когда тайминг сохраняем и звук реально
            # перекодируется с фильтрами (без фильтров аудио копируется — роста нет).
            # Гейтим по СКОРОСТИ (не keep_timing): при изменённой скорости длина
            # вывода = src/speed ≠ src, поэтому -t src_dur был бы неверным. При
            # нормальной скорости итог обязан равняться источнику — даже если сменили
            # fps. Это вторая линия обороны к aresample=async=1 (тот даёт точную
            # длину, -t лишь срезает грубый выброс на кванте opus-кадра).
            normal_speed = abs(speed_factor - 1.0) <= 0.01
            src_dur_cap = item.get('dur') or 0.0
            if src_dur_cap <= 0.0:
                try: src_dur_cap, *_ = _api.get_media_info(path)
                except Exception: src_dur_cap = 0.0
            # dur_cap дублировал бы наш собственный -t из trim_post тем же числом
            # (src_dur_cap уже = item['dur'] = длине отрезка) — пропускаем, чтобы
            # не слать ffmpeg два -t подряд.
            dur_cap = (["-t", f"{float(src_dur_cap):.3f}"]
                       if (normal_speed and audio_filters and src_dur_cap > 0 and not trim) else [])

            if step1_needed:
                # Промежуточный контейнер для видео — Matroska: он принимает копию
                # ЛЮБОГО видеокодека + libopus. .mp4 же отвергает копию ряда
                # кодеков/потоков (легаси-видео, обложки) → "Invalid argument"
                # (exit -22). Финал всё равно делает step2 (AV1→mp4) или ремукс.
                temp_ext = ".mkv" if is_video else ".opus"
                temp_intermediate = _api.os.path.join(_api.TEMP_DIR, f"inter_{_api.uuid.uuid4().hex}{temp_ext}")
                temp_files.append(temp_intermediate)

                # current_input здесь всегда == path (Pass-1 — первый читатель
                # оригинала), поэтому trim_pre/trim_post режут именно исходник.
                cmd_step1 = [_api.FFMPEG, "-y"] + trim_pre + ["-i", current_input] + trim_post \
                            + self._map_av_args(remove_audio, a_map_sel) \
                            + ["-map_metadata", "-1"]
                if remove_audio:
                    cmd_step1 += ["-an"]
                else:
                    # Аудио-онли: этот Pass-1 И ЕСТЬ финальный файл (ветка else
                    # ниже просто переносит .opus-посредник в вывод). Значит хвост
                    # от latency loudnorm надо срезать ЗДЕСЬ, иначе итог длиннее
                    # источника (без -t → 16.47→16.92). aresample=async=1 правит
                    # старт/склейку, реальный кап длины даёт -t (ниже).
                    cmd_step1 += ["-af", self._af_arg(
                        audio_filters,
                        trim_tail=bool((not is_video) and normal_speed and audio_filters))]
                    cmd_step1 += ["-c:a", audio_codec, "-b:a", audio_bitrate]
                if is_video: cmd_step1 += ["-c:v", "copy"]
                else:
                    cmd_step1 += ["-vn"]
                    # Аудио-онли opus: контейнерная длительность = длине аудио-
                    # дорожки. libopus ВСЕГДА добавляет фиксированную задержку
                    # кодера (pre-skip 312 сэмплов = 6.5 мс @48кГц): эмпирически
                    # итог = (-t) + 0.0065 РОВНО, независимо от длины/битрейта.
                    # Поэтому -t компенсируем на pre-skip, чтобы длительность
                    # совпала с источником точь-в-точь (иначе 16.470→16.4765,
                    # округляется до 16.48). Срезаемые 6.5 мс — в самом конце, на
                    # затухании, неслышны. Гейт как у dur_cap: нормальная скорость,
                    # есть аудиофильтры, нет trim (при trim длину задаёт trim_post).
                    if (not remove_audio and normal_speed and audio_filters
                            and src_dur_cap > 0 and not trim):
                        cmd_step1 += ["-t", f"{max(0.0, float(src_dur_cap) - 0.0065):.4f}"]
                cmd_step1 += [temp_intermediate]

                orig_size = _api.os.path.getsize(path) if _api.os.path.exists(path) else 1
                self.run_ffmpeg_capture(cmd_step1, max(1, int(orig_size/1000000)), cb, label="Pass 1 (Audio)", cancel_check=lambda: item["iid"] in self.removed_ids)
                current_input = temp_intermediate

                if not remove_audio:
                    try:
                        after_norm = self.measure_loudness(temp_intermediate)
                        self.update_lufs_sig.emit(item['iid'], before_lufs, after_norm)
                    except Exception: pass

            if is_video and video_enabled:
                if not self.svt_available: raise Exception("libsvtav1 отсутствует — отмена перекодирования.")
                # Аудио в одно-проходном режиме (Pass-1 пропущен): применяем
                # фильтры и кодируем opus прямо здесь. aresample=async=1 + отсутствие
                # .mkv-кругового прохода убирают сдвиг/удлинение аудио. Без фильтров —
                # копируем исходную дорожку без потерь.
                if remove_audio:
                    step2_audio = ["-an"]
                elif single_pass_video and audio_filters:
                    # trim_tail завязан ТОЛЬКО на скорость, не на keep_timing/fps:
                    # подрезка хвоста нужна и когда сменили fps (см. _af_arg).
                    step2_audio = ["-af", self._af_arg(audio_filters, trim_tail=normal_speed),
                                   "-c:a", audio_codec, "-b:a", audio_bitrate]
                else:
                    step2_audio = ["-c:a", "copy"]
                timing_args = ["-fps_mode", "passthrough"] if keep_timing else []
                # current_input здесь всегда == path: step1_needed исключает
                # single_pass_video (см. выше), поэтому trim ещё не применён.
                cmd_step2 = [_api.FFMPEG, "-y"] + trim_pre + ["-i", current_input] + trim_post \
                            + self._map_av_args(remove_audio, a_map_sel) + timing_args \
                            + ["-map_metadata", "-1", "-map_chapters", "-1"]

                vf_list = self._build_video_filters(sv, item, current_input, trim,
                                                    t0, t0_video, speed_factor)
                # Наложенные картинки из Монтажа (режим обрезки «Перекодировать
                # настройками «Обработки»»): PNG приходят уже отрисованными под
                # размер ИСХОДНОГО кадра, поэтому overlay идёт ПЕРВЫМ — до
                # crop/scale/fade, ровно как накладка видна в плеере Монтажа.
                # `format=` берём по pix_fmt исходника: при `auto` граф с RGBA
                # уводил весь кадр в RGB и цвет итога уезжал (см.
                # overlay_chroma_format).
                vf_arg = self._overlay_vf(vf_list, item, current_input)
                # Пробные кодирования подбора CRF/оценки меряют ТОТ ЖЕ кадр, что
                # уйдёт в файл, — иначе метрика считалась бы по картинке без
                # накладок.
                vf_list = [vf_arg] if vf_arg else []

                # FPS из настроек — ОДИН раз на оба профиля («Стандартный» и
                # «Тёмные сцены»). Раньше `-r` дописывался только к cmd_step2, и
                # в профиле «Тёмные сцены» настройка FPS молча игнорировалась:
                # 60-кадровый источник с «Исходный (max 30)» выходил как 60 fps.
                fps_args = self._fps_args(sv.get('fps', 'Исходный') or 'Исходный',
                                          current_input)
                cmd_step2 += fps_args

                preset_mode = sv.get('preset_mode', 'std')
                is_dark_scenes = (preset_mode == "dark")
                # tune SVT-AV1 (0=VQ/1=PSNR/2=SSIM/4=MS-SSIM/5=VMAF), выбирается
                # в настройках (c_tune в tabs.py) — см. _av1_encoder_args.
                video_tune = int(sv.get('tune', 0))

                # Метрика: 'none' — ручной CRF как есть; 'xpsnr' — CRF на этот
                # файл подбирается самостоятельно (_metric_crf_search, без
                # внешних инструментов) под целевое значение метрики (кодек
                # всегда SVT-AV1, тюнинг энкодера — video_tune выше, тот же,
                # что и в финальном кодировании — см. _av1_encoder_args).

                # preset/pix_fmt для пробных кодирований (поиск CRF и/или разовый
                # замер итоговой оценки XPSNR) — те же, что пойдут в реальный
                # финальный энкод этого профиля (см. is_dark_scenes/else дальше).
                preset_for_search = sv.get('pre', 0) if is_dark_scenes else sv.get('pre', 8)
                search_pix_fmt = self._choose_pix_fmt(self._source_has_alpha(current_input))
                # Сэмпл строится ОДИН раз и переживает и подбор CRF, и
                # последующий разовый замер оценки — поэтому убираем его здесь.
                # Когда замеров не будет вовсе (метрика выкл. и колонка оценки
                # скрыта — поведение по умолчанию), нарезка сэмпла тоже не
                # нужна: это лишний проход и копия отрезка в %TEMP%.
                if self._wants_metric_score(sv):
                    metric_sample_input, metric_sample_tmp = self._make_metric_sample(
                        current_input, trim)
                else:
                    metric_sample_input, metric_sample_tmp = current_input, None
                try:
                    crf = self._resolve_crf(item, sv, crf, metric_sample_input,
                                            preset_for_search, search_pix_fmt,
                                            video_tune, vf_list, cb)
                finally:
                    if metric_sample_tmp:
                        try:
                            if _api.os.path.exists(metric_sample_tmp): _api.os.remove(metric_sample_tmp)
                        except Exception: pass

                if is_dark_scenes:
                    # Профиль «Тёмные сцены»: 10-бит, одно-проходный CRF AV1.
                    # SVT-AV1 НЕ поддерживает multi-pass в режиме CRF
                    # ("CRF does not support multi-pass. Use single pass."),
                    # поэтому используем один проход. Для CRF (постоянное качество)
                    # 2-pass всё равно не даёт выигрыша. crf — либо ручной, либо
                    # уже подобран _metric_crf_search под целевую метрику (см. блок выше).
                    has_alpha = self._source_has_alpha(current_input)
                    pix_fmt = self._choose_pix_fmt(has_alpha)
                    preset_val = max(0, min(13, sv.get('pre', 0)))
                    est = max(1, int(_api.os.path.getsize(current_input)/400000)) if _api.os.path.exists(current_input) else 10

                    cmd_dark = [
                        _api.FFMPEG, "-y",
                    ] + trim_pre + ["-i", current_input] + trim_post \
                      + self._map_av_args(remove_audio, a_map_sel) + timing_args + ["-map_metadata", "-1", "-map_chapters", "-1"] \
                      + self._bt709_color_args(current_input) + fps_args \
                      + self._av1_encoder_args(crf, preset_val, pix_fmt, video_tune)
                    if vf_arg:
                        cmd_dark += ["-vf", vf_arg]
                    cmd_dark += ["-threads", "0"] + step2_audio + dur_cap
                    if _api.os.path.splitext(attempted_out)[1].lower() == ".mp4":
                        cmd_dark += ["-movflags", "+faststart"]
                    cmd_dark += [attempted_out]

                    self.log.emit("🌑 Тёмные сцены: кодирование (AV1 10-бит, CRF)...")
                    # Адаптивное ETA по окну FPS (один проход CRF → has_second_pass=False).
                    _tf = self._estimate_total_frames(current_input, speed_factor, cmd_dark,
                                                       dur_override=(item.get('dur') if trim else None))
                    _calc = _api.RealETACalculator(_tf, pass_num=1, has_second_pass=False) if _tf > 0 else None
                    self.run_ffmpeg_capture(cmd_dark, est, cb, label="AV1 кодирование (тёмные сцены)", eta_calc=_calc, cancel_check=lambda: item["iid"] in self.removed_ids)

                else:
                    # Стандартный профиль
                    has_alpha = self._source_has_alpha(current_input)
                    pix_fmt = self._choose_pix_fmt(has_alpha)

                    if has_alpha and 'libvpx-vp9' in _api.detect_ffmpeg_encoders():
                        # libsvtav1 не поддерживает yuva420p → переключаемся на VP9+WebM.
                        # 10-бит альфа (yuva420p10le) в libvpx-vp9 — экспериментальный
                        # и «не широко поддерживаемый» формат (ffmpeg сам предупреждает
                        # и требует -strict experimental), поэтому здесь принудительно
                        # 8-бит yuva420p — единственный надёжно совместимый вариант для
                        # прозрачного WebM.
                        self.log.emit("Альфа-канал → выход: VP9 WebM (SVT-AV1 alpha не поддерживает)")
                        attempted_out = _api.os.path.splitext(attempted_out)[0] + ".webm"
                        out = attempted_out
                        cmd_step2 += ["-c:v", "libvpx-vp9",
                                      "-crf", str(crf), "-b:v", "0",
                                      "-pix_fmt", "yuva420p"]
                    elif has_alpha:
                        self.log.emit("⚠ libvpx-vp9 недоступен — альфа будет потеряна (SVT-AV1 alpha не поддерживает)")
                        cmd_step2 += self._bt709_color_args(current_input)
                        cmd_step2 += self._av1_encoder_args(crf, max(0, min(8, sv.get('pre', 8))), self._choose_pix_fmt(False), video_tune)
                    else:
                        cmd_step2 += self._bt709_color_args(current_input)
                        cmd_step2 += self._av1_encoder_args(crf, max(0, min(8, sv.get('pre', 8))), pix_fmt, video_tune)

                    if vf_arg: cmd_step2 += ["-vf", vf_arg]
                    cmd_step2 += ["-threads", "0"] + step2_audio + dur_cap
                    if _api.os.path.splitext(attempted_out)[1].lower() == ".mp4":
                        cmd_step2 += ["-movflags", "+faststart"]
                    cmd_step2 += [attempted_out]

                    est = max(1, int(_api.os.path.getsize(current_input)/400000)) if _api.os.path.exists(current_input) else 10
                    # Адаптивное ETA по скользящему окну FPS (одно-проходный CRF).
                    _tf = self._estimate_total_frames(current_input, speed_factor, cmd_step2,
                                                       dur_override=(item.get('dur') if trim else None))
                    _calc = _api.RealETACalculator(_tf, pass_num=1, has_second_pass=False) if _tf > 0 else None
                    self.run_ffmpeg_capture(cmd_step2, est, cb, label="Pass 2 (Video)", eta_calc=_calc, cancel_check=lambda: item["iid"] in self.removed_ids)

            else:
                if current_input != path:
                    inter_ext = _api.os.path.splitext(current_input)[1].lower()
                    if inter_ext == out_ext:
                        if _api.os.path.exists(out): _api.os.remove(out)
                        _api.shutil.move(current_input, out)  # step1 уже применил libopus, просто переносим
                    else:
                        # Контейнер промежуточного (.mkv) ≠ выходной → ремукс копией
                        # (видео уже в нужном кодеке, аудио — libopus из step1).
                        cmd_remux = [_api.FFMPEG, "-y", "-i", current_input,
                                     "-map", "0:V?", "-map", "0:a?",
                                     "-c", "copy", out]
                        self.run_ffmpeg_capture(
                            cmd_remux,
                            max(1, int(_api.os.path.getsize(current_input) / 1000000)),
                            cb, label=None, cancel_check=lambda: item["iid"] in self.removed_ids)
                else:
                    # Один прямой проход (видео-копия с аудиофильтрами или аудио-онли).
                    # Для видео-копии (single_pass_copy): passthrough сохраняет VFR-
                    # тайминг при `-c:v copy`, а aresample=async=1 убирает хвост
                    # loudnorm/опус-сдвиг — итог точно равен длине источника.
                    af_direct = self._af_arg(
                        audio_filters,
                        trim_tail=bool(is_video and normal_speed and audio_filters))
                    # Видео тут НЕ перекодируется (-c:v copy) — при заданном trim
                    # рез всё равно останется привязан к ближайшему ключевому
                    # кадру (как обычная copy-обрезка), кадровая точность здесь
                    # принципиально недостижима без реэнкода видео.
                    cmd_direct = [_api.FFMPEG, "-y"] + trim_pre + ["-i", path] + trim_post \
                                 + self._map_av_args(remove_audio, a_map_sel)
                    if is_video and keep_timing:
                        cmd_direct += ["-fps_mode", "passthrough"]
                    if remove_audio:
                        cmd_direct += ["-an"]
                    else:
                        cmd_direct += ["-af", af_direct]
                        cmd_direct += ["-c:a", audio_codec, "-b:a", audio_bitrate]
                    if is_video: cmd_direct += ["-c:v", "copy"]
                    else: cmd_direct += ["-vn"]
                    # Видео-КОПИЯ + аудиофильтры: loudnorm/opus добавляют «хвост»,
                    # из-за которого итог длиннее источника. dur_cap (-t = длине
                    # источника) обрезает лишний аудиохвост — см. определение выше.
                    cmd_direct += dur_cap
                    cmd_direct += [out]
                    self.run_ffmpeg_capture(cmd_direct, max(1, int(_api.os.path.getsize(path)/1000000)), cb, label=None, cancel_check=lambda: item["iid"] in self.removed_ids)

            if _api.os.path.exists(out):
                # «После» LUFS: в одно-проходном режиме Pass-1 (где раньше мерили)
                # пропущен — меряем по готовому файлу.
                if not remove_audio and (single_pass_video or single_pass_copy) and sa.get('norm'):
                    try:
                        after_norm = self.measure_loudness(out)
                        self.update_lufs_sig.emit(item['iid'], before_lufs, after_norm)
                    except Exception: pass
                size_new = _api.os.path.getsize(out)
                dur_new, br_str, _, a_br, a_codec = _api.get_media_info(out)
                vcodec_new = _api.get_video_codec_label(out) if is_video else None
                size_label = f"{vcodec_new} {_api.human_size(size_new)}" if vcodec_new else _api.human_size(size_new)
                self.update_item_sig.emit(item['iid'], size_label,
                                          _api.fmt_bitrate_with_codec(a_codec, a_br or br_str))
                self.update_dur_sig.emit(item['iid'], str(dur_new or 0.0))
                return out
            else:
                raise Exception("Output file не найден после ffmpeg (возможная ошибка записи).")

        except Exception as e:
            errstr = str(e)
            self.log.emit(f"Ошибка при обработке {_api.os.path.basename(path)}: {errstr}")
            try:
                if _api.os.path.exists(attempted_out) and _api.os.path.abspath(attempted_out) != _api.os.path.abspath(path):
                    try:
                        _api.os.remove(attempted_out)
                        self.log.emit(f"Удалён повреждённый/недозаписанный выход: {attempted_out}")
                    except Exception: pass
            except Exception: pass
            for t in temp_files:
                if _api.os.path.exists(t):
                    try:
                        _api.os.remove(t)
                        self.log.emit(f"Удалён временный файл: {t}")
                    except Exception: pass
            raise
        finally:
            for t in temp_files:
                if _api.os.path.exists(t):
                    try: _api.os.remove(t)
                    except Exception: pass

    # Команда кодирования и оценка даунскейла живут в avif_fit — тем же кодом
    # пользуется генератор аниме-паков, чтобы флаги libaom не разъезжались.
    _avif_encode_cmd = staticmethod(_api.avif_encode_cmd)

    _avif_downscale_side = staticmethod(_api.downscale_side)

    def _fmt_eta(self, fraction, start):
        """Строка ETA по доле выполнения (0..1) и времени старта."""
        fraction = min(1.0, max(0.0, fraction))
        elapsed = _api.time.time() - start
        if fraction >= 1.0:
            return "00:00:00"
        if elapsed < 1.0 or fraction <= 0.0:
            return "..."
        rem = max(0, elapsed * (1.0 / fraction - 1.0))
        rh = int(rem // 3600); rm = int((rem % 3600) // 60); rs = int(rem % 60)
        return f"{rh:02}:{rm:02}:{rs:02}"

    def _fmt_eta_rate(self, fraction, anchor_t, anchor_frac):
        """ETA по скорости в ОКНЕ [anchor_t, anchor_frac] → сейчас. В отличие от
        _fmt_eta, не привязана к общему старту: при двухпроходном кодировании
        Pass 1 (анализ) проходит почти мгновенно и доводит долю до ~50% за
        секунды; линейная оценка от старта принимала бы это за «всё быстро» и
        затем во время медленного Pass 2 ETA постоянно росла. Переякоривая окно
        на начало текущего прохода, оцениваем остаток по реальной скорости
        именно этого прохода. При anchor_frac=0 и anchor_t=start идентична
        _fmt_eta (обратная совместимость для однопроходных задач)."""
        fraction = min(1.0, max(0.0, fraction))
        if fraction >= 1.0:
            return "00:00:00"
        dt = _api.time.time() - anchor_t
        df = fraction - anchor_frac
        if dt < 1.0 or df <= 1e-6:
            return "..."
        rem = max(0, (1.0 - fraction) * dt / df)
        rh = int(rem // 3600); rm = int((rem % 3600) // 60); rs = int(rem % 60)
        return f"{rh:02}:{rm:02}:{rs:02}"

    def _guess_out_path(self, item, path):
        """Восстанавливает путь к выходному файлу (для кнопки «Открыть»).

        Страховка на случай, если process_media не вернула путь: основной путь —
        её собственный (см. _process_one)."""
        try:
            sv2 = self.settings.get('video', {})
            sa2 = self.settings.get('audio', {})
            crf2 = sv2.get('crf', 35); spd2 = sv2.get('speed', 100)
            ve2 = sv2.get('enabled', True)
            base2, ext2 = _api.os.path.splitext(path)
            out_dir2 = self._out_dir_for(path)
            vcodec2 = _api.get_video_codec(path)
            # Аудио-режим Монтажа гасит видео так же, как в process_media —
            # иначе угадка ждала бы .mp4 там, где на диске .opus.
            is_vid2 = (vcodec2 is not None) and not bool(item.get('audio_only'))
            out_ext2 = ".mp4" if is_vid2 else ".opus"
            sfx2 = ""
            if is_vid2 and ve2: sfx2 += f"_crf{crf2}_speed{spd2}"
            if sa2.get('norm'): sfx2 += "_norm"
            if sa2.get('fade'): sfx2 += "_fade"
            out_name2 = self._sanitize_name(_api.os.path.basename(base2))
            guessed = _api.os.path.join(out_dir2, out_name2 + sfx2 + out_ext2)
            if _api.os.path.exists(guessed): item['out_path'] = guessed
        except Exception: pass

    def _overwrite_source_if_needed(self, item, out_path):
        """Если включено «Перезаписывать исходник» — удаляет оригинальный файл,
        оставляя только сжатую версию. При совпадении путей (тот же формат)
        файл уже перезаписан на месте — удалять нечего."""
        av = self.settings.get('avif', {})
        if not av.get('overwrite_src'):
            return
        src = item.get('path')
        if not (out_path and src):
            return
        try:
            if (_api.os.path.exists(out_path) and _api.os.path.exists(src)
                    and _api.os.path.abspath(out_path) != _api.os.path.abspath(src)):
                _api.os.remove(src)
                self.log.emit(f"Исходник удалён (перезапись): {_api.os.path.basename(src)}")
        except Exception as e:
            self.log.emit(f"Не удалось удалить исходник: {e}")

    def _total_now(self) -> int:
        """Текущее известное число файлов: уже завершённые + ещё не
        завершённые в очереди. self.queue — живой список MediaTab.items,
        поэтому файлы, доброшенные во время обработки, автоматически
        увеличивают знаменатель прогресса."""
        with self._prog_lock:
            done = self._done_count
        pending = sum(1 for it in list(self.queue) if not it.get('is_done', False))
        return max(1, done + pending)

    def _process_item(self, item, smooth, start, weight=1):
        """Обрабатывает один элемент очереди.
        smooth=True — глобальный прогресс плавно отражает прогресс файла
        (видео/аудио идут по одному). smooth=False — прогресс по факту
        завершения (изображения идут параллельно через QThreadPool).
        weight — вклад в счётчик «занятых потоков ЦП»: видео = все ядра
        (один ffmpeg/SVT-AV1 грузит весь ЦП), изображение = 1."""
        if self.stop_flag:
            return
        iid = item['iid']; path = item['path']
        self.status.emit(iid, "Обработка.", "proc")
        self._inc_active(weight)
        max_frac_seen = [0.0]
        last_label = [None]
        # Окно для ETA по скорости текущего прохода: [время, доля]. По умолчанию
        # совпадает с общим стартом (тогда оценка идентична старой _fmt_eta), но
        # при смене прохода (Pass 1 → Pass 2) переякоривается на текущий момент,
        # чтобы быстрый Pass 1 не занижал оценку и ETA во время Pass 2 не «росла».
        eta_anchor = [start, 0.0]

        def item_prog(pct, pass_label=None, eta_sec=None):
            try:
                if not smooth:
                    # Параллельная обработка изображений: НЕ шлём частые % -сигналы
                    # из множества потоков, но статус («Конвертация картинки N/X»)
                    # обновляем при смене подписи — это редкое событие (раз в проход),
                    # потоки/сигналы Qt безопасны.
                    if pass_label and pass_label != last_label[0]:
                        last_label[0] = pass_label
                        self.status.emit(iid, pass_label, "proc")
                    return
                if pass_label and "Pass 1" in pass_label:
                    display_pct = int(pct * 0.5)
                elif pass_label and "Pass 2" in pass_label:
                    display_pct = int(50 + pct * 0.5)
                else:
                    display_pct = pct
                self.progress.emit(iid, display_pct)
                label_changed = bool(pass_label) and pass_label != last_label[0]
                if label_changed and pct < 100:
                    last_label[0] = pass_label
                    self.status.emit(iid, pass_label, "proc")
                with self._prog_lock:
                    base = self._done_count
                fraction = (base + display_pct / 100.0) / self._total_now()
                fraction = max(min(1.0, fraction), max_frac_seen[0])
                max_frac_seen[0] = fraction
                # Новый проход → переякориваем окно ETA на «здесь и сейчас».
                if label_changed:
                    eta_anchor[0] = _api.time.time()
                    eta_anchor[1] = fraction
                gl_pct = int(min(100, fraction * 100))
                label = pass_label if pass_label else "Processing"
                # Если активный шаг дал реальное ETA (адаптивный калькулятор по
                # кадрам/сложности) — показываем его; иначе старая оценка по доле
                # глобального прогресса (для шагов без покадрового парсинга).
                if eta_sec is not None:
                    eta_str = _api.RealETACalculator.fmt(eta_sec)
                else:
                    eta_str = self._fmt_eta_rate(fraction, eta_anchor[0], eta_anchor[1])
                self.global_progress.emit(gl_pct, f"{label} ETA: {eta_str}")
            except Exception:
                pass

        try:
            out_path = None
            if item.get('type') == 'IMG':
                out_path = self.process_avif(item, item_prog)
                self._overwrite_source_if_needed(item, out_path)
            else:
                # Путь берём У САМОЙ process_media (она его и собрала), а не
                # угадываем по настройкам: угадывание не знало ни про аудио-режим
                # («(Аудио) Перекодировать настройками «Обработки»» даёт .opus, а
                # угадка ждала .mp4 с crf-суффиксом), ни про смену контейнера под
                # альфу (.webm). Промах = пустой out_path, и Монтаж честно
                # ругался «Обработка не создала результат», хотя файл лежал рядом.
                out_path = self.process_media(item, item_prog)
            item['is_done'] = True
            if out_path:
                item['out_path'] = out_path
            else:
                self._guess_out_path(item, path)
            self.status.emit(iid, "Готово", "done")
            self.progress.emit(iid, 100)
        except Exception as e:
            tb = str(e)
            if "StoppedByUser" in tb:
                self.log.emit(f"Остановка {_api.os.path.basename(path)} выполнена.")
                self.status.emit(iid, "Остановлено", "err")
            else:
                self.log.emit(f"Ошибка {_api.os.path.basename(path)}: {tb}")
                self.status.emit(iid, "Ошибка", "err")
            item['is_done'] = True
        finally:
            self._dec_active(weight)
            with self._prog_lock:
                self._done_count += 1
                done = self._done_count
            total = self._total_now()
            frac = done / total
            self.global_progress.emit(int(min(100, frac * 100)),
                                      f"Готово {done}/{total} ETA: {self._fmt_eta(frac, start)}")

    def run(self):
        start = _api.time.time()
        self._done_count = 0
        self._prog_lock = _api.threading.Lock()
        self._processed_ids = set()   # iid'ы, уже отправленные в работу за этот запуск
        self._logged_cpu_msg = False

        cpu = max(1, _api.cpu_thread_count())

        # Обрабатываем очередь по схеме «продюсер-потребитель»: постоянно
        # заглядываем в живой список self.queue, поэтому файлы, доброшенные во
        # время обработки, тут же уходят в работу. Картинки кодируются параллельно
        # в ОБЩЕМ пуле (cpu потоков) и НЕ блокируют диспетчеризацию через
        # waitForDone — доброшенные картинки сразу занимают свободные потоки
        # (просьба пользователя), не дожидаясь конца текущей пачки.
        while not self.stop_flag:
            pending = [it for it in list(self.queue)
                       if not it.get('is_done', False)
                       and it.get('iid') not in self._processed_ids]
            images = [it for it in pending if it.get('type') == 'IMG']
            others = [it for it in pending if it.get('type') != 'IMG']

            # Видео/аудио идут по одному файлу, но кодировщик SVT-AV1 сам нагружает
            # ВСЕ логические ядра ЦП → счётчик показывает занятые потоки ЦП. Перед
            # видео дожидаемся ранее запущенных картинок, иначе они дрались бы за ЦП.
            if others:
                if (self._img_pool is not None
                        and self._img_pool.activeThreadCount() > 0):
                    self._img_pool.waitForDone()
                self._max_threads = cpu
                if not self._logged_cpu_msg:
                    self.log.emit("Кодирование видео/аудио: SVT-AV1.")
                    self._logged_cpu_msg = True
                for it in others:
                    if self.stop_flag:
                        break
                    self._processed_ids.add(it.get('iid'))
                    self._process_item(it, True, start, weight=cpu)
                continue

            if images:
                # Одиночный кадр CPU не насыщает → шлём картинки в общий пул на cpu
                # потоков. Знаменатель счётчика — всегда ВСЕ логические потоки ЦП
                # машины (cpu), чтобы «занято/всего» не скакало по ходу обработки.
                if self._img_pool is None:
                    self._img_pool = _api.QThreadPool()
                    self._img_pool.setMaxThreadCount(cpu)
                    if cpu > 1:
                        self.log.emit(
                            f"Параллельная обработка изображений: до {cpu} потоков")
                self._max_threads = cpu
                for itm in images:
                    if self.stop_flag:
                        break
                    self._processed_ids.add(itm.get('iid'))
                    self._img_pool.start(_api._ImgRunnable(self, itm, start))
                # НЕ ждём waitForDone — короткая пауза, чтобы подхватить доброшенные
                # файлы и занять ими свободные потоки, не крутя цикл вхолостую.
                _api.time.sleep(0.08)
                continue

            # Новых задач нет. Если картинки ещё кодируются — ждём и снова
            # перечитываем очередь (вдруг доросли новые); иначе очередь пуста.
            if (self._img_pool is not None
                    and self._img_pool.activeThreadCount() > 0):
                _api.time.sleep(0.1)
                continue
            break

        if self._img_pool is not None:
            self._img_pool.waitForDone()

        self.active_threads.emit(0, 0)
        self.finished_all.emit()
        self.global_progress.emit(100, "Готово")


ProcessWorker.__module__ = _api.__name__
_api.ProcessWorker = ProcessWorker
