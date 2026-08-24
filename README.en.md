# EasyRun UI Agent

> [简体中文](README.md) | English

An AI-agent-based UI test automation platform: cases are described in natural language,
executed in parallel by multiple test agents, with every step logged, reports viewable in
real time, and failures attributable.

- **LLM**: DeepSeek official API (`deepseek-chat` for action decisions / `deepseek-reasoner` for decomposition and attribution, tiered routing)
- **Everything else**: fully open-source and self-hosted (Playwright / FastAPI / Redis / PostgreSQL / MinIO, etc.)

> Architecture and technology choices: see [docs/platform-design.html](docs/platform-design.html) (open in a browser).

## Quick Start (one-command bootstrap on a new machine)

```bash
sh scripts/bootstrap.sh          # Linux / macOS: auto venv / deps / browser / Allure / .env / environment check
```

On Windows 10/11 use the PowerShell version:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1
```

All three platforms (Linux / macOS / Windows) are supported and can be mixed into one cluster
(shared Redis + PostgreSQL).

bootstrap handles platform specifics automatically: macOS 12 and older pin playwright 1.50
(newer chromium no longer supports old systems), the Allure CLI+JRE is downloaded into the
project-local `tools/` (system untouched), and an `.env` template is generated.

Then edit `.env` to set `DEEPSEEK_API_KEY` and start:

```bash
source .venv/bin/activate
easyrun serve                    # API + scheduler + worker pool (single-machine mode)
```

Open the console: <http://127.0.0.1:8001/app/> (API docs <http://127.0.0.1:8001/docs>)

<details><summary>Manual install (equivalent steps)</summary>

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium
sh scripts/setup-allure.sh       # optional: project-local Allure
cp .env.example .env             # fill in DEEPSEEK_API_KEY
easyrun serve
```

</details>

### End-to-end demo (5 minutes)

With the platform running, execute in another terminal:

```bash
source .venv/bin/activate
python scripts/demo.py
```

The script creates a "store checkout" case (login → add to cart → checkout → assert order
number), submits it to the agent, prints decisions / actions / assertions / failure
attribution in real time, and leaves a full timeline report in the browser console.

## Deployment Guide

Three modes, increasing in scale, mutually compatible (same code, same configuration).

### Mode 3: single-machine development (zero external dependencies, the default)

For local development and debugging: SQLite + in-process queue + built-in worker.

```bash
# 1. Initialize (run once on a new machine): venv / deps / browser / Allure / .env
sh scripts/bootstrap.sh

# 2. Configure the LLM: edit .env with your key (or export DEEPSEEK_API_KEY)
# 3. Start
source .venv/bin/activate
easyrun serve            # http://127.0.0.1:8001/app/
# 4. Verify (in another terminal)
python scripts/demo.py
```

> ⚠️ The in-process queue is **single-process only**: `easyrun serve` with its built-in
> workers is fine, but a separate `easyrun worker` process cannot share that queue (each
> process gets its own). Multi-process deployments must configure Redis.

### Mode 1: single-machine Docker (one command, near-production shape)

Prerequisite: Docker (Linux host or Docker Desktop).

```bash
# 1. Provide the API key (compose reads it from the environment)
export DEEPSEEK_API_KEY=sk-xxx

# 2. Build and start (first build ~3-5 minutes: the image bundles chromium)
docker compose up -d --build

# 3. Check status
docker compose ps
curl http://127.0.0.1:8001/api/health
```

| Service | Role | Notes |
|---|---|---|
| `api` | Control plane: REST API / scheduler / web console | `EASYRUN_WORKERS=0`, no browsers |
| `worker` | Execution plane: agent + chromium | `EASYRUN_WORKERS=4` |
| `redis` / `postgres` | Reliable queue / metadata DB | Health checks; data lives under the project root `./data/` |

The image already bundles the **Allure CLI + JRE** at build time (`/srv/tools/bin/allure`,
same `tools/` layout as local development), so Allure reports work out of the box with no
extra installation. All runtime data (screenshots / Allure results & HTML / PostgreSQL data)
is bind-mounted to the project root `./data/`:

