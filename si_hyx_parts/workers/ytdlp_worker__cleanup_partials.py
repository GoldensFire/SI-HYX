# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""YtdlpWorker: _cleanup_partials. Public namespace: workers."""
import workers as _api


def _cleanup_partials(self, out_dir, final_path):
    """Удаляет осиротевшие промежуточные файлы (.part/.ytdl/.fdash/.fhls) от
        неудачных попыток формата (напр. DASH-таймаут на VK), чтобы рядом с
        итоговым видео не оставался .part. Скоупится по префиксу имени файла."""
    try:
        final = _api.os.path.basename(final_path)
        prefix = (final.split(" [")[0] or final)[:24]
        if not prefix:
            return
        for name in _api.os.listdir(out_dir):
            if name == final:
                continue
            low = name.lower()
            is_partial = (low.endswith(".part") or low.endswith(".ytdl")
                          or ".fdash" in low or ".fhls" in low)
            if is_partial and name.startswith(prefix):
                try: _api.os.remove(_api.os.path.join(out_dir, name))
                except Exception: pass
    except Exception:
        pass

def _parse_progress(self, payload):
    try:
        parts = payload.split("|")
        pct_str = parts[0].strip().rstrip("%")
        pct = float(pct_str) if pct_str and pct_str != "NA" else 0.0
        speed = parts[1].strip() if len(parts) > 1 else ""
        eta = parts[2].strip() if len(parts) > 2 else ""
        downloaded = parts[3].strip() if len(parts) > 3 else ""
        total = parts[4].strip() if len(parts) > 4 else ""
        if (not total or total == "NA") and downloaded not in ("", "NA"):
            try: msg = f"{speed} (Скачано: {_api.human_size(int(downloaded))})"
            except Exception: msg = speed
        else:
            msg = f"{speed} ETA: {eta}"
        # С параллельными фрагментами (--concurrent-fragments) yt-dlp
        # периодически пересчитывает total_bytes_estimate по среднему
        # размеру уже скачанных сегментов — процент от этого может
        # временно проседать, хотя реально скачанные байты не уменьшаются.
        # Не даём прогресс-бару идти назад.
        pct = max(pct, self._last_pct)
        self._enter_download_phase()  # реальный кадр прогресса = загрузка идёт
        self._last_real_progress = _api.time.time()
        self._last_pct = pct
        self.progress_sig.emit(self._iid, pct, msg)
    except Exception:
        pass
