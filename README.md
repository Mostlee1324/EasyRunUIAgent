# EasyRun UI Agent

> 简体中文 | [English](README.en.md)

基于 AI Agent 的 UI 自动化测试平台：用例以自然语言描述，由多个测试 Agent 并行执行，
每一步都留痕，报告实时可看、失败可归因。

- **LLM**：DeepSeek 官方 API（`deepseek-chat` 动作决策 / `deepseek-reasoner` 拆解与归因，分级路由）
- **其余组件**：全部开源、本地部署（Playwright / FastAPI / Redis / PostgreSQL / MinIO 等）

> 架构与选型详见 [docs/platform-design.html](docs/platform-design.html)（浏览器打开）。

## 快速开始（新机器一键初始化）

```bash
sh scripts/bootstrap.sh          # Linux / macOS：自动 venv / 依赖 / 浏览器 / Allure / .env / 环境检查
```

Windows 10/11 用 PowerShell 版：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1
```

三个平台（Linux / macOS / Windows）均可部署，且可混合组集群（共享 Redis + PostgreSQL）。

bootstrap 会按平台自动处理：macOS 12 及更早锁定 playwright 1.50（新版 chromium 不支持旧系统）、
Allure CLI+JRE 下载到项目内 `tools/`（不碰系统）、生成 `.env` 模板。

然后编辑 `.env` 填入 `DEEPSEEK_API_KEY`，启动：

```bash
source .venv/bin/activate
easyrun serve                    # API + 调度器 + Worker 池（单机形态）
```

打开控制台：<http://127.0.0.1:8001/app/>（API 文档 <http://127.0.0.1:8001/docs>）

<details><summary>手工安装（等价步骤）</summary>

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium
sh scripts/setup-allure.sh       # 可选：项目内 Allure
cp .env.example .env             # 填入 DEEPSEEK_API_KEY
easyrun serve
```

</details>

### 端到端演示（5 分钟）

平台启动后，另开终端执行：

```bash
source .venv/bin/activate
python scripts/demo.py
```

脚本会创建「商城下单」用例（登录 → 加购 → 结算 → 断言订单编号），提交给 Agent 执行，
实时打印决策 / 动作 / 断言 / 失败归因，并在浏览器控制台留下完整时间轴报告。

## 部署指南

三种形态按规模递增，互相兼容（同一套代码、同一套配置）。

### 形态三：单机开发（零外部依赖，默认形态）

适合本机开发调试：SQLite + 进程内队列 + 内置 Worker。

```bash
# 1. 初始化（新机器执行一次）：venv / 依赖 / 浏览器内核 / Allure / .env
sh scripts/bootstrap.sh

# 2. 配置 LLM：编辑 .env 填入密钥（或 export DEEPSEEK_API_KEY）
# 3. 启动
source .venv/bin/activate
easyrun serve            # http://127.0.0.1:8001/app/
# 4. 验证（另开终端）
python scripts/demo.py
```

> ⚠️ 内存队列仅限**单进程**：`easyrun serve` 自带 Worker 没问题；
> 但另开 `easyrun worker` 进程无法共享该队列（各进程队列独立），多进程必须配 Redis。

### 形态一：单机 Docker（一条命令，接近生产形态）

前置：Docker（Linux 主机或 Docker Desktop）。

```bash
# 1. 准备密钥（compose 从环境变量读取）
export DEEPSEEK_API_KEY=sk-xxx

# 2. 构建并启动（首次构建约 3-5 分钟：镜像内含 chromium）
docker compose up -d --build

# 3. 查看状态
docker compose ps
curl http://127.0.0.1:8001/api/health
```

| 服务 | 作用 | 说明 |
|---|---|---|
| `api` | 控制面：REST API / 调度器 / Web 控制台 | `EASYRUN_WORKERS=0`，不跑浏览器 |
| `worker` | 执行面：Agent + chromium | `EASYRUN_WORKERS=4` |
| `redis` / `postgres` | 可靠队列 / 元数据库 | 带健康检查；数据落在项目根目录 `./data/` |

镜像构建时已内置 **Allure CLI + JRE**（`/srv/tools/bin/allure`，与本地 `tools/` 同一套布局），
无需任何额外安装即可生成 Allure 报告；全部运行时数据（截图 / Allure 结果与 HTML / PostgreSQL 数据）
绑定挂载到项目根目录的 `./data/`：

