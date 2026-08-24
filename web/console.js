"use strict";
/* EasyRun 控制台 — 零依赖 SPA：总览 / 用例 / 计划 / 执行 / 报告 / 配置（中英双语） */

const API = "/api";
const qs = (s) => document.querySelector(s);
const view = qs("#view");

/* ================= i18n ================= */

const I18N = {
  zh: {
    "nav.overview": "总览", "nav.cases": "用例", "nav.plans": "计划", "nav.runs": "执行",
    "nav.settings": "配置", "nav.docs": "使用文档", "nav.api": "API 文档", "nav.demo": "演示站点",
    "title.overview": "总览", "title.cases": "用例", "title.plans": "计划", "title.runs": "执行",
    "title.run": "执行报告", "title.settings": "配置", "title.404": "页面不存在",
    "health.queue": "queue", "health.workers": "workers", "health.llm": "LLM",
    "health.on": "已配置", "health.off": "未配置",
    "st.passed": "通过", "st.failed": "失败", "st.running": "执行中", "st.queued": "排队中",
    "st.retrying": "重试中", "st.quarantined": "已隔离", "st.partial": "部分通过",
    "st.pending": "待执行", "st.skipped": "跳过", "st.cancelled": "已取消",
    "common.back": "← 返回", "common.cancel": "取消", "common.delete": "删除",
    "common.save": "保存", "common.saved": "已保存", "common.create": "创建",
    "common.confirm": "确定", "common.edit": "编辑", "common.run": "运行",
    "common.view": "查看", "common.env": "环境", "common.tokens": "Token",
    "common.err.load": "加载失败: {0}", "common.err.op": "操作失败: {0}",
    "common.err.save": "保存失败: {0}", "common.err.del": "删除失败: {0}",
    "common.err.cancel": "取消失败: {0}", "common.err.export": "导出失败: {0}",
    "common.err.gen": "生成失败: {0}", "common.err.submit": "提交失败: {0}",
    "common.err.rerun": "重跑失败: {0}", "common.err.select": "请先勾选要删除的执行记录（可点「全选当前页」一键全选）",
    "ov.total_runs": "执行总数", "ov.pass_rate": "执行通过率", "ov.total_tasks": "任务总数",
    "ov.flakiness": "flakiness", "ov.avg_dur": "平均时长", "ov.token_cost": "Token 消耗",
    "ov.recent": "最近执行", "ov.no_runs": "暂无执行记录",
    "ov.locators": "元素库（自愈定位沉淀）", "ov.no_locators": "暂无元素记录（断言失败自愈后会自动沉淀）",
    "ov.col.status": "状态", "ov.col.src": "计划/用例", "ov.col.count": "用例数",
    "ov.col.start": "开始时间", "ov.col.pf": "通过/失败",
    "ov.col.elem": "元素", "ov.col.strategy": "策略", "ov.col.value": "值",
    "ov.col.source": "来源", "ov.col.verified": "验证", "ov.col.page": "页面",
    "ov.src.healed": "自愈", "ov.src.manual": "人工", "ov.verified": "已验证",
    "case.list": "用例列表（{0}）", "case.new": "+ 新建用例", "case.name": "名称",
    "case.desc": "说明", "case.target_url": "访问网址（默认值，运行时仍可修改）",
    "case.steps": "步骤（探索模式为自然语言，每行一步）",
    "case.assertions": "断言（确定性校验，由代码执行；可绑定步骤序号：该步骤完成后立即校验）",
    "case.nl_placeholder": "用一句话描述校验点，AI 生成断言：如「页面出现订单编号；跳转到结算页；列表有 3 个商品」",
    "case.nl_btn": "AI 生成断言", "case.add_assertion": "+ 添加断言",
    "case.goal": "完成条件（可选，满足即停止操作）",
    "case.goal_placeholder": "可选：页面出现这些文本即视为目标达成、停止一切操作（每行一个）。如：中性新闻 (",
    "case.goal_hint": "每一步操作前都会检查：页面可见内容出现这些文本 → 立即停止操作、进入断言。防止对已完成的目标做多余动作（如重复点击）。",
    "case.resource_key": "资源锁", "case.resource_hint": "多个用例共用同一账号时填写，执行时互斥排队",
    "case.edit_title": "编辑用例：{0}", "case.new_title": "新建用例",
    "case.name_required": "名称不能为空", "case.mode.cured": "固化", "case.mode.agentic": "探索",
    "case.col.id": "用例 ID", "case.col.mode": "模式", "case.col.steps": "步骤",
    "case.col.assertions": "断言", "case.col.version": "版本", "case.col.updated": "更新时间",
    "case.col.actions": "操作", "case.cure": "固化", "case.export": "导出代码",
    "case.confirm_del": "删除用例「{0}」？", "case.copy_id": "点击复制编号（内部 ID: {0}）",
    "case.no_cases": "暂无用例，点击「新建用例」创建第一条",
    "case.placeholder.name": "例：商城下单流程", "case.placeholder.desc": "用例说明（可选）",
    "case.placeholder.steps": "自然语言步骤，每行一步：\n1. 打开登录页\n2. 输入用户名 demo、密码 123456，点击登录\n3. …",
    "case.placeholder.url": "留空则用平台默认：{0}",
    "case.placeholder.resource": "共享资源锁标识（可选，如账号名）",
    "at.text_contains": "正文包含文本", "at.url_contains": "URL 包含",
    "at.element_exists": "选择器存在", "at.element_count": "选择器数量",
    "at.element_text": "存在文本元素", "at.text_in_view": "可见文本（屏幕内）",
    "at.text_near_top": "位置校验（文本在窗口上方）", "at.value_compare": "数值比较（标签后数值）",
    "at.visual": "视觉比对", "at.placeholder.target": "目标（文本 / URL 片段 / CSS 选择器）",
    "at.placeholder.target_label": "标签文本（如 订单金额）", "at.placeholder.expected": "期望值（数量类必填）",
    "at.placeholder.expected_cmp": "运算符+数字（如 >= 100）",
    "at.placeholder.step": "步骤序号（1-99，可选）",
    "plan.list": "测试计划（{0}）", "plan.new": "+ 新建计划", "plan.name": "名称",
    "plan.select_cases": "选择用例", "plan.confirm_del": "删除计划「{0}」？",
    "plan.no_plans": "暂无计划。计划 = 一组用例按序并行执行",
    "plan.need_name": "名称不能为空", "plan.need_case": "至少选择一个用例",
    "plan.col.count": "用例数", "plan.col.created": "创建时间",
    "run.submit": "提交执行", "run.single_case": "用例（单条）", "run.plan": "计划（批量）",
    "run.target_url": "目标地址", "run.pick_first": "请选择用例或计划", "run.pick_one": "用例与计划二选一",
    "run.records": "执行记录（共 {0} 条）", "run.batch_del": "批量删除（{0}）",
    "run.clear_sel": "取消选择", "run.select_all": "全选当前页", "run.unselect_all": "取消全选",
    "run.prev": "上一页", "run.next": "下一页", "run.page_of": "第 {0} / {1} 页",
    "run.per_page": "每页 {0} 条", "run.confirm_del_one": "确定删除该执行记录吗？\n将同时删除其任务、事件、截图、Allure 等全部关联内容，此操作不可恢复。",
    "run.confirm_del_many": "确定删除选中的 {0} 条执行记录吗？\n将同时删除其任务、事件、截图、Allure 等全部关联内容，此操作不可恢复。",
    "run.cancel_exec": "取消执行", "run.rerun_failed": "重跑失败用例（{0}）",
    "run.allure_gen": "生成 Allure 报告", "run.allure_view": "查看 Allure 报告",
    "run.allure_pending": "Allure 报告生成中… {0}s",
    "run.allure_missing": "Allure 结果已导出: {0}\n（未安装 allure CLI，安装后执行: allure serve {0}）",
    "run.col.status": "状态", "run.col.src": "计划/用例", "run.col.count": "用例数",
    "run.col.start": "开始时间", "run.col.dur": "时长", "run.col.pfq": "通过/失败/隔离",
    "run.col.report": "报告", "run.no_runs": "暂无执行记录", "run.multi_cases": "{0} 个用例",
    "run.badge.plan": "计划", "run.attempt": "尝试 {0}", "run.del_title": "删除该执行记录",
    "run.target_url_placeholder": "被测应用地址", "run.env_placeholder": "环境标识（可选）",
    "run.run_title_case": "运行用例：{0}", "run.run_title_plan": "运行计划：{0}",
    "rep.not_found": "执行不存在: {0}", "rep.timeline_of": "时间轴 · {0}",
    "rep.task_list": "任务列表", "rep.no_tasks": "暂无任务",
    "rep.no_events": "任务排队中，等待 Worker 领取…", "rep.no_events2": "暂无事件",
    "rep.session_start": "会话开始", "rep.mode": "模式 {0} · 目标 {1}",
    "rep.llm_decision": "LLM 决策", "rep.reason": "理由：",
    "rep.action": "动作执行", "rep.step_shot": "步骤截图", "rep.assertion": "断言", "rep.step_at": "步骤 {0}",
    "rep.pass": "通过", "rep.fail": "失败", "rep.heal_request": "自愈请求",
    "rep.heal_round": "第 {0} 轮：", "rep.heal_result": "自愈结果",
    "rep.heal_ok": "自愈成功，断言重新校验通过", "rep.heal_no": "自愈未成功",
    "rep.case_passed": "用例通过", "rep.case_failed": "用例失败",
    "rep.usage": "断言 {0} 条 · 动作 {1} 步 · LLM 调用 {2} 次 · 自愈 {3} 次",
    "rep.ai_attr": "AI 失败归因", "rep.confidence": "置信度 {0}%",
    "rep.defect": "缺陷草稿：", "rep.reproduce": "复现：", "rep.expected": "期望：", "rep.actual": "实际：",
    "fault.product_bug": "产品缺陷", "fault.env_issue": "环境问题", "fault.case_issue": "用例设计问题",
    "fault.locator_drift": "locator 漂移", "fault.agent_error": "Agent 误判",
    "cfg.title": "执行配置", "cfg.default_url": "默认执行目标地址",
    "cfg.default_url_hint": "运行用例 / 计划未填写网址时使用此地址（优先级：运行时填写 > 用例默认网址 > 此平台默认值）",
    "cfg.current": "当前生效值：{0}", "cfg.unset": "（未设置）", "cfg.placeholder": "如 http://www.mostoo.com",
    "cfg.policy_title": "执行策略（保存后立即生效）",
    "cfg.max_attempts": "失败重跑次数",
    "cfg.max_attempts_hint": "失败后自动重跑次数上限（1-10，默认 1 = 不重跑；置空恢复默认）",
    "cfg.heal_attempts": "断言自愈轮数",
    "cfg.heal_attempts_hint": "断言失败后 LLM 自愈重试轮数（0-5，默认 0 = 不自愈；每轮最多 6 次 LLM 调用）",
    "cfg.max_steps": "单用例最大动作步数",
    "cfg.max_steps_hint": "单用例 LLM 动作步数上限（3-100，默认 30）。收紧可显著降低 token 消耗",
    "cfg.failure_analysis": "失败归因",
    "cfg.failure_analysis_hint": "关闭后失败任务不再自动调 deepseek-reasoner 归因（省 token），报告页将没有根因分析与缺陷草稿",
    "cfg.policy_scope": "修改立即生效：新开始的任务 / 重试用新值，正在执行的任务不受影响",
    "modal.run_submit": "提交执行",
  },
  en: {
    "nav.overview": "Overview", "nav.cases": "Cases", "nav.plans": "Plans", "nav.runs": "Runs",
    "nav.settings": "Settings", "nav.docs": "User Guide", "nav.api": "API Docs", "nav.demo": "Demo Site",
    "title.overview": "Overview", "title.cases": "Cases", "title.plans": "Plans", "title.runs": "Runs",
    "title.run": "Run Report", "title.settings": "Settings", "title.404": "Page Not Found",
    "health.queue": "queue", "health.workers": "workers", "health.llm": "LLM",
    "health.on": "configured", "health.off": "missing",
    "st.passed": "passed", "st.failed": "failed", "st.running": "running", "st.queued": "queued",
    "st.retrying": "retrying", "st.quarantined": "quarantined", "st.partial": "partial",
    "st.pending": "pending", "st.skipped": "skipped", "st.cancelled": "cancelled",
    "common.back": "← Back", "common.cancel": "Cancel", "common.delete": "Delete",
    "common.save": "Save", "common.saved": "Saved", "common.create": "Create",
    "common.confirm": "OK", "common.edit": "Edit", "common.run": "Run",
    "common.view": "View", "common.env": "Env", "common.tokens": "Tokens",
    "common.err.load": "Failed to load: {0}", "common.err.op": "Operation failed: {0}",
    "common.err.save": "Save failed: {0}", "common.err.del": "Delete failed: {0}",
    "common.err.cancel": "Cancel failed: {0}", "common.err.export": "Export failed: {0}",
    "common.err.gen": "Generation failed: {0}", "common.err.submit": "Submit failed: {0}",
    "common.err.rerun": "Re-run failed: {0}", "common.err.select": "Select runs to delete first (use \"Select all on page\")",
    "ov.total_runs": "Total Runs", "ov.pass_rate": "Pass Rate", "ov.total_tasks": "Total Tasks",
    "ov.flakiness": "flakiness", "ov.avg_dur": "Avg Duration", "ov.token_cost": "Token Cost",
    "ov.recent": "Recent Runs", "ov.no_runs": "No runs yet",
    "ov.locators": "Element Repository (healed locators)", "ov.no_locators": "No locators yet (auto-collected after self-healing)",
    "ov.col.status": "Status", "ov.col.src": "Plan / Case", "ov.col.count": "Cases",
    "ov.col.start": "Started", "ov.col.pf": "Pass/Fail",
    "ov.col.elem": "Element", "ov.col.strategy": "Strategy", "ov.col.value": "Value",
    "ov.col.source": "Source", "ov.col.verified": "Verified", "ov.col.page": "Page",
    "ov.src.healed": "healed", "ov.src.manual": "manual", "ov.verified": "verified",
    "case.list": "Cases ({0})", "case.new": "+ New Case", "case.name": "Name",
    "case.desc": "Description", "case.target_url": "Target URL (default, overridable at run time)",
    "case.steps": "Steps (natural language in explore mode, one per line)",
    "case.assertions": "Assertions (deterministic checks, run by code; optional step #: checked right after that step)",
    "case.nl_placeholder": "Describe checks in one sentence, AI generates assertions, e.g. \"page shows Order No; URL contains checkout; list has 3 items\"",
    "case.nl_btn": "AI Generate", "case.add_assertion": "+ Add assertion",
    "case.goal": "Completion conditions (optional, stop when satisfied)",
    "case.goal_placeholder": "Optional: when these texts appear in the visible page the goal is reached and all actions stop (one per line). e.g. 中性新闻 (",
    "case.goal_hint": "Checked before every action: when these texts appear in the visible page → stop all actions and run assertions. Prevents redundant actions (e.g. repeated clicks) on an already-reached goal.",
    "case.resource_key": "Resource lock", "case.resource_hint": "Fill when cases share one account; executions queue exclusively",
    "case.edit_title": "Edit case: {0}", "case.new_title": "New case",
    "case.name_required": "Name is required", "case.mode.cured": "cured", "case.mode.agentic": "explore",
    "case.col.id": "Case ID", "case.col.mode": "Mode", "case.col.steps": "Steps",
    "case.col.assertions": "Asserts", "case.col.version": "Version", "case.col.updated": "Updated",
    "case.col.actions": "Actions", "case.cure": "Cure", "case.export": "Export code",
    "case.confirm_del": "Delete case \"{0}\"?", "case.copy_id": "Click to copy number (internal ID: {0})",
    "case.no_cases": "No cases yet — click \"+ New Case\"",
    "case.placeholder.name": "e.g. Store checkout flow", "case.placeholder.desc": "Description (optional)",
    "case.placeholder.steps": "Natural-language steps, one per line:\n1. Open the login page\n2. Type demo / 123456 and click Login\n3. …",
    "case.placeholder.url": "Empty = platform default: {0}",
    "case.placeholder.resource": "Shared resource key (optional, e.g. account name)",
    "at.text_contains": "Body contains text", "at.url_contains": "URL contains",
    "at.element_exists": "Selector exists", "at.element_count": "Selector count",
    "at.element_text": "Element text exists", "at.text_in_view": "Visible text (on screen)",
    "at.text_near_top": "Position check (text near top)", "at.value_compare": "Numeric compare (after label)",
    "at.visual": "Visual diff", "at.placeholder.target": "Target (text / URL fragment / CSS selector)",
    "at.placeholder.target_label": "Label text (e.g. Order Amount)", "at.placeholder.expected": "Expected (required for counts)",
    "at.placeholder.expected_cmp": "Operator + number (e.g. >= 100)",
    "at.placeholder.step": "Step # (1-99, optional)",
    "plan.list": "Plans ({0})", "plan.new": "+ New Plan", "plan.name": "Name",
    "plan.select_cases": "Select cases", "plan.confirm_del": "Delete plan \"{0}\"?",
    "plan.no_plans": "No plans yet. A plan runs a group of cases together",
    "plan.need_name": "Name is required", "plan.need_case": "Select at least one case",
    "plan.col.count": "Cases", "plan.col.created": "Created",
    "run.submit": "Submit Run", "run.single_case": "Case (single)", "run.plan": "Plan (batch)",
    "run.target_url": "Target URL", "run.pick_first": "Select a case or plan", "run.pick_one": "Choose either case or plan",
    "run.records": "Runs ({0} total)", "run.batch_del": "Delete ({0})",
    "run.clear_sel": "Clear selection", "run.select_all": "Select all on page", "run.unselect_all": "Unselect all",
    "run.prev": "Prev", "run.next": "Next", "run.page_of": "Page {0} / {1}",
    "run.per_page": "{0} / page", "run.confirm_del_one": "Delete this run? All related tasks, events, screenshots and Allure artifacts will be removed. This cannot be undone.",
    "run.confirm_del_many": "Delete the selected {0} runs? All related tasks, events, screenshots and Allure artifacts will be removed. This cannot be undone.",
    "run.cancel_exec": "Cancel Run", "run.rerun_failed": "Re-run Failed ({0})",
    "run.allure_gen": "Generate Allure Report", "run.allure_view": "View Allure Report",
    "run.allure_pending": "Allure Report generating… {0}s",
    "run.allure_missing": "Allure results exported: {0}\n(install allure CLI, then run: allure serve {0})",
    "run.col.status": "Status", "run.col.src": "Plan/Case", "run.col.count": "Cases",
    "run.col.start": "Started", "run.col.dur": "Duration", "run.col.pfq": "Pass/Fail/Quar",
    "run.col.report": "Report", "run.no_runs": "No runs yet", "run.multi_cases": "{0} cases",
    "run.badge.plan": "plan", "run.attempt": "attempt {0}", "run.del_title": "Delete this run",
    "run.target_url_placeholder": "Target app URL", "run.env_placeholder": "Environment tag (optional)",
    "run.run_title_case": "Run case: {0}", "run.run_title_plan": "Run plan: {0}",
    "rep.not_found": "Run not found: {0}", "rep.timeline_of": "Timeline · {0}",
    "rep.task_list": "Tasks", "rep.no_tasks": "No tasks",
    "rep.no_events": "Task queued, waiting for a worker…", "rep.no_events2": "No events yet",
    "rep.session_start": "Session start", "rep.mode": "mode {0} · target {1}",
    "rep.llm_decision": "LLM decision", "rep.reason": "Reason: ",
    "rep.action": "Action", "rep.step_shot": "Step screenshot", "rep.assertion": "Assertion", "rep.step_at": "step {0}",
    "rep.pass": "pass", "rep.fail": "fail", "rep.heal_request": "Heal request",
    "rep.heal_round": "Round {0}: ", "rep.heal_result": "Heal result",
    "rep.heal_ok": "Healed — assertions re-verified", "rep.heal_no": "Healing failed",
    "rep.case_passed": "Case passed", "rep.case_failed": "Case failed",
    "rep.usage": "{0} asserts · {1} actions · {2} LLM calls · {3} heals",
    "rep.ai_attr": "AI Failure Attribution", "rep.confidence": "confidence {0}%",
    "rep.defect": "Defect draft: ", "rep.reproduce": "Steps: ", "rep.expected": "Expected: ", "rep.actual": "Actual: ",
    "fault.product_bug": "Product bug", "fault.env_issue": "Env issue", "fault.case_issue": "Case design",
    "fault.locator_drift": "Locator drift", "fault.agent_error": "Agent error",
    "cfg.title": "Execution Settings", "cfg.default_url": "Default target URL",
    "cfg.default_url_hint": "Used when no URL is given at run time (priority: run-time input > case URL > this platform default)",
    "cfg.current": "Current value: {0}", "cfg.unset": "(unset)", "cfg.placeholder": "e.g. http://www.mostoo.com",
    "cfg.policy_title": "Execution Policy (takes effect once saved)",
    "cfg.max_attempts": "Max retries on failure",
    "cfg.max_attempts_hint": "Auto re-run cap after failure (1-10, default 1 = no re-run; empty = default)",
    "cfg.heal_attempts": "Self-healing rounds",
    "cfg.heal_attempts_hint": "LLM self-healing rounds after assertion failure (0-5, default 0 = off; up to 6 LLM calls per round)",
    "cfg.max_steps": "Max action steps per case",
    "cfg.max_steps_hint": "Cap on LLM action steps per case (3-100, default 30). Lower it to cut token usage",
    "cfg.failure_analysis": "Failure analysis",
    "cfg.failure_analysis_hint": "When off, failed tasks skip the deepseek-reasoner root-cause call (saves tokens); report pages lose root-cause analysis and defect drafts",
    "cfg.policy_scope": "Changes apply to new tasks / retries immediately; running tasks are unaffected",
    "modal.run_submit": "Submit Run",
  },
};