| Container path | Host path | Contents |
|---|---|---|
| `/srv/data/artifacts/allure/<run_id>` | `./data/artifacts/allure/<run_id>` | Raw Allure results (allure-results) |
| `/srv/data/artifacts/allure-html/<run_id>` | `./data/artifacts/allure-html/<run_id>` | Generated static Allure HTML report |
| `/var/lib/postgresql/data` | `./data/postgres/` | PostgreSQL data |

Generating and viewing reports: click "Generate Allure report" on the console report page,
or `POST /api/runs/{id}/allure`, then open `http://127.0.0.1:8001/allure-html/<run_id>/`
(the generated static files sit at `./data/artifacts/allure-html/<run_id>/` on the host,
ready to archive).

Common operations:

```bash
docker compose logs -f worker        # follow worker logs
docker compose up -d --build worker  # rebuild worker after code changes
docker compose down                  # stop (data stays in ./data/, not removed by down)
rm -rf data                          # wipe all runtime data (careful; down -v no longer applies)
```

### Same-machine multi-worker (1 control node + N execution nodes)

"Single-machine Docker" starts only 1 worker container (4 concurrent agents) by default.
On a machine with enough resources you can scale the execution plane out to N worker
containers; the control plane stays a single `api` container:

```
        ┌──────────────────────────────────────────────────┐
        │        One machine (a single docker compose stack)│
        │                                                  │
        │  api ×1 (control node: API / scheduler / console,│
        │          no browsers)                            │
        │    │          enqueue tasks (Redis)              │
        │    ▼              ▼              ▼               │
        │  worker-1       worker-2       worker-3          │
        │  (execution nodes, 4 concurrent agents each)     │
        └──────────────────────────────────────────────────┘
```

**Configuration**: no code changes needed — `docker-compose.yml` uses a YAML anchor
(`&common`) so the control node and every execution node share one connection
configuration, satisfying the two hard requirements for multiple workers:

| Config | Value | Why |
|---|---|---|
| `EASYRUN_REDIS_URL` | `redis://redis:6379/0` | All nodes must connect to the **same queue** for tasks to be distributed; without it each process keeps a private in-memory queue |
| `EASYRUN_DATABASE_URL` | `postgresql+asyncpg://easyrun:easyrun@postgres:5432/easyrun` | All nodes read/write the **same metadata DB** (tasks / events / reports) |
| `EASYRUN_WORKERS` | api=0 / worker=4 | Control node runs no browsers (0); execution nodes set concurrent agents per resources |
| `EASYRUN_DATA_DIR` | `/srv/data` (bind-mounted to the project root `./data`) | Shared artifact directory: workers write screenshots/Allure, the console previews artifacts from any node |
| `EASYRUN_ALLURE_BIN` | Unset (auto-detected) | Detection order: explicit config → PATH → `<project-root>/tools/bin/allure`; Docker images already bundle it (i.e. `/srv/tools/bin/allure` inside the container), **no configuration needed** |
| `EASYRUN_BROWSER_HEADLESS` | `true` | No display inside containers — headless is required |
| `EASYRUN_HOST` / `EASYRUN_PORT` | `0.0.0.0` / `8001` | Built into the Dockerfile; only `api` publishes port 8001 |

Browser binaries need no configuration: `playwright install --with-deps chromium`
bundles them into the image at build time.

**Steps**:

```bash
export DEEPSEEK_API_KEY=sk-xxx
docker compose build                     # first build ~3-5 minutes
docker compose up -d --scale worker=3    # 1 control node + 3 execution nodes
docker compose ps                        # expect api, worker×3, redis, postgres all running
curl http://127.0.0.1:8001/api/health
```

> The `workers` field of `/api/health` reports the **api container's own** worker
> count (0) — that does not reflect execution capacity. Execution happens in the
> worker containers; check `docker compose logs worker` instead.

**Verify concurrency**: submit a multi-case plan from the console, then
`docker compose logs -f worker` should show execution logs from several containers
(`worker-1` / `worker-2` / …) simultaneously.

**Scale in/out** (online, no restart):

```bash
docker compose up -d --scale worker=5    # scale out to 5 containers = 20 concurrent agents
docker compose up -d --scale worker=1    # scale in; extra containers stop automatically
```

