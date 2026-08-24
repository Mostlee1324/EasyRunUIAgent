"""命令行入口：easyrun serve"""

from __future__ import annotations

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(prog="easyrun", description="EasyRun UI Agent 测试平台")
    sub = parser.add_subparsers(dest="command")

    p_serve = sub.add_parser("serve", help="启动平台（API + 调度器 + Worker 池，单机形态）")
    p_serve.add_argument("--host", default=None, help="监听地址（默认取 EASYRUN_HOST）")
    p_serve.add_argument("--port", type=int, default=None, help="监听端口（默认取 EASYRUN_PORT）")

    p_worker = sub.add_parser("worker", help="独立 Worker 进程（多机部署：接 Redis 队列 + 共享数据库）")

    p_health = sub.add_parser("health", help="检查本机环境依赖")

    args = parser.parse_args()

    if args.command == "serve":
        from easyrun.main import serve

        serve()
    elif args.command == "worker":
        from easyrun.worker import worker_main

        worker_main()
    elif args.command == "health":
        from easyrun.config import get_settings

        s = get_settings()
        print("EasyRun UI Agent 环境检查")
        print(f"  LLM API Key   : {'已配置' if s.resolved_api_key else '未配置（设置 DEEPSEEK_API_KEY）'}")
        print(f"  LLM Base URL  : {s.deepseek_base_url}")
        print(f"  数据库        : {s.resolved_database_url}")
        print(f"  数据目录      : {s.data_dir}")
        print(f"  队列          : {'内存队列（单机开发，多机部署需 Redis）' if s.use_memory_queue else s.redis_url}")
        print(f"  Worker 数     : {s.workers}")
        try:
            from playwright.async_api import async_playwright  # noqa: F401

            print("  Playwright    : 已安装（浏览器: playwright install chromium）")
        except ImportError:
            print("  Playwright    : 未安装（pip install playwright && playwright install chromium）")
    else:
        parser.print_help()
