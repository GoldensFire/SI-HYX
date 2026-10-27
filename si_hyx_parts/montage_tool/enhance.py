# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Подготовка улучшений перед сборкой: шейдеры Anime4K, кэш RIFE и кэш
вырезанного персонажа. Public namespace: montage_tool.

render, still, preview, contact-sheet и beat-strip зовут prepare_project:
граф (montage_project.vulkan_fx) только ссылается на готовые файлы, а
скачивание, перевод шейдеров и прогон RIFE — здесь, с прогрессом и отменой.
Сбой (нет Vulkan, модель не скачалась, RIFE упал) — не ошибка сборки:
клип собирается без улучшения, причина — в ответе (enhance.errors).

Кэш RIFE клипа: кусок исходника → mpdecimate (повторы рисунка аниме «на
двойках» убираются, иначе промежуточные кадры между одинаковыми дают
рывки) → PNG (HDR — уже в SDR) → rife-ncnn-vulkan -n N на iGPU (-g) →
mkv H.264 все кадры ключевые (точный поиск окна), частота fps_проекта /
speed. Пропуски неравные (двойки и тройки вперемешку) RIFE считает
равными — время внутри куска чуть плывёт, края точные.

Кэш персонажа без фона (Clip.matte): кусок исходника кадр в кадр (тот же
входной seek, что у графа) → маска по кадру (anime — ISNet anime-seg на
1024², rmbg — RMBG-2.0 приложения); кадр, почти равный прошлому (аниме
«на двойках»), берёт его маску → mkv FFV1 yuva420p с частотой исходника."""
import math
import zipfile

import montage_tool as _api
from si_hyx_parts.montage_tool import vision as _vision

_RIFE_FILES = ("rife-ncnn-vulkan.exe", "vcomp140.dll", "LICENSE")


def _shader(preset, ctl):
    """Файл шейдера пресета Anime4K (проходы в compute) — готовит из zip."""
    mp = _api.montage_project
    path = mp.shader_path(preset)
    if _api.os.path.isfile(path):
        return path
    archive = _api.asset("anime4k/Anime4K_v4.0.zip", ctl)
    parts = []
    with zipfile.ZipFile(archive) as z:
        names = set(z.namelist())
        for n in mp.UPSCALE_PRESETS[preset]:
            member = f"{n}.glsl"
            if member not in names:
                raise _api.ToolError("asset_failed", f"нет {member} в Anime4K_v4.0.zip")
            parts.append(z.read(member).decode("utf-8"))
    text = mp.to_compute("\n".join(parts))
    _api.os.makedirs(_api.os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    _api.os.replace(tmp, path)
    return path


def _rife(model, ctl):
    """(exe, папка модели) — из кэша или скачивание файлов по ASSETS."""
    exe = None
    for name in _RIFE_FILES:
        p = _api.asset(f"rife/{name}", ctl)
        if name.endswith(".exe"):
            exe = p
    for name in ("flownet.bin", "flownet.param"):
        p = _api.asset(f"rife/{model}/{name}", ctl)
    return exe, _api.os.path.dirname(p)


def _run(cmd, ctl, timeout=3600, cwd=None):
    proc = _api.subprocess.Popen(cmd, stdin=_api.subprocess.DEVNULL,
                                 stdout=_api.subprocess.DEVNULL, stderr=_api.subprocess.PIPE,
                                 cwd=cwd, creationflags=_api.CREATE_NO_WINDOW | 0x00004000)
    try:
        while True:
            try:
                _out, err = proc.communicate(timeout=0.5)
                break
            except _api.subprocess.TimeoutExpired:
                if ctl.stop():
                    proc.kill()
                    proc.wait()
                    raise _api.ToolError("cancelled", "отменено файлом отмены") from None
                timeout -= 0.5
                if timeout <= 0:
                    proc.kill()
                    proc.wait()
                    raise _api.ToolError("ml_timeout", "обработка не уложилась во время") from None
    finally:
        if proc.poll() is None:
            proc.kill()
    if proc.returncode != 0:
        raise _api.ToolError("ffmpeg_failed", f"{_api.os.path.basename(cmd[0])}: код {proc.returncode}",
                             detail=(err or b"").decode("utf-8", "replace")[-1500:])


def build_interp(c, fps, ctl, gpu=0):
    """Кэш RIFE клипа c (см. модуль). Путь готового файла."""
    mp = _api.montage_project
    path = mp.interp_path(c, fps)
    if _api.os.path.isfile(path):
        return path
    exe, model_dir = _rife(c.interpolate, ctl)
    rate = mp.interp_rate(c, fps)
    span = c.out_s - c.in_s
    n_out = max(2, int(round(span * rate)))
    work = _api.tempfile.mkdtemp(prefix="r", dir=_api.cache_dir("rife", "tmp"))
    try:
        src_dir = _api.os.path.join(work, "in")
        out_dir = _api.os.path.join(work, "out")
        _api.os.makedirs(src_dir)
        _api.os.makedirs(out_dir)
        rgb = _api.hdr_tonemap.rgb_decode_filter(c.src, _api.escape_filter_path, "rgb24")
        ctl.stage("rife", what="frames", clip=c.id)
        _run([_api.FFMPEG, "-v", "error", "-nostdin", "-y", "-ss", f"{c.in_s:.6f}", "-t",
              f"{span:.6f}", "-i", c.src, "-map", "0:v:0", "-vf",
              "mpdecimate," + (rgb or "format=rgb24"), "-fps_mode", "vfr",
              _api.os.path.join(src_dir, "%08d.png")], ctl)
        if len(_api.os.listdir(src_dir)) < 2:
            raise _api.ToolError("rife_failed", "в куске меньше двух разных кадров")
        ctl.stage("rife", what="interpolate", clip=c.id, frames=n_out, model=c.interpolate)
        _run([exe, "-i", src_dir, "-o", out_dir, "-n", str(n_out), "-m", model_dir,
              "-g", str(int(gpu)), "-j", "1:2:2", "-f", "%08d.png"], ctl,
             cwd=_api.os.path.dirname(exe))
        ctl.stage("rife", what="encode", clip=c.id)
        tmp = path + ".tmp.mkv"
        _api.os.makedirs(_api.os.path.dirname(path), exist_ok=True)
        _run([_api.FFMPEG, "-v", "error", "-nostdin", "-y", "-framerate", mp.fps_expr(rate),
              "-i", _api.os.path.join(out_dir, "%08d.png"), "-vf",
              "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p",
              "-c:v", "libx264", "-preset", "veryfast", "-crf", "12", "-g", "1",
              "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", tmp], ctl)
        _api.os.replace(tmp, path)
        return path
    finally:
        _api.shutil.rmtree(work, ignore_errors=True)


class _AnimeSeg:
    """ISNet anime-seg: RGB 0…1 в квадрате 1024 с полями → маска 0…1."""
    SIDE = 1024

    def __init__(self, ctl):
        self.sess = _vision.session(_api.asset("matte/isnetis.onnx", ctl))
        self.name = self.sess.get_inputs()[0].name

    def __call__(self, rgb):
        import cv2
        import numpy as np
        h, w = rgb.shape[:2]
        k = self.SIDE / float(max(h, w))
        nh, nw = max(1, int(round(h * k))), max(1, int(round(w * k)))
        pad = np.zeros((self.SIDE, self.SIDE, 3), np.float32)
        ph, pw = (self.SIDE - nh) // 2, (self.SIDE - nw) // 2
        pad[ph:ph + nh, pw:pw + nw] = cv2.resize(rgb, (nw, nh), interpolation=cv2.INTER_AREA) / 255.0
        m = self.sess.run(None, {self.name: pad.transpose(2, 0, 1)[None]})[0][0, 0]
        m = cv2.resize(m[ph:ph + nh, pw:pw + nw], (w, h), interpolation=cv2.INTER_LINEAR)
        return (np.clip(m, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)


class _Rmbg:
    def __init__(self, _ctl):
        import rmbg_bg
        self.r = rmbg_bg.RMBGRemover()
        if not self.r.is_available():
            raise _api.ToolError("asset_failed", "нет models/model_uint8.onnx (RMBG-2.0)")

    def __call__(self, rgb):
        return self.r.remove(rgb[:, :, ::-1])


def build_matte(c, ctl):
    """Кэш клипа c с альфой (см. модуль). Путь готового файла."""
    import numpy as np
    mp = _api.montage_project
    path = mp.matte_path(c)
    if _api.os.path.isfile(path):
        return path
    fps = float(c.fps or 0.0) or 24.0
    a, b = mp.matte_span(c)
    first = math.floor(a * fps + 1e-3)
    count = max(1, int(math.ceil((b - a) * fps - 1e-3)) + 1)
    probe = _api.media_probe.probe_media(c.src).get("clip") or {}
    w, h = int(probe.get("width") or c.width), int(probe.get("height") or c.height)
    if h > 1080:                          # маска и кадр — не больше 1080 строк
        w, h = int(round(w * 1080 / h / 2)) * 2, 1080
    rgb = _api.hdr_tonemap.rgb_decode_filter(c.src, _api.escape_filter_path, "rgb24")
    vf = f"scale={w}:{h}," + (rgb or "format=rgb24")
    seg = (_Rmbg if c.matte == "rmbg" else _AnimeSeg)(ctl)
    _api.os.makedirs(_api.os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp.mkv"
    dec = _api.subprocess.Popen(
        [_api.FFMPEG, "-v", "error", "-nostdin", "-ss", f"{max(0.0, (first - 0.25) / fps):.6f}",
         "-i", c.src, "-map", "0:v:0", "-vf", vf, "-frames:v", str(count), "-f", "rawvideo", "-"],
        stdout=_api.subprocess.PIPE, stderr=_api.subprocess.DEVNULL,
        creationflags=_api.CREATE_NO_WINDOW | 0x00004000)
    enc = _api.subprocess.Popen(
        [_api.FFMPEG, "-v", "error", "-nostdin", "-y", "-f", "rawvideo", "-pix_fmt", "rgba",
         "-s", f"{w}x{h}", "-framerate", mp.fps_expr(fps), "-i", "-", "-vf",
         "scale=out_color_matrix=bt709:out_range=tv,format=yuva420p", "-c:v", "ffv1",
         "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", tmp],
        stdin=_api.subprocess.PIPE, stderr=_api.subprocess.DEVNULL,
        creationflags=_api.CREATE_NO_WINDOW | 0x00004000)
    size = w * h * 3
    prev = prev_alpha = None
    done = fresh = 0
    try:
        while done < count:
            raw = dec.stdout.read(size)
            if len(raw) < size:
                break
            frame = np.frombuffer(raw, np.uint8).reshape(h, w, 3)
            small = frame[::max(1, h // 36), ::max(1, w // 64)].astype(np.int16)
            if prev is not None and np.abs(small - prev).mean() < 0.6:
                alpha = prev_alpha               # повтор рисунка — та же маска
            else:
                if ctl.stop():
                    raise _api.ToolError("cancelled", "отменено файлом отмены")
                alpha = seg(frame)
                fresh += 1
            prev, prev_alpha = small, alpha
            enc.stdin.write(np.dstack([frame, alpha]).tobytes())
            done += 1
            if done % 12 == 0:
                ctl.stage("matte", clip=c.id, frame=done, frames=count, model_runs=fresh)
        enc.stdin.close()
        if enc.wait(timeout=600) != 0 or done == 0:
            raise _api.ToolError("matte_failed", "кэш персонажа не записан")
        _api.os.replace(tmp, path)
    finally:
        for proc in (dec, enc):
            if proc.poll() is None:
                proc.kill()
                proc.wait()
        if _api.os.path.exists(tmp):
            _api.os.remove(tmp)
    return path


def prepare_project(p, ctl=None, run=True, gpu=0):
    """Готовит шейдеры апскейла и кэш RIFE для проекта p. run=False —
    только отчёт, чего не хватает (dry-run). {'upscale', 'rife', 'errors'}."""
    ctl = ctl or _api.NO_CONTROL
    mp = _api.montage_project
    _w, h, fps = p.output_format()
    out = {"upscale": {}, "rife": [], "errors": []}
    presets = {mp.upscale_of(p, c) for c in p.clips if c.has_video} - {""}
    if presets:
        ok = mp.vulkan_ok()
        out["vulkan"] = ok
        for preset in sorted(presets):
            path = mp.shader_path(preset)
            if not ok:
                out["errors"].append({"what": "upscale", "message": "нет Vulkan: обычное масштабирование"})
            elif run and not _api.os.path.isfile(path):
                try:
                    _shader(preset, ctl)
                except _api.ToolError as e:
                    if e.code == "cancelled":
                        raise
                    out["errors"].append({"what": f"upscale {preset}", "message": e.message})
            out["upscale"][preset] = {"shader": path, "ready": _api.os.path.isfile(path) and ok}
    out["matte"] = []
    for c in p.clips:
        if not mp.matte_wanted(c):
            continue
        path = mp.matte_path(c)
        item = {"clip": c.id, "model": c.matte, "cache": path, "ready": _api.os.path.isfile(path)}
        if run and not item["ready"]:
            try:
                build_matte(c, ctl)
                item["ready"] = True
            except _api.ToolError as e:
                if e.code == "cancelled":
                    raise
                out["errors"].append({"what": f"matte {c.id}", "message": e.message})
        out["matte"].append(item)
    for c in p.clips:
        if not mp.interp_wanted(c) or c.matte:
            continue
        path = mp.interp_path(c, fps)
        item = {"clip": c.id, "model": c.interpolate, "speed": round(c.play_speed, 4),
                "cache": path, "ready": _api.os.path.isfile(path)}
        if run and not item["ready"]:
            try:
                build_interp(c, fps, ctl, gpu)
                item["ready"] = True
            except _api.ToolError as e:
                if e.code == "cancelled":
                    raise
                out["errors"].append({"what": f"rife {c.id}", "message": e.message,
                                      "detail": (e.detail or "")[-300:]})
        out["rife"].append(item)
    return out