let lang = localStorage.getItem("easyrun-lang") ||
  (navigator.language && navigator.language.startsWith("zh") ? "zh" : "en");

function t(key, ...args) {
  const dict = I18N[lang] || I18N.zh;
  let s = dict[key] ?? I18N.zh[key] ?? key;
  args.forEach((a, i) => { s = s.replace(`{${i}}`, String(a)); });
  return s;
}

function applyStaticI18n() {
  document.querySelectorAll("[data-i18n]").forEach((el) => {
    el.textContent = t(el.getAttribute("data-i18n"));
  });
  document.documentElement.lang = lang === "zh" ? "zh-CN" : "en";
}

/* ================= 基础工具 ================= */

function esc(s) {
  // 所有文本都经 createTextNode / setAttribute 写入（无 innerHTML），
  // 天然防注入，无需 HTML 转义——转义会让「复制出来的文本」带 &quot; 等实体字符。
  return String(s ?? "");
}

// 展示 JSON：对象 → 格式化字符串；历史数据可能自带 HTML 实体（可能多重编码），循环解码直到稳定
function displayJson(v) {
  let s = typeof v === "string" ? v : JSON.stringify(v, null, 2);
  let prev;
  do {
    prev = s;
    s = s
      .replace(/&quot;/g, '"')
      .replace(/&#39;/g, "'")
      .replace(/&lt;/g, "<")
      .replace(/&gt;/g, ">")
      .replace(/&amp;/g, "&");
  } while (s !== prev);
  return s;
}

function el(tag, attrs = {}, ...children) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") n.className = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined) n.setAttribute(k, v);
  }
  for (const c of children.flat(3)) {
    if (c === null || c === undefined) continue;
    n.append(c.nodeType ? c : document.createTextNode(String(c)));
  }
  return n;
}

