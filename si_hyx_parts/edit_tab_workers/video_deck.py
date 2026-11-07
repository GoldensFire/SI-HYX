# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""VideoDeck — плеер картинки просмотра проекта «Монтажа» в своём потоке.
Public namespace: edit_tab_workers.

Зачем. QMediaPlayer (ffmpeg-бэкенд Qt 6.10–6.11) меняет файл в потоке, которому
принадлежит: setSource разбирает прежний декодер (avcodec_free_context,
ожидание его потоков), а при аппаратном декодировании ещё создаёт и уничтожает
устройство D3D11 драйвера. Замер 31.10.2026 (AMD Vega, d3d11va, H.264 и HEVC
10 бит 1080p): основной плеер вкладки на смене файла держал GUI-поток
90–650 мс, первый кадр нового файла приходил через 0.4–0.9 с. Дека делает это
в своём потоке и заранее: кусок открыт, стоит на своём первом кадре, и на
стыке только продолжает играть (EditTabProjectDecksMixin).

Python в потоке деки выполняется один раз — при создании плеера. Команды идут
сигналами прямо в слоты C++ плеера (play, pause, setPosition, setSource…):
слот, вызванный из Python, держал бы GIL всё время разбора декодера и создания
устройства, и GUI-поток стоял бы вместе с ним (прототип: с вызовами из Python —
рывок 50–84 мс на каждой загрузке другого файла, без Python — ни одного).
Состояние плеера и кадры приходят в GUI-поток очередью.

