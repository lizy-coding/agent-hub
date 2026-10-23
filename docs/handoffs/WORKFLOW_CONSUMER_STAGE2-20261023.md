# Forge 工作流消费端下一阶段准备

日期：2026-10-23。状态：准备完成，业务执行尚未开始。机器可读范围和证据见[同名 JSON](/Users/forest/code/agent-hub/docs/handoffs/WORKFLOW_CONSUMER_STAGE2-20261023.json)。

## 已交付基线

Hub 核心代码与 Agent 规则已提交并推送至 origin/main：`15c95b4b46d045b3d39cdecf4193d6ee0ddb0f30`，远端 SHA 已核对。该提交包含 19 个文件；workflow 22、maintenance 49、规则继承 11 项 fixture 通过，覆盖真实 CLI 启停、目录启用、升级终止、最新版重试、备份恢复及规则解析。

源码交付不代表用户服务已重启、旧库已迁移、Forge 已消费新版或系统调度已安装。既有 workspace/sync-plan.json 保持未提交原样；Forge checkout 完全未修改。

## 观察事实与边界

Forge 注册身份为 flutter-forge，checkout 为 /Users/forest/code/langGraph/flutter_forge；观察分支 dev，HEAD `b501f210f275a5a40197e3be2fd38b5d808a782b`。31 个 tracked dirty 路径之外还有显式未跟踪的工作流、GenUI 和网络诊断实现，HEAD 不能描述全部工作区。不能用新的干净 checkout 替代当前消费者事实。

本轮通过 agent-context/workflow profile 捕获 40 个文件，结果 PARTIAL、115 个观察缺口、无阻断，acceptance=false。没有递归发现。随后按明确路径补充 17 个指南、实现和测试文件；连同根指南及一次失败的补充读取尝试，保守内容读取上界 59/64。补充证据不把原始 PARTIAL 改为 SUCCESS，也不构成全库覆盖或主机验收。

首次查询含宽泛验收词，历史路径匹配排在可选指南之前，挤占预算。准备阶段已将根规则、机器契约、模块/共享/包指南及 pin 提升为 workflow profile 必需输入，并给出精确查询词；修订配置尚未重新采集，下一阶段第一步必须重新绑定当前工作区，不能沿用旧采集计划身份。

已定位的改动依据：

| 位置 | 当前事实 | 对下一阶段的要求 |
| --- | --- | --- |
| [workflow_session.dart:49](/Users/forest/code/langGraph/flutter_forge/apps/flutter_forge/lib/modules/ui/workflow_workbench/workflow_session.dart:49) | 连接时只选择 articles.explore v1，参数表单只在连接时初始化 | 改为当前声明与能力结构校验，提交/重试前重新确认目录 |
| [hub_client.dart:64](/Users/forest/code/langGraph/flutter_forge/apps/flutter_forge/lib/shared/workflows/hub_client.dart:64) | 新建发送缓存 definition 的版本 | 区分普通请求的显式版本与最新版重试，显示 Hub 实际冻结版本 |
| [article_workflow_test.dart:74](/Users/forest/code/langGraph/flutter_forge/packages/forge_articles/test/article_workflow_test.dart:74) | runner 测试将版本 2 列为不支持定义 | 同步检查 runner 的接受条件，不能只删页面版本判断 |
| [workflow_session.dart:147](/Users/forest/code/langGraph/flutter_forge/apps/flutter_forge/lib/modules/ui/workflow_workbench/workflow_session.dart:147) | 轮询 cancelling/cancelled 后取消本地 token | 增加升级终止、迟到回报、新令牌重连的实际停止证据 |
| [workflow_ecosystem_test.dart:13](/Users/forest/code/langGraph/flutter_forge/apps/flutter_forge/integration_test/workflow_ecosystem_test.dart:13) | 跨项目测试需显式开启 WORKFLOW_E2E 和临时令牌 | 使用隔离 Hub 与临时库，不连接用户服务或真实模型 |
| [生成器指南](/Users/forest/code/langGraph/flutter_forge/tool/agent_indexes/AGENTS.md) | 机器契约归生成器，禁止直接修改输出；支持声明不聚合历史验收 | 如所有权/依赖变化，修改生成源后完整生成和验证 |

流程定义版本、能力版本、HTTP 协议与 GenUI 组件目录身份分别判断。例如定义升级到 v2 不自动要求 articles.fetch 能力或 forge.workflow.v1 协议升级；也不能仅删除所有版本判断就允许任意步骤执行。只维护一个当前组合，以当前能力和受支持结构明确接受或拒绝。

## 实施顺序

| 编号 | 范围 | 完成条件 |
| --- | --- | --- |
| WF2-01 | session、文章 runner、包测试 | 同能力和受支持结构的当前 v2 可执行；未知能力/结构在副作用前拒绝；没有旧版本分发表 |
| WF2-02 | HTTP client、session、参数表单 | 提交/重试刷新目录；旧输入不合法要求调整；重试新 ID/requestKey 关联原运行，新执行端也可重试 |
| WF2-03 | session、runner、跨项目测试 | 排队/执行中升级均保留原历史；实际本地取消另行确认；旧租约和过期轮询不能复活任务 |
| WF2-04 | 状态接口与页面 | 展示目录摘要、实际运行版本、备份时间与错误，不暴露 token/租约；小屏大字体可用 |
| WF2-05 | Forge 生成源 | 仅在声明变化时更新所有者源，完整生成；生成物与 imports 一致，不弱化既有质量门禁 |
| WF2-06 | package/widget/真实 Hub fixture | 当前选择、升级、重试、新身份、故障、重连各有证据；本地测试、跨库联调和主机验收分开记录 |

单独保留 WF2-HOST：明确真实状态目录、解释器和日志位置后再准备离线每日维护调度。生成配置不是调度验收；要分别验证服务运行时锁冲突、服务关闭时备份，以及至少一次实际调度。该主机配置未执行。

## 下一次开工入口

先核对注册表、dev 分支、必需指南、选中路径指纹和 dirty 范围，再执行：

    PYTHONDONTWRITEBYTECODE=1 ./agent agent-context --project flutter-forge --profile workflow --max-files 40 --requirement "articles.explore workflow_workbench forge_articles hub_client" --output /明确的仓库外临时目录/workflow-context.json

新采集继续保留缺口与 dirty 状态；不扩大读取预算，不把多次快照合成完整覆盖声明。冻结 JSON 中的具体任务写路径及验收边界，保留网络诊断、桌面材质、GenUI 与依赖解析的并行工作。Forge 改动从 dev 开始，生成物不手改；Hub 本次推送不等于 Forge 提交、发布或系统服务操作已执行。

验证按相关包测试、工作流页面测试、隔离真实 Hub 联调、仓库完整质量门禁推进。Dart/Flutter 修改后还需按可用运行会话执行 hot reload/restart 并记录实际结果；没有运行会话时保留未验证，不能用 widget fixture 替代真实主机。当前准备阶段未运行 Forge 测试、生成器或业务构建。

继续延后远端 Hub、后台 executor、多租户、在线流程编辑、任意 DAG、模型生成可执行流程以及旧命令/旧库/旧执行实现兼容层。
