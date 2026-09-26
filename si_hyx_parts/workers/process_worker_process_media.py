# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""ProcessWorker: process_media. Public namespace: workers."""
import workers as _api


def process_media(self, item, cb):
    path = item['path']
    base, ext = _api.os.path.splitext(path)
    out_dir = self._out_dir_for(path)
    sv = self.settings.get('video', {})
    sa = self.settings.get('audio', {})
    crf = sv.get('crf', 35)

    speed_percent = sv.get('speed', 100)
    speed_factor = float(speed_percent) / 100.0
    video_enabled = sv.get('enabled', True)

    # Обрезка + «Обработка» одним проходом (кнопка «Обрезать и обработать» в
    # Монтаже после неточной copy-обрезки): item['trim'] = (in_s, out_s) —
    # режем диапазон исходника ПРЯМО в этом же кодировании, без отдельного
    # x264-реэнкода перед «Обработкой» (которое раньше давало двойное
    # поколение потерь). trim_pre/trim_post вставляются туда, где команда
    # ПЕРВЫЙ раз читает оригинальный `path` (Pass-1, если он есть, иначе
    # Pass-2/прямой проход) — при video_enabled=True Pass-1 архитектурно не
    # запускается (см. step1_needed ниже), так что почти всегда это Pass-2.
    trim = item.get('trim')
    if trim:
        trim_pre, trim_post, t0 = self._trim_seek_args(trim[0], trim[1], speed_factor)
    else:
        trim_pre, trim_post, t0 = [], [], 0.0
    # Выбранная в Монтаже аудиодорожка (кнопка «Обрезать и обработать» на
    # многодорожечном источнике) — иначе -map "0:a?" всегда брал первую
    # дорожку контейнера, игнорируя выбор пользователя.
    audio_index = item.get('audio_index')
    a_map_sel = f"0:{audio_index}" if audio_index is not None else "0:a?"
    # t0 сдвинут видеофильтрам через setpts (он стоит РАНЬШЕ fade в vf_list —
    # к моменту fade PTS уже поделены на speed_factor), а аудиофильтрам —
    # БЕЗ деления (atempo в audio_filters добавляется В КОНЦЕ списка, после
    # fade-фильтров, так что на момент afade PTS ещё исходные).
    t0_video = (t0 / speed_factor) if speed_factor else t0

    vcodec = _api.get_video_codec(path)
    # «(Аудио) Перекодировать настройками «Обработки»» из Монтажа: видеоряд
    # источника игнорируем целиком и гоним ТОЛЬКО звук теми же настройками
    # (битрейт/loudnorm/fade/скорость), что и обычная «Обработка» — итог
    # .opus. Технически это ровно тот же путь, что и для файла БЕЗ видео,
    # поэтому просто гасим is_video: ниже он уже разводит аудио-онли ветку
    # (Pass-1 в opus + перенос) от видеокодирования.
    audio_only = bool(item.get('audio_only'))
    is_video = (vcodec is not None) and not audio_only

    out_ext = ".mp4" if is_video else ".opus"
    out_name = _api.os.path.basename(base)
    sanitized = self._sanitize_name(out_name)
    if sanitized != out_name:
        self.log.emit(f"Имя переименовано (AI-бренд): «{out_name}» → «{sanitized}»")
        out_name = sanitized

    # Удалить аудио — при видео полностью вырезаем звуковую дорожку (-an),
    # остальные аудио-настройки (loudnorm/fade/degrade/битрейт) тогда не
    # имеют смысла. Для аудио-файлов (is_video=False) галочка игнорируется —
    # вырезать звук из чистого аудио значило бы получить пустой файл.
    remove_audio = (bool(sa.get('remove')) or bool(item.get('remove_audio'))) and is_video

    suffix = self._out_suffix(is_video, video_enabled, sv.get('metric'), crf,
                              speed_percent, remove_audio,
                              sa.get('norm'), sa.get('fade'))
    out_name = out_name + suffix + out_ext
    out = _api.os.path.join(out_dir, out_name)

    sel_br = self.settings.get('audio', {}).get('bitrate', '128')
    audio_bitrate = self.get_target_bitrate_str(path, sel_br)

    before_lufs = None
    if not remove_audio:
        try:
            before_lufs = (self.measure_loudness(path, start=trim[0], dur=item.get('dur'))
                            if trim else self.measure_loudness(path))
        except Exception: pass
    # Замер громкости делается всегда (для «Было LUFS») и для длинных файлов
    # длится минуты — если за это время нажали «Стоп», прерываемся здесь же.
    if self.stop_flag:
        raise Exception("StoppedByUser")

    if is_video and video_enabled and not self.svt_available:
        raise Exception("libsvtav1 не доступен в вашей сборке ffmpeg — скрипт настроен работать ТОЛЬКО с svt (libsvtav1).")

    audio_filters = []
    if not remove_audio:
        # Длительность нужна только ветке fade-out — считаем её лениво (и
        # только когда fade включён), чтобы не дёргать ffprobe зря. dur мог не
        # посчитаться при добавлении (кириллица в пути, ffprobe упал) — тогда
        # читаем сейчас, когда файл точно доступен.
        fade_out_dur = 0.0
        if sa.get('fade'):
            fade_out_dur = item.get('dur') or 0.0
            if fade_out_dur <= 0.0:
                try:
                    fade_out_dur, *_ = _api.get_media_info(path)
                except Exception:
                    fade_out_dur = 0.0
        audio_filters = self._build_audio_filters(sa, t0, fade_out_dur, speed_factor)

    temp_files = []
    attempted_out = out

    try:
        current_input = path
        audio_codec = "libopus"  # opus в mp4
        # is_video уже учитывает audio_only (см. выше): для аудио-режима
        # кодек видео не важен вовсе — иначе HEVC-источник уводил бы звук в
        # лишний Pass-1 (результат тот же .opus, но проход впустую).
        is_hevc = bool(is_video and vcodec and ('hevc' in vcodec or 'h265' in vcodec))
        # Когда видео ВСЁ РАВНО перекодируется (step2), отдельный Pass-1 (аудио +
        # copy видео в .mkv) ВРЕДЕН: круговой проход через .mkv ломает тайминги —
        # видео становится CFR-30 (длиннее исходника), а задержка loudnorm/opus
        # превращается в стартовый сдвиг аудио (баг «итог длиннее исходника»).
        # Поэтому при перекодировании видео делаем ОДИН проход (аудиофильтры — в
        # step2). Pass-1 нужен только для аудио-онли/копии видео (вывод формирует
        # ветка else ниже).
        single_pass_video = bool(is_video and video_enabled)
        # Видео-КОПИЯ (перекодирование ВЫКЛ) с аудиофильтрами тоже обязана идти
        # ОДНИМ прямым проходом в .mp4. Прогон через .mkv-посредник ретаймит
        # видео в CFR-30 (177к×1/30=5.900 вместо VFR 5.702 → итог длиннее) и
        # навешивает opus CodecDelay на старт аудио (start_time=0.194 →
        # контейнер 6.02). Прямой `-c:v copy` mp4→mp4 сохраняет исходные PTS
        # пакетов, а aresample=async=1 подрезает хвост loudnorm до длины
        # источника. Только при нормальной скорости: смена скорости требует
        # setpts и несовместима с копией видео.
        single_pass_copy = bool(is_video and not video_enabled
                                and abs(speed_factor - 1.0) <= 0.01)
        step1_needed = (not single_pass_video) and (not single_pass_copy) and (
            is_hevc or bool(audio_filters) or (is_video and abs(speed_factor - 1.0) > 0.01))
        # Сохранять исходный тайминг кадров: VFR-источники (TikTok, записи экрана)
        # иначе растягиваются кодером до CFR-30 и итог становится длиннее. Только
        # при нормальной скорости и без принудительного fps.
        keep_timing = ((single_pass_video or single_pass_copy)
                       and abs(speed_factor - 1.0) <= 0.01
                       and str(sv.get('fps', 'Исходный')) == 'Исходный')

        # Кап длительности вывода = длине источника. Звук после loudnorm +
        # добивки Opus-кадров оказывается на ~50–70 мс длиннее видеодорожки
        # (audio.start_time 0.014 + dur 12.606 = 12.62 при video 12.554), и
        # контейнер (max по дорожкам) растёт. `-t` обрезает только лишний
        # аудиохвост: последний видеокадр PTS < длительности, поэтому видео не
        # теряется. Применяем, когда тайминг сохраняем и звук реально
        # перекодируется с фильтрами (без фильтров аудио копируется — роста нет).
        # Гейтим по СКОРОСТИ (не keep_timing): при изменённой скорости длина
        # вывода = src/speed ≠ src, поэтому -t src_dur был бы неверным. При
        # нормальной скорости итог обязан равняться источнику — даже если сменили
        # fps. Это вторая линия обороны к aresample=async=1 (тот даёт точную
        # длину, -t лишь срезает грубый выброс на кванте opus-кадра).
        normal_speed = abs(speed_factor - 1.0) <= 0.01
        src_dur_cap = item.get('dur') or 0.0
        if src_dur_cap <= 0.0:
            try: src_dur_cap, *_ = _api.get_media_info(path)
            except Exception: src_dur_cap = 0.0
        # dur_cap дублировал бы наш собственный -t из trim_post тем же числом
        # (src_dur_cap уже = item['dur'] = длине отрезка) — пропускаем, чтобы
        # не слать ffmpeg два -t подряд.
        dur_cap = (["-t", f"{float(src_dur_cap):.3f}"]
                   if (normal_speed and audio_filters and src_dur_cap > 0 and not trim) else [])

        if step1_needed:
            # Промежуточный контейнер для видео — Matroska: он принимает копию
            # ЛЮБОГО видеокодека + libopus. .mp4 же отвергает копию ряда
            # кодеков/потоков (легаси-видео, обложки) → "Invalid argument"
            # (exit -22). Финал всё равно делает step2 (AV1→mp4) или ремукс.
            temp_ext = ".mkv" if is_video else ".opus"
            temp_intermediate = _api.os.path.join(_api.TEMP_DIR, f"inter_{_api.uuid.uuid4().hex}{temp_ext}")
            temp_files.append(temp_intermediate)

            # current_input здесь всегда == path (Pass-1 — первый читатель
            # оригинала), поэтому trim_pre/trim_post режут именно исходник.
            cmd_step1 = [_api.FFMPEG, "-y"] + trim_pre + ["-i", current_input] + trim_post \
                        + self._map_av_args(remove_audio, a_map_sel) \
                        + ["-map_metadata", "-1"]
            if remove_audio:
                cmd_step1 += ["-an"]
            else:
                # Аудио-онли: этот Pass-1 И ЕСТЬ финальный файл (ветка else
                # ниже просто переносит .opus-посредник в вывод). Значит хвост
                # от latency loudnorm надо срезать ЗДЕСЬ, иначе итог длиннее
                # источника (без -t → 16.47→16.92). aresample=async=1 правит
                # старт/склейку, реальный кап длины даёт -t (ниже).
                cmd_step1 += ["-af", self._af_arg(
                    audio_filters,
                    trim_tail=bool((not is_video) and normal_speed and audio_filters))]
                cmd_step1 += ["-c:a", audio_codec, "-b:a", audio_bitrate]
            if is_video: cmd_step1 += ["-c:v", "copy"]
            else:
                cmd_step1 += ["-vn"]
                # Аудио-онли opus: контейнерная длительность = длине аудио-
                # дорожки. libopus ВСЕГДА добавляет фиксированную задержку
                # кодера (pre-skip 312 сэмплов = 6.5 мс @48кГц): эмпирически
                # итог = (-t) + 0.0065 РОВНО, независимо от длины/битрейта.
                # Поэтому -t компенсируем на pre-skip, чтобы длительность
                # совпала с источником точь-в-точь (иначе 16.470→16.4765,
                # округляется до 16.48). Срезаемые 6.5 мс — в самом конце, на
                # затухании, неслышны. Гейт как у dur_cap: нормальная скорость,
                # есть аудиофильтры, нет trim (при trim длину задаёт trim_post).
                if (not remove_audio and normal_speed and audio_filters
                        and src_dur_cap > 0 and not trim):
                    cmd_step1 += ["-t", f"{max(0.0, float(src_dur_cap) - 0.0065):.4f}"]
            cmd_step1 += [temp_intermediate]

            orig_size = _api.os.path.getsize(path) if _api.os.path.exists(path) else 1
            self.run_ffmpeg_capture(cmd_step1, max(1, int(orig_size/1000000)), cb, label="Pass 1 (Audio)", cancel_check=lambda: item["iid"] in self.removed_ids)
            current_input = temp_intermediate

            if not remove_audio:
                try:
                    after_norm = self.measure_loudness(temp_intermediate)
                    self.update_lufs_sig.emit(item['iid'], before_lufs, after_norm)
                except Exception: pass

        if is_video and video_enabled:
            if not self.svt_available: raise Exception("libsvtav1 отсутствует — отмена перекодирования.")
            # Аудио в одно-проходном режиме (Pass-1 пропущен): применяем
            # фильтры и кодируем opus прямо здесь. aresample=async=1 + отсутствие
            # .mkv-кругового прохода убирают сдвиг/удлинение аудио. Без фильтров —
            # копируем исходную дорожку без потерь.
            if remove_audio:
                step2_audio = ["-an"]
            elif single_pass_video and audio_filters:
                # trim_tail завязан ТОЛЬКО на скорость, не на keep_timing/fps:
                # подрезка хвоста нужна и когда сменили fps (см. _af_arg).
                step2_audio = ["-af", self._af_arg(audio_filters, trim_tail=normal_speed),
                               "-c:a", audio_codec, "-b:a", audio_bitrate]
            else:
                step2_audio = ["-c:a", "copy"]
            timing_args = ["-fps_mode", "passthrough"] if keep_timing else []
            # current_input здесь всегда == path: step1_needed исключает
            # single_pass_video (см. выше), поэтому trim ещё не применён.
            cmd_step2 = [_api.FFMPEG, "-y"] + trim_pre + ["-i", current_input] + trim_post \
                        + self._map_av_args(remove_audio, a_map_sel) + timing_args \
                        + ["-map_metadata", "-1", "-map_chapters", "-1"]

            vf_list = self._build_video_filters(sv, item, current_input, trim,
                                                t0, t0_video, speed_factor)
            # Наложенные картинки из Монтажа (режим обрезки «Перекодировать
            # настройками «Обработки»»): PNG приходят уже отрисованными под
            # размер ИСХОДНОГО кадра, поэтому overlay идёт ПЕРВЫМ — до
            # crop/scale/fade, ровно как накладка видна в плеере Монтажа.
            # `format=` берём по pix_fmt исходника: при `auto` граф с RGBA
            # уводил весь кадр в RGB и цвет итога уезжал (см.
            # overlay_chroma_format).
            vf_arg = self._overlay_vf(vf_list, item, current_input)
            # Пробные кодирования подбора CRF/оценки меряют ТОТ ЖЕ кадр, что
            # уйдёт в файл, — иначе метрика считалась бы по картинке без
            # накладок.
            vf_list = [vf_arg] if vf_arg else []

            # FPS из настроек — ОДИН раз на оба профиля («Стандартный» и
            # «Тёмные сцены»). Раньше `-r` дописывался только к cmd_step2, и
            # в профиле «Тёмные сцены» настройка FPS молча игнорировалась:
            # 60-кадровый источник с «Исходный (max 30)» выходил как 60 fps.
            fps_args = self._fps_args(sv.get('fps', 'Исходный') or 'Исходный',
                                      current_input)
            cmd_step2 += fps_args

            preset_mode = sv.get('preset_mode', 'std')
            is_dark_scenes = (preset_mode == "dark")
            # tune SVT-AV1 (0=VQ/1=PSNR/2=SSIM/4=MS-SSIM/5=VMAF), выбирается
            # в настройках (c_tune в tabs.py) — см. _av1_encoder_args.
            video_tune = int(sv.get('tune', 0))

            # Метрика: 'none' — ручной CRF как есть; 'xpsnr' — CRF на этот
            # файл подбирается самостоятельно (_metric_crf_search, без
            # внешних инструментов) под целевое значение метрики (кодек
            # всегда SVT-AV1, тюнинг энкодера — video_tune выше, тот же,
            # что и в финальном кодировании — см. _av1_encoder_args).

            # preset/pix_fmt для пробных кодирований (поиск CRF и/или разовый
            # замер итоговой оценки XPSNR) — те же, что пойдут в реальный
            # финальный энкод этого профиля (см. is_dark_scenes/else дальше).
            preset_for_search = sv.get('pre', 0) if is_dark_scenes else sv.get('pre', 8)
            search_pix_fmt = self._choose_pix_fmt(self._source_has_alpha(current_input))
            # Сэмпл строится ОДИН раз и переживает и подбор CRF, и
            # последующий разовый замер оценки — поэтому убираем его здесь.
            # Когда замеров не будет вовсе (метрика выкл. и колонка оценки
            # скрыта — поведение по умолчанию), нарезка сэмпла тоже не
            # нужна: это лишний проход и копия отрезка в %TEMP%.
            if self._wants_metric_score(sv):
                metric_sample_input, metric_sample_tmp = self._make_metric_sample(
                    current_input, trim)
            else:
                metric_sample_input, metric_sample_tmp = current_input, None
            try:
                crf = self._resolve_crf(item, sv, crf, metric_sample_input,
                                        preset_for_search, search_pix_fmt,
                                        video_tune, vf_list, cb)
            finally:
                if metric_sample_tmp:
                    try:
                        if _api.os.path.exists(metric_sample_tmp): _api.os.remove(metric_sample_tmp)
                    except Exception: pass

            if is_dark_scenes:
                # Профиль «Тёмные сцены»: 10-бит, одно-проходный CRF AV1.
                # SVT-AV1 НЕ поддерживает multi-pass в режиме CRF
                # ("CRF does not support multi-pass. Use single pass."),
                # поэтому используем один проход. Для CRF (постоянное качество)
                # 2-pass всё равно не даёт выигрыша. crf — либо ручной, либо
                # уже подобран _metric_crf_search под целевую метрику (см. блок выше).
                has_alpha = self._source_has_alpha(current_input)
                pix_fmt = self._choose_pix_fmt(has_alpha)
                preset_val = max(0, min(13, sv.get('pre', 0)))
                est = max(1, int(_api.os.path.getsize(current_input)/400000)) if _api.os.path.exists(current_input) else 10

                cmd_dark = [
                    _api.FFMPEG, "-y",
                ] + trim_pre + ["-i", current_input] + trim_post \
                  + self._map_av_args(remove_audio, a_map_sel) + timing_args + ["-map_metadata", "-1", "-map_chapters", "-1"] \
                  + self._bt709_color_args(current_input) + fps_args \
                  + self._av1_encoder_args(crf, preset_val, pix_fmt, video_tune)
                if vf_arg:
                    cmd_dark += ["-vf", vf_arg]
                cmd_dark += ["-threads", "0"] + step2_audio + dur_cap
                if _api.os.path.splitext(attempted_out)[1].lower() == ".mp4":
                    cmd_dark += ["-movflags", "+faststart"]
                cmd_dark += [attempted_out]

                self.log.emit("🌑 Тёмные сцены: кодирование (AV1 10-бит, CRF)...")
                # Адаптивное ETA по окну FPS (один проход CRF → has_second_pass=False).
                _tf = self._estimate_total_frames(current_input, speed_factor, cmd_dark,
                                                   dur_override=(item.get('dur') if trim else None))
                _calc = _api.RealETACalculator(_tf, pass_num=1, has_second_pass=False) if _tf > 0 else None
                self.run_ffmpeg_capture(cmd_dark, est, cb, label="AV1 кодирование (тёмные сцены)", eta_calc=_calc, cancel_check=lambda: item["iid"] in self.removed_ids)

            else:
                # Стандартный профиль
                has_alpha = self._source_has_alpha(current_input)
                pix_fmt = self._choose_pix_fmt(has_alpha)

                if has_alpha and 'libvpx-vp9' in _api.detect_ffmpeg_encoders():
                    # libsvtav1 не поддерживает yuva420p → переключаемся на VP9+WebM.
                    # 10-бит альфа (yuva420p10le) в libvpx-vp9 — экспериментальный
                    # и «не широко поддерживаемый» формат (ffmpeg сам предупреждает
                    # и требует -strict experimental), поэтому здесь принудительно
                    # 8-бит yuva420p — единственный надёжно совместимый вариант для
                    # прозрачного WebM.
                    self.log.emit("Альфа-канал → выход: VP9 WebM (SVT-AV1 alpha не поддерживает)")
                    attempted_out = _api.os.path.splitext(attempted_out)[0] + ".webm"
                    out = attempted_out
                    cmd_step2 += ["-c:v", "libvpx-vp9",
                                  "-crf", str(crf), "-b:v", "0",
                                  "-pix_fmt", "yuva420p"]
                elif has_alpha:
                    self.log.emit("⚠ libvpx-vp9 недоступен — альфа будет потеряна (SVT-AV1 alpha не поддерживает)")
                    cmd_step2 += self._bt709_color_args(current_input)
                    cmd_step2 += self._av1_encoder_args(crf, max(0, min(8, sv.get('pre', 8))), self._choose_pix_fmt(False), video_tune)
                else:
                    cmd_step2 += self._bt709_color_args(current_input)
                    cmd_step2 += self._av1_encoder_args(crf, max(0, min(8, sv.get('pre', 8))), pix_fmt, video_tune)

                if vf_arg: cmd_step2 += ["-vf", vf_arg]
                cmd_step2 += ["-threads", "0"] + step2_audio + dur_cap
                if _api.os.path.splitext(attempted_out)[1].lower() == ".mp4":
                    cmd_step2 += ["-movflags", "+faststart"]
                cmd_step2 += [attempted_out]

                est = max(1, int(_api.os.path.getsize(current_input)/400000)) if _api.os.path.exists(current_input) else 10
                # Адаптивное ETA по скользящему окну FPS (одно-проходный CRF).
                _tf = self._estimate_total_frames(current_input, speed_factor, cmd_step2,
                                                   dur_override=(item.get('dur') if trim else None))
                _calc = _api.RealETACalculator(_tf, pass_num=1, has_second_pass=False) if _tf > 0 else None
                self.run_ffmpeg_capture(cmd_step2, est, cb, label="Pass 2 (Video)", eta_calc=_calc, cancel_check=lambda: item["iid"] in self.removed_ids)

        else:
            if current_input != path:
                inter_ext = _api.os.path.splitext(current_input)[1].lower()
                if inter_ext == out_ext:
                    if _api.os.path.exists(out): _api.os.remove(out)
                    _api.shutil.move(current_input, out)  # step1 уже применил libopus, просто переносим
                else:
                    # Контейнер промежуточного (.mkv) ≠ выходной → ремукс копией
                    # (видео уже в нужном кодеке, аудио — libopus из step1).
                    cmd_remux = [_api.FFMPEG, "-y", "-i", current_input,
                                 "-map", "0:V?", "-map", "0:a?",
                                 "-c", "copy", out]
                    self.run_ffmpeg_capture(
                        cmd_remux,
                        max(1, int(_api.os.path.getsize(current_input) / 1000000)),
                        cb, label=None, cancel_check=lambda: item["iid"] in self.removed_ids)
            else:
                # Один прямой проход (видео-копия с аудиофильтрами или аудио-онли).
                # Для видео-копии (single_pass_copy): passthrough сохраняет VFR-
                # тайминг при `-c:v copy`, а aresample=async=1 убирает хвост
                # loudnorm/опус-сдвиг — итог точно равен длине источника.
                af_direct = self._af_arg(
                    audio_filters,
                    trim_tail=bool(is_video and normal_speed and audio_filters))
                # Видео тут НЕ перекодируется (-c:v copy) — при заданном trim
                # рез всё равно останется привязан к ближайшему ключевому
                # кадру (как обычная copy-обрезка), кадровая точность здесь
                # принципиально недостижима без реэнкода видео.
                cmd_direct = [_api.FFMPEG, "-y"] + trim_pre + ["-i", path] + trim_post \
                             + self._map_av_args(remove_audio, a_map_sel)
                if is_video and keep_timing:
                    cmd_direct += ["-fps_mode", "passthrough"]
                if remove_audio:
                    cmd_direct += ["-an"]
                else:
                    cmd_direct += ["-af", af_direct]
                    cmd_direct += ["-c:a", audio_codec, "-b:a", audio_bitrate]
                if is_video: cmd_direct += ["-c:v", "copy"]
                else: cmd_direct += ["-vn"]
                # Видео-КОПИЯ + аудиофильтры: loudnorm/opus добавляют «хвост»,
                # из-за которого итог длиннее источника. dur_cap (-t = длине
                # источника) обрезает лишний аудиохвост — см. определение выше.
                cmd_direct += dur_cap
                cmd_direct += [out]
                self.run_ffmpeg_capture(cmd_direct, max(1, int(_api.os.path.getsize(path)/1000000)), cb, label=None, cancel_check=lambda: item["iid"] in self.removed_ids)

        if _api.os.path.exists(out):
            # «После» LUFS: в одно-проходном режиме Pass-1 (где раньше мерили)
            # пропущен — меряем по готовому файлу.
            if not remove_audio and (single_pass_video or single_pass_copy) and sa.get('norm'):
                try:
                    after_norm = self.measure_loudness(out)
                    self.update_lufs_sig.emit(item['iid'], before_lufs, after_norm)
                except Exception: pass
            size_new = _api.os.path.getsize(out)
            dur_new, br_str, _, a_br, a_codec = _api.get_media_info(out)
            vcodec_new = _api.get_video_codec_label(out) if is_video else None
            size_label = f"{vcodec_new} {_api.human_size(size_new)}" if vcodec_new else _api.human_size(size_new)
            self.update_item_sig.emit(item['iid'], size_label,
                                      _api.fmt_bitrate_with_codec(a_codec, a_br or br_str))
            self.update_dur_sig.emit(item['iid'], str(dur_new or 0.0))
            return out
        else:
            raise Exception("Output file не найден после ffmpeg (возможная ошибка записи).")

    except Exception as e:
        errstr = str(e)
        self.log.emit(f"Ошибка при обработке {_api.os.path.basename(path)}: {errstr}")
        try:
            if _api.os.path.exists(attempted_out) and _api.os.path.abspath(attempted_out) != _api.os.path.abspath(path):
                try:
                    _api.os.remove(attempted_out)
                    self.log.emit(f"Удалён повреждённый/недозаписанный выход: {attempted_out}")
                except Exception: pass
        except Exception: pass
        for t in temp_files:
            if _api.os.path.exists(t):
                try:
                    _api.os.remove(t)
                    self.log.emit(f"Удалён временный файл: {t}")
                except Exception: pass
        raise
    finally:
        for t in temp_files:
            if _api.os.path.exists(t):
                try: _api.os.remove(t)
                except Exception: pass