async function api(path, opts = {}) {
  const init = { headers: { "Content-Type": "application/json" }, ...opts };
  if (opts.body !== undefined) init.body = JSON.stringify(opts.body);
  const res = await fetch(API + path, init);
  if (!res.ok) {
    let msg = res.statusText;
    try { const j = await res.json(); msg = j.detail || JSON.stringify(j); } catch (e) { /* ignore */ }
    throw new Error(msg);
  }
  return res.json();
}

/* Allure 报告按钮：按需生成，生成一次后保存复用。
   - 未生成：显示「生成 Allure 报告」，点击后生成（带耗时状态跟踪）
   - 已生成：显示「查看 Allure 报告」原生 <a> 链接（原生链接不会被弹窗拦截器拦截） */
const allureJobs = {};
function allureGenerated(runId) {
  return fetch(`/allure-html/${runId}/`, { method: "HEAD" })
    .then((r) => r.ok)
    .catch(() => false);
}
function ensureAllure(runId) {
  if (!allureJobs[runId]) {
    allureJobs[runId] = api(`/runs/${runId}/allure`, { method: "POST" })
      .finally(() => { delete allureJobs[runId]; });
  }
  return allureJobs[runId];
}
function allureViewLink(runId) {
  return el("a", { class: "btn", href: `/allure-html/${runId}/`, target: "_blank", rel: "noopener" }, t("run.allure_view"));
}
function setGenerating(btn) {
  btn.disabled = true;
  btn.style.opacity = ".6";
  btn.style.cursor = "default";
  const start = Date.now();
  btn.textContent = t("run.allure_pending", 0);
  const tick = setInterval(() => {
    if (!btn.isConnected) { clearInterval(tick); return; }
    btn.textContent = t("run.allure_pending", Math.round((Date.now() - start) / 1000));
  }, 1000);
  return () => {
    clearInterval(tick);
    btn.disabled = false;
    btn.style.opacity = "";
    btn.style.cursor = "";
    btn.textContent = t("run.allure_gen");
  };
}
function allureGenBtn(runId) {
  return el("button", {
    class: "btn",
    onclick: async function () {
      const btn = this;
      const reset = setGenerating(btn);
      try {
        const r = await ensureAllure(runId);
        if (!btn.isConnected) return;  // 页面已切走 / 已重渲染
        if (r.html_url) {
          reset();
          btn.replaceWith(allureViewLink(runId));
        } else {
          reset();
          alert(t("run.allure_missing", r.dir));
        }
      } catch (e) {
        if (!btn.isConnected) return;
        reset();
        alert(t("common.err.export", e.message));
      }
    },
  }, t("run.allure_gen"));
}
function renderAllureBtn(runId) {
  const wrap = el("span", { style: "margin-left:8px" });
  const btn = allureGenBtn(runId);
  wrap.append(btn);
  const job = allureJobs[runId];
  if (job) {
    // 生成进行中（如执行中轮询重渲染），直接进入进度态并跟随原任务
    setGenerating(btn);
    job.then((r) => {
      if (!btn.isConnected) return;
      if (r.html_url) btn.replaceWith(allureViewLink(runId));
    }).catch(() => { /* 触发按钮已复位并提示 */ });
  } else {
    // 已生成过则直接显示查看链接（HEAD 探测，秒回）
    allureGenerated(runId).then((gen) => {
      if (gen && btn.isConnected) btn.replaceWith(allureViewLink(runId));
    });
  }
  return wrap;
}

