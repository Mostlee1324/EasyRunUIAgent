"""测试 Agent 执行引擎（设计文档 §04）。

观察 → 决策 → 行动 → 校验 循环；JSON 动作协议；确定性断言；
断言失败触发 LLM 自愈；探索通过的路径自动记录为固化动作（deterministic 回放）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable

from easyrun.assertions import AssertionResult, normalize_assertions, run_assertion
from easyrun.browser import BrowserError, BrowserSession, format_snapshot
from easyrun.config import Settings
from easyrun.events import (
    EV_ASSERTION,
    EV_CASE_FAILED,
    EV_CASE_PASSED,
    EV_GOAL_REACHED,
    EV_HEAL_REQUEST,
    EV_HEAL_RESULT,
    EV_LLM_DECISION,
    EV_SCREENSHOT,
    EV_SESSION_START,
    EV_TOOL_CALL,
    EventEmitter,
)
from easyrun.models import (
    CASE_MODE_AGENTIC,
    CASE_MODE_DETERMINISTIC,
    StepEvent,
)

logger = logging.getLogger("easyrun.agent")

# 固化回放时不记录的工具（瞬态 / 非业务操作）
# 注意：browser_wait 必须记录——页面动态渲染（如点日期后出现链接）依赖等待时机，
# 回放丢失 wait 会导致点击过早而失败
_NON_RECORDED = {"finish", "fail", "browser_screenshot"}

# 观察类工具：本身不改变页面，不参与「无变化重复」判定（否则等待/读取会被误杀）
_NOCHANGE_EXEMPT = {"browser_wait", "browser_get_text", "browser_screenshot"}

TOOL_SPECS: dict[str, str] = {
    "browser_navigate": "打开指定 URL。参数: {url}",
    "browser_click": "点击快照中索引对应的元素。参数: {index}",
    "browser_type": "向输入框输入文本。参数: {index, text}",
    "browser_wait": "等待指定毫秒数。参数: {ms}",
    "browser_go_back": "返回上一页",
    "browser_click_link": "按名称点击 class=sub-links 分组内的链接（如 利好新闻/利空新闻/中性新闻）。参数: {name}",
    "browser_get_text": "读取索引元素的文本。参数: {index}",
    "case_step_done": "标记用例第 step 步已完成，平台立即执行该步骤绑定的确定性断言（无需自行判断页面状态）。参数: {step}（步骤序号，从 1 开始）",
    "finish": "用例步骤全部完成，页面状态符合预期。参数: {summary}",
    "fail": "无法继续执行。参数: {reason}",
}

SYSTEM_PROMPT = f"""你是 UI 自动化测试 Agent，通过浏览器执行用户用例。每一步只输出一个 JSON 对象动作，格式：
{{"tool": "<工具名>", "args": {{...}}, "reason": "<一句话理由>"}}
除 JSON 外不要输出任何内容。

规则：
1. 基于最新的【页面快照】选择操作。快照行格式为 [索引|标签|文本|类型|href|可见性]，索引只对当次快照有效。
2. 页面操作优先使用快照索引；索引失效（页面变化）时重新观察，不要猜测。
3. 若页面上存在 class=sub-links 的分组链接（如 利好新闻/利空新闻/中性新闻），点击它们时优先用 browser_click_link 按名称点击，不要用索引猜测。
3. 用例步骤全部完成且页面符合预期后调用 finish；确实无法继续（页面错误、找不到入口）时调用 fail 并说明原因，不要编造操作。
4. 页面加载慢时用 browser_wait 等待；输入框先点击再输入（如需）。
5. 每完成一个用例步骤后调用 case_step_done 标记该步骤完成（参数 step=步骤序号，从 1 开始），平台会立即执行该步骤绑定的断言；全部步骤完成后调用 finish。

