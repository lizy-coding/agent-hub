# Agent Hub

[English](./README.en.md) | **中文**

一个以项目注册表驱动的 LangGraph 工作区托管与重构编排平台。通用 Worker、Thread/Run 生命周期和路径门禁不绑定业务仓库；项目特有的 capability inventory 与架构规则通过显式 adapter 提供。

Agent Hub 本身不提交业务项目源码。它接收“项目注册 + 工作区运行时配置”作为上下文，并在受管 worktree 中执行重构/迁移。接入只读分析型项目不需要修改 Graph；需要项目特有架构判断的 decomposition 项目必须注册对应 adapter。

---

## 1. 目录与文件

| 路径 | 说明 |
| --- | --- |
| `src/agent_hub/` | 源码（`gateway` CLI、`graphs` 图、`projects` 注册表、`workspace` 配置、`execution` Worker、`policies` 安全策略等） |
| `langgraph.json` | 注册给 LangGraph CLI 的全部 Graph 入口 |
| `workspace/config.json` | 工作区运行时上下文（工作区根、可读路径、排除路径、注册表） |
| `workspace/projects.json` | decomposition（拆解）项目注册表 |
| `workspace/registry.json` | 刷新后的工程事实注册表（生成的只读产物） |
| `agent` | 本地命令行入口（重构 / 拆解 dashboard） |
| `.integration/` | development 重构集成 worktree（flutter_forge，运行期由 `refactor-run` 创建） |
| `.decomposition/` | decomposition 拆解程序的工作树与状态快照 |
| `plans/` | 迁移/拆解计划与提案（JSON） |
| `tests/` | `unittest` 测试套件 |

---

## 2. 已注册的 Graph

| Graph（`langgraph.json`） | 模块 | 作用 |
| --- | --- | --- |
| `workspace_bootstrap` | `graphs/bootstrap.py` | 最小只读启动图 `START -> workspace_check -> END`，校验工作区可读、注册表可解析、仓库路径在工作区内且存在、LangGraph 可导入 |
| `context_analysis` | `graphs/context_analysis.py` | 只读上下文解析图：加载注册表、解析候选、检索证据、解析规则、打包上下文 |
| `capability_analysis` | `graphs/capability_analysis.py` | 能力分析图：上下文解析 -> 能力发现 -> 耦合分析 -> 归属分类 -> 与工作区能力匹配 -> 抽取评估 |
| `shadow_benchmark` | `graphs/shadow_benchmark.py` | 影子基准图：加载场景与已评审 golden，运行上下文/能力分析、证据评分、指标聚合与门禁评估 |
| `migration_planning` | `graphs/migration_planning.py` | 迁移规划图：由能力分析推导架构不变量、生成 MigrationTask DAG、绑定规则与验证、评估风险 |
| `migration_execution` | `graphs/migration_execution.py` | 迁移执行骨架图（加载批准计划、验证权威与源新鲜度、worktree、执行、scope/validate/integration） |
| `development` | `graphs/development.py` | 重构执行图：`bootstrap_runtime -> reconcile -> inventory -> normalize -> prepare -> execute -> review -> commit -> final_rescan`，驱动单仓库全量重构程序 |
| `decomposition` | `graphs/decomposition.py` | 拆解编排图：能力盘点 -> 包候选分类 -> 生成 MigrationTask DAG -> worktree 管理 -> Worker 派发 -> 校验 -> 评审 -> 集成 |
| `release_hosting` | `graphs/release_hosting.py` | GitHub 安装包发布托管图（scene#22 CI/CD）：reconcile -> freeze -> verify_artifacts -> preflight -> publish -> verify_release；默认 PLAN_ONLY，`--execute` 才经冻结的 `gh release` 通道发布 |

---

## 3. 环境与安装

- Python `>= 3.11`
- 依赖由 `pyproject.toml` 管理（langgraph、langgraph-cli、pydantic、PyYAML）

```bash
cd /path/to/agent-hub
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e .
```

验证全部 Graph 可被 LangGraph 解析：

```bash
langgraph validate --config langgraph.json
```

---

## 4. 启动 LangGraph 服务

Dashboard 与 `./agent` 默认访问 `http://127.0.0.1:2024`：

```bash
langgraph dev --no-browser --no-reload --port 2024
```

---

## 5. 使用方式

### 5.1 启动自检（Bootstrap）

```bash
agent-hub-bootstrap --config workspace/config.json
```

- 运行时切换工作区（不改 Graph 源码）：

  ```bash
  agent-hub-bootstrap --config workspace/config.json --workspace-root /absolute/new/workspace
  ```

