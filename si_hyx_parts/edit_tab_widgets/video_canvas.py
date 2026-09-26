# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""VideoCanvas. Public namespace: edit_tab_widgets."""
import edit_tab_widgets as _api


class VideoCanvas(_api._PaintedVideoCanvas):
    """Холст видео вкладки «Монтаж»: кадр выводит GPU (QML VideoOutput), всё
    остальное поведение — от ЦП-холста, у которого этот класс унаследован.

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
        self._quick = None
        self._out_sink = None
        self._vo = None
        self._ovl_item = None
        self._vo_geom = None            # последняя выставленная геометрия кадра
        # Когда в последний раз приходил кадр ИМЕННО ОТ ПЛЕЕРА (см.
        # _want_cpu_copy). Отдельно от часов кадра (_last_frame_at): те ведёт и
        # точный кадр от предекодера, а нам нужен признак «идёт поток».
        self._last_player_frame_at = 0.0
        self._setup_quick()
        if self._quick is not None:
            # Кнопки «Применить/Отмена» созданы РАНЬШЕ сцены и оказались бы под
            # ней (порядок стека = порядок создания).
            for b in (self._crop_apply_btn, self._crop_cancel_btn):
                b.raise_()

    # ── Сцена ────────────────────────────────────────────────────────────────
    def _setup_quick(self):
        """Поднимает QML-сцену. Если не вышло (нет Qt Quick, не создался
        контекст) — молча остаёмся на ЦП-пути предка: вкладка обязана работать
        в любом случае, пусть и дороже."""
        if not _api._QUICK_AVAILABLE:
            return
        quick = None
        try:
            path = _api._canvas_qml_path()
            if not path:
                return
            quick = _api.QQuickWidget(self)
            # Мышь/колесо/клавиши обрабатывает сам холст (кроп, накладки, зум,
            # панорама) — сцена не должна перехватывать события.
            quick.setAttribute(_api.Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            quick.setResizeMode(_api.QQuickWidget.ResizeMode.SizeRootObjectToView)
            quick.setClearColor(_api.QColor(_api.C["bg"]))
            quick.setSource(_api.QUrl.fromLocalFile(path))
            root = quick.rootObject()
            sink = root.property("sink") if root is not None else None
            if root is None or sink is None:
                errs = "; ".join(e.toString() for e in quick.errors())
                raise RuntimeError(errs or "QML-сцена холста не поднялась")
            self._vo = root.findChild(_api.QObject, "videoOutput")
            self._ovl_item = _api._CanvasOverlayItem(self, root)
            self._ovl_item.setZ(10)
            quick.setGeometry(0, 0, max(1, self.width()), max(1, self.height()))
            quick.lower()
            quick.show()
            self._quick = quick
            self._out_sink = sink
            self._sync_scene()
        except Exception:
            self._quick = None
            self._out_sink = None
            self._vo = None
            self._ovl_item = None
            if quick is not None:
                try:
                    quick.setParent(None)
                    quick.deleteLater()
                except Exception:
                    pass

    def _sync_scene(self):
        """Подгоняет сцену под виджет: размер QQuickWidget и слоя оверлеев, а
        главное — прямоугольник кадра (letterbox + зум + панорама). Источник
        правды один — video_rect(), тот же, по которому считаются координаты
        рамки кадрирования и накладок."""
        quick = getattr(self, "_quick", None)
        if quick is None:
            return
        w, h = max(1, self.width()), max(1, self.height())
        if quick.width() != w or quick.height() != h or quick.x() or quick.y():
            quick.setGeometry(0, 0, w, h)
        ovl = self._ovl_item
        if ovl is not None and (int(ovl.width()) != w or int(ovl.height()) != h):
            ovl.setWidth(float(w))
            ovl.setHeight(float(h))
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

    def update(self, *args):
        """Вся унаследованная логика заявляет об изменениях через self.update() —
        здесь этот вызов заодно двигает кадр в сцене и перерисовывает оверлеи.

        В горячем пути кадра update() НЕ зовётся (см. _on_frame): кадр рисует
        сама сцена, а перерисовывать из-за него слой оверлеев значило бы гнать
        текстуру размером с виджет 60 раз в секунду — ровно та работа, от
        которой мы ушли."""
        if getattr(self, "_quick", None) is not None:
            self._sync_scene()
            if self._ovl_item is not None:
                self._ovl_item.update()
        super().update(*args)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if getattr(self, "_quick", None) is not None:
            self._sync_scene()
            if self._ovl_item is not None:
                self._ovl_item.update()

    def paintEvent(self, ev):
        # Кадр и оверлеи рисует сцена; виджету остаётся фон — он виден разве что
        # в момент до первого кадра сцены.
        if getattr(self, "_quick", None) is None:
            super().paintEvent(ev)
            return
        p = _api.QPainter(self)
        p.fillRect(self.rect(), self._bg)
        p.end()

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
        этой работы мы и ушли, а держать ссылку на сам QVideoFrame до
        востребования бесполезно: после возврата из слота бэкенд переиспользует
        буфер, и toImage() отдаёт пустую картинку (проверено экспериментом)."""
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
        size = self._frame_px_size(frame)
        if size.width() > 0 and size != self._px_size:
            self._px_size = size
            self._vo_geom = None        # прямоугольник кадра пересчитать
        self._frame_img = (self._grab_cpu_copy(frame)
                           if self._want_cpu_copy() else None)
        self._last_player_frame_at = _api.time.monotonic()
        self._publish_frame(frame)
        # Часы кадра — время картинки, которая СЕЙЧАС на экране.
        if pts >= 0:
            self._last_pts_us = pts
            self._last_frame_at = _api.time.monotonic()
            # Время предпросмотра накладки берём из PTS самого кадра: так
            # накладка стоит на своём кадре и при воспроизведении, и при
            # покадровой перемотке (positionChanged плеера приходит реже).
            if self._trk is not None:
                self._trk_t = pts / 1_000_000.0
        if self._vo_geom is None:      # сменился размер кадра — переставить
            self._sync_scene()
        # Слой оверлеев перерисовываем, только если он зависит от кадра: трек-
        # превью едет за объектом по времени кадра. Субтитры, рамка кропа и
        # накладки от смены кадра не меняются — и не стоят ничего.
        if self._trk is not None and self._ovl_item is not None:
            self._ovl_item.update()

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
        """Возвращает картинку на сцену после пересоздания графического
        контекста (перенос холста в полноэкранное окно и обратно). Во время
        воспроизведения ничего делать не нужно — следующий кадр приедет сам
        через ~16 мс; а вот на паузе сцена осталась бы чёрной."""
        quick = getattr(self, "_quick", None)
        if quick is None:
            return
        self._sync_scene()
        img = self._frame_img
        if img is not None and not img.isNull():
            # Просто подать картинку мало: VideoOutput после переезда держит
            # кадр от ПРЕЖНЕГО графического контекста и новый сам не
            # подхватывает — экран остаётся чёрным (проверено скриншотом
            # реального окна). Сбрасываем кадр, будим сцену, подаём заново.
            sink = self._out_sink
            if sink is not None:
                try:
                    sink.setVideoFrame(_api.QVideoFrame())
                except Exception:
                    pass
            quick.update()
            self._px_size = img.size()
            self._vo_geom = None
            self._publish_image(img)
            self._sync_scene()
            quick.update()
        if self._ovl_item is not None:
            self._ovl_item.update()

    def event(self, ev):
        if (getattr(self, "_quick", None) is not None
                and ev.type() == _api.QEvent.Type.ParentChange):
            # Перенос в полноэкранное окно пересоздаёт контекст сцены — кадр
            # надо подать заново, но уже ПОСЛЕ того, как Qt закончит перенос.
            _api.QTimer.singleShot(0, self._republish_frame)
        return super().event(ev)

    def showEvent(self, ev):
        super().showEvent(ev)
        if getattr(self, "_quick", None) is not None:
            self._sync_scene()
            _api.QTimer.singleShot(0, self._republish_frame)

VideoCanvas.__module__ = _api.__name__
_api.VideoCanvas = VideoCanvas
