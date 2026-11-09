# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Кодирование видео пака на видеокарте — ТОЛЬКО AV1.

Пак всегда в AV1: других кодеков не бывает ни при каких настройках (просьба
пользователя, «максимально важно»). Поэтому правило одно:

* видеокарта нативно кодирует AV1 (RTX 40xx и новее — av1_nvenc, Radeon
  RX 7000 / Radeon 7x0M — av1_amf, Intel Arc и Core Ultra — av1_qsv) —
  кодирует она;
* не кодирует — кодирует процессор (SVT-AV1), как и раньше.

Настройка `video_encoder` генератора: «auto» — правило выше, «cpu» — всегда
процессор. Поддержку проверяет пробный кадр: в сборке ffmpeg кодировщики есть
все, а запускаются только те, что есть у железа (на GTX 1060 или Radeon Vega
av1_nvenc / av1_amf честно не открываются).

Качество — эквивалент CRF SVT-AV1 из настроек вкладки. Шкала квантайзера у
аппаратного AV1 та же, что у SVT-AV1 (CRF → qindex ≈ ×4: у NVENC `-cq` 0…63,
у AMF и QSV — qindex 0…255), с небольшим запасом в сторону качества.
Замера на самих картах не было: на машине разработки AV1-кодировщика нет.
"""
from __future__ import annotations

import subprocess
import sys
import threading
from dataclasses import dataclass

import ffmpeg_env

MODES = ("auto", "cpu")
MODE_LABELS = {"auto": "Авто (AV1 на видеокарте, если умеет)",
               "cpu": "Процессор (SVT-AV1)"}

NVIDIA, AMD, INTEL = 0x10DE, 0x1002, 0x8086
# Аппаратный AV1 каждой фирмы.
VENDOR_ENCODERS = {NVIDIA: "av1_nvenc", AMD: "av1_amf", INTEL: "av1_qsv"}
ENCODER_NAMES = frozenset(VENDOR_ENCODERS.values())
_SOFTWARE_ADAPTER = 2      # DXGI_ADAPTER_FLAG_SOFTWARE (Basic Render Driver)


@dataclass(frozen=True)
class Adapter:
    name: str
    vendor: int
    dedicated_mb: int


@dataclass(frozen=True)
class GpuEncoder:
    name: str
    adapter: str = ""
    pix_fmt: str = "p010le"

    def args(self, crf) -> list[str]:
        return encode_args(self.name, crf, self.pix_fmt)


def _crf(value) -> int:
    try:
        return max(1, min(63, int(value)))
    except (TypeError, ValueError):
        return 45


def _qindex(crf: int) -> str:
    """qindex AV1 (0…255) для CRF SVT-AV1: ×4 и чуть лучше — у SVT-AV1 к
    базовому кадру ещё идут пониженные смещения иерархии."""
    return str(max(1, min(255, crf * 4 - 12)))


# 10 бит — как у SVT-AV1; 8 бит — запасной вариант: AMF на драйверах старше
# 23.30 10-битный AV1 не открывает, хотя сама карта AV1 кодирует.
PIX_FMTS = ("p010le", "nv12")


def encode_args(name: str, crf, pix_fmt: str = "p010le") -> list[str]:
    """Флаги ffmpeg аппаратного AV1: качество — эквивалент CRF SVT-AV1."""
    if name not in ENCODER_NAMES:
        raise ValueError(f"не AV1-кодировщик видеокарты: {name}")
    if pix_fmt not in PIX_FMTS:
        raise ValueError(f"формат пикселей не из {PIX_FMTS}: {pix_fmt}")
    crf = _crf(crf)
    # Ключевой кадр раз в 10 секунд: у SVT-AV1 они только на сменах сцены,
    # а частые I-кадры зря раздувают файл.
    tail = ["-g", "300", "-pix_fmt", pix_fmt]
    if name == "av1_nvenc":
        return ["-c:v", name, "-preset", "p5", "-tune", "hq", "-rc", "vbr",
                "-cq", str(max(1, crf - 3)), "-b:v", "0", "-spatial-aq", "1",
                *tail]
    if name == "av1_amf":
        q = _qindex(crf)
        return ["-c:v", name, "-usage", "transcoding", "-quality", "quality",
                "-rc", "cqp", "-qp_i", q, "-qp_p", q, *tail]
    # av1_qsv: -q:v включает CQP с этим qindex у P-кадров.
    return ["-c:v", name, "-preset", "slow", "-q:v", _qindex(crf), *tail]


# ── Какие видеокарты есть (DXGI, без запуска внешних программ) ────────────
_adapters_lock = threading.Lock()
_adapters_cache: list[Adapter] | None = None


def _dxgi_adapters() -> list[Adapter]:
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16),
                    ("Data3", ctypes.c_uint16), ("Data4", ctypes.c_ubyte * 8)]

    class LUID(ctypes.Structure):
        _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]

    class DESC1(ctypes.Structure):
        _fields_ = [("Description", wintypes.WCHAR * 128),
                    ("VendorId", wintypes.UINT), ("DeviceId", wintypes.UINT),
                    ("SubSysId", wintypes.UINT), ("Revision", wintypes.UINT),
                    ("DedicatedVideoMemory", ctypes.c_size_t),
                    ("DedicatedSystemMemory", ctypes.c_size_t),
                    ("SharedSystemMemory", ctypes.c_size_t),
                    ("AdapterLuid", LUID), ("Flags", wintypes.UINT)]

    def method(obj, index, *argtypes):
        table = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))
        proto = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)
        return proto(table.contents[index])

    iid = GUID(0x770AAE78, 0xF26F, 0x4DBA,
               (ctypes.c_ubyte * 8)(0xA8, 0x29, 0x25, 0x3C, 0x83, 0xD1, 0xB3, 0x87))
    factory = ctypes.c_void_p()
    dxgi = ctypes.WinDLL("dxgi")
    if dxgi.CreateDXGIFactory1(ctypes.byref(iid), ctypes.byref(factory)) != 0:
        return []
    out = []
    try:
        enum = method(factory, 12, wintypes.UINT, ctypes.POINTER(ctypes.c_void_p))
        for index in range(16):
            adapter = ctypes.c_void_p()
            if enum(factory, index, ctypes.byref(adapter)) != 0:
                break
            try:
                desc = DESC1()
                if method(adapter, 10, ctypes.POINTER(DESC1))(
                        adapter, ctypes.byref(desc)) == 0 and not (
                        desc.Flags & _SOFTWARE_ADAPTER):
                    out.append(Adapter(desc.Description.strip(), desc.VendorId,
                                       int(desc.DedicatedVideoMemory // 2 ** 20)))
            finally:
                method(adapter, 2)(adapter)
    finally:
        method(factory, 2)(factory)
    return out


def adapters() -> list[Adapter]:
    """Видеокарты компьютера (один раз за процесс; [] — узнать не вышло)."""
    global _adapters_cache
    with _adapters_lock:
        if _adapters_cache is None:
            found: list[Adapter] = []
            if sys.platform.startswith("win"):
                try:
                    found = _dxgi_adapters()
                except (OSError, AttributeError, ValueError):
                    found = []
            # Одна карта может прийти дважды (по выходу на монитор).
            _adapters_cache = list(dict.fromkeys(found))
        return list(_adapters_cache)


# ── Пробный кадр: кодирует ли эта карта AV1 ──────────────────────────────
_probe_lock = threading.Lock()
_probe_cache: dict[str, str] = {}


def _probe(name: str, pix_fmt: str, ffmpeg=None) -> bool:
    try:
        done = subprocess.run(
            [ffmpeg or ffmpeg_env.FFMPEG, "-v", "error", "-nostdin", "-f",
             "lavfi", "-i", "color=s=640x360:r=24:d=0.3",
             *encode_args(name, 45, pix_fmt), "-f", "null", "-"],
            stdin=subprocess.DEVNULL, capture_output=True,
            creationflags=ffmpeg_env.CREATE_NO_WINDOW, timeout=30)
        return done.returncode == 0
    except (OSError, subprocess.SubprocessError, ValueError):
        return False


def works(name: str, ffmpeg=None) -> str:
    """Формат пикселей, с которым кодировщик запустился («» — не кодирует)."""
    with _probe_lock:
        if name not in _probe_cache:
            _probe_cache[name] = next(
                (pix for pix in PIX_FMTS if _probe(name, pix, ffmpeg)), "")
        return _probe_cache[name]


def pick(mode="auto", ffmpeg=None) -> GpuEncoder | None:
    """AV1-кодировщик видеокарты или None — кодировать процессором (SVT-AV1)."""
    if mode == "cpu":
        return None
    found = sorted(adapters(), key=lambda a: a.dedicated_mb, reverse=True)
    for adapter in found:
        name = VENDOR_ENCODERS.get(adapter.vendor)
        pix = works(name, ffmpeg) if name else ""
        if pix:
            return GpuEncoder(name, adapter.name, pix)
    if not found:
        # Карты узнать не вышло (не Windows): пробуем все AV1 по порядку.
        for name in VENDOR_ENCODERS.values():
            pix = works(name, ffmpeg)
            if pix:
                return GpuEncoder(name, pix_fmt=pix)
    return None


def adapters_hint() -> str:
    """Какие видеокарты есть — для подсказки на вкладке (без пробных кадров)."""
    found = adapters()
    if not found:
        return "Видеокарту определить не удалось."
    return "Видеокарты: " + ", ".join(a.name for a in found) + "."
