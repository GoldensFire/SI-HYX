# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""EditTab: _reset_image_overlay. Public namespace: edit_tab."""
import edit_tab as _api


def _reset_image_overlay(self, idx):
    """Сброс слоя к исходному виду: без поворота, без обрезки, стандартный
        размер/место (удобно, когда картинку «закрутили» и потеряли)."""
    items = self.image_overlays()
    if not (0 <= idx < len(items)):
        return
    it = items[idx]
    it.angle = 0.0
    it.set_crop(_api.QRectF(0.0, 0.0, 1.0, 1.0), keep_width=False)
    cw, ch = it.cropped_size()
    it.rect = _api.fit_rect_norm(cw, ch, it.frame_w, it.frame_h)
    self.video_widget.update()
    self._refresh_overlay_panel(idx)

def _crop_image_overlay(self, idx):
    """Кадрирование самой картинки (отдельное окно с рамкой обрезки)."""
    items = self.image_overlays()
    if not (0 <= idx < len(items)):
        return
    it = items[idx]
    dlg = _api.OverlayCropDialog(it, self)
    if dlg.exec() != _api.QDialog.DialogCode.Accepted:
        return
    if it.set_crop(dlg.crop_norm()):
        self.video_widget.update()
        self._refresh_overlay_panel(idx)

def _clear_image_overlays(self):
    """Убирает все слои (новый файл начинается чистым, как и пикселизация)."""
    vw = getattr(self, "video_widget", None)
    if isinstance(vw, _api.VideoCanvas):
        vw.clear_image_overlays()
    self._refresh_overlay_panel()

def _render_export_overlays(self):
    """Готовит PNG всех накладок под размер ИСХОДНОГО кадра. Возвращает
        список (путь, x, y) для overlay_filter_graph (пустой — накладок нет).

        PNG кладутся во временную папку вкладки и переписываются на каждом
        экспорте; папку убирает shutdown()."""
    items = self.image_overlays()
    if not items:
        return []
    fw, fh = self._overlay_frame_size()
    if fw <= 0 or fh <= 0:
        return []
    d = getattr(self, "_overlay_tmp_dir", None)
    if not d or not _api.os.path.isdir(d):
        d = _api.tempfile.mkdtemp(prefix="sihyx_overlay_")
        self._overlay_tmp_dir = d
    return _api.render_overlays(items, d, fw, fh)

def _paint_overlays_on_image(self, img):
    """Впечатывает наложенные картинки в готовый кадр (QImage) — тем же
        порядком и в тех же долях, что и экспорт. Возвращает новый QImage (или
        исходный, если накладок нет)."""
    items = self.image_overlays()
    if not items or img is None or img.isNull():
        return img
    out = img.convertToFormat(_api.QImage.Format.Format_ARGB32)
    p = _api.QPainter(out)
    try:
        for it in items:
            ovl, x, y = it.rendered(out.width(), out.height())
            if ovl is not None:
                p.drawImage(int(x), int(y), ovl)
    finally:
        p.end()
    return out

def _static_overlays_bgra(self, frame_w, frame_h):
    """Наложенные картинки в виде (BGRA, x, y) под размер кадра — для путей,
        которые правят кадры сами (TrackOverlayWorker), а не через -vf."""
    out = []
    for it in self.image_overlays():
        img, x, y = it.rendered(frame_w, frame_h)
        if img is None:
            continue
        bgra = _api.qimage_to_bgra(img)
        if bgra is not None:
            out.append((bgra, int(x), int(y)))
    return out

def _wrap_vf(self, chain, src=None):
    """Оборачивает готовую цепочку -vf графом с накладками (если они есть).
        `chain` — строка фильтров Монтажа (может быть пустой), `src` — файл, из
        которого идёт кодирование (по умолчанию открытый в Монтаже).

        Формат работы overlay берём ПО ИСХОДНИКУ (см. overlay_chroma_format):
        при `format=auto` граф с RGBA-накладкой уводил ВЕСЬ кадр в RGB, libx264
        писал gbrp — и итог получался кислотно-зелёным/малиновым."""
    rendered = self._render_export_overlays()
    if not rendered:
        return chain or ""
    return _api.overlay_filter_graph(chain or "", rendered,
                                self._escape_filter_path,
                                pix_fmt=self._overlay_pix_fmt(src))

