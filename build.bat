@echo off
REM Garmin Chat Desktop v4.1.0 Build Script - SIMPLE VERSION

echo ========================================
echo Garmin Chat Desktop v4.1.0 Build
echo ========================================
echo.

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python not found
    pause
    exit /b 1
)

echo [1/5] Cleaning...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo [2/5] Checking files...
if not exist GarminChatDesktop.py (
    echo ERROR: GarminChatDesktop.py not found!
    pause
    exit /b 1
)

echo [3/5] Installing PyInstaller...
pip install --quiet pyinstaller

echo [4/5] Building (this will take 3-5 minutes)...
pyinstaller GarminChatDesktop_optimized.spec

if %errorlevel% neq 0 (
    echo ERROR: Build failed!
    pause
    exit /b 1
)

echo [5/5] Verifying...
if not exist "dist\GarminChatDesktop\GarminChatDesktop.exe" (
    echo ERROR: Executable not created!
    pause
    exit /b 1
)

for %%A in ("dist\GarminChatDesktop\GarminChatDesktop.exe") do set size=%%~zA
set /a sizeMB=%size%/1048576

echo.
echo ========================================
echo BUILD COMPLETE
echo ========================================
echo Location: dist\GarminChatDesktop\
echo Size: %sizeMB% MB
echo.
echo Test it: cd dist\GarminChatDesktop ^&^& GarminChatDesktop.exe
echo ========================================

pause