> ⚠️ Use `--scale` only for worker: `api` publishes port 8001, so multiple replicas
> would conflict; single replicas of redis/postgres suffice.

**Capacity planning** (1 concurrent agent ≈ 1 chromium instance ≈ 400-600MB RAM):

| Machine RAM | Suggested | Concurrent agents |
|---|---|---|
| 8 GB | `--scale worker=2` | 8 |
| 16 GB | `--scale worker=4` | 16 |
| 32 GB | `--scale worker=8` | 32 |

**Tune per-container concurrency** (default 4): add a `docker-compose.override.yml`
(compose merges it automatically; no need to edit the main file):

```yaml
services:
  worker:
    environment:
      EASYRUN_WORKERS: "2"               # 2 concurrent agents per container
```

Then `docker compose up -d --scale worker=6` = 12 concurrent agents.

### Mode 2: multi-machine cluster (horizontal scale-out)

**Architecture**: 1 control node (API + scheduler) + N worker nodes + shared infrastructure
(Redis / PostgreSQL / artifact storage).

```
                    ┌──────────────┐
   Users/CI ───────▶│ Control ×1   │  easyrun serve (WORKERS=0)
                    │ API+scheduler│
                    │ + Web console│
                    └──────┬───────┘
                           │ enqueue / persist status
              ┌────────────┼────────────┐
              ▼            ▼            ▼
        ┌──────────┐ ┌──────────┐ ┌──────────┐
        │Worker A  │ │Worker B  │ │Worker C  │  easyrun worker (WORKERS=N)
        │chromium  │ │chromium  │ │chromium  │
        └──────────┘ └──────────┘ └──────────┘
              └─── Shared: Redis queue / PostgreSQL / artifacts ───┘
```

> ⚠️ Multi-machine deployment is **not** "run commands only on the control node": every
> worker machine must be deployed independently (copy code → bootstrap → configure `.env`
> → start). The control node cannot provision remote machines; a worker node joins
> automatically as soon as it connects to the shared Redis (no central registry, no
> control-node approval). Worker machines need their own browser binaries (downloaded
> by bootstrap), which is why each machine must be deployed separately.

**Step 1: infrastructure** (one machine, or reuse existing Redis/PG)

```bash
# Start only redis + postgres:
docker compose up -d redis postgres
# Note the addresses: redis://<this-machine-IP>:6379/0
#                     postgresql+asyncpg://easyrun:easyrun@<this-machine-IP>:5432/easyrun
```

**Step 2: control node**

```bash
sh scripts/bootstrap.sh                          # same as development
cat >> .env <<'EOF'
EASYRUN_REDIS_URL=redis://<infra-IP>:6379/0
EASYRUN_DATABASE_URL=postgresql+asyncpg://easyrun:easyrun@<infra-IP>:5432/easyrun
EASYRUN_WORKERS=0                                # control node runs no browsers
EOF
easyrun serve
```

**Step 3: worker nodes ×N** (repeat on each machine)

```bash
sh scripts/bootstrap.sh                          # deps + browser on every worker machine
cat >> .env <<'EOF'
EASYRUN_REDIS_URL=redis://<infra-IP>:6379/0
EASYRUN_DATABASE_URL=postgresql+asyncpg://easyrun:easyrun@<infra-IP>:5432/easyrun
EASYRUN_WORKERS=4                                # tune to machine memory: 1 agent ≈ 1 browser instance
EOF
easyrun worker
```

**Worker nodes via Docker (optional)**: run only a worker container per machine,
connecting to the central Redis/PG:

```bash
# Point at the central infrastructure via an override (docker-compose.override.yml):
#   services:
#     worker:
#       environment:
#         EASYRUN_REDIS_URL: redis://<infra-IP>:6379/0
#         EASYRUN_DATABASE_URL: postgresql+asyncpg://easyrun:easyrun@<infra-IP>:5432/easyrun
docker compose up -d --no-deps --build worker
```

> `--no-deps` is required: without it compose would also start a local redis/postgres
> pair on this machine.
> Docker worker images already bundle the Allure CLI + JRE (identical across machines);
> artifacts land in that machine's project root `./data/artifacts/` (compose bind-mounts
> `./data:/srv/data`, no configuration needed).