function fmtTs(iso, withYear) {
  if (!iso) return "—";
  const d = new Date(iso);
  const p = (x) => String(x).padStart(2, "0");
  const date = withYear
    ? `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
    : `${d.getMonth() + 1}-${d.getDate()}`;
  return `${date} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

function fmtDur(sec) {
  if (sec === null || sec === undefined) return "—";
  if (sec < 60) return sec.toFixed(1) + "s";
  if (sec < 3600) return (sec / 60).toFixed(1) + "min";
  return (sec / 3600).toFixed(1) + "h";
}

const STATUS_CLS = { passed: "passed", failed: "failed", running: "running", queued: "queued", retrying: "retrying", quarantined: "quarantined", partial: "partial", cancelled: "quarantined" };

function chip(status) {
  const label = (I18N[lang] && I18N[lang]["st." + status]) || I18N.zh["st." + status] || status;
  return el("span", { class: "chip " + (STATUS_CLS[status] || "") }, label);
}

const FAULT_KEY = { product_bug: "fault.product_bug", env_issue: "fault.env_issue", case_issue: "fault.case_issue", locator_drift: "fault.locator_drift", agent_error: "fault.agent_error" };

function badge(text, cls = "") { return el("span", { class: "badge " + cls }, text); }

function modal(titleText, bodyNode, onOk, okText) {
  const mask = el("div", { class: "modal-mask" });
  const m = el("div", { class: "modal" });
  m.append(el("h3", {}, titleText));
  m.append(bodyNode);
  const foot = el("div", { class: "foot" });
  const cancel = el("button", { class: "btn", onclick: () => mask.remove() }, t("common.cancel"));
  const ok = el("button", {
    class: "btn primary",
    onclick: async () => { try { await onOk(); mask.remove(); } catch (e) { alert(t("common.err.op", e.message)); } },
  }, okText || t("common.confirm"));
  foot.append(cancel, ok);
  m.append(foot);
  mask.append(m);
  mask.addEventListener("click", (e) => { if (e.target === mask) mask.remove(); });
  document.body.append(mask);
  return m;
}

function field(labelText, inputNode, hintText = "") {
  const wrap = el("div", {});
  wrap.append(el("label", {}, labelText), inputNode);
  if (hintText) wrap.append(el("div", { class: "hint" }, hintText));
  return wrap;
}

function empty(text) { return el("div", { class: "empty" }, text); }

// 删除图标（trash，内联 SVG，跟随文字颜色）
function trashIcon() {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 16 16");
  svg.setAttribute("width", "13");
  svg.setAttribute("height", "13");
  svg.setAttribute("fill", "currentColor");
  svg.setAttribute("aria-hidden", "true");
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d",
    "M2.5 1a1 1 0 0 0-1 1v1a1 1 0 0 0 1 1H3v9a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2V4h.5a1 1 0 0 0 1-1V2a1 1 0 0 0-1-1H10a1 1 0 0 0-1-1H7a1 1 0 0 0-1 1H2.5zm3 4a.5.5 0 0 1 .5.5v7a.5.5 0 0 1-1 0v-7a.5.5 0 0 1 .5-.5zM8 5a.5.5 0 0 1 .5.5v7a.5.5 0 0 1-1 0v-7A.5.5 0 0 1 8 5zm3 .5v7a.5.5 0 0 1-1 0v-7a.5.5 0 0 1 1 0z");
  svg.append(path);
  return svg;
}

/* ================= 全局状态 ================= */

let pollTimer = null;
function stopPoll() { if (pollTimer) { clearInterval(pollTimer); pollTimer = null; } }

let runsPage = 1;
let runsPageSize = 20;
let defaultTargetUrl = "http://127.0.0.1:8000/demo/";
const selectedRunIds = new Set();

async function deleteRuns(ids) {
  if (!ids.length) return;
  if (!confirm(t("run.confirm_del_many", ids.length))) return;
  try {
    await api("/runs/batch-delete", { method: "POST", body: { run_ids: ids } });
    ids.forEach((id) => selectedRunIds.delete(id));
    renderRuns();
  } catch (e) { alert(t("common.err.del", e.message)); }
}

// 执行记录的来源名称：测试计划执行 → 计划名；单用例执行 → 用例名
function makeRunTitle(planMap, caseMap) {
  return (r) => {
    if (r.plan_id && planMap.has(r.plan_id)) {
      return [badge(t("run.badge.plan"), "ok"), " " + esc(planMap.get(r.plan_id))];
    }
    if (r.case_ids.length === 1 && caseMap.has(r.case_ids[0])) {
      return [esc(caseMap.get(r.case_ids[0]))];
    }
    return [t("run.multi_cases", r.case_ids.length)];
  };
}

function runModal(kind, refId, name, defaultUrl) {
  const url = el("input", { value: defaultUrl || defaultTargetUrl, placeholder: t("run.target_url_placeholder") });
  const env = el("input", { value: "", placeholder: t("run.env_placeholder") });
  modal(
    t(kind === "case" ? "run.run_title_case" : "run.run_title_plan", name),
    el("div", {}, field(t("run.target_url"), url), field(t("common.env"), env)),
    async () => {
      const r = await api("/runs", { method: "POST", body: kind === "case" ? { case_id: refId, target_url: url.value, env: env.value } : { plan_id: refId, target_url: url.value, env: env.value } });
      location.hash = "#/run/" + r.id;
    },
    t("modal.run_submit")
  );
}

/* ================= 路由 ================= */

async function route() {
  stopPoll();
  const parts = location.hash.slice(1).split("/").filter(Boolean);
  const v = parts[0] || "overview";
  const id = parts[1];
  document.querySelectorAll(".nav a").forEach((a) => a.classList.toggle("active", a.dataset.nav === v));
  qs("#page-title").textContent = t("title." + v) || "EasyRun";
  view.innerHTML = "";
  try {
    if (v === "overview") await renderOverview();
    else if (v === "cases") await renderCases();
    else if (v === "plans") await renderPlans();
    else if (v === "runs") await renderRuns();
    else if (v === "settings") await renderSettings();
    else if (v === "run" && id) await renderRun(id);
    else view.append(el("div", { class: "panel" }, el("p", {}, t("title.404"))));
  } catch (e) {
    view.append(el("div", { class: "panel" }, el("p", { style: "color:var(--fail)" }, t("common.err.load", e.message))));
  }
}
window.addEventListener("hashchange", route);

async function loadHealth() {
  try {
    const h = await api("/health");
    const node = qs("#health");
    node.textContent = `${t("health.queue")}: ${h.queue} · ${t("health.workers")}: ${h.workers} · ${t("health.llm")}: ${h.llm_configured ? t("health.on") : t("health.off")}`;
    node.classList.toggle("ok", h.ok);
  } catch (e) { /* ignore */ }
}

async function loadAppSettings() {
  try {
    const s = await api("/settings");
    if (s.default_target_url) defaultTargetUrl = s.default_target_url;
  } catch (e) { /* 配置加载失败用内置默认值 */ }
}

