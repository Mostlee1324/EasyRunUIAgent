"""平台配置：环境变量（前缀 EASYRUN_）驱动，开发模式零外部依赖即可启动。

数据与代码分离：数据库、截图、Allure 输出等运行时数据统一放在 data/ 目录
（可用 EASYRUN_DATA_DIR 覆盖），代码目录保持纯净可移植。
"""

from __future__ import annotations

import os
import shutil
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="EASYRUN_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "EasyRun UI Agent"
    host: str = "127.0.0.1"
    port: int = 8001

    # ---- 数据目录（运行时数据与代码分离）----
    data_dir: Path = ROOT_DIR / "data"
    # 以下两项留空时自动落到 data_dir 下；显式设置优先
    database_url: str = ""
    artifact_dir: Path | None = None

    # ---- 队列 ----
    # 为空时使用进程内内存队列（单机开发）；多机部署必填 redis://host:6379/0
    redis_url: str = ""

    # ---- LLM（DeepSeek 官方 API，OpenAI 兼容协议，可替换为本地开源权重）----
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_chat_model: str = "deepseek-chat"
    deepseek_reasoner_model: str = "deepseek-reasoner"
    llm_timeout: float = 120.0
    llm_max_tokens: int = 4096
    llm_temperature: float = 0.2

    # ---- 执行 ----
    workers: int = 4                      # Worker 数量（并发 Agent 数）；纯 API 节点设 0
    task_timeout_seconds: int = 600       # 单任务执行上限
    max_attempts: int = 1                 # 失败自动重试次数上限（1 = 只执行一次，失败后用「重跑失败用例」手动重试）
    quarantine_threshold: int = 3         # 连续失败达到该值进入隔离区
    max_steps_per_case: int = 30          # 单用例 LLM 动作步数上限
    heal_attempts: int = 0                # 断言失败后的自愈重试轮数（0 = 不自愈重试，失败即止，手动 rerun）
    max_noop_repeats: int = 1             # 同一动作允许执行次数（1 = 每个动作只执行一次；重复请求时跳过并提示执行下一步）
    max_skipped_repeats: int = 2          # 同一动作被重复请求时最多跳过的次数（超过则终止，防 LLM 空转）
    lock_wait_seconds: int = 300          # 资源锁等待上限

    # ---- 浏览器与工件 ----
    browser_headless: bool = True
    screenshot_every_step: bool = True
    replay_step_delay_ms: int = 3000    # 固化回放的动作间延迟（等待页面动态渲染，如日期选项卡的链接）

    # ---- Web ----
    web_dir: Path = ROOT_DIR / "web"
    demo_dir: Path = ROOT_DIR / "demo"

    # ---- Allure（可选）----
    # 为空时自动探测：PATH 中的 allure → 项目内 tools/bin/allure
    allure_bin: str = ""

    # ---- 解析后的路径（显式配置优先，否则落到 data_dir）----

    @property
    def resolved_database_url(self) -> str:
        return self.database_url or f"sqlite+aiosqlite:///{self.data_dir / 'easyrun.db'}"

    @property
    def resolved_artifact_dir(self) -> Path:
        return self.artifact_dir or self.data_dir / "artifacts"

    @property
    def resolved_api_key(self) -> str:
        """DEEPSEEK_API_KEY 与 EASYRUN_DEEPSEEK_API_KEY 二选一。"""
        return self.deepseek_api_key or os.environ.get("DEEPSEEK_API_KEY", "")

    @property
    def use_memory_queue(self) -> bool:
        return not self.redis_url

    def resolve_allure_bin(self) -> str | None:
        """定位 allure CLI：显式配置 > PATH > 项目内 tools/bin/allure。"""
        candidates = [self.allure_bin] if self.allure_bin else [
            shutil.which("allure") or "",
            str(ROOT_DIR / "tools" / "bin" / "allure"),
        ]
        for c in candidates:
            if c and Path(c).exists():
                return c
        return None


def migrate_legacy_paths(settings: Settings) -> None:
    """v0.1 → v0.2 数据目录迁移：根目录的 easyrun.db / artifacts 移入 data/。

    仅在用户未显式配置（使用默认路径）且新位置不存在时执行，幂等。
    """
    if settings.database_url or settings.artifact_dir is not None:
        return
    data = settings.data_dir
    data.mkdir(parents=True, exist_ok=True)
    legacy_db = ROOT_DIR / "easyrun.db"
    legacy_artifacts = ROOT_DIR / "artifacts"
    if legacy_db.exists() and not (data / "easyrun.db").exists():
        shutil.move(str(legacy_db), str(data / "easyrun.db"))
    if legacy_artifacts.is_dir() and not (data / "artifacts").exists():
        shutil.move(str(legacy_artifacts), str(data / "artifacts"))


@lru_cache
def get_settings() -> Settings:
    return Settings()
