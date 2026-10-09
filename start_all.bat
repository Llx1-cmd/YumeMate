@echo off
chcp 65001 >nul
title YuukaChat 一键启动
cd /d %~dp0

echo ==========================================
echo          YuukaChat 一键启动
echo ==========================================
echo.

rem ---- 1/4 Ollama（聊天与日语翻译都依赖；桌面版通常已自启）----
netstat -ano | findstr ":11434" | findstr "LISTENING" >nul 2>nul
if %errorlevel%==0 (
    echo [1/4] Ollama 已在运行，跳过
) else (
    echo [1/4] 启动 Ollama...
    where ollama >nul 2>nul && start "Ollama" /min cmd /c ollama serve || echo [1/4] 未检测到 Ollama，请手动启动后再聊天
)

rem ---- 2/4 后端 8000（聊天 API + 语音端点）----
netstat -ano | findstr ":8000" | findstr "LISTENING" >nul 2>nul
if %errorlevel%==0 (
    echo [2/4] 后端 8000 已在运行，跳过
) else (
    echo [2/4] 启动后端 8000...
    start "YuukaChat-Backend-8000" cmd /k "cd /d %~dp0backend && python -m uvicorn main:app --host 127.0.0.1 --port 8000"
)

rem ---- 3/4 GPT-SoVITS 9880（日语语音；首次权重加载约 1 分钟）----
netstat -ano | findstr ":9880" | findstr "LISTENING" >nul 2>nul
if %errorlevel%==0 (
    echo [3/4] GPT-SoVITS 9880 已在运行，跳过
) else (
    echo [3/4] 启动 GPT-SoVITS 9880（权重加载较慢，语音稍等片刻可用，聊天不受影响）...
    start "GPT-SoVITS-9880" cmd /k "cd /d %~dp0GPT-SoVITS-v2pro-20250604 && runtime\python.exe api.py -a 127.0.0.1 -p 9880"
)

rem ---- 4/4 前端 8501（Streamlit）----
netstat -ano | findstr ":8501" | findstr "LISTENING" >nul 2>nul
if %errorlevel%==0 (
    echo [4/4] 前端 8501 已在运行，跳过
) else (
    echo [4/4] 启动前端 Streamlit...
    start "YuukaChat-Frontend-8501" cmd /k "cd /d %~dp0frontend && python -m streamlit run streamlit_app.py"
)

echo.
echo 启动完成！浏览器打开: http://localhost:8501
echo 停止服务 = 关闭对应的命令行窗口。
pause
