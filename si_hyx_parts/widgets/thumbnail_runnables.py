# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Фоновая загрузка миниатюр: локальных и по сети. Public namespace: widgets."""
import widgets as _api


class LocalThumbnailRunnable(_api.QRunnable):
    def __init__(self, path, iid, signal):
        super().__init__(); self.path = path; self.iid = iid; self.signal = signal
    def run(self):
        try:
            ext = _api.Path(self.path).suffix.lower()
            if ext in _api.ALLOWED_IMG and _api.Image:
                try:
                    with _api.Image.open(self.path) as im:
                        if _api.ImageOps: im = _api.ImageOps.exif_transpose(im)
                        im.thumbnail((320, 180), _api.Image.LANCZOS)
                        icon = _api.pil_to_qicon(im)
                        if not icon.isNull():
                            self.signal.emit(self.iid, icon)
                            return
                except Exception: pass
            out = _api.os.path.join(_api.TEMP_DIR, f"thumb_{self.iid}.png")
            # Сначала пробуем кадр на 1с, если файл короче — берём первый кадр
            cmd = [_api.FFMPEG, "-y", "-ss", "00:00:01", "-i", self.path, "-vframes", "1", "-vf", "scale=320:-1", "-q:v", "4", out]
            try: _api.subprocess.run(cmd, stdout=_api.subprocess.DEVNULL, stderr=_api.subprocess.DEVNULL, creationflags=_api.CREATE_NO_WINDOW, check=False, timeout=8)
            except Exception: pass
            if not _api.os.path.exists(out) or _api.os.path.getsize(out) < 100:
                # Fallback: первый доступный кадр
                cmd = [_api.FFMPEG, "-y", "-i", self.path, "-vframes", "1", "-vf", "scale=320:-1", "-q:v", "4", out]
            try: _api.subprocess.run(cmd, stdout=_api.subprocess.DEVNULL, stderr=_api.subprocess.DEVNULL, creationflags=_api.CREATE_NO_WINDOW, check=False)
            except Exception: pass
            if _api.os.path.exists(out):
                try:
                    if _api.Image:
                        with _api.Image.open(out) as im:
                            im.thumbnail((160, 90))
                            icon = _api.pil_to_qicon(im)
                            if not icon.isNull(): self.signal.emit(self.iid, icon)
                    else:
                        with open(out, "rb") as f:
                            data = f.read()
                        pix = _api.QPixmap()
                        if pix.loadFromData(data): self.signal.emit(self.iid, _api.QIcon(pix))
                except Exception: pass
                try: _api.os.remove(out)
                except Exception: pass
        except Exception: pass

LocalThumbnailRunnable.__module__ = _api.__name__
_api.LocalThumbnailRunnable = LocalThumbnailRunnable


class RemoteThumbnailRunnable(_api.QRunnable):
    def __init__(self, url, iid, signal):
        super().__init__(); self.url = url; self.iid = iid; self.signal = signal
    def run(self):
        if not self.url: return
        try:
            tmp = _api.os.path.join(_api.TEMP_DIR, f"yt_thumb_{self.iid}.tmp")
            with _api.http_get(self.url, headers={'User-Agent': _api.USER_AGENT}, timeout=20) as r, open(tmp, 'wb') as f:
                f.write(r.read())

            if _api.Image:
                with _api.Image.open(tmp) as im:
                    im.thumbnail((160, 90))
                    icon = _api.pil_to_qicon(im)
                    if not icon.isNull(): self.signal.emit(self.iid, icon)
            else:
                with open(tmp, 'rb') as f:
                    data = f.read()
                pix = _api.QPixmap()
                if pix.loadFromData(data): self.signal.emit(self.iid, _api.QIcon(pix))
            try: _api.os.remove(tmp)
            except Exception: pass
        except Exception: pass

RemoteThumbnailRunnable.__module__ = _api.__name__
_api.RemoteThumbnailRunnable = RemoteThumbnailRunnable
