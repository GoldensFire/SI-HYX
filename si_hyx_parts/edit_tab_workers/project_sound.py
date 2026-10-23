# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""ProjectSoundEngine — звук просмотра проекта «Монтажа» своим трактом.
Public namespace: edit_tab_workers.

Зачем. Просмотр проекта играет картинку одним QMediaPlayer, кусок за куском,
и на стыке кусков плеер перематывается на ходу. Звук у QtMultimedia после
такой перемотки замерен записью звука процесса (HDR HEVC + E-AC-3 5.1, стык
двух кусков одного файла): конец куска обрывается на 74 мс раньше, 210 мс
тишины, начало следующего — с пропуском 37 мс. Плюс аудиочасы плеера после
перемотки запускаются позже картинки, и видео до конца куска отставало на
~130 мс со скачком 145–166 мс через 0.8–1.1 с. Одним плеером это не лечится.

Поэтому звук просмотра — свой: фоновый ffmpeg рендерит звук проекта ТЕМ ЖЕ
графом, что и сборка (montage_project.build_source по выдержке проекта —
громкость клипов, дорожки, сведение), окнами по _WINDOW_S, а отдельный поток
подаёт PCM в QAudioSink. Стыки внутри графа посэмпловые — паузы нет по
построению. Плеер в просмотре проекта играет только картинку (без аудиовыхода
его часы идут по стене: после перемотки на ходу первый кадр через ~85 мс, и
дальше ровно по стене, без отставания).

QAudioSink живёт в своём потоке: подкачка из главного потока зависела бы от
его занятости, а WASAPI будит поток-владелец на каждый период (~200 раз в
секунду). Очередь сбрасывается reset()-ом (DiscardRingbuffer): stop() в Qt
6.10.0–6.10.1 не завершает свой рабочий поток. Громкость Qt применяет при
выборке из кольцевого буфера, поэтому setVolume(0) глушит очередь почти
мгновенно — так и ставим на паузу.