- 切换注册表（注册表是显式配置的只读输入，其内部仓库路径仍须落在 `workspace_root` 下）：

  ```bash
  agent-hub-bootstrap --config workspace/config.json --registry-path /absolute/path/to/registry.json
  ```

### 5.2 刷新工程事实注册表

```bash
python -c 'from pathlib import Path; from agent_hub.workspace.config import WorkspaceConfig; from agent_hub.projects.api import refresh; print(refresh(WorkspaceConfig.from_file(Path("workspace/config.json"))))'
```

`WorkspaceRegistry` 是只读的工程事实层：仅在工作区内发现 Git 根与 manifest 支撑的开发单元，记录证据与新鲜度、推导路径依赖，并把归一化结果写入 `workspace/registry.json`。稳定消费 API 见 `agent_hub.projects.api`（`get_workspace`、仓库/单元查询、依赖/反向依赖、规则文件与校验查询、`refresh`、`validate_registry`）。

> `AGENTS.md` / `AGENTS.override.md` 只记录路径/作用域/来源（provenance），**不把规则文本复制进注册表**。

### 5.2.1 关键 Agent 有界上下文

```bash
./agent agent-context --project flutter-forge
./agent agent-context --project gcode-core
./agent agent-context --project flutterguard
./agent sync-plan --max-files 64
```

事实入口从注册的 `sync_profiles` 与 Git 近期文件出发，优先主 manifest、必需文件及声明的局部依赖，再将明确的 `candidate_paths` 和冻结文本传入现有 context/capability 图。默认写入 `workspace/sync-plan.json`，返回 `sync-plan.v1` 和 0/1/2 结果协议；不调用全量发现或覆盖 `workspace/registry.json`。`--output` 可指定其他观察文件。

显式文件列表约束实际读取范围；缺失、删除、目录、symlink 与超过预算的候选会记录为缺口。未提交工作区、历史证据与当前提交验收分别记录。未传 `candidate_paths` 的兼容解析入口仍可能遍历源码，不能用结果数量上限代替本入口的范围约束。

规则入口按实际文件的祖先目录解析，根到深层继承；同目录 `AGENTS.override.md` 优先于 `AGENTS.md`。候选选择会将必需指南纳入同一文件预算，避免只有源码而没有适用规则。指南缺失、不可读、越界或预算不足会记录具体缺口；规则解析不依赖历史 registry 已经收录新指南，也不向兄弟目录或邻居仓库扩散。

FlutterGuard 通过独立 `workspace/flutterguard.json` 只读接入，仓库 ID 为 `flutterguard`，包名为 `flutterguard_cli`。它与 Forge 消费的 immutable Git pin 分开核对；IDE adapter 不成为新的检测实现来源。

### 5.3 重构程序（development Graph）

```bash
./agent refactor-status            # 查看持久化重构线程状态
./agent refactor-watch             # 每 2 秒刷新状态
./agent refactor-run               # 提交/继续全局重构运行（自动拉起 Worker）
./agent refactor-decide --decision-id <id> --choice <choice> [--reason "..."]   # 处理阻塞决策
```

重构程序遵循**冻结任务（frozen task）**模式：每次只允许一个冻结的 `DevelopmentTask` 修改代码，经 Worker -> Codex -> ScopeGuard -> 定向校验 -> flutter analyze 基线对比 -> Reviewer 后，仅批准的任务在集成 worktree 内提交。不 push、不 merge、不 release。

### 5.4 拆解程序（decomposition Graph，PLAN_ONLY）

```bash
./agent decomposition-plan                # 提交规划运行
./agent decomposition-propose --spec <proposal.json>   # 只读自定义任务提案
./agent decomposition-sync                # fast-forward clean managed base 到已验证 integration HEAD
./agent decomposition-status              # 查看拆解程序状态
./agent decomposition-run --execute       # 允许执行 MigrationTask（默认仅规划）
./agent decomposition-decide --decision-id <id> --choice <choice>
```

- 拆解程序在 `workspace/projects.json` 中按项目注册（默认项目 `flutter-forge`）。
- 规划阶段**绝不执行**任何迁移；执行必须显式传 `--execute`，且 Worker 派发由 Graph 冻结精确路径。
- 自定义提案不允许携带 `allowed_paths` / `candidate_paths` 等 Graph 自有字段。

Flutter Forge 的 PC 封板与 Android readiness 任务由项目 adapter 冻结，当前顺序为：

1. `responsive_navigation_policy`：移动端/小屏应用内导航，桌面大屏多窗口。
2. `pc_window_lifecycle_baseline`：PC 三分类窗口生命周期、关闭重开和 Engine 稳定性。
3. `pc_build_matrix`：macOS/Windows 构建矩阵；Windows 必须由 Windows host 或 CI 验证。
4. `android_mobile_navigation_baseline`：360dp 小屏布局和导航验收。
5. `android_host_readiness`：Android host、插件矩阵、APK 和 emulator smoke test；属于非阻塞兼容轨道。