Дека — только картинка: без аудиовыхода её часы идут по стене, звук просмотра
играет тракт project_sound."""
import edit_tab_workers as _api
from sip_notify import prime_disconnect_notify


class _DeckHome(_api.QObject):
    """Создаёт плеер деки в её потоке: объект Qt живёт там, где создан."""

    born = _api.pyqtSignal(object, object)       # QMediaPlayer, QVideoSink

    @_api.pyqtSlot()
    def create(self):
        player = prime_disconnect_notify(_api.QMediaPlayer(self))
        sink = prime_disconnect_notify(_api.QVideoSink(self))
        player.setVideoSink(sink)
        self.born.emit(player, sink)

    @_api.pyqtSlot()
    def shutdown(self):
        # Плеер — ребёнок: удалится вместе с домом здесь же, в потоке деки.
        self.deleteLater()
        _api.QThread.currentThread().quit()


class VideoDeck(_api.QObject):
    """Дека для вкладки (живёт в GUI-потоке). load() — встать на кадр файла;
    встала — сигнал ready, сам кадр в ready_frame; кадры после play() —
    сигнал frame."""

    ready = _api.pyqtSignal(object)              # дека
    frame = _api.pyqtSignal(object, object)      # дека, QVideoFrame (только в слоте)
    failed = _api.pyqtSignal(object)             # дека: файл не открылся

    _c_create = _api.pyqtSignal()
    _c_shutdown = _api.pyqtSignal()
    _c_url = _api.pyqtSignal(_api.QUrl)
    _c_device = _api.pyqtSignal(_api.QIODevice, _api.QUrl)
    _c_position = _api.pyqtSignal('qint64')
    _c_rate = _api.pyqtSignal(float)
    _c_play = _api.pyqtSignal()
    _c_pause = _api.pyqtSignal()
    _c_stop = _api.pyqtSignal()

    def __init__(self, name, parent=None):
        super().__init__(parent)
        self.player = None
        self.sink = None
        self.key = None              # заказ (его сравнивает вкладка); None — свободна
        self.path = None             # файл открытый или открываемый
        self.ready_frame = None      # QVideoFrame заказанного кадра
        self.is_ready = False
        self.playing = False
        self.free_at = 0.0           # раньше этого момента не перезаказывать
        self.used_at = 0.0
        self._window = (0, 0)        # pts (мкс), в которых кадр — заказанный
        self._want = None            # (мс, скорость): встать после LoadedMedia
        self._seen_loading = False
        self._accept = False         # кадры уже от заказанного файла
        self._opened = False         # path открыт: новый заказ — только перемотка
        self._dev = None
        self._old_devs = []
        self._pending = None         # заказ до рождения плеера
        self._thread = _api.QThread(self)
        self._thread.setObjectName(name)
        self._home = _DeckHome()
        self._home.moveToThread(self._thread)
        self._c_create.connect(self._home.create)
        self._c_shutdown.connect(self._home.shutdown)
        self._home.born.connect(self._on_born)
        self._thread.start()
        self._c_create.emit()

    def _on_born(self, player, sink):
        self.player, self.sink = player, sink
        self._c_url.connect(player.setSource)
        self._c_device.connect(player.setSourceDevice)
        self._c_position.connect(player.setPosition)
        self._c_rate.connect(player.setPlaybackRate)
        self._c_play.connect(player.play)
        self._c_pause.connect(player.pause)
        self._c_stop.connect(player.stop)
        player.mediaStatusChanged.connect(self._on_status)
        player.errorOccurred.connect(self._on_error)
        sink.videoFrameChanged.connect(self._on_frame)
        pend, self._pending = self._pending, None
        if pend is not None:
            self.load(*pend)

    # ── Заказ ────────────────────────────────────────────────────────────────
    def load(self, key, path, pos_ms, window, rate):
        """Встать на кадр файла path: pos_ms — середина кадра, window=(lo, hi) —
        pts (мкс), в которых пришедший кадр считается заказанным."""
        self.key = key
        self.ready_frame = None
        self.is_ready = False
        self.playing = False
        self._window = window
        self.used_at = _api.time.monotonic()
        if self.player is None:
            self._pending = (key, path, pos_ms, window, rate)
            return
        if self._opened and path == self.path:
            # Файл уже открыт — только перемотка: декодер не разбирается.
            self._accept = True
            self._c_rate.emit(float(rate))
            self._c_position.emit(int(pos_ms))
            self._c_pause.emit()
            return
        self._accept = False
        self._opened = False
        self._seen_loading = False
        self._want = (int(pos_ms), float(rate))
        self.path = path
        url = _api.QUrl.fromLocalFile(str(path))
        # Как у основного плеера: файл открыт с FILE_SHARE_DELETE — исходник
        # можно удалить и тогда, когда его держит дека.
        dev = _api.open_share_delete_file(path)
        if self._dev is not None:
            self._old_devs.append(self._dev)
        self._dev = dev
        if dev is not None:
            self._c_device.emit(dev, url)
        else:
            self._c_url.emit(url)

    def play(self):
        if self.player is None or not self.is_ready:
            return False
        self.playing = True
        self._c_play.emit()
        return True

    def pause(self):
        self.playing = False
        if self.player is not None:
            self._c_pause.emit()

    def release(self, delay_s=0.0):
        """Кусок доигран или заказ не нужен: дека свободна не раньше чем через
        delay_s — сцена холста успеет сменить её кадр. Иначе последний кадр
        декодера освобождался бы в потоке рендера уже после его разбора, а с
        ним и устройство D3D11."""
        self.pause()
        self.key = None
        self.ready_frame = None
        self.is_ready = False
        self.free_at = _api.time.monotonic() + delay_s

    def unload(self):
        """Закрыть файл: не держать ни его, ни декодер."""
        self.release()
        self._want = None
        self._accept = False
        self._opened = False
        self.path = None
        if self.player is not None:
            self._c_stop.emit()
            self._c_url.emit(_api.QUrl())
        if self._dev is not None:
            self._old_devs.append(self._dev)
            self._dev = None
        if self.player is None:
            self._close_old_devices()

    def shutdown(self):
        self.unload()
        self._c_shutdown.emit()
        self._thread.quit()
        self._thread.wait(3000)
        self._close_old_devices()

    # ── Из потока деки ───────────────────────────────────────────────────────
    def _on_status(self, status):
        S = _api.QMediaPlayer.MediaStatus
        if status == S.LoadingMedia:
            # Прежний источник разобран (setSource делает это до загрузки).
            self._seen_loading = True
            self._close_old_devices()
        elif status == S.LoadedMedia and self._want is not None and self._seen_loading:
            # До LoadedMedia плеер перемотку пропускает. Перед новой загрузкой
            # Qt шлёт LoadedMedia ещё прежнего файла — его отсекает _seen_loading.
            pos, rate = self._want
            self._want = None
            self._opened = True
            self._accept = True
            self._c_rate.emit(rate)
            self._c_position.emit(pos)
            self._c_pause.emit()
        elif status == S.InvalidMedia and self._want is not None:
            self._fail()
        elif status == S.NoMedia:
            self._close_old_devices()

    def _on_error(self, _error, _message):
        if self._want is not None:
            self._fail()

    def _fail(self):
        self._want = None
        self._opened = False
        self._accept = False
        self.path = None
        self.is_ready = False
        self.ready_frame = None
        self.failed.emit(self)

    def _on_frame(self, frame):
        if not self._accept or self.key is None:
            return
        try:
            if not frame.isValid():
                return
            pts = int(frame.startTime())
        except Exception:
            return
        if not self.is_ready:
            lo, hi = self._window
            if lo <= pts < hi:
                self.ready_frame = _api.QVideoFrame(frame)
                self.is_ready = True
                self.ready.emit(self)
            return
        self.frame.emit(self, frame)

    def _close_old_devices(self):
        devs, self._old_devs = self._old_devs, []
        for d in devs:
            try:
                d.close()
            except Exception:
                pass


VideoDeck.__module__ = _api.__name__