/* ================= 总览 ================= */

async function renderOverview() {
  const [tdata, locs, cases, plans] = await Promise.all([
    api("/trends"), api("/locators"), api("/cases"), api("/plans"),
  ]);
  const runTitle = makeRunTitle(
    new Map(plans.map((p) => [p.id, p.name])),
    new Map(cases.map((c) => [c.id, c.name]))
  );
  view.append(
    el("div", { class: "cards" },
      el("div", { class: "card" }, el("div", { class: "k" }, t("ov.total_runs")), el("div", { class: "v" }, tdata.total_runs)),
      el("div", { class: "card" }, el("div", { class: "k" }, t("ov.pass_rate")), el("div", { class: "v" }, (tdata.pass_rate * 100).toFixed(1) + "%")),
      el("div", { class: "card" }, el("div", { class: "k" }, t("ov.total_tasks")), el("div", { class: "v" }, tdata.total_tasks, el("small", {}, t("ov.flakiness") + " " + (tdata.flakiness * 100).toFixed(1) + "%"))),
      el("div", { class: "card" }, el("div", { class: "k" }, t("ov.avg_dur")), el("div", { class: "v" }, fmtDur(tdata.avg_duration_seconds))),
      el("div", { class: "card" }, el("div", { class: "k" }, t("ov.token_cost")), el("div", { class: "v" }, tdata.total_tokens.toLocaleString())),
    ),
    el("div", { class: "panel" },
      el("h3", {}, t("ov.recent")),
      tdata.recent_runs.length
        ? el("table", { class: "tbl" },
            el("thead", {}, el("tr", {},
              ...[t("ov.col.status"), t("ov.col.src"), t("ov.col.count"), t("ov.col.start"), t("ov.col.pf"), t("common.env")].map((h) => el("th", {}, h)))),
            el("tbody", {}, ...tdata.recent_runs.map((r) =>
              el("tr", { class: "clickable", onclick: () => { location.hash = "#/run/" + r.id; } },
                el("td", {}, chip(r.status)),
                el("td", {}, runTitle(r)),
                el("td", { class: "mono" }, r.case_ids.length),
                el("td", { class: "mono" }, fmtTs(r.started_at)),
                el("td", { class: "mono" }, `${r.stats?.passed ?? 0} / ${r.stats?.failed ?? 0}`),
                el("td", { class: "muted" }, esc(r.env || "—"))))))
        : empty(t("ov.no_runs"))),
    el("div", { class: "panel" },
      el("h3", {}, t("ov.locators")),
      locs.length
        ? el("table", { class: "tbl" },
            el("thead", {}, el("tr", {}, ...[t("ov.col.elem"), t("ov.col.strategy"), t("ov.col.value"), t("ov.col.source"), t("ov.col.verified"), t("ov.col.page")].map((h) => el("th", {}, h)))),
            el("tbody", {}, ...locs.map((l) =>
              el("tr", {},
                el("td", {}, el("b", {}, esc(l.element_key))),
                el("td", { class: "mono" }, l.strategy),
                el("td", { class: "mono muted" }, esc(l.value)),
                el("td", {}, badge(l.source === "healed" ? t("ov.src.healed") : t("ov.src.manual"), l.source === "healed" ? "err" : "")),
                el("td", {}, l.verified ? badge(t("ov.verified"), "ok") : "—"),
                el("td", { class: "mono muted" }, esc(l.page || "—"))))))
        : empty(t("ov.no_locators")))
  );
}

/* ================= 用例 ================= */

const ASSERTION_TYPE_LABELS = () => ({
  text_contains: t("at.text_contains"), url_contains: t("at.url_contains"),
  element_exists: t("at.element_exists"), element_count: t("at.element_count"),
  element_text: t("at.element_text"), text_in_view: t("at.text_in_view"),
  text_near_top: t("at.text_near_top"), value_compare: t("at.value_compare"),
  visual: t("at.visual"),
});

function caseForm(c) {
  const name = el("input", { value: c?.name || "", placeholder: t("case.placeholder.name") });
  const desc = el("textarea", { rows: 2, placeholder: t("case.placeholder.desc") }, c?.description || "");
  const targetUrl = el("input", { value: c?.target_url || "", placeholder: t("case.placeholder.url", defaultTargetUrl) });
  const steps = el("textarea", {
    rows: 6,
    placeholder: t("case.placeholder.steps"),
  }, (c?.steps || []).map((s) => (typeof s === "string" ? s : JSON.stringify(s))).join("\n"));
  const resKey = el("input", { value: c?.resource_key || "", placeholder: t("case.placeholder.resource") });
  const goalInput = el("textarea", {
    rows: 2,
    placeholder: t("case.goal_placeholder"),
  }, (c?.completion_checks || []).map((a) => a.target).join("\n"));

  const nlInput = el("input", { placeholder: t("case.nl_placeholder") });
  const nlRow = el("div", { style: "display:flex;gap:8px;margin-top:4px" },
    nlInput,
    el("button", {
      class: "btn",
      style: "white-space:nowrap",
      onclick: async (e) => {
        e.preventDefault();
        const text = nlInput.value.trim();
        if (!text) { alert(t("common.err.select")); return; }
        try {
          const r = await api("/cases/assertions/parse", { method: "POST", body: { text } });
          r.assertions.forEach((a) => asserts.push({ type: a.type, target: a.target, expected: a.expected }));
          renderAsserts();
          nlInput.value = "";
        } catch (err) { alert(t("common.err.gen", err.message)); }
      },
    }, t("case.nl_btn")));

  const assertRows = el("div", {});
  let asserts = (c?.assertions || []).map((a) => ({ ...a }));
  if (!asserts.length) asserts = [{ type: "text_contains", target: "", expected: "" }];
  function renderAsserts() {
    assertRows.innerHTML = "";
    asserts.forEach((a, i) => {
      const labels = ASSERTION_TYPE_LABELS();
      const typeSel = el("select", {},
        ...Object.entries(labels).map(([v, label]) => el("option", { value: v, selected: a.type === v ? "" : null }, label)));
      typeSel.value = a.type;
      typeSel.onchange = () => { a.type = typeSel.value; };
      const target = el("input", { value: a.target, placeholder: a.type === "value_compare" ? t("at.placeholder.target_label") : t("at.placeholder.target"), oninput: (e) => { a.target = e.target.value; } });
      const expected = el("input", { value: a.expected, placeholder: a.type === "value_compare" ? t("at.placeholder.expected_cmp") : t("at.placeholder.expected"), oninput: (e) => { a.expected = e.target.value; } });
      const step = el("input", { type: "number", min: "1", max: "99", style: "width:70px", value: a.after_step ?? "", placeholder: t("at.placeholder.step"), oninput: (e) => { const v = parseInt(e.target.value, 10); a.after_step = Number.isInteger(v) && v >= 1 && v <= 99 ? v : null; } });
      const del = el("button", { class: "btn sm danger", onclick: () => { asserts.splice(i, 1); renderAsserts(); } }, t("common.delete"));
      assertRows.append(el("div", { class: "row", style: "margin-bottom:8px" }, typeSel, target, expected, step, del));
    });
  }
  renderAsserts();

  const body = el("div", {},
    field(t("case.name"), name),
    field(t("case.desc"), desc),
    field(t("case.target_url"), targetUrl),
    field(t("case.steps"), steps),
    el("label", { style: "margin-top:14px" }, t("case.assertions")),
    nlRow,
    assertRows,
    el("button", { class: "btn sm", onclick: () => { asserts.push({ type: "text_contains", target: "", expected: "" }); renderAsserts(); } }, t("case.add_assertion")),
    field(t("case.goal"), goalInput, t("case.goal_hint")),
    field(t("case.resource_key"), resKey, t("case.resource_hint")),
  );
  return { body, collect: () => ({
    name: name.value.trim(),
    description: desc.value.trim(),
    target_url: targetUrl.value.trim(),
    steps: steps.value.split("\n").map((s) => s.trim()).filter(Boolean),
    assertions: asserts.filter((a) => a.target || a.expected || a.type === "element_count" || a.type === "value_compare").map((a) => ({ type: a.type, target: a.target.trim(), expected: a.expected.trim(), ...(a.after_step ? { after_step: a.after_step } : {}) })),
    completion_checks: goalInput.value.split("\n").map((s) => s.trim()).filter(Boolean).map((x) => {
      const prev = (c?.completion_checks || []).find((a) => a.target === x);
      return { type: "text_in_view", target: x, ...(prev?.min_steps ? { min_steps: prev.min_steps } : {}) };
    }),
    resource_key: resKey.value.trim(),
  }) };
}