| 容器内路径 | 宿主机路径 | 内容 |
|---|---|---|
| `/srv/data/artifacts/allure/<run_id>` | `./data/artifacts/allure/<run_id>` | Allure 原始结果（allure-results） |
| `/srv/data/artifacts/allure-html/<run_id>` | `./data/artifacts/allure-html/<run_id>` | 生成的 Allure 静态 HTML 报告 |
| `/var/lib/postgresql/data` | `./data/postgres/` | PostgreSQL 数据 |

报告生成与查看：控制台报告页点「生成 Allure 报告」，或 `POST /api/runs/{id}/allure`，
然后访问 `http://127.0.0.1:8001/allure-html/<run_id>/`（生成后的静态文件就在宿主机
`./data/artifacts/allure-html/<run_id>/`，可直接打包归档）。

常用运维：

```bash
docker compose logs -f worker        # 看执行日志
docker compose up -d --build worker  # 代码更新后重建 worker
docker compose down                  # 停止（数据在 ./data/，不随 down 删除）
rm -rf data                          # 清空全部运行时数据（谨慎，down -v 不再适用）
```

### 同机多 Worker（控制器 ×1 + 执行节点 ×N）

「单机 Docker」默认只起 1 个 worker 容器（4 个并发 Agent）。一台机器资源充足时，
可以把执行面横向扩展到 N 个 worker 容器，控制面仍是 1 个 `api` 容器：

```
        ┌──────────────────────────────────────────────────┐
        │            同一台机器（docker compose 一套栈）        │
        │                                                  │
        │  api ×1（控制节点：API / 调度器 / 控制台，不跑浏览器）    │
        │    │          任务入队（Redis）                     │
        │    ▼              ▼              ▼                │
        │  worker-1       worker-2       worker-3           │
        │  （执行节点，每容器 4 个并发 Agent）                    │
        └──────────────────────────────────────────────────┘
```

**配置**：无需改任何代码——`docker-compose.yml` 用 YAML 锚点（`&common`）保证
控制节点与全部执行节点拿到同一份连接配置，天然满足多 Worker 的两个硬性前提：

| 配置 | 取值 | 为什么 |
|---|---|---|
| `EASYRUN_REDIS_URL` | `redis://redis:6379/0` | 所有节点连**同一个队列**，任务才分发得出去；不配则各进程内存队列互不相通 |
| `EASYRUN_DATABASE_URL` | `postgresql+asyncpg://easyrun:easyrun@postgres:5432/easyrun` | 所有节点读写**同一个元数据库**（任务/事件/报告） |
| `EASYRUN_WORKERS` | api=0 / worker=4 | 控制节点不跑浏览器（0）；执行节点按资源设并发 Agent 数 |
| `EASYRUN_DATA_DIR` | `/srv/data`（绑定挂载项目根目录 `./data`） | 所有节点共享工件目录：worker 写截图/Allure，控制台才能预览任意节点的产物 |
| `EASYRUN_ALLURE_BIN` | 不设（自动探测） | 探测顺序：显式配置 → PATH → `<项目根>/tools/bin/allure`；Docker 镜像已内置（容器内即 `/srv/tools/bin/allure`），**无需配置** |
| `EASYRUN_BROWSER_HEADLESS` | `true` | 容器内无显示器，必须无头 |
| `EASYRUN_HOST` / `EASYRUN_PORT` | `0.0.0.0` / `8001` | Dockerfile 内置默认；只有 api 对外发布 8001 |

浏览器内核无需配置：构建镜像时 `playwright install --with-deps chromium` 已打进镜像。

**步骤**：

```bash
export DEEPSEEK_API_KEY=sk-xxx
docker compose build                     # 首次 3-5 分钟
docker compose up -d --scale worker=3    # 控制节点 ×1 + 执行节点 ×3
docker compose ps                        # 应看到 api、worker×3、redis、postgres 全部 running
curl http://127.0.0.1:8001/api/health
```

> `/api/health` 的 `workers` 显示的是 **api 容器自身**的 Worker 数（0），
> 不代表执行能力——执行在 worker 容器里，以 `docker compose logs worker` 为准。

**验证并发**：控制台提交一个多用例计划，`docker compose logs -f worker` 里应同时
出现多个容器（`worker-1` / `worker-2` / …）的执行日志。

**扩缩容**（在线，无需重启）：

```bash
docker compose up -d --scale worker=5    # 扩容到 5 个容器 = 20 并发 Agent
docker compose up -d --scale worker=1    # 缩容，多余容器自动停止
```