def _overlay_pix_fmt(self, src=None):
    """Значение `format=` для overlay под pix_fmt исходника (кэшируется на
        файл: ffprobe на каждый экспорт тут ни к чему)."""
    path = str(src or getattr(self, "actual_source_file", "") or "")
    if not path or not _api.os.path.exists(path):
        return "yuv420"
    cache = getattr(self, "_ovl_fmt_cache", None)
    if cache is None:
        cache = self._ovl_fmt_cache = {}
    stamp = self._file_cache_stamp(path)
    key = (path, stamp)
    got = cache.get(key)
    if got is None:
        got = cache[key] = _api.overlay_chroma_format(_api.get_pix_fmt(path))
    return got

@staticmethod
def _apply_frame_crop(img, n):
    """Обрезает QImage по нормализованной рамке n (QRectF 0..1). Координаты
        зажимаются в границы изображения."""
    if img is None or img.isNull() or n is None:
        return img
    w, h = img.width(), img.height()
    x = max(0, min(w - 1, int(round(n.left() * w))))
    y = max(0, min(h - 1, int(round(n.top() * h))))
    cw = max(1, min(w - x, int(round(n.width() * w))))
    ch = max(1, min(h - y, int(round(n.height() * h))))
    return img.copy(x, y, cw, ch)

# ── Сохранение текущего кадра ────────────────────────────────────────────
def save_frame(self):
    """Сохраняет кадр на текущей позиции воспроизведения в PNG (полное
        разрешение, извлекается из исходника через ffmpeg). Без диалога —
        файл сразу кладётся в папку сохранения (или рядом с исходником)."""
    src = self.actual_source_file or self.filepath
    if not src or not _api.os.path.exists(src) or self.duration <= 0:
        return
    # Рамка кадрирования (если задана на холсте) — сохраняем только её.
    crop_n = None
    _vw = getattr(self, "video_widget", None)
    if isinstance(_vw, _api.VideoCanvas):
        crop_n = _vw.crop_norm()
    # Время кадра, который на экране (см. _clock_pos_s) — им же назван файл,
    # и по нему же идёт резервное извлечение через ffmpeg.
    pos = max(0.0, self._clock_pos_s())
    base = _api.os.path.splitext(_api.os.path.basename(src))[0]
    stamp = _api.s_to_time(pos).replace(':', '-').replace('.', '_')
    save_dir = (self.export_dir if (self.export_dir and _api.os.path.isdir(self.export_dir))
                else _api.os.path.dirname(src))
    fname = _api._unique_output(_api.os.path.join(save_dir, f"{base}_{stamp}.png"))
    ok = False
    # 1) В painted-режиме (VideoCanvas) сохраняем РОВНО тот кадр, что показан
    #    на холсте — без пере-извлечения через ffmpeg. Иначе seek по позиции
    #    на HEVC отдавал следующий кадр (out_time приходился между кадрами →
    #    ffmpeg брал первый PTS ≥ позиции = следующий).
    # (Если активен превью-прокси, кадр на холсте уменьшён — тогда лучше
    #  полноразмерный кадр из оригинала через ffmpeg, см. ниже.)
    if isinstance(self.video_widget, _api.VideoCanvas) and not self.is_proxy_active:
        try:
            img = self.video_widget.current_frame_image()
            if img is not None and not img.isNull():
                img = self._paint_overlays_on_image(img)
                if crop_n is not None:
                    img = self._apply_frame_crop(img, crop_n)
                ok = bool(img.save(fname, "PNG"))
        except Exception:
            ok = False
    # 2) Резерв (overlay-режим / нет кадра на холсте): извлекаем через ffmpeg.
    #    -ss перед -i точен, но позиция может прийтись между кадрами; вычитаем
    #    половину интервала кадра, чтобы попасть в текущий, а не следующий.
    if not ok:
        # Целимся четвертью кадра НИЖЕ его pts: ffmpeg отдаёт первый кадр с
        # pts ≥ -ss, значит это ровно наш кадр (см. FrameGrid.seek_of).
        if self._grid.valid:
            seek = self._grid.seek_of(self._grid.index_at(pos))
        else:
            seek = max(0.0, pos - 0.02)
        cmd = [_api.FFMPEG, "-y", "-ss", f"{seek:.3f}", "-i", src,
               "-frames:v", "1", "-update", "1", fname]
        kw = {}
        if _api.os.name == 'nt':
            kw['creationflags'] = _api.CREATE_NO_WINDOW
        try:
            r = _api.subprocess.run(cmd, stdout=_api.subprocess.DEVNULL,
                               stderr=_api.subprocess.DEVNULL, timeout=60, **kw)
            ok = (r.returncode == 0 and _api.os.path.exists(fname)
                  and _api.os.path.getsize(fname) > 0)
        except Exception:
            ok = False
        # Полноразмерный кадр из ffmpeg обрезаем под рамку кадрирования.
        if ok and (crop_n is not None or self.has_image_overlays()):
            try:
                _qi = _api.QImage(fname)
                if not _qi.isNull():
                    _qi = self._paint_overlays_on_image(_qi)
                    if crop_n is not None:
                        _qi = self._apply_frame_crop(_qi, crop_n)
                    _qi.save(fname, "PNG")
            except Exception:
                pass
    msg = (f"🖼 Кадр сохранён: {_api.os.path.basename(fname)}" if ok
           else "Не удалось сохранить кадр")
    try:
        if self.main is not None and hasattr(self.main, "log"):
            self.main.log(msg)
    except Exception:
        pass
    try:
        gp = self.btn_save_frame.mapToGlobal(
            _api.QPoint(0, -self.btn_save_frame.height()))
        _api.QToolTip.showText(gp, msg, self.btn_save_frame)
    except Exception:
        pass