可用工具：
{chr(10).join(f"- {k}: {v}" for k, v in TOOL_SPECS.items())}"""


class CaseFailed(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass
class AgentOutcome:
    status: str = "passed"              # passed / failed
    error: str = ""
    actions: list[dict] = field(default_factory=list)      # 固化用动作记录
    healed_locators: list[dict] = field(default_factory=list)
    usage: dict = field(default_factory=lambda: {
        "prompt_tokens": 0, "completion_tokens": 0, "llm_calls": 0, "steps": 0, "heals": 0,
    })

    def add_usage(self, prompt: int, completion: int) -> None:
        self.usage["prompt_tokens"] += prompt
        self.usage["completion_tokens"] += completion
        self.usage["llm_calls"] += 1


class AgentRunner:
    """执行单个用例任务。

    browser_factory 可注入（测试用 Fake），默认创建真实 BrowserSession。
    """

    def __init__(
        self,
        settings: Settings,
        llm,
        browser_factory: Callable[[], Awaitable[BrowserSession]] | None = None,
    ) -> None:
        self._settings = settings
        self._llm = llm
        self._browser_factory = browser_factory or self._default_browser

    async def _default_browser(self) -> BrowserSession:
        return await BrowserSession(self._settings).start()

    # ------------------------------------------------------------------

    async def run(
        self,
        *,
        task_id: str,
        case,
        target_url: str,
        emitter: EventEmitter,
        session_id: str,
        artifact_root: Path,
        should_stop: Callable[[], Awaitable[bool]] | None = None,
        previous_error: str = "",
    ) -> AgentOutcome:
        """should_stop：每步执行前检查，返回 True 时以「任务已取消」终止。

        previous_error：重试场景传入上一次失败原因，注入用例说明帮助 LLM 换策略。
        """
        browser = self._browser_factory()
        if asyncio.iscoroutine(browser):
            browser = await browser
        # 已标记完成的步骤号（case_step_done）：收尾兜底补跑未标记步骤的绑定断言
        self._done_steps: set[int] = set()
        try:
            await browser.new_page()
            await emitter.emit(
                EV_SESSION_START,
                {"task_id": task_id, "case_name": case.name, "mode": case.mode, "target_url": target_url},
            )
            completion_checks = normalize_assertions(case.completion_checks or [])
            if case.mode == CASE_MODE_DETERMINISTIC:
                return await self._run_deterministic(
                    browser, case, target_url, emitter, artifact_root, session_id, should_stop,
                    completion_checks=completion_checks,
                )
            return await self._run_agentic(
                browser, case, target_url, emitter, artifact_root, session_id, should_stop,
                previous_error=previous_error, completion_checks=completion_checks,
            )
        finally:
            try:
                await browser.close()
            except Exception:  # pragma: no cover
                logger.warning("关闭浏览器失败", exc_info=True)

    # ---- 探索模式 ----

    async def _run_agentic(
        self, browser, case, target_url, emitter, artifact_root, session_id, should_stop,
        previous_error: str = "", completion_checks: list[dict] | None = None,
    ) -> AgentOutcome:
        outcome = AgentOutcome()
        brief = self._build_brief(case, target_url, previous_error, completion_checks)
        messages: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": brief},
        ]
        # ---- 断言拆分：绑定步骤的（标记点执行）与无绑定的（收尾执行）----
        assertions = normalize_assertions(case.assertions or [])
        step_assertions: dict[int, list[dict]] = {}
        final_assertions: list[dict] = []
        for a in assertions:
            n = a.get("after_step")
            if n is not None:
                step_assertions.setdefault(n, []).append(a)
            else:
                final_assertions.append(a)
        try:
            await self._action_loop(
                browser, messages, outcome, emitter, artifact_root, session_id,
                goal="执行用例步骤，完成后调用 finish", should_stop=should_stop,
                completion_checks=completion_checks, step_assertions=step_assertions,
            )
        except CaseFailed as e:
            outcome.status = "failed"
            outcome.error = e.reason
        if outcome.status == "failed":
            await emitter.emit(EV_CASE_FAILED, {"error": outcome.error, "usage": outcome.usage})
            return outcome

        # ---- 收尾断言：兜底补跑未标记步骤的绑定断言（按步骤序）+ 无绑定断言 ----
        pending = [n for n in sorted(step_assertions) if n not in self._done_steps]
        wrapup = [a for n in pending for a in step_assertions[n]] + final_assertions
        failures = await self._assert_phase(browser, wrapup, emitter, outcome)
        if failures:
            healed = await self._heal(
                browser, wrapup, failures, emitter, outcome, artifact_root, session_id, should_stop,
                step_assertions=step_assertions,
            )
            if healed:
                outcome.usage["heals"] += 1
                outcome.healed_locators = self._locators_from_failures(
                    await browser.url(), failures
                )
            else:
                outcome.status = "failed"
                outcome.error = "断言失败: " + "；".join(f.detail for f in failures)

        if outcome.status == "passed":
            await emitter.emit(EV_CASE_PASSED, {"assertions": len(assertions), "usage": outcome.usage})
        else:
            await emitter.emit(EV_CASE_FAILED, {"error": outcome.error, "usage": outcome.usage})
        return outcome

    async def _action_loop(
        self,
        browser,
        messages: list[dict],
        outcome: AgentOutcome,
        emitter: EventEmitter,
        artifact_root: Path,
        session_id: str,
        *,
        goal: str,
        max_steps: int | None = None,
        record: bool = True,
        should_stop: Callable[[], Awaitable[bool]] | None = None,
        completion_checks: list[dict] | None = None,
        step_assertions: dict[int, list[dict]] | None = None,
    ) -> None:
        """通用动作循环：LLM 决策 → 执行 → 反馈。finish 正常返回，fail 抛 CaseFailed。

        record=False 时动作不进入固化记录（自愈路径不入固化）。
        completion_checks：每次决策前检查，全部满足 → 立即停止操作（目标已达成）。
        """
        max_steps = max_steps or self._settings.max_steps_per_case
        repeat_counts: dict[tuple, int] = {}  # (tool,args) 已执行次数
        skip_counts: dict[tuple, int] = {}    # (tool,args) 被重复请求后跳过的次数
        for step in range(max_steps):
            if should_stop is not None and await should_stop():
                raise CaseFailed("任务已取消")
            snap_before = await browser.snapshot()
            # 完成条件前置检查：条件已满足就不再做任何动作（含点击链接）
            if completion_checks and await self._goal_reached(browser, completion_checks, emitter, outcome):
                return
            messages.append({"role": "user", "content": f"【页面快照】\n{format_snapshot(snap_before)}"})
            obj, result = await self._llm.chat_json(messages)
            outcome.add_usage(result.usage.prompt_tokens, result.usage.completion_tokens)
            tool = obj.get("tool", "")
            args = obj.get("args") or {}
            if not isinstance(args, dict):
                args = {"value": args}
            reason = str(obj.get("reason", ""))[:300]
            await emitter.emit(
                EV_LLM_DECISION,
                {"step": step, "goal": goal, "tool": tool, "args": args, "reason": reason,
                 "prompt_tokens": result.usage.prompt_tokens,
                 "completion_tokens": result.usage.completion_tokens},
            )
            messages.append(
                {"role": "assistant", "content": json.dumps(obj, ensure_ascii=False)}
            )
            if tool not in TOOL_SPECS:
                messages.append(
                    {"role": "user",
                     "content": f"未知工具「{tool}」。可用工具: {', '.join(TOOL_SPECS)}，请重新输出一个动作。"}
                )
                self._trim(messages)
                continue
            if tool == "finish":
                return
            if tool == "fail":
                raise CaseFailed(str(args.get("reason") or "Agent 判定无法继续"))
            # 步骤完成标记：立即执行该步骤绑定的断言（确定性校验，0 token）。
            # 不是页面动作：不走 _execute、不参与重复动作护栏、不占 usage.steps。
            if tool == "case_step_done":
                try:
                    n = int(args.get("step", 0))
                except (TypeError, ValueError):
                    raise CaseFailed("case_step_done 参数错误：step 必须为 1 起的整数")
                if n < 1:
                    raise CaseFailed("case_step_done 参数错误：step 必须为 1 起的整数")
                if n in self._done_steps:
                    # 幂等：重复标记不重跑断言、不入固化
                    await emitter.emit(EV_TOOL_CALL, {
                        "step": step, "tool": tool, "args": args, "ok": True, "skipped": True,
                        "reason": f"步骤 {n} 已标记过",
                    })
                    messages.append({"role": "user", "content": f"步骤 {n} 此前已标记完成，本次请求已跳过。"})
                    self._trim(messages)
                    continue
                self._done_steps.add(n)
                await emitter.emit(EV_TOOL_CALL, {
                    "step": step, "tool": tool, "args": args, "ok": True, "marked": True,
                })
                if record:
                    outcome.actions.append({"tool": "case_step_done", "args": {"step": n}})
                bound = (step_assertions or {}).get(n, [])
                step_failures = await self._assert_phase(browser, bound, emitter, outcome)
                if step_failures:
                    detail = "；".join(f.detail for f in step_failures)
                    if self._settings.heal_attempts > 0:
                        healed = await self._heal(
                            browser, bound, step_failures, emitter, outcome,
                            artifact_root, session_id, should_stop,
                            step_assertions=step_assertions,
                        )
                        if healed:
                            outcome.usage["heals"] += 1
                            outcome.healed_locators = self._locators_from_failures(
                                await browser.url(), step_failures
                            )
                        else:
                            raise CaseFailed(f"步骤 {n} 断言失败：{detail}")
                    else:
                        raise CaseFailed(f"步骤 {n} 断言失败：{detail}")
                else:
                    messages.append({"role": "user", "content": f"步骤 {n} 已标记完成，绑定断言全部通过。"})
                    self._trim(messages)
                continue
            # 单次执行策略：同一动作在整个用例中只允许执行一次。
            # 已执行过的动作被再次请求 → 【跳过而不失败】，提示 LLM 执行下一步；
            # 反复请求超过上限（max_skipped_repeats）→ 终止防空转。
            key = (tool, json.dumps(args, sort_keys=True))
            if tool not in _NOCHANGE_EXEMPT:
                executed = repeat_counts.get(key, 0)
                if executed >= self._settings.max_noop_repeats:
                    skipped = skip_counts.get(key, 0) + 1
                    skip_counts[key] = skipped
                    if skipped > self._settings.max_skipped_repeats:
                        raise CaseFailed(
                            f"动作 {tool} 被反复请求 {executed + skipped} 次（已跳过 {skipped} 次），已终止。"
                            "请检查用例步骤或页面结构"
                        )
                    await emitter.emit(EV_TOOL_CALL, {
                        "step": step, "tool": tool, "args": args,
                        "ok": True, "skipped": True,
                        "reason": f"该动作已执行过（第 {skipped} 次跳过）",
                    })
                    messages.append(
                        {"role": "user",
                         "content": f"动作 {tool} 此前已执行过一次，本次请求已跳过（第 {skipped} 次跳过）。"
                                    "不要再请求该动作：继续执行用例的下一步骤；若目标已达成请调用 finish。"}
                    )
                    self._trim(messages)
                    continue
                repeat_counts[key] = executed + 1

            res = await self._execute(browser, tool, args)
            outcome.usage["steps"] += 1
            await emitter.emit(
                EV_TOOL_CALL, {"step": step, "tool": tool, "args": args, **res}
            )
            if not res.get("ok"):
                # 失败即终止：不重试、不换方式，交给用户从报告页手动 rerun
                raise CaseFailed(f"动作 {tool} 执行失败：{res.get('error', '')}")
            # 前后快照对比：仅供 LLM 的提示信息，不参与终止判定
            snap_after = await browser.snapshot()
            changed = self._page_changed(snap_before, snap_after)
            note = (
                "执行成功。"
                if tool in _NOCHANGE_EXEMPT
                else ("页面内容已更新。" if changed else "⚠️ 页面文本没有变化——该操作可能只是滚动或无效，请勿重复同一动作。")
            )
            messages.append(
                {"role": "user",
                 "content": f"动作 {tool} 执行成功：{json.dumps(res, ensure_ascii=False)}。{note}"}
            )
            if record and tool not in _NON_RECORDED:
                outcome.actions.append({"tool": tool, "args": args})
            if self._settings.screenshot_every_step:
                artifact = await self._save_screenshot(
                    browser, artifact_root, session_id, step, emitter
                )
                if artifact:
                    await emitter.emit(EV_SCREENSHOT, {"step": step, "path": artifact}, artifact)
            self._trim(messages)
        raise CaseFailed(f"超过最大步数 {max_steps}，Agent 未调用 finish")

    # ---- 断言与自愈 ----

    async def _assert_phase(
        self, browser, assertions, emitter, outcome
    ) -> list[AssertionResult]:
        failures: list[AssertionResult] = []
        baseline_dir = self._settings.resolved_artifact_dir / "baselines"
        for a in assertions:
            try:
                r = await run_assertion(browser, a, baseline_dir=baseline_dir)
            except Exception as e:  # 断言执行异常按失败处理
                r = AssertionResult(type=a["type"], target=a["target"], expected=a["expected"],
                                    ok=False, detail=f"断言执行异常: {e}")
            outcome.usage["steps"] += 1
            await emitter.emit(EV_ASSERTION, {
                "type": r.type, "target": r.target, "expected": r.expected,
                "ok": r.ok, "actual": r.actual, "detail": r.detail,
                "step": a.get("after_step"),  # 步骤后断言带步骤号；无绑定为 None
            })
            if not r.ok:
                failures.append(r)
        return failures

    async def _heal(
        self, browser, assertions, failures, emitter, outcome, artifact_root, session_id,
        should_stop=None, step_assertions: dict[int, list[dict]] | None = None,
    ) -> bool:
        for attempt in range(1, self._settings.heal_attempts + 1):
            await emitter.emit(EV_HEAL_REQUEST, {
                "attempt": attempt,
                "failures": [{"type": f.type, "detail": f.detail} for f in failures],
            })
            messages: list[dict] = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": (
                    "当前处于【自愈模式】：用例断言失败，请分析失败原因并修正页面状态。\n"
                    f"失败断言：{json.dumps([{'type': f.type, 'target': f.target, 'detail': f.detail} for f in failures], ensure_ascii=False)}\n"
                    "修正完成后调用 finish。若页面本身存在问题无法修正，调用 fail 说明原因。"
                )},
            ]
            ok = True
            try:
                await self._action_loop(
                    browser, messages, outcome, emitter, artifact_root, session_id,
                    goal="自愈：修正断言失败", max_steps=6, record=False,
                    should_stop=should_stop, step_assertions=step_assertions,
                )
            except CaseFailed as e:
                ok = False
            if ok:
                remaining = await self._assert_phase(browser, assertions, emitter, outcome)
                if not remaining:
                    await emitter.emit(EV_HEAL_RESULT, {"attempt": attempt, "ok": True})
                    return True
            await emitter.emit(EV_HEAL_RESULT, {"attempt": attempt, "ok": False})
        return False

    @staticmethod
    def _locators_from_failures(url: str, failures: list[AssertionResult]) -> list[dict]:
        out = []
        for f in failures:
            if f.type in ("text_contains", "element_text") and f.target:
                out.append({
                    "page": url.split("?")[0],
                    "element_key": f.target,
                    "strategy": "text",
                    "value": f.target,
                })
        return out

    # ---- 固化模式（确定性回放，不调用 LLM）----

    async def _run_deterministic(
        self, browser, case, target_url, emitter, artifact_root, session_id, should_stop,
        completion_checks: list[dict] | None = None,
    ) -> AgentOutcome:
        outcome = AgentOutcome()
        actions: list[dict] = list(case.steps or [])
        # 动作列表不以导航开头时（如探索阶段已在目标页开始记录），回放需先导航
        if target_url and (not actions or actions[0].get("tool") != "browser_navigate"):
            actions.insert(0, {"tool": "browser_navigate", "args": {"url": target_url}})
        # ---- 断言拆分（与探索模式同一语义）：绑定步骤的标记点执行，无绑定的收尾执行 ----
        assertions = normalize_assertions(case.assertions or [])
        step_assertions: dict[int, list[dict]] = {}
        final_assertions: list[dict] = []
        for a in assertions:
            n = a.get("after_step")
            if n is not None:
                step_assertions.setdefault(n, []).append(a)
            else:
                final_assertions.append(a)
        done_steps: set[int] = set()
        try:
            for i, action in enumerate(actions):
                if should_stop is not None and await should_stop():
                    raise CaseFailed("任务已取消")
                # 完成条件前置检查：已满足则跳过剩余动作
                if completion_checks and await self._goal_reached(browser, completion_checks, emitter, outcome):
                    break
                tool, args = action.get("tool"), dict(action.get("args") or {})
                if tool not in TOOL_SPECS or tool in ("finish", "fail"):
                    continue
                # 步骤完成标记（固化自探索模式）：在标记点执行绑定断言
                if tool == "case_step_done":
                    try:
                        n = int(args.get("step", 0))
                    except (TypeError, ValueError):
                        raise CaseFailed(
                            f"固化动作第 {i + 1} 步 case_step_done 参数错误：step 必须为 1 起的整数"
                        )
                    if n < 1:
                        raise CaseFailed(
                            f"固化动作第 {i + 1} 步 case_step_done 参数错误：step 必须为 1 起的整数"
                        )
                    if n not in done_steps:
                        done_steps.add(n)
                        await emitter.emit(EV_TOOL_CALL, {
                            "step": i, "tool": tool, "args": args, "ok": True, "marked": True,
                        })
                        step_failures = await self._assert_phase(
                            browser, step_assertions.get(n, []), emitter, outcome
                        )
                        if step_failures:
                            detail = "；".join(f.detail for f in step_failures)
                            raise CaseFailed(f"固化动作第 {i + 1} 步（步骤 {n}）断言失败：{detail}")
                    else:
                        await emitter.emit(EV_TOOL_CALL, {
                            "step": i, "tool": tool, "args": args, "ok": True, "skipped": True,
                            "reason": f"步骤 {n} 已标记过",
                        })
                    continue  # 标记不是页面动作：不计数、不吃回放延迟、不截图
                # 回放时用本次执行的目标地址替换首次导航
                if tool == "browser_navigate" and i == 0 and target_url:
                    args = {**args, "url": target_url}
                res = await self._execute(browser, tool, args)
                outcome.usage["steps"] += 1
                await emitter.emit(EV_TOOL_CALL, {"step": i, "tool": tool, "args": args, **res})
                if not res.get("ok"):
                    raise CaseFailed(
                        f"固化动作第 {i + 1} 步 {tool} 执行失败：{res.get('error', '')}，建议回到探索模式重新固化"
                    )
                # 回放节奏：探索模式下 LLM 决策天然有 3~8 秒间隔（等待动态渲染与滚动动画）；
                # 回放在【截图之前】等待，保证步骤截图拍到的是动作完成后的稳定页面
                if tool != "browser_wait" and self._settings.replay_step_delay_ms:
                    await asyncio.sleep(self._settings.replay_step_delay_ms / 1000)
                if self._settings.screenshot_every_step:
                    artifact = await self._save_screenshot(
                        browser, artifact_root, session_id, i, emitter
                    )
                    if artifact:
                        await emitter.emit(EV_SCREENSHOT, {"step": i, "path": artifact}, artifact)
        except CaseFailed as e:
            outcome.status = "failed"
            outcome.error = e.reason
            await emitter.emit(EV_CASE_FAILED, {"error": outcome.error, "usage": outcome.usage})
            return outcome

        # 沉降等待：站点滚动动画等异步效果需要时间完成。
        # 探索模式有 LLM 决策延迟天然兜底；回放必须显式等待，否则断言在动画中途执行。
        if self._settings.replay_step_delay_ms:
            await asyncio.sleep(self._settings.replay_step_delay_ms / 1000)
        # 收尾断言：兜底补跑未标记步骤的绑定断言（按步骤序）+ 无绑定断言
        pending = [n for n in sorted(step_assertions) if n not in done_steps]
        wrapup = [a for n in pending for a in step_assertions[n]] + final_assertions
        failures = await self._assert_phase(browser, wrapup, emitter, outcome)
        if failures:
            outcome.status = "failed"
            outcome.error = "断言失败: " + "；".join(f.detail for f in failures)
            await emitter.emit(EV_CASE_FAILED, {"error": outcome.error, "usage": outcome.usage})
            return outcome
        await emitter.emit(EV_CASE_PASSED, {"assertions": len(assertions), "usage": outcome.usage})
        return outcome

    # ---- 工具执行与辅助 ----

    async def _execute(self, browser: BrowserSession, tool: str, args: dict) -> dict:
        try:
            if tool == "browser_navigate":
                return await browser.navigate(str(args.get("url", "")))
            if tool == "browser_click":
                return await browser.click(int(args.get("index", -1)))
            if tool == "browser_type":
                return await browser.type_text(int(args.get("index", -1)), str(args.get("text", "")))
            if tool == "browser_wait":
                return await browser.wait(int(args.get("ms", 1000)))
            if tool == "browser_go_back":
                return await browser.go_back()
            if tool == "browser_click_link":
                return await browser.click_link(str(args.get("name", "")))
            if tool == "browser_get_text":
                return await browser.get_text(int(args.get("index", -1)))
            return {"ok": False, "error": f"未知工具 {tool}"}
        except (BrowserError, ValueError, KeyError, TypeError) as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:  # 页面 JS 异常等兜底
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    async def _save_screenshot(
        self, browser, artifact_root: Path, session_id: str, step: int, emitter
    ) -> str:
        try:
            # 固定沉降：平滑滚动等动画约 1 秒，截图前等待让画面稳定
            await asyncio.sleep(0.5)
            rel = f"sessions/{session_id}/s_{step:04d}.png"
            await browser.screenshot(artifact_root / rel)
            return rel
        except Exception:  # 截图失败不影响执行
            logger.warning("截图失败 step=%s", step, exc_info=True)
            return ""

    async def _goal_reached(
        self, browser, checks: list[dict], emitter: EventEmitter, outcome: AgentOutcome
    ) -> bool:
        """完成条件全部满足 → 记录事件并返回 True（调用方停止操作）。

        min_steps：条件仅在已执行动作数达到阈值后才参与判定——
        用于「目标状态与初始状态相同」的场景（如 #8 利好新闻标签加载即可见，
        但用例要求先点日期再点按钮）。
        """
        results = []
        baseline_dir = self._settings.resolved_artifact_dir / "baselines"
        executed = outcome.usage.get("steps", 0)
        for a in checks:
            min_steps = a.get("min_steps") or 0
            if executed < min_steps:
                # 尚未达到执行门槛：该条件视为未满足
                results.append(AssertionResult(
                    type=a["type"], target=a["target"], expected=a["expected"],
                    ok=False, detail=f"待执行 {min_steps - executed} 个动作后生效",
                ))
                continue
            try:
                r = await run_assertion(browser, a, baseline_dir=baseline_dir)
            except Exception as e:
                r = AssertionResult(type=a["type"], target=a["target"], expected=a["expected"],
                                    ok=False, detail=f"完成条件执行异常: {e}")
            results.append(r)
        if results and all(r.ok for r in results):
            outcome.usage["steps"] += len(results)
            await emitter.emit(EV_GOAL_REACHED, {
                "checks": [{"type": r.type, "target": r.target, "detail": r.detail} for r in results],
            })
            return True
        return False

    @staticmethod
    def _page_changed(before: dict, after: dict) -> bool:
        """页面内容是否变化：仅比较前 80 个元素的文本指纹（数字归一化）。

        刻意不判断：URL（点击可能只是滚动，URL 不变）、inView（点击自带
        scrollIntoView 会改可见性）。该结果只用于给 LLM 的提示信息，
        不参与任何终止判定——单次执行护栏只数「同一动作执行了几次」。
        """

        def sig(s: dict):
            out = []
            for e in (s.get("els") or [])[:80]:
                text = re.sub(r"\d+", "#", e.get("text", "") or "")
                out.append((e.get("i"), text[:80]))
            return out

        return sig(before) != sig(after)

    @staticmethod
    def _build_brief(case, target_url: str, previous_error: str = "", completion_checks: list[dict] | None = None) -> str:
        lines = [f"目标站点：{target_url}".strip()]
        if previous_error:
            lines.append(
                f"⚠️ 该用例上一次执行失败，原因：{previous_error[:500]}。"
                "本次请分析失败原因，避免重复同样的无效操作。"
            )
        lines.append("用例步骤：")
        steps = case.steps or case.description.splitlines() or ["（无步骤描述，自行探索页面）"]
        bound_steps: set[int] = set()
        for a in case.assertions or []:
            as_ = a.get("after_step")
            if as_ is not None:
                try:
                    bound_steps.add(int(as_))
                except (TypeError, ValueError):
                    pass
        for i, s in enumerate(steps, 1):
            line = f"{i}. {s}"
            if i in bound_steps:
                line += f"（完成本步骤后调用 case_step_done(step={i}) 触发绑定断言）"
            lines.append(line)
        if completion_checks:
            lines.append("完成条件（全部满足即目标已达成，请立即调用 finish，不要再做任何操作）：")
            for a in completion_checks:
                lines.append(f"- {a['type']}: {a.get('target') or a.get('expected')}")
        if case.assertions:
            lines.append("断言（无需你执行，确保页面状态满足即可；绑定步骤的断言会在该步骤完成时立即执行）：")
            for a in case.assertions:
                suffix = f"（步骤 {int(a['after_step'])} 完成后校验）" if a.get("after_step") is not None else ""
                lines.append(f"- {a.get('type')}: {a.get('target') or a.get('expected')}{suffix}")
        return "\n".join(lines)

    @staticmethod
    def _trim(messages: list[dict], keep_tail: int = 10) -> None:
        """保留 system + 用例说明 + 最近几轮，防止长用例上下文膨胀。

        裁剪时把被丢弃的轮次压缩为「历史动作摘要」留在原位置——
        否则 LLM 遗忘已做过的动作，出现「重复点击同一步骤」的行为环。
        """
        if len(messages) > keep_tail + 2:
            dropped = messages[2 : len(messages) - keep_tail]
            acts: list[str] = []
            for m in dropped:
                if m.get("role") == "assistant":
                    try:
                        obj = json.loads(m["content"])
                        acts.append(f"{obj.get('tool')}({json.dumps(obj.get('args'), ensure_ascii=False)[:60]})")
                    except Exception:
                        pass
            summary = "【历史动作摘要】" + (" → ".join(acts[-20:]) if acts else "（无）")
            messages[2 : len(messages) - keep_tail] = [
                {"role": "user", "content": summary}
            ]
