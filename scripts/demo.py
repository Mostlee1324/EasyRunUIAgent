#!/usr/bin/env python3
"""端到端演示：创建「商城下单」用例 → 提交执行 → 等待 Agent 跑完 → 打印报告。

前置：平台已启动（easyrun serve）、已配置 DEEPSEEK_API_KEY、
已安装浏览器（playwright install chromium）。
用法：python scripts/demo.py [--base http://127.0.0.1:8001]
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone

import httpx


def localtime(iso: str) -> str:
    """ISO 时间 → 本地时区 HH:MM:SS（后端统一存 UTC，展示层转本地）。"""
    dt = datetime.fromisoformat(iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone().strftime("%H:%M:%S")

DEMO_CASE = {
    "name": "演示：商城下单流程",
    "description": "登录演示商城，加入购物车并结算，确认订单编号出现",
    "steps": [
        "输入用户名 demo、密码 123456，点击「登 录」按钮",
        "点击「测试商品 A」的「加入购物车」按钮",
        "点击「去结算」按钮，进入结算页",
        "确认页面出现「订单编号」",
    ],
    "assertions": [
        {"type": "url_contains", "target": "checkout"},
        {"type": "text_contains", "target": "订单编号"},
    ],
}

STATUS_ZH = {
    "passed": "✅ 通过", "failed": "❌ 失败", "quarantined": "⚠️ 隔离",
    "skipped": "➖ 跳过", "running": "执行中", "queued": "排队中", "retrying": "重试中",
}

FAULT_ZH = {
    "product_bug": "产品缺陷", "env_issue": "环境问题", "case_issue": "用例设计问题",
    "locator_drift": "locator 漂移", "agent_error": "Agent 误判",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8001")
    parser.add_argument("--target", default="http://127.0.0.1:8001/demo/")
    args = parser.parse_args()
    base = args.base.rstrip("/")
    client = httpx.Client(timeout=30)

    # 1. 健康检查
    try:
        health = client.get(f"{base}/api/health").json()
    except httpx.HTTPError:
        print("无法连接平台，请先启动: easyrun serve")
        sys.exit(1)
    if not health.get("llm_configured"):
        print("警告：未配置 DEEPSEEK_API_KEY，Agent 将无法决策（仅报告层可用）")

    # 2. 创建演示用例（幂等：复用同名用例，但每次重置为探索模式，保证走完整 LLM 链路）
    cases = client.get(f"{base}/api/cases").json()
    case = next((c for c in cases if c["name"] == DEMO_CASE["name"]), None)
    if case is None:
        case = client.post(f"{base}/api/cases", json=DEMO_CASE).json()
        print(f"已创建用例: {case['name']} ({case['id'][:8]})")
    else:
        case = client.put(
            f"{base}/api/cases/{case['id']}",
            json={**DEMO_CASE, "mode": "agentic"},
        ).json()
        print(f"复用并重置用例: {case['name']} ({case['id'][:8]})，模式: {case['mode']}")

    # 3. 提交执行
    run = client.post(
        f"{base}/api/runs",
        json={"case_id": case["id"], "target_url": args.target, "env": "demo"},
    ).json()
    run_id = run["id"]
    print(f"已提交执行: {run_id}  目标: {args.target}\n")

    # 4. 轮询等待
    last_done = 0
    for _ in range(300):  # 最多 10 分钟
        detail = client.get(f"{base}/api/runs/{run_id}").json()
        run, tasks = detail["run"], detail["tasks"]
        done = sum(1 for t in tasks if t["status"] in ("passed", "failed", "quarantined", "skipped"))
        if done != last_done:
            last_done = done
            for t in tasks:
                print(f"  [{STATUS_ZH.get(t['status'], t['status'])}] {t['case_name']}")
        if run["status"] in ("passed", "failed", "partial"):
            break
        time.sleep(2)

    # 5. 打印完整报告
    report = client.get(f"{base}/api/runs/{run_id}/report").json()
    print()
    print("=" * 68)
    print(f"执行报告  run={run_id[:12]}  status={run['status']}  stats={run['stats']}")
    print("=" * 68)
    for tr in report["tasks"]:
        task = tr["task"]
        print(f"\n▸ {task['case_name']}  [{STATUS_ZH.get(task['status'], task['status'])}]  尝试 {task['attempt']} 次")
        for ev in tr["events"]:
            p = ev["payload"]
            ts = localtime(ev["created_at"])
            if ev["type"] == "llm_decision":
                print(f"  {ts} 💭 决策 → {p.get('tool')}  理由: {p.get('reason', '')[:60]}")
            elif ev["type"] == "tool_call":
                if p.get("skipped"):
                    print(f"  {ts} ⏭ {p.get('tool')} 已跳过（{p.get('reason', '')[:40]}）")
                else:
                    mark = "✓" if p.get("ok") else f"✗ {p.get('error', '')[:60]}"
                    print(f"  {ts} ⚙ {p.get('tool')} {str(p.get('args', ''))[:60]} {mark}")
            elif ev["type"] == "assertion":
                mark = "✓" if p.get("ok") else "✗"
                print(f"  {ts} {mark} 断言 {p.get('type')}:{p.get('target')} — {p.get('detail', '')[:70]}")
            elif ev["type"] == "heal_result":
                print(f"  {ts} ♻ 自愈: {'成功' if p.get('ok') else '未成功'}")
            elif ev["type"] == "case_passed":
                u = p.get("usage", {})
                print(f"  {ts} ✅ 用例通过 — 动作 {u.get('steps')} 步 · LLM {u.get('llm_calls')} 次 · tokens {u.get('prompt_tokens', 0) + u.get('completion_tokens', 0)}")
            elif ev["type"] == "case_failed":
                print(f"  {ts} ❌ 用例失败: {p.get('error', '')[:100]}")
        if task["error"]:
            print(f"  错误信息: {task['error'][:200]}")
        if tr["analysis"]:
            a = tr["analysis"]
            print(f"  🔍 AI 归因: {FAULT_ZH.get(a['category'], a['category'])}（置信度 {a['confidence']:.0%}）")
            print(f"     根因: {a['root_cause'][:120]}")
            if a["defect_draft"].get("title"):
                print(f"     缺陷草稿: {a['defect_draft']['title']}")

    allure = client.post(f"{base}/api/runs/{run_id}/allure").json()
    print(f"\nAllure 结果: {allure['dir']}")
    if allure.get("html_url"):
        print(f"Allure 报告: {base}{allure['html_url']}")
    print(f"Web 报告: {base}/app/#/run/{run_id}")

    if run["status"] == "passed":
        print("\n演示成功 🎉")
        sys.exit(0)
    else:
        print("\n演示未完全通过，请查看上方报告定位原因")
        sys.exit(1)


if __name__ == "__main__":
    main()
