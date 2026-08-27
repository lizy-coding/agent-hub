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

- 已实现：启动自检、工作区注册表、上下文解析、能力分析、影子基准、迁移规划/执行骨架、development 重构程序、decomposition 拆解程序。
- 有意不在范围内：需求分析器、通用 RAG、外部项目管理集成；宿主不 push / 不 merge / 不发布。