**Step 4 (important): shared artifact storage — data path configuration in detail**

First understand **who writes what and who reads what**, then decide how to configure paths:

| Node | Writes (to its local `data/`) | Reads |
|---|---|---|
| Control node (api) | Raw Allure results `data/artifacts/allure/<run_id>/`, Allure HTML `data/artifacts/allure-html/<run_id>/` (generated by the control node when you click "Generate Allure report") | All nodes' screenshots & baselines: console previews, and attachment packing when generating Allure |
| Worker node | Step screenshots `data/artifacts/sessions/<session_id>/s_*.png`, visual baselines `data/artifacts/baselines/` | Effectively write-only |

**Conclusion**: workers write where they run, the control node reads everywhere — the control
node must be able to read every worker's `data/artifacts/`, otherwise cross-node screenshots
cannot be previewed and Allure report attachments come out missing.

**Default data paths per node** (when nothing is configured):

| Node form | Host path | Container path | Configuration needed |
|---|---|---|---|
| Bare-metal (control/worker) | `<project-root>/data` | — | None (it is the `EASYRUN_DATA_DIR` default) |
| Docker (control/worker) | `<project-root>/data` | `/srv/data` | None (compose already bind-mounts `./data:/srv/data`) |

> To use a different directory: bare-metal sets `EASYRUN_DATA_DIR=<dir>`; Docker changes the
> volume to `<dir>:/srv/data` in `docker-compose.override.yml` (or overrides the
> `EASYRUN_DATA_DIR` environment variable — the two must point at the same directory).

---

**Option A (recommended): shared path = the control node's project-root `data/`**

The control node doubles as the NFS server and exports its own `<project-root>/data` to all
worker nodes. Every node's data then lives under its own project `data/` — intuitive paths,
zero configuration changes.

**A1. Control node: export `data/` (NFS server, Linux)**

```bash
sudo apt install -y nfs-kernel-server          # Debian/Ubuntu

# Append an export rule: allow the worker subnet read/write (use your real subnet; "*" opens to all)
echo '<project-root>/data 192.168.1.0/24(rw,sync,no_subtree_check,no_root_squash)' | sudo tee -a /etc/exports

sudo exportfs -ra                              # reload the export table
sudo systemctl enable --now nfs-server         # start on boot
showmount -e 127.0.0.1                         # should list the exported path
```

Export options explained:

| Option | Meaning |
|---|---|
| `rw` | Allows workers to write |
| `sync` | Replies only after data hits disk (consistency) |
| `no_subtree_check` | More stable mounts |
| `no_root_squash` | **Critical**: Docker containers write as root; without this option root is squashed to `nobody` and every container write fails with Permission denied |

Firewall (if ufw is enabled): `sudo ufw allow from <worker-subnet> to any port nfs`.

If the control node runs macOS (NFS server):

```bash
sudo nfsd enable
sudo sh -c 'echo "<project-root>/data -network 192.168.1.0 -mask 255.255.255.0 -maproot=root:wheel" >> /etc/exports'
sudo nfsd update
```

The control node itself needs **zero configuration**: its own processes read/write the local
disk directly (in the Docker form, compose already bind-mounts `./data`, which is still the
local disk, not NFS).

**A2. Each worker node: mount the control node's `data/` onto its own project root**

```bash
sudo apt install -y nfs-common                  # NFS client (Debian/Ubuntu)
sudo mkdir -p <project-root>/data

# Mount: <data exported by the control node> → <this machine's project-root>/data
sudo mount -t nfs <control-IP>:<control-project-root>/data <project-root>/data

# Auto-mount on boot (nofail: a temporarily unavailable NFS must not block boot)
echo '<control-IP>:<control-project-root>/data <project-root>/data nfs defaults,nofail 0 0' | sudo tee -a /etc/fstab
```

Once mounted, **worker nodes need no configuration changes at all**:

- Bare-metal worker: `EASYRUN_DATA_DIR` already defaults to `<project-root>/data`, which is now the NFS mount point;
- Docker worker: compose's `./data:/srv/data` automatically points at that NFS mount point.

