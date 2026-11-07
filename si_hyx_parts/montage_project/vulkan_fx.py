# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Качество картинки на Vulkan: апскейл Anime4K и кэш интерполяции RIFE.
Public namespace: montage_project.

Anime4K (bloc97, MIT) — шейдеры mpv через libplacebo нашей сборки ffmpeg
(custom_shader_path). На iGPU Radeon (драйвер AMD) фрагментные проходы
пользовательских шейдеров libplacebo дают чёрный кадр, а compute — верный,
поэтому проходы переводятся в compute (to_compute: код прохода — в
hook_frag(), hook() пишет его в out_image). Применяется, только если кадр
исходника меньше кадра проекта (нужен апскейл); нет Vulkan (vulkan_ok) или
файла шейдера (готовит montage_tool) — обычное масштабирование.

Каждый экземпляр libplacebo держит до конца сборки ~50 МБ текстур в
device-local куче iGPU (256 МБ): больше ~21 клипа в одном графе — ffmpeg
падает (0xC0000005). Поэтому клип берётся из кэша апскейла (upscale_source:
кусок исходника — или кэша вырезки / RIFE — уже в 2×, по процессу ffmpeg на
клип, готовит montage_tool), а libplacebo в графе — запасной путь без кэша;
там все экземпляры делят одно устройство Vulkan (SourceGraph.input_args).
Альфа вырезки идёт мимо libplacebo: масштабируется отдельно и
возвращается alphamerge.