Устройство может пропасть на ходу (подключили наушники — сменился выход по
умолчанию, драйвер сбросил поток): Qt сам гасит поток и удаляет QIODevice,
который вернул start(). Тогда звук этого места пропал, но тракт жив —
следующий prepare открывает устройство заново (_SinkWorker._fail)."""
import edit_tab_workers as _api

_WINDOW_S = 30.0        # длина окна звука, которое рендерит один запуск ffmpeg
_FIRST_WINDOW_S = 1.0   # первое окно на паузе — коротким: ffmpeg не держит файл
_AHEAD_S = 3.0          # сколько готового PCM держим впереди устройства
_RING_S = 0.5           # кольцевой буфер QAudioSink
_PREFILL_S = 0.4        # столько звука лежит в устройстве до старта
_FEED_MS = 10           # такт подкачки
_HOST_LATENCY_S = 0.015  # буфер WASAPI поверх кольца (поправка часов)
_INLINE_GRAPH_MAX = 6000  # длиннее — граф в файл (-/filter_complex)


class _Fifo:
    """Готовый PCM между потоком ffmpeg и потоком устройства."""

    def __init__(self):
        self.cond = _api.threading.Condition()
        self.chunks = _api.collections.deque()
        self.size = 0
        self.gen = 0
        self.done = False               # рендер дошёл до конца проекта

    def reset(self, gen):
        with self.cond:
            self.chunks.clear()
            self.size = 0
            self.gen = gen
            self.done = False
            self.cond.notify_all()

    def push(self, data, gen, limit):
        """Кладёт PCM, ожидая места (не больше limit байт впереди). False —
        очередь уже другого поколения (рендер устарел)."""
        with self.cond:
            while self.gen == gen and self.size >= limit:
                self.cond.wait(0.2)
            if self.gen != gen:
                return False
            self.chunks.append(data)
            self.size += len(data)
            return True

    def finish(self, gen):
        with self.cond:
            if self.gen == gen:
                self.done = True

    def pop(self, n):
        out = []
        with self.cond:
            while n > 0 and self.chunks:
                head = self.chunks[0]
                if len(head) <= n:
                    out.append(self.chunks.popleft())
                    n -= len(head)
                else:
                    out.append(head[:n])
                    self.chunks[0] = head[n:]
                    n = 0
            got = sum(len(c) for c in out)
            self.size -= got
            if got:
                self.cond.notify_all()
            exhausted = self.done and not self.chunks
        return b"".join(out), exhausted


class _Clock:
    """Часы звука: что записано в устройство и что из этого ещё в очереди."""

    def __init__(self):
        self.lock = _api.threading.Lock()
        self.gen = -1
        self.written = 0                # кадров PCM записано с начала поколения
        self.queued = 0                 # кадров ещё в кольцевом буфере
        self.at = 0.0                   # monotonic снимка
        self.playing = False

    def set(self, gen, written, queued, playing):
        with self.lock:
            self.gen, self.written, self.queued = gen, written, queued
            self.at = _api.time.monotonic()
            self.playing = playing

    def get(self):
        with self.lock:
            return self.gen, self.written, self.queued, self.at, self.playing


class _Renderer(_api.threading.Thread):
    """Звук проекта от кадра PCM n0 до n_end окнами ffmpeg → в _Fifo."""

    def __init__(self, project, n0, n_end, first_window_s, fmt, fifo, gen):
        super().__init__(daemon=True)
        self.project = project
        self.n0, self.n_end = int(n0), int(n_end)
        self.first_window_s = float(first_window_s)
        self.rate, self.channels, self.pcm = fmt
        self.bpf = self.channels * (4 if self.pcm == "f32le" else 2)
        self.fifo = fifo
        self.gen = gen
        self.limit = int(_AHEAD_S * self.rate) * self.bpf
        self.stopped = False
        self.proc = None
        self.error = ""

    def stop(self):
        self.stopped = True
        p = self.proc
        if p is not None:
            try:
                p.kill()
            except Exception:
                pass

    def run(self):
        n = self.n0
        win = self.first_window_s
        while n < self.n_end and not self.stopped:
            m = min(self.n_end, n + max(1, int(round(win * self.rate))))
            if not self._render(n, m):
                return
            n = m
            win = _WINDOW_S
        if not self.stopped:
            self.fifo.finish(self.gen)

    def _push(self, data):
        return not self.stopped and self.fifo.push(data, self.gen, self.limit)

    def _silence(self, frames):
        chunk = bytes(self.bpf * min(frames, self.rate // 4))
        while frames > 0:
            k = min(frames, len(chunk) // self.bpf)
            if not self._push(chunk[:k * self.bpf]):
                return False
            frames -= k
        return True

    def _render(self, a, b):
        """Окно [a, b) кадров PCM. Ровно b - a кадров: недостающее — тишиной,
        лишнее отрезаем (часы и стык следующего окна держатся на счёте)."""
        want = b - a
        rate = float(self.rate)
        src = _api.montage_project.build_source(
            self.project.excerpt(a / rate, b / rate), video=False, audio=True)
        if src is None or not src.audio:
            return self._silence(want)
        graph_file = None
        cmd = [_api.FFMPEG, "-nostdin", "-hide_banner", "-loglevel", "error"]
        cmd += src.input_args()
        if len(src.graph) > _INLINE_GRAPH_MAX:
            try:
                tf = _api.tempfile.NamedTemporaryFile(
                    "w", encoding="utf-8", delete=False, suffix=".txt", prefix="sihyx_snd_")
                tf.write(src.graph)
                tf.close()
                graph_file = tf.name
                cmd += ["-/filter_complex", graph_file]
            except Exception:
                cmd += ["-filter_complex", src.graph]
        else:
            cmd += ["-filter_complex", src.graph]
        cmd += ["-map", "[aout]", "-f", self.pcm, "-ar", str(self.rate),
                "-ac", str(self.channels), "-"]
        got = 0
        try:
            try:
                proc = _api.subprocess.Popen(cmd, stdout=_api.subprocess.PIPE,
                                             stderr=_api.subprocess.DEVNULL,
                                             creationflags=_api.CREATE_NO_WINDOW)
            except Exception as e:
                self.error = f"ffmpeg не запустился: {e}"
                return self._silence(want)
            self.proc = proc
            need = want * self.bpf
            step = max(self.bpf, (self.rate // 20) * self.bpf)     # ~50 мс за чтение
            tail = b""
            try:
                while got < need and not self.stopped:
                    data = proc.stdout.read(min(step, need - got))
                    if not data:
                        break
                    data = tail + data
                    whole = len(data) - len(data) % self.bpf
                    tail = data[whole:]
                    if whole and not self._push(data[:whole]):
                        return False
                    got += whole
            finally:
                try:
                    proc.kill()
                except Exception:
                    pass
                try:
                    proc.stdout.close()
                except Exception:
                    pass
                self.proc = None
            if self.stopped:
                return False
            if got == 0:
                self.error = "ffmpeg не отдал звук"
        finally:
            if graph_file:
                try:
                    _api.os.remove(graph_file)
                except OSError:
                    pass
        return self._silence(want - got // self.bpf)


class _SinkWorker(_api.QObject):
    """QAudioSink и подкачка в него — в своём потоке."""

    primed = _api.pyqtSignal(int)        # поколение: предзаполнение в устройстве
    broken = _api.pyqtSignal(int, str)   # поколение, причина: устройство отказало

    def __init__(self, fmt, fifo, clock):
        super().__init__()
        self._fmt = fmt
        self._fifo = fifo
        self._clock = clock
        self._rate = fmt.sampleRate()
        self._bpf = fmt.bytesPerFrame()
        self._prefill = int(_PREFILL_S * self._rate) * self._bpf
        self._sink = None
        self._dev_id = b""
        self._io = None
        self._timer = None
        self._gen = -1
        self._state = "idle"            # idle | prefill | primed | play
        self._play_pending = False      # play() пришёл до конца предзаполнения
        self._written = 0
        self._volume = 1.0

    @_api.pyqtSlot()
    def init(self):
        self._timer = _api.QTimer(self)
        self._timer.setTimerType(_api.Qt.TimerType.PreciseTimer)
        self._timer.setInterval(_FEED_MS)
        self._timer.timeout.connect(self._feed)

    def _open(self):
        dev = _api.QMediaDevices.defaultAudioOutput()
        if dev is None or dev.isNull():
            raise RuntimeError("нет устройства вывода звука")
        if self._sink is not None and bytes(dev.id()) != self._dev_id:
            # Сменился выход по умолчанию (наушники, монитор) — новое устройство.
            old, self._sink = self._sink, None
            try:
                old.reset()
            except Exception:
                pass
            old.deleteLater()
        if self._sink is None:
            sink = _api.QAudioSink(dev, self._fmt, self)
            sink.setBufferSize(int(_RING_S * self._rate) * self._bpf)
            self._sink = sink
            self._dev_id = bytes(dev.id())
        else:
            # Очередь прошлого места — прочь (reset, а не stop: см. докстроку).
            self._sink.reset()
        self._io = self._sink.start()
        if self._io is None:
            raise RuntimeError("устройство вывода звука не открылось")
        self._sink.suspend()

    @_api.pyqtSlot(int)
    def prepare(self, gen):
        self._gen = gen
        self._written = 0
        self._play_pending = False
        try:
            self._open()
        except Exception as e:
            self._fail(str(e))
            return
        self._state = "prefill"
        self._publish()
        self._timer.start()
        self._feed()

    @_api.pyqtSlot(int)
    def play(self, gen):
        if gen != self._gen or self._sink is None or self._state == "idle":
            return
        if self._state == "prefill":
            # Звук пойдёт, как только устройство наполнится (картинку вкладка
            # пустит по тому же сигналу primed).
            self._play_pending = True
            return
        self._start_output()

    def _start_output(self):
        self._play_pending = False
        self._state = "play"
        try:
            self._sink.setVolume(self._volume)
            self._sink.resume()
        except Exception as e:
            self._fail(str(e))
            return
        self._timer.start()
        self._feed()

    def _fail(self, msg):
        """Устройство отказало: подкачка встаёт, QAudioSink — прочь, вкладке —
        один сигнал. Следующий prepare откроет устройство заново.

        Раньше подкачка продолжала писать в удалённый QIODevice каждые 10 мс
        (в журнале — сотни одинаковых строк в секунду), а вкладка от первой же
        ошибки отказывалась от тракта до перезапуска программы: просмотр
        проекта шёл звуком плеера с его задержкой старта и хвостом после паузы."""
        self._state = "idle"
        self._play_pending = False
        if self._timer is not None:
            self._timer.stop()
        sink, self._sink, self._io, self._dev_id = self._sink, None, None, b""
        if sink is not None:
            try:
                sink.reset()
            except Exception:
                pass
            sink.deleteLater()
        self._publish()
        self.broken.emit(self._gen, msg or "ошибка устройства звука")

    @_api.pyqtSlot()
    def pause(self):
        self._state = "idle"
        self._play_pending = False
        if self._timer is not None:
            self._timer.stop()
        if self._sink is not None:
            try:
                # Громкость Qt применяет при выборке из кольца — тишина сразу,
                # а не через ~0.5 с очереди. Очередь сбросит следующий prepare.
                self._sink.setVolume(0.0)
                self._sink.suspend()
            except Exception:
                pass
        self._publish()

    @_api.pyqtSlot(float)
    def set_volume(self, v):
        self._volume = max(0.0, min(1.0, float(v)))
        if self._sink is not None and self._state == "play":
            try:
                self._sink.setVolume(self._volume)
            except Exception:
                pass

    @_api.pyqtSlot()
    def shutdown(self):
        if self._timer is not None:
            self._timer.stop()
        sink, self._sink, self._io = self._sink, None, None
        if sink is not None:
            try:
                sink.reset()            # не stop(): в Qt 6.10.1 его поток не завершается
            except Exception:
                pass
            sink.deleteLater()
        _api.QThread.currentThread().quit()

    def _queued_frames(self):
        try:
            return max(0, int(self._sink.bufferSize()) - int(self._sink.bytesFree())) // self._bpf
        except Exception:
            return 0

    def _publish(self):
        queued = self._queued_frames() if self._sink is not None else 0
        self._clock.set(self._gen, self._written, queued, self._state == "play")

    def _feed(self):
        if self._sink is None or self._io is None or self._state in ("idle", "primed"):
            return
        if self._fifo.gen != self._gen:
            return                      # очередь уже нового места, а prepare ещё в пути
        try:
            if _api.QAudio is not None and (
                    self._sink.error() not in (_api.QAudio.Error.NoError,
                                               _api.QAudio.Error.UnderrunError)
                    or self._sink.state() == _api.QAudio.State.StoppedState):
                # Устройство пропало (выдернули наушники, сменился выход по
                # умолчанию): Qt остановил поток сам — см. _fail.
                self._fail("устройство вывода звука пропало")
                return
            free = int(self._sink.bytesFree())
        except Exception:
            return
        free -= free % self._bpf
        if self._state == "prefill":
            free = min(free, self._prefill - self._written * self._bpf)
        exhausted = False
        if free > 0:
            data, exhausted = self._fifo.pop(free)
            if data:
                try:
                    self._io.write(data)
                except Exception as e:
                    self._fail(str(e))
                    return
                self._written += len(data) // self._bpf
        if self._state == "prefill" and (
                self._written * self._bpf >= self._prefill or exhausted):
            self._state = "primed"
            if self._play_pending:
                self._start_output()
            self.primed.emit(self._gen)
        self._publish()


class ProjectSoundEngine(_api.QObject):
    """Звук просмотра проекта (см. докстроку модуля). Вызовы — из главного
    потока; устройство и рендер работают в своих потоках."""

    ready = _api.pyqtSignal()            # предзаполнение готово — старт без задержки
    failed = _api.pyqtSignal(str)        # устройство отказало (prepare откроет заново)

    _sig_prepare = _api.pyqtSignal(int)
    _sig_play = _api.pyqtSignal(int)
    _sig_pause = _api.pyqtSignal()
    _sig_volume = _api.pyqtSignal(float)
    _sig_shutdown = _api.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._qfmt = self._pick_format()
        self._fifo = _Fifo()
        self._clock = _Clock()
        self._renderer = None
        self._gen = 0
        self._t0 = None                  # время проекта, с которого идёт поколение
        self._key = None                 # (снимок проекта, n0) подготовленного звука
        self._primed_gen = -1
        self._playing = False
        self._broken = ""                # тракт невозможен вовсе (нет формата)
        self._error = ""                 # последний отказ устройства (переоткроется)
        self._thread = None
        self._worker = None
        if self._qfmt is None:
            self._broken = "нет подходящего формата вывода звука"
            return
        rate = self._qfmt.sampleRate()
        ch = self._qfmt.channelCount()
        pcm = "f32le" if self._qfmt.sampleFormat() == _api.QAudioFormat.SampleFormat.Float else "s16le"
        self._pcm = (rate, ch, pcm)
        self._thread = _api.QThread(self)
        self._thread.setObjectName("ProjectSoundSink")
        self._worker = _SinkWorker(self._qfmt, self._fifo, self._clock)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.init)
        self._sig_prepare.connect(self._worker.prepare)
        self._sig_play.connect(self._worker.play)
        self._sig_pause.connect(self._worker.pause)
        self._sig_volume.connect(self._worker.set_volume)
        self._sig_shutdown.connect(self._worker.shutdown)
        self._worker.primed.connect(self._on_primed)
        self._worker.broken.connect(self._on_broken)
        self._thread.start()

    @staticmethod
    def _pick_format():
        """48 кГц стерео float (как сводит Qt: float без нормировки 5.1 → 2),
        иначе int16, иначе родной формат устройства."""
        if _api.QAudioFormat is None or _api.QMediaDevices is None or _api.QAudioSink is None:
            return None
        try:
            dev = _api.QMediaDevices.defaultAudioOutput()
            if dev is None or dev.isNull():
                return None
            for sf in (_api.QAudioFormat.SampleFormat.Float, _api.QAudioFormat.SampleFormat.Int16):
                fmt = _api.QAudioFormat()
                fmt.setSampleRate(48000)
                fmt.setChannelCount(2)
                fmt.setSampleFormat(sf)
                if dev.isFormatSupported(fmt):
                    return fmt
            fmt = dev.preferredFormat()
            if fmt.sampleFormat() in (_api.QAudioFormat.SampleFormat.Float,
                                      _api.QAudioFormat.SampleFormat.Int16):
                return fmt
        except Exception:
            pass
        return None

    # ── состояние ────────────────────────────────────────────────────────────
    def usable(self):
        return self._worker is not None and not self._broken

    def error(self):
        return self._broken or self._error

    def is_playing(self):
        return self._playing

    def is_ready(self):
        return self._primed_gen == self._gen and self._t0 is not None

    def start_time(self):
        """Время проекта, с которого подготовлен звук (None — не готовился)."""
        return self._t0

    def prepared_for(self, project, t):
        """Звук уже подготовлен ровно с этого места этого проекта."""
        return self._key == self._make_key(project, t) and self._t0 is not None

    def _make_key(self, project, t):
        try:
            snap = _api.json.dumps(project.to_dict(), sort_keys=True)
        except Exception:
            snap = None
        return (snap, int(round(max(0.0, float(t)) * self._pcm[0])))

    # ── управление ───────────────────────────────────────────────────────────
    def prepare(self, project, t, end=None):
        """Звук проекта с времени t: рендер и предзаполнение устройства. Пока
        не play(), устройство молчит. Первое окно короткое — на паузе ffmpeg
        не держит файлы открытыми."""
        if not self.usable():
            return False
        self._stop_render()
        self._gen += 1
        gen = self._gen
        rate = self._pcm[0]
        t = max(0.0, float(t))
        total = project.duration() if end is None else float(end)
        n0 = int(round(t * rate))
        n_end = max(n0, int(round(total * rate)))
        self._t0 = n0 / float(rate)
        self._key = self._make_key(project, t)
        self._playing = False
        self._fifo.reset(gen)
        self._renderer = _Renderer(project.copy(), n0, n_end, _FIRST_WINDOW_S,
                                   self._pcm, self._fifo, gen)
        self._renderer.start()
        self._sig_prepare.emit(gen)
        return True

    def play(self):
        """Звук пошёл. True — сразу (предзаполнение готово); False — пойдёт,
        когда будет готово (сигнал ready тоже придёт)."""
        if not self.usable() or self._t0 is None:
            return False
        self._playing = True
        self._sig_play.emit(self._gen)
        return self.is_ready()

    def stop(self):
        """Пауза: тишина сразу; следующий play — только после prepare."""
        self._playing = False
        self._stop_render()
        self._t0 = None
        self._key = None
        self._gen += 1
        self._fifo.reset(self._gen)
        if self._worker is not None:
            self._sig_pause.emit()

    def set_volume(self, v):
        if self._worker is not None:
            self._sig_volume.emit(float(v))

    def now(self):
        """Время проекта, которое сейчас слышно (с), или None."""
        if self._t0 is None:
            return None
        gen, written, queued, at, playing = self._clock.get()
        if gen != self._gen:
            return self._t0
        rate = float(self._pcm[0])
        played = max(0, written - queued)
        t = self._t0 + played / rate
        if playing and played > 0:
            t += min(max(0.0, _api.time.monotonic() - at), queued / rate)
            t -= _HOST_LATENCY_S
        return max(self._t0, t)

    def shutdown(self):
        self._stop_render()
        if self._worker is not None:
            self._sig_shutdown.emit()
            self._thread.wait(2000)
            self._worker = None

    # ── внутреннее ───────────────────────────────────────────────────────────
    def _stop_render(self):
        r = self._renderer
        self._renderer = None
        if r is not None:
            r.stop()

    def _on_primed(self, gen):
        if gen != self._gen:
            return
        self._primed_gen = gen
        self._error = ""
        self.ready.emit()

    def _on_broken(self, gen, msg):
        """Устройство отказало (_SinkWorker._fail): звук этого места пропал,
        но тракт жив — следующий prepare откроет устройство заново."""
        if gen != self._gen:
            return                      # отказ прошлого места: новое уже готовится
        self._stop_render()
        self._error = msg or "ошибка устройства звука"
        self._playing = False
        self._t0 = None
        self._key = None
        self.failed.emit(self._error)