# ── Удаление объекта с видео (LaMa, покадрово) ───────────────────────────
def _ensure_inpainter(self):
    """Лениво создаёт движок LaMa (ТОТ ЖЕ, что в фоторедакторе) и
        переиспользует его между запусками. Сессия живёт в дочернем процессе
        (см. lama_inpaint.py), поэтому загрузка 200-МБ модели не морозит UI."""
    inp = getattr(self, "_inpainter", None)
    if inp is not None:
        return inp
    try:
        from lama_inpaint import LaMaProcessInpainter
    except Exception:
        return None
    self._inpainter = LaMaProcessInpainter()
    return self._inpainter

def _grab_source_frame_bgr(self, src):
    """Извлекает кадр оригинала на текущей позиции воспроизведения в ПОЛНОМ
        разрешении (через ffmpeg) и возвращает numpy BGR. Способ совпадает с тем,
        как VideoInpaintWorker позже извлечёт все кадры, поэтому нарисованная маска
        попадает в кадры попиксельно (то же разрешение и дисплейная ориентация)."""
    pos = max(0.0, self._clock_pos_s())
    # -ss перед -i точен, но позиция может прийтись между кадрами — целимся
    # четвертью кадра ниже pts нужного кадра (см. FrameGrid.seek_of), иначе
    # ffmpeg отдаст СЛЕДУЮЩИЙ кадр и маска ляжет не на тот кадр.
    if self._grid.valid:
        seek = self._grid.seek_of(self._grid.index_at(pos))
    else:
        seek = max(0.0, pos - 0.02)
    tmp = _api.os.path.join(_api.tempfile.gettempdir(),
                       f"sihyx_vmask_{_api.os.getpid()}_{int(_api.time.time() * 1000)}.png")
    cmd = [_api.FFMPEG, "-y", "-ss", f"{seek:.3f}", "-i", src,
           "-frames:v", "1", "-update", "1", tmp]
    kw = {}
    if _api.os.name == 'nt':
        kw['creationflags'] = _api.CREATE_NO_WINDOW
    try:
        r = _api.subprocess.run(cmd, stdout=_api.subprocess.DEVNULL,
                           stderr=_api.subprocess.DEVNULL, timeout=60, **kw)
        if r.returncode != 0 or not _api.os.path.exists(tmp):
            return None
        from lama_inpaint import load_bgr
        return load_bgr(tmp)
    except Exception:
        return None
    finally:
        try:
            if _api.os.path.exists(tmp):
                _api.os.remove(tmp)
        except Exception:
            pass
