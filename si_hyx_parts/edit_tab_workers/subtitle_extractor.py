# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Извлечение дорожки субтитров в фоне. Public namespace: edit_tab_workers."""
import edit_tab_workers as _api


class SubtitleExtractor(_api.QThread):
    """Извлекает выбранную текстовую дорожку субтитров в SRT и парсит её —
    в фоне, чтобы не подвешивать GUI."""
    done = _api.pyqtSignal(int, object)   # (token, cues|None)

    def __init__(self, src, sub_index, token):
        super().__init__()
        self.src = str(src)
        self.sub_index = int(sub_index)
        self.token = int(token)

    def run(self):
        cues = None
        tmp = None
        try:
            ext = _api.os.path.splitext(self.src)[1].lower()
            if self.sub_index == 0 and ext == '.srt':
                # Внешний SRT читаем сами: ffmpeg считает его UTF-8 и
                # заменяет кириллицу из cp1251 на «�» (см. read_subtitle_text).
                cues = _api._parse_srt(_api.read_subtitle_text(self.src))
            else:
                tf = _api.tempfile.NamedTemporaryFile(delete=False, suffix=".srt")
                tmp = tf.name; tf.close()
                cmd = [_api.FFMPEG, "-y"]
                if self.sub_index == 0 and ext in ('.ass', '.ssa'):
                    # Внешний ASS/SSA в cp1251: без sub_charenc ffmpeg либо
                    # отказывается его читать, либо заменяет кириллицу на «�».
                    try:
                        cmd += ["-sub_charenc", _api.subtitle_text_encoding(self.src)]
                    except Exception:
                        pass
                cmd += ["-i", self.src,
                        "-map", f"0:s:{self.sub_index}", tmp]
                kw = {}
                if _api.os.name == 'nt':
                    kw['creationflags'] = _api.CREATE_NO_WINDOW
                _api.subprocess.run(cmd, stdout=_api.subprocess.DEVNULL,
                               stderr=_api.subprocess.DEVNULL, timeout=90, **kw)
                if _api.os.path.exists(tmp) and _api.os.path.getsize(tmp) > 0:
                    with open(tmp, 'r', encoding='utf-8', errors='replace') as f:
                        cues = _api._parse_srt(f.read())
        except Exception:
            cues = None
        finally:
            if tmp:
                try: _api.os.remove(tmp)
                except Exception: pass
        self.done.emit(self.token, cues)

SubtitleExtractor.__module__ = _api.__name__
_api.SubtitleExtractor = SubtitleExtractor
