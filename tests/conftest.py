"""共享夹具：内存 SQLite、测试配置、应用工厂。"""

from __future__ import annotations

import pytest
import pytest_asyncio

from easyrun.config import Settings
from easyrun.db import create_engine_and_session, init_db
from easyrun.main import create_app


@pytest.fixture
def settings(tmp_path):
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        workers=0,
        artifact_dir=tmp_path / "artifacts",
        deepseek_api_key="test-key",
        screenshot_every_step=True,
        heal_attempts=2,
        max_steps_per_case=10,
        replay_step_delay_ms=0,  # 测试不等待，保持速度
    )


@pytest_asyncio.fixture
async def sf(settings):
    """session_factory：独立内存库。"""
    engine, factory = create_engine_and_session(settings.database_url)
    await init_db(engine)
    yield factory
    await engine.dispose()


@pytest.fixture
def app(tmp_path):
    """应用级夹具用文件库：后台调度器与请求并发访问，避免内存库单连接竞态。"""
    app_settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'app.db'}",
        workers=0,
        artifact_dir=tmp_path / "artifacts",
        deepseek_api_key="test-key",
        screenshot_every_step=True,
    )
    return create_app(app_settings)
