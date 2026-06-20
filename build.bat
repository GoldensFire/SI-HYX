@echo off
setlocal enabledelayedexpansion

echo ============================================
echo   Building SI-HYX (PyInstaller, onedir mode)
echo ============================================

REM 0) Read APP_VERSION from config.py so the output folder/zip carry the version
for /f "usebackq delims=" %%V in (`python -c "import config,sys; sys.stdout.write(config.APP_VERSION)"`) do set "APP_VERSION=%%V"
if not defined APP_VERSION (
    echo [ERROR] Could not read APP_VERSION from config.py.
    pause
    exit /b 1
)
set "RELEASE_NAME=SI-HYX v%APP_VERSION%"
REM update-архив именуется ОТДЕЛЬНО от полного («HYXUpdate-…»), чтобы его нельзя
REM было перепутать с основным архивом релиза. Суффикс «-update.zip» сохранён —
REM по нему апдейтер опознаёт update-архив (см. _pick_update_asset в main.py).
set "UPDATE_ZIP=HYXUpdate-v%APP_VERSION%-update.zip"
set "FULL_ZIP=SI-HYX-v%APP_VERSION%-full.zip"
echo Version: %APP_VERSION%   ->   "%RELEASE_NAME%"

REM 1) Install / upgrade PyInstaller
python -m pip install --upgrade pyinstaller

REM 2) Build (folder, not single file - fast startup + bin alongside)
REM    icon.ico is bundled as data -> lands in dist\SI-HYX\_internal\ (found via _MEIPASS)
REM    --collect-submodules siquester: вкладка SiQuester импортируется лениво
REM    (внутри try/except), поэтому явно включаем весь пакет в сборку.
REM    soundfile/numpy/lxml тоже импортируются лениво (волны/LUFS/разбор .siq) —
REM    --collect-all soundfile тянет нативный libsndfile, остальное hidden-import.
pyinstaller --noconfirm --windowed --name SI-HYX --icon=icon.ico --add-data "icon.ico;." --collect-submodules siquester --collect-all soundfile --collect-all qtawesome --hidden-import numpy --hidden-import lxml.etree main.py
if errorlevel 1 (
    echo [ERROR] Build failed.
    pause
    exit /b 1
)

REM 3) Rename the dist folder to include the version: dist\SI-HYX vX.Y.Z
REM    (bin ещё НЕ скопирован — это нужно для app.zip без bin)
if exist "dist\%RELEASE_NAME%" rmdir /S /Q "dist\%RELEASE_NAME%"
move /Y "dist\SI-HYX" "dist\%RELEASE_NAME%" >nul
if errorlevel 1 (
    echo [ERROR] Could not rename dist\SI-HYX to "dist\%RELEASE_NAME%".
    pause
    exit /b 1
)

REM 4) update-архив — ТОЛЬКО код + _internal (без bin). Качается при обновлении,
REM    если bin не менялся. Делаем ДО копирования bin.
if exist "dist\%UPDATE_ZIP%" del /Q "dist\%UPDATE_ZIP%"
powershell -NoProfile -Command "Compress-Archive -Path 'dist\%RELEASE_NAME%' -DestinationPath 'dist\%UPDATE_ZIP%' -Force"
if errorlevel 1 (
    echo [ERROR] Could not create update archive.
    pause
    exit /b 1
)

REM 5) Copy external binaries next to the exe (icon is already inside _internal)
xcopy /E /I /Y bin "dist\%RELEASE_NAME%\bin" >nul

REM 6) Пишем bin\.binver (хеш bin) — ДО упаковки full, чтобы он попал внутрь.
python make_manifest.py binver "dist\%RELEASE_NAME%"
if errorlevel 1 (
    echo [ERROR] make_manifest.py binver failed.
    pause
    exit /b 1
)

REM 7) full-архив (код + bin + .binver). Для новых клиентов при изменённом bin
REM    и для старых клиентов (легаси-апдейтер).
if exist "dist\%FULL_ZIP%" del /Q "dist\%FULL_ZIP%"
powershell -NoProfile -Command "Compress-Archive -Path 'dist\%RELEASE_NAME%' -DestinationPath 'dist\%FULL_ZIP%' -Force"
if errorlevel 1 (
    echo [ERROR] Could not create full archive.
    pause
    exit /b 1
)

REM 8) manifest.json {version, bin_sha, update_sha, full_sha} — ПОСЛЕ обоих
REM    архивов, чтобы записать их SHA256 для проверки целостности при загрузке.
python make_manifest.py manifest "dist\%RELEASE_NAME%" "dist" "dist\%UPDATE_ZIP%" "dist\%FULL_ZIP%"
if errorlevel 1 (
    echo [ERROR] make_manifest.py manifest failed.
    pause
    exit /b 1
)

echo.
echo DONE. Program is here:  dist\%RELEASE_NAME%\
echo Run: dist\%RELEASE_NAME%\SI-HYX.exe
echo.
echo Upload these 3 assets to the GitHub Release:
echo   1) dist\%FULL_ZIP%     ^(full: code + bin^)
echo   2) dist\%UPDATE_ZIP%   ^(update only: code, no bin^)
echo   3) dist\manifest.json             ^(version + bin/update/full SHA^)
echo.
pause
