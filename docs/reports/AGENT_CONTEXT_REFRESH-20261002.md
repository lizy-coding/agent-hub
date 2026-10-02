# 关键 Agent 有界更新记录 — 2026-10-02

## 结果

从 Agent Hub 项目注册、当前 LangGraph context/capability 图和 Git 近期路径开始，完成 Forge、gcode-core、FlutterGuard 的关键 Agent 指南与托管元数据更新。没有调用全量发现、WorkspaceRegistry.refresh、真实仓库 legacy 无范围解析或业务全量扫描。

3/3 项目有界图调用通过；共 59 个已选证据文件，每项目上限 24。真实调用和 fixture 都将 os.walk、Path.glob、Path.rglob、discover、refresh 设为失败操作，调用仍通过。定向 30 tests PASS，git diff --check PASS；这不是业务全量测试或平台验收结果。

## 项目与来源

| 项目 | 本地基线/版本 | 本轮范围 |
| --- | --- | --- |
| flutter-forge（别名 forge） | f799663；1.2.8+2 | 24 文件；生成器、app/theme、BLE、共享能力契约与近期工作区 |
| gcode-core | 22d76ad；0.2.1 | 11 文件；GPU-only package、Android host、维护者确认与历史证据 |
| flutterguard | b3beced；0.7.1 | 24 文件；executable CLI、单文件/stdout 协议、IDE adapter 与原生打包 |

当前 checkout 包含未提交的 Agent 更新及原有工作。快照记录真实 worktree 状态和各文件 SHA256，acceptance=false；工作区实现不能成为已提交版本或真实设备验收证明。

## 控制面更新

- Context/Capability 图支持显式 candidate_paths 与 limits，显式空列表读取零源码；绝对路径、..、目录、缺失及 symlink 拒绝，依赖邻居不扩大源码读取。
- 新增 ./agent agent-context，按注册 seeds + 近期六个 Git 提交/工作区 tracked 路径构造范围，输出 workspace/agent-context.json。
- FlutterGuard 登记为独立 generic PLAN_ONLY 项目，独立 runtime/config/namespace，业务写入默认关闭。它不位于 langGraph 目录，不复用 Forge 路径边界。
- gcode-core adapter 读取当前版本、GPU metadata、models/native reader 所有权及匹配版本的维护者证据；历史 macOS 报告不能自动升级当前详细验收。
- Agent Hub 新增根 AGENTS.md，并更新 README 使用入口。

## 指南更新

- Forge：根 AGENTS.md、app/AGENTS.md、tool/agent_indexes/AGENTS.md；记录分拆后的生成器、主题与分类窗口生命周期、共享 popup/table、依赖 manifest/lock 单一事实源。
- gcode-core：根 AGENTS.md；记录 GPU 播放不重建几何、资源释放、Android API 29+/ARM64/GPU metadata、维护者确认与详细验收分开。
- FlutterGuard：根 AGENTS.md、CONTEXT.md、lib/src/cli/AGENTS.md、scripts/AGENTS.md、idea-plugin/AGENTS.md；CONTEXT 为纯术语表，移除已失效 monorepo handover，实际实现入口在分层指南中维护。

外部文档共 9 份，应用前核对原文件 SHA256，并通过明确文件范围的写入授权；未修改业务源码、已有工作区改动、历史验收或 .hermes 计划。

## 保留的缺口

- Forge/gcode 全量 registry 缓存仍分别是 2026-09-07 / 2026-09-05；本轮只读目标 metadata，未伪称整个 registry 已刷新。
- FlutterGuard 缓存缺失时仅投影 manifest 支撑的单 root unit，明确为 EXPLICIT_ROOT_FALLBACK；不是完整单元发现。
- 当前快照共 9 个 unknown，主要为 dirty/untracked 工作区与上述 metadata 缺口。超预算、目录、历史删除等忽略原因逐项保留。
- Forge 实际消费 gcode_core v0.2.1 / 22d76ad；FlutterGuard requested/resolved pin 均为 9f9be84。独立 FlutterGuard 当前 b3beced 的 IDE/stdout 能力不能推定消费者已升级。
- gcode-core 维护者确认 macOS/Android 0.2.1 手测；API 覆盖、截图、帧/内存数据等当前详细证据继续 PENDING。
- FlutterGuard IDEA 资源包使用 flutterguard-windows-x64.exe，当前运行时 lookup 缺少 .exe；本轮记录边界，未修改该业务实现。

## 重跑

```sh
PYTHONDONTWRITEBYTECODE=1 ./agent agent-context --max-files 24
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest tests.test_agent_context tests.test_bounded_context tests.test_gcode_core_adapter tests.test_decomposition_projects tests.test_runtime_workspace tests.test_project_adapters
```

快照：workspace/agent-context.json。它是已选文件的工作区投影，不是发布准入或全库验收。
