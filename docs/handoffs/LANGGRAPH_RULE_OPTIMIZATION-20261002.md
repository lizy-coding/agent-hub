# LangGraph 规则入口优化续接记录 — 2026-10-02

状态：用户要求暂存进度；实现与测量已保存在本地，停在独立审阅与最终收尾之前。本轮改动尚未提交或推送。

## 目标与边界

从 Agent Hub 现有 LangGraph context/capability 能力出发，维护 Forge、gcode-core、FlutterGuard 关键 Agent，再验证命中率并优化全项目通用规则入口。

采用注册表 + 近期 Git 路径 + 显式候选文件。不调用真实仓库 Legacy 无范围解析、不运行全库源码扫描或 WorkspaceRegistry.refresh。单项目实际证据预算保持 24；两图运行时禁止 walk/glob/rglob/discover/refresh。

## 已完成

1. 更新 Agent Hub 根指南、注册/CLI/快照入口；FlutterGuard 独立 generic 只读 PLAN_ONLY 接入，Forge alias→flutter-forge。
2. 更新外部 9 份 Agent/CONTEXT 文档：Forge 根/app/generator 3份；gcode-core 根1份；FlutterGuard 根/CONTEXT/CLI/scripts/IDE 5份。已通过明确路径授权应用，保留业务源码及原有dirty改动。
3. 两图支持 bounded candidate_paths/limits；新 agent_context 入口记录版本、消费者 pins、文件SHA、工作区差异和未知，不伪称整库验收。
4. gcode-core adapter 分开当前0.2.1维护者手测确认、历史macOS报告、当前详细验收PENDING；补GPU metadata及native readers所有权。
5. 冻结独立10正例+2负例；每个中英文成对执行共24次查询。must_hit只是关键路径下限，precision没有评分。
6. 修复通用规则解析：按实际文件祖先目录根→深层继承；同目录override优先且不可用时不降级；有界模式只采用已选且已成功读取的规则，明确missing/unknown；cached CONTEXT/ADR按scope和边界过滤。
7. 修复intake规则预算：必需祖先指南前置于同一max_files预算；不可用指南导致相关源文件排除并记录具体缺口，未扩大全库搜索。

## 冻结样本前后结果

| 指标 | 基线 | 优化后 |
| --- | --- | --- |
| 关键文件覆盖 | 19/25，76% | 19/25，76% |
| 规则入口覆盖 | 4/15，26.7% | 15/15，100% |
| 中文：具词法证据关键文件 | 3/25，12% | 3/25，12% |
| 英文：具词法证据关键文件 | 6/25，24% | 8/25，32% |
| 端到端归属 | 2/5，40% | 2/5，40% |
| 已产生节点归属（unknown仍在分母） | 2/4，50% | 2/4，50% |

规则按项目：Forge 4/6→6/6；gcode-core 0/3→3/3；FlutterGuard 0/6→6/6。15条是10个case的最低规则期望，不是整个工程所有指南覆盖率。

固定case语义SHA256：`10e612ad49525528b0cce6144d8973b00cd10275ff645c8ef94ac54481500e9a`。仅修正过goldens的limitations文本，未调整case预期来迁就结果。

## 已获得验证

- 新规则11 + bounded7 + intake13 = 31项PASS；相关配置/adapter16项PASS；合计47项定向测试通过。
- 有红→绿记录，覆盖无/旧缓存、root-only generic下嵌套指南、override、兄弟scope隔离、symlink/越界/不可读、预算不足、legacy unit API。
- 实际三项目图测量在递归入口禁用状态下通过；没有把supplied→returned=100%当检索命中率。
- 负例没有输出“支持已验证”结论的schema，本轮语义误提升率未评分；既有HIGH ownership不能当支持不存在能力的证据。
- 原字段 unrelated_actionable_suggestions 误含UNKNOWN，control_nodes还含脚本；新评价脚本改为query_unfiltered_recommendations与严格markdown统计。基线旧JSON保留原字段，解读需注意。

## 本地关键文件

- `AGENTS.md`、`agent`、`README.md`、`workspace/projects.json`、`workspace/flutterguard.json`。
- `src/agent_hub/context/resolver.py`、`capability/analyzer.py`、`graphs/context_analysis.py`、`graphs/capability_analysis.py`。
- `src/agent_hub/projects/agent_context.py`、`gcode_core_adapter.py`。
- `tests/test_rule_entrypoints.py`、`test_agent_context.py`、`test_bounded_context.py`、`test_gcode_core_adapter.py`。
- `scripts/evaluate_agent_context_hits.py`。
- `benchmarks/agent_context_goldens/cases.json`。
- 基线：`benchmarks/agent_context_runs/20261002-baseline/{intake,results}.json`。
- 优化后：`benchmarks/agent_context_runs/20261002-rules-optimized/{intake,results}.json`。
- 旧 `20261002-basic` 结果是原基线副本；不要把新运行覆盖到冻结baseline。
- `workspace/agent-context.json` 仍是前轮快照；新规则后的快照在optimized/intake.json。恢复后如需要，重跑主快照入口。

## 尚未完成与续接顺序

1. 先读本记录与同名state.json，检查四库当前HEAD/status及关键文件hash；保留Forge主题/BLE和FlutterGuard workflow/.hermes等已有工作。
2. 完成独立实现审閱：forge_hit_goldens 的只读review在暂停前中断，尚无最终结果。重点检查override不降级、scope隔离、指南预算闭包和隐含读取；发现缺陷才修复。
3. 必要时合并复跑47定向测试并刷新主快照；不自动执行全库测试/扫描。
4. 将前后结果写入正式评估报告，修订原Agent更新报告中“当前快照”的指向。若用户要求交付，再按仓库分组提交；推送需要明确授权。
5. 后续优化候选：六个关键源文件漏选、多语言检索、source/control symbol预算、文档归属置信度和query绑定。它们尚未实施，不能把规则修复等同于整体分析READY。

明确的关键文件漏选：
- `apps/flutter_forge/lib/modules/platform/bluetooth_ble/state/ble_session.dart`
- `apps/flutter_forge/windows/installer/setup.iss`
- `lib/src/models/toolpath_segment.dart`
- `lib/src/parser/gcode_parser.dart`
- `lib/src/rules/registry.dart`
- `tool/build_web_release.sh`

## 复跑命令

```bash
cd /Users/forest/code/agent-hub
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest tests.test_rule_entrypoints tests.test_bounded_context tests.test_agent_context tests.test_gcode_core_adapter tests.test_decomposition_projects tests.test_runtime_workspace tests.test_project_adapters
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/evaluate_agent_context_hits.py --output benchmarks/agent_context_runs/REPLACE_WITH_NEW_RUN_NAME
PYTHONDONTWRITEBYTECODE=1 ./agent agent-context --max-files 24
```

当前基线和完整工作树状态见同目录 `LANGGRAPH_RULE_OPTIMIZATION-20261002-state.json`。本记录不修改历史验收、基准golden或业务实现。

## 续接分析补充 — 2026-10-02

独立Standards/Spec审阅已完成，详见 docs/reports/LANGGRAPH_NEXT_OPTIMIZATIONS-20261002.md。新增确认5项问题（只读output写入边界、git.path绑定、分析内容/hash漂移、CLI失败退出、recommendation枚举计数），均未修复；能力ID碰撞和文档置信度问题另有冻结结果证据。本轮遵循“继续分析”范围，生产代码和goldens未改。下一步应以新报告为优化清单，原实现审阅待办已完成。
