# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""ProcessWorker: _av1_encoder_args. Public namespace: workers."""
import workers as _api


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
