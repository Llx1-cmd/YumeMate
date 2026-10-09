@echo off
cd /d %~dp0

echo ============================================
echo   YuukaChat v2.0 - WeChat Style
echo ============================================
echo.

echo [1/3] Checking Python...
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo ERROR: python not found
    pause
    exit /b 1
)

python -m pip install streamlit requests pydantic-settings fastapi uvicorn websockets aiohttp -q

echo.
echo [2/3] Starting backend service...
start "YuukaChat-Backend" cmd /k "cd backend && python -m uvicorn main:app --host 127.0.0.1 --port 8000"
echo Waiting for backend to start...
timeout /t 3 /nobreak >nul

echo.
echo [3/3] Starting YuukaChat frontend...
echo.
echo Open: http://localhost:8501
echo Press Ctrl+C to stop
echo ============================================

set STREAMLIT_SERVER_HEADLESS=true
set STREAMLIT_BROWSER_GATHER_USAGE_STATS=false
set HOME=%~dp0

python -m streamlit run frontend\streamlit_app.py --server.port 8501 --server.headless true --browser.gatherUsageStats false
pause
