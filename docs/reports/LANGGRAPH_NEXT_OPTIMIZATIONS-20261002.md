# LangGraph 后续优化分析 — 2026-10-02

## 当前基线

本轮是分析与独立审阅，没有修改生产实现、goldens 或重新运行完整同批基准。核对续接 state.json，8个关键代码/评估文件SHA256与暂停时一致。既有47项定向测试是该版本已取得的证据，不记为本轮新测试。

审阅固定点为 cde1adb，范围为未提交的有界context/capability、agent_context、CLI及评价脚本。标准来源AGENTS.md与README 5.2.1；需求来源会话和LANGGRAPH_RULE_OPTIMIZATION-20261002.md。两个review轴独立执行，以下分别保留结论。

当前样本：10正例、2负例，各中英文成对，共24次查询。规则入口15/15是最低路径期望的覆盖，不等于每条规则都正确绑定到所有目标文件，也不等于整体理解质量100%。

| 指标 | 保存的规则优化后结果 |
| --- | --- |
| 关键文件覆盖 | 19/25，76% |
| 中文具词法证据文件 | 3/25，12% |
| 英文具词法证据文件 | 8/25，32% |
| 规则路径覆盖 | 15/15，100% |
| 端到端归属 | 2/5，40% |
| 有预测节点归属 | 2/4，50%；保留unknown分母 |

## Standards

1. **P1：只读入口允许覆盖托管仓库文件。** agent_context.py:334-345只保护registry文件，随后直接写入任意output。临时fixture标记writable:false，output设为业务pubspec或源码后，文件被快照JSON覆盖，结果仍声明read_only_business_repositories=true。违反根AGENTS独立权限和FlutterGuard只读接入边界。建议在执行前验证解析后的输出路径，排除全部托管仓库、workspace配置和注册表。
2. **P2：Git依赖锁定状态忽略子目录。** agent_context.py:118-122仅比较URL/ref；manifest git.path=packages/current而lock path=packages/stale，仍返回DECLARED_AND_LOCKED且gaps为空。临时内存样例已验证；尚未发现当前三库实际出现该差异。应比较规范化git.path，保留消费者精确来源。

判断性维护建议：入口和评价脚本重复构造临时registry/config/state；agent_context.py同时承担Git intake、依赖绑定、规则预算和输出职责。优先将输出校验与依赖绑定拆成明确边界，再考虑参数类型化，避免为重构而扩大范围。

Standards共2项硬问题；最严重为P1只读写入边界。

## Spec

1. **P1：快照SHA与实际分析内容可能不一致。** 需求要求记录实际观察文件及SHA。agent_context.py:261-270先计算SHA，294-296让两图重新读工作区；resolver与analyzer仍读盘。fixture在首次读取后将Parser改成Widget，保存旧SHA但symbols来自新widget，未记录漂移。建议两图消费同一冻结文本，或在分析后复核hash并使漂移结果失效。
2. **P2：CLI把失败报告为成功退出。** agent:42-44无条件返回0；helper存在UNKNOWN_PROJECT_OR_CONTEXT_POLICY与CONTEXT_REFRESH_FAILED。真实CLI临时样例对未知project返回0且refreshed=0。建议全失败非零，部分失败输出逐项目原因与明确状态。
3. **P2：评价脚本漏计实际建议类型。** scripts/evaluate_agent_context_hits.py:68的集合与analyzer.py:84-86不一致，漏掉MOVE_TO_EXISTING_UNIT、EXTEND_EXISTING_UNIT、NEW_SHARED_CORE_CANDIDATE等。应共享decision定义；当前recommendation计数不能用于判断噪声下降。

优化候选：

- 指南全部前置会使预算只容纳指南而排除本可纳入的高优先源码；fixture预算3被根与两个低优先分支指南占满，产生0源码。建议按每个候选的“源码＋必需祖先指南”完整成本分配预算，保留硬上限和不缺指南原则。
- 规则评价应同时度量(rule.path, applies_to)，不能仅按规则路径去重。指南只作用于自身，也可能通过当前15/15路径指标；增加源码目标配对和错误scope分母。

Spec共3项缺陷、2项优化候选；最严重为P1证据hash与分析文本不一致。

## 命中质量的后续优化

| 方向 | 当前证据 | 建议与验收 |
| --- | --- | --- |
| 能力身份与证据类型 | ID=unit+basename；Forge两份AGENTS同ID、四份AI_ANALYSIS同ID，Guard八份AGENTS同ID；14/21 Markdown为HIGH且非unknown | 使用repo-relative完整路径构造稳定ID；区分指南/契约描述与源码能力，节点ID全部唯一，文档不能仅凭关键词生成HIGH源码归属 |
| 中文词项与symbol分配 | 中文8/10正例terms为空；英文8/10耗尽80符号。Guard三类英文查询的80条均来自Markdown | 领域双语别名、标识符拆词、泛词降权；按任务类型分配source/config/docs证据，先给每个相关文件机会；保持文件24和symbols80预算检验 |
| 按需求选择候选 | 6漏选中4未进池、1被prefix排除、1预算淘汰；agent-context没有requirement参数，使用固定提示 | 增加任务需求入口，按注册主题与明确imports/exports/脚本引用有界扩展；不要硬编码golden路径，新增独立holdout验证 |
| 归属角色证据 | CLI参数/输出适配被判unknown；IDE annotator被判platform_plugin，suffix包含子串ffi也会触发平台耦合 | 使用词边界/语言token、imports和职责证据，区分CLI/IDE adapter与真实FFI插件；保留现有orchestration和GPU ui_only正确样本 |
| 查询支持与评估 | 同一项目不同查询输出同样的文件能力集合；尚无支持/不支持/证据不足结论schema | 文件自身归属应稳定，另标记与当前需求的相关性及支持证据。补无证据弃答、完整相关性标签和留出样本；precision/语义负例误提升率继续不乱计 |

六个具体漏选：gcode parser/model、Forge build_web_release.sh、FlutterGuard rules/registry.dart均未进候选池；Forge setup.iss被change_prefix排除；BLE ble_session.dart因预算被淘汰。单纯增加max_files最多直接解决其中一项。

预算饥饿示例：Forge主题英文在tool/generate_agent_indexes.js:47达到80条，其中70条Markdown；Guard stdout英文在lib/src/cli/AGENTS.md:21用满80条，源码尚未获得词法证据。配置、工作流、脚本对发布问题可能是正确证据，不能统一排除所有非Dart文件。

## 建议下一阶段

先分别完成Standards和Spec中的正确性修正，确保后续测量可信。命中质量按“能力身份/类型 → 多语言与公平预算 → 需求驱动候选 → 归属角色 → 查询支持schema”开展小步验证。保留现有case不变，另增holdout；规则路径15/15保持，同时新增规则—源码配对覆盖，不能只追单一命中率。

建议阶段验收（目标，尚未实施）：输出不能写入托管库；同次分析内容与hash一致；失败CLI非零；节点ID无碰撞；建议枚举统计完整；24文件/80symbol约束下提高关键文件与中文证据覆盖，并保留未知与范围边界。

## 证据

- 基准：benchmarks/agent_context_runs/20261002-rules-optimized/{intake,results}.json。
- 临时复现：/private/tmp/langgraph-next-analysis/probes.json（仅临时仓库数据）。
- 文档节点与ID：/private/tmp/langgraph-next-analysis/quality-diagnostics.json。
- 生产源码未修改；本轮新增分析报告并更新续接状态。未提交或推送。
