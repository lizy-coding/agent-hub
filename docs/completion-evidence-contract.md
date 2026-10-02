# 完成状态校验契约（独立试点）

本试点仅新增 `execution/completion_evidence.py` 与定向 fixture；未接入
Graph、Worker、CLI、注册表或共享 schema，未改变现有 DONE 判定。
它校验单仓库、单冻结任务的结果，不负责调度、执行、修复或发布。

## 权威来源

调用方必须是可信 Graph/证据收集器，独立构造冻结契约与证据绑定。
不得从 Worker 返回值同时构造“预期值”和“实际值”，否则相等校验无意义。

`EvidenceBinding` 的身份是：

- `project_id`、`repository_id`、`task_id`：来自冻结任务与注册表映射。
- `contract_sha256`：调用方对完整冻结契约规范化序列化后计算的 SHA256；
  契约包含精确路径、验证命令及环境要求、平台验收要求和 no-effect 策略。
- `source_revision`：冻结任务的完整 Git 基线 OID。
- `output_tree_oid`：可信收集器捕获的完整待验证输出树 OID。
  它绑定内容，不用源基线 SHA 冒充改动后的验证版本。

契约冻结与输出树捕获是两个时点。输出树变化后，原验证/验收回执失效，
需要重新收集。本模块不构造输出树，不执行 `git add` / `write-tree`。

输入为冻结 dataclass，路径和要求为不可变 tuple。仅支持精确文件路径，
不支持目录前缀、glob、隐式邻仓读取。验证要求至少一项。

## 四个里程碑

| 请求 | 所需证据 |
| --- | --- |
| EXECUTED | 身份一致、SUCCESS、scope PASS、变更不越界、非空变更（除非冻结契约显式允许 no-effect） |
| VALIDATED | EXECUTED + 每个必需 check 恰有一份身份一致、通过且含证据引用和环境的回执 |
| INTEGRATED | VALIDATED + review APPROVED + 本地 Git 回读证明 |
| PLATFORM_ACCEPTED | INTEGRATED + 非空平台要求 + 每个平台唯一的产物与操作/回读回执，绑定身份和产物 SHA256 一致 |

执行完成不自动升级为验证或验收。请求更高里程碑会校验全部前置条件。
返回 `GateResult(milestone, issues)`，仅无 issue 时 `passed=True`。
使用结构化 issue code 做上层分支，不解析展示文本。

Git 回读要求：提供的路径是实际仓库根；提交等于当前 HEAD；工作区无
已修改、暂存、未跟踪或忽略文件；实际提交树等于输出树；源基线是其祖先；
实际 diff 与回执路径完全相同且落在冻结范围内。关闭 rename 折叠以保留
删除源路径，禁用 Git replace 对象和可选索引更新，Git 调用有超时。
提交不存在、Git 不可用、祖先关系不成立或超时保留为 GIT_PROOF_UNAVAILABLE。

## 信任边界与后续接入

- 本模块直接核对 Git 事实；测试、产物哈希、设备操作与回读是可信收集器
  的回执，模块不验证引用文件内容、不运行测试、不读取真实设备。
  fixture PASS 不是任何业务项目的平台验收。
- EXECUTED / VALIDATED 针对供应的输出快照，不声明当前可变工作区新鲜度。
- Git 检查是即时只读观察，并非事务锁。接入 Graph 时必须在冻结的执行
  临界区内收集与消费证据，避免检查之后工作区又变化。
- 当前 Git-only 严格模式拒绝忽略文件。真实构建目录通常含此类文件；未来
  如需放宽，应对验证相关的非 Git 输入另加内容清单，不能直接忽略 dirty。
- 环境字段目前要求非空，由冻结 check_id 及可信 collector 约束具体 host /
  device 资格；模块尚不解析环境描述或区分 emulator 与 physical device。
- 多仓库任务需由 Graph 对每个仓库单独校验，再在全部结果通过时聚合。
- `contract_sha256` 是调用方提供的绑定值；本模块不替调用方重新冻结契约。
- 未授权任何 release、push、merge 或业务仓库写入。

下一步接入前，应由单一会话负责共享结果映射：从已有 WorkerResult 提取
执行回执，由 Graph 获取实际 Git 树及验证回执，调用校验器并投影里程碑。
此时才修改现有 Graph；不能直接信任 Worker 自报 `passed` 或 `DONE`。

## 定向验证

```sh
PYTHONPATH=src PYTHONPYCACHEPREFIX=/tmp/completion-evidence-pycache \
  python3 -m unittest discover -s tests -p test_completion_evidence.py -v
```

测试只使用临时 Git 仓库，覆盖旧绑定、空 diff、失败/中断、验证缺失/重复、
Git 树/提交/路径不匹配、脏工作区、重命名、多平台证据缺口及产物不匹配。
另将 Python walk/glob/rglob 设为报错，并核对源码、HEAD 与索引字节未变化。
