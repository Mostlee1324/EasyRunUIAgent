# 一键初始化（Windows PowerShell 版）：venv / 依赖 / 浏览器 / Allure / .env / 环境检查
# 用法：powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "==> [1/5] 检查 Python"
python --version
if ($LASTEXITCODE -ne 0) { Write-Host "未找到 python，请先安装 Python 3.11+ 并加入 PATH"; exit 1 }

Write-Host "==> [2/5] 创建虚拟环境并安装依赖"
if (-not (Test-Path ".venv")) { python -m venv .venv }
& ".venv\Scripts\python" -m pip install --upgrade pip
& ".venv\Scripts\pip" install -e ".[dev]"

Write-Host "==> [3/5] 安装 Playwright 浏览器"
& ".venv\Scripts\playwright" install chromium

Write-Host "==> [4/5] 配置 Allure（项目内自包含，不装系统依赖）"
powershell -ExecutionPolicy Bypass -File "scripts\setup-allure.ps1"

Write-Host "==> [5/5] 生成环境配置"
if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env"; Write-Host "已生成 .env，请填入 DEEPSEEK_API_KEY" }

Write-Host ""
Write-Host "环境检查："
& ".venv\Scripts\easyrun" health
Write-Host ""
Write-Host "启动：.venv\Scripts\easyrun serve"
Write-Host "演示：.venv\Scripts\python scripts\demo.py"
