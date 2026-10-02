# Agent Hub Agent guide

## 维护入口

先读 `workspace/projects.json`、选中项目的 `workspace_config` 与 `langgraph.json`。项目身份和运行路径通过注册表解析；Forge、gcode-core、FlutterGuard 各自保持独立 checkout、namespace 和权限。

## 从图开始探索

- 关键 Agent 上下文使用 `./agent agent-context --project <id>`：先固定 Git 近期文件和关键契约，再向 `context_analysis`、`capability_analysis` 传递显式 `candidate_paths`。
- `max_files` 是证据预算；不传 `candidate_paths` 的旧解析入口可能遍历源码。本轮 Agent 更新不能调用该入口、全量 `WorkspaceRegistry.refresh()` 或用全库搜索替代定位。
- 有界快照只投影实际读取的文件和版本；缺失文件、过期缓存、未提交改动与未绑定当前 SHA 的验收必须保留为未知或待验证。
- 邻居依赖由注册元数据提供；不得因为引用关系自动读取其他仓库源码。
- 规则按实际源文件祖先目录解析，根到深层继承，同目录 `AGENTS.override.md` 为优先入口。必需指南与源码共用证据预算；缺指南必须记录路径和原因，不能将缓存缺失解释为没有规则。

## 所有权和执行边界

- Graph 负责 lifecycle、冻结、ScopeGuard、验证与集成；adapter 负责项目事实和能力归属。
- Forge 的机器契约由它的生成器维护；Hub 不直接修改生成物或把新工具 checkout 替代消费者的 immutable pin。
- gcode-core 独立拥有 parser/model/GPU，example 拥有会话与演示。维护者手测确认、历史报告、当前详细验收分开记录。
- FlutterGuard 是 executable-only CLI；IDE adapter 通过 JSON/SARIF 使用能力，不复制 detector 或规则注册表。其初始托管为只读 PLAN_ONLY，执行迁移需要另外冻结精确范围。
- 未经当前任务授权，不提交、推送、合并或发布。Release 必须经 `release-plan` 与 `release-run --execute`；核对远端大小及 SHA256 后才报告完成。

## 验证

先运行本次改动关联的 fixture 定向测试。验证有界入口时，将 walk/glob/rglob 设为报错，证明没有隐藏递归。真实业务改动和平台验收保持独立；Agent 文档更新不默认触发业务全量扫描或构建。
