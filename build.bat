@echo off
setlocal enabledelayedexpansion

echo ============================================
echo   Building SI-HYX (PyInstaller, spec-driven)
echo ============================================

REM Установи NONINTERACTIVE=1 (build_gui.py делает это сам), чтобы пропустить
REM все "pause" — иначе сборка, запущенная не из интерактивной консоли (GUI,
REM CI), зависнет в ожидании нажатия клавиши.
if not defined NONINTERACTIVE set "NONINTERACTIVE=0"

REM GUI/CI: переводим консоль в UTF-8. Python-вывод и так UTF-8
REM (build_gui.py задаёт PYTHONUTF8), а cmd echo с кириллицей иначе приходит
REM в лог кракозябрами. Для интерактивной консоли кодовую страницу не трогаем.
if "%NONINTERACTIVE%"=="1" chcp 65001 >nul 2>&1

REM Уровень deflate для архивов релиза (см. tools\make_release_zip.py):
REM   4 — почти размер Compress-Archive Optimal, но заметно быстрее;
REM   1 — ещё быстрее, зато zip крупнее примерно на четверть.
REM build_gui.py передаёт 1 для галочки «Быстрые архивы».
if not defined SIHYX_ZIP_LEVEL set "SIHYX_ZIP_LEVEL=4"
REM 1 — переносить неизменные bin/models из прошлого full-архива без сжатия.
if not defined SIHYX_REUSE_ASSETS set "SIHYX_REUSE_ASSETS=1"

REM 0) Read APP_VERSION from config.py so the output folder/zip carry the version
for /f "usebackq delims=" %%V in (`python -c "import config,sys; sys.stdout.write(config.APP_VERSION)"`) do set "APP_VERSION=%%V"
if not defined APP_VERSION (
    echo [ERROR] Could not read APP_VERSION from config.py.
    if not "%NONINTERACTIVE%"=="1" pause
    exit /b 1
)
set "RELEASE_NAME=SI-HYX v%APP_VERSION%"
REM update-архив именуется ОТДЕЛЬНО от полного («UpdateHYX-…»), чтобы его нельзя
REM было перепутать с основным архивом релиза. Апдейтер опознаёт update-архив по
REM префиксу «UpdateHYX» (см. _pick_update_asset в main.py).
set "UPDATE_ZIP=UpdateHYX-v%APP_VERSION%.zip"
set "FULL_ZIP=SI-HYX-v%APP_VERSION%-full.zip"
echo Version: %APP_VERSION%   ->   "%RELEASE_NAME%"

REM Метки [STEP n/9] — по ним build_gui.py считает прогресс/ETA сборки.
REM Печатаются ПЕРЕД тем шагом, который сейчас начинается (см. STEP_WEIGHTS
REM в build_gui.py). Не переставляй/не удаляй, если не готов поправить и там.

REM 1) PyInstaller: обновляем только по явному запросу (build_gui.py →
REM    «Обновлять PyInstaller»). Иначе проверяем, что он уже стоит: pip
REM    --upgrade каждый раз ходит в сеть и добавляет к сборке десятки секунд,
REM    ничего не меняя. Если пакета нет — ставим.
echo [STEP 1/9] Preparing PyInstaller...
if /I "%UPDATE_PYINSTALLER%"=="1" (
    python -m pip install --upgrade pyinstaller
) else (
    python -c "import PyInstaller" >nul 2>&1
    if errorlevel 1 (
        echo [INFO] PyInstaller is not installed — installing...
        python -m pip install --upgrade pyinstaller
    ) else (
        echo [INFO] PyInstaller is already installed — update skipped.
    )
)
if errorlevel 1 ( echo [ERROR] pip install pyinstaller failed. & if not "%NONINTERACTIVE%"=="1" pause & exit /b 1 )

REM 2) Сверка окружения с requirements.txt ДО сборки: PyInstaller кладёт в exe
REM    то, что стоит в окружении, а CI ставит зависимости из requirements.txt.
REM    Разъехавшиеся версии = релиз и тесты проверяют разные библиотеки
REM    (именно так 41 алерт Dependabot жил на Pillow 12.3.0 при 13.0.0 в
REM    окружении). Проверка ничего не ставит — только останавливает сборку.
echo [STEP 2/9] Checking installed versions against requirements.txt...
python tools\check_requirements.py
if errorlevel 1 (
    echo [ERROR] Environment does not match requirements.txt. Fix with: pip install -r requirements.txt
    if not "%NONINTERACTIVE%"=="1" pause
    exit /b 1
)

