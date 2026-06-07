@echo off
chcp 65001 >nul
echo ============================================
echo   Сборка SI-HYX (PyInstaller, режим onedir)
echo ============================================

REM 1) Установка/проверка PyInstaller
python -m pip install --upgrade pyinstaller >nul 2>&1

REM 2) Сборка (папка, а не один файл — быстрый старт + bin рядом)
pyinstaller --noconfirm --windowed --name SI-HYX --icon=icon.ico main.py
if errorlevel 1 (
    echo [ОШИБКА] Сборка не удалась.
    pause
    exit /b 1
)

REM 3) Кладём внешние бинарники и иконку рядом с exe
xcopy /E /I /Y bin "dist\SI-HYX\bin" >nul
copy /Y icon.ico "dist\SI-HYX\" >nul
if exist "Промпт.txt" copy /Y "Промпт.txt" "dist\SI-HYX\" >nul

echo.
echo ГОТОВО. Программа здесь:  dist\SI-HYX\
echo Запуск: dist\SI-HYX\SI-HYX.exe
echo Для раздачи — заархивируй всю папку dist\SI-HYX в zip.
echo.
pause
