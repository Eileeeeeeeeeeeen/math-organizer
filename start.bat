@echo off
chcp 65001 >nul
title 📐 考研数学题目整理 Agent
cd /d "%~dp0"

set "VENV_DIR=venv"
set "APP_MODULE=gui.app"
set "APP_PORT=30000"

REM ── 检查 Python ──
where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo ❌ 未找到 Python，请先安装 Python 3.10+
    pause
    exit /b 1
)

REM ── 创建/激活虚拟环境 ──
if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo 🔧 首次运行，正在创建虚拟环境...
    python -m venv "%VENV_DIR%"
    if %ERRORLEVEL% neq 0 (
        echo ❌ 虚拟环境创建失败
        pause
        exit /b 1
    )
)

echo 🔄 激活虚拟环境...
call "%VENV_DIR%\Scripts\activate.bat"

REM ── 检查依赖是否已安装 ──
python -c "import gradio" >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo 📦 安装依赖（首次运行较慢，请耐心等待）...
    pip install -r requirements.txt
    if %ERRORLEVEL% neq 0 (
        echo ❌ 依赖安装失败
        pause
        exit /b 1
    )
)

REM ── 启动应用 ──
echo.
echo ╔══════════════════════════════════════════╗
echo ║     📐 考研数学题目整理 Agent            ║
echo ╠══════════════════════════════════════════╣
echo ║  启动中，请稍候...                        ║
echo ║                                          ║
echo ║  浏览器将自动打开 http://localhost:%APP_PORT%  ║
echo ║                                          ║
echo ║  按 Ctrl+C 可停止服务                     ║
echo ╚══════════════════════════════════════════╝
echo.

REM 等待2秒后打开浏览器
timeout /t 2 /nobreak >nul
start http://localhost:%APP_PORT%

python -m "%APP_MODULE%"
if %ERRORLEVEL% neq 0 (
    echo.
    echo ⚠️ 进程已退出（代码：%ERRORLEVEL%）
    pause
)