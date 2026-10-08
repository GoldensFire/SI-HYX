# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Обработка: аргументы ffmpeg — кадрирование, фильтры, кодеки и подбор CRF по метрике."""
import workers as _api


class ProcessFiltersMixin:
    """Обработка: аргументы ffmpeg — кадрирование, фильтры, кодеки и подбор CRF по метрике."""

    @classmethod
    def _crop_from_counts(cls, row_counts, col_counts, iw: int, ih: int):
        """(w, h, x, y) рамки без полос — по числу ЯРКИХ пикселей в каждой
        строке/столбце кадра (максимум по всем просмотренным кадрам), либо None,
        если обрезать нечего.

        Линия считается полосой, когда ярких пикселей в ней не больше допуска на
        шум: одиночные засветки полосу не отменяют, а сотня пикселей — это уже
        содержимое, и трогать такую линию нельзя."""
        tol_row = max(cls._CROP_NOISE_MIN, int(iw * cls._CROP_NOISE_SHARE))
        tol_col = max(cls._CROP_NOISE_MIN, int(ih * cls._CROP_NOISE_SHARE))
        rows = [i for i, c in enumerate(row_counts) if c > tol_row]
        cols = [i for i, c in enumerate(col_counts) if c > tol_col]
        if not rows or not cols:
            return None      # весь сэмпл чёрный (затемнение/пустая сцена) — не режем
        y0, y1 = int(rows[0]), int(rows[-1])
        x0, x1 = int(cols[0]), int(cols[-1])
        # yuv420 (и тем более SVT-AV1) требует чётных размеров. Округляем ТОЛЬКО
        # наружу: смещение — к меньшему чётному, размер — к большему. Иначе
        # округление само срезало бы строку-столбец содержимого.
        x0 -= x0 % 2
        y0 -= y0 % 2
        w = x1 - x0 + 1
        h = y1 - y0 + 1
        if w % 2:
            w = min(w + 1, iw - x0)
        if h % 2:
            h = min(h + 1, ih - y0)
        if w <= 0 or h <= 0 or w % 2 or h % 2:
            return None
        if w >= iw - 2 and h >= ih - 2:
            return None      # рамка совпала с кадром — полос нет
        return w, h, x0, y0

    @classmethod
    def _detect_crop(cls, path: str, dur: float = 0.0, start: float = 0.0):
        """Рамка видео без чёрных полос: строка 'w:h:x:y' для фильтра crop или
        None, если полос нет.

        Считаем сами по нескольким кадрам, а НЕ через ffmpeg cropdetect: тот
        решает по средней яркости линии, и строка «чёрная везде, кроме мелкого
        яркого элемента» для него полоса. На записи экрана 1920×1080 это срезало
        18 строк с панелью задач вместе с реальными полосами по бокам (проверено
        на файле пользователя: cropdetect давал 1728:1062:96:0, тогда как
        содержимое идёт до 1078-й строки). Здесь линия — полоса, только если
        ярких пикселей в ней не больше допуска на шум (см. _crop_from_counts).

        Пропускаем первые ~10% (интро/логотипы на чёрном дают ложную рамку) и
        смотрим ограниченный отрезок: несколько кадров, а не весь файл.
        start — смещение начала отрезка (при обрезке сэмплить надо внутри
        [in_s,out_s), а не с начала файла)."""
        try:
            import numpy as np
            pr = _api.subprocess.run(
                [_api.FFPROBE, "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=width,height",
                 "-of", "csv=p=0:s=x", path],
                stdout=_api.subprocess.PIPE, stderr=_api.subprocess.DEVNULL,
                text=True, encoding="utf-8", errors="replace",
                creationflags=_api.CREATE_NO_WINDOW, timeout=30,
            )
            iw, ih = (int(v) for v in _api.csv_fields(pr.stdout, "x")[:2])
            if iw <= 0 or ih <= 0:
                return None
            # Чем крупнее кадр, тем меньше кадров берём — выборка целиком лежит
            # в памяти (серый кадр = w*h байт).
            frames = max(4, min(12, cls._CROP_SAMPLE_BYTES // max(1, iw * ih)))
            win = cls._CROP_WINDOW_SEC
            ss = start + (dur * 0.1 if dur and dur > win else 0.0)
            fps = max(1.0, frames / win)
            cmd = [_api.FFMPEG, "-hide_banner", "-nostdin"]
            if ss > 0:
                cmd += ["-ss", f"{ss:.2f}"]
            cmd += [
                "-i", path, "-t", f"{win:.2f}",
                "-vf", f"fps={fps:g},format=gray",
                "-frames:v", str(frames), "-an", "-sn",
                "-f", "rawvideo", "-pix_fmt", "gray", "-",
            ]
            p = _api.subprocess.run(cmd, stdout=_api.subprocess.PIPE,
                               stderr=_api.subprocess.DEVNULL,
                               creationflags=_api.CREATE_NO_WINDOW)
            buf, size = p.stdout or b"", iw * ih
            n = len(buf) // size
            if n == 0:
                return None
            a = np.frombuffer(buf[:n * size], dtype=np.uint8).reshape(n, ih, iw)
            bright = a > cls._CROP_LUMA_LIMIT
            # Максимум по кадрам, а не сумма/среднее: полоса обязана быть чёрной
            # во ВСЕХ просмотренных кадрах, иначе это содержимое, которое просто
            # темнеет местами.
            row_counts = bright.sum(axis=2).max(axis=0)
            col_counts = bright.sum(axis=1).max(axis=0)
            box = cls._crop_from_counts(row_counts, col_counts, iw, ih)
            if box is None:
                return None
            w, h, x, y = box
            return f"{w}:{h}:{x}:{y}"
        except Exception:
            return None

    @staticmethod
    def _choose_pix_fmt(has_alpha: bool) -> str:
        """Возвращает pix_fmt с учётом альфа-канала. Всегда 10-бит
        (yuv420p10le/yuva420p10le) — выбора 8-бит в настройках больше нет."""
        return "yuva420p10le" if has_alpha else "yuv420p10le"

    @staticmethod
    def _target_dims(ow, oh, adim=0, wlim=0, hlim=0):
        """Целевой размер картинки с учётом всех активных пределов сразу:
        макс. сторона (adim), макс. ширина (wlim), макс. высота (hlim). Пропорции
        сохраняются, применяется самый строгий предел, увеличение не делается.
        Возвращает (w, h) чётные, либо None если ужимать не нужно / размер неизвестен."""
        try:
            ow, oh = int(ow), int(oh)
        except Exception:
            return None
        if ow <= 0 or oh <= 0:
            return None
        factor = 1.0
        if adim and adim > 0: factor = min(factor, adim / max(ow, oh))
        if wlim and wlim > 0: factor = min(factor, wlim / ow)
        if hlim and hlim > 0: factor = min(factor, hlim / oh)
        if factor >= 1.0:
            return None  # уже вписывается во все пределы — не трогаем
        tw = max(2, int(round(ow * factor)))
        th = max(2, int(round(oh * factor)))
        tw -= tw % 2; th -= th % 2  # чётные стороны — безопасно для 4:2:0/4:2:2
        return (max(2, tw), max(2, th))

    @staticmethod
    def _av1_encoder_args(crf, preset, pix_fmt, tune=0):
        """Аргументы кодировщика SVT-AV1 (единственный используемый кодек).
        tune — режим тюнинга SVT-AV1, выбирается в настройках (c_tune в
        tabs.py): 0=VQ (по умолчанию), 1=PSNR, 2=SSIM, 4=MS-SSIM, 5=VMAF.
        tune=3 (IQ) намеренно не предлагается — работает только в
        all-intra/low-delay предсказании и падает с ошибкой на нашей
        random-access GOP-структуре (keyint=-1:scd=1 ниже). Выбор целевой
        метрики подбора CRF в настройках (Выкл/XPSNR) с этим тюнингом не
        связан — тот влияет только на то, ОТКУДА берётся crf, см.
        _metric_crf_search (самостоятельный подбор CRF под целевую метрику,
        без внешних инструментов).
        GOP: keyint=-1 (без принудительного периода) + scd=1 (детектор смены
        сцены) — ключевые кадры ставятся ТОЛЬКО на реальных сменах сцены.
        Принудительные периодические keyframe — самая дорогая по битам часть
        потока, поэтому это даёт максимальную оптимизацию под размер файла."""
        return ["-c:v", "libsvtav1", "-crf", str(crf),
                "-preset", str(max(0, min(13, int(preset)))),
                "-svtav1-params", f"tune={int(tune)}:keyint=-1:scd=1",
                "-pix_fmt", pix_fmt]

    def _measure_metric(self, orig_path, enc_path, metric):
        """Сравнивает enc_path с orig_path через встроенный ffmpeg-фильтр
        xpsnr, возвращает единое число (XPSNR в дБ) или None при ошибке.
        scale2ref подстраивает оригинал под размер закодированного кадра —
        иначе фильтр падает при несовпадении разрешений (когда в vf_list
        есть scale/crop)."""
        cmd = [_api.FFMPEG, "-i", enc_path, "-i", orig_path,
               "-filter_complex",
               f"[1:v][0:v]scale2ref=flags=bicubic[ref][enc];[enc][ref]{metric}",
               "-f", "null", "-"]
        try:
            r = _api.subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                                errors="replace", creationflags=_api.CREATE_NO_WINDOW, timeout=300)
        except Exception:
            return None
        out = (r.stderr or "") + (r.stdout or "")
        if metric == 'xpsnr':
            m = _api.re.search(r'XPSNR\s+y:\s*([\d.]+)\s+u:\s*([\d.]+)\s+v:\s*([\d.]+)', out)
            if not m:
                return None
            y, u, v = float(m.group(1)), float(m.group(2)), float(m.group(3))
            # Взвешенное усреднение в линейной (MSE) области с весами 4:1:1
            # (яркость:цветность при 4:2:0) — стандартная формула сведения
            # XPSNR к одному числу, а не наивное среднее в дБ.
            lin = (4 * (10 ** (-y / 10)) + (10 ** (-u / 10)) + (10 ** (-v / 10))) / 6
            return -10 * _api.math.log10(lin) if lin > 0 else 99.0
        return None

    @staticmethod
    def _short_sample(path, max_len=15.0, min_src=20.0):
        """Короткий (~max_len с) кусок ИЗ СЕРЕДИНЫ файла для пробных замеров
        качества → (путь, временный_файл_или_None).

        Seek только ВХОДНОЙ (`-ss` ДО `-i`) + `-t`: с `-c copy` выходной `-ss`
        не годится — не имея права декодировать, ffmpeg выбрасывает всё до
        СЛЕДУЮЩЕГО ключевого кадра, и на длинном GOP (10 с у типичного рипа)
        от сэмпла остаётся 2 кадра. Входной seek встаёт на ключевой кадр сам.
        Точная граница для метрики не важна — важен представительный материал.

        Файлы короче min_src отдаются как есть (резать нечего). Удаление
        временного файла — на вызывающем."""
        try:
            dur, *_ = _api.get_media_info(path)
        except Exception:
            dur = 0.0
        if not dur or dur <= min_src:
            return path, None
        sample_len = min(float(max_len), dur * 0.3)
        start = max(0.0, dur / 2 - sample_len / 2)
        tmp = _api.os.path.join(_api.TEMP_DIR, f"metricsample_{_api.uuid.uuid4().hex}"
                                     f"{_api.os.path.splitext(path)[1] or '.mkv'}")
        try:
            cmd_cut = [_api.FFMPEG, "-y", "-ss", f"{start:.3f}", "-i", path,
                       "-t", f"{sample_len:.3f}", "-c", "copy", tmp]
            _api.subprocess.run(cmd_cut, capture_output=True,
                            creationflags=_api.CREATE_NO_WINDOW, timeout=60)
            if _api.os.path.exists(tmp) and _api.os.path.getsize(tmp) > 0:
                return tmp, tmp
        except Exception:
            pass
        try:
            if _api.os.path.exists(tmp): _api.os.remove(tmp)
        except Exception:
            pass
        return path, None

    def _measure_at_crf(self, sample_path, crf, preset, pix_fmt, tune, vf_list,
                        metric='xpsnr', cancel_check=None):
        """Кодирует КОРОТКИЙ кусок sample_path заданным CRF и меряет метрику
        против него же — разовый замер (без бинарного поиска _metric_crf_search)
        для колонки «Оценка XPSNR», когда CRF ручной (вместо цели по метрике)
        или подбор не удался. Возвращает float | None.

        Замер идёт по сэмплу ~15 с и на preset не медленнее
        _SEARCH_PRESET_FLOOR — ровно как пробы в _metric_crf_search. Раньше
        кодировался ВЕСЬ вход целиком и на финальном (медленном) preset: на
        preset 2 это ровно удваивало время всей обработки файла ради числа в
        одной колонке. Быстрый preset при том же CRF даёт качество не выше
        финального, поэтому оценка остаётся консервативной (не завышенной)."""
        work_path, work_tmp = self._short_sample(sample_path)
        tmp_out = _api.os.path.join(_api.TEMP_DIR, f"xpsnrscore_{_api.uuid.uuid4().hex}.mkv")
        try:
            if self.stop_flag or (cancel_check is not None and cancel_check()):
                return None
            cmd = ([_api.FFMPEG, "-y", "-i", work_path] +
                   self._av1_encoder_args(crf, max(int(preset), self._SEARCH_PRESET_FLOOR),
                                          pix_fmt, tune) + ["-an"])
            if vf_list: cmd += ["-vf", ",".join(vf_list)]
            cmd += ["-threads", "0", tmp_out]
            ok = self._run_killable(cmd, cancel_check=cancel_check)
            if not ok or not _api.os.path.exists(tmp_out):
                return None
            return self._measure_metric(work_path, tmp_out, metric)
        except Exception:
            return None
        finally:
            for f in (tmp_out, work_tmp):
                try:
                    if f and _api.os.path.exists(f): _api.os.remove(f)
                except Exception: pass

    def _run_killable(self, cmd, cancel_check=None, on_tick=None, t_start=None, poll=0.4):
        """Popen + периодический опрос вместо блокирующего subprocess.run —
        stop_flag/cancel_check подхватываются в пределах poll секунд, а не
        только когда сам процесс (может идти минутами на медленном preset)
        завершится сам. Возвращает True при успешном (returncode 0) завершении,
        False при ошибке/отмене."""
        si = _api.subprocess.STARTUPINFO() if _api.IS_WIN else None
        if _api.IS_WIN and si is not None: si.dwFlags |= _api.subprocess.STARTF_USESHOWWINDOW
        try:
            p = _api.subprocess.Popen(cmd, stdout=_api.subprocess.DEVNULL, stderr=_api.subprocess.DEVNULL,
                                 creationflags=_api.CREATE_NO_WINDOW | getattr(self, '_priority_flag', 0),
                                 startupinfo=si)
        except Exception:
            return False
        last_tick = _api.time.time()
        while True:
            if self.stop_flag or (cancel_check is not None and cancel_check()):
                try: p.kill()
                except Exception: pass
                try: p.wait(timeout=3)
                except Exception: pass
                return False
            try:
                p.wait(timeout=poll)
                return p.returncode == 0
            except _api.subprocess.TimeoutExpired:
                now = _api.time.time()
                if on_tick is not None and t_start is not None and now - last_tick >= 1.0:
                    last_tick = now
                    try: on_tick(now - t_start)
                    except Exception: pass
                continue

    def _metric_crf_search(self, path, preset, pix_fmt, metric, target,
                            vf_list, cancel_check=None, on_tick=None, tune=0):
        """Подбирает CRF (0-63) без внешних инструментов: вырезает из середины
        файла короткий (~15с) сэмпл и бинарным поиском находит максимальный
        CRF (= минимальный размер), при котором SVT-AV1 (tune — тот же
        тюнинг, что и в финальном кодировании, см. _av1_encoder_args) всё ещё
        даёт метрику (xpsnr, встроенный фильтр ffmpeg) не хуже target.

        Сперва проверяется CRF=0 (лучшее возможное качество) — если даже он не
        дотягивает до target, цель физически недостижима на этом материале
        (типично для шумного/зернистого видео), и нет смысла тратить время на
        полный бинарный поиск (было — до 6 пробных кодирований вслепую, минуты
        на медленных preset'ах; стало — 1 пробa и мгновенный честный отказ).

        preset для проб ограничен снизу (не медленнее _SEARCH_PRESET_FLOOR),
        независимо от того, насколько медленный preset выбран для финального
        кодирования — иначе один пробный энкод 1080p на preset=0-2 может идти
        по несколько минут, и Стоп ждал бы своего часа между попытками. Более
        быстрый preset для поиска — общепринятый компромисс (напр. в ab-av1):
        качество при том же CRF на быстром preset обычно НЕ выше, чем на
        медленном, поэтому финальный (медленный) preset с подобранным CRF
        будет не хуже, а обычно даже с запасом.

        Возвращает (crf:int|None, info:str) — при успехе info — достигнутое
        значение метрики пробы, при неудаче — причина отказа."""
        t_start = _api.time.time()
        search_preset = max(int(preset), self._SEARCH_PRESET_FLOOR)
        sample_path, sample_tmp = self._short_sample(path)

        def _cleanup_sample():
            if sample_tmp:
                try:
                    if _api.os.path.exists(sample_tmp): _api.os.remove(sample_tmp)
                except Exception: pass

        def _cancelled():
            return self.stop_flag or (cancel_check is not None and cancel_check())

        def _trial(crf):
            """Кодирует сэмпл с данным CRF и измеряет метрику. Возвращает
            (score:float|None, err:str|None); err='отменено' при остановке."""
            if _cancelled():
                return None, "отменено"
            tmp_out = _api.os.path.join(_api.TEMP_DIR, f"metrictrial_{_api.uuid.uuid4().hex}.mkv")
            cmd = ([_api.FFMPEG, "-y", "-i", sample_path] +
                   self._av1_encoder_args(crf, search_preset, pix_fmt, tune) + ["-an"])
            if vf_list: cmd += ["-vf", ",".join(vf_list)]
            cmd += ["-threads", "0", tmp_out]
            ok = self._run_killable(cmd, cancel_check=cancel_check, on_tick=on_tick, t_start=t_start)
            if not ok:
                try:
                    if _api.os.path.exists(tmp_out): _api.os.remove(tmp_out)
                except Exception: pass
                return None, ("отменено" if _cancelled() else "ошибка пробного кодирования")
            score = self._measure_metric(sample_path, tmp_out, metric) if _api.os.path.exists(tmp_out) else None
            try:
                if _api.os.path.exists(tmp_out): _api.os.remove(tmp_out)
            except Exception: pass
            if on_tick is not None:
                try: on_tick(_api.time.time() - t_start)
                except Exception: pass
            return score, (None if score is not None else "не удалось измерить метрику")

        # Проверка достижимости: лучший возможный случай — CRF=0.
        score0, err0 = _trial(0)
        if err0 is not None:
            _cleanup_sample()
            return None, err0
        if score0 < target:
            _cleanup_sample()
            return None, (f"даже CRF 0 (лучшее качество) даёт {metric.upper()} ≈{score0:.2f} "
                          f"< цели {target:.2f} — недостижимо на этом материале")

        lo, hi = 0, 63
        best_crf, best_info = 0, f"{score0:.2f}"
        tries, max_tries = 0, 5
        while lo < hi and tries < max_tries:
            mid = (lo + hi + 1) // 2
            score, err = _trial(mid)
            tries += 1
            if err is not None:
                break
            if score >= target:
                best_crf, best_info = mid, f"{score:.2f}"
                lo = mid
            else:
                hi = mid - 1
        _cleanup_sample()
        return best_crf, best_info

    def run_ffmpeg_capture(self, cmd, total_est_sec, percent_callback, label=None, eta_calc=None, cancel_check=None):
        from ffmpeg_faststart import with_faststart
        cmd = with_faststart(cmd)
        si = _api.subprocess.STARTUPINFO() if _api.IS_WIN else None
        if _api.IS_WIN and si is not None: si.dwFlags |= _api.subprocess.STARTF_USESHOWWINDOW
        buf = _api.deque(maxlen=8000)
        try:
            p = _api.subprocess.Popen(cmd, stderr=_api.subprocess.PIPE, stdout=_api.subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace", creationflags=_api.CREATE_NO_WINDOW | getattr(self, '_priority_flag', 0), startupinfo=si)
        except Exception as e:
            raise Exception(f"Не удалось запустить ffmpeg: {e}")
        start = _api.time.time()
        last_pct = -1
        last_eta = None          # последнее посчитанное ETA (с)
        last_emit_t = 0.0        # когда последний раз слали колбэк
        last_frame = None        # последний разобранный номер кадра ffmpeg
        total_frames = getattr(eta_calc, 'total_frames', 0) if eta_calc is not None else 0
        try:
            while True:
                # cancel_check: файл убрали из очереди во время обработки (см.
                # MediaTab.rem) — прерываем ТОЛЬКО этот процесс, не весь stop_flag.
                if self.stop_flag or (cancel_check is not None and cancel_check()):
                    try: p.kill()
                    except Exception: pass
                    try:
                        tail = p.stderr.read() or ""
                        for L in tail.splitlines(): buf.append(L + "\n")
                    except Exception: pass
                    raise Exception("StoppedByUser")
                line = p.stderr.readline()
                if line: buf.append(line)
                now = _api.time.time()
                elapsed = now - start
                # ── Реальное ETA + кадр: вытаскиваем текущий кадр из строки ffmpeg
                #    и скармливаем адаптивному калькулятору (если он передан). Вся
                #    математика — здесь, в потоке ffmpeg; GUI не трогаем. ───────
                if eta_calc is not None and line:
                    m = _api._RE_FFMPEG_FRAME.search(line)
                    if m:
                        last_frame = int(m.group(1))
                        try:
                            val = eta_calc.update(last_frame)
                            if val is not None:
                                last_eta = val
                        except Exception:
                            pass
                # ── Прогресс-бар ──────────────────────────────────────────────
                # Временная формула (fallback): чисто по времени. Точна ровно
                # настолько, насколько точен est, — для медленных пресетов упирается
                # в 99% почти мгновенно.
                pct_time = int(min(99, (elapsed / total_est_sec) * 99)) if total_est_sec and total_est_sec > 0 else int(min(98, elapsed * 15))
                if total_frames > 0:
                    # Калькулятор активен → ведём полосу по РЕАЛЬНОМУ прогрессу
                    # кадров (frame/всего). Честно отражает медленные пресеты.
                    if last_frame is not None:
                        pct = int(min(99, last_frame / total_frames * 99))
                    else:
                        # Кадров ещё нет (SVT-AV1 буферизует look-ahead) — лёгкий
                        # «прогрев», но НЕ даём временной формуле улететь в 99 и
                        # потом прыгнуть вниз при первом кадре.
                        pct = min(2, pct_time)
                else:
                    pct = pct_time
                # Монотонность: полоса не едет назад (на стыке прогрев→кадры и при
                # буферизации SVT-AV1, когда frame замирает).
                if pct < last_pct and last_pct >= 0:
                    pct = last_pct
                # Колбэк шлём: (а) при смене целого процента ИЛИ (б) раз в ~1 с,
                # пока есть реальное ETA. Без (б) ETA «замерзал», когда бар упирался
                # в 99% (заниженный est) и pct переставал меняться. Это развязывает
                # обновление ETA от движения полосы прогресса.
                pct_changed = (pct != last_pct)
                eta_tick = (eta_calc is not None and last_eta is not None
                            and (now - last_emit_t) >= 1.0)
                if pct_changed or eta_tick:
                    if pct_changed: last_pct = pct
                    last_emit_t = now
                    eta_sec = last_eta if eta_calc is not None else None
                    try:
                        percent_callback(pct, label, eta_sec)
                    except TypeError:
                        # Обратная совместимость со старыми колбэками (без eta_sec).
                        try:
                            percent_callback(pct, label)
                        except Exception:
                            try:
                                percent_callback(pct)
                            except Exception:
                                pass
                    except Exception:
                        pass
                if not line and p.poll() is not None: break
        except Exception:
            try: p.kill()
            except Exception: pass
            raise
        if p.returncode != 0:
            stderr_tail = ''.join(buf)
            raise _api.subprocess.CalledProcessError(p.returncode, cmd, output=None, stderr=stderr_tail)

    def _estimate_total_frames(self, src_path, speed_factor, cmd, dur_override=None):
        """Оценка числа ВЫХОДНЫХ кадров видео для знаменателя ETA.
        Учитывает изменение скорости (setpts) и принудительный -r из cmd.
        Возвращает 0, если оценить не удалось (тогда ETA-калькулятор не создаётся
        и работает старая оценка по доле прогресса).

        dur_override — длительность ВХОДА в секундах, если она уже известна и НЕ
        равна полной длительности src_path (обрезка: кодируем не весь файл, а
        отрезок [in_s,out_s) — иначе ETA считало бы кадры на весь исходник)."""
        try:
            dur = float(dur_override) if dur_override and dur_override > 0 else 0.0
            if not dur:
                try: dur, *_ = _api.get_media_info(src_path)
                except Exception: dur = 0.0
            if not dur or dur <= 0:
                return 0
            sf = speed_factor if speed_factor and speed_factor > 0 else 1.0
            out_dur = dur / sf
            # Принудительный fps (-r N) перекрывает исходный.
            out_fps = 0.0
            try:
                if "-r" in cmd:
                    out_fps = float(cmd[cmd.index("-r") + 1])
            except Exception:
                out_fps = 0.0
            if out_fps <= 0:
                out_fps = _api.get_fps_float(src_path) or 0.0
            if out_fps <= 0:
                return 0
            return max(1, int(out_dur * out_fps))
        except Exception:
            return 0

    def get_target_bitrate_str(self, path, sel_val):
        if str(sel_val).lower() == 'auto':
            try:
                _, _, _, a_br_str, _ = _api.get_media_info(path)
                if a_br_str and a_br_str != "-":
                    m = _api._RE_DIGITS.findall(a_br_str)
                    if m:
                        val = int(m[0])
                        if val > 512: val = 512
                        return f"{val}k"
            except Exception: pass
            return "128k"
        return f"{sel_val}k"

    @staticmethod
    def _trim_seek_args(in_s, out_s, speed_factor=1.0):
        """Тот же приём, что EditTab._execute_cut (edit_tab.py:8841-8876): быстрый
        ВХОДНОЙ pre-seek (до ближайшей секунды перед резом) экономит декодирование
        на длинных файлах, а частичный ВЫХОДНОЙ -ss/-t после него остаётся
        кадрово-точным (секунды передаём как есть, без округления до HH:MM:SS —
        погрешности форматирования нет, поэтому pre-seek компенсировать не нужно).

        `-ss` тут ВЫХОДНОЙ (после -i, без второго -i дальше) — ffmpeg декодирует
        и отбрасывает кадры до точки, PTS не обнуляются, а `-t` считает
        длительность уже В ВЫХОДНОЙ (постфильтровой) шкале. Если включена смена
        скорости — setpts потом делит PTS на speed_factor, поэтому сам `-t`
        обязан быть уже поделен на speed_factor: иначе он ограничит ВЫХОД
        нетронутыми «сырыми» секундами и декодер прочитает far больше входа,
        чем нужно (проверено: без деления вместо 5с/1.5x=3.33с выходило
        ровно 5с — «-t» душил по немасштабированному времени).

        Возвращает (pre_args, post_args, t0): pre_args/post_args — куски cmd
        (pre_args ДО `-i`, post_args ПОСЛЕ), t0 — время начала клипа в шкале
        фильтрграфа, нужное чтобы сдвинуть st= у фейдов на правильную величину
        (t0_video ниже уже сам делит на скорость там, где это нужно).

        ВАЖНО про t0: шкалу времени фильтрграфа задаёт именно ВЫХОДНОЙ `-ss`
        (значение после -i), а НЕ абсолютная позиция in_s. Когда есть входной
        pre-seek (`-ss (in_s-PRESEEK)` до -i), он обнуляет тайминги в точке
        pre-seek, и последующий выходной `-ss PRESEEK` выводит клип, начинающийся
        в шкале фильтров с PRESEEK — а не с in_s. Поэтому t0 = значение выходного
        `-ss`: PRESEEK в ветке с pre-seek, in_s — без него. Раньше здесь всегда
        возвращалось in_s, из-за чего при in_s>6с (ветка pre-seek) afade/vfade
        ставились на st ≈ in_s+dur (за пределами клипа) и фейды НЕ применялись,
        хотя суффикс _fade в имени присутствовал (баг «пишет fade, а его нет»).
        При in_s≤6с (без pre-seek) t0=in_s был и остаётся верным."""
        PRESEEK = 3.0
        dur = max(0.0, out_s - in_s)
        sf = speed_factor if speed_factor else 1.0
        out_dur = dur / sf
        # ВЫХОДНОЙ `-ss` применяется к ПОСТфильтровой шкале — а видео там уже
        # сжато setpts=(1/speed)*PTS (и звук atempo), поэтому seek обязан быть
        # ПОДЕЛЁН на speed_factor РОВНО КАК `-t`. Раньше делили только `-t`, а
        # `-ss` слали как есть (PRESEEK/in_s) — при speed≠100% старт уезжал вправо
        # на seek*(speed−1) (напр. PRESEEK=3с ×0.07 = 0.21с ≈ 5 кадров при 107%:
        # баг «обрезка сдвигает начало, первое слово срезается»). Проверено
        # покадрово (SSIM) на реальном 25fps h264: с делением старт встаёт ровно
        # на in_s, без — на in_s + PRESEEK*(speed−1). При speed=100% sf=1 → как было.
        # t0 (шкала фильтрграфа для st= фейдов) остаётся в ИСХОДНОЙ до-setpts шкале
        # (PRESEEK / in_s) — фейды считаются до atempo/после setpts по сырому t0.
        if in_s > 2 * PRESEEK:
            return (["-ss", f"{in_s - PRESEEK:.6f}"],
                    ["-ss", f"{PRESEEK / sf:.6f}", "-t", f"{out_dur:.6f}"],
                    PRESEEK)
        return ([], ["-ss", f"{in_s / sf:.6f}", "-t", f"{out_dur:.6f}"], in_s)

    @staticmethod
    def _out_suffix(is_video, video_enabled, metric, crf, speed_percent,
                    remove_audio, norm, fade):
        """Суффикс имени выходного файла (напр. «_crf45_speed100_norm_fade»).

        Чистая функция (вынесена из process_media для читаемости/тестируемости).
        При авто-подборе CRF (metric=='xpsnr') пишет 'autocrf' вместо числа —
        реальный CRF на этот момент ещё неизвестен, подбирается для каждого файла
        свой, и врать цифрой, взятой ДО подбора, нельзя. Порядок частей сохранён
        1:1 с прежним инлайн-кодом."""
        suffix = ""
        if is_video and video_enabled:
            crf_tag = "autocrf" if metric == 'xpsnr' else f"crf{crf}"
            suffix += f"_{crf_tag}_speed{speed_percent}"
        if remove_audio:
            suffix += "_noaudio"
        elif norm:
            suffix += "_norm"
        if not remove_audio and fade:
            suffix += "_fade"
        return suffix

    @staticmethod
    def _build_audio_filters(sa, t0, fade_out_dur, speed_factor):
        """Цепочка аудиофильтров для ffmpeg `-af` из настроек звука.

        Порядок (сохранён 1:1 с прежним инлайн-кодом process_media): loudnorm →
        fade-in → fade-out → «деградация» (lowpass/highpass/u8/volume) → atempo
        (смена скорости, через _build_atempo_chain). Чистая функция: t0 (начало
        клипа в шкале фильтров) и fade_out_dur (длительность отрезка/файла, нужна
        только ветке fade-out) передаются уже вычисленными — ffprobe тут не
        вызывается, поэтому логику легко покрыть тестами. Вызывать только когда
        звук сохраняется (не remove_audio) — как и раньше."""
        filters = []
        if sa.get('norm'):
            tgt_i = float(sa.get('tgt', -20.0))
            lra = float(sa.get('lra', 11.0))
            tp = float(sa.get('tp', -1.5))
            filters.append(f"loudnorm=I={tgt_i}:LRA={lra}:TP={tp}")
        if sa.get('fade_in'):
            fade_in_d = sa.get('fade_in_d', 1.0)
            # st=t0: при обрезке (trim) seek не обнуляет PTS — фильтр видит
            # исходное время клипа, поэтому фейд-ин начинается от t0, а не 0.
            filters.append(f"afade=t=in:st={t0:.3f}:d={fade_in_d}")
        if sa.get('fade'):
            fade_d = sa.get('fade_d', 1.0)
            filters.append(
                f"afade=t=out:st={max(0.0, t0 + (fade_out_dur or 0.0) - fade_d):.3f}:d={fade_d}")
        if sa.get('deg'):
            filters.append(f"lowpass=f={sa.get('lp', 3000)}")
            filters.append(f"highpass=f={sa.get('hp', 200)}")
            hz = int(sa.get('hz', 44100))
            if sa.get('u8'):
                filters.append(f"aformat=sample_fmts=u8:sample_rates={hz}")
            gain_db = float(sa.get('deg_gain_db', 0.0))
            if abs(gain_db) > 0.01:
                filters.append(f"volume={gain_db}dB")
        if abs(speed_factor - 1.0) > 0.01:
            filters.extend(_api._build_atempo_chain(speed_factor))
        return filters

    @staticmethod
    def _scale_vf(res_sel):
        """Фильтр `scale` по выбранному разрешению или None (исходное/не задано).

        '1280x720' → вписать в рамку без искажения пропорций
        (force_original_aspect_ratio=decrease), стороны чётные (SVT-AV1 требует).
        Некорректная строка «WxH» откатывается на прямой `scale=<res>`. Чистая
        функция — строит ровно ту же строку, что раньше инлайн в process_media."""
        if not (isinstance(res_sel, str) and res_sel and res_sel != "Исходное"):
            return None
        if 'x' in res_sel:
            try:
                w_str, h_str = res_sel.split('x', 1)
                w = int(w_str); h = int(h_str)
                return (f"scale=w='min(iw,{w})':h='min(ih,{h})'"
                        f":force_original_aspect_ratio=decrease"
                        f":force_divisible_by=2")
            except Exception:
                return f"scale={res_sel}:force_divisible_by=2"
        return f"scale={res_sel}:force_divisible_by=2"

    @staticmethod
    def _af_arg(filters, trim_tail=False):
        """Готовая строка для ffmpeg `-af`: фильтры + фикс раскладки под libopus.

        OPUS_LAYOUT_FIX добавляется ВСЕГДА (в т.ч. когда своих фильтров нет) —
        libopus отвергает «боковые»/нестандартные раскладки каналов (5.1(side)
        у AC3-дорожек) с "Invalid channel layout … (exit -22)"; на stereo/mono
        это no-op и downmix не делается.

        trim_tail=True добавляет aresample=async=1 ПЕРЕД фиксом раскладки —
        выравнивает длину аудио к входной дорожке, срезая «хвост» от latency
        loudnorm и добивки opus-кадров (иначе контейнер длиннее источника).
        Включать только при нормальной скорости: при смене скорости длину
        задаёт atempo, и async лишь помешал бы.

        Чистая функция (вынесена из process_media — раньше эти же две цепочки
        собирались инлайн в четырёх местах)."""
        chain = list(filters)
        if trim_tail:
            chain.append("aresample=async=1")
        chain.append(_api.OPUS_LAYOUT_FIX)
        return ",".join(chain)

    @staticmethod
    def _map_av_args(remove_audio, a_map_sel):
        """`-map`-аргументы: только настоящее видео + (опционально) аудио.

        0:V? исключает обложки/attached_pic. Субтитры/вложения/данные не
        маппим сознательно: их кодеки несовместимы с целевым контейнером →
        ffmpeg падает. a_map_sel — либо конкретная дорожка, выбранная в
        Монтаже ("0:3"), либо "0:a?". Чистая функция."""
        if remove_audio:
            return ["-map", "0:V?"]
        return ["-map", "0:V?", "-map", a_map_sel]

    @staticmethod
    def _fps_args(fps_sel, src_path):
        """`-r`-аргументы по выбранному в настройках fps (или [] — не менять).

        «Исходный (max 30)» ставит -r 30 только если источник реально быстрее
        (иначе кодер бессмысленно растянул бы VFR до CFR). Нечисловые значения
        игнорируются. Единственная нечистота — чтение fps источника."""
        if fps_sel == "Исходный (max 30)":
            try:
                if _api.get_fps_float(src_path) > 30.5:
                    return ["-r", "30"]
            except Exception:
                pass
            return []
        if isinstance(fps_sel, str) and fps_sel != "Исходный":
            try:
                float(fps_sel)
                return ["-r", fps_sel]
            except Exception:
                pass
        return []

    def _build_video_filters(self, sv, item, current_input, trim, t0, t0_video,
                             speed_factor):
        """Цепочка видеофильтров для `-vf` (порядок сохранён 1:1 с прежним
        инлайн-кодом process_media): crop чёрных полос → setpts (скорость) →
        scale → fade-in → fade-out.

        Порядок значим: crop идёт ПЕРВЫМ, чтобы масштаб и фейды считались уже
        от обрезанного кадра, а setpts — ДО fade, поэтому к моменту fade PTS
        уже поделены на speed_factor.

        Не чистая: определение чёрных полос и длительность/fps источника
        требуют чтения файла."""
        vf_list = []

        if sv.get('crop_black'):
            crop = self._detect_crop(current_input, item.get('dur') or 0.0,
                                      start=(trim[0] if trim else 0.0))
            if crop:
                vf_list.append(f"crop={crop}")
                self.log.emit(f"✂ Обрезка чёрных полос: crop={crop}")
            else:
                self.log.emit("✂ Чёрные полосы не обнаружены — обрезка пропущена")

        # Вшивание субтитров из Монтажа (режим обрезки «настройками «Обработки»»).
        # Стоит ПОСЛЕ crop чёрных полос (текст рисуется на уже обрезанном кадре,
        # как и в собственной перекодировке Монтажа) и ДО setpts: фильтр subtitles
        # ищет реплики по времени, а setpts это время меняет.
        burn = item.get('burn_subs') or {}
        if burn.get('vf'):
            # Отрезок вырезается быстрым ВХОДНЫМ pre-seek'ом, а он обнуляет
            # тайминги в своей точке — время фильтрграфа идёт не от начала файла,
            # а от t0 (см. _trim_seek_args). Фильтр же subtitles сопоставляет
            # реплики со временем САМОГО файла субтитров, поэтому на время его
            # работы возвращаем исходную шкалу и сразу возвращаем обратно; иначе
            # текст уехал бы ровно на pre-seek.
            off = float(burn.get('src_in') or 0.0) - float(t0 or 0.0)
            if off > 0.001:
                vf_list.append(f"setpts=PTS+{off:.6f}/TB")
                vf_list.append(burn['vf'])
                vf_list.append(f"setpts=PTS-{off:.6f}/TB")
            else:
                vf_list.append(burn['vf'])

        if abs(speed_factor - 1.0) > 0.01:
            vf_list.append(f"setpts={1.0/speed_factor}*PTS")

        scale_vf = self._scale_vf(sv.get('res', 'Исходное') or 'Исходное')
        if scale_vf:
            vf_list.append(scale_vf)

        # Видео fade in / out (через чёрный).
        # st фейд-ИНА берём в ИСХОДНОЙ (до-setpts) шкале — сырой t0, НЕ
        # поделённый на скорость. Проверено эмпирически: fade-фильтр
        # сопоставляет st по времени кадров ДО setpts, поэтому при обрезке
        # со сменой скорости fade-in ловится ровно на st=t0 (=значение
        # output-seek), а t0_video (t0/speed) промахивается и первый кадр
        # остаётся не затемнённым. При нормальной скорости t0==t0_video,
        # так что обычный (частый) случай не меняется.
        if sv.get('vfade_in'):
            vfi = float(sv.get('vfade_in_d', 1.0))
            if vfi > 0:
                vf_list.append(f"fade=t=in:st={t0:.3f}:d={vfi}")
        if sv.get('vfade_out'):
            vfo = float(sv.get('vfade_out_d', 1.0))
            if vfo > 0:
                src_dur = item.get('dur') or 0.0
                if src_dur <= 0.0:
                    try: src_dur, *_ = _api.get_media_info(current_input)
                    except Exception: src_dur = 0.0
                out_dur = (src_dur / speed_factor) if speed_factor else src_dur
                out_dur += t0_video
                # Фейд должен ЗАВЕРШИТЬСЯ до последнего кадра, иначе кадр
                # окажется на ~96% затемнения, а не на 100%. Сдвигаем фейд
                # на запас (≥1.5 кадра) — фильтр держит чёрный после конца.
                try: _fps = _api.get_fps_float(current_input) or 25.0
                except Exception: _fps = 25.0
                if _fps <= 0: _fps = 25.0
                margin = max(0.08, 1.5 / _fps)
                st = max(0.0, out_dur - vfo - margin)
                vf_list.append(f"fade=t=out:st={st:.3f}:d={vfo}")

        return vf_list

    def _overlay_vf(self, vf_list, item, current_input):
        """Готовая строка `-vf`: цепочка фильтров «Обработки» плюс наложенные
        картинки Монтажа, если они пришли с элементом очереди.

        item['overlays'] — список (png, x, y) от EditTab._render_export_overlays
        (координаты в пикселях ИСХОДНОГО кадра), item['overlay_format'] — формат
        работы overlay, посчитанный Монтажом по pix_fmt исходника. Формата нет —
        считаем сами: `format=auto` оставлять нельзя, иначе RGBA-накладка уводит
        весь граф в RGB и цвет итогового файла уезжает."""
        chain = ",".join(vf_list)
        rendered = [tuple(o) for o in (item.get('overlays') or [])]
        if not rendered:
            return chain
        fmt = item.get('overlay_format') or _api.overlay_chroma_format(
            _api.get_pix_fmt(current_input))
        return _api.overlay_filter_graph(chain, rendered, pix_fmt=fmt)

    def _make_metric_sample(self, current_input, trim, max_len=20.0):
        """Вход для пробных замеров качества → (путь, временный_файл_или_None).

        При обрезке (trim) вырезает кусок ИЗ СЕРЕДИНЫ вырезаемого диапазона
        (не длиннее max_len): без этого замер (подбор CRF ИЛИ разовая оценка
        XPSNR) мог бы попасть на кадры вне отрезка. Без trim и при любой
        ошибке нарезки возвращает исходный вход и None — короткий сэмпл из
        него потом вырежут сами замеры (_short_sample). Удаление временного
        файла — на вызывающем (он переживает и подбор CRF, и оценку).

        Seek ТОЛЬКО входной (`-ss` до `-i`). Раньше сюда передавались готовые
        trim_pre/trim_post финального реза, где `-ss` стоит и ПОСЛЕ `-i`
        (кадрово точный выходной seek): с `-c copy` ffmpeg не декодирует и
        поэтому выбрасывает всё до СЛЕДУЮЩЕГО ключевого кадра — на обычном
        GOP в 10 с от 10-секундного отрезка оставалось 2 кадра (проверено
        ffprobe: nb_frames=2 из 250). Подбор CRF и оценка XPSNR при обрезке
        считались, таким образом, по двум кадрам. Кадровая точность границ
        для метрики не нужна — нужен представительный материал."""
        if not trim:
            return current_input, None
        in_s, out_s = float(trim[0]), float(trim[1])
        dur = max(0.0, out_s - in_s)
        if dur <= 0.0:
            return current_input, None
        take = min(float(max_len), dur)
        start = in_s + max(0.0, (dur - take) / 2.0)
        tmp = _api.os.path.join(
            _api.TEMP_DIR, f"metricsample_{_api.uuid.uuid4().hex}"
                      f"{_api.os.path.splitext(current_input)[1] or '.mkv'}")
        try:
            cmd_cut = [_api.FFMPEG, "-y", "-ss", f"{start:.3f}", "-i", current_input,
                       "-t", f"{take:.3f}", "-c", "copy", tmp]
            _api.subprocess.run(cmd_cut, capture_output=True, creationflags=_api.CREATE_NO_WINDOW, timeout=120)
            if _api.os.path.exists(tmp) and _api.os.path.getsize(tmp) > 0:
                return tmp, tmp
        except Exception:
            pass
        return current_input, tmp

    @staticmethod
    def _wants_metric_score(sv):
        """Нужна ли вообще оценка XPSNR для этого прогона.

        Считаем её только когда пользователь её видит: включена метрика
        (тогда она побочный результат подбора CRF) ЛИБО показана колонка
        «Оценка XPSNR» (переключатель продвинутых настроек кодирования,
        см. set_advanced_encode_visible в tabs.py). По умолчанию колонка
        скрыта, а метрика выключена — и всё равно на каждый файл гонялось
        лишнее пробное кодирование ВСЕГО входа на финальном (медленном)
        preset: ровно удвоенное время обработки ради числа, которого нет
        на экране."""
        return (sv.get('metric', 'none') != 'none') or bool(sv.get('show_metric_col'))

    def _resolve_crf(self, item, sv, crf, sample_input, preset_for_search,
                     search_pix_fmt, video_tune, vf_list, cb):
        """Итоговый CRF для этого файла + эмит оценки XPSNR в таблицу.

        metric=='xpsnr' → CRF подбирается под целевую метрику (_metric_crf_search,
        без внешних инструментов); ручной CRF из настроек остаётся фолбэком,
        если подбор не удался. Когда подбора не было (или он не удался),
        оценку даёт одно пробное кодирование короткого сэмпла на итоговом CRF —
        и только если оценку есть кому показать (см. _wants_metric_score)."""
        xpsnr_score = None
        vmetric = sv.get('metric', 'none')
        if vmetric == 'xpsnr':
            target_metric = float(sv.get('target_metric', 40.0))
            metric_label = vmetric.upper()
            self.log.emit(f"🔍 подбор CRF под {metric_label} ≥{target_metric:.2f}…")
            cb(2, f"Подбор CRF под {metric_label} {target_metric:.2f}")
            found_crf, info = self._metric_crf_search(
                sample_input, preset_for_search, search_pix_fmt,
                vmetric, target_metric, vf_list, tune=video_tune,
                cancel_check=lambda: item["iid"] in self.removed_ids,
                on_tick=lambda el: cb(min(9, 2 + int(el // 3)),
                                      f"Подбор CRF под {metric_label} {target_metric:.2f} ({int(el)}с)"))
            if found_crf is not None:
                crf = found_crf
                self.log.emit(f"✅ подобран CRF {crf} ({metric_label} ≈{info})")
                # info — уже измеренная оценка НА ЭТОМ ЖЕ crf (подбор
                # останавливается на первом подходящем значении), повторно
                # мерить не нужно.
                try: xpsnr_score = float(info)
                except (TypeError, ValueError): xpsnr_score = None
            else:
                self.log.emit(f"⚠ подбор CRF не удался: {info} → использован ручной CRF {crf}")

        if xpsnr_score is None and self._wants_metric_score(sv):
            xpsnr_score = self._measure_at_crf(
                sample_input, crf, preset_for_search, search_pix_fmt,
                video_tune, vf_list, cancel_check=lambda: item["iid"] in self.removed_ids)
        self.xpsnr_sig.emit(item['iid'], xpsnr_score)
        return crf
