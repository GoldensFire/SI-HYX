# -*- mode: python ; coding: utf-8 -*-
#
# Сборка SI-HYX (PyInstaller, onedir). Это ЕДИНЫЙ источник правды для сборки —
# build.bat вызывает именно его (`pyinstaller --noconfirm SI-HYX.spec`), а не
# длинную команду в одну строку. Меняешь набор пакетов/иконку/исключения —
# правишь здесь.
#
# Что НЕ кладём внутрь сборки (живёт внешними ассетами рядом с .exe, копируется
# build.bat ПОСЛЕ сборки):
#   • bin\        — ffmpeg/yt-dlp и пр. (большие, меняются редко);
#   • models\     — lama_fp32.onnx (~200 МБ) и model_uint8.onnx (~360 МБ) для
#                   подвкладок «Фото → Удаление объектов/фона». Внешние ассеты,
#                   чтобы они НЕ попадали в дельта-апдейт (update-архив = только
#                   код). Код находит их рядом с .exe (см. _resolve_model в
#                   lama_inpaint.py / rmbg_bg.py).
from PyInstaller.utils.hooks import collect_submodules, collect_all

datas = [('icon.ico', '.')]
binaries = []
# numpy/lxml тянутся лениво (волны/LUFS/разбор .siq), siquester — внутри try/except,
# поэтому пакет включаем целиком. soundfile несёт нативный libsndfile (collect_all).
hiddenimports = ['numpy', 'lxml.etree']
hiddenimports += collect_submodules('siquester')
for _pkg in ('soundfile', 'qtawesome'):
    _d, _b, _h = collect_all(_pkg)
    datas += _d; binaries += _b; hiddenimports += _h

# Тяжёлые пакеты, которые код НЕ импортирует, но PyInstaller втягивал из окружения
# (стек torch/HuggingFace + data-science) — раздували сборку на ~0.5 ГБ впустую.
# Удаление объектов/фона работает ТОЛЬКО на onnxruntime+opencv+numpy, поэтому torch
# и transformers не нужны. Если какой-то пакет реально понадобится — убери из списка.
# ВАЖНО: pandas сюда возвращать НЕЛЬЗЯ — вкладка «Поиск пакетов» (sigstats/
# analysis.py, sigstats/export.py) реально импортирует его на уровне модуля,
# exclude тут вслепую вырубал бы всю вкладку в собранном .exe.
excludes = [
    'torch', 'torchvision', 'torchaudio',
    'transformers', 'tokenizers', 'safetensors', 'huggingface_hub',
    'hf_xet', 'datasets', 'accelerate',
    'pyarrow',
    'scipy', 'sklearn', 'scikit_learn',
    'numba', 'llvmlite',
    'matplotlib', 'sympy', 'networkx',
    'IPython', 'jupyter', 'notebook', 'tensorboard',
    'av',  # PyAV не используется: монтаж работает через bundled ffmpeg.exe
]


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='SI-HYX',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['icon.ico'],
    version='version_info.txt',   # Windows-метаданные .exe (версия/копирайт)
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='SI-HYX',
)
