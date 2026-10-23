# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""ProcessWorker: проект «Монтажа» настройками «Обработки» за одно кодирование."""
import hdr_tonemap
import montage_project as _mp
import workers as _api

# Длиннее — граф уходит в файл (-/filter_complex): у командной строки Windows
# предел 32 767 символов, а у проекта из сотни кусков граф длиннее.
_INLINE_GRAPH_MAX = 6000
# Сэмпл проекта для обрезки чёрных полос и подбора CRF: не длиннее этого,
# из середины — так же, как _make_metric_sample режет обычный файл.
_SAMPLE_MAX_S = 20.0


class ProcessProjectMixin:
    """Проект «Монтажа» (режим экспорта «Перекодировать настройками
    «Обработки»»): элемент очереди несёт item['project'] — Project.to_dict().

    Граф проекта (склейка кусков, смешивание звука — montage_project.
    build_source) становится входом, а цепочки «Обработки» (скорость, масштаб,
    фейды, loudnorm, fps) дописываются прямо в этот же filter_complex. Итог
    кодируется ОДИН раз — без промежуточного файла и второго поколения
    сжатия. Файл нужен только обрезке чёрных полос и замерам качества — для
    них рендерится короткий сэмпл из середины проекта."""

    def process_project(self, item, cb):
        proj = _mp.Project.from_dict(item['project'])
        sv = self.settings.get('video', {})
        sa = self.settings.get('audio', {})
        crf = sv.get('crf', 35)
        speed_percent = sv.get('speed', 100)
        speed_factor = float(speed_percent) / 100.0
        normal_speed = abs(speed_factor - 1.0) <= 0.01
        video_enabled = sv.get('enabled', True)

        is_video = proj.has_video() and not item.get('audio_only')
        has_audio = bool(proj.audio_parts())
        remove_audio = is_video and (bool(sa.get('remove')) or bool(item.get('remove_audio')))
        if not is_video and not has_audio:
            raise Exception("В проекте нет звука — обрабатывать нечего.")
        # HDR10-куски сводятся в SDR, как в просмотре Монтажа (hdr_tonemap).
        tonemap = (hdr_tonemap.tonemap_filters(
            (c.src for c in proj.clips if c.has_video and not c.is_image),
            _api.escape_filter_path) if is_video and item.get('sdr_tonemap') else {})
        src = _mp.build_source(proj, video=is_video, audio=has_audio and not remove_audio,
                               subs=item.get('project_subs') if is_video else None,
                               tonemap=tonemap)
        if src is None:
            raise Exception("Проект пуст — собирать нечего.")
        if is_video and video_enabled and not self.svt_available:
            raise Exception("libsvtav1 не доступен в вашей сборке ffmpeg — скрипт настроен работать ТОЛЬКО с svt (libsvtav1).")

        out_ext = ".mp4" if is_video else ".opus"
        out_name = self._sanitize_name(item.get('name') or "проект")
        suffix = self._out_suffix(is_video, video_enabled, sv.get('metric'), crf,
                                  speed_percent, remove_audio,
                                  sa.get('norm'), sa.get('fade'))
        out = _api.os.path.join(self._out_dir_for(item['path']), out_name + suffix + out_ext)
        out_dur = src.duration / speed_factor if speed_factor else src.duration

        chains = [src.graph]
        maps = []
        temp_files = []
        try:
            if src.audio:
                audio_filters = self._build_audio_filters(sa, 0.0, src.duration, speed_factor)
                chains.append(f"[aout]{self._af_arg(audio_filters, trim_tail=normal_speed)}[afin]")
                srcs = sorted({c.audio_path for c in proj.audio_parts()})
                sel_br = sa.get('bitrate', '128')
                audio_bitrate = max((self.get_target_bitrate_str(p, sel_br) for p in srcs),
                                    key=lambda b: int(b.rstrip('k') or 0), default="128k")
                audio_args = ["-map", "[afin]", "-c:a", "libopus", "-b:a", audio_bitrate]
            else:
                audio_args = ["-an"]

            if is_video:
                video_args = self._project_video_args(item, proj, src, sv, crf, speed_factor,
                                                      video_enabled, chains, temp_files, cb,
                                                      tonemap)
                maps = ["-map", "[vfin]"] + video_args
            else:
                maps = ["-vn"]

            graph = ";".join(chains)
            graph_args = ["-filter_complex", graph]
            if len(graph) > _INLINE_GRAPH_MAX:
                gfile = _api.os.path.join(_api.TEMP_DIR, f"projgraph_{_api.uuid.uuid4().hex}.txt")
                with open(gfile, "w", encoding="utf-8") as f:
                    f.write(graph)
                temp_files.append(gfile)
                graph_args = ["-/filter_complex", gfile]
            cmd = ([_api.FFMPEG, "-y", "-hide_banner"] + src.input_args() + graph_args
                   + maps + audio_args
                   + ["-map_metadata", "-1", "-t", f"{out_dur:.6f}"])
            if is_video:
                cmd += ["-movflags", "+faststart"]
            cmd += [out]

            calc = None
            if is_video:
                out_fps = src.fps
                if "-r" in cmd:
                    try: out_fps = float(cmd[cmd.index("-r") + 1])
                    except (ValueError, IndexError): pass
                frames = int(out_dur * out_fps)
                calc = _api.RealETACalculator(frames, pass_num=1, has_second_pass=False) if frames > 0 else None
            self.log.emit(f"Монтаж: проект «{out_name}» — {len(src.inputs)} входов, "
                          f"{out_dur:.1f} с, одно кодирование.")
            self.run_ffmpeg_capture(cmd, max(1, int(out_dur)), cb, label=None, eta_calc=calc,
                                    cancel_check=lambda: item["iid"] in self.removed_ids)
            if not _api.os.path.exists(out):
                raise Exception("Output file не найден после ffmpeg (возможная ошибка записи).")
            if src.audio and sa.get('norm'):
                try:
                    self.update_lufs_sig.emit(item['iid'], None, self.measure_loudness(out))
                except Exception: pass
            size_new = _api.os.path.getsize(out)
            dur_new, br_str, _, a_br, a_codec = _api.get_media_info(out)
            vcodec_new = _api.get_video_codec_label(out) if is_video else None
            size_label = f"{vcodec_new} {_api.human_size(size_new)}" if vcodec_new else _api.human_size(size_new)
            self.update_item_sig.emit(item['iid'], size_label,
                                      _api.fmt_bitrate_with_codec(a_codec, a_br or br_str))
            self.update_dur_sig.emit(item['iid'], str(dur_new or 0.0))
            return out
        except Exception as e:
            self.log.emit(f"Ошибка при обработке проекта: {e}")
            try:
                if _api.os.path.exists(out):
                    _api.os.remove(out)
            except OSError:
                pass
            raise
        finally:
            for t in temp_files:
                try:
                    if _api.os.path.exists(t): _api.os.remove(t)
                except OSError:
                    pass

    def _project_video_args(self, item, proj, src, sv, crf, speed_factor, video_enabled,
                            chains, temp_files, cb, tonemap):
        """Дописывает в chains видеоцепочку «Обработки» ([vout] → [vfin]) и
        возвращает аргументы кодирования видео. tonemap — как у build_source."""
        crop_black = bool(sv.get('crop_black'))
        sample = None
        if crop_black or (video_enabled and self._wants_metric_score(sv)):
            sample = self._project_sample(proj, temp_files, tonemap)
        vf_list = []
        if crop_black:
            crop = self._detect_crop(sample) if sample else None
            if crop:
                vf_list.append(f"crop={crop}")
                self.log.emit(f"✂ Обрезка чёрных полос: crop={crop}")
            else:
                self.log.emit("✂ Чёрные полосы не обнаружены — обрезка пропущена")
        vf_list += self._build_video_filters(
            dict(sv, crop_black=False), {'dur': src.duration}, None, None,
            0.0, 0.0, speed_factor, src_fps=src.fps)
        chains.append(f"[vout]{','.join(vf_list) or 'null'}[vfin]")

        fps_args = self._fps_args(sv.get('fps', 'Исходный') or 'Исходный', None,
                                  src_fps=src.fps)
        first = next((c for c in proj.clips if c.has_video and not c.is_image), None)
        if tonemap:
            color = list(hdr_tonemap.SDR_COLOR_ARGS)
        else:
            color = self._bt709_color_args(first.src) if first is not None else []
        if not video_enabled:
            # Копировать нечего: кадр проекта склеен из кусков. Видео кодирует
            # кодер Монтажа, всё остальное — по настройкам «Обработки».
            self.log.emit("«Перекодировать видео» выключено, но проект склеен из "
                          "кусков — видео кодируется кодером Монтажа.")
            return fps_args + color + list(item.get('fallback_venc') or
                                           ["-c:v", "libx264", "-preset", "fast", "-crf", "18"])

        pix_fmt = self._choose_pix_fmt(False)
        video_tune = int(sv.get('tune', 0))
        is_dark = sv.get('preset_mode', 'std') == "dark"
        preset_for_search = sv.get('pre', 0) if is_dark else sv.get('pre', 8)
        if sample:
            crf = self._resolve_crf(item, sv, crf, sample, preset_for_search, pix_fmt,
                                    video_tune, vf_list, cb)
        else:
            self.xpsnr_sig.emit(item['iid'], None)
        preset = max(0, min(13, sv.get('pre', 0))) if is_dark else max(0, min(8, sv.get('pre', 8)))
        if is_dark:
            self.log.emit("🌑 Тёмные сцены: кодирование (AV1 10-бит, CRF)...")
        return (fps_args + color + self._av1_encoder_args(crf, preset, pix_fmt, video_tune)
                + ["-threads", "0"])

    def _project_sample(self, proj, temp_files, tonemap):
        """Короткий кусок из середины проекта почти без потерь — вход для
        обрезки чёрных полос и подбора CRF (уже сведённый в SDR, как итог).
        None, если не получилось."""
        dur = proj.duration()
        take = min(_SAMPLE_MAX_S, dur)
        t0 = max(0.0, (dur - take) / 2.0)
        part = _mp.build_source(proj, audio=False, tonemap=tonemap, window=(t0, t0 + take))
        if part is None or not part.video:
            return None
        tmp = _api.os.path.join(_api.TEMP_DIR, f"projsample_{_api.uuid.uuid4().hex}.mkv")
        temp_files.append(tmp)
        cmd = ([_api.FFMPEG, "-y", "-hide_banner"] + part.input_args()
               + ["-filter_complex", part.graph, "-map", "[vout]",
                  "-c:v", "libx264", "-preset", "ultrafast", "-crf", "4",
                  "-an", "-t", f"{part.duration:.6f}", tmp])
        if not self._run_killable(cmd) or not _api.os.path.exists(tmp):
            self.log.emit("⚠ Не удалось собрать сэмпл проекта — обрезка полос и "
                          "подбор CRF пропущены.")
            return None
        return tmp