> ⚠️ `--scale` 只能用于 worker：api 发布了 8001 端口，多副本会端口冲突；redis/postgres 单副本即可。

**容量估算**（1 个并发 Agent ≈ 1 个 chromium 实例 ≈ 400-600MB 内存）：

| 机器内存 | 建议 | 并发 Agent |
|---|---|---|
| 8 GB | `--scale worker=2` | 8 |
| 16 GB | `--scale worker=4` | 16 |
| 32 GB | `--scale worker=8` | 32 |

**调整每容器并发数**（默认 4）：加 `docker-compose.override.yml`（compose 自动合并，不改主文件）：

```yaml
services:
  worker:
    environment:
      EASYRUN_WORKERS: "2"               # 每容器 2 个并发 Agent
```

然后 `docker compose up -d --scale worker=6` = 12 并发 Agent。

### 形态二：多机集群（水平扩容）

**架构**：1 个控制节点（API+调度器）+ N 个执行节点（Worker）+ 共享基础设施（Redis/PostgreSQL/工件存储）。

```
                    ┌──────────────┐
   用户/CI ────────▶│  控制节点 ×1  │  easyrun serve (WORKERS=0)
                    │  API+调度器+  │
                    │  Web 控制台   │
                    └──────┬───────┘
                           │ 任务入队 / 状态落库
              ┌────────────┼────────────┐
              ▼            ▼            ▼
        ┌──────────┐ ┌──────────┐ ┌──────────┐
        │执行节点 A │ │执行节点 B │ │执行节点 C │  easyrun worker (WORKERS=N)
        │chromium  │ │chromium  │ │chromium  │
        └──────────┘ └──────────┘ └──────────┘
              └────── 共享：Redis 队列 / PostgreSQL / 工件存储 ──────┘
```

> ⚠️ 多机部署**不是**只在控制节点上执行命令：每台执行机都要独立完成部署
> （拷贝代码 → bootstrap → 配 `.env` → 启动）。控制节点无法远程下发部署；
> 执行节点连上共享 Redis 即自动接入（无中心注册表，加节点无需控制节点审批）。
> 执行机需要本机浏览器内核（bootstrap 自动下载），这是必须逐台部署的根本原因。

**第 1 步：基础设施**（一台机器，或复用现有 Redis/PG）

```bash
# 只起 redis + postgres：
docker compose up -d redis postgres
# 记下地址：redis://<此机IP>:6379/0
#           postgresql+asyncpg://easyrun:easyrun@<此机IP>:5432/easyrun
```

**第 2 步：控制节点**

```bash
sh scripts/bootstrap.sh                          # 与开发一致
cat >> .env <<'EOF'
EASYRUN_REDIS_URL=redis://<基础设施IP>:6379/0
EASYRUN_DATABASE_URL=postgresql+asyncpg://easyrun:easyrun@<基础设施IP>:5432/easyrun
EASYRUN_WORKERS=0                                # 控制节点不跑浏览器
EOF
easyrun serve
```

**第 3 步：执行节点 ×N**（每台机器重复）

```bash
sh scripts/bootstrap.sh                          # 每台执行机都要装依赖+浏览器
cat >> .env <<'EOF'
EASYRUN_REDIS_URL=redis://<基础设施IP>:6379/0
EASYRUN_DATABASE_URL=postgresql+asyncpg://easyrun:easyrun@<基础设施IP>:5432/easyrun
EASYRUN_WORKERS=4                                # 按机器内存调：1 个 Agent ≈ 1 个浏览器实例
EOF
easyrun worker
```

**执行节点用 Docker（可选）**：每台执行机只跑 worker 容器，连接中心 Redis/PG：

```bash
# 用 override 指向中心基础设施（docker-compose.override.yml）：
#   services:
#     worker:
#       environment:
#         EASYRUN_REDIS_URL: redis://<基础设施IP>:6379/0
#         EASYRUN_DATABASE_URL: postgresql+asyncpg://easyrun:easyrun@<基础设施IP>:5432/easyrun
docker compose up -d --no-deps --build worker
```

> `--no-deps` 必须加：否则 compose 会连带把依赖的 redis/postgres 也在这台机器上各起一套。
> Docker 执行节点镜像已内置 Allure CLI + JRE（多机各节点一致），工件落在该机项目根目录
> `./data/artifacts/`（compose 绑定挂载 `./data:/srv/data`，无需配置）。

