# 托管工程下一阶段维护清单

日期：2026-10-10，Asia/Shanghai。Forge 与 FlutterGuard 的本地脱耦验收已通过，下一阶段优先处理执行可靠性、证据准确性和发布来源，再补齐真实平台与长期运行验收。

本清单是维护顺序和验收条件，不是冻结的 MigrationTask。项目身份以 `workspace/projects.json` 为准；FlutterGuard 保持只读 PLAN_ONLY。实现任务开始前固定精确路径、必需验证和执行身份。提交、推送、部署、发布须有对应授权。

## 当前基线

| 工程 | 源码 HEAD | 证据范围 |
| --- | --- | --- |
| flutter-forge | `75a57d1cdab644d3499f77eade3f1c668acbec83` | HEAD 加未提交工作区；应用声明 `1.2.8+2` |
| flutterguard | `b3becede57d87b9d5a3c53e6a2bca79e3cb84e17` | HEAD 加未提交工作区；CLI `0.7.1` |
| gcode-core | `22d76ad54e11ad752771b594b8345d5f9aab6a31` | 2026-10-10 健康度快照；详细运行验收待补 |

脱耦验收记录见 [验收记录](forge-flutterguard-decoupling-20261010.json)。既有本地结果：Forge 五阶段门禁通过，367 项 Flutter 测试、22 项 Node 测试、scaffold 和 27/27 模块测试存在性检查通过；FlutterGuard 分析无 issue、21 项契约测试通过，macOS arm64 原生 CLI 的 JSON/SARIF、退出码 0/1/2 及 stdout 无文件写入通过。原始日志与二进制位于临时目录，不能作为长期产物存储。

## 脱耦残留清理

- Forge 生成源移除失效的 `flutterGuardDependency` 读取和 `external_tool` 字段，通过生成器同步验证，禁止手改生成物。
- Forge 的 CI/CD 验收报告将 Node 测试数量从 24 更正为实际执行的 22。
- Hub adapter 移除应用迁移契约与默认路径中的旧 `flutterguard.yaml` 授权。
- 既有历史报告保持原有证据范围；不把独立工具重新加入 Forge 依赖、Git hook、CI 或发布门禁。

清理复验：Forge 完整门禁 5/5 PASS，367 项 Flutter 测试、22 项 Node 测试、scaffold 与 27/27 模块检查通过；Hub 3 项定向测试通过。生成器 59 个输出无变化，53 份契约有效。清理文件哈希和验证摘要已归档到验收记录。

## 下一阶段顺序

| 顺序 | 优先级 | 责任工程 | 维护项 | 当前状态 | 完成条件 |
| --- | --- | --- | --- | --- | --- |
| 1 | P1 | Agent Hub | 验证缓存与源码树隔离 | 待实现 | 默认环境执行控制测试通过；验证产生的缓存不进入产物树；真实源码修改仍被拒绝 |
| 2 | P1 | Agent Hub | 应用版本与包版本分开投影 | 本地实现，定向验证通过，未提交 | Forge 应用版本来自应用 manifest；各包版本独立记录；调整候选顺序不会改变应用身份 |
| 3 | P1 | Agent Hub | 发布来源与平台完整性 | 待实现 | 冻结源码 SHA、CI run、工具链、平台、架构、签名及验收；缺端、来源或哈希不一致均阻断 |
| 4 | P1 | flutter-forge | 同提交远端质量与打包闭环 | 待提交及远端执行 | 同 SHA 的 CI、质量阻断反例与四端产物成立；下载后的大小及 SHA256 与 manifest 一致 |
| 5 | P1 | flutterguard | Windows IDE 原生资源查找 | 待冻结实现范围 | 打包与查找统一 `.exe` 名称；四种资源查找用例通过；Gradle check、verifier 与 Windows IDE 实测分别记录 |
| 6 | P2 | Agent Hub | 托管元数据与运行配置校准 | 待实现 | 定点核对 Forge/gcode 缓存及 FlutterGuard 回退元数据；显式记录新鲜度；Hub 发布矩阵与当前 Forge 工作流一致 |
| 7 | P2 | flutter-forge | 原生订阅与重连稳定性 | 待主机及设备验收 | USB、BLE、电池、多窗口分别覆盖错误、关闭重开、重连与长时资源增长；按平台记录 |
| 8 | P2 | gcode-core | GPU 与文件读取长期验收 | 待主机及设备验收 | 固定大文件样本，覆盖加载、拖动、切换及销毁重建；记录帧耗时和内存趋势；Android ARM64 API 29/35 分别验证 |

推荐首先推进第 1 项。2026-10-10 的执行控制相关 55 项测试在默认环境下有 12 项失败、1 项错误；禁用 Python 字节码写入后全部通过。独立复现确认 `__pycache__/test_suite.cpython-311.pyc` 导致 `validation_changed_output`。修复应让验证过程的输出进入源码树外，保留产物树和验证收据绑定，不能通过放宽 ScopeGuard 或关闭源码变化检查解决。