REM 3) Build STRICTLY from SI-HYX.spec — единый источник правды (иконка, datas,
REM    hidden-imports, исключения тяжёлых неиспользуемых пакетов: torch/transformers/
REM    pandas/scipy/… — раздували сборку на ~0.5 ГБ). Модели и bin НЕ внутри сборки —
REM    они внешние ассеты (копируются ниже), поэтому update-архив остаётся лёгким.
REM    Запуск через `python -m PyInstaller`, а не голым `pyinstaller`: так сборка
REM    гарантированно идёт тем же интерпретатором, чьё окружение проверил шаг 2.
echo [STEP 3/9] Running PyInstaller (this takes a while)...
REM -u: без буферизации. Иначе GUI получает лог PyInstaller пачками только
REM в конце шага, и прогресс/ETA в build_gui.py выглядят «зависшими».
python -u -m PyInstaller --log-level INFO --noconfirm SI-HYX.spec
if errorlevel 1 (
    echo [ERROR] Build failed.
    if not "%NONINTERACTIVE%"=="1" pause
    exit /b 1
)

REM 4) Rename the dist folder to include the version: dist\SI-HYX vX.Y.Z
REM    (bin и models ещё НЕ скопированы — это нужно для лёгкого update-архива)
echo [STEP 4/9] Renaming dist folder...
if exist "dist\%RELEASE_NAME%" rmdir /S /Q "dist\%RELEASE_NAME%"
move /Y "dist\SI-HYX" "dist\%RELEASE_NAME%" >nul
if errorlevel 1 (
    echo [ERROR] Could not rename dist\SI-HYX to "dist\%RELEASE_NAME%".
    if not "%NONINTERACTIVE%"=="1" pause
    exit /b 1
)

REM 5) update-архив — ТОЛЬКО код + _internal (без bin и без models). Качается при
REM    обновлении, если внешние ассеты не менялись. Делаем ДО копирования bin/models.
REM    tools\make_release_zip.py быстрее Compress-Archive, печатает прогресс для
REM    build_gui.py и заменяет готовый архив только после успешной записи.
echo [STEP 5/9] Creating update archive...
python -u tools\make_release_zip.py "dist\%RELEASE_NAME%" "dist\%UPDATE_ZIP%" --step 5
if errorlevel 1 (
    echo [ERROR] Could not create update archive.
    if not "%NONINTERACTIVE%"=="1" pause
    exit /b 1
)

REM 6) Внешние ассеты рядом с .exe: bin\ (ffmpeg/yt-dlp) и models\ (LaMa/RMBG).
REM    Код находит модели рядом с .exe (см. _resolve_model в lama_inpaint.py).
echo [STEP 6/9] Copying bin/models assets...
xcopy /E /I /Y bin "dist\%RELEASE_NAME%\bin" >nul
if not exist "models\lama_fp32.onnx" (
    echo [WARN] models\lama_fp32.onnx not found — «Удаление объектов» в сборке не заработает.
)
if not exist "models\model_uint8.onnx" (
    echo [WARN] models\model_uint8.onnx not found — «Удаление фона» в сборке не заработает.
)
if exist "models" xcopy /E /I /Y models "dist\%RELEASE_NAME%\models" >nul

REM 7) Пишем bin\.binver (хеш bin + models) — ДО упаковки full, чтобы он попал внутрь.
echo [STEP 7/9] Hashing bin/models (.binver)...
python make_manifest.py binver "dist\%RELEASE_NAME%"
if errorlevel 1 (
    echo [ERROR] make_manifest.py binver failed.
    if not "%NONINTERACTIVE%"=="1" pause
    exit /b 1
)

REM 8) full-архив (код + bin + models + .binver). Для новых клиентов и при
REM    изменённых внешних ассетах (новый bin или новая модель).
REM    Если bin/.binver совпал с прошлым full-архивом, bin/models переносятся
REM    из него как есть — их повторное сжатие и было основной потерей времени.
echo [STEP 8/9] Creating full archive...
python -u tools\make_release_zip.py "dist\%RELEASE_NAME%" "dist\%FULL_ZIP%" --step 8 --reuse-assets-from "dist"
if errorlevel 1 (
    echo [ERROR] Could not create full archive.
    if not "%NONINTERACTIVE%"=="1" pause
    exit /b 1
)

REM 9) manifest.json {version, bin_sha, update_sha, full_sha, silent} — ПОСЛЕ обоих
REM    архивов, чтобы записать их SHA256 для проверки целостности при загрузке.
REM    silent берётся из config.SILENT_UPDATE (см. build_gui.py / make_manifest.py).
echo [STEP 9/9] Writing manifest.json...
REM reuse-binver: шаг 7 только что посчитал bin_sha по bin+models. Без флага
REM манифест читал бы эти же полтора гигабайта второй раз.
python -u make_manifest.py manifest "dist\%RELEASE_NAME%" "dist" "dist\%UPDATE_ZIP%" "dist\%FULL_ZIP%" reuse-binver
if errorlevel 1 (
    echo [ERROR] make_manifest.py manifest failed.
    if not "%NONINTERACTIVE%"=="1" pause
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
if not "%NONINTERACTIVE%"=="1" pause
