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
echo Version: %APP_VERSION%   ->   "%RELEASE_NAME%"

REM 1) Install / upgrade PyInstaller
python -m pip install --upgrade pyinstaller

REM 2) Build (folder, not single file - fast startup + bin alongside)
REM    icon.ico is bundled as data -> lands in dist\SI-HYX\_internal\ (found via _MEIPASS)
pyinstaller --noconfirm --windowed --name SI-HYX --icon=icon.ico --add-data "icon.ico;." main.py
if errorlevel 1 (
    echo [ERROR] Build failed.
    pause
    exit /b 1
)

REM 3) Copy external binaries next to the exe (icon is already inside _internal)
xcopy /E /I /Y bin "dist\SI-HYX\bin" >nul

REM 4) Rename the dist folder to include the version: dist\SI-HYX vX.Y.Z
if exist "dist\%RELEASE_NAME%" rmdir /S /Q "dist\%RELEASE_NAME%"
move /Y "dist\SI-HYX" "dist\%RELEASE_NAME%" >nul
if errorlevel 1 (
    echo [ERROR] Could not rename dist\SI-HYX to "dist\%RELEASE_NAME%".
    pause
    exit /b 1
)

REM 5) Archive the versioned folder to a .zip next to it
if exist "dist\%RELEASE_NAME%.zip" del /Q "dist\%RELEASE_NAME%.zip"
powershell -NoProfile -Command "Compress-Archive -Path 'dist\%RELEASE_NAME%' -DestinationPath 'dist\%RELEASE_NAME%.zip' -Force"
if errorlevel 1 (
    echo [ERROR] Could not create zip archive.
    pause
    exit /b 1
)

echo.
echo DONE. Program is here:  dist\%RELEASE_NAME%\
echo Run: dist\%RELEASE_NAME%\SI-HYX.exe
echo Archive: dist\%RELEASE_NAME%.zip
echo.
pause
