@echo off
chcp 65001 >nul
title Web搜索与阅读 MCP - 安装与自测
cd /d "%~dp0"

echo [1/3] 创建虚拟环境 .venv ...
python -m venv .venv || goto :err

echo [2/3] 安装依赖（mcp v1 / requests / trafilatura）...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt || goto :err

echo [3/3] 运行自测（无需 MCP 客户端）...
".venv\Scripts\python.exe" test_self.py || goto :err

echo.
echo 完成。接入 DeepSeek Harness 见 README.md「接入」一节。
pause
exit /b 0

:err
echo.
echo 安装/自测失败，请查看上方报错。
pause
exit /b 1
