"""EasyRun UI Agent — 基于 AI Agent 的 UI 自动化测试平台。

LLM 调用 DeepSeek 官方 API（deepseek-chat / deepseek-reasoner 分级路由），
其余组件全部开源、本地部署。
"""

__version__ = "0.2.0"

import os
from pathlib import Path

# 浏览器内核收进项目数据目录（data/browsers），随项目一起迁移、备份。
# 必须在任何 playwright 导入之前设置；显式设置 PLAYWRIGHT_BROWSERS_PATH 优先。
_ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(_ROOT / "data" / "browsers"))
