# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Монтаж: автосинхронизация субтитров по звуку.

Субтитры, которые отстают или спешат на пару секунд (другой релиз, другая
заставка), одной кнопкой сдвигаются к речи выбранной аудиодорожки. Как:

1. Берутся до шести отрезков по минуте, где реплик больше всего, и звук
   вокруг них с запасом ±5 с (16 кГц, моно) — шесть коротких ffmpeg с
   перемоткой, а не декодирование всего фильма.
2. «Здесь говорят» на каждые 10 мс: энергия полосы речи 300–3000 Гц в
   логарифме, нормированная по соседним 6 с (громкая сцена и тихая — на
   равных) и умноженная на долю этой полосы во всём спектре.
3. Грубо: корреляция маски реплик с этой оценкой на сдвигах ±5 с (сумма по
   отрезкам). Реплики обычно висят после конца фразы, и целые интервалы тянут
   ответ на ~0.1 с раньше, поэтому
4. точно: в ±0.4 с от грубого ответа — совпадение НАЧАЛ реплик с моментами,
   где речь начинается (рост громкости полосы речи).
5. Доверие: каждый отрезок считается и по отдельности; ответ принимается,
   только если с общим согласны не меньше двух третей отрезков (±0.2 с).

Замер на Macross Plus OVA 1 (русские субтитры к японской дорожке): сдвиги
от −2.0 до +2.5 с находятся с точностью ~0.05 с, согласны 5–6 отрезков из 6,
расчёт ~3–4 с. Реплики, расставленные случайно (то же число и длины), дают
0–2 согласных отрезка из 6 и отклоняются.