这些任务只允许修改 adapter 冻结的应用、测试、文档和 Android host 路径；不修改通用 Graph，也不允许宿主自动 push、merge 或 release。

### 5.4.1 执行控制与仓库维护进度

development 与 decomposition 的执行结果必须绑定 project/task、冻结契约哈希、
attempt 和输出树。必需检查缺失、失败或输出树变化时不得集成；同 Git 仓库
的写入通过 OS 锁串行化。旧任务缺少 `validation_by_repository` 时需要补充
检查并重新冻结，不会自动接受历史 SUCCESS 回执。

多仓库任务先整体预检，再逐仓持久化集成 phase、commit 与 gate。dashboard
展示这些维护进度；中断后校对 Git 事实续跑，不重复提交已完成仓库。
发布完成还要求回读远端产物的大小与 SHA256。具体格式、恢复规则和验证边界
见 [架构控制进度](docs/reports/ARCHITECTURE_CONTROL-20261002.md)。

### 5.5 安装包发布托管（release_hosting Graph，scene#22 CI/CD）

```bash
./agent release-plan [--spec release.json]   # 冻结 ReleaseProgram 并校验安装包 sha256（PLAN_ONLY）
./agent release-status                       # 查看发布程序状态
./agent release-run --execute                # 经冻结的 gh release 通道发布到 GitHub Releases
./agent release-decide --decision-id retry:release:<tag> --choice retry   # 部分发布失败后的重试决策
```

- 发布目标在 `workspace/projects.json` 的 `release` 段冻结：`github_repo`（发布前必须配置，否则以 `RELEASE_NOT_CONFIGURED` 阻塞）、`tag_prefix`、`artifact_root`、默认 draft/prerelease。
- Flutter Forge 约定：安装包由 CI 或本地构建预置到 `<repo>/release/<version>/`，命名 `FlutterForge-<version>-<platform>.<ext>`（apk/aab/dmg/exe/msix/zip/ipa/tar.gz），可选 `SHA256SUMS` 交叉校验；版本默认取 `apps/flutter_forge/pubspec.yaml`。
- 图只消费预构建的安装包，**从不运行构建**；发布前逐文件重算 sha256 与冻结值比对，路径逃逸、缺失或校验和不匹配都会阻塞。
- 发布通道是 `forbid_release` 的唯一显式例外（`policies/safety.py::validate_release_command`）：仅允许 `gh release create/upload/view/list/download`、`gh auth status`、`gh repo view`，且 `--repo` 必须等于冻结仓库；`delete`/`edit`/push/merge 仍被拒绝。凭据来自运维者本人的 `gh auth` 会话，宿主不存储任何 token。
- 发布工作流所有权固定为 `agent_hub.gateway.release`（`policies/safety.py::validate_release_entrypoint`）。业务仓库的 CI 只能构建/暂存产物，不得直接创建、编辑或上传 Release；发布必须通过 `release-plan` 冻结后再由 `release-run --execute` 进入 `release_hosting` 图。
- 幂等恢复：tag 已存在时进入 RESUME 模式只补传缺失资产；上传中断以 `PARTIAL_PUBLISH` 阻塞，经 `release-decide` 重试后从断点续传；发布完成后回读 release 校验资产名与大小，并下载逐项核对 SHA256 后才标记 `PUBLISHED`。
- release spec（`--spec`）只允许请求 `version`/`tag`/`name`/`notes`/`draft`/`prerelease`/显式 `artifacts`；`github_repo`、`repository_paths` 等 Graph 自有字段一律拒绝。

---

## 6. 配置说明

### 6.1 `workspace/config.json`

| 字段 | 说明 |
| --- | --- |
| `workspace_root` | 工作区根目录 |
| `allowed_paths` | 允许读取的路径（默认 = 工作区根） |
| `excluded_paths` | 排除路径 |
| `registry_path` | 外部提供的启动注册表（JSON） |
| `registry_storage_path` | 归一化后注册表的落盘位置 |
| `runtime` | 运行时身份（环境、primary 仓库、仓库运行时路径等） |

### 6.2 `workspace/projects.json`

拆解项目注册：`default_project` + 每个项目的 `adapter` / `program_id` / `snapshot_namespace` / `workspace_config` 路径。`adapter` 必须在 `agent_hub.projects.adapters` 注册；当前提供 `flutter_forge`（项目事实和架构策略位于 `projects/flutter_forge_adapter.py`）和 `generic`（安全的 plan-only 基线）。

新增项目的最小接入只需：

