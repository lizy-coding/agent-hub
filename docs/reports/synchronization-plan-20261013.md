# 托管项目同步计划与工作流优化

日期：2026-10-13，Asia/Shanghai。此次同步将 Agent Hub、Forge、gcode-core、FlutterGuard 的当前工作区事实、项目队列和工作流差异汇总为 PLAN_ONLY 计划。优先完善输入预算与统一同步入口，验证缓存隔离可独立推进，再处理发布契约和运行检查点的同步。

本次只新增计划与证据文件，保留此前 P1 的未提交改动。计划中的路径是待冻结候选；允许操作与写路径为空，不能据此 dispatch、集成或发布。

## 同步基线

| 工程 | 当前 HEAD | 声明版本 | 工作区 | 上下文采集 | 观察状态 |
| --- | --- | --- | --- | --- | --- |
| flutter-forge | `b90d5971a8af6de4a6eaedf979344a9e53ef0cac` | 应用 `1.2.8+2` | 有未提交改动 | 64 文件 | 40 项缺口或状态说明 |
| gcode-core | `2c6945da2f0f1c721fcbae9043b25d3c2f92dcfc` | 包 `0.2.1` | 有未提交改动 | 19 文件 | 1 项工作区状态说明 |
| flutterguard | `fb86f4ffa322bb0dbe69748c5c594296bf44657d` | CLI `0.7.1` | 有未提交改动 | 33 文件 | 3 项缺口或状态说明；只读 |

三个项目均为 `REFRESHED_WITH_GAPS`。共选中 116 个上下文文件；独立 inventory 另有 15、3、2 个输入文件，各自预算为 32、16、8。两阶段去重后分别覆盖 Forge 71、gcode-core 19、FlutterGuard 33 个文件，不能把联合结果表述为一次 64 文件采集。所选上下文内容与 Git HEAD、已跟踪改动路径在报告归档前复核稳定；所有结果仍包含未提交内容。

与 2026-10-10 的 P1 记录相比，三个 HEAD 均相同；Forge 与 gcode-core 从当时的 clean 变为 dirty。FlutterGuard 当时已有 dirty 状态。版本相同、HEAD 相同都不意味着工作区内容相同。

Forge 消费的 gcode-core Git pin 仍绑定 `22d76ad54e11ad752771b594b8345d5f9aab6a31`，与独立 checkout 的 `2c6945d…` 分开记录。此次没有升级消费依赖。

## 队列与工作流同步结果

Forge 的 `REFACTOR_PLAN.md` 包含 20 项：11 项声明 completed、8 项 pending、1 项 planned。开放项为 USB 平台边界、移动布局、Android 兼容规划、3D 相机运动、3D 选择、Windows 3D 准入、Android 3D 只读准入、Android 视频和 Android 文件选择。完整 ID、目标、依赖与验收声明已投影到 [机器计划](synchronization-plan-20261013.json)，写范围保持为空。completed 是源契约状态，不是此次对当前 SHA 的验收。

- Forge CI 执行质量门禁；release 的 build 依赖 quality，并使用 quality 输出的源码 SHA。实际暂存物包含 macOS DMG、Windows EXE、Android ARM64 debug APK 和 Web zip。Hub 仍将 Windows 描述为构建目录、Web 描述为 `build/web`，macOS runner 也与业务工作流不同，需要校准。
- gcode-core CI 已声明独立纯 Dart timing smoke、包与 example 测试、Android ABI/API 检查及 macOS 构建。它们是当前工作流声明，此次没有运行这些业务任务。
- FlutterGuard 的 CLI release 按 validate、build、publish-github-release 编排；IDE preflight 与 Marketplace 发布由独立脚本负责。preflight 会复制原生资源并运行 Gradle，不能作为只读同步步骤执行。
- 当前 Forge 指南已将日常维护矩阵简化为支持声明、功能差异和限制依据。Hub 的工作区与证据状态继续单独记录，不能将其重新混入业务支持矩阵。

LangGraph 的本地 HTTP 检查被沙箱拒绝，实时 checkpoint 状态为未知。两个显式读取的本地历史快照均没有 `orchestration_sync`；其中一个 integration HEAD 为 `11ac3a2…`，与当前 Forge HEAD 不同。这两个样本不能证明最新运行状态。此次完成本地同步计划，没有提交远端 Run 或执行 `decomposition-sync` 的基线快进。

## 可以流程化的环节