function openCaseModal(c) {
  const isEdit = !!(c && c.id);
  const f = caseForm(isEdit ? c : null);
  modal(isEdit ? t("case.edit_title", c.name) : t("case.new_title"), f.body, async () => {
    const data = f.collect();
    if (!data.name) throw new Error(t("case.name_required"));
    if (isEdit) await api(`/cases/${c.id}`, { method: "PUT", body: data });
    else await api("/cases", { method: "POST", body: { ...data, mode: "agentic" } });
    location.reload();
  }, isEdit ? t("common.save") : t("common.create"));
}

async function renderCases() {
  const cases = await api("/cases");
  view.append(
    el("div", { class: "panel" },
      el("div", { style: "display:flex;justify-content:space-between;align-items:center;margin-bottom:12px" },
        el("h3", { style: "margin:0" }, t("case.list", cases.length)),
        el("button", { class: "btn primary", onclick: () => openCaseModal() }, t("case.new"))),
      cases.length
        ? el("table", { class: "tbl" },
            el("thead", {}, el("tr", {}, ...[t("case.name"), t("case.col.id"), t("case.col.mode"), t("case.col.steps"), t("case.col.assertions"), t("case.col.version"), t("case.col.updated"), t("case.col.actions")].map((h) => el("th", {}, h)))),
            el("tbody", {}, ...cases.map((c) => {
              const actions = el("td", {});
              actions.append(el("a", { href: "#", onclick: (e) => { e.preventDefault(); runModal("case", c.id, c.name, c.target_url); } }, t("common.run")));
              if (c.cured_actions?.length && c.mode === "agentic") {
                actions.append(el("a", { href: "#", style: "margin-left:10px", onclick: async (e) => { e.preventDefault(); await api(`/cases/${c.id}/cure`, { method: "POST" }); location.reload(); } }, t("case.cure")));
              }
              if (c.cured_actions?.length || c.mode === "deterministic") {
                actions.append(el("a", { href: "#", style: "margin-left:10px", onclick: async (e) => {
                  e.preventDefault();
                  try {
                    const r = await api(`/cases/${c.id}/export-code`, { method: "POST" });
                    const blob = new Blob([r.code], { type: "text/x-python" });
                    const a = document.createElement("a");
                    a.href = URL.createObjectURL(blob);
                    a.download = r.filename;
                    a.click();
                    URL.revokeObjectURL(a.href);
                  } catch (err) { alert(t("common.err.export", err.message)); }
                } }, t("case.export")));
              }
              actions.append(el("a", { href: "#", style: "margin-left:10px", onclick: (e) => { e.preventDefault(); openCaseModal(c); } }, t("common.edit")));
              actions.append(el("a", { href: "#", style: "margin-left:10px;color:var(--fail)", onclick: async (e) => { e.preventDefault(); if (confirm(t("case.confirm_del", c.name))) { await api(`/cases/${c.id}`, { method: "DELETE" }); location.reload(); } } }, t("common.delete")));
              return el("tr", {},
                el("td", {}, el("b", {}, esc(c.name))),
                el("td", {},
                  el("span", {
                    class: "mono muted",
                    style: "font-size:12px;cursor:pointer;user-select:all",
                    title: t("case.copy_id", c.id),
                    onclick: () => {
                      navigator.clipboard?.writeText(String(c.case_no ?? "")).then(
                        () => { /* 复制成功 */ },
                        () => { alert(c.case_no); });
                    },
                  }, `#${c.case_no ?? "—"}`)),
                el("td", {}, c.mode === "deterministic" ? badge(t("case.mode.cured"), "ok") : badge(t("case.mode.agentic"))),
                el("td", { class: "mono" }, c.steps.length),
                el("td", { class: "mono" }, c.assertions.length),
                el("td", { class: "mono" }, "v" + c.version),
                el("td", { class: "mono muted" }, fmtTs(c.updated_at)),
                actions);
            })))
        : empty(t("case.no_cases")))
  );
}

/* ================= 计划 ================= */

async function renderPlans() {
  const [plans, cases] = await Promise.all([api("/plans"), api("/cases")]);
  view.append(
    el("div", { class: "panel" },
      el("div", { style: "display:flex;justify-content:space-between;align-items:center;margin-bottom:12px" },
        el("h3", { style: "margin:0" }, t("plan.list", plans.length)),
        el("button", { class: "btn primary", onclick: () => openPlanModal(cases) }, t("plan.new"))),
      plans.length
        ? el("table", { class: "tbl" },
            el("thead", {}, el("tr", {}, ...[t("plan.name"), t("plan.col.count"), t("plan.col.created"), t("case.col.actions")].map((h) => el("th", {}, h)))),
            el("tbody", {}, ...plans.map((p) => {
              const actions = el("td", {});
              actions.append(el("a", { href: "#", onclick: (e) => { e.preventDefault(); runModal("plan", p.id, p.name); } }, t("common.run")));
              actions.append(el("a", { href: "#", style: "margin-left:10px;color:var(--fail)", onclick: async (e) => { e.preventDefault(); if (confirm(t("plan.confirm_del", p.name))) { await api(`/plans/${p.id}`, { method: "DELETE" }); location.reload(); } } }, t("common.delete")));
              return el("tr", {},
                el("td", {}, el("b", {}, esc(p.name))),
                el("td", { class: "mono" }, p.case_ids.length),
                el("td", { class: "mono muted" }, fmtTs(p.created_at)),
                actions);
            })))
        : empty(t("plan.no_plans")))
  );
}

function openPlanModal(cases) {
  const name = el("input", { placeholder: "例：商城核心链路冒烟" });
  const box = el("div", { style: "max-height:300px;overflow:auto" });
  const picked = new Set();
  cases.forEach((c) => {
    const cb = el("input", { type: "checkbox", style: "width:auto;margin-right:8px", onchange: () => { cb.checked ? picked.add(c.id) : picked.delete(c.id); } });
    box.append(el("div", { style: "padding:4px 0" }, cb, esc(c.name)));
  });
  modal(t("plan.new"), el("div", {}, field(t("plan.name"), name), el("label", {}, t("plan.select_cases")), box), async () => {
    if (!name.value.trim()) throw new Error(t("plan.need_name"));
    if (!picked.size) throw new Error(t("plan.need_case"));
    await api("/plans", { method: "POST", body: { name: name.value.trim(), case_ids: [...picked] } });
    location.reload();
  }, t("common.create"));
}

/* ================= 执行 ================= */

