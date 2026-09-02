@echo off
chcp 65001 >nul
title 智财代账工作台
cd /d "%~dp0"

set PY=.venv\Scripts\python.exe
set PORT=8000

echo ==========================================
echo   智财代账工作台 启动中...
echo ==========================================

REM ---- 1. 检查 venv ----
if not exist "%PY%" (
    echo [1/4] 首次运行：正在创建虚拟环境...
    python -m venv .venv
    if errorlevel 1 (
        echo.
        echo 创建虚拟环境失败，请确认已安装 Python 3.12+
        pause
        exit /b 1
    )
) else (
    echo [1/4] 虚拟环境已就绪
)

REM ---- 2. 检查依赖 ----
"%PY%" -c "import fastapi, uvicorn, sqlalchemy, itsdangerous, yaml" >nul 2>&1
if errorlevel 1 (
    echo [2/4] 正在安装依赖（首次约 1-2 分钟）...
    "%PY%" -m pip install --quiet -r requirements.txt
    if errorlevel 1 (
        echo.
        echo 依赖安装失败，请检查网络后重试
        pause
        exit /b 1
    )
) else (
    echo [2/4] 依赖已就绪
)

REM ---- 3. 端口探测 ----
echo [3/4] 检查端口占用...
:findport
"%PY%" -c "import socket,sys; s=socket.socket(); s.settimeout(0.5); sys.exit(0 if s.connect_ex(('127.0.0.1',%PORT%))==0 else 1)" >nul 2>&1
if errorlevel 1 goto portok

REM 端口被占用：先判断是不是本系统已经在跑
"%PY%" -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:%PORT%/api/v1/meta/menu',timeout=2).status==200 else 1)" >nul 2>&1
if not errorlevel 1 (
    echo.
    echo 检测到服务已经在 %PORT% 端口运行，直接打开浏览器...
    start http://127.0.0.1:%PORT%
    echo 账号：admin  密码：admin123
    echo.
    echo （无需重复启动，本窗口 5 秒后自动关闭）
    timeout /t 5 >nul
    exit /b 0
)

echo 端口 %PORT% 被其他程序占用，尝试下一个...
set /a PORT+=1
if %PORT% gtr 8010 (
    echo.
    echo 错误：8000-8010 端口均被占用，无法启动。
    echo 请关闭占用端口的程序后重试。
    pause
    exit /b 1
)
goto findport

:portok
echo [4/4] 启动服务（http://127.0.0.1:%PORT%）...
echo.
echo   访问地址：http://127.0.0.1:%PORT%
echo   账号：admin   密码：admin123
echo   数据文件：data\zhicai.db
echo   关闭本窗口即停止服务
echo ==========================================
echo.

REM 延迟 4 秒等 uvicorn 就绪后自动开浏览器
start "" cmd /c "timeout /t 4 /nobreak >nul && start http://127.0.0.1:%PORT%"

"%PY%" -m uvicorn app.main:app --host 127.0.0.1 --port %PORT%

echo.
echo ==========================================
echo 服务已停止。如果上面出现红色报错，请截图反馈。
pause
