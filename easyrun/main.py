"""应用入口：FastAPI + 调度器 + Worker 池同进程运行（v1 部署形态）。

生产可拆分为多进程/多副本：调度器与 API 放一处，Worker 独立扩容
（WORKERS=0 且 REDIS_URL 启用时即为纯 API 节点）。
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from easyrun.api import api_router
from easyrun.config import Settings, get_settings, migrate_legacy_paths
from easyrun.db import create_engine_and_session, init_db
from easyrun.llm import DeepSeekClient
from easyrun.orchestrator import Orchestrator
from easyrun.queue import get_queue
from easyrun.worker import LockManager, Worker

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger("easyrun")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    migrate_legacy_paths(settings)
    artifact_dir = settings.resolved_artifact_dir
    artifact_dir.mkdir(parents=True, exist_ok=True)

    engine, session_factory = create_engine_and_session(settings.resolved_database_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await init_db(engine)
        queue = get_queue(settings)
        llm = DeepSeekClient(settings)
        locks = LockManager()
        orchestrator = Orchestrator(settings, session_factory, queue)

        app.state.settings = settings
        app.state.engine = engine
        app.state.sf = session_factory
        app.state.queue = queue
        app.state.llm = llm
        app.state.locks = locks
        app.state.orchestrator = orchestrator
        app.state.cancel_registry: set = set()

        tasks: list[asyncio.Task] = []
        tasks.append(asyncio.create_task(orchestrator.run_forever(), name="orchestrator"))
        for i in range(settings.workers):
            worker = Worker(
                f"w-{i + 1}", settings, session_factory, queue, locks, llm,
                cancel_registry=app.state.cancel_registry,
            )
            tasks.append(asyncio.create_task(worker.run_forever(), name=f"worker-{i + 1}"))
        logger.info(
            "平台启动：queue=%s workers=%s llm=%s",
            "memory" if settings.use_memory_queue else "redis",
            settings.workers,
            settings.deepseek_base_url,
        )
        try:
            yield
        finally:
            orchestrator.stop()
            for t in tasks:
                t.cancel()
            for t in tasks:
                try:
                    await t
                except asyncio.CancelledError:
                    pass
                except Exception:
                    pass
            await queue.close()
            await engine.dispose()

    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
    app.include_router(api_router)

    # 静态资源：Web 控制台 / 演示应用 / 执行工件（截图等）
    app.mount("/app", StaticFiles(directory=settings.web_dir, html=True), name="console")
    app.mount("/demo", StaticFiles(directory=settings.demo_dir, html=True), name="demo")
    app.mount("/artifacts", StaticFiles(directory=artifact_dir), name="artifacts")
    # Allure HTML 报告（由 allure CLI 生成后托管）
    allure_html_dir = artifact_dir / "allure-html"
    allure_html_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/allure-html", StaticFiles(directory=allure_html_dir, html=True), name="allure-html")

    @app.get("/", include_in_schema=False)
    async def index() -> RedirectResponse:
        return RedirectResponse("/app/")

    return app


app = create_app()


def serve() -> None:
    """uvicorn 启动入口（easyrun serve）。"""
    import uvicorn

    settings = get_settings()
    uvicorn.run("easyrun.main:app", host=settings.host, port=settings.port, reload=False)
