#!/bin/sh
# 一键初始化：在新机器上执行即可得到可运行的平台（Linux / macOS）。
# 用法：sh scripts/bootstrap.sh
set -e

DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$DIR"

echo "==> [1/6] 检查 Python"
if ! command -v python3 >/dev/null 2>&1; then
  echo "未找到 python3，请先安装 Python 3.11+（macOS: brew install python@3.12）"; exit 1
fi
PY_MAJOR=$(python3 -c 'import sys; print(sys.version_info[1])')
if [ "$PY_MAJOR" -lt 11 ]; then
  echo "需要 Python 3.11+（当前 3.$PY_MAJOR）"; exit 1
fi

echo "==> [2/6] 创建虚拟环境并安装依赖"
if [ ! -d .venv ]; then python3 -m venv .venv; fi
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -e ".[dev]"

echo "==> [3/6] 安装 Playwright 浏览器"
# macOS 12 及更早锁定 playwright 1.50（新版 chromium 不再支持旧系统）
if [ "$(uname -s)" = "Darwin" ] && [ "$(sw_vers -productVersion | cut -d. -f1)" -le 12 ]; then
  .venv/bin/pip install -q "playwright==1.50.0"
fi
.venv/bin/playwright install chromium

echo "==> [4/6] 配置 Allure（项目内自包含，不装系统依赖）"
sh scripts/setup-allure.sh || echo "Allure 安装跳过（不影响核心功能）"

echo "==> [5/6] 生成环境配置"
if [ ! -f .env ]; then cp .env.example .env; echo "已生成 .env，请填入 DEEPSEEK_API_KEY"; fi

echo "==> [6/6] 环境检查"
.venv/bin/easyrun health
echo
echo "启动：source .venv/bin/activate && easyrun serve"
echo "演示：.venv/bin/python scripts/demo.py"