> ⚠️ Order matters: **mount NFS first, then `docker compose up`** (or run
> `docker compose restart worker` after mounting). A container's bind mount is locked to the
> host directory at container start; mounting NFS afterwards leaves the container seeing the
> old local directory.

**A3. Verify (three steps)**

```bash
# ① Bidirectional visibility: the worker sees the control node's files, and writes travel back
ls <project-root>/data/artifacts/
touch <project-root>/data/nfs-check && ls <control-project-root>/data/nfs-check && rm <project-root>/data/nfs-check

# ② Cross-node preview: submit a multi-case plan from the console; once tasks spread across
#    worker nodes, the console report page should preview every screenshot (screenshots are
#    actually written on the worker, then reach the control node via NFS)

# ③ Allure consistency: after clicking "Generate Allure report", the control node and every
#    worker's data/artifacts/allure-html/<run_id>/ should be identical
```

---

**Option B: separate shared storage (NFS/S3-like mount at any location)**

When you don't want to export the control node's directory (or the shared storage is a
standalone NAS), mount the share anywhere and configure explicitly:

```bash
# On every machine (including the control node):
sudo mkdir -p /mnt/easyrun-share
sudo mount -t nfs <NFS-server>:/easyrun-share /mnt/easyrun-share
# Also add an /etc/fstab entry (as above, with nofail)
```

Bare-metal nodes (including the control node), in `.env`:

```
EASYRUN_DATA_DIR=/mnt/easyrun-share
```

Docker nodes, via `docker-compose.override.yml` (compose merges it automatically; the main
file stays untouched):

```yaml
services:
  api:      # control node
    volumes:
      - /mnt/easyrun-share:/srv/data
  worker:   # worker node
    volumes:
      - /mnt/easyrun-share:/srv/data
```

> ⚠️ **The control node must mount the same share too**: the control node is what generates
> the Allure report, and it must be able to read worker screenshots from the shared directory
> for attachments to be complete.

---

**Behavior without shared storage**

The cluster runs fine without shared storage (execution is unaffected), but:

- The console can only preview artifacts in **the control node's own `data/`**; screenshots
  produced on other nodes cannot be previewed;
- Generating Allure leaves out screenshot attachments produced on non-control nodes (the
  report itself still generates normally);
- Remedy: after mounting the share, click "Generate Allure report" once more to repack
  everything completely.

**Permissions & pitfalls quick reference**

| Symptom | Cause | Fix |
|---|---|---|
| Containers get Permission denied writing to the share | Export lacks `no_root_squash` (containers write as root) | Add `no_root_squash` to exports, then `sudo exportfs -ra` |
| Bare-metal workers fail to write | User uids differ across machines (NFS authorizes by uid) | Align user uids across machines, or export with `all_squash,anonuid=<uid>` |
| Share missing on workers after reboot | No /etc/fstab entry | Add an fstab entry (with `nofail`) |
| Containers don't see NFS contents | Containers started before the NFS mount | `docker compose restart` after mounting |
| postgres data appears inside the share | The whole `data/` tree is exported, including `data/postgres/` | Harmless: postgres only accesses it locally on the infrastructure machine; **never** start postgres on multiple machines pointing at the same directory |

**Scaling and operations**

```bash
# Scale out = run "Step 3" on a new machine; node registration needs no control-node approval
# Take a node offline: just stop the process / shut down — crashed tasks are recovered and re-queued by the scheduler
# Observe: GET /api/health (control node); easyrun health (any node)
# Rolling upgrade: stop workers one by one → pull code → bootstrap → start worker; upgrade the control node last
```

### Configuration precedence

`Web console Settings page (platform_setting table, multi-machine shared, effective on save)` > `command line / environment variables` > `.env file` > `code defaults`.
Only the "default target URL" and the "execution policy" (rows marked ⚙ below) can be overridden at runtime from the console Settings page; the rest follow the table below.

#### Runtime execution policy (console "Settings" page)

