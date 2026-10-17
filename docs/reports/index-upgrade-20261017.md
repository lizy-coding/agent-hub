# 全部托管项目索引升级与后续优化清单

日期：2026-10-17，Asia/Shanghai。已刷新全部三个注册项目的统一事实索引，校准 BoundaryLens 的入口声明，并按上一步 Q1–Q4 决议更新后续优化清单。gcode-core 与 Forge 的选中内容在归档核对时稳定；BoundaryLens 工作区持续变化，保留部分观察与采集后过期标识，不能作为当前实施的完整依据。

## 本轮索引结果

| 注册项目 | 当前产品或包 | 捕获 HEAD | 版本 | 选中文件 | 捕获结果 | 归档新鲜度 |
| --- | --- | --- | --- | --- | --- | --- |
| gcode-core | gcode_core | `2c6945da2f0f1c721fcbae9043b25d3c2f92dcfc` | `0.2.1` | 19 | SUCCESS，0 缺口 | 选中文件与 HEAD 复核稳定 |
| flutter-forge | Flutter Forge | `6910044320f33ae27aa32d8ff5e2617672ccb248` | `1.2.8+2` | 62 | SUCCESS，0 缺口 | 选中文件与 HEAD 复核稳定 |
| flutterguard | BoundaryLens，包 boundarylens_cli | `ca8092573a05abd7341b3f05b9c6402c568779d3` | `0.7.1` | 64 | PARTIAL，44 缺口 | CHANGED_AFTER_CAPTURE，需重核当前声明 |

这里的“全部”指覆盖全部已注册项目。本轮没有运行全库源码递归发现，也未将有界观察升级为整库完整性或平台验收。最终一轮共选中 145 个文件，每项目不超过 64；全部投影复用该轮文本。前置观察、配置校准、并发变更后的有限重采分别归档，不能将多个轮次合并宣称为一次 64 文件采集。

统一入口按捕获结果返回 1：2 个 SUCCESS、1 个 PARTIAL、0 个 BLOCKED。后置新鲜度检查是额外核对：BoundaryLens 的 release workflow、IDE 指南、插件描述、脚本指南、preflight 与部分文档在捕获后继续变化，已记录具体路径与范围。这是本轮新增的一致性优化依据，不能用入口返回的 PARTIAL 代替当前内容已复核的结论。

## 已执行的索引升级

- 已更新 [当前统一索引](../../workspace/sync-plan.json)，并保存 [本轮归档](index-upgrade-20261017.json)与[复核和优化数据](index-upgrade-review-20261017.json)。历史快照未覆盖。
- 当前 manifest 和插件 descriptor 均声明 BoundaryLens。Hub 已增加 `boundarylens → flutterguard` 别名、显示名称、新 CLI 必需入口 `bin/boundarylens.dart`、插件 descriptor 及四个有实际文件依据的 Kotlin 候选。稳定 project_id、namespace、runtime 路径和只读权限保持原值；校准依据见 [profile 更新记录](index-profile-update-20261017.json)。
- Forge 的三个旧生成器路径已按 Git 删除提交 `41f1d750…` 归类为历史退役；FlutterGuard 的旧 StartupActivity 也有已提交删除证明。BoundaryLens 其余旧路径仍涉及工作区删除，不自动标为退役。
- Forge 的工作队列仍为 20 项声明，11 completed、8 pending、1 planned，相比 10 月 13 日没有队列声明差异。这些状态不代表本轮重新验收。
- Forge 的发布工作流声明与 Hub 策略 MATCH；其消费的 gcode-core pin 仍为 `22d76ad…`，没有替换成独立 checkout 的 `2c6945d…`。

Forge 在本轮三次捕获之间先后出现 `be0757b…`、`8d17ac8…`、`6910044…` 的源码基线。其缺口变化不能全部归因于 Hub 配置调整。BoundaryLens 的新命名声明包含未提交内容，不代表重命名已经交付。

