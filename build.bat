@echo off
REM HealthChat Desktop v4.1.0 Build Script - SIMPLE VERSION

echo ========================================
echo HealthChat Desktop v4.1.0 Build
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
if not exist HealthChatDesktop.py (
    echo ERROR: HealthChatDesktop.py not found!
    pause
    exit /b 1
)

echo [3/5] Installing PyInstaller...
pip install --quiet pyinstaller

echo [4/5] Building (this will take 3-5 minutes)...
pyinstaller --noconfirm HealthChatDesktop_optimized.spec

if %errorlevel% neq 0 (
    echo ERROR: Build failed!
    pause
    exit /b 1
)

echo [5/5] Verifying...
if not exist "dist\HealthChatDesktop\HealthChatDesktop.exe" (
    echo ERROR: Executable not created!
    pause
    exit /b 1
)

for %%A in ("dist\HealthChatDesktop\HealthChatDesktop.exe") do set size=%%~zA
set /a sizeMB=%size%/1048576

echo.
echo ========================================
echo BUILD COMPLETE
echo ========================================
echo Location: dist\HealthChatDesktop\
echo Size: %sizeMB% MB
echo.
echo Test it: cd dist\HealthChatDesktop ^&^& HealthChatDesktop.exe
echo ========================================

pause
