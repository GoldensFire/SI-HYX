# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""PgsExtractor. Public namespace: edit_tab_workers."""
import edit_tab_workers as _api
import pgs_subtitles


class PgsExtractor(_api.QThread):
    """Копирует дорожку PGS (картиночные субтитры Blu-ray) потоком .sup и
    разбирает её (pgs_subtitles.parse_sup) — в фоне. Эмитит (token,
    PgsTrack|None). Плееру Qt такие дорожки не отдаются: см. pgs_subtitles."""
    done = _api.pyqtSignal(int, object)   # (token, PgsTrack|None)

    def __init__(self, src, sub_index, token):
        super().__init__()
        self.src = str(src)
        self.sub_index = int(sub_index)
        self.token = int(token)

    def run(self):
        track = None
        try:
            # Копия без перекодирования — только демультиплексирование файла.
            cmd = [_api.FFMPEG, "-nostdin", "-v", "error", "-i", self.src,
                   "-map", f"0:s:{self.sub_index}", "-c:s", "copy",
                   "-f", "sup", "-"]
            kw = {}
            if _api.os.name == 'nt':
                kw['creationflags'] = _api.CREATE_NO_WINDOW
            pr = _api.subprocess.run(cmd, stdout=_api.subprocess.PIPE,
                                     stderr=_api.subprocess.DEVNULL,
                                     timeout=300, **kw)
            if pr.stdout:
                track = pgs_subtitles.parse_sup(pr.stdout)
                if not track.has_images():
                    track = None
        except Exception:
            track = None
        self.done.emit(self.token, track)

PgsExtractor.__module__ = _api.__name__
_api.PgsExtractor = PgsExtractor
