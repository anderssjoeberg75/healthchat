@echo off
echo ============================================================
echo Garmin Chat Desktop v4.0 - Setup
echo ============================================================
echo.
echo This will install all required dependencies...
echo.

REM Check if Python is available
py --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python is not installed or not in PATH
    echo Please install Python 3.12 or 3.13 from python.org
    echo.
    pause
    exit /b 1
)

echo Python found:
py --version
echo.

echo Installing dependencies...
echo.
echo This includes:
echo   - garminconnect (Garmin API)
echo   - openai (for xAI, OpenAI, Azure)
echo   - anthropic (for Claude)
echo   - google-generativeai (for Gemini)
echo.
py -m pip install --upgrade pip
py -m pip install -r requirements-desktop.txt

if %errorlevel% neq 0 (
    echo.
    echo ERROR: Failed to install dependencies
    echo.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo Setup Complete!
echo ============================================================
echo.
echo NEW in v4.0: Multi-Provider AI Support!
echo.
echo You can now choose from 5 AI providers:
echo   1. xAI (Grok) - Fast, conversational
echo   2. OpenAI (ChatGPT) - Most popular
echo   3. Azure OpenAI - Enterprise ready
echo   4. Google Gemini - Free tier available!
echo   5. Anthropic (Claude) - Long context
echo.
echo Next steps:
echo 1. Run Startup.bat to launch Garmin Chat Desktop
echo 2. Open Settings and select your AI provider
echo 3. Configure your credentials
echo.
echo You'll need (for your chosen provider):
echo   - API key from one of the providers above
echo   - Garmin Connect email
echo   - Garmin Connect password
echo.
echo API Key Links:
echo   xAI:       https://console.x.ai/
echo   OpenAI:    https://platform.openai.com/api-keys
echo   Gemini:    https://makersuite.google.com/app/apikey
echo   Anthropic: https://console.anthropic.com/
echo   Azure:     https://portal.azure.com/
echo.
echo All credentials are stored securely in the app.
echo You can save multiple provider keys and switch anytime!
echo.
pause