## 对上一步决议的复核

| 决议 | 本轮执行 | 剩余问题 |
| --- | --- | --- |
| Q1 共享 64 文件预算 | 每轮源码、指南、版本、能力、依赖、队列和发布声明共用预算 | BoundaryLens 仍有 25 个可选预算缺口，需要任务 profile，而非放宽上限 |
| Q2 关键阻断与部分结果分开 | 捕获时没有关键输入阻断；BoundaryLens 保留 PARTIAL | 采集结束后的变更尚未进入统一协议，需增加发布前新鲜度检查 |
| Q3 只有证明充分的历史可选输入才退役 | Forge 3 项和旧 StartupActivity 按证明分类；未提交删除保留缺口 | 应区分工作区迁移、声明替代与历史退役，减少歧义 |
| Q4 接受破坏性修改 | 沿用 sync-plan.v1 与 0/1/2 协议，没有引入旧输出兼容层 | 后续可继续简化重复入口，不能为“兼容”恢复第二套采集 |

## 后续优化清单

以下为提案，不是冻结的执行范围；机器记录中的操作和写路径均为空。

| 优先级 | 优化项 | 责任方 | 完成条件 |
| --- | --- | --- | --- |
| P1 新增 | 整批索引发布前的新鲜度检查 | Agent Hub | 所有投影结束后及更新 latest 前复核 SHA、配置与选中文件；并发改动最多有限重采，仍变化则保留 stale 观察，不宣称当前可用 |
| P1 本轮部分完成 | 入口声明驱动 profile 校准 | Agent Hub | 从已捕获的 executables、descriptor 引用生成有限差异提案；保留稳定管理身份，不扫描源码猜入口 |
| P1 新增 | 工作区迁移与历史退役分类 | Hub 与项目维护者 | 工作区 D、声明替代和已提交 D 分开记录；新入口存在不等于旧路径已完成迁移；必需输入缺失不降级 |
| P1 延续 | 按 daily、IDE、release 等任务拆分 profile | Agent Hub | 每轮仍共享 64 文件；关键闭包完整，可选遗漏可追溯，避免将 IDE 文档和原生实现全部挤入同一轮 |
| P1 外部待补 | producer manifest 的 architecture/toolchain | flutter-forge | 生成源输出真实构建字段，再核对同 SHA 的 CI、平台、签名、模式、大小与 SHA256；旧 manifest 继续阻断 |
| P1 延续 | CLI 根开发单元的有限元数据缓存 | Agent Hub | 消除 TARGET_REGISTRY_METADATA_MISSING 的根因，绑定身份和来源；不得调用全量 refresh 或复制 detector 注册表 |
| P2 新增 | 未配置、未观察和空队列的差异语义 | Agent Hub | NOT_OBSERVED 不应仅输出 COMPARED 加空数组；只有可比较的声明才计算 delta，不能据空数组断言没有工作 |
| P2 新增 | 统一归档与项目级增量失效 | Agent Hub | 一次发布保留 canonical、archive、配置、哈希与比较基线；评估减少全局 alias 变更导致的无关项目 plan_id 抖动，变更身份规则前更新 ADR |

优先推进第一项，再把本轮手工的入口校准固化为有限声明提案。架构与工具链缺口仍由 Forge producer 拥有；Hub 不填造字段或放松已确认的发布门禁。

## 验证与边界

维护菜单 49 项通过，包含禁止 walk/glob/rglob 与全量 refresh 的 fixture；注册校验通过，新 alias 解析后仍是只读的 flutterguard 项目。所选内容复核结果按项目记录，BoundaryLens 的采集后变化没有被隐藏。

本轮只修改 Hub 注册配置、索引与报告，保留此前未提交实现；没有修改业务 checkout，没有恢复或协调运行 checkpoint，没有运行真实 CI、业务全量测试、平台验收或发布，也没有提交或推送。
