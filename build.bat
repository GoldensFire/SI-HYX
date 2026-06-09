@echo off
setlocal

echo ============================================
echo   Building SI-HYX (PyInstaller, onedir mode)
echo ============================================

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

echo.
echo DONE. Program is here:  dist\SI-HYX\
echo Run: dist\SI-HYX\SI-HYX.exe
echo To distribute - zip the whole dist\SI-HYX folder.
echo.
pause
