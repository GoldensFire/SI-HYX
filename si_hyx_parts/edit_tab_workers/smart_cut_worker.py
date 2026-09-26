# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""SmartCutWorker. Public namespace: edit_tab_workers."""
import edit_tab_workers as _api


class SmartCutWorker(_api.QThread):
    """Умная обрезка (Smart Cut). Основная часть видео между опорными кадрами
    копируется БЕЗ перекодирования (оригинальное качество и скорость), а
    перекодируются только короткие граничные участки от точек реза до ближайших
    ключевых кадров. Итог склеивается concat-демуксером.

    head: [in, kf_start)  — перекодировка (точное начало реза)
    mid:  [kf_start, kf_end) — copy видео (без потерь), аудио → AAC (для ровной склейки)
    tail: [kf_end, out)   — перекодировка (точный конец реза)

    Если умную обрезку выполнить нельзя (нет опорных кадров внутри отрезка, чужой
    видеокодек, ошибка склейки) — ПРОЗРАЧНЫЙ ОТКАТ на полную перекодировку отрезка,
    чтобы пользователь всегда получил корректный файл."""
    progress = _api.pyqtSignal(float)
    status = _api.pyqtSignal(str)
    finished = _api.pyqtSignal(bool, str)

    def __init__(self, src, in_s, out_s, out_path, venc, audio_index=None,
                 parent=None, no_audio=False):
        super().__init__(parent)
        self.src = str(src)
        self.in_s = float(in_s)
        self.out_s = float(out_s)
        self.out_path = out_path
        self.venc = list(venc)
        # Абсолютный индекс выбранной аудиодорожки (None → первая: 0:a:0). Без
        # него Smart Cut всегда брал дорожку по умолчанию, игнорируя выбор.
        self.audio_index = audio_index
        # Пункт «Нет» в списке дорожек Монтажа: результат без звука.
        self.no_audio = bool(no_audio)
        self._stopped = False
        self._procs = []
        self._tmpdir = None

    def stop(self):
        self._stopped = True
        for p in list(self._procs):
            try:
                if p.poll() is None:
                    p.kill()
            except Exception:
                pass

    def _run(self, cmd):
        if self._stopped:
            return 1
        from ffmpeg_faststart import with_faststart
        cmd = with_faststart(cmd)
        try:
            p = _api.subprocess.Popen(cmd, stdout=_api.subprocess.DEVNULL,
                                 stderr=_api.subprocess.DEVNULL,
                                 creationflags=_api.CREATE_NO_WINDOW)
        except Exception:
            return 1
        self._procs.append(p)
        rc = p.wait()
        try: self._procs.remove(p)
        except ValueError: pass
        return rc

    def _video_codec(self):
        try:
            r = _api.subprocess.run(
                [_api.FFPROBE, "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=codec_name", "-of", "csv=p=0", self.src],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", creationflags=_api.CREATE_NO_WINDOW, timeout=30)
            # csv_first: у ffprobe в конце строки остаётся разделитель («h264,»)
            return _api.csv_first(r.stdout)
        except Exception:
            return ""

    def _keyframes(self):
        """Тайминги ключевых кадров видео в окрестности [in, out] (по флагам
        пакетов, без декодирования — быстро)."""
        cmd = [_api.FFPROBE, "-v", "error", "-select_streams", "v:0",
               "-show_entries", "packet=pts_time,flags",
               "-read_intervals", f"{max(0.0, self.in_s - 2):.3f}%{self.out_s + 2:.3f}",
               "-of", "csv=p=0", self.src]
        try:
            r = _api.subprocess.run(cmd, capture_output=True, text=True,
                               encoding="utf-8", errors="replace",
                               creationflags=_api.CREATE_NO_WINDOW, timeout=60)
        except Exception:
            return []
        kfs = []
        for line in (r.stdout or "").splitlines():
            parts = line.split(",")
            if len(parts) >= 2 and parts[0] not in ("", "N/A") and "K" in parts[1]:
                try:
                    kfs.append(float(parts[0]))
                except Exception:
                    pass
        return sorted(kfs)

    # Общий timescale для всех сегментов: без него re-encode (libx264) и copy
    # имеют разную временную базу, и concat-демуксер вставляет рассинхрон на
    # стыке. 90000 — стандарт для видео.
    _TS = "90000"

    def _media_dur(self, path):
        """Длительность готового файла по контейнеру (для подгонки аудио к видео)."""
        try:
            r = _api.subprocess.run(
                [_api.FFPROBE, "-v", "error", "-show_entries", "format=duration",
                 "-of", "csv=p=0", path], capture_output=True, text=True,
                encoding="utf-8", errors="replace",
                creationflags=_api.CREATE_NO_WINDOW, timeout=30)
            return float(_api.csv_first(r.stdout) or 0.0)
        except Exception:
            return 0.0

    def _max_frame_gap(self, path):
        """(max_gap, median_gap) между соседними видео-пакетами склейки. Щель на
        стыке сегментов (open-GOP роняет хвостовые B-кадры у границы GOP при
        lossless-copy → дырка в 2–3 кадра) даёт max_gap заметно больше медианного
        интервала. Нужен, чтобы поймать НЕровную склейку и честно откатиться на
        полный реэнкод (он всегда кадрово-непрерывен)."""
        try:
            r = _api.subprocess.run(
                [_api.FFPROBE, "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "packet=pts_time", "-of", "csv=p=0", path],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", creationflags=_api.CREATE_NO_WINDOW, timeout=60)
        except Exception:
            return (0.0, 0.0)
        ts = sorted(
            float(x.replace(",", "")) for x in (r.stdout or "").split()
            if x.strip() and x.replace(",", "") not in ("", "N/A"))
        if len(ts) < 3:
            return (0.0, 0.0)
        gaps = sorted(ts[i + 1] - ts[i] for i in range(len(ts) - 1))
        return (gaps[-1], gaps[len(gaps) // 2])

    def _encode_seg(self, start, dur, out_file):
        """Перекодирует ВИДЕО граничного участка [start, start+dur) без звука.

        Ключевые моменты (выверены экспериментально на h264/aac):
        • ВХОДНОЙ seek (-ss ДО -i) + -t — первый кадр сегмента встаёт в 0.000;
          двухступенчатый seek (вход к ключевому + выход к точке) оставлял
          смещение ~0.08с и щель на стыке → «зависание первых кадров».
        • `-bf 0` — без B-кадров у границы нет задержки переупорядочивания
          (иначе первый PTS = 2 кадра → щель/смещение при concat).
        • общий `-video_track_timescale` — ровная склейка с copy-серединой.

        Звук НЕ кодируем посегментно: на каждом стыке AAC-кодер добавил бы
        priming/padding → провал звука. Берём звук единым проходом (_encode_audio).

        Тайминги форматируем с точностью .6f: округление до мс смещало срез на доли
        кадра — у copy это вырезало кадр у границы (дырка → щель на стыке)."""
        cmd = [_api.FFMPEG, "-y", "-ss", f"{start:.6f}", "-i", self.src,
               "-t", f"{dur:.6f}"] + self.venc + \
              ["-bf", "0", "-an", "-sn", "-video_track_timescale", self._TS,
               "-avoid_negative_ts", "make_zero", out_file]
        return self._run(cmd) == 0

    def _copy_seg(self, start, end, out_file):
        """Копирует середину [start, end) без перекодирования видео и БЕЗ звука.
        ВХОДНОЙ seek на ключевой кадр `start` + ОГРАНИЧЕНИЕ ДЛИТЕЛЬНОСТЬЮ `-t`.

        КРИТИЧНО: здесь НЕЛЬЗЯ `-avoid_negative_ts make_zero`. Он сдвигает
        таймстемпы в ноль, и тогда `-t`/`-to` перестают резать по длительности —
        copy захватывает ЛИШНИЕ GOP (замерено: с make_zero копия [106.4,127.2) =
        2 GOP давала 31с/749 кадров вместо 21с/498 → склейка длиннее запроса →
        предохранитель всегда откатывал на полный реэнкод; а если overshoot <1.5с,
        он проскакивал → «застывший кадр + лишняя секунда звука в конце»). Без
        make_zero `-t` режет ровно по длительности (498–500 кадров). Нулевой старт
        для стыка обеспечивает уже сам concat (`make_zero` на склейке). Общий
        `-video_track_timescale` оставляем — ровная склейка с re-encode-границами."""
        dur = max(0.0, end - start)
        cmd = [_api.FFMPEG, "-y", "-ss", f"{start:.6f}", "-i", self.src,
               "-t", f"{dur:.6f}", "-c:v", "copy", "-an", "-sn",
               "-video_track_timescale", self._TS, out_file]
        return self._run(cmd) == 0

    def _encode_audio(self, dur, out_file):
        """Кодирует звук ВЫБРАННОЙ дорожки от in_s РОВНО длиной dur (= длине
        склеенного видео) ОДНИМ проходом в AAC. `apad` добивает тишиной до полной
        длины, поэтому звук покрывает и ПОСЛЕДНИЙ кадр (без apad `-shortest` в mux
        обрезал звук по последнему ВИДЕО-пакету и на финальном кадре звука не было
        — «звук обрывается в конце»). Единый поток → нет провалов на стыках.
        Дорожка — self.audio_index (выбор пользователя), иначе первая 0:a:0.
        Возвращает True только если файл создан (источник без звука → False)."""
        if self.no_audio:
            return False
        amap = f"0:{self.audio_index}" if self.audio_index is not None else "0:a:0"
        cmd = [_api.FFMPEG, "-y", "-ss", f"{self.in_s:.6f}", "-i", self.src,
               "-t", f"{max(0.1, dur):.6f}", "-vn", "-sn",
               "-map", amap, "-af", "apad", "-c:a", "aac", "-b:a", "192k",
               "-avoid_negative_ts", "make_zero", out_file]
        return (self._run(cmd) == 0 and _api.os.path.exists(out_file)
                and _api.os.path.getsize(out_file) > 0)

    def _mux(self, video_file, audio_file, out_file):
        """Сводит готовую видео-дорожку с единой аудио-дорожкой без перекодировки.
        Звук уже точно равен длине видео (apad + -t = video_dur), поэтому БЕЗ
        `-shortest`: и последний кадр озвучен, и нет «застывшего» хвоста видео.
        muxdelay/muxpreload 0 + make_zero убирают начальное смещение контейнера."""
        cmd = [_api.FFMPEG, "-y", "-i", video_file, "-i", audio_file,
               "-map", "0:v:0", "-map", "1:a:0", "-c", "copy",
               "-avoid_negative_ts", "make_zero", "-muxpreload", "0",
               "-muxdelay", "0", out_file]
        return self._run(cmd) == 0

    def _full_reencode(self, out_file):
        """Откат: полная перекодировка отрезка одним проходом. ВХОДНОЙ seek
        (-ss ДО -i) + re-encode даёт кадрово-точный старт и не декодирует файл с
        нуля (выходной seek на in_s=100с тормозил бы). Один проход → звук
        непрерывен, провалов на стыках нет.

        КРИТИЧНО — маппим ВЫБРАННУЮ аудиодорожку. Без -map ffmpeg по умолчанию
        берёт дорожку с НАИБОЛЬШИМ числом каналов (напр. 5.1), а не выбранную
        пользователем 2.0 → «после обрезки звук стал другой». apad держит звук до
        последнего кадра (только когда дорожка точно есть)."""
        if self.no_audio:
            amap, aenc = ["-map", "0:v:0"], ["-an"]
        elif self.audio_index is not None:
            amap = ["-map", "0:v:0", "-map", f"0:{self.audio_index}"]
            aenc = ["-c:a", "aac", "-b:a", "192k", "-af", "apad"]
        else:
            # Дорожка не выбрана: optional-map первой аудио (источник без звука не
            # упадёт); apad НЕ ставим — на безаудийном входе фильтр бы ошибся.
            amap = ["-map", "0:v:0", "-map", "0:a:0?"]
            aenc = ["-c:a", "aac", "-b:a", "192k"]
        cmd = [_api.FFMPEG, "-y", "-ss", f"{self.in_s:.6f}", "-i", self.src,
               "-t", f"{self.out_s - self.in_s:.6f}"] + amap + self.venc + \
              aenc + ["-sn", out_file]
        return self._run(cmd) == 0

    def run(self):
        # Промежуточные сегменты ВСЕГДА в .mp4: только mp4-муксер уважает общий
        # -video_track_timescale, без которого re-encode и copy склеиваются со
        # сдвигом (mkv свой timescale игнорирует → щель на стыке mid→tail). В
        # пользовательский контейнер (mkv/…) перекладываем уже готовый результат
        # финальным mux/remux без перекодировки.
        ext = ".mp4"
        try:
            self._tmpdir = _api.tempfile.mkdtemp(prefix="sihyx_smartcut_")
        except Exception:
            self.finished.emit(False, "Не удалось создать временную папку"); return

        def _finish(ok, msg):
            try:
                import shutil
                if self._tmpdir:
                    shutil.rmtree(self._tmpdir, ignore_errors=True)
            except Exception:
                pass
            self.finished.emit(ok and not self._stopped, msg)

        try:
            self.status.emit("Smart Cut: анализ ключевых кадров…")
            self.progress.emit(3.0)
            vcodec = self._video_codec()
            kfs = self._keyframes()
            # Опорные кадры строго ВНУТРИ отрезка (с зазором, чтобы участки не
            # вырождались в ноль).
            inner = [t for t in kfs if self.in_s + 0.10 < t < self.out_s - 0.10]
            # Условия применимости умной обрезки: знаем кодек и есть ХОТЯ БЫ ДВА
            # опорных кадра внутри (нужны старт И конец copy-середины). При одном
            # kf_start==kf_end → copy «-ss X -to X» падает («-to value smaller than
            # -ss») и весь Smart Cut откатывался на реэнкод. Короткий клип (короче
            # ~2 GOP, частый случай: ~15с при GOP ~10с) копировать нечего — сразу
            # честный полный реэнкод (он теперь уважает выбранную аудиодорожку).
            if self._stopped:
                _finish(False, "Отменено"); return
            if vcodec not in ("h264", "hevc", "h265") or len(inner) < 2:
                self.status.emit("Smart Cut недоступен для отрезка — полная перекодировка…")
                self.progress.emit(10.0)
                ok = self._full_reencode(self.out_path)
                _finish(ok, "Готово (перекодировка)" if ok else "Ошибка перекодировки")
                return

            kf_start, kf_end = inner[0], inner[-1]
            head = _api.os.path.join(self._tmpdir, f"head{ext}")
            mid  = _api.os.path.join(self._tmpdir, f"mid{ext}")
            tail = _api.os.path.join(self._tmpdir, f"tail{ext}")
            segs = []

            # head: [in, kf_start) — только видео (входной seek прямо в in_s)
            self.status.emit("Smart Cut: граница начала…"); self.progress.emit(20.0)
            if kf_start - self.in_s > 0.04:
                if not self._encode_seg(self.in_s, kf_start - self.in_s, head):
                    raise RuntimeError("head encode failed")
                segs.append(head)

            # mid: [kf_start, kf_end) — copy без перекодировки (только видео)
            self.status.emit("Smart Cut: копирование середины…"); self.progress.emit(40.0)
            if not self._copy_seg(kf_start, kf_end, mid):
                raise RuntimeError("mid copy failed")
            segs.append(mid)

            # tail: [kf_end, out) — только видео
            self.status.emit("Smart Cut: граница конца…"); self.progress.emit(60.0)
            if self.out_s - kf_end > 0.04:
                if not self._encode_seg(kf_end, self.out_s - kf_end, tail):
                    raise RuntimeError("tail encode failed")
                segs.append(tail)

            if self._stopped:
                _finish(False, "Отменено"); return

            # Склейка ВИДЕО-сегментов (без звука) в единую дорожку.
            self.status.emit("Smart Cut: склейка…"); self.progress.emit(75.0)
            video_only = _api.os.path.join(self._tmpdir, f"video{ext}")
            listfile = _api.os.path.join(self._tmpdir, "list.txt")
            with open(listfile, "w", encoding="utf-8") as f:
                for s in segs:
                    f.write(f"file '{s.replace(chr(39), chr(92) + chr(39))}'\n")
            rc = self._run([_api.FFMPEG, "-y", "-f", "concat", "-safe", "0",
                            "-i", listfile, "-c", "copy", "-an",
                            "-avoid_negative_ts", "make_zero",
                            "-muxpreload", "0", "-muxdelay", "0", video_only])
            ok = (rc == 0 and _api.os.path.exists(video_only)
                  and _api.os.path.getsize(video_only) > 0)
            if not ok:
                # Склейка не удалась → откат на полную перекодировку.
                self.status.emit("Склейка не удалась — полная перекодировка…")
                ok = self._full_reencode(self.out_path)
                _finish(ok, "Готово (перекодировка)" if ok else "Ошибка Smart Cut")
                return

            if self._stopped:
                _finish(False, "Отменено"); return

            # ПРЕДОХРАНИТЕЛЬ ДЛИТЕЛЬНОСТИ: head/tail режутся точно по in_s/out_s, а
            # mid ограничен ключевыми кадрами внутри [in,out] — поэтому склейка
            # обязана быть ≈ (out_s−in_s). Если она заметно длиннее/короче (битый
            # индекс/таймстемпы редкого контейнера → copy захватил лишнее: «обрезал
            # 15с, получил 21с»), Smart Cut НЕНАДЁЖЕН для этого файла — честно
            # откатываемся на полную перекодировку (она всегда кадрово-точна).
            requested = self.out_s - self.in_s
            vdur = self._media_dur(video_only) or requested
            if abs(vdur - requested) > 1.5:
                self.status.emit("Smart Cut неточен для файла — полная перекодировка…")
                ok = self._full_reencode(self.out_path)
                _finish(ok, "Готово (перекодировка)" if ok else "Ошибка Smart Cut")
                return

            # ПРЕДОХРАНИТЕЛЬ СТЫКА: у open-GOP исходника (B-кадры ссылаются на
            # СЛЕДУЮЩИЙ ключевой) lossless-copy роняет 2–3 хвостовых B-кадра на
            # границе GOP → щель на стыке mid→tail (микро-рывок «застывший кадр»).
            # Кадров реально нет — концат её не закроет (проверено: даже filter-
            # concat с реэнкодом оставляет ту же щель). Если на склейке есть
            # аномальный разрыв между видео-пакетами (> 1.8× медианного интервала),
            # склейка неровная → честный откат на полный реэнкод (кадрово-непрерывен).
            # Чистая склейка (быстрый путь) проходит дальше без потерь.
            maxgap, medgap = self._max_frame_gap(video_only)
            if medgap > 0 and maxgap > medgap * 1.8:
                self.status.emit("Smart Cut: неровный стык — полная перекодировка…")
                ok = self._full_reencode(self.out_path)
                _finish(ok, "Готово (перекодировка)" if ok else "Ошибка Smart Cut")
                return

            # Звук единым проходом → подмешиваем к видео. Так на стыках сегментов
            # нет провалов AAC-priming (баг «звук обрывается и снова идёт»). Длину
            # звука берём РОВНО по длине склеенного видео (apad добьёт тишиной),
            # чтобы озвучить и последний кадр. Источник без звука → видео как есть.
            self.status.emit("Smart Cut: звук…"); self.progress.emit(88.0)
            audio = _api.os.path.join(self._tmpdir, "audio.m4a")
            if self._encode_audio(vdur, audio):
                if not self._mux(video_only, audio, self.out_path):
                    self.status.emit("Сведение не удалось — полная перекодировка…")
                    ok = self._full_reencode(self.out_path)
                    _finish(ok, "Готово (перекодировка)" if ok else "Ошибка Smart Cut")
                    return
            else:
                # Нет аудио-дорожки — перекладываем видео в контейнер результата
                # без перекодировки (intermediate всегда mp4, цель может быть mkv).
                rc = self._run([_api.FFMPEG, "-y", "-i", video_only, "-c", "copy",
                                "-an", "-avoid_negative_ts", "make_zero",
                                "-muxpreload", "0", "-muxdelay", "0",
                                self.out_path])
                if rc != 0 or not _api.os.path.exists(self.out_path):
                    import shutil
                    shutil.copyfile(video_only, self.out_path)
            ok = (_api.os.path.exists(self.out_path)
                  and _api.os.path.getsize(self.out_path) > 0)
            if not ok:
                raise RuntimeError("final output missing")
            self.progress.emit(100.0)
            _finish(True, "Готово (Smart Cut)")
        except Exception as e:
            if self._stopped:
                _finish(False, "Отменено"); return
            # Любая ошибка пайплайна → надёжный откат на полный реэнкод.
            try:
                self.status.emit(f"Smart Cut: откат на перекодировку ({e})")
                ok = self._full_reencode(self.out_path)
                _finish(ok, "Готово (перекодировка)" if ok else f"Ошибка Smart Cut: {e}")
            except Exception as e2:
                _finish(False, f"Ошибка Smart Cut: {e2}")

SmartCutWorker.__module__ = _api.__name__
_api.SmartCutWorker = SmartCutWorker
