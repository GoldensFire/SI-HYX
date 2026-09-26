# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""EditTab: _scrub_audio_engine. Public namespace: edit_tab."""
import edit_tab as _api


def _scrub_audio_engine(self):
    """Лениво поднимает фоновый декодер PCM вокруг плейхеда."""
    eng = getattr(self, "_audio_scrub", None)
    if eng is None:
        eng = _api.AudioScrubber(self)
        eng.ready.connect(self._on_scrub_audio_window)
        eng.start()
        self._audio_scrub = eng
    return eng

def _scrub_audio_source(self):
    """(файл, поток) для скраб-звука: внешняя озвучка, если выбрана, иначе
        ОРИГИНАЛ (не прокси: у прокси звук пережат в AAC, а дорожка может быть
        и не одна). Поток — абсолютный индекс выбранной дорожки, чтобы звук шага
        совпадал с тем, что играет плеер."""
    if getattr(self, "audio_disabled", False):
        return (None, "a:0")          # пункт «Нет»: шаг кадра без звука
    ext = getattr(self, "selected_audio_ext_path", None)
    if ext:
        return (str(ext), "a:0")
    src = getattr(self, "actual_source_file", None)
    if not src:
        return (None, "a:0")
    idx = getattr(self, "selected_audio_abs_index", None)
    return (str(src), str(int(idx)) if idx is not None else "a:0")

def _sync_scrub_audio_source(self):
    """Держит источник скраб-звука в согласии с выбранной дорожкой."""
    src, stream = self._scrub_audio_source()
    if not src:
        return None
    eng = self._scrub_audio_engine()
    if eng.source() != (src, stream):
        fmt = self._scrub_sink_format()
        if fmt is not None:
            eng.configure(fmt.sampleRate(), fmt.channelCount(),
                          4 if fmt.sampleFormat() == _api.QAudioFormat.SampleFormat.Float else 2)
        eng.set_source(src, stream)
    return eng

def _scrub_sink_format(self):
    """Формат вывода для скраб-звука (создаётся один раз под устройство)."""
    fmt = getattr(self, "_scrub_fmt", None)
    if fmt is not None:
        return fmt
    if _api.QAudioFormat is None or _api.QMediaDevices is None:
        return None
    try:
        dev = _api.QMediaDevices.defaultAudioOutput()
        if dev is None or dev.isNull():
            return None
        fmt = _api.QAudioFormat()
        fmt.setSampleRate(48000)
        fmt.setChannelCount(2)
        fmt.setSampleFormat(_api.QAudioFormat.SampleFormat.Int16)
        if not dev.isFormatSupported(fmt):
            # Устройство не тянет 48 кГц/16 бит — берём его собственный
            # формат и просим ffmpeg отдавать PCM ровно в нём.
            fmt = dev.preferredFormat()
        self._scrub_fmt = fmt
        return fmt
    except Exception:
        return None

def _scrub_sink(self):
    """QAudioSink для блипов (push-режим). Открывается один раз и живёт:
        pause/play у QMediaPlayer заново открывали бы аудиоустройство, а это на
        Windows заметная задержка — здесь же запись в устройство слышна через
        1–9 мс (замерено)."""
    sink = getattr(self, "_scrub_sink_obj", None)
    if sink is not None:
        return sink
    if _api.QAudioSink is None:
        return None
    fmt = self._scrub_sink_format()
    if fmt is None:
        return None
    try:
        dev = _api.QMediaDevices.defaultAudioOutput()
        sink = _api.QAudioSink(dev, fmt, self)
        # Буфер с запасом на пару срезов: сама задержка звука от него не
        # зависит (устройство играет то, что в очереди, а очередь мы держим
        # короткой — см. _play_scrub_slice), зато длинный срез влезает
        # целиком и не режется.
        bytes_per_s = fmt.sampleRate() * fmt.channelCount() * fmt.bytesPerSample()
        sink.setBufferSize(max(4096, int(bytes_per_s * 0.25)))
        sink.setVolume(self._scrub_volume())
        self._scrub_sink_obj = sink
        # start() стоит ~45 мс (поднимается сеанс WASAPI) — поэтому делаем
        # его РОВНО ОДИН РАЗ, при первом обращении, а дальше только пишем в
        # устройство (запись — 0 мс). Именно поэтому здесь нет ни stop(), ни
        # reset() на каждый шаг: они убивают QIODevice, и следующий шаг
        # платил бы за start() те же 45 мс задержки перед звуком.
        self._scrub_sink_io = sink.start()
        return sink
    except Exception:
        self._scrub_sink_obj = None
        self._scrub_sink_io = None
        return None

def _scrub_volume(self):
    try:
        return max(0.0, min(1.0, self.vol_slider.value() / 100.0))
    except Exception:
        return 1.0

def _scrub_blip_seconds(self):
    """Длина блипа: ровно кадр, но в разумных пределах слышимости."""
    fps = float(self.fps or 0.0)
    one = (1.0 / fps) if fps > 0 else self._SCRUB_BLIP_MIN_S
    return max(self._SCRUB_BLIP_MIN_S, min(self._SCRUB_BLIP_MAX_S, one))

def _scrub_audio_time_s(self):
    """Время, с которого обязан звучать шаг, — НАЧАЛО показанного кадра
        (плееру мы отдаём середину кадра, но слышно должно быть то же, что
        видно). Берём его из НОМЕРА кадра, а не из округлённых миллисекунд."""
    if self._grid.valid and self._frame_idx is not None:
        return self._grid.start_of(self._frame_idx)
    ms = getattr(self, "_scrub_audio_ms", None)
    if ms is None:
        ms = getattr(self, "_scrub_target", None)
    if ms is None:
        try:
            ms = self.player.position()
        except Exception:
            return None
    return max(0.0, ms / 1000.0)

