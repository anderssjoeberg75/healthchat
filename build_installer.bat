@echo off
REM Garmin Chat Desktop v4.1.0 Installer Build Script
REM Requires: Inno Setup 6.x installed
REM This script creates the Windows installer from the built executable

echo ==========================================
echo Garmin Chat Desktop Installer Build
echo ==========================================
echo.

REM Check if dist folder exists
if not exist "dist\GarminChatDesktop" (
    echo ERROR: dist\GarminChatDesktop folder not found!
    echo Please run build.bat first to create the executable.
    pause
    exit /b 1
)

REM Check if executable exists
if not exist "dist\GarminChatDesktop\GarminChatDesktop.exe" (
    echo ERROR: GarminChatDesktop.exe not found in dist folder!
    echo Please run build.bat first.
    pause
    exit /b 1
)

echo [1/4] Verifying required files...

REM Check for required documentation
set MISSING_FILES=0
if not exist "README.md" (
    echo WARNING: README.md not found
    set MISSING_FILES=1
)
if not exist "CHANGELOG.md" (
    echo WARNING: CHANGELOG.md not found
    set MISSING_FILES=1
)
if not exist "INSTALLATION_GUIDE.md" (
    echo WARNING: INSTALLATION_GUIDE.md not found
    set MISSING_FILES=1
)
if not exist "OLLAMA_SETUP_GUIDE.md" (
    echo WARNING: OLLAMA_SETUP_GUIDE.md not found
    set MISSING_FILES=1
)
if not exist "LICENSE.txt" (
    echo WARNING: LICENSE.txt not found - creating placeholder...
    echo MIT License > LICENSE.txt
    echo. >> LICENSE.txt
    echo Copyright ^(c^) 2025 >> LICENSE.txt
    echo. >> LICENSE.txt
    echo See repository for full license text. >> LICENSE.txt
)

if %MISSING_FILES%==1 (
    echo.
    echo Some documentation files are missing but installer will continue.
    echo Consider adding them for a complete installation package.
    echo.
    timeout /t 3
)

echo [2/4] Locating Inno Setup...

REM Try to find Inno Setup compiler
set "ISCC_PATH="
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" set "ISCC_PATH=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if exist "C:\Program Files\Inno Setup 6\ISCC.exe" if not defined ISCC_PATH set "ISCC_PATH=C:\Program Files\Inno Setup 6\ISCC.exe"

if not defined ISCC_PATH (
    echo ERROR: Inno Setup compiler ISCC.exe not found!
    echo.
    echo Please install Inno Setup 6 from:
    echo https://jrsoftware.org/isdl.php
    echo.
    echo Default installation paths checked:
    echo - C:\Program Files ^(x86^)\Inno Setup 6\
    echo - C:\Program Files\Inno Setup 6\
    echo.
    pause
    exit /b 1
)

echo    Found: %ISCC_PATH%

echo [3/4] Building installer with Inno Setup...
echo    This may take 1-2 minutes...
echo.

REM Run Inno Setup compiler
"%ISCC_PATH%" installer_script.iss

if %errorlevel% neq 0 (
    echo.
    echo ERROR: Inno Setup compilation failed!
    echo Please check installer_script.iss for errors.
    pause
    exit /b 1
)

echo [4/4] Verifying installer...

REM Find the created installer
set INSTALLER_NAME=GarminChatSetup_v4.0.4.exe
if not exist "%INSTALLER_NAME%" (
    echo ERROR: Installer not created!
    echo Expected: %INSTALLER_NAME%
    pause
    exit /b 1
)

REM Get installer size
for %%A in ("%INSTALLER_NAME%") do set size=%%~zA
set /a sizeMB=%size%/1048576

echo.
echo ==========================================
echo Installer Build Complete!
echo ==========================================
echo File: %INSTALLER_NAME%
echo Size: %sizeMB% MB
echo Location: %CD%\%INSTALLER_NAME%
echo.

REM Calculate SHA256 checksum
echo Calculating SHA256 checksum...
powershell -Command "Get-FileHash '%INSTALLER_NAME%' -Algorithm SHA256 | Select-Object -ExpandProperty Hash" > checksum.txt
set /p CHECKSUM=<checksum.txt
echo SHA256: %CHECKSUM%
echo.
echo Checksum saved to: checksum.txt
echo Add this to your release notes!
echo.

echo ==========================================
echo Next Steps:
echo ==========================================
echo 1. Test the installer on a clean Windows machine
echo 2. Verify all features work after installation  
echo 3. Add SHA256 checksum to release notes
echo 4. Upload to GitHub releases
echo 5. Celebrate! 🎉
echo ==========================================
echo.

REM Ask if user wants to test installer
set /p test="Do you want to run the installer now? (Y/N): "
if /i "%test%"=="Y" (
    echo.
    echo Launching installer...
    start "" "%INSTALLER_NAME%"
)

echo.
echo Installer build completed successfully!
pause
