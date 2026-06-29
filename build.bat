@echo off
setlocal enabledelayedexpansion

echo ============================================
echo   Building SI-HYX (PyInstaller, spec-driven)
echo ============================================

REM 0) Read APP_VERSION from config.py so the output folder/zip carry the version
for /f "usebackq delims=" %%V in (`python -c "import config,sys; sys.stdout.write(config.APP_VERSION)"`) do set "APP_VERSION=%%V"
if not defined APP_VERSION (
    echo [ERROR] Could not read APP_VERSION from config.py.
    pause
    exit /b 1
)
set "RELEASE_NAME=SI-HYX v%APP_VERSION%"
REM update-архив именуется ОТДЕЛЬНО от полного («UpdateHYX-…»), чтобы его нельзя
REM было перепутать с основным архивом релиза. Апдейтер опознаёт update-архив по
REM префиксу «UpdateHYX» (см. _pick_update_asset в main.py).
set "UPDATE_ZIP=UpdateHYX-v%APP_VERSION%.zip"
set "FULL_ZIP=SI-HYX-v%APP_VERSION%-full.zip"
echo Version: %APP_VERSION%   ->   "%RELEASE_NAME%"

REM 1) Install / upgrade PyInstaller
python -m pip install --upgrade pyinstaller
if errorlevel 1 ( echo [ERROR] pip install pyinstaller failed. & pause & exit /b 1 )

REM 2) Build STRICTLY from SI-HYX.spec — единый источник правды (иконка, datas,
REM    hidden-imports, исключения тяжёлых неиспользуемых пакетов: torch/transformers/
REM    pandas/scipy/… — раздували сборку на ~0.5 ГБ). Модели и bin НЕ внутри сборки —
REM    они внешние ассеты (копируются ниже), поэтому update-архив остаётся лёгким.
pyinstaller --noconfirm SI-HYX.spec
if errorlevel 1 (
    echo [ERROR] Build failed.
    pause
    exit /b 1
)

REM 3) Rename the dist folder to include the version: dist\SI-HYX vX.Y.Z
REM    (bin и models ещё НЕ скопированы — это нужно для лёгкого update-архива)
if exist "dist\%RELEASE_NAME%" rmdir /S /Q "dist\%RELEASE_NAME%"
move /Y "dist\SI-HYX" "dist\%RELEASE_NAME%" >nul
if errorlevel 1 (
    echo [ERROR] Could not rename dist\SI-HYX to "dist\%RELEASE_NAME%".
    pause
    exit /b 1
)

REM 4) update-архив — ТОЛЬКО код + _internal (без bin и без models). Качается при
REM    обновлении, если внешние ассеты не менялись. Делаем ДО копирования bin/models.
if exist "dist\%UPDATE_ZIP%" del /Q "dist\%UPDATE_ZIP%"
powershell -NoProfile -Command "Compress-Archive -Path 'dist\%RELEASE_NAME%' -DestinationPath 'dist\%UPDATE_ZIP%' -Force"
if errorlevel 1 (
    echo [ERROR] Could not create update archive.
    pause
    exit /b 1
)

REM 5) Внешние ассеты рядом с .exe: bin\ (ffmpeg/yt-dlp) и models\ (LaMa/RMBG).
REM    Код находит модели рядом с .exe (см. _resolve_model в lama_inpaint.py).
xcopy /E /I /Y bin "dist\%RELEASE_NAME%\bin" >nul
if not exist "models\lama_fp32.onnx" (
    echo [WARN] models\lama_fp32.onnx not found — «Удаление объектов» в сборке не заработает.
)
if not exist "models\model_uint8.onnx" (
    echo [WARN] models\model_uint8.onnx not found — «Удаление фона» в сборке не заработает.
)
if exist "models" xcopy /E /I /Y models "dist\%RELEASE_NAME%\models" >nul

REM 6) Пишем bin\.binver (хеш bin + models) — ДО упаковки full, чтобы он попал внутрь.
python make_manifest.py binver "dist\%RELEASE_NAME%"
if errorlevel 1 (
    echo [ERROR] make_manifest.py binver failed.
    pause
    exit /b 1
)

REM 7) full-архив (код + bin + models + .binver). Для новых клиентов и при
REM    изменённых внешних ассетах (новый bin или новая модель).
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
echo   1) dist\%FULL_ZIP%     ^(full: code + bin + models^)
echo   2) dist\%UPDATE_ZIP%   ^(update only: code, no bin/models^)
echo   3) dist\manifest.json             ^(version + bin/update/full SHA^)
echo.
pause