| Item | Range | Default | Notes |
|---|---|---|---|
| Max retries on failure | 1-10 | 1 (= no re-run) | Cap on full-case re-runs; every re-run is a fresh execution (≤30 LLM calls) |
| Self-healing rounds | 0-5 | 0 (= off) | LLM self-healing rounds after assertion failure; ≤6 LLM calls per round |
| Max action steps per case | 3-100 | 30 | 1 LLM call per step — **tightening this saves tokens most directly** |
| Failure analysis | on/off | on | When off, failed tasks skip the deepseek-reasoner attribution call (saves tokens); report pages lose root-cause analysis and defect drafts |

- Stored in the shared database (`platform_setting` table), **consistent across machines**: the scheduler re-reads every 2 seconds and workers read at the start of every task — saving applies to new tasks/retries immediately; running tasks are unaffected.
- Saving an empty input clears the override and falls back to the environment/code default.
- The page key `max_steps` maps to the environment variable `EASYRUN_MAX_STEPS_PER_CASE`.

## Configuration (environment variables, prefix `EASYRUN_`)

| Variable | Default | Description |
|---|---|---|
| `EASYRUN_DATA_DIR` | `./data` | Runtime data (DB / screenshots / Allure / **browser binaries**), separated from code; multi-machine sharing is configured in "Mode 2 · Step 4" |
| `EASYRUN_DATABASE_URL` | `data/easyrun.db` (SQLite) | Empty falls back to the data dir; production: `postgresql+asyncpg://user:pass@host/db` |
| `EASYRUN_REDIS_URL` | empty (in-process queue, single-process only) | Required for multi-machine/multi-process: `redis://host:6379/0` |
| `EASYRUN_WORKERS` | `4` | Concurrent agents (scaling unit = browser instance); set `0` on pure API nodes |
| `EASYRUN_TASK_TIMEOUT_SECONDS` | `600` | Per-task execution limit |
| `EASYRUN_MAX_ATTEMPTS` ⚙ | `1` | Automatic retry cap (1 = execute once; retry manually via "Re-run Failed" on the report page); changeable at runtime on the Settings page (1-10) |
| `EASYRUN_HEAL_ATTEMPTS` ⚙ | `0` | Self-healing retry rounds after an assertion failure (0 = no self-healing, fail immediately); changeable at runtime on the Settings page (0-5) |
| `EASYRUN_QUARANTINE_THRESHOLD` | `3` | Consecutive failures reaching this value quarantine the case |
| `EASYRUN_MAX_STEPS_PER_CASE` ⚙ | `30` | Cap on LLM action steps per case; changeable at runtime on the Settings page (3-100, page key `max_steps`) |
| `EASYRUN_MAX_NOOP_REPEATS` | `1` | Allowed executions per identical action (1 = each action runs once; repeats are skipped with a prompt to proceed, regardless of page state) |
| `EASYRUN_MAX_SKIPPED_REPEATS` | `2` | Max skips for a repeatedly requested action (beyond this the run terminates, preventing LLM spinning) |
| `EASYRUN_BROWSER_HEADLESS` | `true` | Headless browser mode |
| `EASYRUN_REPLAY_STEP_DELAY_MS` | `3000` | Delay between replayed actions (waits for dynamic rendering, e.g. news links appearing after a date click) |
| `EASYRUN_ALLURE_BIN` | auto-detect | Allure CLI path (tries PATH → `tools/bin/allure`) |
| `PLAYWRIGHT_BROWSERS_PATH` | `data/browsers` | Browser binaries directory (injected automatically, moves with the project; usually not needed) |
| `DEEPSEEK_API_KEY` | — | DeepSeek API key (or `EASYRUN_DEEPSEEK_API_KEY`) |
| `EASYRUN_DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | OpenAI-compatible endpoint; can point to a local vLLM/Ollama |

## Authoring Guide

1. **Write steps as "what to do", not "how to click"** — the agent translates natural language into concrete actions (find element, click, wait). The more explicit, the more stable: "type username demo, password 123456" beats "log in". Each case can set a **default target URL**, still overridable at run time.
2. **Assertions are the only source of truth** — however well the steps are written, the case fails if its assertions do not pass. Give every case at least one assertion covering the business outcome (order number appears, URL navigation, error message text).
   **Not sure how to write assertions? Use natural language**: in the assertion area of the case form, type "page shows Order No; navigates to checkout; list has 3 items; order amount greater than 100", then click **"AI Generate"** to convert automatically (LLM structured extraction + deterministic checks; still manually adjustable afterwards).
   There are 9 assertion types: `text_contains` / `url_contains` / `element_exists` / `element_count` / `element_text` / `text_in_view` (visible text on screen) / **`text_near_top` (position check: the text appears in the upper window area; target=text, expected optionally the upper-area ratio, default 0.4)** / **`value_compare` (compares the number after a label with an expected value, e.g. "Order Amount" `>= 100`, "Analyzed" `> 0`; supports both `<span>Analyzed: <strong>2363</strong> items</span>` and adjacent-sibling forms)** / `visual` (screenshot comparison).
   **Step-bound assertions**: an assertion can be bound to a step number (fill the "Step #" field on the assertion row) — in explore mode the agent calls `case_step_done` after completing each step, and the platform runs the bound assertions **immediately** after that step's actions (0-token deterministic checks; fail-fast: self-heal first if configured, otherwise the case fails). If the agent finishes without marking a step, the wrap-up fallback runs all unmarked step assertions in step order, then the unbound ones. Cured replay also runs them at the marker points (markers are saved with the cured actions); exported code generates the bound assertions inline right after the corresponding actions.

   **How the step number maps to your case**: the number you fill in is the **line number in the case's Steps list** (1-based, one step per line). Rules:

   - One step can bind several assertions; one assertion binds exactly one step number.
   - The number is the **step line number, not an action count** — one step may correspond to several actions (find + click + wait); actions are decided by the agent.
   - In the prompt, steps are listed with numbers, and lines with bound assertions get a "call `case_step_done(step=N)` after completing this step" hint appended.
   - Agent misses a marker, or the number exceeds the step count: the assertion is **never lost** — the wrap-up fallback runs it in step-number order (it degrades to end-of-run timing, still labeled "step N" in the report).
   - No number = runs after all steps complete (the traditional behavior).
   - ⚠️ Adding/removing step lines does **not** renumber bindings automatically — double-check the assertion step numbers after editing steps.

   Example (the assertion "page shows Order No" is bound to step 4):

   | Step | Bound assertion | When it runs |
   |---|---|---|
   | 1. Open the store homepage | `url_contains` /home (step 1) | Immediately after step 1's actions |
   | 2. Search "mechanical keyboard" | `element_count` results = 12 (step 2) | Immediately after step 2's actions |
   | 3. Click the first result | (none) | — |
   | 4. Add to cart and check out | `text_contains` Order No (step 4) | Immediately after step 4's actions |
   | — | `value_compare` order amount > 100 (no number) | After all steps complete |
3. **One case = one business scenario** — keep steps short (≤10 recommended); failures attribute more accurately. Split scenarios into separate cases and batch them with a Plan.

**Explore once, save forever**: explore mode costs LLM tokens per step (~0.5–1.5k/step) and is only for path discovery.
After an explore pass, the platform records the actions automatically, unlocking two token-free paths:
- **Cure replay**: click "Cure" on the case row → every subsequent run costs 0 tokens (platform-dependent);
- **Export code**: click "Export code" on the case row → generates a standalone Playwright script (`get_by_text` semantic locators + assertions)
  that runs outside the platform and can be committed to your test repo for CI — **the case becomes automation code**.

## Platform Capabilities (design doc → implementation)

| Design | Implementation |
|---|---|
| Multi-agent parallel execution | Worker pool (`EASYRUN_WORKERS` agents consuming the queue concurrently) |
| Master-Worker | `orchestrator.py` (decomposition / retry / watchdog / quarantine / finalization) |
| Observe→Decide→Act→Verify | `agent.py` JSON action protocol + Playwright indexed snapshot |
| Deterministic assertions | `assertions.py` (6 assertion types incl. visual comparison) |
| Locator self-healing | Assertion failure → LLM re-location → collected into the element repo (`/api/locators`) |
| Cure mode | Actions auto-recorded after an explore pass → `/cases/{id}/cure` enables deterministic replay (no LLM cost) |
| Export automation code | `/cases/{id}/export-code` → standalone Playwright script (semantic locators + assertions, runs outside the platform, 0 tokens) |
| Step-level event stream | `step_event` table + `/api/runs/{id}/events?after=` polling cursor |
| Report center | Timeline report (screenshots / LLM decision traces / assertions) + 5-category AI failure attribution + defect draft |
| Allure-compatible export | `/api/runs/{id}/allure` → allure-results, plus HTML auto-generated (when the allure CLI is installed) and served at `/allure-html/<run_id>/` |
| Trend dashboard | `/api/trends` (pass rate / flakiness / duration / token cost) |

## Viewing Test Reports

| Method | Entry point | Notes |
|---|---|---|
| **Web console (primary)** | <http://127.0.0.1:8001/app/#/runs> → View Report | Timeline (LLM decision traces / action results / screenshots / assertions) + AI failure attribution + defect draft |
| **Allure HTML** | On the report page click "Generate Allure Report" to generate on demand (with progress status); once saved, the button becomes "View Allure Report" and opens in a new tab — or `POST /api/runs/{id}/allure` then open `/allure-html/{id}/` | Standard Allure format, CI-compatible; generated once and reused, hosted by the platform |
| **Allure CLI offline** | `./tools/bin/allure serve artifacts/allure/<run_id>` | Bundled CLI + JRE, no system install |
| **Terminal report** | Output of `python scripts/demo.py` | Decisions / actions / assertions / attribution printed line by line |

## REST API Summary

```
GET    /api/cases                Case list           POST   /api/cases            Create case
GET    /api/cases/{id}           Case detail         PUT    /api/cases/{id}       Update case
DELETE /api/cases/{id}           Delete case         POST   /api/cases/{id}/run   Run single case
POST   /api/cases/{id}/cure      Enable cure replay
GET    /api/plans                Plan list           POST   /api/plans            Create plan
POST   /api/plans/{id}/run       Run plan
POST   /api/runs                 Submit run (case_id or plan_id)
GET    /api/runs                 Run list            GET    /api/runs/{id}        Run detail + tasks
GET    /api/runs/{id}/events     Event stream (after-cursor polling)
GET    /api/runs/{id}/report     Aggregated report (incl. failure attribution)
POST   /api/runs/{id}/allure     Export Allure results
GET    /api/trends               Trend stats         GET    /api/locators        Element repo
```

## Directory Structure

```
easyrun/            Platform backend (FastAPI + scheduler + worker + agent runtime)
  agent.py          Agent execution loop (observe→decide→act→verify + healing + cure)
  browser.py        Playwright snapshot and action tools
  assertions.py      Deterministic assertions (6 types)
  llm.py            DeepSeek client (OpenAI-compatible, swappable for local open weights)
  orchestrator.py   Scheduler (Master)
  worker.py         Worker (resource locks / cure / event stream / standalone entry)
  reporter.py       Report aggregation / AI failure attribution / Allure export
  api/              REST routes
web/                Console (zero-build SPA, hosted directly by the backend)
demo/               Demo store site (the target app tested by the agent)
scripts/            bootstrap.sh (one-command init) / setup-allure.sh (per-platform download) / demo.py
tools/              Local binaries: Allure CLI + JRE (generated by setup-allure.sh, not committed)
data/               Runtime data: database / screenshots / Allure output (not committed)
docs/               Architecture design documents
tests/              Test suite
.env.example        Environment template (copy to .env)
```

## Tests

```bash
pytest                      # unit + API tests (no browser / API key needed)
pytest -m browser           # browser integration tests (requires playwright install chromium)
```

## Roadmap (P2 planning)

- [ ] Mobile agent (Appium 2.0 + MCP wrapper)
- [ ] Element repo promotion workflow (healed locators become verified after one regression pass)
- [ ] Event stream SSE push (currently polling)
- [ ] CI plugins (Jenkins / GitLab CI)
- [ ] Failure knowledge base with vector search (pgvector)

## License

Apache-2.0 (third-party deps: Playwright Apache-2.0, FastAPI MIT, SQLAlchemy MIT, etc.;
DeepSeek API is an external model service with an OpenAI-compatible protocol, replaceable by
local open-source weights).
