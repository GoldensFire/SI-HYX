@echo off
setlocal

echo ============================================
echo   Building SI-HYX (PyInstaller, onedir mode)
echo ============================================

REM 1) Install / upgrade PyInstaller
python -m pip install --upgrade pyinstaller

REM 2) Build (folder, not single file - fast startup + bin alongside)
pyinstaller --noconfirm --windowed --name SI-HYX --icon=icon.ico main.py
if errorlevel 1 (
    echo [ERROR] Build failed.
    pause
    exit /b 1
)

REM 3) Copy external binaries and icon next to the exe
xcopy /E /I /Y bin "dist\SI-HYX\bin" >nul
copy /Y icon.ico "dist\SI-HYX\" >nul

echo.
echo DONE. Program is here:  dist\SI-HYX\
echo Run: dist\SI-HYX\SI-HYX.exe
echo To distribute - zip the whole dist\SI-HYX folder.
echo.
pause