**第 4 步（重要）：共享工件存储 —— 数据路径配置详解**

先弄清楚**谁写什么、谁读什么**，再决定路径怎么配：

| 节点 | 写入（本地 `data/`） | 读取 |
|---|---|---|
| 控制节点（api） | Allure 原始结果 `data/artifacts/allure/<run_id>/`、Allure HTML `data/artifacts/allure-html/<run_id>/`（点「生成 Allure 报告」时由控制节点生成） | 全部节点的截图与基线：控制台预览、生成 Allure 时打包附件 |
| 执行节点（worker） | 步骤截图 `data/artifacts/sessions/<session_id>/s_*.png`、视觉基线 `data/artifacts/baselines/` | 基本只写不读 |

**结论**：执行节点各自写、控制节点统一读——控制节点必须能读到每台执行节点的
`data/artifacts/`，否则跨节点截图无法预览、Allure 报告附件缺失。

**各节点数据路径默认值**（不改任何配置时）：

| 节点形态 | 宿主机路径 | 容器内路径 | 需要配置 |
|---|---|---|---|
| 裸机（控制/执行） | `<项目根目录>/data` | — | 无（`EASYRUN_DATA_DIR` 默认值就是它） |
| Docker（控制/执行） | `<项目根目录>/data` | `/srv/data` | 无（compose 已绑定挂载 `./data:/srv/data`） |

> 想改用其他目录：裸机设 `EASYRUN_DATA_DIR=<目录>`；Docker 在
> `docker-compose.override.yml` 里把 volume 改为 `<目录>:/srv/data`
> （或同时覆盖 `EASYRUN_DATA_DIR` 环境变量，两者指向同一目录即可）。

---

**方案 A（推荐）：共享路径 = 控制节点项目根目录的 `data/`**

控制节点自己当 NFS 服务器，把它的 `<项目根目录>/data` 导出给所有执行节点。
所有节点的数据都落在各自项目的 `data/` 下，路径直观、配置零改动。

**A1. 控制节点：导出 `data/`（NFS 服务器，Linux）**

```bash
sudo apt install -y nfs-kernel-server          # Debian/Ubuntu

# 追加导出规则：允许执行节点网段读写（替换为实际网段；也可用 * 放开全部）
echo '<项目根目录>/data 192.168.1.0/24(rw,sync,no_subtree_check,no_root_squash)' | sudo tee -a /etc/exports

sudo exportfs -ra                              # 重载导出表
sudo systemctl enable --now nfs-server         # 开机自启
showmount -e 127.0.0.1                         # 应看到刚导出的路径
```

导出选项说明：

| 选项 | 作用 |
|---|---|
| `rw` | 允许执行节点写入 |
| `sync` | 写请求落盘后应答（数据一致性） |
| `no_subtree_check` | 提高挂载稳定性 |
| `no_root_squash` | **关键**：Docker 容器以 root 写共享目录，不加此选项 root 会被压成 `nobody`，容器写入全部 Permission denied |

防火墙（启用了 ufw 时）：`sudo ufw allow from <执行节点网段> to any port nfs`。

控制节点为 macOS 时（NFS 服务器）：

```bash
sudo nfsd enable
sudo sh -c 'echo "<项目根目录>/data -network 192.168.1.0 -mask 255.255.255.0 -maproot=root:wheel" >> /etc/exports'
sudo nfsd update
```

控制节点自身**零配置**：本机进程直接读写本地磁盘（Docker 部署时 compose 已绑定挂载
`./data`，读写同样是本机磁盘，不走 NFS）。

**A2. 每台执行节点：把控制节点的 `data/` 挂到本机项目根目录**

```bash
sudo apt install -y nfs-common                  # NFS 客户端（Debian/Ubuntu）
sudo mkdir -p <项目根目录>/data

# 挂载：<控制节点导出的 data> → <本机项目根目录>/data
sudo mount -t nfs <控制节点IP>:<控制节点项目根目录>/data <项目根目录>/data

# 开机自动挂载（nofail：NFS 暂时不可用时不影响开机）
echo '<控制节点IP>:<控制节点项目根目录>/data <项目根目录>/data nfs defaults,nofail 0 0' | sudo tee -a /etc/fstab
```

挂好之后，**执行节点不需要改任何配置**：

- 裸机执行节点：`EASYRUN_DATA_DIR` 默认就是 `<项目根目录>/data`，现在它已是 NFS 挂载点；
- Docker 执行节点：compose 的 `./data:/srv/data` 自动指向该 NFS 挂载点。