Сдвинутые субтитры сохраняются копией (…_sync.srt / .ass — у ASS стили и теги
событий остаются как были) и сразу становятся активной дорожкой: превью и
вшивание берут их; исходная дорожка остаётся в списке."""
import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal

from si_hyx_parts.edit_tab import subtitle_style
import edit_tab as _api

# Расчёт без Qt — в speech_sync (его берёт и headless-анализ montage_tool).
from speech_sync import (  # noqa: F401
    MAX_SHIFT_S, MIN_SHIFT_S, SYNC_RATE, estimate_offset, onset_strength,
    pick_windows, speech_activity)


def _extract_srt_text(src, rel_idx):
    """Дорожка субтитров 0:s:rel_idx файла как текст SRT (или None)."""
    tmp = None
    try:
        tf = _api.tempfile.NamedTemporaryFile(delete=False, suffix=".srt")
        tmp = tf.name
        tf.close()
        kw = {'creationflags': _api.CREATE_NO_WINDOW} if _api.os.name == 'nt' else {}
        _api.subprocess.run([_api.FFMPEG, "-y", "-i", str(src), "-map", f"0:s:{int(rel_idx)}", tmp],
                            stdout=_api.subprocess.DEVNULL, stderr=_api.subprocess.DEVNULL,
                            timeout=300, **kw)
        if _api.os.path.exists(tmp) and _api.os.path.getsize(tmp) > 0:
            with open(tmp, "r", encoding="utf-8", errors="replace") as f:
                return f.read()
    except Exception:
        return None
    finally:
        if tmp:
            try:
                _api.os.remove(tmp)
            except OSError:
                pass
    return None


def _read_text(path):
    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
            return f.read()
    except OSError:
        return None


# ── Фон ──────────────────────────────────────────────────────────────────────
class SubtitleSyncWorker(QThread):
    """Расчёт поправки в фоне: и чтение субтитров, и звук берёт ffmpeg, а на
    файле в 10 ГБ это секунды — окно в это время живо.

    load_srt() → текст SRT реплик; load_ass() → исходный ASS для сдвига со
    стилями или None (у SRT/VTT стилей нет)."""

    done = pyqtSignal(object)
    progress = pyqtSignal(str)

    def __init__(self, load_srt, audio_src, audio_map, load_ass=None, parent=None):
        super().__init__(parent)
        self._load_srt = load_srt
        self._load_ass = load_ass
        self.audio_src = str(audio_src)
        self.audio_map = audio_map
        self._stopped = False

    def stop(self):
        self._stopped = True

    def _decode(self, t0, dur):
        if self._stopped:
            raise RuntimeError("остановлено")
        kw = {'creationflags': _api.CREATE_NO_WINDOW} if _api.os.name == 'nt' else {}
        r = _api.subprocess.run(
            [_api.FFMPEG, "-v", "error", "-nostdin", "-ss", f"{max(0.0, t0):.3f}",
             "-i", self.audio_src, "-map", self.audio_map, "-t", f"{max(0.1, dur):.3f}",
             "-vn", "-sn", "-ac", "1", "-ar", str(SYNC_RATE), "-f", "s16le", "-"],
            capture_output=True, timeout=120, **kw)
        return np.frombuffer(r.stdout, dtype=np.int16).astype(np.float32) / 32768.0

    def run(self):
        res = {'ok': False, 'reason': "не удалось прочитать субтитры"}
        try:
            self.progress.emit("Синхронизация субтитров: читаю реплики…")
            text = self._load_srt()
            cues = [(a, b) for a, b, _t in _api._parse_srt(text or "")]
            if cues:
                res = estimate_offset(
                    cues, self._decode,
                    progress=lambda i, n: self.progress.emit(
                        f"Синхронизация субтитров: слушаю отрезок {i + 1} из {n}…"))
                res['srt'] = text
                if (res.get('ok') and abs(res['offset']) >= MIN_SHIFT_S
                        and self._load_ass is not None):
                    res['ass'] = self._load_ass()
        except Exception as e:
            res = {'ok': False, 'reason': f"ошибка: {e}"}
        if not self._stopped:
            self.done.emit(res)


# ── Вкладка ──────────────────────────────────────────────────────────────────
class EditTabSubtitleSyncMixin:
    """Монтаж: кнопка «Синхронизировать субтитры со звуком»."""

    def sync_subtitles(self):
        worker = getattr(self, "_sub_sync_worker", None)
        if worker is not None and worker.isRunning():
            return
        entry = getattr(self, "_sub_sel_entry", None)
        if self.cmb_subs.currentIndex() <= 0 or not entry:
            _api.msgbox_information(self, "Субтитры", "Сначала выберите дорожку субтитров.")
            return
        kind, ref = entry
        if kind == 'emb':
            src, idx = self.actual_source_file, ref
            try:
                codec = (self._sub_streams[ref].get('codec_name') or '').lower()
            except Exception:
                codec = ''
        else:
            src, idx = ref, 0
            codec = _api.os.path.splitext(str(ref))[1].lower().lstrip('.')
        if codec in self._BITMAP_SUB_CODECS:
            _api.msgbox_information(self, "Субтитры",
                                    "Это субтитры-картинки — сдвигать их по звуку не умею.")
            return
        audio_src, audio_map = self._sync_audio_source()
        if not audio_src:
            _api.msgbox_information(self, "Субтитры",
                                    "У файла нет звука — синхронизировать не по чему.")
            return
        cues_now = list(getattr(self, "_sub_cues", None) or [])
        ass_path = getattr(self, "_ass_path", None)
        if not (getattr(self, "_sub_use_ass", False) and ass_path
                and _api.os.path.exists(ass_path)):
            ass_path = None
        styled = codec in ('ass', 'ssa', 'mov_text')
        cues_to_srt = self._cues_to_srt

        def load_srt():
            if cues_now:
                return cues_to_srt(cues_now)
            if ass_path:
                cues = subtitle_style.ass_cues(_read_text(ass_path) or "")
                if cues:
                    return cues_to_srt(cues)
            if kind == 'ext' and codec == 'srt':
                return _read_text(ref)
            return _extract_srt_text(src, idx)

        def load_ass():
            if not styled:
                return None
            if ass_path:
                return _read_text(ass_path)
            if kind == 'ext' and codec in ('ass', 'ssa'):
                return _read_text(ref)
            return subtitle_style.extract_ass(src, idx, codec)

        worker = SubtitleSyncWorker(load_srt, audio_src, audio_map, load_ass, self)
        worker.progress.connect(self._on_subtitle_sync_progress)
        worker.done.connect(self._on_subtitle_sync_done)
        worker.finished.connect(worker.deleteLater)
        self._sub_sync_worker = worker
        self._sub_sync_target = (kind, ref)
        btn = getattr(self, "btn_sync_subs", None)
        if btn is not None:
            btn.setEnabled(False)
        self._on_subtitle_sync_progress("Синхронизация субтитров…")
        worker.start()

    def _sync_audio_source(self):
        """(файл, -map) звука для синхронизации: выбранная внешняя озвучка или
        выбранная дорожка файла; звук выключен «Нет» — первая дорожка."""
        ext = getattr(self, "selected_audio_ext_path", None)
        if ext and _api.os.path.exists(str(ext)):
            return str(ext), "0:a:0"
        if not self.actual_source_file or not getattr(self, "_audio_streams", None):
            return None, None
        idx = getattr(self, "selected_audio_abs_index", None)
        if idx is None:
            idx = getattr(self, "audio_stream_index", None)
        return str(self.actual_source_file), (f"0:{int(idx)}" if idx is not None else "0:a:0")

    def _on_subtitle_sync_progress(self, text):
        try:
            self.log_label.setText(text)
            self._report_progress(0, text)
        except Exception:
            pass

    def _on_subtitle_sync_done(self, res):
        self._sub_sync_worker = None
        btn = getattr(self, "btn_sync_subs", None)
        if btn is not None:
            btn.setEnabled(True)
        try:
            self._report_progress(0, "")
        except Exception:
            pass
        title = "Синхронизация субтитров"
        if getattr(self, "_sub_sel_entry", None) != getattr(self, "_sub_sync_target", None):
            return              # пока считали, выбрали другую дорожку
        if not res.get('ok'):
            _api.msgbox_information(
                self, title, f"Сдвиг не найден: {res.get('reason', 'не вышло')}.\n"
                             "Субтитры оставлены как были.")
            return
        off = float(res['offset'])
        votes = f"согласны {res.get('agree')} отрезков из {res.get('windows')}"
        if abs(off) < MIN_SHIFT_S:
            _api.msgbox_information(
                self, title, f"Субтитры уже совпадают со звуком: расхождение "
                             f"{off:+.2f} с ({votes}).")
            return
        text, ext = None, ".srt"
        if res.get('ass'):
            text, ext = subtitle_style.shift_ass(res['ass'], off), ".ass"
        if not text:
            shifted = [(max(0.0, a + off), b + off, body)
                       for a, b, body in _api._parse_srt(res.get('srt') or "") if b + off > 0]
            text, ext = self._cues_to_srt(shifted), ".srt"
        path = self._save_synced_subs(text, ext)
        if path is None:
            return
        if self.main is not None and hasattr(self.main, "log"):
            self.main.log(f"Монтаж: субтитры сдвинуты на {off:+.2f} с ({votes}) → {path}")
        self._select_saved_subs(path)
        later = "позже" if off > 0 else "раньше"
        _api.msgbox_information(
            self, title, f"Субтитры сдвинуты на {abs(off):.2f} с {later} ({votes}).\n"
                         f"Сохранено копией: {_api.os.path.basename(path)} — она уже выбрана; "
                         "исходная дорожка осталась в списке.")

    def _save_synced_subs(self, text, ext):
        try:
            _api.os.makedirs(_api.CONFIG_DIR, exist_ok=True)
            base = self.actual_source_file.stem if self.actual_source_file else "subs"
            path = _api.os.path.join(_api.CONFIG_DIR, f"{base}_sync{ext}")
            n = 1
            while (_api.os.path.exists(path)
                   and _api.os.path.normpath(path) not in self._sub_ext):
                path = _api.os.path.join(_api.CONFIG_DIR, f"{base}_sync_{n}{ext}")
                n += 1
            with open(path, "w", encoding="utf-8") as f:
                f.write(text if text.endswith("\n") else text + "\n")
        except Exception as e:
            _api.msgbox_warning(self, "Субтитры", f"Не удалось сохранить: {e}")
            return None
        return _api.os.path.normpath(path)

    def _select_saved_subs(self, path):
        """Сохранённый файл — активная дорожка (превью и вшивание)."""
        if path in self._sub_ext:
            self._sub_cues = []
            try:
                idx = self._sub_entries.index(('ext', path)) + 1
            except ValueError:
                self._add_external_sub(path)
                return
            if self.cmb_subs.currentIndex() == idx:
                self.on_sub_track_changed(idx)
            else:
                self.cmb_subs.setCurrentIndex(idx)
        else:
            self._add_external_sub(path)
