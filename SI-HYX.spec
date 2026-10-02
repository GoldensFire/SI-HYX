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
#                   подвкладок «Фото → Удаление объектов/фона», плюс
#                   необязательный dyhit.onnx (трекер «Монтаж → Привязать к
#                   объекту», см. dyhit_tracker.py). Внешние ассеты,
#                   чтобы они НЕ попадали в дельта-апдейт (update-архив = только
#                   код). Код находит их рядом с .exe (см. _resolve_model в
#                   lama_inpaint.py / rmbg_bg.py).
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules, collect_all, collect_data_files

datas = [('icon.ico', '.'), ('open-file.svg', '.')]
# Standalone source for the isolated ML interpreter; torch stays excluded.
datas += [(str(p), 'chiptune') for p in Path('chiptune').glob('*.py')]
binaries = []
# numpy/lxml тянутся лениво (волны/LUFS/разбор .siq), siquester — внутри try/except,
# поэтому пакет включаем целиком. soundfile несёт нативный libsndfile (collect_all).
hiddenimports = ['numpy', 'lxml.etree']
hiddenimports += ['google.auth', 'google.auth.transport.requests',
                  'google.oauth2.service_account']
hiddenimports += collect_submodules('siquester')
hiddenimports += collect_submodules('si_hyx_parts.kuhi')
datas += [('si_hyx_parts/kuhi/LICENSE', 'si_hyx_parts/kuhi')]
# Холст видео «Монтажа» выводит кадр через QML VideoOutput (см. VideoCanvas в
# edit_tab_widgets.py), поэтому в сборку обязаны попасть Qt Quick/Qml вместе с
# их qml-плагинами (их подтягивают хуки PyInstaller для этих модулей) и
# QML-модуль QtMultimedia. Импорт в коде стоит внутри try/except — перечисляем
# явно, чтобы анализатор не решил, что модули необязательные.
hiddenimports += ['PyQt6.QtQml', 'PyQt6.QtQuick', 'PyQt6.QtQuickWidgets']
# Каверы опенингов (docs/anime-covers.md) подключаются ЛЕНИВО — импортом внутри
# функции загрузчика звука и внутри кнопки «Проверить каверы…». Перечисляем
# явно, чтобы анализатор не решил, что модули необязательные.
hiddenimports += ['cover_audio', 'cover_cache', 'cover_fingerprint',
                  'cover_match', 'cover_meta',
                  'cover_meta_rules', 'cover_search', 'cover_select',
                  'cover_service',
                  'si_hyx_parts.animepack.cover_processing',
                  'si_hyx_parts.animepack_tab.cover_controls',
                  'si_hyx_parts.animepack_tab.cover_lang_controls',
                  'si_hyx_parts.animepack_tab.cover_preview']
for _pkg in ('soundfile', 'qtawesome', 'tzdata'):
    _d, _b, _h = collect_all(_pkg)
    datas += _d; binaries += _b; hiddenimports += _h
# RapidOCR resolves model metadata and dictionaries as package data. Its
# optional Torch/Paddle/TensorRT engines must not enter the ONNX-only build.
datas += collect_data_files('rapidocr')

# Тяжёлые пакеты, которые код НЕ импортирует, но PyInstaller втягивал из окружения
# (стек torch/HuggingFace + data-science) — раздували сборку на ~0.5 ГБ впустую.
# Удаление объектов/фона работает ТОЛЬКО на onnxruntime+opencv+numpy, поэтому torch
# и transformers не нужны. Если какой-то пакет реально понадобится — убери из списка.
# pandas здесь с тех пор, как вырезана вкладка «Поиск пакетов» — она была
# единственным его потребителем.
excludes = [
    'pandas', 'bs4', 'emoji', 'mutagen',
    # yt-dlp живёт в bin\yt-dlp.exe и запускается процессом — как ПАКЕТ он в коде
    # не используется (см. комментарий у Optional libs в config.py). Вместе с ним
    # из сборки уходят его зависимости, которые больше никто не тянет:
    # Cryptodome/Crypto, curl_cffi, chardet, websockets, yt_dlp_ejs.
    'yt_dlp', 'yt_dlp_ejs',
    'torch', 'torchvision', 'torchaudio',
    'transformers', 'tokenizers', 'safetensors', 'huggingface_hub',
    'hf_xet', 'datasets', 'accelerate',
    'pyarrow',
    'scipy', 'sklearn', 'scikit_learn',
    'numba', 'llvmlite',
    'matplotlib', 'sympy', 'networkx',
    'IPython', 'jupyter', 'notebook', 'tensorboard',
    'av',  # PyAV не используется: монтаж работает через bundled ffmpeg.exe
    # Qt Quick нужен ТОЛЬКО холсту видео («import QtQuick» + «import
    # QtMultimedia»), но его хук тянет за собой весь стек Quick — включая
    # QtWebEngine (одна Qt6WebEngineCore.dll — 193 МБ!), Quick 3D и Quick
    # Controls. Ни один из них в программе не используется.
    'PyQt6.QtWebEngineCore', 'PyQt6.QtWebEngineWidgets', 'PyQt6.QtWebEngineQuick',
    'PyQt6.QtQuick3D', 'PyQt6.QtQuickWidgets.QtQuick3D',
]

# Что из притащенного хуком Qt Quick выбрасываем. Проверялось замером: без
# фильтра сборка росла на 257 МБ, с ним — на 36 МБ. Список намеренно узкий:
# сцена холста (см. _QML_CANVAS_SOURCE в edit_tab_widgets.py) состоит из Item,
# Rectangle и VideoOutput, то есть базового QtQuick и QtMultimedia — всё
# остальное в Quick-стеке лишнее. Если сцена перестанет подниматься, вкладка
# скажет об этом в лог («сцена Qt Quick не поднялась»), а кадр будет рисоваться
# на ЦП — тогда что-то из списка вернуть.
_QT_QUICK_DROP = (
    'qt6webengine', 'qtwebengine',           # браузерный движок, 193 МБ
    'qt6quick3d', 'qtquick3d',               # 3D-сцены
    'qt6quickcontrols', 'qt6quicktemplates', 'qt6quickdialogs',
    'qtquick/controls', 'qtquick/dialogs', 'qtquick/templates',
    'qtquick/nativestyle', 'qtquick/particles', 'qt6quickparticles',
    'qt6quicktest', 'qtquick/localstorage', 'qt6quickeffects',
    'qtquick/effects', 'qtquick/shapes', 'qt6quickshapes',
    'qtquick/vectorimage', 'qt6quickvectorimage', 'qtquick/timeline',
    'qt6quicktimeline', 'qtquick/scene2d', 'qtquick/scene3d',
    'qt6pdfquick', 'qtquick/pdf',
)


def _quick_junk(dest):
    d = str(dest).replace(os.sep, '/').lower()
    return any(pat in d for pat in _QT_QUICK_DROP)


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
# Фильтруем ПОСЛЕ анализа: часть этого добра приходит не импортами, а
# зависимостями qml-плагинов, и excludes до них не достаёт.
a.binaries = [b for b in a.binaries if not _quick_junk(b[0])]
a.datas = [d for d in a.datas if not _quick_junk(d[0])]

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