def _scrub_audio_blip(self, painted=True):
    """Короткий звук нового кадра: точный PCM-срез с pts кадра в устройство.

        В overlay-режиме (QVideoWidget) кадр доставляется коротким play()
        основного плеера, который несёт и звук, — там мы молчим. Исключение —
        выбранная внешняя озвучка: звук видео тогда заглушён, и слышно только
        то, что сыграем здесь."""
    if not getattr(self, "_scrub_audio_enabled", True):
        return
    if not painted and not getattr(self, "_ext_audio_active", False):
        return
    t_s = self._scrub_audio_time_s()
    if t_s is None:
        return
    eng = self._sync_scrub_audio_source()
    if eng is None:
        return
    eng.request(t_s)                    # окно вокруг плейхеда — заранее
    data = eng.slice_at(t_s, self._scrub_blip_seconds())
    if data:
        self._play_scrub_slice(data)
        self._scrub_wait = None
        return
    # Окна ещё нет (первый шаг после загрузки/перемотки) — доиграем, как
    # только фоновый декодер его принесёт (см. _on_scrub_audio_window).
    # Раньше в этом месте звука просто не было — жалоба «при AV1 звук на
    # шаге появляется не всегда».
    self._scrub_wait = (t_s, _api.time.monotonic())

def _on_scrub_audio_window(self):
    """Окно PCM доехало: если шаг был только что и с тех пор никуда не
        ушли — играем его звук с опозданием, а не молчим."""
    pending = getattr(self, "_scrub_wait", None)
    self._scrub_wait = None
    if not pending or not getattr(self, "_scrub_audio_enabled", True):
        return
    t_s, at = pending
    if _api.time.monotonic() - at > 0.4:
        return                          # поздно, звук был бы «из прошлого»
    cur = self._scrub_audio_time_s()
    if cur is None or abs(cur - t_s) > 0.001:
        return                          # плейхед уже ушёл — играть нечего
    eng = getattr(self, "_audio_scrub", None)
    data = eng.slice_at(t_s, self._scrub_blip_seconds()) if eng else None
    if data:
        self._play_scrub_slice(data)

def _play_scrub_slice(self, data):
    """Пишет срез в аудиоустройство, НЕ давая очереди расти.

        Очередь длиннее одного среза — это и есть «звук уехал вперёд»: при
        удержании клавиши шаги идут чаще, чем звук успевает проигрываться, и
        хвост копится, а следующий шаг слышится уже с опозданием. Поэтому
        пишем ровно столько, сколько успело проиграться: одиночный шаг звучит
        целиком, а удержание даёт непрерывную перемотку по звуку, отстающую от
        картинки не больше чем на срез."""
    sink = self._scrub_sink()
    io = getattr(self, "_scrub_sink_io", None)
    if sink is None or io is None:
        return
    try:
        sink.setVolume(self._scrub_volume())
        free = int(sink.bytesFree())
        pending = max(0, int(sink.bufferSize()) - free)
        budget = min(free, len(data) - pending)
        if budget <= 0:
            return              # предыдущий срез ещё звучит — не наслаиваем
        io.write(data[:budget])
    except Exception:
        # Устройство могло пропасть (наушники выдернули) — пересоберём.
        self._release_scrub_sink()

def _release_scrub_sink(self):
    sink = getattr(self, "_scrub_sink_obj", None)
    self._scrub_sink_obj = None
    self._scrub_sink_io = None
    self._scrub_fmt = None
    if sink is not None:
        try:
            sink.stop()
        except Exception:
            pass
        try:
            sink.deleteLater()
        except Exception:
            pass

def _end_scrub(self):
    self.player.pause()
    # play() ушёл вперёд на ~2 кадра — возвращаем плеер РОВНО на целевой кадр,
    # иначе шаг назад визуально «отскакивал» вперёд (баг).
    tgt = getattr(self, "_scrub_target", None)
    if tgt is not None:
        self.player.setPosition(int(tgt))
        self._ext_audio_seek(int(tgt))
    # Сбрасываем флаг после того, как событие паузы будет обработано.
    _api.QTimer.singleShot(40, lambda: setattr(self, "_scrubbing", False))

# ── Export / Cut ──────────────────────────────────────────────────────
def _available_encoders(self):
    """Строка `ffmpeg -encoders` (детект один раз, кэшируется). Пустая строка
        трактуется как «всё доступно» (не смогли опросить сборку)."""
    cache = getattr(self, "_encoders_str", None)
    if cache is not None:
        return cache
    encoders = ""
    try:
        p = _api.subprocess.run([_api.FFMPEG, "-hide_banner", "-encoders"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", creationflags=_api.CREATE_NO_WINDOW)
        encoders = p.stdout or ""
    except Exception:
        encoders = ""
    self._encoders_str = encoders
    return encoders

def _gpu_encoder_args(self, encoders, hardsub=False):
    """Первый доступный аппаратный (GPU) H.264-кодировщик, иначе None.
        При hardsub (вшивание субтитров) поджимаем качество, чтобы края текста
        не мылились."""
    q = 18 if hardsub else 20
    if "h264_nvenc" in encoders:
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-cq", str(q)]
    if "h264_qsv" in encoders:
        return ["-c:v", "h264_qsv", "-global_quality", str(q)]
    if "h264_amf" in encoders:
        return ["-c:v", "h264_amf", "-quality", "balanced", "-rc", "cqp",
                "-qp_i", str(q), "-qp_p", str(q)]
    if "h264_mf" in encoders:
        qual = 80 if hardsub else 70
        return ["-c:v", "h264_mf", "-rate_control", "quality", "-quality", str(qual)]
    return None
