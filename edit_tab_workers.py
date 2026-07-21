# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
# edit_tab_workers.py — фоновые воркеры вкладки «Монтаж»: резка (ffmpeg/Smart Cut),
# прокси-превью, загрузка звуковой волны, извлечение субтитров, удаление объектов.
# Слой поверх edit_tab_base.

import os
import subprocess
import sys
import tempfile
import threading
import wave
from config import (CREATE_NO_WINDOW, FFMPEG, FFPROBE, QThread, pyqtSignal)
from edit_tab_base import (_parse_srt, time_to_s)
from PyQt6.QtCore import (QIODevice)
from PyQt6.QtGui import (QImage)



class ShareDeleteIODevice(QIODevice):
    """QIODevice поверх файла, открытого с FILE_SHARE_DELETE (Windows).

    Зачем: QMediaPlayer, играя файл напрямую (setSource(file://…)), держит его
    так, что Проводник не даёт файл удалить («занят другим процессом»). Если же
    скормить плееру этот девайс (setSourceDevice), файл открыт с правом общего
    удаления — пользователь спокойно удаляет исходник прямо во время монтажа
    (Windows физически уберёт его, когда плеер отпустит хэндл). Перемотка
    работает: девайс произвольного доступа (isSequential=False, есть seek)."""

    def __init__(self, path, parent=None):
        super().__init__(parent)
        self._path = str(path)
        self._h = None
        try:
            self._sz = os.path.getsize(self._path)
        except Exception:
            self._sz = 0

    def open(self, mode=QIODevice.OpenModeFlag.ReadOnly):
        if os.name != 'nt':
            return False
        try:
            import ctypes
            from ctypes import wintypes
            k32 = ctypes.windll.kernel32
            k32.CreateFileW.restype = wintypes.HANDLE
            k32.CreateFileW.argtypes = [
                wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
            GENERIC_READ = 0x80000000
            SHARE_ALL = 0x1 | 0x2 | 0x4          # READ | WRITE | DELETE
            OPEN_EXISTING = 3
            NORMAL = 0x80
            INVALID = ctypes.c_void_p(-1).value
            h = k32.CreateFileW(self._path, GENERIC_READ, SHARE_ALL, None,
                                OPEN_EXISTING, NORMAL, None)
            if not h or h == INVALID:
                return False
            self._h = h
            self._k32 = k32
            return super().open(QIODevice.OpenModeFlag.ReadOnly)
        except Exception:
            return False

    def isSequential(self):
        return False

    def size(self):
        return self._sz

    def seek(self, pos):
        try:
            import ctypes
            from ctypes import wintypes
            self._k32.SetFilePointerEx.argtypes = [
                wintypes.HANDLE, ctypes.c_longlong,
                ctypes.POINTER(ctypes.c_longlong), wintypes.DWORD]
            self._k32.SetFilePointerEx(wintypes.HANDLE(self._h),
                                       ctypes.c_longlong(int(pos)), None, 0)
        except Exception:
            return False
        return super().seek(pos)

    def readData(self, maxlen):
        if not self._h:
            return b''
        try:
            import ctypes
            from ctypes import wintypes
            n = int(maxlen)
            if n <= 0:
                return b''
            buf = ctypes.create_string_buffer(n)
            rd = wintypes.DWORD(0)
            ok = self._k32.ReadFile(wintypes.HANDLE(self._h), buf, n,
                                    ctypes.byref(rd), None)
            if not ok:
                return b''
            return bytes(buf.raw[:rd.value])
        except Exception:
            return b''

    def close(self):
        try:
            if self._h:
                import ctypes
                from ctypes import wintypes
                self._k32.CloseHandle(wintypes.HANDLE(self._h))
        except Exception:
            pass
        self._h = None
        try:
            super().close()
        except Exception:
            pass


def start_share_delete_feeder(path, stdin, stop_flag=None):
    """Фоновый поток: читает файл с FILE_SHARE_DELETE и пишет его байты в stdin
    запущенного ffmpeg (вход «pipe:0»). Зачем: ffmpeg, открывая файл напрямую,
    держит его без права удаления, и Проводник не даёт удалить исходник (а тем
    более папку с ним), пока крутится фоновый воркер (волна/прокси). Если же
    кормить ffmpeg через этот поток, файл открыт нами с FILE_SHARE_DELETE —
    пользователь спокойно удаляет исходник прямо во время монтажа.

    stop_flag — необязательный callable → True для досрочной остановки. Возвращает
    запущенный поток-демон. stdin закрывается по достижении конца файла."""
    out = getattr(stdin, "buffer", stdin)   # бинарный канал даже при text=True

    def _pump():
        h = None
        k32 = None
        f = None
        try:
            if os.name == 'nt':
                import ctypes
                from ctypes import wintypes
                k32 = ctypes.windll.kernel32
                k32.CreateFileW.restype = wintypes.HANDLE
                k32.CreateFileW.argtypes = [
                    wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                    ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
                GENERIC_READ = 0x80000000
                SHARE_ALL = 0x1 | 0x2 | 0x4          # READ | WRITE | DELETE
                OPEN_EXISTING = 3
                NORMAL = 0x80
                INVALID = ctypes.c_void_p(-1).value
                hh = k32.CreateFileW(str(path), GENERIC_READ, SHARE_ALL, None,
                                     OPEN_EXISTING, NORMAL, None)
                if hh and hh != INVALID:
                    h = hh
                if h is not None:
                    buf = ctypes.create_string_buffer(1 << 20)
                    rd = wintypes.DWORD(0)
                    while stop_flag is None or not stop_flag():
                        ok = k32.ReadFile(wintypes.HANDLE(h), buf, len(buf),
                                          ctypes.byref(rd), None)
                        if not ok or rd.value == 0:
                            break
                        try:
                            out.write(buf.raw[:rd.value])
                        except Exception:
                            break
            else:
                f = open(str(path), 'rb')
                while stop_flag is None or not stop_flag():
                    data = f.read(1 << 20)
                    if not data:
                        break
                    try:
                        out.write(data)
                    except Exception:
                        break
        except Exception:
            pass
        finally:
            if h is not None:
                try:
                    import ctypes
                    from ctypes import wintypes
                    ctypes.windll.kernel32.CloseHandle(wintypes.HANDLE(h))
                except Exception:
                    pass
            if f is not None:
                try: f.close()
                except Exception: pass
            try: stdin.close()
            except Exception: pass

    t = threading.Thread(target=_pump, daemon=True)
    t.start()
    return t


# ─── Workers ─────────────────────────────────────────────────────────────────
class FfmpegWorker(QThread):
    progress = pyqtSignal(float)
    finished = pyqtSignal(bool, str)

    def __init__(self, cmd, duration=None, parent=None):
        super().__init__(parent)
        self.cmd = cmd
        self.duration = duration
        self.proc = None
        self._stopped = False

    def run(self):
        try:
            self.proc = subprocess.Popen(
                self.cmd, stderr=subprocess.PIPE, text=True,
                encoding="utf-8", errors="replace",
                creationflags=CREATE_NO_WINDOW)
        except Exception as e:
            self.finished.emit(False, f"Не удалось запустить ffmpeg: {e}")
            return

        proc = self.proc
        if self.duration is None:
            rc = proc.wait()
            self.finished.emit(rc == 0 and not self._stopped, f"Код: {rc}")
            return

        try:
            for line in proc.stderr:
                if self._stopped:
                    break
                if 'time=' in line:
                    try:
                        idx = line.index('time=')
                        tpart = line[idx + 5:].split()[0]
                        tsec = time_to_s(tpart)
                        perc = min(100.0, max(0.0, (tsec / self.duration) * 100.0)) if self.duration > 0 else 0.0
                        self.progress.emit(perc)
                    except Exception:
                        pass
            rc = proc.wait()
            if self._stopped:
                self.finished.emit(False, "Отменено")
            else:
                self.finished.emit(rc == 0, f"Код: {rc}")
        except Exception as e:
            try:
                proc.kill()
            except Exception:
                pass
            self.finished.emit(False, f"Ошибка ffmpeg: {e}")

    def stop(self):
        """Помечает воркер отменённым и убивает ffmpeg-процесс (без зомби)."""
        self._stopped = True
        p = self.proc
        if p and p.poll() is None:
            try:
                p.kill()
            except Exception:
                pass


class SmartCutWorker(QThread):
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
    progress = pyqtSignal(float)
    status = pyqtSignal(str)
    finished = pyqtSignal(bool, str)

    def __init__(self, src, in_s, out_s, out_path, venc, audio_index=None,
                 parent=None):
        super().__init__(parent)
        self.src = str(src)
        self.in_s = float(in_s)
        self.out_s = float(out_s)
        self.out_path = out_path
        self.venc = list(venc)
        # Абсолютный индекс выбранной аудиодорожки (None → первая: 0:a:0). Без
        # него Smart Cut всегда брал дорожку по умолчанию, игнорируя выбор.
        self.audio_index = audio_index
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
        try:
            p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL,
                                 creationflags=CREATE_NO_WINDOW)
        except Exception:
            return 1
        self._procs.append(p)
        rc = p.wait()
        try: self._procs.remove(p)
        except ValueError: pass
        return rc

    def _video_codec(self):
        try:
            r = subprocess.run(
                [FFPROBE, "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=codec_name", "-of", "csv=p=0", self.src],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", creationflags=CREATE_NO_WINDOW, timeout=30)
            return (r.stdout or "").strip()
        except Exception:
            return ""

    def _keyframes(self):
        """Тайминги ключевых кадров видео в окрестности [in, out] (по флагам
        пакетов, без декодирования — быстро)."""
        cmd = [FFPROBE, "-v", "error", "-select_streams", "v:0",
               "-show_entries", "packet=pts_time,flags",
               "-read_intervals", f"{max(0.0, self.in_s - 2):.3f}%{self.out_s + 2:.3f}",
               "-of", "csv=p=0", self.src]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True,
                               encoding="utf-8", errors="replace",
                               creationflags=CREATE_NO_WINDOW, timeout=60)
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
            r = subprocess.run(
                [FFPROBE, "-v", "error", "-show_entries", "format=duration",
                 "-of", "csv=p=0", path], capture_output=True, text=True,
                encoding="utf-8", errors="replace",
                creationflags=CREATE_NO_WINDOW, timeout=30)
            return float((r.stdout or "0").strip() or 0.0)
        except Exception:
            return 0.0

    def _max_frame_gap(self, path):
        """(max_gap, median_gap) между соседними видео-пакетами склейки. Щель на
        стыке сегментов (open-GOP роняет хвостовые B-кадры у границы GOP при
        lossless-copy → дырка в 2–3 кадра) даёт max_gap заметно больше медианного
        интервала. Нужен, чтобы поймать НЕровную склейку и честно откатиться на
        полный реэнкод (он всегда кадрово-непрерывен)."""
        try:
            r = subprocess.run(
                [FFPROBE, "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "packet=pts_time", "-of", "csv=p=0", path],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", creationflags=CREATE_NO_WINDOW, timeout=60)
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
        cmd = [FFMPEG, "-y", "-ss", f"{start:.6f}", "-i", self.src,
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
        cmd = [FFMPEG, "-y", "-ss", f"{start:.6f}", "-i", self.src,
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
        amap = f"0:{self.audio_index}" if self.audio_index is not None else "0:a:0"
        cmd = [FFMPEG, "-y", "-ss", f"{self.in_s:.6f}", "-i", self.src,
               "-t", f"{max(0.1, dur):.6f}", "-vn", "-sn",
               "-map", amap, "-af", "apad", "-c:a", "aac", "-b:a", "192k",
               "-avoid_negative_ts", "make_zero", out_file]
        return (self._run(cmd) == 0 and os.path.exists(out_file)
                and os.path.getsize(out_file) > 0)

    def _mux(self, video_file, audio_file, out_file):
        """Сводит готовую видео-дорожку с единой аудио-дорожкой без перекодировки.
        Звук уже точно равен длине видео (apad + -t = video_dur), поэтому БЕЗ
        `-shortest`: и последний кадр озвучен, и нет «застывшего» хвоста видео.
        muxdelay/muxpreload 0 + make_zero убирают начальное смещение контейнера."""
        cmd = [FFMPEG, "-y", "-i", video_file, "-i", audio_file,
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
        if self.audio_index is not None:
            amap = ["-map", "0:v:0", "-map", f"0:{self.audio_index}"]
            aenc = ["-c:a", "aac", "-b:a", "192k", "-af", "apad"]
        else:
            # Дорожка не выбрана: optional-map первой аудио (источник без звука не
            # упадёт); apad НЕ ставим — на безаудийном входе фильтр бы ошибся.
            amap = ["-map", "0:v:0", "-map", "0:a:0?"]
            aenc = ["-c:a", "aac", "-b:a", "192k"]
        cmd = [FFMPEG, "-y", "-ss", f"{self.in_s:.6f}", "-i", self.src,
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
            self._tmpdir = tempfile.mkdtemp(prefix="sihyx_smartcut_")
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
            kf_before_in = max([t for t in kfs if t <= self.in_s + 0.001], default=0.0)

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
            head = os.path.join(self._tmpdir, f"head{ext}")
            mid  = os.path.join(self._tmpdir, f"mid{ext}")
            tail = os.path.join(self._tmpdir, f"tail{ext}")
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
            video_only = os.path.join(self._tmpdir, f"video{ext}")
            listfile = os.path.join(self._tmpdir, "list.txt")
            with open(listfile, "w", encoding="utf-8") as f:
                for s in segs:
                    f.write(f"file '{s.replace(chr(39), chr(92) + chr(39))}'\n")
            rc = self._run([FFMPEG, "-y", "-f", "concat", "-safe", "0",
                            "-i", listfile, "-c", "copy", "-an",
                            "-avoid_negative_ts", "make_zero",
                            "-muxpreload", "0", "-muxdelay", "0", video_only])
            ok = (rc == 0 and os.path.exists(video_only)
                  and os.path.getsize(video_only) > 0)
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
            audio = os.path.join(self._tmpdir, "audio.m4a")
            if self._encode_audio(vdur, audio):
                if not self._mux(video_only, audio, self.out_path):
                    self.status.emit("Сведение не удалось — полная перекодировка…")
                    ok = self._full_reencode(self.out_path)
                    _finish(ok, "Готово (перекодировка)" if ok else "Ошибка Smart Cut")
                    return
            else:
                # Нет аудио-дорожки — перекладываем видео в контейнер результата
                # без перекодировки (intermediate всегда mp4, цель может быть mkv).
                rc = self._run([FFMPEG, "-y", "-i", video_only, "-c", "copy",
                                "-an", "-avoid_negative_ts", "make_zero",
                                "-muxpreload", "0", "-muxdelay", "0",
                                self.out_path])
                if rc != 0 or not os.path.exists(self.out_path):
                    import shutil
                    shutil.copyfile(video_only, self.out_path)
            ok = (os.path.exists(self.out_path)
                  and os.path.getsize(self.out_path) > 0)
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


class VideoInpaintWorker(QThread):
    """Покадровое удаление объекта (водяной знак/эмодзи и т.п.) с ВИДЕО в отдельном
    потоке, чтобы интерфейс не зависал.

    Принципиально НЕ содержит собственной реализации инпейнтинга: для каждого кадра
    вызывается ТОТ ЖЕ движок LaMa (inpainter.inpaint), что и при удалении объекта с
    одиночного изображения в фоторедакторе. Пайплайн целиком на FFmpeg + LaMa:

      1) FFmpeg разбивает видео на PNG-кадры (полное разрешение, дисплейная
         ориентация — autorotate по умолчанию, без потерь);
      2) каждый кадр прогоняется через inpainter.inpaint(frame, mask) — функция
         сама обрабатывает только ROI вокруг маски (см. lama_inpaint.py), поэтому
         для небольшого знака весь кадр через сеть НЕ гоняется и это быстро;
      3) FFmpeg собирает кадры обратно, сохраняя исходные FPS, разрешение,
         ориентацию и аудиодорожку оригинала.

    Маска ОДНА на всё видео (закрашивается на одном кадре в диалоге) — рассчитано
    на статичные объекты, что и нужно для водяных знаков/логотипов/эмодзи.

    Отмена (cancel) прерывает на любом этапе; временная папка удаляется ВСЕГДА —
    и при успехе, и при ошибке, и при отмене.
    """
    progress = pyqtSignal(int, str)      # (процент 0..100; -1 = «busy», текст фазы)
    done = pyqtSignal(str)               # путь готового файла
    failed = pyqtSignal(str)             # текст ошибки ("Отменено" при отмене)

    def __init__(self, inpainter, src, mask, fps, out_path, venc, has_audio):
        super().__init__()
        self._inp = inpainter
        # Абсолютный путь: ffmpeg для разных этапов вызывается в разное время, и
        # относительный путь ненадёжен (рабочий каталог процесса мог измениться).
        self._src = os.path.abspath(str(src))
        self._mask = mask                # numpy (H,W) uint8 {0,255}
        self._fps = float(fps) if fps and fps > 0 else 25.0
        self._out = str(out_path)
        self._venc = list(venc)          # аргументы видеокодировщика (как у «Обрезать»)
        self._has_audio = bool(has_audio)
        self._cancel = False
        self._proc = None                # текущий subprocess ffmpeg (для отмены)
        self._tmp = None

    def cancel(self):
        """Просит прервать обработку (потокобезопасно по флагу) и убивает текущий
        ffmpeg, если он запущен, чтобы отмена была мгновенной."""
        self._cancel = True
        p = self._proc
        if p is not None and p.poll() is None:
            try:
                p.terminate()
            except Exception:
                pass

    # Алиас для единообразной остановки в EditTab.shutdown (как у остальных воркеров).
    def stop(self):
        self.cancel()

    def _run_ffmpeg(self, cmd):
        """Запускает ffmpeg и ждёт завершения, периодически проверяя отмену.
        Возвращает returncode (или -1, если прервали по cancel)."""
        kw = {}
        if os.name == 'nt':
            kw['creationflags'] = CREATE_NO_WINDOW
        self._proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL, **kw)
        try:
            while True:
                try:
                    return self._proc.wait(timeout=0.2)
                except subprocess.TimeoutExpired:
                    if self._cancel:
                        try:
                            self._proc.terminate()
                        except Exception:
                            pass
                        try:
                            self._proc.wait(timeout=5)
                        except Exception:
                            pass
                        return -1
        finally:
            self._proc = None

    def run(self):
        # Загрузчик/сохранятель кадров — те же, что использует фоторедактор
        # (Unicode-безопасные обёртки над OpenCV). Импорт ленивый: тяжёлые
        # зависимости подтягиваются только при реальном запуске обработки.
        from lama_inpaint import load_bgr, save_bgr
        import shutil
        try:
            self._tmp = tempfile.mkdtemp(prefix="sihyx_vinp_")
            frames_dir = os.path.join(self._tmp, "frames")
            os.makedirs(frames_dir, exist_ok=True)
            patt = os.path.join(frames_dir, "%08d.png")

            # 1) Разбор видео на кадры (полное разрешение, дисплейная ориентация).
            self.progress.emit(-1, "Разбор видео на кадры…")
            if self._run_ffmpeg([FFMPEG, "-y", "-i", self._src, patt]) != 0 or self._cancel:
                raise RuntimeError("Отменено" if self._cancel
                                   else "Не удалось извлечь кадры из видео")

            frames = sorted(f for f in os.listdir(frames_dir) if f.endswith(".png"))
            total = len(frames)
            if total == 0:
                raise RuntimeError("В видео не найдено кадров")

            # 2) Прогрев модели ДО цикла (её загрузка длится ~10–25 c) — чтобы
            #    прогресс по кадрам шёл ровно, а не «застрял» на первом кадре.
            self.progress.emit(-1, "Загрузка модели LaMa…")
            try:
                self._inp.warmup()
            except Exception:
                pass
            if self._cancel:
                raise RuntimeError("Отменено")

            # 3) Покадровый инпейнт ТЕМ ЖЕ движком, что и для фото. Маска одна на
            #    всё видео; inpaint сам работает только по ROI вокруг неё.
            for i, name in enumerate(frames):
                if self._cancel:
                    raise RuntimeError("Отменено")
                fp = os.path.join(frames_dir, name)
                res = self._inp.inpaint(load_bgr(fp), self._mask)
                save_bgr(fp, res)        # перезаписываем кадр результатом (экономит диск)
                pct = 5 + int(88 * (i + 1) / total)
                self.progress.emit(pct, f"Удаление объекта… кадр {i + 1}/{total}")

            if self._cancel:
                raise RuntimeError("Отменено")

            # 4) Сборка обратно: исходные FPS + аудиодорожка из оригинала.
            self.progress.emit(95, "Сборка видео…")
            out_tmp = os.path.join(self._tmp, "out" + os.path.splitext(self._out)[1])

            def _assemble(copy_audio):
                cmd = [FFMPEG, "-y", "-framerate", f"{self._fps:.6f}", "-i", patt]
                if self._has_audio:
                    # Аудио берём из оригинала; copy — без потерь; при несовместимости
                    # контейнера/кодека (редко) ниже откатываемся на перекодировку в AAC.
                    cmd += ["-i", self._src, "-map", "0:v:0", "-map", "1:a?"]
                    cmd += (["-c:a", "copy"] if copy_audio
                            else ["-c:a", "aac", "-b:a", "192k"])
                else:
                    cmd += ["-map", "0:v:0"]
                cmd += self._venc + ["-pix_fmt", "yuv420p",
                                     "-movflags", "+faststart", "-shortest", out_tmp]
                return self._run_ffmpeg(cmd)

            rc = _assemble(copy_audio=True)
            if rc != 0 and not self._cancel and self._has_audio:
                # Аудио не скопировалось (несовместимый кодек для контейнера) —
                # пробуем ещё раз, перекодировав звук в AAC. Дорожка сохраняется.
                rc = _assemble(copy_audio=False)
            if rc != 0 or self._cancel:
                raise RuntimeError("Отменено" if self._cancel
                                   else "Не удалось собрать видео")

            # Переносим результат во финальное имя (терпимо к занятому файлу — как
            # обычная обрезка; см. EditTab._replace_tolerant). Ленивый импорт: этот
            # воркер живёт в edit_tab_workers, а EditTab — в edit_tab; импорт внутри
            # метода (а не на уровне модуля) разрывает цикл parts↔tab и безопасен —
            # к моменту вызова edit_tab уже полностью загружен.
            from edit_tab import EditTab
            final = EditTab._replace_tolerant(out_tmp, self._out)
            self.done.emit(final)
        except Exception as e:
            msg = str(e)
            if self._cancel or msg == "Отменено":
                self.failed.emit("Отменено")
            else:
                self.failed.emit(msg)
        finally:
            # Уборка временных файлов — безусловная.
            try:
                if self._tmp and os.path.isdir(self._tmp):
                    shutil.rmtree(self._tmp, ignore_errors=True)
            except Exception:
                pass


class ProxyWorker(QThread):
    finished = pyqtSignal(bool, str, str)
    progress = pyqtSignal(str)   # текст прогресса для волны: «Создание превью… N%»

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
        self.proc = subprocess.Popen(
            full, stdin=(subprocess.PIPE if feed_path else None),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace",
            creationflags=CREATE_NO_WINDOW)
        if feed_path:
            start_share_delete_feeder(
                feed_path, self.proc.stdin, stop_flag=lambda: self._stopped)
        # Фоновый слив stderr — держим pipe пустым, чтобы ffmpeg не блокировался.
        err_chunks = []
        def _drain_err(pipe):
            try:
                for line in pipe:
                    err_chunks.append(line)
            except Exception:
                pass
        err_thread = threading.Thread(target=_drain_err, args=(self.proc.stderr,),
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
                FFMPEG, "-y", "-i", src,
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
        feed = str(self.input_path) if os.name == 'nt' else None
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
            return os.path.getsize(self.output_path) > 4096
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


class AudioWaveformLoader(QThread):
    # samples (combined max L/R для рисовки), duration, left, right (раздельные
    # огибающие каналов — для честного стерео-индикатора уровня).
    finished = pyqtSignal(list, float, list, list)
    progress = pyqtSignal(str)

    def __init__(self, filepath, audio_index, duration=0.0, parent=None):
        super().__init__(parent)
        self.filepath = str(filepath)
        self.audio_index = audio_index
        self.total_dur = float(duration or 0.0)   # для процентов извлечения
        self.tmp_wav = None
        self.proc = None
        self._stopped = False

    def _run_ffmpeg(self, cmd, feed_path=None):
        # -progress pipe:1 даёт машинный прогресс (out_time_us=…) — по нему
        # показываем проценты. -nostats глушит обычный лог в stderr.
        # feed_path задан → вход «pipe:0» кормим файлом через FILE_SHARE_DELETE
        # (исходник остаётся удаляемым из Проводника во время построения волны).
        full = cmd[:1] + ["-progress", "pipe:1", "-nostats"] + cmd[1:]
        self.proc = subprocess.Popen(
            full, stdin=(subprocess.PIPE if feed_path else None),
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace",
            creationflags=CREATE_NO_WINDOW)
        feeder = None
        if feed_path:
            feeder = start_share_delete_feeder(
                feed_path, self.proc.stdin, stop_flag=lambda: self._stopped)
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
                            self.progress.emit(f"Извлечение аудио… {pct}%")
                    except Exception:
                        pass
        except Exception:
            pass
        self.proc.wait()
        return self.proc.returncode == 0

    def run(self):
        self.progress.emit("Извлечение аудио...")
        tf = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        tf.close()
        self.tmp_wav = tf.name

        tail = []
        if self.audio_index is not None:
            tail += ["-map", f"0:{self.audio_index}"]
        # -ac 2: тянем ДВА канала (mono-источник ffmpeg продублирует — L==R, как и
        # положено; 5.1 сведёт в стерео) → у индикатора уровня честные L и R.
        tail += ["-af", "aresample=6000,asetpts=PTS-STARTPTS",
                 "-ac", "2", "-ar", "6000", "-f", "wav", self.tmp_wav]
        cmd_pipe = [FFMPEG, "-y", "-i", "pipe:0", "-vn"] + tail
        cmd_file = [FFMPEG, "-y", "-i", self.filepath, "-vn"] + tail

        ok = False
        # Сначала через FILE_SHARE_DELETE-пайп (исходник остаётся удаляемым во
        # время построения волны). Не для всех контейнеров pipe:0 годится
        # (moov в конце mp4 без faststart) — ffmpeg тогда может отрапортовать
        # rc=0, при этом записав ПУСТОЙ wav (см. тот же баг в ProxyWorker), так
        # что дополнительно проверяем реальное число сэмплов, а не только rc.
        if os.name == 'nt':
            try:
                ok = self._run_ffmpeg(cmd_pipe, feed_path=self.filepath) and self._wav_has_frames(self.tmp_wav)
            except Exception:
                ok = False
        if not ok and not self._stopped:
            try:
                ok = self._run_ffmpeg(cmd_file) and self._wav_has_frames(self.tmp_wav)
            except Exception:
                ok = False

        if not ok and not self._stopped:
            try:
                ok = self._run_ffmpeg(
                    [FFMPEG, "-y", "-i", self.filepath, "-vn",
                     "-ac", "2", "-ar", "6000", "-f", "wav", self.tmp_wav]) and self._wav_has_frames(self.tmp_wav)
            except Exception:
                ok = False

        if self._stopped or not ok or not os.path.exists(self.tmp_wav):
            self._cleanup_tmp()
            self.finished.emit([], 0.0, [], [])
            return

        self.progress.emit("Генерация волны...")
        try:
            samples, duration, left, right = self.read_wav_chunked(
                self.tmp_wav, target_samples=8000)
        except Exception:
            samples, duration, left, right = [], 0.0, [], []
        self._cleanup_tmp()
        self.finished.emit(samples, duration, left, right)

    @staticmethod
    def _wav_has_frames(path):
        try:
            wf = wave.open(path, 'rb')
            try:
                return wf.getnframes() > 0
            finally:
                wf.close()
        except Exception:
            return False

    def _cleanup_tmp(self):
        try:
            if self.tmp_wav and os.path.exists(self.tmp_wav):
                os.remove(self.tmp_wav)
        except Exception:
            pass

    def stop(self):
        self._stopped = True
        p = self.proc
        if p and p.poll() is None:
            try:
                p.kill()
            except Exception:
                pass

    def read_wav_chunked(self, wav_path, target_samples=8000):
        """Возвращает (combined, duration, left, right): combined — поканальный
        максимум (для рисовки волны), left/right — раздельные огибающие каналов
        (для честного стерео-индикатора). Кадры деинтерливим (буфер L,R,L,R…)
        и считаем пики L и R в одних и тех же бакетах, чтобы шкалы были выровнены."""
        import array as _array
        try:
            wf = wave.open(wav_path, 'rb')
        except Exception:
            return [], 0.0, [], []

        n_frames  = wf.getnframes()
        framerate = wf.getframerate()
        sampwidth = wf.getsampwidth()
        nchan     = max(1, wf.getnchannels())
        duration  = n_frames / framerate if framerate > 0 else 0.0

        if n_frames == 0:
            wf.close()
            return [], duration, [], []

        samples_per_pixel = max(1, n_frames // target_samples)
        chunk_size_frames = 256 * 1024

        if sampwidth == 1:
            typecode = 'B'; scale = 128.0; bias = 128
        elif sampwidth == 2:
            typecode = 'h'; scale = 32768.0; bias = 0
        elif sampwidth == 4:
            typecode = 'i'; scale = 2147483648.0; bias = 0
        else:
            wf.close()
            return [], duration, [], []

        def _peak(seg):
            if not len(seg):
                return 0.0
            hi = max(seg); lo = min(seg)
            if bias:
                return max(abs(hi - bias), abs(lo - bias)) / scale
            return max(abs(hi), abs(lo)) / scale

        comb: list[float] = []; left: list[float] = []; right: list[float] = []
        cur_l = 0.0; cur_r = 0.0; acc = 0

        processed = 0
        while processed < n_frames:
            if self._stopped:
                break
            raw = wf.readframes(chunk_size_frames)
            if not raw:
                break
            buf = _array.array(typecode, raw)
            if typecode != 'B' and sys.byteorder == 'big':
                buf.byteswap()
            if nchan >= 2:
                lbuf = buf[0::nchan]; rbuf = buf[1::nchan]
            else:
                lbuf = buf; rbuf = buf
            frames_in_chunk = len(lbuf)
            i = 0
            while i < frames_in_chunk:
                take = min(samples_per_pixel - acc, frames_in_chunk - i)
                if take <= 0:
                    break
                pl = _peak(lbuf[i: i + take])
                pr = _peak(rbuf[i: i + take])
                if pl > cur_l: cur_l = pl
                if pr > cur_r: cur_r = pr
                acc += take
                i += take
                if acc >= samples_per_pixel:
                    left.append(cur_l); right.append(cur_r)
                    comb.append(cur_l if cur_l > cur_r else cur_r)
                    cur_l = 0.0; cur_r = 0.0; acc = 0
            processed += frames_in_chunk

        wf.close()
        if not comb:
            return [0.0], duration, [0.0], [0.0]
        return comb, duration, left, right


class AudioSegmentWaveformLoader(AudioWaveformLoader):
    """Быстрая волна ТОЛЬКО для отрезка IN..OUT — используется при смене
    аудиодорожки, чтобы сразу показать, как звучит новая дорожка именно на
    выделенном куске, не дожидаясь полного прохода по всему файлу (для фильма
    это могут быть минуты). Точный -ss перед -i декодирует только сам отрезок."""
    finished = pyqtSignal(list, float, float, list, list)  # samples, seg_in, seg_out, left, right

    def __init__(self, filepath, audio_index, seg_in, seg_out, full_duration, parent=None):
        super().__init__(filepath, audio_index, duration=max(0.05, seg_out - seg_in), parent=parent)
        self.seg_in = float(seg_in)
        self.seg_out = float(seg_out)
        self.full_duration = max(0.001, float(full_duration or (seg_out - seg_in)))

    def run(self):
        tf = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        tf.close()
        self.tmp_wav = tf.name

        tail = []
        if self.audio_index is not None:
            tail += ["-map", f"0:{self.audio_index}"]
        tail += ["-af", "aresample=6000,asetpts=PTS-STARTPTS",
                 "-ac", "2", "-ar", "6000", "-f", "wav", self.tmp_wav]
        cmd = ([FFMPEG, "-y", "-ss", f"{self.seg_in:.3f}", "-i", self.filepath,
                "-t", f"{max(0.05, self.seg_out - self.seg_in):.3f}", "-vn"] + tail)

        ok = False
        try:
            ok = self._run_ffmpeg(cmd) and self._wav_has_frames(self.tmp_wav)
        except Exception:
            ok = False

        if self._stopped or not ok or not os.path.exists(self.tmp_wav):
            self._cleanup_tmp()
            self.finished.emit([], self.seg_in, self.seg_out, [], [])
            return

        # Разрешение отрезка пропорционально его доле в полном файле — тот же
        # эффективный масштаб «сэмплов на секунду», что и у полной волны.
        seg_dur = max(0.001, self.seg_out - self.seg_in)
        target = max(50, min(4000, int(8000 * seg_dur / self.full_duration)))
        try:
            samples, _dur, left, right = self.read_wav_chunked(self.tmp_wav, target_samples=target)
        except Exception:
            samples, left, right = [], [], []
        self._cleanup_tmp()
        self.finished.emit(samples, self.seg_in, self.seg_out, left, right)


class SubtitleExtractor(QThread):
    """Извлекает выбранную текстовую дорожку субтитров в SRT и парсит её —
    в фоне, чтобы не подвешивать GUI."""
    done = pyqtSignal(int, object)   # (token, cues|None)

    def __init__(self, src, sub_index, token):
        super().__init__()
        self.src = str(src)
        self.sub_index = int(sub_index)
        self.token = int(token)

    def run(self):
        cues = None
        tmp = None
        try:
            tf = tempfile.NamedTemporaryFile(delete=False, suffix=".srt")
            tmp = tf.name; tf.close()
            cmd = [FFMPEG, "-y", "-i", self.src,
                   "-map", f"0:s:{self.sub_index}", tmp]
            kw = {}
            if os.name == 'nt':
                kw['creationflags'] = CREATE_NO_WINDOW
            subprocess.run(cmd, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=90, **kw)
            if os.path.exists(tmp) and os.path.getsize(tmp) > 0:
                with open(tmp, 'r', encoding='utf-8', errors='replace') as f:
                    cues = _parse_srt(f.read())
        except Exception:
            cues = None
        finally:
            if tmp:
                try: os.remove(tmp)
                except Exception: pass
        self.done.emit(self.token, cues)


class AssExtractor(QThread):
    """Извлекает выбранную дорожку субтитров в .ass (для рендера через libass) —
    в фоне. Эмитит (token, путь_к_ass|None)."""
    done = pyqtSignal(int, object)   # (token, ass_path|None)

    def __init__(self, src, sub_index, token):
        super().__init__()
        self.src = str(src)
        self.sub_index = int(sub_index)
        self.token = int(token)

    def run(self):
        out = None
        try:
            tf = tempfile.NamedTemporaryFile(delete=False, suffix=".ass")
            out = tf.name; tf.close()
            cmd = [FFMPEG, "-y", "-i", self.src,
                   "-map", f"0:s:{self.sub_index}", "-c:s", "ass", out]
            kw = {}
            if os.name == 'nt':
                kw['creationflags'] = CREATE_NO_WINDOW
            subprocess.run(cmd, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=120, **kw)
            if not (os.path.exists(out) and os.path.getsize(out) > 0):
                try: os.remove(out)
                except Exception: pass
                out = None
        except Exception:
            if out:
                try: os.remove(out)
                except Exception: pass
            out = None
        self.done.emit(self.token, out)


class _SeekThumbnailer(QThread):
    """Фоновый извлекатель кадров для превью полосы воспроизведения. Держит одну
    «целевую» позицию; пока идёт извлечение, новые запросы лишь обновляют цель
    (промежуточные отбрасываются — на быстром движении мыши не копится очередь)."""
    ready = pyqtSignal(float, object)   # quantized_sec, QImage

    def __init__(self):
        super().__init__()
        self._src = None
        self._pending = None
        self._stop = False
        self._cond = threading.Condition()

    def set_source(self, src):
        with self._cond:
            self._src = str(src) if src else None
            self._pending = None

    def request(self, sec):
        with self._cond:
            self._pending = float(sec)
            self._cond.notify()

    def stop(self):
        with self._cond:
            self._stop = True
            self._cond.notify()

    def run(self):
        while True:
            with self._cond:
                while self._pending is None and not self._stop:
                    self._cond.wait()
                if self._stop:
                    return
                sec = self._pending; src = self._src
                self._pending = None
            if src is None:
                continue
            img = self._extract(src, sec)
            if img is not None and not img.isNull():
                self.ready.emit(sec, img)

    @staticmethod
    def _extract(src, sec):
        try:
            # Скорость превью важнее точности кадра, поэтому жертвуем качеством:
            #   -noaccurate_seek — прыжок СРАЗУ на ближайший ключевой кадр, без
            #     декодирования от него до точной позиции (главный источник
            #     задержки при наведении);
            #   -probesize/-analyzeduration — короткий анализ входа (не сканируем
            #     весь файл ради одного кадра);
            #   scale=160 + -q:v 8 — мелкий кадр пониженного качества кодируется и
            #     передаётся через pipe быстрее.
            cmd = [FFMPEG, "-nostdin",
                   "-probesize", "2M", "-analyzeduration", "0",
                   "-noaccurate_seek", "-ss", f"{max(0.0, sec):.3f}",
                   "-i", str(src), "-frames:v", "1", "-an", "-sn",
                   "-vf", "scale=160:-2", "-q:v", "8", "-threads", "1",
                   "-f", "image2pipe", "-vcodec", "mjpeg", "-"]
            pr = subprocess.run(cmd, capture_output=True,
                                creationflags=CREATE_NO_WINDOW, timeout=8)
            if pr.returncode == 0 and pr.stdout:
                im = QImage.fromData(pr.stdout, "JPG")
                return im
        except Exception:
            pass
        return None
