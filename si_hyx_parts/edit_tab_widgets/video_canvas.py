# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""VideoCanvas. Public namespace: edit_tab_widgets."""
import edit_tab_widgets as _api


class VideoCanvas(_api._PaintedVideoCanvas):
    """Холст видео вкладки «Монтаж»: кадр выводит GPU (QML VideoOutput в
    собственном окне Qt Quick с потоком рендера), всё остальное поведение — от
    ЦП-холста, у которого этот класс унаследован.

    Публичный API совпадает с прежним холстом полностью (videoSink, video_rect,
    субтитры, пин кадра, кадрирование, накладки, трек-превью, зум/панорама) —
    вкладка не знает, каким путём кадр попадает на экран.

    Единственное отличие в поведении: current_frame_image() во время
    ВОСПРОИЗВЕДЕНИЯ отдаёт None (ЦП-копии кадра в этот момент нет и не должно
    быть). «Сохранить кадр» тогда сам уходит на резервный ffmpeg-путь, который
    для этого и написан. На паузе и на покадровом шаге копия есть, и кадр
    сохраняется ровно тот, что на экране."""

    def __init__(self, parent=None):
        super().__init__(parent)
        # Размер кадра в пикселях (уже с учётом поворота из метаданных) — по
        # нему считается letterbox. Раньше его давал QImage кадра, которого в
        # GPU-пути попросту нет.
        self._px_size = _api.QSize()
        self._quick = None              # контейнер окна сцены (QWidget)
        self._qwin = None               # окно сцены (QQuickWindow)
        self._engine = None
        self._ovl_provider = None
        self._out_sink = None
        self._vo = None
        self._ovl_obj = None            # слой оверлеев (Image в сцене)
        self._vo_geom = None            # последняя выставленная геометрия кадра
        self._ovl_pending = False       # перерисовка оверлеев уже запланирована
        self._ovl_shown = False
        self._ovl_seq = 0
        # Когда в последний раз приходил кадр ИМЕННО ОТ ПЛЕЕРА (см.
        # _want_cpu_copy). Отдельно от часов кадра (_last_frame_at): те ведёт и
        # точный кадр от предекодера, а нам нужен признак «идёт поток».
        self._last_player_frame_at = 0.0
        # Кадр плеера отдаётся сцене, только когда она показала предыдущий
        # (см. _present_frame): с какого момента сцена занята и какой кадр
        # ждёт своей очереди (frame, pts).
        self._scene_busy_since = 0.0
        self._pending_frame = None
        self._setup_quick()
        if self._quick is not None:
            # Сцена — нативное окно и перекрывает обычные дочерние виджеты
            # холста. Кнопки «Применить/Отмена» поэтому тоже нативные (одни,
            # без соседей и предков — см. _make_native_alone) и держатся над
            # сценой (см. _update_crop_buttons).
            for b in (self._crop_apply_btn, self._crop_cancel_btn):
                _api._make_native_alone(b)
                b.raise_()

    # ── Сцена ────────────────────────────────────────────────────────────────
    def _setup_quick(self):
        """Поднимает QML-сцену. Если не вышло (нет Qt Quick, не создался
        контекст) — молча остаёмся на ЦП-пути предка: вкладка обязана работать
        в любом случае, пусть и дороже."""
        if not _api._QUICK_AVAILABLE:
            return
        cont = None
        try:
            engine = _api.QQmlEngine()
            provider = _api._CanvasOverlayProvider()
            engine.addImageProvider(_api._OVERLAY_PROVIDER, provider)
            win = _api._create_canvas_window(engine)
            sink = win.property("sink")
            vo = win.findChild(_api.QObject, "videoOutput")
            ovl = win.findChild(_api.QObject, "overlay")
            if sink is None or vo is None or ovl is None:
                raise RuntimeError("в QML-сцене холста нет нужных элементов")
            # Сигнал испускает поток рендера; очередь доставляет его в
            # GUI-поток, и Python в потоке рендера не выполняется вовсе.
            win.frameSwapped.connect(self._on_scene_swapped,
                                     _api.Qt.ConnectionType.QueuedConnection)
            cont = _api.QWidget.createWindowContainer(win, self)
            # Движок обязан пережить окно сцены: контейнер удаляет окно в
            # своём деструкторе и лишь потом — своих детей, движок в их числе.
            # Ребёнком холста он умер бы раньше контейнера (дети удаляются в
            # порядке создания) — и падение при закрытии программы.
            engine.setParent(cont)
            # Мышь — холсту (см. флаги окна сцены), фокус — тоже: контейнер с
            # фокусом активировал бы окно сцены и увёл бы у вкладки клавиши.
            cont.setAttribute(_api.Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            cont.setFocusPolicy(_api.Qt.FocusPolicy.NoFocus)
            cont.setGeometry(0, 0, max(1, self.width()), max(1, self.height()))
            cont.lower()
            cont.show()
            self._engine = engine
            self._ovl_provider = provider
            self._qwin = win
            self._vo = vo
            self._ovl_obj = ovl
            self._out_sink = sink
            self._quick = cont
            self._sync_scene()
        except Exception:
            self._quick = None
            self._qwin = None
            self._engine = None
            self._ovl_provider = None
            self._out_sink = None
            self._vo = None
            self._ovl_obj = None
            if cont is not None:
                try:
                    cont.setParent(None)
                    cont.deleteLater()
                except Exception:
                    pass

    def _sync_scene(self):
        """Подгоняет сцену под виджет: размер окна сцены, а главное —
        прямоугольник кадра (letterbox + зум + панорама). Источник правды
        один — video_rect(), тот же, по которому считаются координаты рамки
        кадрирования и накладок."""
        quick = getattr(self, "_quick", None)
        if quick is None:
            return
        w, h = max(1, self.width()), max(1, self.height())
        if quick.width() != w or quick.height() != h or quick.x() or quick.y():
            quick.setGeometry(0, 0, w, h)
        vo = self._vo
        if vo is None:
            return
        if self._has_frame():
            vr = self.video_rect()
            geom = (vr.left(), vr.top(), max(1, vr.width()), max(1, vr.height()))
        else:
            geom = None
        if geom == self._vo_geom:
            return
        self._vo_geom = geom
        if geom is None:
            vo.setProperty("visible", False)
            return
        vo.setProperty("x", float(geom[0]))
        vo.setProperty("y", float(geom[1]))
        vo.setProperty("width", float(geom[2]))
        vo.setProperty("height", float(geom[3]))
        vo.setProperty("visible", True)

    # ── Слой оверлеев ────────────────────────────────────────────────────────
    def _schedule_overlay(self):
        """Перерисовать оверлеи один раз на ближайшем витке цикла событий, как
        бы часто ни звали update() (тянут рамку — это десятки раз в секунду)."""
        if self._ovl_obj is None or self._ovl_pending:
            return
        self._ovl_pending = True
        _api.QTimer.singleShot(0, self._refresh_overlay)

    def _overlay_has_content(self, has_frame):
        if not has_frame:
            return bool(self._audio_only_msg)
        return bool(self._ovls or self._text or self._image is not None
                    or self._crop_norm is not None or self._trk is not None)

    def _refresh_overlay(self):
        """Рисует оверлеи в картинку ровно в размер холста (в пикселях
        экрана) и отдаёт её сцене. Тот же код и тот же порядок слоёв, что и в
        paintEvent ЦП-холста."""
        self._ovl_pending = False
        ovl = self._ovl_obj
        if ovl is None:
            return
        try:
            has_frame = self._has_frame()
            if not self._overlay_has_content(has_frame):
                # Пустой слой во весь холст GPU всё равно смешивал бы на каждом
                # кадре — прячем его.
                if self._ovl_shown:
                    self._ovl_shown = False
                    ovl.setProperty("visible", False)
                    self._ovl_provider.image = _api.QImage()
                return
            w, h = max(1, self.width()), max(1, self.height())
            dpr = self.devicePixelRatioF() or 1.0
            img = _api.QImage(max(1, _api.math.ceil(w * dpr)), max(1, _api.math.ceil(h * dpr)),
                              _api.QImage.Format.Format_ARGB32_Premultiplied)
            img.setDevicePixelRatio(dpr)
            img.fill(_api.Qt.GlobalColor.transparent)
            p = _api.QPainter(img)
            try:
                if has_frame:
                    self._paint_overlays(p, self.video_rect())
                else:
                    self._paint_audio_only(p)
            finally:
                p.end()
            self._ovl_provider.image = img
            self._ovl_seq += 1
            ovl.setProperty("source", _api.QUrl(
                f"image://{_api._OVERLAY_PROVIDER}/{self._ovl_seq}"))
            if not self._ovl_shown:
                self._ovl_shown = True
                ovl.setProperty("visible", True)
        except RuntimeError:            # холст уже снесён Qt — рисовать нечего
            pass

    def update(self, *args):
        """Вся унаследованная логика заявляет об изменениях через self.update() —
        здесь этот вызов заодно двигает кадр в сцене и перерисовывает оверлеи.

        В горячем пути кадра update() НЕ зовётся (см. _on_frame): кадр рисует
        сама сцена, а перерисовывать из-за него слой оверлеев значило бы гнать
        картинку размером с виджет 24–60 раз в секунду — ровно та работа, от
        которой мы ушли."""
        if getattr(self, "_quick", None) is not None:
            self._sync_scene()
            self._schedule_overlay()
        super().update(*args)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if getattr(self, "_quick", None) is not None:
            self._sync_scene()
            self._schedule_overlay()

    def paintEvent(self, ev):
        # Кадр и оверлеи рисует сцена; виджету остаётся фон — он виден разве что
        # в момент до первого кадра сцены.
        if getattr(self, "_quick", None) is None:
            super().paintEvent(ev)
            return
        p = _api.QPainter(self)
        p.fillRect(self.rect(), self._bg)
        p.end()

    def _update_crop_buttons(self):
        super()._update_crop_buttons()
        if getattr(self, "_quick", None) is None:
            return
        for b in (self._crop_apply_btn, self._crop_cancel_btn):
            if b.isVisible() and b.property("_mask_size") != b.size():
                b.setMask(_api._round_mask(b.size(), 6.0))
                b.setProperty("_mask_size", b.size())

    # ── Наличие и размер кадра ───────────────────────────────────────────────
    def _has_frame(self):
        if self._px_size.width() > 0 and self._px_size.height() > 0:
            return True
        return super()._has_frame()

    def _frame_size(self):
        if self._px_size.width() > 0 and self._px_size.height() > 0:
            return self._px_size
        return super()._frame_size()

    @staticmethod
    def _pts_of(frame):
        try:
            pts = frame.startTime()
        except Exception:
            return -1
        return int(pts) if pts is not None else -1

    @staticmethod
    def _frame_px_size(frame):
        """Размер кадра ТАК, КАК ЕГО ПОКАЖЕТ СЦЕНА — с учётом поворота из
        метаданных. Раньше поворот за нас применял toImage(); теперь его
        применяет VideoOutput, и letterbox обязан считаться по повёрнутому
        размеру, иначе у вертикалок с телефона рамка кадрирования, субтитры и
        накладки лягут мимо кадра."""
        try:
            w, h = int(frame.width()), int(frame.height())
        except Exception:
            return _api.QSize()
        if w <= 0 or h <= 0:
            return _api.QSize()
        rot = 0
        try:
            r = frame.surfaceFormat().rotation()
            rot = int(getattr(r, "value", r))
        except Exception:
            rot = 0
        # В разных версиях Qt это либо градусы (0/90/180/270), либо номер в
        # перечислении (0..3) — принимаем оба.
        if rot in (90, 270, 1, 3):
            w, h = h, w
        return _api.QSize(w, h)

    def _publish_frame(self, frame):
        sink = self._out_sink
        if sink is None:
            return
        try:
            sink.setVideoFrame(frame)
        except Exception:
            pass

    def _publish_image(self, img):
        """Кладёт готовую картинку (точный кадр от предекодера, статичный кадр
        режима «картинка → видео») в ту же сцену, что и кадры плеера — одним
        путём, без второго слоя поверх видео."""
        sink = self._out_sink
        if sink is None or img is None or img.isNull():
            return
        # Картинка вкладки главнее отложенного кадра плеера: тот показал бы
        # поверх неё прошлое.
        self._pending_frame = None
        try:
            frame = _api.QVideoFrame(img)
            if not frame.isValid():
                frame = _api.QVideoFrame(img.convertToFormat(_api.QImage.Format.Format_RGB32))
            if frame.isValid():
                sink.setVideoFrame(frame)
        except Exception:
            pass

    def _clear_scene_frame(self):
        """Убирает кадр со сцены (новый файл, аудио без видеоряда)."""
        self._px_size = _api.QSize()
        self._vo_geom = None
        self._pending_frame = None
        sink = self._out_sink
        if sink is not None:
            try:
                sink.setVideoFrame(_api.QVideoFrame())
            except Exception:
                pass
        vo = self._vo
        if vo is not None:
            vo.setProperty("visible", False)

    def _want_cpu_copy(self):
        """Нужна ли ЦП-копия ЭТОГО кадра (см. _grab_cpu_copy).

        Мало спросить у флагов, которые ставит вкладка (воспроизведение,
        протяжка): кадры сыплются потоком и в тех местах, где вкладка о
        воспроизведении не объявляет — например, во время беззвучного прогрева
        аудио (EditTab._preroll_at: плеер реально играет, но on_playback_changed
        молчит). Поэтому смотрим и на сами кадры: если предыдущий пришёл меньше
        120 мс назад — идёт поток, и конвертировать каждый кадр нельзя ни в
        коем случае (ровно эта работа и грузила главный поток)."""
        if self._playing or self._scrub_active:
            return False
        last = self._last_player_frame_at
        return not (last > 0.0 and (_api.time.monotonic() - last) < 0.12)

    def _grab_cpu_copy(self, frame):
        """ЦП-копия кадра для «Сохранить кадр». Делается ТОЛЬКО когда монтаж
        стоит: там кадр приходит по одному на перемотку, и 8 мс на конвертацию
        никому не мешают. Во время воспроизведения копии нет вовсе — ровно от
        этой работы мы и ушли. А держать до востребования сам кадр из слота
        нельзя: это обёртка над копией кадра внутри события очереди, и после
        возврата из слота она висячая (toImage() давал пустую картинку,
        обращение позже роняет программу, см. _present_frame)."""
        try:
            img = frame.toImage()
        except Exception:
            return None
        return img if (img is not None and not img.isNull()) else None

    # ── Кадр от плеера ───────────────────────────────────────────────────────
    def _on_frame(self, frame):
        if getattr(self, "_quick", None) is None:
            super()._on_frame(frame)
            return
        # Аудиофайл (видеоряда нет): «поздние» кадры прошлого источника не
        # должны перекрывать сообщение «нет видео».
        if self._audio_only_msg:
            return
        try:
            if frame is None or not frame.isValid():
                return
        except Exception:
            return
        pts = self._pts_of(frame)
        # Граница OUT по PTS — ДО показа кадра: кадр за границей не показываем
        # вовсе и просим плеер на паузу (анти-overshoot правой границы).
        if self._bound_us is not None and pts >= 0 and pts >= self._bound_us:
            self.boundaryReached.emit()
            return
        # Пин кадра N: пока на холсте стоит ТОЧНЫЙ кадр, кадры плеера с чужим
        # pts на экран не пускаем — иначе шаг стрелкой показывает не тот кадр.
        if (self._pin_has_img and self._pin_span is not None and pts >= 0
                and not (self._pin_span[0] <= pts < self._pin_span[1])):
            return
        # ЦП-копию снимаем здесь же, пока объект кадра из слота жив (см.
        # _grab_cpu_copy). Кадр, отложенный до готовности сцены, копии не
        # требует — копия бывает только тогда, когда потока кадров нет.
        self._frame_img = (self._grab_cpu_copy(frame)
                           if self._want_cpu_copy() else None)
        now = _api.time.monotonic()
        self._last_player_frame_at = now
        self._present_frame(frame, pts, now)

    def _present_frame(self, frame, pts, now):
        """Отдаёт кадр сцене — или, если она ещё показывает предыдущий,
        откладывает до сигнала frameSwapped (_on_scene_swapped).

        Зачем. Новый кадр запускает синхронизацию сцены, а её GUI-поток ждёт,
        пока поток рендера не освободится. Когда GPU занят чужой работой
        (игра, другой видеоредактор), один Present у потока рендера тянется
        30–80 мс при кадре раз в 41 мс — и GUI-поток простаивал бы в ожидании
        почти постоянно. Отложенный кадр заменяется более свежим: на экран
        уходит последний, промежуточные пропадают — как и положено видео,
        которое не успевает за GPU. Если сцена молчит дольше 250 мс (окно
        скрыто, сигнал потерялся), ждать перестаём."""
        busy = self._scene_busy_since
        if busy and (now - busy) < 0.25:
            # Именно копия: объект из слота — обёртка над копией кадра внутри
            # события очереди и умирает вместе с ним сразу после возврата из
            # слота (обращение к нему потом роняет программу). Копия делит с
            # кадром буфер и держит его живым.
            self._pending_frame = (_api.QVideoFrame(frame), pts)
            return
        self._pending_frame = None
        self._commit_frame(frame, pts, now)

    def _commit_frame(self, frame, pts, now):
        size = self._frame_px_size(frame)
        if size.width() > 0 and size != self._px_size:
            self._px_size = size
            self._vo_geom = None        # прямоугольник кадра пересчитать
        self._scene_busy_since = now
        self._publish_frame(frame)
        # Часы кадра — время картинки, которая СЕЙЧАС на экране.
        if pts >= 0:
            self._last_pts_us = pts
            self._last_frame_at = now
            # Время предпросмотра накладки берём из PTS самого кадра: так
            # накладка стоит на своём кадре и при воспроизведении, и при
            # покадровой перемотке (positionChanged плеера приходит реже).
            if self._trk is not None:
                self._trk_t = pts / 1_000_000.0
        if self._vo_geom is None:      # сменился размер кадра — переставить
            self._sync_scene()
            self._schedule_overlay()
        # Слой оверлеев перерисовываем, только если он зависит от кадра: трек-
        # превью едет за объектом по времени кадра. Субтитры, рамка кропа и
        # накладки от смены кадра не меняются — и не стоят ничего.
        if self._trk is not None:
            self._schedule_overlay()

    def _on_scene_swapped(self):
        """Сцена показала кадр — можно отдавать следующий, и, если он уже
        ждёт, отдаём сразу. Пин, граница OUT и режим «нет видео» за время
        ожидания могли смениться — проверяем их заново."""
        self._scene_busy_since = 0.0
        pending = self._pending_frame
        if pending is None:
            return
        self._pending_frame = None
        frame, pts = pending
        if self._audio_only_msg or self._out_sink is None:
            return
        if self._bound_us is not None and pts >= 0 and pts >= self._bound_us:
            return
        if (self._pin_has_img and self._pin_span is not None and pts >= 0
                and not (self._pin_span[0] <= pts < self._pin_span[1])):
            return
        self._commit_frame(frame, pts, _api.time.monotonic())

    # ── Кадры, которые ставит вкладка ────────────────────────────────────────
    def set_exact_frame(self, img, span_us=None, pts_us=None):
        if (getattr(self, "_quick", None) is not None
                and img is not None and not img.isNull()):
            if img.size() != self._px_size:
                self._px_size = img.size()
                self._vo_geom = None
            self._publish_image(img)
        super().set_exact_frame(img, span_us, pts_us)

    def set_static_image(self, qimg):
        if getattr(self, "_quick", None) is not None:
            if qimg is not None and not qimg.isNull():
                self._px_size = qimg.size()
                self._vo_geom = None
                self._publish_image(qimg)
            else:
                self._clear_scene_frame()
        super().set_static_image(qimg)

    def clear_frame(self):
        if getattr(self, "_quick", None) is not None:
            self._clear_scene_frame()
        super().clear_frame()

    def set_audio_only_message(self, text):
        if getattr(self, "_quick", None) is not None and text:
            self._clear_scene_frame()
        super().set_audio_only_message(text)

    def current_frame_image(self):
        """Кадр, который сейчас на холсте, — или None во время воспроизведения
        (ЦП-копии в этот момент нет, см. _grab_cpu_copy). Возвращать устаревшую
        картинку нельзя: «Сохранить кадр» сохранил бы не тот кадр — пусть лучше
        сработает резервный ffmpeg-путь вкладки."""
        return super().current_frame_image()

    # ── Полноэкранный режим ──────────────────────────────────────────────────
    def _republish_frame(self):
        """Подгоняет сцену после переезда холста в другое окно (полноэкранный
        режим и обратно). Окно сцены переезжает вместе с холстом целиком, со
        своим графическим контекстом и показанным кадром, — подать заново надо
        лишь геометрию, слой оверлеев и кнопки кадрирования поверх сцены."""
        if getattr(self, "_quick", None) is None:
            return
        self._vo_geom = None
        self._sync_scene()
        self._schedule_overlay()
        self._update_crop_buttons()

    def event(self, ev):
        if (getattr(self, "_quick", None) is not None
                and ev.type() == _api.QEvent.Type.ParentChange):
            # Подгоняем сцену, когда Qt закончит перенос.
            _api.QTimer.singleShot(0, self._republish_frame)
        return super().event(ev)

    def showEvent(self, ev):
        super().showEvent(ev)
        if getattr(self, "_quick", None) is not None:
            self._sync_scene()
            _api.QTimer.singleShot(0, self._republish_frame)

VideoCanvas.__module__ = _api.__name__
_api.VideoCanvas = VideoCanvas
