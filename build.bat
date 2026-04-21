@echo off
setlocal

echo [1/3] Checking Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo Python not found. Please install Python first.
    pause
    exit /b 1
)

echo [2/3] Checking PyInstaller...
python -m pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo PyInstaller not found. Installing...
    python -m pip install pyinstaller
    if errorlevel 1 (
        echo Failed to install PyInstaller.
        pause
        exit /b 1
    )
)

echo [3/3] Building EXE...
python -m PyInstaller --noconfirm --clean --onefile --windowed --name "cc-session-util" "main.py"
if errorlevel 1 (
    echo Build failed.
    pause
    exit /b 1
)

echo.
echo Build succeeded!
echo Output: dist\cc-session-util.exe
pause
exit /b 0