> ⚠️ 顺序很重要：**先挂载 NFS，再 `docker compose up`**（或挂载后
> `docker compose restart worker`）。容器的绑定挂载在启动时锁定宿主机目录，
> 容器运行后再挂 NFS，容器看到的仍是旧的本地目录。

**A3. 验证（三步）**

```bash
# ① 双向可见：执行节点能看到控制节点的文件，写入也能回到控制节点
ls <项目根目录>/data/artifacts/
touch <项目根目录>/data/nfs-check && ls <控制节点项目根目录>/data/nfs-check && rm <项目根目录>/data/nfs-check

# ② 跨节点预览：控制台提交一个多用例计划，任务分布到不同执行节点后，
#    控制台报告页应能预览所有截图（截图实际写在工作节点，经 NFS 回到控制节点）

# ③ Allure 一致：点「生成 Allure 报告」后，控制节点与各执行节点的
#    data/artifacts/allure-html/<run_id>/ 内容应完全一致
```

---

**方案 B：独立共享存储（NFS/S3 类挂载到任意位置）**

不想导出控制节点的目录（或共享存储是独立 NAS）时，把共享挂到任意位置并显式配置：

```bash
# 每台机器（含控制节点）：
sudo mkdir -p /mnt/easyrun-share
sudo mount -t nfs <NFS服务器>:/easyrun-share /mnt/easyrun-share
# 写入 /etc/fstab（同上，加 nofail）
```

裸机节点（含控制节点）`.env`：

```
EASYRUN_DATA_DIR=/mnt/easyrun-share
```

Docker 节点用 `docker-compose.override.yml`（compose 自动合并，不改主文件）：

```yaml
services:
  api:      # 控制节点
    volumes:
      - /mnt/easyrun-share:/srv/data
  worker:   # 执行节点
    volumes:
      - /mnt/easyrun-share:/srv/data
```

> ⚠️ **控制节点也要挂同一共享**：生成 Allure 报告的是控制节点，它必须从共享目录
> 读得到 worker 截图，报告附件才完整。

---

**不共享时的行为边界**

不挂共享存储也能跑（执行不受影响），但：

- 控制台只能预览**控制节点自己 `data/` 里**的工件，其他节点产出的截图无法预览；
- 生成 Allure 报告时，非控制节点产出的截图附件缺失（报告本身照常生成）；
- 补救：把共享挂好之后，重新点一次「生成 Allure 报告」即可完整重打包。

**权限与常见坑速查**

| 现象 | 原因 | 处理 |
|---|---|---|
| 容器写共享目录报 Permission denied | 导出未加 `no_root_squash`（容器以 root 写） | exports 加 `no_root_squash` 后 `sudo exportfs -ra` |
| 裸机执行节点写失败 | 各机用户 uid 不一致（NFS 按 uid 鉴权） | 统一各机用户 uid，或导出加 `all_squash,anonuid=<uid>` |
| 重启后执行节点丢失共享 | 未写 /etc/fstab | 补 fstab 条目（加 `nofail`） |
| 容器里看不到 NFS 内容 | 先起容器后挂 NFS | 挂载后 `docker compose restart` |
| 共享目录里出现 postgres 数据 | `data/` 整树被导出，含 `data/postgres/` | 无碍：postgres 只在基础设施机本机访问本地磁盘；**勿**在多台机器同时启动指向同一目录的 postgres |

**扩容与运维**

```bash
# 扩容 = 新机器执行「第 3 步」即可，节点注册无需控制节点审批
# 节点下线：直接停进程/关机 —— 崩溃任务由调度器超时回收重新入队
# 观察：GET /api/health（控制节点）；easyrun health（任意节点）
# 滚动升级：逐台停 worker → 拉代码 → bootstrap → 起 worker；最后升级控制节点
```

### 配置优先级

`Web 配置页（platform_setting 表，多机共享，保存即生效）` > `命令行/环境变量` > `.env 文件` > `代码默认值`。
其中仅「默认执行目标地址」与「执行策略」（下表标注 ⚙ 的项）支持在控制台配置页运行时覆盖，其余配置见下表。

#### 运行时执行策略（控制台「配置」页）

