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

SYNC_RATE = 16000
_HOP = SYNC_RATE // 100        # 10 мс
MAX_SHIFT_S = 5.0
_WINDOWS = 6
_REFINE_S = 0.4
_AGREE_S = 0.2
# Меньше этого субтитры уже совпадают со звуком — сдвигать незачем.
MIN_SHIFT_S = 0.08


# ── Расчёт (без Qt) ──────────────────────────────────────────────────────────
def _band_spectrum(x):
    """Спектр мощности окон 20 мс с шагом 10 мс и частоты его полос."""
    win = 2 * _HOP
    n = (len(x) - win) // _HOP + 1
    if n <= 0:
        return None, None
    frames = np.lib.stride_tricks.sliding_window_view(x, win)[::_HOP][:n]
    spec = np.abs(np.fft.rfft(frames * np.hanning(win), n=512)) ** 2
    return spec, np.fft.rfftfreq(512, 1.0 / SYNC_RATE)


def speech_activity(x):
    """Оценка «здесь говорят» на каждые 10 мс звука x (моно, SYNC_RATE)."""
    spec, f = _band_spectrum(x)
    if spec is None:
        return np.zeros(0, np.float32)
    band = spec[:, (f >= 300) & (f <= 3000)].sum(axis=1)
    total = spec[:, f >= 60].sum(axis=1) + 1e-9
    loud = np.log10(band + 1e-9)
    k = 600                                   # нормировка по соседним 6 с
    n = len(loud)
    pad = np.pad(loud, (k // 2, k - k // 2), mode="edge")
    cs = np.concatenate(([0.0], np.cumsum(pad)))
    cs2 = np.concatenate(([0.0], np.cumsum(pad * pad)))
    mean = ((cs[k:] - cs[:-k]) / k)[:n]
    var = np.maximum(((cs2[k:] - cs2[:-k]) / k)[:n] - mean * mean, 1e-6)
    z = (loud - mean) / np.sqrt(var)
    return (np.clip(z, -2.0, 3.0) * (0.5 + band / total)).astype(np.float32)


def onset_strength(x):
    """Где речь НАЧИНАЕТСЯ: рост громкости полосы речи (на каждые 10 мс)."""
    spec, f = _band_spectrum(x)
    if spec is None:
        return np.zeros(0, np.float32)
    loud = np.log10(spec[:, (f >= 300) & (f <= 3000)].sum(axis=1) + 1e-9)
    loud = np.convolve(loud, np.ones(3) / 3.0, mode="same")
    return np.maximum(np.diff(loud, prepend=loud[0]), 0.0).astype(np.float32)


def pick_windows(cues, count=_WINDOWS, length=60.0):
    """(начала отрезков, длина отрезка): до count непересекающихся отрезков,
    где реплик больше всего. У коротких субтитров отрезки короче (до 20 с)."""
    if not cues:
        return [], length
    first = min(a for a, _b in cues)
    end = max(b for _a, b in cues)
    span = max(0.0, end - first)
    length = max(20.0, min(length, span / count)) if span > 0 else 20.0
    step = max(1.0, length / 6.0)
    lo = max(0.0, first - 1.0)
    starts = np.arange(lo, max(lo, end - length) + step, step)
    a = np.array([c[0] for c in cues])
    b = np.array([c[1] for c in cues])
    cover = np.array([np.clip(np.minimum(b, s + length) - np.maximum(a, s), 0, None).sum()
                      for s in starts])
    picked = []
    for i in np.argsort(cover)[::-1]:
        if cover[i] <= 0:
            break
        s = float(starts[i])
        if all(abs(s - p) >= length for p in picked):
            picked.append(s)
        if len(picked) >= count:
            break
    return sorted(picked), length


def estimate_offset(cues, decode, max_shift=MAX_SHIFT_S, progress=None):
    """Поправка ко времени реплик: реплика T должна стоять на T + offset.

    cues — [(начало, конец)] в секундах файла; decode(t0, длительность) —
    звук с t0 (моно, SYNC_RATE, float32; у краёв файла может быть короче).
    Возвращает словарь: ok, offset, agree, windows и reason, если не вышло."""
    picked, length = pick_windows(cues)
    if not picked:
        return {'ok': False, 'reason': "в субтитрах нет реплик"}
    K = int(round(max_shift * 100))
    n = int(round(length * 100))
    shifts = 2 * K + 1
    total = np.zeros(shifts)
    onsets = np.zeros(shifts)
    per = []
    kernel = np.exp(-0.5 * (np.arange(-15, 16) / 5.0) ** 2)
    for w, s in enumerate(picked):
        if progress is not None:
            progress(w, len(picked))
        t0 = s - max_shift
        x = decode(max(0.0, t0), length + 2 * max_shift - max(0.0, -t0))
        if t0 < 0:                       # начало файла — слева тишина
            x = np.concatenate((np.zeros(int(round(-t0 * SYNC_RATE)), np.float32), x))
        act, on = speech_activity(x), onset_strength(x)
        need = n + 2 * K
        if len(act) < need:              # конец файла — справа тишина
            act = np.pad(act, (0, need - len(act)))
            on = np.pad(on, (0, need - len(on)))
        mask = np.zeros(n, np.float32)
        starts = np.zeros(n, np.float32)
        for a, b in cues:
            i0, i1 = int(round((a - s) * 100)), int(round((b - s) * 100))
            if i1 <= 0 or i0 >= n:
                continue
            mask[max(0, i0):min(n, i1)] = 1.0
            if i0 >= 0:
                starts[i0] = 1.0
        if mask.sum() < 50:              # меньше полсекунды реплик — не отрезок
            continue
        mask -= mask.mean()
        score = np.correlate(act[:need], mask, mode="valid")[:shifts]
        total += score
        per.append(int(np.argmax(score)))
        onsets += np.correlate(on[:need], np.convolve(starts, kernel, mode="same"),
                               mode="valid")[:shifts]
    if not per:
        return {'ok': False, 'reason': "под репликами не нашлось звука"}
    coarse = int(np.argmax(total))
    reach = int(round(_REFINE_S * 100))
    lo, hi = max(0, coarse - reach), min(shifts, coarse + reach + 1)
    best = lo + int(np.argmax(onsets[lo:hi]))
    agree = sum(1 for p in per if abs(p - coarse) <= int(round(_AGREE_S * 100)))
    need_agree = max(2, int(np.ceil(len(per) * 2 / 3))) if len(per) > 1 else 1
    res = {'offset': (best - K) / 100.0, 'agree': agree, 'windows': len(per)}
    if abs(coarse - K) >= K - 20:
        res.update(ok=False, reason=f"расхождение больше ±{max_shift:g} с — это уже "
                                    "не небольшая рассинхронизация")
    elif agree < need_agree:
        res.update(ok=False, reason=f"звук и реплики не сошлись: согласны {agree} "
                                    f"отрезков из {len(per)}")
    else:
        res['ok'] = True
    return res


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
