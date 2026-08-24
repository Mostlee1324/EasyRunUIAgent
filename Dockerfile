FROM python:3.12-slim

WORKDIR /srv
COPY pyproject.toml README.md ./
COPY scripts ./scripts

# Allure CLI + JRE 打进镜像：复用 scripts/setup-allure.sh（容器内 uname 为 Linux，
# 自动下载 Linux x64/aarch64 JRE），与本地开发同一套 tools/ 布局，多机各节点一致。
# tools/ 为机器专属二进制，不入库、不进构建上下文（.dockerignore）。
# 放在代码层之前：代码变更不会使本层缓存失效。
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && sh scripts/setup-allure.sh \
    && apt-get purge -y --auto-remove curl \
    && rm -rf /var/lib/apt/lists/*

COPY easyrun ./easyrun
COPY web ./web
COPY demo ./demo

# 生产依赖：postgres + redis；浏览器内核打进镜像
# 必须 editable 安装：easyrun 的 ROOT_DIR 按代码位置解析 web/demo 等路径，
# 非 editable 安装会指到 site-packages 导致 StaticFiles 找不到目录。
# 内核路径需显式指定：运行时 /srv/data 被卷挂载，镜像层的内核会被遮住，
# 且不指定时 easyrun 会把内核路径默认到 <ROOT>/data/browsers（空卷）。
RUN pip install --no-cache-dir -e ".[prod]" \
    && playwright install --with-deps chromium

ENV EASYRUN_HOST=0.0.0.0 EASYRUN_PORT=8001 EASYRUN_DATA_DIR=/srv/data \
    PLAYWRIGHT_BROWSERS_PATH=/root/.cache/ms-playwright
EXPOSE 8001

# 默认启动 API+调度器；Worker 服务用 command: easyrun worker 覆盖
CMD ["easyrun", "serve"]