| 项 | 范围 | 默认 | 说明 |
|---|---|---|---|
| 失败重跑次数 | 1-10 | 1（= 不重跑） | 失败后整用例重跑上限；每次重跑都是全新执行（≤30 次 LLM 调用） |
| 断言自愈轮数 | 0-5 | 0（= 不自愈） | 断言失败后 LLM 自愈重试轮数；每轮 ≤6 次 LLM 调用 |
| 单用例最大动作步数 | 3-100 | 30 | 每步 1 次 LLM 调用，**收紧此项最直接省 token** |
| 失败归因 | 开/关 | 开 | 关闭后失败任务不再自动调 deepseek-reasoner 归因（省 token）；报告页将没有根因分析与缺陷草稿 |

- 存储于共享数据库（`platform_setting` 表），**多机一致**：调度器每 2 秒重读、Worker 每个任务开始时读取，保存即对新任务/重试生效，正在执行的任务不受影响。
- 输入框置空保存 = 清除覆盖，回落环境变量/代码默认值。
- 配置页键名 `max_steps` 对应环境变量 `EASYRUN_MAX_STEPS_PER_CASE`。

## 配置项（环境变量，前缀 `EASYRUN_`）

| 变量 | 默认 | 说明 |
|---|---|---|
| `EASYRUN_DATA_DIR` | `./data` | 运行时数据（数据库/截图/Allure/**浏览器内核**），与代码分离；多机共享配置详见「形态二·第 4 步」 |
| `EASYRUN_DATABASE_URL` | `data/easyrun.db`（SQLite） | 留空自动落到数据目录；生产用 `postgresql+asyncpg://user:pass@host/db` |
| `EASYRUN_REDIS_URL` | 空（内存队列，仅单进程） | 多机/多进程必填 `redis://host:6379/0` |
| `EASYRUN_WORKERS` | `4` | 并发 Agent 数（扩容单元 = 浏览器实例）；纯 API 节点设 `0` |
| `EASYRUN_TASK_TIMEOUT_SECONDS` | `600` | 单任务执行上限 |
| `EASYRUN_MAX_ATTEMPTS` ⚙ | `1` | 失败自动重试次数上限（1 = 只执行一次，失败后用报告页「重跑失败用例」手动重试）；可在配置页运行时修改（1-10） |
| `EASYRUN_HEAL_ATTEMPTS` ⚙ | `0` | 断言失败后的自愈重试轮数（0 = 不自愈重试，失败即止）；可在配置页运行时修改（0-5） |
| `EASYRUN_QUARANTINE_THRESHOLD` | `3` | 连续失败达到该值进入隔离区 |
| `EASYRUN_MAX_STEPS_PER_CASE` ⚙ | `30` | 单用例 LLM 动作步数上限；可在配置页运行时修改（3-100，页面键名 `max_steps`） |
| `EASYRUN_MAX_NOOP_REPEATS` | `1` | 同一动作允许执行次数（1 = 每个动作只执行一次；重复请求时跳过并提示执行下一步，不判断页面是否变化） |
| `EASYRUN_MAX_SKIPPED_REPEATS` | `2` | 同一动作被重复请求时最多跳过的次数（超过则终止，防 LLM 空转） |
| `EASYRUN_BROWSER_HEADLESS` | `true` | 浏览器无头模式 |
| `EASYRUN_REPLAY_STEP_DELAY_MS` | `3000` | 固化回放的动作间延迟（等待页面动态渲染，如点日期后出现的新闻链接） |
| `EASYRUN_ALLURE_BIN` | 自动探测 | allure CLI 路径（默认依次找 PATH → `tools/bin/allure`） |
| `PLAYWRIGHT_BROWSERS_PATH` | `data/browsers` | 浏览器内核目录（平台自动注入，随项目迁移；一般无需配置） |
| `DEEPSEEK_API_KEY` | — | DeepSeek API Key（或 `EASYRUN_DEEPSEEK_API_KEY`） |
| `EASYRUN_DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | OpenAI 兼容端点，可指向本地 vLLM/Ollama |

## 编写用例指南

1. **步骤写「做什么」，不写「怎么点」**——Agent 负责把自然语言翻译成具体操作（找元素、点击、等待）。描述越明确越稳：写「输入用户名 demo、密码 123456」比写「登录」好。每个用例可设置**默认访问网址**，运行时仍可临时修改。
2. **断言是唯一的事实裁判**——步骤写得再对，断言不过用例就是失败。每个用例至少配一条断言，覆盖业务结果（订单编号出现、跳转 URL、错误提示文案）。
   **不会写断言？用自然语言**：在用例表单的断言区输入「页面出现订单编号；跳转到结算页；列表有 3 个商品；订单金额大于 100」，点 **「AI 生成断言」** 自动转换（LLM 结构化提取 + 确定性校验，生成后仍可手工调整）。
   断言共 9 类：`text_contains` / `url_contains` / `element_exists` / `element_count` / `element_text` / `text_in_view`（屏幕可见文本） / **`text_near_top`（位置校验：文本出现在窗口上方区域，target=文本，expected 可选上方比例阈值默认 0.4）** / **`value_compare`（标签后数值与期望值比较，如「订单金额」`>= 100`、「已分析」`> 0`；支持 `<span>已分析: <strong>2363</strong> 条</span>` 与相邻兄弟元素两种形态）** / `visual`（视觉比对）。
   **步骤后断言**：断言可绑定步骤序号（表单中每行断言填「步骤序号」）——探索模式下 Agent 每完成一步调用 `case_step_done` 标记，平台在该步骤动作后**立即**执行绑定断言（0 token 的确定性校验，失败即止：有自愈配置先自愈，否则用例失败）；Agent 忘标记直接结束时，收尾兜底按步骤序补跑所有未执行的绑定断言，再接无绑定断言。固化回放同样在标记点执行（标记随固化动作保存）；导出代码时绑定断言就地生成在对应动作之后。

   **步骤序号怎么对应**：断言填的序号 = 用例「步骤」列表的行号（从 1 开始，每行一步）。规则：

   - 一个步骤可绑多条断言；一条断言只绑一个序号。
   - 序号是**步骤行号，不是动作数**——一个步骤可能对应多个动作（找元素 + 点击 + 等待），动作由 Agent 自主决策。
   - 提示词中步骤带编号列出，绑定断言的步骤行会追加「完成本步骤后调用 `case_step_done(step=N)` 触发绑定断言」提示。
   - Agent 漏标记、或序号超出步骤数：断言**不会丢**，收尾兜底按序号顺序补跑（执行时机退化为「结束时」，报告仍显示「步骤 N」标签）。
   - 不填序号 = 全部步骤完成后统一执行（传统行为）。
   - ⚠️ 增删步骤行后序号**不会自动跟随**，需手动核对断言行的序号。

   示例（断言「页面出现订单编号」填步骤序号 4）：

   | 步骤 | 绑定断言 | 执行时机 |
   |---|---|---|
   | 1. 打开商城首页 | `url_contains` /home（序号 1） | 步骤 1 动作完成后立即校验 |
   | 2. 搜索机械键盘 | `element_count` 搜索结果 = 12（序号 2） | 步骤 2 动作完成后立即校验 |
   | 3. 点击第一个搜索结果 | （无） | — |
   | 4. 加入购物车并结算 | `text_contains` 订单编号（序号 4） | 步骤 4 动作完成后立即校验 |
   | — | `value_compare` 订单金额 > 100（不填） | 全部步骤完成后统一校验 |
3. **一条用例一个业务场景**——步骤别贪多（建议 ≤10 步），失败时归因更准；多场景拆多条，用「计划」批量跑。

**探索一次，长期省钱**：探索模式每步消耗 LLM token（约 0.5~1.5k/步），只用于发现路径。
探索通过后平台自动记录动作，两条免 token 路径：
- **固化回放**：用例行点「固化」→ 之后每次执行 0 token（依赖平台）；
- **导出代码**：用例行点「导出代码」→ 生成独立 Playwright 脚本（`get_by_text` 语义定位器 + 断言），
  脱离平台也能跑，可提交到测试代码库随 CI 执行——**用例从此就是自动化代码**。

## 平台能力对照（设计文档 → 实现）

| 设计 | 实现 |
|---|---|
| 多 Agent 并行执行 | Worker 池（`EASYRUN_WORKERS` 个 Agent 并发消费队列） |
| Master-Worker | `orchestrator.py`（拆解 / 重试 / watchdog / quarantine / 收口） |
| 观察→决策→行动→校验 | `agent.py` JSON 动作协议 + Playwright 索引快照 |
| 确定性断言 | `assertions.py`（6 类断言，含视觉比对） |
| locator 自愈 | 断言失败 → LLM 自愈重定位 → 元素库沉淀（`/api/locators`） |
| 固化模式 | 探索通过自动记录动作 → `/cases/{id}/cure` 启用确定性回放（不耗 LLM） |
| 导出自动化代码 | `/cases/{id}/export-code` → 生成独立 Playwright 脚本（语义定位器 + 断言，脱离平台可跑，0 token） |
| 步骤级事件流 | `step_event` 表 + `/api/runs/{id}/events?after=` 轮询游标 |
| 报告中心 | 时间轴报告（截图 / LLM 决策轨迹 / 断言）+ AI 失败五类归因 + 缺陷草稿 |
| Allure 兼容导出 | `/api/runs/{id}/allure` → allure-results + 装了 allure CLI 后自动生成 HTML，托管于 `/allure-html/<run_id>/` |
| 趋势面板 | `/api/trends`（通过率 / flakiness / 时长 / Token 成本） |

## 查看测试报告

| 方式 | 入口 | 说明 |
|---|---|---|
| **Web 控制台（主报告）** | <http://127.0.0.1:8001/app/#/runs> → 查看报告 | 时间轴（LLM 决策轨迹 / 动作结果 / 截图 / 断言）+ AI 失败归因 + 缺陷草稿 |
| **Allure HTML** | 报告页点「生成 Allure 报告」按需生成（带进度显示），完成后按钮变为「查看 Allure 报告」新窗口打开；或 `POST /api/runs/{id}/allure` 后访问 `/allure-html/{id}/` | 标准 Allure 格式，CI 兼容；生成一次后保存复用，由平台托管 |
| **Allure CLI 离线查看** | `./tools/bin/allure serve artifacts/allure/<run_id>` | 项目内置 CLI + JRE，无需系统安装 |
| **终端报告** | `python scripts/demo.py` 的输出 | 决策 / 动作 / 断言 / 归因逐行打印 |

## REST API 摘要

```
GET    /api/cases                用例列表            POST   /api/cases            新建用例
GET    /api/cases/{id}           用例详情            PUT    /api/cases/{id}       更新用例
DELETE /api/cases/{id}           删除用例            POST   /api/cases/{id}/run   单用例执行
POST   /api/cases/{id}/cure      启用固化回放
GET    /api/plans                计划列表            POST   /api/plans            新建计划
POST   /api/plans/{id}/run       计划执行
POST   /api/runs                 提交执行（case_id 或 plan_id 二选一）
GET    /api/runs                 执行列表            GET    /api/runs/{id}        执行详情+任务
GET    /api/runs/{id}/events     事件流（after 游标轮询）
GET    /api/runs/{id}/report     聚合报告（含失败归因）
POST   /api/runs/{id}/allure     导出 Allure 结果
GET    /api/trends               趋势统计            GET    /api/locators        元素库
```

## 目录结构

```
easyrun/            平台后端（FastAPI + 调度器 + Worker + Agent 运行时）
  agent.py          Agent 执行循环（观察→决策→行动→校验 + 自愈 + 固化）
  browser.py        Playwright 快照与操作工具
  assertions.py     确定性断言（6 类）
  llm.py            DeepSeek 客户端（OpenAI 兼容，可替换本地开源权重）
  orchestrator.py   调度器（Master）
  worker.py         Worker（资源锁 / 固化 / 事件流 / 独立进程入口）
  reporter.py       报告聚合 / AI 失败归因 / Allure 导出
  api/              REST 路由
web/                控制台（零构建 SPA，后端直接托管）
demo/               演示商城站点（被 Agent 测试的目标应用）
scripts/            bootstrap.sh（一键初始化）/ setup-allure.sh（按平台下载）/ demo.py
tools/              本机二进制：Allure CLI + JRE（setup-allure.sh 生成，不入库）
data/               运行时数据：数据库 / 截图 / Allure 输出（不入库）
docs/               架构设计文档
tests/              测试套件
.env.example        环境配置模板（复制为 .env 使用）
```

## 测试

```bash
pytest                      # 单元 + API 测试（无需浏览器 / API Key）
pytest -m browser           # 浏览器集成测试（需 playwright install chromium）
```

## 路线图（P2 规划）

- [ ] 移动端 Agent（Appium 2.0 + MCP 封装）
- [ ] 元素库转正流程（自愈定位需一次回归验证后 verified）
- [ ] 事件流 SSE 推送（当前为轮询）
- [ ] CI 插件（Jenkins / GitLab CI）
- [ ] 失败知识库向量检索（pgvector）

## 许可证

Apache-2.0（第三方依赖：Playwright Apache-2.0、FastAPI MIT、SQLAlchemy MIT 等；
DeepSeek API 为外部模型服务，协议 OpenAI 兼容，可替换为本地开源权重）。
