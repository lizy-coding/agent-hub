from langgraph_sdk import get_sync_client

SERVER = "http://127.0.0.1:2024"
GRAPH = "development"
THREAD_ID = "019ff8bc-e2de-76d1-8386-4c08fdbaf5a6"

client = get_sync_client(url=SERVER)

requirement = """
继续 flutter-study-refactor-program，进入全项目持续重构模式。

当前目标不是完成一个局部 task，而是完成 flutter_study 全仓 architecture inventory、
任务拆解、dependency DAG 和所有当前可安全执行的 behavior-preserving refactor。

PRIMARY repository:
flutter_study

全局扫描范围：
- lib/app/**
- lib/modules/**
- packages/**
- test/**
- tool/**
- pubspec.yaml
- AGENTS.md
- **/AGENTS.override.md

必须覆盖全部实际 DevelopmentUnits。

重点识别：
1. application / capability 边界
2. WorkspaceSession / controller / provider / runtime / read-model ownership
3. device / io / preview / render / materials / editor 依赖方向
4. UI 与业务逻辑、基础设施逻辑混杂
5. 重复 facade / service / controller / state
6. 超大职责文件
7. 跨模块隐式依赖
8. packages/** 与主应用边界
9. public API 与内部实现耦合
10. 测试与 validation 边界
11. behavior-preserving refactor 候选

首先刷新 RefactorProgram：
- architecture_summary
- development_units
- workstreams
- architecture_issues
- tasks
- dependency_dag
- execution_order
- blocked_decisions

已有 DONE task 保持 DONE，不重复执行。

然后立即进入自动执行循环：

while 存在 READY task:
    选择 dependency 已满足、无 blocker、风险最低的 task
    重新获取最新 context
    解析 applicable AGENTS rules
    candidate_paths -> exact allowed_paths
    freeze DevelopmentTask
    execute_code
    Worker isolated worktree
    Codex
    ScopeGuard
    targeted validation
    flutter analyze baseline comparison
    tracked + untracked diff
    Reviewer

    if APPROVED:
        task = DONE
    elif 可以在 frozen scope 内修复:
        修复并重新验证
    elif 需要人工架构决策:
        task = BLOCKED_DECISION

    更新 RefactorProgram
    继续下一个 READY task

执行约束：
- 一次只允许一个 frozen DevelopmentTask 修改代码
- flutter_study/packages/** 属于 PRIMARY 内部 DevelopmentUnits
- 外部 gcode_core / file_picker_bridge 等仓库只读
- 不跨 allowed_paths
- 不执行 dart format .
- 不运行会全仓格式化的 quality_gate.sh
- 只格式化当前修改 Dart 文件
- ScopeGuard 检查 tracked + untracked
- flutter analyze 以既有 diagnostics 为 baseline
- 原有 .hermes/** 保持不变
- 不 commit
- 不 push
- 不 merge
- 不 release

Program 不得仅因为当前 READY task 数量为 0 就直接 COMPLETED。

只有满足以下条件之一才能结束：

A. 全部 DevelopmentUnits 已完成 architecture inventory，
   所有 evidence-backed tasks 均 DONE；

B. 剩余未完成任务全部是 BLOCKED_DECISION；

C. 全仓再次扫描后不存在新的 evidence-backed、
   behavior-preserving refactor 候选。

不要返回到基础设施建设。
不要讨论 Studio、Tunnel、Cloudflare 或 Deployment。
直接执行现有重构系统。
"""

for event in client.runs.stream(
    THREAD_ID,
    GRAPH,
    input={
        "requirement": requirement,
        "program_id": "flutter-study-refactor-program",
        "business_write": True,
    },
):
    print(f"\n[{event.event}]")
    print(event.data)