async function renderRuns() {
  stopPoll();
  view.innerHTML = "";
  const [runsResp, cases, plans] = await Promise.all([
    api(`/runs?page=${runsPage}&page_size=${runsPageSize}`),
    api("/cases"), api("/plans"),
  ]);
  const runs = runsResp.items;
  const anyActive = runs.some((r) => ["running", "pending"].includes(r.status));

  const caseSel = el("select", {}, el("option", { value: "" }, "— " + t("run.single_case") + " —"), ...cases.map((c) => el("option", { value: c.id }, c.name)));
  const planSel = el("select", {}, el("option", { value: "" }, "— " + t("run.plan") + " —"), ...plans.map((p) => el("option", { value: p.id }, p.name)));
  const url = el("input", { value: defaultTargetUrl, placeholder: t("run.target_url_placeholder") });

  const planMap = new Map(plans.map((p) => [p.id, p.name]));
  const caseMap = new Map(cases.map((c) => [c.id, c.name]));
  const runTitle = makeRunTitle(planMap, caseMap);
  const pageIds = runs.map((r) => r.id);
  const allSelected = pageIds.length > 0 && pageIds.every((id) => selectedRunIds.has(id));

  view.append(
    el("div", { class: "panel" },
      el("h3", {}, t("run.submit")),
      el("div", { class: "row" },
        field(t("run.single_case"), caseSel),
        field(t("run.plan"), planSel)),
      field(t("run.target_url"), url),
      el("div", { style: "margin-top:14px" },
        el("button", { class: "btn primary", onclick: async () => {
          const case_id = caseSel.value, plan_id = planSel.value;
          if (!case_id && !plan_id) { alert(t("run.pick_first")); return; }
          if (case_id && plan_id) { alert(t("run.pick_one")); return; }
          try {
            const r = await api("/runs", { method: "POST", body: { case_id: case_id || null, plan_id: plan_id || null, target_url: url.value } });
            location.hash = "#/run/" + r.id;
          } catch (e) { alert(t("common.err.submit", e.message)); }
        } }, t("run.submit")))),
    el("div", { class: "panel" },
      el("div", { style: "display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;gap:10px;flex-wrap:wrap" },
        el("h3", { style: "margin:0" }, t("run.records", runsResp.total)),
        el("div", {},
          el("button", { class: "btn sm", onclick: () => {
            if (allSelected) pageIds.forEach((id) => selectedRunIds.delete(id));
            else pageIds.forEach((id) => selectedRunIds.add(id));
            renderRuns();
          } }, allSelected ? t("run.unselect_all") : t("run.select_all")),
          el("button", {
            class: "btn danger",
            style: "margin-left:8px",
            onclick: () => selectedRunIds.size ? deleteRuns([...selectedRunIds]) : alert(t("common.err.select")),
          }, t("run.batch_del", selectedRunIds.size)),
          selectedRunIds.size
            ? el("button", { class: "btn sm", style: "margin-left:8px", onclick: () => { selectedRunIds.clear(); renderRuns(); } }, t("run.clear_sel"))
            : null)),
      runs.length
        ? el("table", { class: "tbl dense" },
            el("thead", {}, (() => {
              const headRow = el("tr", {},
                ...[t("run.col.status"), t("run.col.src"), t("run.col.count"), t("run.col.start"), t("run.col.dur"), t("run.col.pfq"), t("common.tokens"), t("common.env"), t("run.col.report")].map((h) => el("th", {}, h)));
              headRow.prepend(
                el("th", { style: "width:32px" }, el("input", {
                  type: "checkbox", style: "width:auto;cursor:pointer",
                  checked: allSelected ? "" : null,
                  onchange: (e) => {
                    if (e.target.checked) runs.forEach((r) => selectedRunIds.add(r.id));
                    else runs.forEach((r) => selectedRunIds.delete(r.id));
                    renderRuns();
                  },
                })));
              return headRow;
            })()),
            el("tbody", {}, ...runs.map((r) => {
              const s = r.stats || {};
              return el("tr", {},
                el("td", {}, el("input", {
                  type: "checkbox", style: "width:auto;cursor:pointer",
                  checked: selectedRunIds.has(r.id) ? "" : null,
                  onchange: (e) => {
                    if (e.target.checked) selectedRunIds.add(r.id);
                    else selectedRunIds.delete(r.id);
                    renderRuns();
                  },
                })),
                el("td", {}, chip(r.status)),
                el("td", {}, runTitle(r)),
                el("td", { class: "mono" }, r.case_ids.length),
                el("td", { class: "mono" }, fmtTs(r.started_at, true)),
                el("td", { class: "mono" }, fmtDur(r.finished_at ? (new Date(r.finished_at) - new Date(r.started_at)) / 1000 : null)),
                el("td", { class: "mono" }, `${s.passed ?? 0} / ${s.failed ?? 0} / ${s.quarantined ?? 0}`),
                el("td", { class: "mono muted" }, (s.tokens ?? 0).toLocaleString()),
                el("td", { class: "muted" }, esc(r.env || "—")),
                el("td", {},
                  el("a", { href: "#/run/" + r.id, onclick: () => { location.hash = "#/run/" + r.id; } }, t("common.view")),
                  ["running", "pending"].includes(r.status)
                    ? el("a", { href: "#", style: "margin-left:10px;color:var(--fail)", onclick: async (e) => {
                        e.preventDefault();
                        try { await api(`/runs/${r.id}/cancel`, { method: "POST" }); renderRuns(); }
                        catch (err) { alert(t("common.err.cancel", err.message)); }
                      } }, t("common.cancel"))
                    : null,
                  el("a", { href: "#", style: "margin-left:10px;color:var(--fail);vertical-align:middle", title: t("run.del_title"), onclick: async (e) => {
                    e.preventDefault();
                    if (!confirm(t("run.confirm_del_one"))) return;
                    try {
                      await api(`/runs/${r.id}`, { method: "DELETE" });
                      selectedRunIds.delete(r.id);
                      renderRuns();
                    } catch (err) { alert(t("common.err.del", err.message)); }
                  } }, trashIcon())));
            })))
        : empty(t("run.no_runs")),
      makePager(runsResp))
  );
  if (anyActive) pollTimer = setInterval(() => { if (location.hash.startsWith("#/runs")) renderRuns(); }, 5000);
}

// 分页控件：每页条数 20/50/100 三档 + 上一页/下一页
function makePager(resp) {
  const totalPages = Math.max(1, Math.ceil(resp.total / resp.page_size));
  const sizeSel = el("select", {
    style: "width:auto;padding:4px 8px",
    onchange: () => { runsPageSize = Number(sizeSel.value); runsPage = 1; renderRuns(); },
  }, ...[20, 50, 100].map((n) => el("option", { value: n, selected: n === resp.page_size ? "" : null }, t("run.per_page", n))));
  sizeSel.value = resp.page_size;
  return el("div", { class: "pager" },
    sizeSel,
    el("button", { class: "btn sm", onclick: () => { runsPage = Math.max(1, runsPage - 1); renderRuns(); } }, t("run.prev")),
    el("span", { class: "mono muted" }, t("run.page_of", resp.page, totalPages)),
    el("button", { class: "btn sm", onclick: () => { runsPage = Math.min(totalPages, runsPage + 1); renderRuns(); } }, t("run.next")));
}

/* ================= 报告 ================= */

let selectedTaskId = null;

async function renderRun(runId) {
  stopPoll();
  view.innerHTML = "";
  let report;
  try { report = await api(`/runs/${runId}/report`); } catch (e) { view.append(el("div", { class: "panel" }, el("p", {}, t("rep.not_found", e.message)))); return; }
  const { run, tasks } = report;
  if (!selectedTaskId || !tasks.some((x) => x.task.id === selectedTaskId)) {
    selectedTaskId = tasks[0]?.task.id || null;
  }
  const TERMINAL = ["passed", "failed", "partial", "cancelled"];
  const active = !TERMINAL.includes(run.status);
  const s = run.stats || {};

  view.append(
    el("div", { class: "panel" },
      el("div", { style: "display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px" },
        el("div", {},
          chip(run.status),
          el("span", { class: "mono muted", style: "margin-left:12px" }, run.id.slice(0, 12)),
          el("span", { class: "muted", style: "margin-left:12px" }, esc(run.target_url)),
          el("span", { class: "muted", style: "margin-left:12px" }, `${s.passed ?? 0} / ${s.failed ?? 0} / ${s.quarantined ?? 0} · ${(s.tokens ?? 0).toLocaleString()} tokens`)),
        el("div", {},
          el("a", { class: "btn", href: "#/runs", onclick: () => { location.hash = "#/runs"; } }, t("common.back")),
          active
            ? el("button", { class: "btn danger", style: "margin-left:8px", onclick: async () => {
                try { await api(`/runs/${runId}/cancel`, { method: "POST" }); }
                catch (e) { alert(t("common.err.cancel", e.message)); }
                renderRun(runId);
              } }, t("run.cancel_exec"))
            : null,
          !active && ((s.failed ?? 0) + (s.quarantined ?? 0)) > 0
            ? el("button", { class: "btn primary", style: "margin-left:8px", onclick: async () => {
                try {
                  const r = await api(`/runs/${runId}/rerun-failed`, { method: "POST" });
                  selectedTaskId = null;
                  location.hash = "#/run/" + r.id;
                } catch (e) { alert(t("common.err.rerun", e.message)); }
              } }, t("run.rerun_failed", (s.failed ?? 0) + (s.quarantined ?? 0)))
            : null,
          renderAllureBtn(runId))),
    el("div", { class: "report-grid" },
      el("div", { class: "panel", style: "margin-bottom:0" },
        el("h3", {}, t("rep.task_list")),
        tasks.length
          ? el("div", { class: "task-list" }, ...tasks.map((tr) => {
              const x = tr.task;
              const n = el("div", { class: "task-item" + (x.id === selectedTaskId ? " active" : ""), onclick: () => { selectedTaskId = x.id; renderRun(runId); } },
                el("div", { class: "n" }, esc(x.case_name)),
                el("div", {}, chip(x.status), x.attempt > 1 ? el("span", { class: "mono muted", style: "margin-left:8px" }, t("run.attempt", x.attempt)) : null),
                x.error ? el("div", { class: "mono muted", style: "margin-top:6px;font-size:11.5px" }, esc(x.error.slice(0, 120))) : null);
              return n;
            }))
          : empty(t("rep.no_tasks"))),
      el("div", { class: "panel", style: "margin-bottom:0" }, renderTimeline(report, selectedTaskId))),
  ));

  if (active) {
    pollTimer = setInterval(() => { if (location.hash === "#/run/" + runId) renderRun(runId); }, 3000);
  }
}