RIFE (rife-ncnn-vulkan, TNTwise, MIT) — замедленный клип (play_speed < 1,
Clip.interpolate = модель) берётся из кэша промежуточного видео: кадров с
частотой fps_проекта / speed на тот же кусок исходника, так что после
setpts/speed на кадр проекта приходится свой кадр кэша. Ключ кэша — файл
(путь, размер, время правки), кусок, скорость, модель и fps проекта; нет
кэша — клип собирается как раньше (без интерполяции)."""
import functools
import hashlib
import os
import re
import subprocess

import montage_project as _api

UPSCALE_PRESETS = {
    "anime4k_s": ("Anime4K_Clamp_Highlights", "Anime4K_Restore_CNN_S", "Anime4K_Upscale_CNN_x2_S"),
    "anime4k_m": ("Anime4K_Clamp_Highlights", "Anime4K_Restore_CNN_M", "Anime4K_Upscale_CNN_x2_M"),
    "anime4k_l": ("Anime4K_Clamp_Highlights", "Anime4K_Restore_CNN_L", "Anime4K_Upscale_CNN_x2_L"),
}
RIFE_MODELS = ("rife-v4.22-lite", "rife-v4.25")
CACHE_ENV = "SI_HYX_MONTAGE_CACHE"
_RIFE_VERSION = 1
_UPSCALE_VERSION = 1
# Общее устройство Vulkan для всех libplacebo графа (глобальные опции ffmpeg).
VULKAN_DEVICE_ARGS = ["-init_hw_device", "vulkan=vk", "-filter_hw_device", "vk"]


def cache_root():
    """Кэш montage_tool (как montage_tool.cache_dir, без создания папки)."""
    return os.environ.get(CACHE_ENV) or os.path.join(os.path.expanduser("~"), ".cache",
                                                     "si-hyx-montage")


# ── Anime4K ──────────────────────────────────────────────────────────────────
def to_compute(text):
    """Шейдер mpv с проходами-фрагментами → те же проходы как compute."""
    lines = text.replace("\r\n", "\n").split("\n")
    head, blocks, hdr, body = [], [], [], []
    for ln in lines:
        if ln.startswith("//!"):
            if body and hdr:
                blocks.append((hdr, body))
                hdr, body = [], []
            elif body:
                head.extend(body)
                body = []
            hdr.append(ln)
        else:
            body.append(ln)
    if hdr:
        blocks.append((hdr, body))
    else:
        head.extend(body)
    out = list(head)
    rx = re.compile(r"vec4\s+hook\s*\(\s*\)")
    for hdr, body in blocks:
        code = "\n".join(body)
        if not any(h.startswith("//!COMPUTE") for h in hdr) and rx.search(code):
            hdr = hdr + ["//!COMPUTE 16 16"]
            code = rx.sub("vec4 hook_frag()", code, count=1)
            code += ("\nvoid hook() {\n    imageStore(out_image, ivec2(gl_GlobalInvocationID), "
                     "hook_frag());\n}\n")
        out.extend(hdr)
        out.append(code)
    return "\n".join(out)


def shader_path(preset):
    return os.path.join(cache_root(), "anime4k", f"{preset}.compute.glsl")


@functools.lru_cache(maxsize=1)
def vulkan_ok():
    """libplacebo нашей сборки ffmpeg поднимает Vulkan (один пробный кадр)."""
    if os.environ.get("SI_HYX_NO_VULKAN"):
        return False
    from ffmpeg_env import CREATE_NO_WINDOW, FFMPEG
    try:
        r = subprocess.run([FFMPEG, "-v", "error", "-nostdin", "-f", "lavfi", "-i",
                            "color=c=gray:s=64x64:d=0.04", "-vf",
                            "libplacebo=w=128:h=128:format=yuv420p", "-frames:v", "1",
                            "-f", "null", "-"], capture_output=True, timeout=60,
                           creationflags=CREATE_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0


def upscale_of(project, c):
    """Пресет апскейла клипа: свой (none — выключен) или проекта; ""."""
    if c.upscale == "none":
        return ""
    return c.upscale or project.settings.upscale or ""


def upscale_wanted(project, c, out_h):
    """Пресет апскейла клипа c или "": выключен, картинка, кадр исходника не
    меньше кадра проекта."""
    preset = upscale_of(project, c)
    if not preset or c.is_image or not c.height or c.height >= out_h:
        return ""
    return preset


def upscale_vf(preset, deband, alpha=False, lab=None):
    """Цепочка апскейла 2× с запятой в конце или "": нет Vulkan или файла
    шейдера. alpha — у кадра есть альфа (вырезка): libplacebo получает кадр
    без неё, альфа масштабируется отдельно; lab — метки (обязательна при
    alpha)."""
    path = shader_path(preset)
    if not os.path.isfile(path) or not vulkan_ok():
        return ""
    from ffmpeg_env import escape_filter_path
    pl = (f"libplacebo=w=iw*2:h=ih*2:custom_shader_path={escape_filter_path(path)}"
          f"{':deband=true' if deband else ''}:format=yuv420p")
    if not alpha:
        return pl + ","
    k, a, al, u = lab("uk"), lab("ua"), lab("ual"), lab("uu")
    # format до split: иначе согласование форматов отдаёт split кадр без
    # альфы (ветке libplacebo она не нужна) и alphaextract не настраивается.
    return (f"format=yuva420p,split[{k}][{a}];[{a}]alphaextract,scale=iw*2:ih*2[{al}];"
            f"[{k}]format=yuv420p,{pl}[{u}];[{u}][{al}]alphamerge,")


def upscale_filter(project, c, out_h, alpha=False, lab=None):
    """libplacebo с Anime4K для клипа c или "": выключено, кадр исходника не
    меньше кадра проекта, нет Vulkan или файла шейдера. alpha, lab — как у
    upscale_vf."""
    preset = upscale_wanted(project, c, out_h)
    if not preset:
        return ""
    return upscale_vf(preset, project.settings.deband, alpha, lab)


def upscale_key(base, preset, deband):
    """Ключ кэша апскейла: исходник base (файл или кэш вырезки / RIFE) —
    путь, размер, время правки, кусок; пресет и deband."""
    try:
        st = os.stat(base.src)
        stamp = f"{st.st_size}:{st.st_mtime_ns}"
    except OSError:
        stamp = "missing"
    a, b = _api.matte_span(base)
    raw = (f"{os.path.abspath(base.src)}|{stamp}|{a:.6f}|{b:.6f}|{preset}|{int(bool(deband))}|"
           f"v{_UPSCALE_VERSION}")
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def upscale_path(base, preset, deband):
    return os.path.join(cache_root(), "upscale", f"{upscale_key(base, preset, deband)}.mkv")


def upscale_source(project, c, base, out_h):
    """Клип-заместитель для цепочки картинки: исходник — кэш апскейла куска
    base (кусок с нуля, как у matte_source) или None: апскейла нет, кэш не
    готов. c — клип проекта (пресет, размер кадра), base — что граф читал
    бы без апскейла: c или его кэш вырезки / RIFE."""
    preset = upscale_wanted(project, c, out_h)
    if not preset:
        return None
    path = upscale_path(base, preset, project.settings.deband)
    if not os.path.isfile(path):
        return None
    from dataclasses import replace
    a, b = _api.matte_span(base)
    if base.frozen:
        return replace(base, src=path, freeze_at=0.0, src_duration=b - a, matte="")
    return replace(base, src=path, in_s=0.0, out_s=b - a, src_duration=b - a, matte="")


# ── RIFE ─────────────────────────────────────────────────────────────────────
def interp_wanted(c):
    return (bool(c.interpolate) and c.has_video and not c.is_image and not c.frozen
            and not c.reverse and not c.speed_curve and c.play_speed < 1.0 - 1e-6)


def interp_key(c, project_fps):
    try:
        st = os.stat(c.src)
        stamp = f"{st.st_size}:{st.st_mtime_ns}"
    except OSError:
        stamp = "missing"
    raw = (f"{os.path.abspath(c.src)}|{stamp}|{c.in_s:.6f}|{c.out_s:.6f}|"
           f"{c.play_speed:.6f}|{c.interpolate}|{project_fps:.6f}|v{_RIFE_VERSION}")
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def interp_path(c, project_fps):
    return os.path.join(cache_root(), "rife", "clips", f"{interp_key(c, project_fps)}.mkv")


def interp_rate(c, project_fps):
    """Частота кадров кэша: после замедления на speed — кадр на кадр проекта."""
    return project_fps / c.play_speed


def interp_source(c, project_fps):
    """Клип-заместитель для цепочки картинки: исходник — кэш RIFE (кусок с
    нуля, его частота) или None, если интерполяции нет или кэш не готов."""
    if not interp_wanted(c):
        return None
    path = interp_path(c, project_fps)
    if not os.path.isfile(path):
        return None
    from dataclasses import replace
    span = c.out_s - c.in_s
    return replace(c, src=path, in_s=0.0, out_s=span, fps=interp_rate(c, project_fps),
                   src_duration=span)
