# 架构控制与仓库维护进度 — 2026-10-02

## 本轮范围

落实执行链路 P0：必需验证、执行身份、同仓库单写入者，以及发布远端内容校验。
仓库维护进度落实为逐仓持久化集成记录、恢复与 dashboard 展示。
不执行业务迁移，不发布，不提交或推送。本报告不代表业务平台验收。
命中率、查询、上下文和基准由另一会话维护，不属于本轮改动。

## 当前控制

| 控制 | 实现 | 证明 |
| --- | --- | --- |
| 必需验证 | Graph 冻结 validation_by_repository；Worker 以固定 argv 执行；回执绑定完整输出树；验证修改源码即失效 | 实际 Python unittest 子进程，失败、缺失、被篡改回执与树漂移 fixture |
| 执行身份 | project/task + contract_sha256 + attempt_id + generation；可信本地记录与请求、回执逐项核对 | 旧 attempt、契约变更、回执变更、重复请求 fixture |
| 单写入者 | 按 Git common-dir 排序获取 OS 锁，开发/拆解 worktree 共用仓库身份；发布另按 repo/tag 加锁 | 跨进程竞争、同 Git 仓库不同 worktree、发布锁竞争 fixture |
| 完成门禁 | 开发与拆解 Graph 均消费同一校验/集成模块；未知旧契约不能进入提交 | 两条 Graph → 真 Worker → 验证 → 集成的闭环 fixture |
| 集成进度 | 所有仓库先预检；逐仓 PENDING/APPLYING/COMMITTED + commit/tree/gate 原子落盘 | 两仓库第二次提交失败；重试不重复第一仓；commit 后落盘前崩溃恢复 |
| 状态恢复 | 从可信记录恢复 collector 结果后重校验；部分集成不允许新 attempt 抹除 | 部分集成拒绝重新 reserve；集成完成但 Graph 尚未 DONE 的恢复 fixture |
| 发布完整性 | 上传前重算本地产物；发布与远端回读在同一锁内；下载精确资产核对大小和 SHA256 | 同大小不同内容、下载失败、预检后产物漂移 fixture |
| 未实现入口 | migration_execution 明确返回 EXECUTION_NOT_IMPLEMENTED/complete=false | 无副作用失败 fixture |
| 进度展示 | decomposition dashboard 按 task/repository 展示 phase、commit、gate | 部分 COMMITTED/APPLYING 展示 fixture |

## 冻结验证格式

提案可请求验证，adapter 仍负责候选与归属，Graph 冻结并校验命令标识。
旧任务缺少此字段会阻塞为 REQUIRED_VALIDATION_MISSING，必须补充精确检查再冻结；
不会以默认空检查或人工描述补成 PASS。

```json
{
  "validation_by_repository": {
    "product": [
      {"check_id": "flutter_analyze", "cwd": "apps/product", "timeout_seconds": 300},
      {"check_id": "flutter_test:test/domain_test.dart", "cwd": "apps/product", "timeout_seconds": 300}
    ]
  }
}
```

支持 flutter_analyze/flutter_test/flutter_test:<path>、dart_analyze/dart_test、
flutter_build[:macos|windows|apk] 和 python_unittest:<module>。不接受 shell、任意
可执行文件、额外参数或越界 cwd；所有冻结检查为必需检查，未运行不能算通过。
裸 flutter_build 保留 macOS debug 别名。平台手测与运行验收仍需独立证据。

## 维护进度的来源与恢复

可信控制目录默认 `.execution/control`，Graph 与本地 Worker 必须使用同一目录。
HTTP 请求不能指定该目录；远端/不同宿主 Worker 没有对应记录时直接拒绝。
控制记录为 execution-control.v1，状态保存采用临时文件、fsync 与原子替换。
仓库锁使用 OS 生命周期；PID 仅作诊断，不用于认定进程仍在运行。

逐仓集成记录包含冻结基线、预期树、phase、commit 和完成 gate，dashboard
只投影这些事实。恢复必须核对真实提交父节点、完整提交消息及树对象。
部分集成保留已提交仓库，不自动回滚、不新建 attempt 覆盖进度。

旧 checkpoint 没有身份绑定的成功结果不再允许继续提交；需重新冻结执行。
没有 runnable task，但仍有未完成任务/依赖时报告 PROGRAM_INCOMPLETE。
PLAN_ONLY 即使带有保存的 SUCCESS 回执，也不会进入集成。

## 验证边界

本轮测试仅使用临时 Git 仓库、测试程序和模拟远端 Release，未构建业务项目、
未使用真实设备，也未执行真实发布。macOS 本地锁有跨进程验证；Windows 的
msvcrt 分支与其他宿主实际执行尚未验收。

集成的 Git-only 严格模式仍拒绝忽略文件；测试运行在 Worker 的隔离树中，
不会将缓存带入受管集成树。历史集成事实与后续版本的新鲜度分层、非 Git
依赖内容清单、平台环境资格等 P1 保留为后续任务。

## 定向检查

```sh
PYTHONPATH=src PYTHONPYCACHEPREFIX=/tmp/agent-hub-pycache \
  .venv/bin/python -m unittest discover -s tests -p test_execution_control.py -v
PYTHONPATH=src PYTHONPYCACHEPREFIX=/tmp/agent-hub-pycache \
  .venv/bin/python -m unittest discover -s tests -p test_release_integrity.py -v
```

关联回归包含 completion_evidence、decomposition、Worker bridge、development
reconciliation、refactor orchestration、project adapters、release program、runtime
bootstrap。Worker HTTP fixture 需要本地临时 loopback 端口权限。