function renderTimeline(report, taskId) {
  const tr = report.tasks.find((x) => x.task.id === taskId);
  const wrap = el("div", {});
  if (!tr) return wrap;
  const events = tr.events;
  wrap.append(el("h3", {}, t("rep.timeline_of", tr.task.case_name)));
  if (!events.length) { wrap.append(empty(tr.task.status === "queued" ? t("rep.no_events") : t("rep.no_events2"))); return wrap; }

  const tl = el("div", { class: "tl" });
  for (const ev of events) {
    const p = ev.payload || {};
    let cls = "", label = ev.type, detail = null, badgeNode = null, pre = null, img = null;

    if (ev.type === "session_start") {
      label = t("rep.session_start"); cls = "ok";
      detail = el("div", { class: "d muted" }, t("rep.mode", p.mode || "agentic", p.target_url || ""));
    } else if (ev.type === "llm_decision") {
      label = t("rep.llm_decision");
      badgeNode = badge(p.tool);
      detail = el("div", { class: "d" }, el("span", { class: "muted" }, t("rep.reason")), esc(p.reason || ""));
      pre = el("pre", {}, esc(displayJson(p.args || {})));
      if (p.prompt_tokens) detail.append(el("span", { class: "mono muted", style: "margin-left:8px" }, `↑${p.prompt_tokens} ↓${p.completion_tokens} tokens`));
    } else if (ev.type === "tool_call") {
      label = t("rep.action"); cls = p.ok ? "ok" : "fail";
      badgeNode = badge(p.tool);
      if (p.ok) {
        const detailJson = {};
        for (const [k, v] of Object.entries(p)) {
          if (k !== "reason") detailJson[k] = v;
        }
        detail = el("pre", {}, esc(displayJson(detailJson)));
      } else {
        detail = el("div", { class: "d", style: "color:var(--fail)" }, esc(displayJson(p.error || t("rep.fail"))));
      }
    } else if (ev.type === "screenshot") {
      label = t("rep.step_shot"); cls = "ok";
      if (ev.artifact) img = el("img", { src: "/artifacts/" + ev.artifact, loading: "lazy", alt: t("rep.step_shot") });
    } else if (ev.type === "assertion") {
      label = t("rep.assertion"); cls = p.ok ? "ok" : "fail";
      badgeNode = badge(p.ok ? t("rep.pass") : t("rep.fail"), p.ok ? "ok" : "err");
      detail = el("div", { class: "d" }, el("b", {}, `${p.type}: ${esc(p.target || "")}`), p.step ? el("span", { class: "muted" }, " " + t("rep.step_at", p.step)) : null, p.detail ? el("span", { class: "muted" }, " — " + esc(p.detail)) : "");
    } else if (ev.type === "heal_request") {
      label = t("rep.heal_request"); cls = "fail";
      detail = el("div", { class: "d" }, t("rep.heal_round", p.attempt) + esc(displayJson(p.failures || [])));
    } else if (ev.type === "heal_result") {
      label = t("rep.heal_result"); cls = p.ok ? "ok" : "fail";
      detail = el("div", { class: "d" }, p.ok ? t("rep.heal_ok") : t("rep.heal_no"));
    } else if (ev.type === "case_passed") {
      label = t("rep.case_passed"); cls = "ok";
      const u = p.usage || {};
      detail = el("div", { class: "d muted" }, t("rep.usage", p.assertions ?? 0, u.steps ?? 0, u.llm_calls ?? 0, u.heals ?? 0));
    } else if (ev.type === "case_failed") {
      label = t("rep.case_failed"); cls = "fail";
      detail = el("div", { class: "d", style: "color:var(--fail)" }, esc(p.error || ""));
    }

    const item = el("div", { class: "tl-item " + cls },
      el("div", { class: "t" }, label, badgeNode,
        el("span", { class: "mono muted", style: "margin-left:8px;font-weight:400" }, fmtTs(ev.created_at))));
    if (detail) item.append(detail);
    if (pre) item.append(pre);
    if (img) item.append(img);
    tl.append(item);
  }
  wrap.append(tl);

  if (tr.analysis) {
    const a = tr.analysis;
    wrap.append(
      el("div", { style: "margin-top:16px;padding:14px;border:1px solid var(--warn);border-radius:8px;background:var(--warn-soft)" },
        el("div", { style: "display:flex;align-items:center;gap:10px;margin-bottom:8px" },
          el("b", {}, t("rep.ai_attr")), badge(t(FAULT_KEY[a.category] || a.category), "err"),
          el("span", { class: "mono muted" }, t("rep.confidence", (a.confidence * 100).toFixed(0)))),
        el("div", { class: "d", style: "margin-bottom:8px" }, esc(a.root_cause)),
        a.defect_draft?.title
          ? el("div", { class: "d" },
              el("div", {}, el("b", {}, t("rep.defect")), esc(a.defect_draft.title)),
              a.defect_draft.steps ? el("div", { class: "muted", style: "font-size:12.5px;margin-top:4px" }, t("rep.reproduce"), esc(a.defect_draft.steps)) : null,
              a.defect_draft.expected ? el("div", { class: "muted", style: "font-size:12.5px" }, t("rep.expected"), esc(a.defect_draft.expected)) : null,
              a.defect_draft.actual ? el("div", { class: "muted", style: "font-size:12.5px" }, t("rep.actual"), esc(a.defect_draft.actual)) : null)
          : null));
  }
  return wrap;
}

/* ================= 配置 ================= */

async function renderSettings() {
  const s = await api("/settings");
  const url = el("input", { value: s.default_target_url || "", placeholder: t("cfg.placeholder") });
  const num = (v) => el("input", { type: "number", value: String(v), style: "width:120px" });
  const ma = num(s.max_attempts); ma.min = "1"; ma.max = "10";
  const ha = num(s.heal_attempts); ha.min = "0"; ha.max = "5";
  const ms = num(s.max_steps); ms.min = "3"; ms.max = "100";
  // checkbox 用属性存在性表示选中：el() 走 setAttribute，必须 "" : null（与 848/862 行同一惯例）
  const fa = el("input", { type: "checkbox", checked: s.failure_analysis ? "" : null, style: "margin-top:6px" });
  view.append(
    el("div", { class: "panel", style: "max-width:640px" },
      el("h3", {}, t("cfg.title")),
      field(t("cfg.default_url"), url, t("cfg.default_url_hint")),
      el("div", { style: "margin:18px 0 8px;font-weight:600" }, t("cfg.policy_title")),
      field(t("cfg.max_attempts"), ma, t("cfg.max_attempts_hint")),
      field(t("cfg.heal_attempts"), ha, t("cfg.heal_attempts_hint")),
      field(t("cfg.max_steps"), ms, t("cfg.max_steps_hint")),
      field(t("cfg.failure_analysis"), fa, t("cfg.failure_analysis_hint")),
      el("div", { class: "muted", style: "font-size:12px;margin-top:10px" }, t("cfg.policy_scope")),
      el("div", { style: "margin-top:14px" },
        el("button", {
          class: "btn primary",
          onclick: async () => {
            try {
              const body = { default_target_url: url.value.trim() };
              body.max_attempts = ma.value === "" ? null : parseInt(ma.value, 10);
              body.heal_attempts = ha.value === "" ? null : parseInt(ha.value, 10);
              body.max_steps = ms.value === "" ? null : parseInt(ms.value, 10);
              body.failure_analysis = fa.checked;
              const r = await api("/settings", { method: "PUT", body });
              defaultTargetUrl = r.default_target_url || defaultTargetUrl;
              ma.value = String(r.max_attempts); ha.value = String(r.heal_attempts);
              ms.value = String(r.max_steps); fa.checked = !!r.failure_analysis;
              alert(t("common.saved"));
            } catch (e) { alert(t("common.err.save", e.message)); }
          },
        }, t("common.save")),
        el("span", { class: "muted", style: "margin-left:10px;font-size:12px" },
          t("cfg.current", esc(s.default_target_url || t("cfg.unset"))))))
  );
}

/* ================= 语言切换 ================= */

qs("#lang-btn").addEventListener("click", () => {
  lang = lang === "zh" ? "en" : "zh";
  localStorage.setItem("easyrun-lang", lang);
  location.reload();
});

function updateLangBtn() {
  qs("#lang-btn").textContent = lang === "zh" ? "EN" : "中文";
}

/* ================= 启动 ================= */

updateLangBtn();
applyStaticI18n();
loadHealth();
loadAppSettings();
route();