| 优先级 | 当前摩擦 | 优化方式 | 完成标准 |
| --- | --- | --- | --- |
| P1 | 注册检查、上下文、inventory 分开调用，重复读取；退出码含义不同 | 增加统一 `sync-plan` 入口，复用同一冻结文本，统一过程结果、观察缺口与执行阻断字段 | 一次运行产出版本、能力、队列差异和证据；缺口不会被退出码 0 隐藏；全程无递归 |
| P1 | Forge 有 38 个 seed、102 个候选，64 文件预算仍遗漏 33 项；上下文缺三个依赖 manifest，独立 inventory 却完整 | 建立有限任务 profile，优先主 manifest、相关依赖和祖先指南；区分必需文件与历史退役路径 | 相同任务输入可复现；指南和源码同预算；无关历史路径不挤占核心输入 |
| P1 | Hub 发布矩阵与业务工作流重复维护 | 消费业务仓库的标准发布 manifest，并对工作流、Hub 策略与产物做差异校验 | EXE/DMG/APK/Web zip、平台、架构、源码、工具链及签名一致；来源或哈希不一致阻断发布 |
| P1 | 验证子进程继承缓存环境；维护全量测试可能调用旧无界解析 | 隔离验证缓存，登记显式有界测试 profile；端口和平台测试单独验收 | 默认验证不污染输出源码树；真实修改仍被 ScopeGuard 拒绝；维护菜单不调用旧 benchmark |
| P2 | 源队列、历史迁移状态和运行检查点容易被当作同一状态 | 基于契约哈希同步队列差异，校验项目身份和 checkpoint 来源 | 幂等重跑，不自动生成执行范围；历史完成与当前验证独立；实时状态缺失时保留未知 |
| P2 | 日常声明、开发测试、专项验收易混合为“健康”指标 | 分开输出声明维护、开发反馈和发布验收 | dirty、预算缺口不推定业务失败；历史验收和 checkout 不代替当前收据及消费 pin |

缺失候选包括 Forge 的三个旧 generator 文件和 FlutterGuard 的 StartupActivity。它们说明采集输入需要校准，不能单独认定为业务回归。是否退役应结合当前契约和 Git 删除记录确认；显式必需指南或契约缺失仍应保留阻断或未知。

## 实施顺序与验收

1. **输入 profile 与缺口分类。** 范围集中在 `workspace/projects.json`、`agent_context.py`、`registry_check.py` 与关联 fixture。证明候选顺序不改变版本，核心 manifest 与活动指南优先，walk/glob/rglob/refresh 被禁用时仍可工作。
2. **统一同步入口。** 新增共享同步模块，连接注册、冻结输入、事实投影、队列和差异报告。配置与文件哈希、source SHA 必须进入输出；相同内容重跑保持同一观察身份，写路径始终为空。
3. **缓存隔离与测试菜单。** 可与前两项并行。先复现缓存污染，再验证树外缓存与真实源码变更拒绝；只运行选定 fixture，不用全量扫描或构建代替维护验证。
4. **发布契约校准。** 基于统一入口实现漂移检查。Forge 继续拥有生成源和构建工作流；Hub 只消费契约并按自己的发布策略校验。依赖业务生成源修改时另行冻结该仓库范围。
5. **队列和 checkpoint 投影。** 在有实时状态访问时核对 namespace、项目身份、来源 SHA 和执行记录。当前本地计划不覆盖旧 checkpoint，不自动快进 worktree。

各项的已定位候选路径、依赖和验收条件见机器计划。新模块与新测试文件单独标为创建候选；正式实现前还需解析对应祖先规则并由 Graph 冻结精确范围。

```mermaid
flowchart LR
  A[注册与权限校验] --> B[选择有限输入和祖先指南]
  B --> C[冻结文本与源码身份]
  C --> D[版本 能力 依赖 队列投影]
  D --> E[差异与缺口分类]
  E --> F[PLAN_ONLY 同步计划]
  F --> G[另行冻结实施提案]
```

## 本次验证与证据

注册校验无错误，保留 Forge seed 超过默认预算的警告；三个独立 inventory 所选输入没有缺口。34 项维护、上下文、完整性及有界 fixture 通过，fixture 将 walk/glob/rglob 和全量 refresh 设为报错。此次没有运行业务门禁、平台验收或旧无界 benchmark，也没有提交、推送、合并或发布。

- [有界上下文快照](synchronization-context-20261013.json)：原始选择、哈希、上下文和缺口。
- [机器同步计划](synchronization-plan-20261013.json)：当前事实、队列、工作流、六项发现及五步实施提案。
- [此前 P1 记录](project-maintenance-p1-20261010.json)：比较基线，保留其原始证据范围。
