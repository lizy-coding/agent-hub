# 工作流优化决议

日期：2026-10-13，Asia/Shanghai。用户已确认 Q1–Q3 按推荐执行，并明确 Q4 接受破坏性修改，不要求旧命令保持可用。以下决议据此进入实现，取代此前待确认草案。

## 已确定决议

| 编号 | 决议 | 实现约束 |
| --- | --- | --- |
| D01 | 按优化清单推进输入 profile、统一入口、缓存与测试菜单、发布契约、队列与 checkpoint 投影 | 验证缓存可独立实现；各项分别记录结果 |
| D02 | 事实同步保持本地 PLAN_ONLY | 不修改业务 checkout，不调用会 rehydrate 或 reconcile 的 status 入口，不快进执行基线 |
| D03 | Graph 负责生命周期、冻结和执行；adapter 负责事实和归属 | 观察与计划不授予操作或写权限 |
| D04 | 只采集显式输入及其有限声明引用 | 不调用全量 refresh、旧无界解析或递归遍历；源码与祖先指南同预算 |
| D05 | 消费 pin、上游 checkout、历史完成与当前验证分开记录 | 不自动升级依赖，不提交、推送或发布 |
| D06 | 整轮共享默认 64 文件预算 | 以唯一文件的内容读取尝试计数；失败读取计入；路径探测另设上限；全部事实投影共用冻结文本 |
| D07 | 必需输入缺失阻断，可选输入不足部分输出 | 新协议 SUCCESS/PARTIAL/BLOCKED，退出码 0/1/2；单项目阻断不丢弃其他项目的观察 |
| D08 | 历史可选候选允许凭 Git 删除证据自动分类为退役 | 保留路径、删除提交和来源；显式必需、显式候选与当前工作区改动不自动降级；不自动编辑配置 |
| D09 | 接受破坏性接口修改 | 新入口及已有事实入口共用新协议；不维持旧 schema/退出码的兼容层 |

## 决议落实

- `sync-plan` 统一注册检查、输入选择、版本/能力/依赖投影、队列差异和发布声明校验。`agent-context` 也使用新协议，独立 inventory 脚本改为消费同一入口。
- `sync_profiles` 成为输入配置入口，合并原先两套文件清单。主 manifest、必需控制文件及活动指南优先；从已捕获 manifest 中的 workspace/path 声明继续定点读取局部 manifest，不遍历目录。
- `source_snapshot_id` 描述内容；`plan_id` 同时绑定注册与 workspace 配置、profile、预算、需求、比较队列与显式 checkpoint 的来源。时间戳不用于判定观察身份。
- 计划默认不查看 runtime checkpoint。显式指定本地 checkpoint 时只读取一个文件，核对项目、program 和 namespace，保留“不是最新状态证明”的范围说明；输出不能覆盖该 checkpoint。
- 验证缓存进入冻结输出树之外，Python 字节码关闭；真实源码变化仍由现有 `validation_changed_output` 检查拒绝。维护、执行和发布采用显式测试菜单，不进行全量测试发现。
- Hub 发布配置校准为 DMG、EXE、ARM64 debug APK、Web zip，并与捕获的工作流核对来源 SHA 绑定、quality 依赖、runner、工具链和暂存命名。发布时还需冻结各平台 producer manifest，再核对 CI 完成、源码、产物大小及哈希。

关键输入是 profile 的 required_files、主 manifest、从已读取 manifest 声明的局部 manifest，以及选中源码需要的活动指南。Git 工作区 dirty 和显式未跟踪内容属于来源说明，不直接表示功能失败；必需闭包放不进预算时仍阻断。

## 交付边界

当前 Forge producer manifest 已包含源码、CI run/attempt、签名、模式与产物哈希，但尚未记录新门禁要求的架构和工具链字段。Hub 不伪造这些字段，不直接修改业务生成器；旧 manifest 会被阻断，生产端补齐前不能据此发布。

业务工作流声明匹配只表示声明一致。它不代表远端 CI、真实主机、设备或长期运行验收通过。

- [共享采集预算 ADR](../adr/0001-shared-fact-capture-budget.md)
- [同步结果与接口迁移 ADR](../adr/0002-explicit-sync-outcomes.md)
- [领域词汇](../../CONTEXT.md)
- [原始同步计划](synchronization-plan-20261013.md)

## 验证结果

维护菜单 49 项、默认环境下的执行菜单 47 项、发布菜单 18 项均通过；关联集成入口复验 19 项通过。修复前默认环境的 worker 返回 `validation_changed_output`，修复后通过，真实源码修改仍被拒绝。

最新统一采集保持每项目 64 文件上限：gcode-core SUCCESS，Forge 与 FlutterGuard PARTIAL，无关键输入阻断。Forge 发布工作流声明 MATCH；可选预算不足和元数据缺口保留，未作为平台验收。所选文件哈希与来源 HEAD 已复核。

[实施证据](workflow-optimization-evidence-20261013.json)与[最新同步观察](workflow-optimization-sync-20261013.json)已保存。修改未提交或推送，业务仓库与运行检查点未修改；真实 CI 与发布没有执行。
