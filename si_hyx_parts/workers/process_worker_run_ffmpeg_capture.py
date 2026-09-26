# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""ProcessWorker: run_ffmpeg_capture. Public namespace: workers."""
import workers as _api


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