1. 在 `workspace/projects.json` 增加项目身份和 `adapter`；
2. 在对应 `workspace/config.json` 声明运行时仓库及路径；
3. 若需要项目特有 decomposition 规则，实现 `ProjectAdapter` 的能力盘点、提案冻结、架构守卫和 contract preflight，并注册 adapter；
4. 用第二个项目的 plan/reconcile/worker-path 测试证明 Graph 主流程无需项目名分支。

未知 adapter 会在项目配置加载阶段失败；Worker 使用冻结任务携带的 `repository_paths`，不会回退到默认项目仓库。

### 6.3 `.env.local`

本地运行参数：Worker endpoint、Codex profile 等（该文件含密钥，请勿提交；必要时提供 `.env.local.example`）。可通过环境变量覆盖，例如 `AGENT_HUB_CODE_WORKER_ENDPOINT`、`AGENT_HUB_CONFIG`。

---

## 7. 安全策略

默认**拒绝一切（deny-by-default）**，见 `src/agent_hub/policies/safety.py`：

- 业务仓库只读：读取被限制在配置的 `allowed_paths` 内；
- 禁止对业务仓库写入、禁止 Git push / merge / release / 删除仓库；
- 宿主不暴露不受限的 Shell 执行器；
- 执行必须经由 Graph 冻结的精确路径（ScopeGuard 同时检查 tracked 与 untracked 改动）。

---

## 8. 测试

```bash
source .venv/bin/activate
python -m unittest discover -s tests
```

测试覆盖：bootstrap、workspace registry、runtime workspace、context resolver、capability analyzer、migration planner/executor、shadow benchmark、refactor dashboard/decide/run、development reconciliation、decomposition、architecture goldens 等。

---

## 9. 当前范围

- 已实现：启动自检、工作区注册表、上下文解析、能力分析、影子基准、迁移规划/执行骨架、development 重构程序、decomposition 拆解程序、release_hosting 安装包发布托管（PLAN_ONLY 默认 + 显式 `--execute` 发布通道）。
- 有意不在范围内：需求分析器、通用 RAG、外部项目管理集成；除 release_hosting 冻结通道外，宿主不 push / 不 merge / 不发布。

### 统一事实同步与验证

```bash
./agent sync-plan --output workspace/sync-plan.json
./agent sync-plan --project forge --profile maintenance --max-files 64 --output /private/tmp/forge-plan.json
./agent sync-plan --project forge --previous /private/tmp/forge-plan.json --output /private/tmp/forge-plan-next.json
./agent maintenance-test --profile maintenance
./agent maintenance-test --profile execution
./agent maintenance-test --profile release
```

注册项的 `sync_profiles` 是统一输入配置。主 manifest、required_files 与活动祖先指南优先；workspace/path 依赖只从已捕获的 manifest 定点扩展。每项目整轮共享最多 64 个文件的内容读取预算，context、capability、inventory、队列和发布声明检查复用同一冻结文本，不各自重置预算。内容读取失败也计入；候选路径探测有独立上限。必需闭包不完整为 BLOCKED，可选缺口为 PARTIAL。

公共命令使用 `sync-plan.v1`：SUCCESS 退出 0，PARTIAL 退出 1，BLOCKED 或入口错误退出 2。`agent-context` 和 `scripts/project_inventory.py` 已改用这一协议，旧 JSON schema 与退出码没有兼容承诺。dirty 工作区与显式未跟踪内容作为来源说明，不据此判定功能失败。

`source_snapshot_id` 绑定选中内容；`plan_id` 另绑定配置、profile、预算、需求及比较依据。队列 delta 是源契约声明的变化，不更新执行任务状态。默认不读取运行检查点；`--checkpoint <local-file> --project <id>` 仅核对指定本地快照，不恢复、不协调、不快进，并不证明最新运行状态。

注册校验仍可独立运行 `.venv/bin/python scripts/check_project_registry.py`。测试菜单只包含显式 fixture，维护菜单不会调用全量 discover、旧 shadow benchmark 或业务全库扫描。验证器缓存位于输出树外，Python 字节码关闭；源码变化拒绝仍保留。

发布声明核对使用捕获的 workflow 与 Hub 策略，正式发布继续走 `release-plan` / `release-run --execute`。必须提供每个必需平台的 producer manifest，绑定源码 SHA、成功 CI run/attempt、架构、工具链、签名、模式、产物大小和 SHA256；缺失或不一致阻断。当前 Forge producer 尚缺架构与工具链字段，Hub 不伪造，生产端补齐前旧 manifest 不能通过新门禁。

决议与边界见 [工作流优化决议](docs/reports/workflow-optimization-decisions-20261013.md)。
