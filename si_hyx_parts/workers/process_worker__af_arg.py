# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""ProcessWorker: _af_arg. Public namespace: workers."""
import workers as _api


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
