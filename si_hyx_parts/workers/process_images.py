# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Обработка: картинки и AVIF с подбором качества под предел размера."""
import workers as _api


class ProcessImagesMixin:
    """Обработка: картинки и AVIF с подбором качества под предел размера."""

    @staticmethod
    def _pil_has_alpha(im) -> bool:
        """True только если в уже открытом PIL.Image есть реальная прозрачность."""
        if im.mode == 'P' and 'transparency' in im.info:
            return True
        if im.mode in ('LA', 'PA', 'La', 'RGBa'):
            return True
        if im.mode == 'RGBA':
            return im.getchannel('A').getextrema()[0] < 255
        return False

    @staticmethod
    def _normalize_16bit_pil(im):
        """16-битный серый (I;16/I) → 8-битный L без обрезки в белый."""
        if im.mode.startswith('I;16'):
            return im.point(lambda x: x >> 8, 'L')
        if im.mode == 'I':
            lo, hi = im.getextrema()
            if hi > 255:
                scale = 255.0 / max(1, hi - lo)
                return im.point(lambda x, _lo=lo, _sc=scale: int((x - _lo) * _sc), 'L')
            return im.convert('L')
        return im

    @staticmethod
    def _commit_output_file(src_tmp: str, out_path: str):
        """Атомарно переносит готовый временный файл в out_path через временный
        файл в целевой папке + os.replace. Если копирование сорвётся (другой
        диск, нет места), исходный out_path остаётся нетронутым."""
        if not (_api.os.path.exists(src_tmp) and _api.os.path.getsize(src_tmp) > 0):
            raise Exception("Результат конвертации пуст или не создан.")
        out_dir = _api.os.path.dirname(_api.os.path.abspath(out_path)) or "."
        ext = _api.os.path.splitext(out_path)[1]
        staged = _api.os.path.join(out_dir, f".sihyx_tmp_{_api.uuid.uuid4().hex}{ext}")
        try:
            _api.shutil.copy2(src_tmp, staged)
            if not (_api.os.path.exists(staged) and _api.os.path.getsize(staged) > 0):
                raise Exception("Не удалось записать итоговый файл (пустой файл).")
            _api.os.replace(staged, out_path)
        except Exception:
            try:
                if _api.os.path.exists(staged):
                    _api.os.remove(staged)
            except Exception:
                pass
            raise
        try:
            if _api.os.path.exists(src_tmp):
                _api.os.remove(src_tmp)
        except Exception:
            pass

    @staticmethod
    def _save_pil_atomic(img, out_path: str, **save_kw):
        """Сохраняет PIL.Image во временный файл рядом с out_path и атомарно
        подменяет через os.replace — исходник не портится при ошибке записи."""
        out_dir = _api.os.path.dirname(_api.os.path.abspath(out_path)) or "."
        ext = _api.os.path.splitext(out_path)[1]
        staged = _api.os.path.join(out_dir, f".sihyx_tmp_{_api.uuid.uuid4().hex}{ext}")
        try:
            img.save(staged, **save_kw)
            if not (_api.os.path.exists(staged) and _api.os.path.getsize(staged) > 0):
                raise Exception("Не удалось сохранить изображение (пустой файл).")
            _api.os.replace(staged, out_path)
        except Exception:
            try:
                if _api.os.path.exists(staged):
                    _api.os.remove(staged)
            except Exception:
                pass
            raise

    def _search_quality_under_limit(self, save_to_tmp, limit_kb, passes, q_lo=10, q_hi=95,
                                    on_pass=None, cancel_check=None, return_best_file=False):
        """Бинарный поиск макс. quality (q_lo..q_hi), при котором размер файла ≤ limit_kb.
        save_to_tmp(q) -> путь к временному файлу.
        passes — число проб (1..8). on_pass(n, total) — колбэк прогресса подбора.
        При return_best_file=False возвращает выбранное quality (int) и удаляет все
        временные файлы. При return_best_file=True возвращает
        (chosen_q, best_tmp, best_size_kb, found), сохраняя лучший временный файл
        (удалить/перенести его обязан вызывающий)."""
        passes = max(1, min(8, int(passes or 4)))
        lo, hi = int(q_lo), int(q_hi)
        chosen, found, n = q_lo, False, 0
        best_tmp, best_size_kb = None, None
        smallest_tmp, smallest_size_kb, smallest_q = None, None, q_lo

        def _rm(p):
            if p:
                try:
                    if _api.os.path.exists(p):
                        _api.os.remove(p)
                except Exception:
                    pass

        try:
            while lo <= hi and n < passes:
                if self.stop_flag or (cancel_check is not None and cancel_check()):
                    raise Exception("StoppedByUser")
                n += 1
                if on_pass:
                    try:
                        on_pass(n, passes)
                    except Exception:
                        pass
                mid = (lo + hi) // 2
                tmp = save_to_tmp(mid)
                size_kb = max(1, _api.os.path.getsize(tmp) // 1024)
                fits = size_kb <= limit_kb
                if return_best_file:
                    if fits:
                        _rm(best_tmp)
                        best_tmp, best_size_kb = tmp, size_kb
                    else:
                        if smallest_size_kb is None or size_kb < smallest_size_kb:
                            _rm(smallest_tmp)
                            smallest_tmp, smallest_size_kb, smallest_q = tmp, size_kb, mid
                        else:
                            _rm(tmp)
                else:
                    _rm(tmp)
                if fits:
                    chosen, found, lo = mid, True, mid + 1
                else:
                    hi = mid - 1
        except Exception:
            _rm(best_tmp)
            _rm(smallest_tmp)
            raise

        if not return_best_file:
            return chosen if found else q_lo

        if found:
            _rm(smallest_tmp)
            return chosen, best_tmp, best_size_kb, True
        _rm(best_tmp)
        return smallest_q, smallest_tmp, smallest_size_kb, False

    def _convert_simple_image(self, item, src_path, out_dir, sanitized, adim, av, fmt, cb,
                              *, pil_im=None, icc=None, overwrite_src=None):
        """Конвертация изображения в png / jpg / ico / webp через Pillow (без ffmpeg).
        Учитывает лимит разрешения (adim) и для jpg/webp/png — лимит размера файла.
        """
        if not _api.Image:
            raise Exception("Pillow (PIL) не установлен — конвертация в этот формат недоступна.")
        iid = item['iid']
        cancel_check = lambda: self._is_cancelled(iid)
        self._check_cancelled(iid)

        fmt = fmt.lower()
        ext = {'jpeg': 'jpg', 'jpg': 'jpg', 'png': 'png', 'ico': 'ico', 'webp': 'webp'}.get(fmt, fmt)
        ow_flag = bool(av.get('overwrite_src')) if overwrite_src is None else bool(overwrite_src)
        suffix = "" if ow_flag else "_Сжатый"
        orig_path = item.get('path') or src_path
        out_path = _api._reserve_out_path(
            self, out_dir, sanitized, suffix, f".{ext}", orig_path,
            allow_overwrite_src=ow_flag)

        def _on_pass(n, total):
            cb(int((n - 1) / total * 100), f"Конвертация картинки {n}/{total}")

        cb(0, "Конвертация картинки")

        owned_im = None
        try:
            if pil_im is not None:
                im = pil_im
            else:
                owned_im = _api.Image.open(src_path)
                if getattr(owned_im, 'n_frames', 1) > 1:
                    self.log.emit(
                        f"⚠ Анимированное изображение ({owned_im.n_frames} кадров) пропущено "
                        f"(исходник не изменён): {_api.os.path.basename(orig_path)}")
                    item['_skipped_anim'] = True
                    cb(100, "Пропущено (анимация)")
                    return orig_path
                icc = owned_im.info.get('icc_profile')
                im = owned_im
                if _api.ImageOps:
                    orient = 1
                    try:
                        orient = im.getexif().get(0x0112, 1)
                    except Exception:
                        orient = 1
                    if orient != 1:
                        im = _api.ImageOps.exif_transpose(im)

            self._check_cancelled(iid)
            im = self._normalize_16bit_pil(im)
            had_alpha = self._pil_has_alpha(im)

            # JPEG не поддерживает альфу — кладём на белую подложку вместо чёрной.
            if ext == 'jpg':
                if had_alpha:
                    rgba = im.convert('RGBA')
                    bg = _api.Image.new('RGB', rgba.size, (255, 255, 255))
                    bg.paste(rgba, mask=rgba.getchannel('A'))
                    im = bg
                else:
                    im = im.convert('RGB')
            elif ext == 'ico':
                im = im.convert('RGBA')
            elif ext == 'webp':
                im = im.convert('RGBA') if had_alpha else im.convert('RGB')
            else:  # png
                im = im.convert('RGBA') if had_alpha else im.convert('RGB')

            # Лимит разрешения; для ICO жёсткий потолок 256px
            awidth = av.get('awidth', 0) or 0
            aheight = av.get('aheight', 0) or 0
            if ext == 'ico':
                cap = min(256, adim) if (adim and adim > 0) else 256
                if max(im.width, im.height) > cap:
                    sc = cap / max(im.width, im.height)
                    im = im.resize((max(1, int(im.width * sc)), max(1, int(im.height * sc))), _api.Image.LANCZOS)
            else:
                tgt = self._target_dims(im.width, im.height, adim, awidth, aheight)
                if tgt:
                    im = im.resize(tgt, _api.Image.LANCZOS)

            self._check_cancelled(iid)
            limit_kb = int(av.get('limit', 0) or 0) if av.get('limit_on', True) else 0
            if limit_kb <= 0:
                cb(55, "Конвертация картинки")

            icc_kw = {'icc_profile': icc} if icc else {}

            if ext == 'ico':
                side = max(im.width, im.height)
                if im.width != im.height:
                    canvas = _api.Image.new("RGBA", (side, side), (0, 0, 0, 0))
                    canvas.paste(im, ((side - im.width) // 2, (side - im.height) // 2))
                    im = canvas
                cand = [16, 24, 32, 48, 64, 128, 256]
                sizes = [(s, s) for s in cand if s <= side] or [(side, side)]
                self._save_pil_atomic(im, out_path, format='ICO', sizes=sizes)
            elif ext in ('jpg', 'webp', 'png'):
                def _save_kwargs(q, _ext=ext):
                    if _ext == 'jpg':
                        return dict(format='JPEG', quality=q, optimize=True, **icc_kw)
                    if _ext == 'webp':
                        return dict(format='WEBP', quality=q, method=6, **icc_kw)
                    return dict(format='PNG', optimize=True, **icc_kw)

                def _mk_tmp(img, q, _ext=ext):
                    self._check_cancelled(iid)
                    t = _api.os.path.join(_api.TEMP_DIR, f"{_ext}_{_api.uuid.uuid4().hex}.{_ext}")
                    img.save(t, **_save_kwargs(q, _ext))
                    return t

                if limit_kb <= 0:
                    self._save_pil_atomic(im, out_path, **_save_kwargs({'jpg': 92, 'webp': 90}.get(ext, 0)))
                else:
                    q_lo, q_hi = 10, 95
                    passes = av.get('fit_passes', 4)
                    cur = im
                    saved = False
                    for attempt in range(6):
                        self._check_cancelled(iid)
                        if ext == 'png':
                            t = _mk_tmp(cur, 0)
                            size_kb = max(1, _api.os.path.getsize(t) // 1024)
                            if size_kb <= limit_kb:
                                self._commit_output_file(t, out_path)
                                saved = True
                                break
                            try:
                                _api.os.remove(t)
                            except Exception:
                                pass
                        else:
                            chosen, best_tmp, size_kb, fits = self._search_quality_under_limit(
                                lambda q, _im=cur: _mk_tmp(_im, q), limit_kb, passes,
                                q_lo=q_lo, q_hi=q_hi,
                                on_pass=_on_pass if attempt == 0 else None,
                                cancel_check=cancel_check,
                                return_best_file=True)
                            if fits and best_tmp:
                                self._commit_output_file(best_tmp, out_path)
                                saved = True
                                break
                            # Не влезло: замеряем q_lo только если в поиске его ещё не пробовали.
                            if chosen != q_lo or best_tmp is None:
                                if best_tmp:
                                    try:
                                        _api.os.remove(best_tmp)
                                    except Exception:
                                        pass
                                t_lo = _mk_tmp(cur, q_lo)
                                size_kb = max(1, _api.os.path.getsize(t_lo) // 1024)
                                if size_kb <= limit_kb:
                                    self._commit_output_file(t_lo, out_path)
                                    saved = True
                                    break
                                try:
                                    _api.os.remove(t_lo)
                                except Exception:
                                    pass
                            else:
                                try:
                                    _api.os.remove(best_tmp)
                                except Exception:
                                    pass
                        # Не влезли даже на минимальном качестве → уменьшаем сторону.
                        if attempt == 0:
                            side = self._avif_downscale_side(cur.width, cur.height,
                                                             size_kb or limit_kb * 2, limit_kb)
                        else:
                            side = int(max(cur.width, cur.height) * 0.85)
                        side = max(16, min(side, max(cur.width, cur.height) - 1))
                        sc = side / max(cur.width, cur.height)
                        cur = cur.resize((max(1, int(cur.width * sc)),
                                          max(1, int(cur.height * sc))), _api.Image.LANCZOS)
                        self.log.emit(
                            f"{ext.upper()}: лимит {limit_kb} КБ не достигнут "
                            f"({size_kb} КБ) → уменьшаю до {cur.width}x{cur.height}")
                    if not saved:
                        self._check_cancelled(iid)
                        self._save_pil_atomic(cur, out_path, **_save_kwargs(q_lo if ext != 'png' else 0))
        finally:
            if owned_im is not None:
                try:
                    owned_im.close()
                except Exception:
                    pass

        cb(100, "Конвертация картинки")
        try:
            self.update_item_sig.emit(item['iid'], _api.human_size(_api.os.path.getsize(out_path)), "-")
        except Exception:
            pass
        return out_path

    def _avif_prepare_input(self, path):
        """Готовит вход для AVIF-конвейера → (path, rot_tmp_file, ширина, высота).

        Авто-поворот по EXIF делается ТОЛЬКО когда тег ориентации != 1:
        exif_transpose всегда возвращает копию, поэтому без проверки тега
        каждая картинка лишний раз сохранялась в PNG во TEMP."""
        rot_tmp_file = None
        orig_w, orig_h = 0, 0
        try:
            if _api.Image and _api.ImageOps:
                with _api.Image.open(path) as im:
                    orient = 1
                    try:
                        orient = im.getexif().get(0x0112, 1)
                    except Exception:
                        orient = 1
                    if orient != 1:
                        icc = im.info.get('icc_profile')
                        im_t = _api.ImageOps.exif_transpose(im)
                        orig_w, orig_h = im_t.size
                        tmp_rot = _api.os.path.join(_api.TEMP_DIR, f"rot_{_api.uuid.uuid4().hex}.png")
                        im_t.save(tmp_rot, **({'icc_profile': icc} if icc else {}))
                        path = tmp_rot
                        rot_tmp_file = tmp_rot
                    else:
                        orig_w, orig_h = im.size
        except Exception as e:
            self.log.emit(f"EXIF rotation notice: {e}")

        if not orig_w:
            try:
                p = _api.subprocess.run(
                    [_api.FFPROBE, "-v", "error", "-select_streams", "v:0",
                     "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", path],
                    stdout=_api.subprocess.PIPE, stderr=_api.subprocess.DEVNULL,
                    text=True, encoding="utf-8", errors="replace",
                    creationflags=_api.CREATE_NO_WINDOW)
                parts = _api.csv_fields(p.stdout, 'x')
                if len(parts) >= 2:
                    orig_w, orig_h = int(parts[0]), int(parts[1])
            except Exception:
                pass

        return path, rot_tmp_file, orig_w, orig_h

    def _strip_ai_watermarks_pil(self, im, orig_path, raw_name, av):
        """Ищет и снимает вотермарки Gemini и Meta AI на уже открытом PIL.Image,
        сканируя только правый нижний угол (без декодирования всей картинки в numpy).
        Возвращает (im, removed_list)."""
        if not av.get('gemini_wm', True) or im is None:
            return im, []
        try:
            import numpy as np
            import gemini_watermark
            import meta_watermark
            if gemini_watermark.cv2 is None and meta_watermark.cv2 is None:
                return im, []
            w, h = im.size
            if min(w, h) < 120:
                return im, []
            # Правый нижний угол достаточен и для Gemini (до scale 3.0 → ~475 px),
            # и для Meta AI (45% ширины / 28% высоты, но не меньше 400×120).
            cw = min(w, max(720, int(w * 0.45)))
            ch = min(h, max(720, int(h * 0.30)))
            cx0, cy0 = w - cw, h - ch
            corner = im.crop((cx0, cy0, w, h))
            has_alpha = self._pil_has_alpha(im)
            arr = np.asarray(corner.convert('RGBA' if has_alpha else 'RGB'))
            removed = []
            if gemini_watermark.cv2 is not None and min(cw, ch) >= 160:
                found = gemini_watermark.find_watermark(
                    arr, hint=raw_name.startswith('Gemini_Generated_Image'))
                if found:
                    arr = gemini_watermark.remove_watermark(arr, found)
                    removed.append('Gemini')
            if meta_watermark.cv2 is not None:
                found = meta_watermark.find_watermark(arr, search_all=True)
                if found:
                    lama = self._meta_inpainter()
                    try:
                        arr = meta_watermark.remove_watermark(arr, found, lama)
                    except Exception as e:
                        if lama is None:
                            raise
                        self.log.emit(f"LaMa не сработала ({e}), знак Meta AI "
                                      "залит по соседям")
                        self._meta_lama = False
                        arr = meta_watermark.remove_watermark(arr, found)
                    removed.append('Meta AI')
            if not removed:
                return im, []
            base_im = im.convert('RGBA' if has_alpha else 'RGB')
            base_im.paste(_api.Image.fromarray(arr), (cx0, cy0))
            self.log.emit(f"Вотермарка {' и '.join(removed)} снята: {_api.os.path.basename(orig_path)}")
            return base_im, removed
        except Exception as e:
            self.log.emit(f"Вотермарки не сняты ({_api.os.path.basename(orig_path)}): {e}")
            return im, []

    def _strip_ai_watermarks(self, path, raw_name, av, tmp_files):
        """Совместимая обёртка снятия вотермарок по пути к файлу."""
        if not av.get('gemini_wm', True) or not (_api.Image and _api.ImageOps):
            return path
        try:
            with _api.Image.open(path) as src:
                if getattr(src, 'n_frames', 1) > 1:
                    return path
                icc = src.info.get('icc_profile')
                orient = 1
                try:
                    orient = src.getexif().get(0x0112, 1)
                except Exception:
                    orient = 1
                im = _api.ImageOps.exif_transpose(src) if orient != 1 else src
                im_clean, removed = self._strip_ai_watermarks_pil(im, path, raw_name, av)
                if not removed:
                    return path
                tmp = _api.os.path.join(_api.TEMP_DIR, f"ai_wm_{_api.uuid.uuid4().hex}.png")
                im_clean.save(tmp, **({'icc_profile': icc} if icc else {}))
                tmp_files.append(tmp)
                return tmp
        except Exception as e:
            self.log.emit(f"Вотермарки не сняты ({_api.os.path.basename(path)}): {e}")
            return path

    def _meta_inpainter(self):
        """LaMa для знака Meta AI или None, если модели нет или она уже
        отказала в этом запуске. Сессия ONNX живёт в дочернем процессе:
        её сборка держит GIL ~20 с и заморозила бы окно. Один на запуск,
        выгружается в конце run()."""
        with self._meta_lama_lock:
            if self._meta_lama is None:
                self._meta_lama = False
                try:
                    import lama_inpaint
                    lama = lama_inpaint.LaMaProcessInpainter()
                    if lama.is_available():
                        self._meta_lama = lama
                except Exception:
                    pass
            return self._meta_lama or None

    def process_avif(self, item, cb):
        # Временные PNG (поворот/вотермарки/HEIC) чистятся гарантированно в finally.
        tmp_files = []
        try:
            return self._process_image_item(item, cb, tmp_files)
        finally:
            for t in tmp_files:
                try:
                    if _api.os.path.exists(t):
                        _api.os.remove(t)
                except Exception:
                    pass

    def _process_image_item(self, item, cb, tmp_files):
        iid = item['iid']
        self._check_cancelled(iid)
        path = item['path']
        base, ext = _api.os.path.splitext(path)
        ext_low = ext.lower()

        # Пропускаем файлы, которые сами являются результатом предыдущей конвертации
        if _api.os.path.basename(base).endswith("_Сжатый"):
            self.log.emit(f"Пропущен уже обработанный файл: {_api.os.path.basename(path)}")
            cb(100, "Пропущен")
            return path
        out_dir = self._out_dir_for(path)
        orig_path = path
        av = self.settings.get('avif', {})
        ow_flag = (bool(item['_overwrite_src']) if '_overwrite_src' in item
                   else bool(av.get('overwrite_src')))
        adim = av.get('adim', 0) or 0
        aspd = av.get('aspd', 0)
        raw_name = _api.os.path.basename(base)
        sanitized = self._sanitize_name(raw_name)
        if sanitized != raw_name:
            self.log.emit(f"Имя переименовано (AI-бренд): «{raw_name}» → «{sanitized}»")
        suffix = "" if ow_flag else "_Сжатый"
        img_fmt = (av.get('img_fmt') or 'avif').lower()

        # Единожды открываем картинку в Pillow: проверяем анимацию, EXIF-поворот,
        # альфу, ICC-профиль и снимаем вотермарки в кропе угла.
        pil_opened = None
        pil_im = None
        icc = None
        orig_w, orig_h = 0, 0
        has_alpha = None
        orient = 1
        wm_removed = []

        try:
            if _api.Image:
                try:
                    pil_opened = _api.Image.open(orig_path)
                    n_frames = getattr(pil_opened, 'n_frames', 1)
                    if n_frames > 1:
                        self.log.emit(
                            f"⚠ Анимированное изображение ({n_frames} кадров) пропущено "
                            f"(исходник не изменён): {_api.os.path.basename(orig_path)}")
                        item['_skipped_anim'] = True
                        cb(100, "Пропущено (анимация)")
                        return orig_path
                    icc = pil_opened.info.get('icc_profile')
                    try:
                        orient = pil_opened.getexif().get(0x0112, 1)
                    except Exception:
                        orient = 1
                    pil_im = (_api.ImageOps.exif_transpose(pil_opened)
                              if (_api.ImageOps and orient != 1) else pil_opened)
                    orig_w, orig_h = pil_im.size
                    has_alpha = self._pil_has_alpha(pil_im)
                    self._check_cancelled(iid)
                    pil_im, wm_removed = self._strip_ai_watermarks_pil(
                        pil_im, orig_path, raw_name, av)
                except Exception as e:
                    if "StoppedByUser" in str(e):
                        raise
                    pil_im = None

            self._check_cancelled(iid)

            # Бюджет пикселей для параллельного пула: не даём нескольким 24+ Мп
            # картинкам одновременно сжечь память и CPU.
            px_budget = self._acquire_pixel_budget(orig_w * orig_h, iid)
            try:
                # Выбранный пользователем формат: png/jpg/ico/webp обрабатываем через Pillow
                if img_fmt in ('png', 'jpg', 'jpeg', 'ico', 'webp'):
                    self.log.emit(f"Формат изображения: {img_fmt.upper()}")
                    return self._convert_simple_image(
                        item, path, out_dir, sanitized, adim, av, img_fmt, cb,
                        pil_im=pil_im, icc=icc, overwrite_src=ow_flag)

                if 'libaom-av1' not in _api.detect_ffmpeg_encoders():
                    raise Exception(
                        "libaom-av1 не доступен в вашей сборке ffmpeg — AVIF перекодирование "
                        "настроено работать ТОЛЬКО через libaom (libaom-av1).")

                # Пишем временный PNG только когда это реально нужно:
                # есть EXIF-поворот, снята вотермарка или формат, который ffmpeg
                # не читает напрямую (HEIC/HEIF/ICO). Обычные PNG/JPG/WebP/AVIF
                # идут в ffmpeg напрямую без rot_*.png!
                need_png = (pil_im is not None and (
                    orient != 1 or bool(wm_removed)
                    or ext_low in ('.heic', '.heif', '.hif', '.ico')))
                if need_png:
                    tmp_in = _api.os.path.join(_api.TEMP_DIR, f"img_in_{_api.uuid.uuid4().hex}.png")
                    pil_im.save(tmp_in, **({'icc_profile': icc} if icc else {}))
                    tmp_files.append(tmp_in)
                    path = tmp_in
                elif not orig_w:
                    path, rot_tmp, orig_w, orig_h = self._avif_prepare_input(path)
                    if rot_tmp:
                        tmp_files.append(rot_tmp)

                out = _api._reserve_out_path(
                    self, out_dir, sanitized, suffix, ".avif", orig_path,
                    allow_overwrite_src=ow_flag)

                if orig_w * orig_h > 8500000:
                    if aspd < 6:
                        aspd = 6

                awidth = av.get('awidth', 0) or 0
                aheight = av.get('aheight', 0) or 0
                vf = None
                _tgt = self._target_dims(orig_w, orig_h, adim, awidth, aheight)
                if _tgt:
                    vf = f"scale={_tgt[0]}:{_tgt[1]}"
                elif (adim and adim > 0) and not (orig_w and orig_h):
                    vf = f"scale=if(gte(iw\\,ih)\\,{adim}\\,-2):if(gt(ih\\,iw)\\,{adim}\\,-2)"

                if has_alpha is None:
                    has_alpha = self._source_has_alpha(path)
                pix_fmt_avif = self._avif_pix_fmt(has_alpha, av.get('chroma', '420'))

                if has_alpha and _api.os.path.exists(out) and not _api._same_path(out, orig_path):
                    try:
                        _api.os.remove(out)
                    except Exception:
                        pass

                tried_tmp_files = []

                def _cleanup(files):
                    for t in list(files):
                        try:
                            if _api.os.path.exists(t):
                                _api.os.remove(t)
                        except Exception:
                            pass

                def _alpha_webp_fallback():
                    self._check_cancelled(iid)
                    self.log.emit("AVIF с альфой не удался → резерв: WebP (RGBA)")
                    cb(0, "Конвертация картинки")

                    def _on_pass_a(n, total):
                        cb(int((n - 1) / total * 100), f"Конвертация картинки {n}/{total}")

                    icc_kw_a = {'icc_profile': icc} if icc else {}
                    if pil_im is not None:
                        im_a = pil_im.convert('RGBA')
                    else:
                        with _api.Image.open(path) as _im:
                            im_a = _im.convert('RGBA')
                    _tgt_a = self._target_dims(im_a.width, im_a.height, adim,
                                               av.get('awidth', 0) or 0, av.get('aheight', 0) or 0)
                    if _tgt_a:
                        im_a = im_a.resize(_tgt_a, _api.Image.LANCZOS)

                    out_webp = _api._reserve_out_path(
                        self, out_dir, sanitized, suffix, ".webp", orig_path,
                        allow_overwrite_src=ow_flag)
                    limit_kb_l = int(av.get('limit', 0) or 0)

                    if limit_kb_l > 0:
                        def _save_webp_a(q):
                            self._check_cancelled(iid)
                            t = _api.os.path.join(_api.TEMP_DIR, f"wp_{_api.uuid.uuid4().hex}.webp")
                            im_a.save(t, format="WEBP", quality=q, lossless=False, **icc_kw_a)
                            return t
                        chosen_q, best_wp, _, fits_wp = self._search_quality_under_limit(
                            _save_webp_a, limit_kb_l, av.get('fit_passes', 4), q_lo=10, q_hi=85,
                            on_pass=_on_pass_a,
                            cancel_check=lambda: self._is_cancelled(iid),
                            return_best_file=True)
                        if fits_wp and best_wp:
                            self._commit_output_file(best_wp, out_webp)
                        else:
                            if best_wp:
                                try:
                                    _api.os.remove(best_wp)
                                except Exception:
                                    pass
                            self._check_cancelled(iid)
                            self._save_pil_atomic(
                                im_a, out_webp, format="WEBP", quality=chosen_q,
                                lossless=False, **icc_kw_a)
                    else:
                        cb(50, "Конвертация картинки")
                        self._check_cancelled(iid)
                        self._save_pil_atomic(
                            im_a, out_webp, format="WEBP", quality=85,
                            lossless=False, **icc_kw_a)

                    cb(100, "Конвертация картинки")
                    size_new = _api.os.path.getsize(out_webp)
                    self.update_item_sig.emit(item['iid'], _api.human_size(size_new), "-")
                    _cleanup(tried_tmp_files)
                    if (_api.os.path.exists(out) and not _api._same_path(out, out_webp)
                            and not _api._same_path(out, orig_path)):
                        try:
                            _api.os.remove(out)
                        except Exception:
                            pass
                    return out_webp

                limit_kb = int(av.get('limit', 0) or 0)
                if has_alpha:
                    self.log.emit("Альфа-канал обнаружен → AVIF с прозрачностью (alphaextract, libaom-av1, tune=IQ)")
                else:
                    self.log.emit("AVIF: libaom-av1, tune=IQ, 10-бит")

                _limit_on = bool(limit_kb and limit_kb > 0)
                total_passes = max(1, min(8, int(av.get('fit_passes', 4)))) if _limit_on else 1
                pass_state = {'n': 0}

                def _pass_cb(pct, _label=None):
                    total = total_passes
                    nn = min(pass_state['n'], total) or 1
                    overall = int(((nn - 1) + pct / 100.0) / total * 100) if total > 0 else pct
                    overall = max(0, min(100, overall))
                    if total > 1:
                        cb(overall, f"Конвертация картинки {nn}/{total}")
                    else:
                        cb(overall, "Конвертация картинки")

                aom_threads = getattr(self, '_img_aom_threads', 0)

                def _encode_to(tmp_out, crf_val, vf_override=None):
                    self._check_cancelled(iid)
                    pass_state['n'] += 1
                    cmd = self._avif_encode_cmd(
                        path, tmp_out, crf_val,
                        vf_override if vf_override is not None else vf,
                        has_alpha, pix_fmt_avif, aspd,
                        size=(orig_w, orig_h) if (orig_w and orig_h) else None,
                        threads=aom_threads)
                    orig_size = _api.os.path.getsize(path) if _api.os.path.exists(path) else 1
                    est_seconds = max(1, int(orig_size / 400_000))

                    def _try(c):
                        try:
                            self.run_ffmpeg_capture(
                                c, est_seconds, _pass_cb,
                                cancel_check=lambda: item["iid"] in self.removed_ids)
                            return True, None
                        except _api.subprocess.CalledProcessError as e:
                            return False, (e.stderr[:4000] if hasattr(e, 'stderr') else str(e))
                        except Exception as e:
                            if "StoppedByUser" in str(e) or self._is_cancelled(iid):
                                raise Exception("StoppedByUser")
                            return False, str(e)

                    ok, err = _try(cmd)
                    if ok:
                        return True, None
                    self._check_cancelled(iid)
                    plain = _api.strip_allintra(cmd)
                    if plain != cmd:
                        ok2, err2 = _try(plain)
                        if ok2:
                            self.log.emit("ffmpeg не знает -usage allintra — кодирую без него")
                            return True, None
                        return False, err2 or err
                    return False, err

                if not limit_kb or limit_kb <= 0:
                    tmp = _api.os.path.join(_api.TEMP_DIR, f"avif_{_api.uuid.uuid4().hex}.avif")
                    try:
                        ok, err = _encode_to(tmp, int(av.get('cq', 30)))
                        if not ok:
                            if _api.os.path.exists(tmp):
                                try:
                                    _api.os.remove(tmp)
                                except Exception:
                                    pass
                            self._check_cancelled(iid)
                            if has_alpha and _api.Image:
                                return _alpha_webp_fallback()
                            raise Exception(f"AVIF conversion failed: {err}")
                        self._commit_output_file(tmp, out)
                        size_new = _api.os.path.getsize(out)
                        self.update_item_sig.emit(item['iid'], _api.human_size(size_new), "-")
                        return out
                    finally:
                        if _api.os.path.exists(tmp):
                            try:
                                _api.os.remove(tmp)
                            except Exception:
                                pass
                        _cleanup(tried_tmp_files)

                best_tmp = None
                best_size_kb = -1
                size63_kb = None

                try:
                    iterations = 0
                    max_iterations = max(1, min(8, int(av.get('fit_passes', 4))))

                    def _probe(crf_val):
                        t = _api.os.path.join(_api.TEMP_DIR, f"avif_{_api.uuid.uuid4().hex}_{crf_val}.avif")
                        tried_tmp_files.append(t)
                        ok, err = _encode_to(t, crf_val)
                        if not ok:
                            if _api.os.path.exists(t):
                                try:
                                    _api.os.remove(t)
                                except Exception:
                                    pass
                            raise Exception(f"AVIF conversion failed: {err}")
                        return t, max(1, _api.os.path.getsize(t) // 1024)

                    def _discard(t):
                        try:
                            if _api.os.path.exists(t):
                                _api.os.remove(t)
                                tried_tmp_files.remove(t)
                        except Exception:
                            pass

                    def _consider(t, s):
                        nonlocal best_tmp, best_size_kb
                        if s > best_size_kb:
                            if best_tmp and best_tmp != t and _api.os.path.exists(best_tmp):
                                try:
                                    _api.os.remove(best_tmp)
                                except Exception:
                                    pass
                            best_tmp, best_size_kb = t, s
                        else:
                            _discard(t)

                    tmp0, size0_kb = _probe(0)
                    iterations += 1
                    if size0_kb <= limit_kb:
                        _consider(tmp0, size0_kb)
                    else:
                        bad_crf, bad_size = 0, size0_kb
                        good_crf, good_size = None, None
                        if iterations < max_iterations:
                            t63, s63 = _probe(63)
                            iterations += 1
                            size63_kb = s63
                            if s63 <= limit_kb:
                                good_crf, good_size = 63, s63
                                _consider(t63, s63)
                            else:
                                _discard(t63)
                                bad_crf, bad_size = 63, s63

                        if good_crf is not None:
                            _TARGET_BIAS = 0.9
                            while good_crf - bad_crf > 1 and iterations < max_iterations:
                                if bad_size == good_size:
                                    mid = (bad_crf + good_crf) // 2
                                else:
                                    lt = _api.math.log(max(1, limit_kb * _TARGET_BIAS))
                                    lo, hi = _api.math.log(bad_size), _api.math.log(good_size)
                                    frac = max(0.0, min(1.0, (lo - lt) / (lo - hi)))
                                    mid = int(round(bad_crf + frac * (good_crf - bad_crf)))
                                    mid = max(bad_crf + 1, min(good_crf - 1, mid))
                                t, s = _probe(mid)
                                iterations += 1
                                if s <= limit_kb:
                                    good_crf, good_size = mid, s
                                    _consider(t, s)
                                else:
                                    _discard(t)
                                    bad_crf, bad_size = mid, s

                    if best_tmp and _api.os.path.exists(best_tmp):
                        self._commit_output_file(best_tmp, out)
                        size_new = _api.os.path.getsize(out)
                        _cleanup(tried_tmp_files)
                        self.update_item_sig.emit(item['iid'], _api.human_size(size_new), "-")
                        return out

                    if not orig_w or not orig_h:
                        try:
                            if _api.Image:
                                with _api.Image.open(path) as im:
                                    orig_w, orig_h = im.size
                        except Exception:
                            pass

                    if size63_kb is None:
                        t63, size63_kb = _probe(63)
                        if size63_kb <= limit_kb:
                            _consider(t63, size63_kb)
                        else:
                            _discard(t63)

                    if best_tmp and _api.os.path.exists(best_tmp):
                        self._commit_output_file(best_tmp, out)
                        size_new = _api.os.path.getsize(out)
                        _cleanup(tried_tmp_files)
                        self.update_item_sig.emit(item['iid'], _api.human_size(size_new), "-")
                        return out

                    if not orig_w or not orig_h:
                        _cleanup(tried_tmp_files)
                        raise Exception("Не удалось получить размеры изображения для downscale.")

                    new_max_side = self._avif_downscale_side(orig_w, orig_h, size63_kb, limit_kb)

                    down_attempt = 0
                    max_down_attempts = 5
                    current_side = new_max_side
                    while down_attempt < max_down_attempts:
                        vf_down = f"scale=if(gte(iw\\,ih)\\,{current_side}\\,-2):if(gt(ih\\,iw)\\,{current_side}\\,-2)"
                        tmp_down = _api.os.path.join(_api.TEMP_DIR, f"avif_{_api.uuid.uuid4().hex}_down{down_attempt}.avif")
                        tried_tmp_files.append(tmp_down)
                        ok, err = _encode_to(tmp_down, 63, vf_override=vf_down)
                        if not ok:
                            if _api.os.path.exists(tmp_down):
                                try:
                                    _api.os.remove(tmp_down)
                                except Exception:
                                    pass
                            raise Exception(f"AVIF conversion failed during downscale attempt: {err}")
                        size_kb = max(1, _api.os.path.getsize(tmp_down) // 1024)
                        if size_kb <= limit_kb:
                            self._commit_output_file(tmp_down, out)
                            size_new = _api.os.path.getsize(out)
                            _cleanup(tried_tmp_files)
                            self.update_item_sig.emit(item['iid'], _api.human_size(size_new), "-")
                            return out
                        else:
                            try:
                                if _api.os.path.exists(tmp_down):
                                    _api.os.remove(tmp_down)
                                    tried_tmp_files.remove(tmp_down)
                            except Exception:
                                pass
                            current_side = max(16, int(current_side * 0.85))
                            down_attempt += 1

                    _cleanup(tried_tmp_files)
                    raise Exception("Не удалось достичь указанного лимита AVIF.")

                except _api.subprocess.CalledProcessError as e:
                    stderr_tail = e.stderr if hasattr(e, 'stderr') else ''
                    _cleanup(tried_tmp_files)
                    if _api.os.path.exists(out) and not _api._same_path(out, orig_path):
                        try:
                            _api.os.remove(out)
                            self.log.emit(f"Удалён повреждённый AVIF: {out}")
                        except Exception:
                            pass
                    if has_alpha and _api.Image and not self._is_cancelled(iid):
                        return _alpha_webp_fallback()
                    raise Exception(f"AVIF conversion failed: {stderr_tail[:4000]}")
                except Exception as e:
                    _cleanup(tried_tmp_files)
                    if _api.os.path.exists(out) and not _api._same_path(out, orig_path):
                        try:
                            _api.os.remove(out)
                            self.log.emit(f"Удалён повреждённый AVIF: {out}")
                        except Exception:
                            pass
                    if "StoppedByUser" in str(e) or self._is_cancelled(iid):
                        raise Exception("StoppedByUser")
                    if has_alpha and _api.Image:
                        return _alpha_webp_fallback()
                    raise
            finally:
                self._release_pixel_budget(px_budget)
        finally:
            if pil_opened is not None:
                try:
                    pil_opened.close()
                except Exception:
                    pass
