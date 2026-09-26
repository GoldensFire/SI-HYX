# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""ProxyWorker. Public namespace: edit_tab_workers."""
import edit_tab_workers as _api


class ProxyWorker(_api.QThread):
    finished = _api.pyqtSignal(bool, str, str)
    progress = _api.pyqtSignal(str)   # текст прогресса для волны: «Создание превью… N%»

    def __init__(self, input_path, output_path, parent=None, scale=1.0,
                 duration=0.0, limit_sec=0.0):
        super().__init__(parent)
        self.input_path = input_path
        self.output_path = output_path
        # scale<1.0 → прокси меньшего разрешения (быстрее воспроизведение/перемотка,
        # как «качество предпросмотра» в Filmora). 1.0 → только смена кодека.
        self.scale = float(scale) if scale else 1.0
        # limit_sec>0 → прокси только для первых N секунд файла (быстрее собрать
        # для тяжёлых/длинных видео; предпросмотр ограничен этим отрезком).
        self.limit_sec = float(limit_sec or 0.0)
        full = float(duration or 0.0)
        # Для процентов: если прокси усечён, ориентируемся на длину отрезка.
        self.total_dur = (min(full, self.limit_sec)
                          if (self.limit_sec > 0 and full > 0) else full)
        self.proc = None
        self._stopped = False

    def _run_with_progress(self, cmd, feed_path=None):
        """Запуск ffmpeg с -progress pipe:1 — по out_time_us показываем проценты
        создания прокси (как при извлечении аудио для H.264).

        stderr читаем ОТДЕЛЬНЫМ потоком, а не через communicate() после цикла по
        stdout. Иначе — взаимная блокировка: уже стартовый баннер ffmpeg (сведения
        о входе, libdav1d/libx264, длинная строка опций x264) больше буфера
        анонимного pipe в Windows (~4 КБ). ffmpeg повисает на записи в stderr →
        не пишет прогресс в stdout → наш `for line in stdout` ждёт строку, которой
        не будет → communicate() (он же дренаж stderr) недостижим. Для AV1 это
        100% дедлок («бесконечное создание превью»): AV1 — единственный путь, что
        вообще идёт через прокси (H.264 играется напрямую)."""
        full = cmd[:1] + ["-progress", "pipe:1", "-nostats"] + cmd[1:]
        self.proc = _api.subprocess.Popen(
            full, stdin=(_api.subprocess.PIPE if feed_path else None),
            stdout=_api.subprocess.PIPE, stderr=_api.subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace",
            creationflags=_api.CREATE_NO_WINDOW)
        if feed_path:
            _api.start_share_delete_feeder(
                feed_path, self.proc.stdin, stop_flag=lambda: self._stopped)
        # Фоновый слив stderr — держим pipe пустым, чтобы ffmpeg не блокировался.
        err_chunks = []
        def _drain_err(pipe):
            try:
                for line in pipe:
                    err_chunks.append(line)
            except Exception:
                pass
        err_thread = _api.threading.Thread(target=_drain_err, args=(self.proc.stderr,),
                                      daemon=True)
        err_thread.start()
        last_pct = -1
        try:
            for line in self.proc.stdout:
                if self._stopped:
                    break
                line = line.strip()
                if self.total_dur > 0 and line.startswith("out_time_us="):
                    try:
                        us = int(line.split("=", 1)[1])
                        pct = max(0, min(99, int(us / (10000.0 * self.total_dur))))
                        if pct != last_pct:
                            last_pct = pct
                            self.progress.emit(f"Создание превью… {pct}%")
                    except Exception:
                        pass
        except Exception:
            pass
        self.proc.wait()
        err_thread.join(timeout=2.0)
        return self.proc.returncode, "".join(err_chunks)

    def run(self):
        # scale filter ensures even dimensions required by libx264. При scale<1
        # дополнительно уменьшаем кадр (превью-прокси).
        if self.scale < 0.999:
            vf = f"scale=trunc(iw*{self.scale}/2)*2:trunc(ih*{self.scale}/2)*2"
        else:
            vf = "scale=trunc(iw/2)*2:trunc(ih/2)*2"
        # Прокси оптимизирован под ПЕРЕМОТКУ (как proxy/optimized media в Filmora),
        # а не под размер:
        #   -g 12 -keyint_min 12 -sc_threshold 0 — ключевой кадр каждые ~0.5 с.
        #     При перемотке декодер стартует с ближайшего ключевого кадра; частые
        #     keyframe'ы = почти мгновенный seek (у исходных аниме-BDRip GOP до
        #     250+ кадров → каждый скраб декодирует секунды видео).
        #   -tune fastdecode — отключает deblock/CABAC ради скорости ДЕКОДИРОВАНИЯ
        #     (для превью-прокси качество вторично, важна лёгкость проигрывания).
        #   -pix_fmt yuv420p — 8-бит 4:2:0: 10-битные/4:4:4 источники иначе тянут
        #     медленный software-путь в QtMultimedia.
        #   +faststart — moov в начало файла: плеер открывает и сикает сразу.
        # -t N (выходная опция, после -i) — кодируем только первые N секунд.
        limit = ["-t", f"{self.limit_sec:.3f}"] if self.limit_sec > 0 else []

        def _base(src):
            return [
                _api.FFMPEG, "-y", "-i", src,
            ] + limit + [
                "-c:v", "libx264", "-preset", "ultrafast", "-tune", "fastdecode",
                "-crf", "23", "-pix_fmt", "yuv420p",
                "-g", "12", "-keyint_min", "12", "-sc_threshold", "0",
                "-vf", vf,
                "-movflags", "+faststart",
            ]

        # -map 0:v:0 + -map 0:a? — берём первое видео и ВСЕ аудиодорожки
        # исходника, чтобы в превью-режиме (когда играет прокси) переключение
        # озвучки работало так же, как на оригинале. Без явного -map ffmpeg клал
        # в прокси только дорожку по умолчанию → выбор другой озвучки в превью
        # не срабатывал (плеер видел всего одну дорожку).
        # Сначала кормим вход через FILE_SHARE_DELETE-пайп (исходник остаётся
        # удаляемым из Проводника, пока строится прокси); при неудаче — прямой вход.
        feed = str(self.input_path) if _api.os.name == 'nt' else None
        cmds = []
        if feed:
            pbase = _base("pipe:0")
            cmds += [(pbase + ["-map", "0:v:0", "-map", "0:a?", "-c:a", "aac",
                               self.output_path], feed),
                     (pbase + ["-map", "0:v:0", "-an", self.output_path], feed)]
        fbase = _base(str(self.input_path))
        cmds += [(fbase + ["-map", "0:v:0", "-map", "0:a?", "-c:a", "aac",
                           self.output_path], None),
                 (fbase + ["-map", "0:v:0", "-an", self.output_path], None)]
        last_error = "неизвестная ошибка"
        for cmd, feed_path in cmds:
            if self._stopped:
                self.finished.emit(False, "Отменено", "")
                return
            try:
                self.progress.emit("Создание превью…")
                rc, err = self._run_with_progress(cmd, feed_path=feed_path)
                if self._stopped:
                    self.finished.emit(False, "Отменено", "")
                    return
                # rc==0 не гарантия успеха: mov/mp4 с moov в конце файла (не
                # +faststart) через НЕ-seekable pipe:0 ffmpeg демуксит с ошибкой
                # «partial file»/«Invalid data…», но всё равно завершается кодом 0,
                # написав пустой (~200 байт, только ftyp) выходной файл — баг
                # воспроизводился на реальном AV1+Opus исходнике без faststart
                # (итог: «в Монтаже ни картинки, ни звука»). Поэтому после pipe-
                # попытки проверяем реальный размер результата, а не только rc —
                # иначе следующая (рабочая) команда с прямым файловым входом даже
                # не пробуется.
                if rc == 0 and self._looks_like_real_output(err):
                    self.finished.emit(True, "OK", self.output_path)
                    return
                last_error = (err or "")[-600:] or f"код {rc}"
            except Exception as e:
                last_error = str(e)
        self.finished.emit(False, last_error, "")

    def _looks_like_real_output(self, err_text=""):
        if "Output file is empty" in (err_text or ""):
            return False
        try:
            return _api.os.path.getsize(self.output_path) > 4096
        except OSError:
            return False

    def stop(self):
        self._stopped = True
        p = self.proc
        if p and p.poll() is None:
            try:
                p.kill()
            except Exception:
                pass

ProxyWorker.__module__ = _api.__name__
_api.ProxyWorker = ProxyWorker
