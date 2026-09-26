# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""ProcessWorker: _avif_prepare_input. Public namespace: workers."""
import workers as _api


def _avif_prepare_input(self, path):
    """Готовит вход для AVIF-конвейера → (path, rot_tmp_file, ширина, высота).

        Авто-поворот по EXIF делается ЗАРАНЕЕ, отдельным .png: ffmpeg сам EXIF-
        ориентацию картинок не применяет, и без этого повёрнутые снимки с
        телефона выходили боком. rot_tmp_file (или None) — временный файл,
        который вызывающий обязан удалить, но только когда ffmpeg уже точно не
        будет читать path. Размеры нужны для расчёта ужимания; если Pillow не
        справился — добираем их ffprobe, а если и это не вышло, вернутся нули
        (вызывающий тогда падает на scale-выражение по макс. стороне)."""
    rot_tmp_file = None
    orig_w, orig_h = 0, 0
    try:
        if _api.Image and _api.ImageOps:
            with _api.Image.open(path) as im:
                im_t = _api.ImageOps.exif_transpose(im)
                orig_w, orig_h = im_t.size
                if im_t is not im:
                    tmp_rot = _api.os.path.join(_api.TEMP_DIR, f"rot_{_api.uuid.uuid4().hex}.png")
                    im_t.save(tmp_rot)
                    path = tmp_rot
                    rot_tmp_file = tmp_rot
    except Exception as e:
        self.log.emit(f"EXIF rotation notice: {e}")

    if not orig_w:
        try:
            p = _api.subprocess.run([_api.FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", path],
                               stdout=_api.subprocess.PIPE, stderr=_api.subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace", creationflags=_api.CREATE_NO_WINDOW)
            # csv_fields: ffprobe печатает «960x540x» (хвостовой
            # разделитель), и проверка len(parts)==2 молча не срабатывала.
            parts = _api.csv_fields(p.stdout, 'x')
            if len(parts) >= 2: orig_w, orig_h = int(parts[0]), int(parts[1])
        except Exception: pass

    return path, rot_tmp_file, orig_w, orig_h