第 2、3、6 项可在 Hub 内独立验证；第 4 项消费已经冻结的候选提交。第 5 项由 FlutterGuard 独立拥有，不能通过修改 Forge 的消费依赖处理。第 7、8 项分别依赖真实平台环境，交叉编译和单元测试不代替运行验收。

## 执行与证据要求

每个实现项先创建精确范围的提案，记录 `candidate_paths`、规则入口、源码 SHA 和文件哈希；不得调用全量 registry refresh 或旧无界解析入口。规划期间的允许操作和写路径保持为空，Graph 冻结后才授予执行范围。

先运行关联 fixture，再运行仓库规定的必要门禁。验证有界入口时让 walk/glob/rglob 报错；分别记录 EXECUTED、VALIDATED、INTEGRATED、PLATFORM_ACCEPTED，不以某一状态推定另一状态。临时目录证据在进入集成或发布前转入版本化证据存储。

Forge 正式发布继续使用 Hub `release-plan` 和 `release-run --execute`。远端校验已有大小与 SHA256 检查，应保持；待补的是来源和必需平台约束。Windows/macOS 未签名及 Android debug APK 必须保留准确标识。

## 日常维护节奏

| 周期 | 动作 | 记录内容 |
| --- | --- | --- |
| 每次变更 | 范围检查与定向测试 | 当前 SHA、工作区内容哈希、责任工程、PASS/PENDING/FAIL |
| 每周 | 检查悬挂改动、执行失败、元数据缺口 | 每个问题的责任工程、阻塞原因与下一步 |
| 每次发版或依赖升级 | 完整门禁与来源冻结 | 消费版本、同 SHA 构建、签名、产物大小及 SHA256 |
| 每月 | 原生能力和 GPU 长时验证 | 样本、设备、工具链、重连结果、帧耗时及资源趋势 |
| 每季度 | 复核规则和职责边界 | 单一事实源、过期证据标识与权限范围 |

## 2026-10-10 P1 索引维护落地

本轮实现的是索引维护评估中的三项 P1：注册一致性检查、能力与包依赖投影、应用与包版本分离。上表中的验证缓存隔离和发布来源完整性仍待实现。

- `scripts/check_project_registry.py` 校验注册身份、别名、adapter、namespace、runtime 路径与托管权限；发布配置复用同一项目解析入口。
- `scripts/project_inventory.py` 从显式契约和 manifest 投影能力、职责、声明平台、包版本及已观察的局部依赖图；源码和活动祖先指南共用文件预算，变化或缺失保留未知。Forge 的电池、USB-network 与当前工作区包纳入输入，既有架构策略和迁移任务状态保持独立。
- `agent_context.primary_manifest` 固定项目版本来源；上下文与 adapter 共用投影模块。主 manifest 缺失不回退到插件版本，Git 消费 pin 不由邻居 checkout 替代。

相关 60 项测试通过，最后一次投影模块复验 8 项通过，`git diff --check` 通过。注册校验无错误，保留 Forge 38 个 seed 超过默认 24 文件预算的警告。Forge 定点投影共检查 15 个文件，应用版本 `1.2.8+2`，所选输入无缺口；64 文件上下文采集仍为 `REFRESHED_WITH_GAPS`，不代表全库完整或平台验收。

全量回归未通过：本地 HTTP worker 测试因沙箱禁止绑定监听端口报错；旧 shadow benchmark 触发无界业务解析后已停止，本轮不再调用该路径。版本化证据见 [P1 维护记录](project-maintenance-p1-20261010.json)。业务 checkout 未修改，既有上下文快照未覆盖，修改未提交、推送或发布。

## 2026-10-13 同步计划

后续维护顺序、当前工作区基线和工作流优化见 [2026-10-13 同步计划](synchronization-plan-20261013.md)。此次为本地 PLAN_ONLY 投影，既有历史验收范围保持不变；实时 LangGraph checkpoint 尚未核对。

## 2026-10-13 优化实施

统一 sync-plan、共享预算、结果协议、显式测试菜单、Python 验证缓存隔离、发布声明校准与队列差异已在 Hub 实现。[决议与验证结果](workflow-optimization-decisions-20261013.md)记录 Q1–Q4 的确认与证据。

原维护清单第 1 项已本地修复；第 3 项的 Hub 来源与平台门禁已实现，Forge producer 仍需补齐架构和工具链字段才能通过新门禁。真实远端质量与打包闭环、平台和长期运行验收仍保持原责任边界及待验证状态。

## 2026-10-17 索引升级

[2026-10-17 全部托管项目索引升级](index-upgrade-20261017.md)记录最新捕获、BoundaryLens 入口校准及八项后续优化。gcode-core 与 Forge 选中范围复核稳定；BoundaryLens 保留部分观察与采集后过期标识，不代表当前完整索引。
