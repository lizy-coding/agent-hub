"""Small, evidence-backed development orchestration graph.

Business files are never touched here.  A frozen task is the only value sent
to the local Worker, which creates its own disposable worktree.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Literal, TypedDict
from urllib.request import Request, urlopen

from langgraph.graph import END, START, StateGraph

from agent_hub.projects import api as registry_api
from agent_hub.execution.primary_apply import apply_approved, validate_applied
from agent_hub.workspace.config import WorkspaceConfig
from agent_hub.workspace.runtime import RuntimeWorkspaceProvider


class DevelopmentState(TypedDict, total=False):
    requirement: str
    repository_id: str
    program: dict[str, object]
    development_task: dict[str, object]
    worker_result: dict[str, object]
    primary_apply: dict[str, object]
    result: dict[str, object]


def _call_worker(task: dict[str, object]) -> dict[str, object]:
    endpoint = os.environ.get("AGENT_HUB_CODE_WORKER_ENDPOINT")
    if not endpoint:
        return {"status": "BLOCKED_EXECUTION_ENVIRONMENT", "reason": "code_worker_endpoint_unconfigured"}
    worker_url = endpoint.rstrip("/")
    if not worker_url.endswith("/execute"):
        worker_url += "/execute"
    request = Request(
        worker_url,
        data=json.dumps(task).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=600) as response:
            return json.loads(response.read())
    except OSError as error:
        return {"status": "BLOCKED_EXECUTION_ENVIRONMENT", "reason": "code_worker_unreachable", "detail": str(error)}


def _line(path: Path, needle: str) -> int:
    for number, value in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if needle in value:
            return number
    return 1


def _ref(path: Path, root: Path, needle: str) -> str:
    return f"{path.relative_to(root).as_posix()}:{_line(path, needle)}"


def _rules_for(path: Path, root: Path) -> list[str]:
    rules: list[str] = []
    for parent in (path.parent, *path.parents):
        for name in ("AGENTS.md", "AGENTS.override.md"):
            candidate = parent / name
            if candidate.is_file():
                rules.append(candidate.relative_to(root).as_posix())
        if parent == root:
            break
    return rules


def _new_program(config: WorkspaceConfig, repository_id: str, completed: list[str] | None = None) -> dict[str, object]:
    """Build only tasks supported by exact source evidence.

    The first task removes a demonstrably thin, private router facade.  It is
    deliberately narrow so the first Worker invocation proves the complete
    isolation/review path without inventing broad architectural changes.
    """
    registry_api.refresh(config)
    repository = registry_api.get_repository(config, repository_id)
    if repository is None:
        return {"program_id": "flutter-study-refactor-program", "status": "BLOCKED", "blocked_tasks": [{"reason": "primary_repository_not_found"}]}
    root = repository.path.resolve()
    units = [
        {"unit_id": unit.unit_id, "path": unit.relative_path, "type": unit.unit_type, "evidence": [item.path for item in unit.evidence]}
        for unit in repository.development_units
    ]
    app = root / "lib/app/app.dart"
    router = root / "lib/app/router/app_router.dart"
    table = root / "lib/app/router/app_route_table.dart"
    task: dict[str, object] | None = None
    if app.is_file() and router.is_file() and table.is_file():
        app_text, router_text = app.read_text(encoding="utf-8"), router.read_text(encoding="utf-8")
        if "AppRouter.router" in app_text and "static final GoRouter router" in router_text and "AppRouteTable.routes" in router_text:
            task = {
                "task_id": "app-router-private-facade",
                "title": "Inline the private AppRouter facade into the application shell",
                "development_unit": f"{repository_id}:." if any(unit["path"] == "." for unit in units) else repository_id,
                "evidence": [_ref(app, root, "AppRouter.router"), _ref(router, root, "static final GoRouter router"), _ref(router, root, "AppRouteTable.routes")],
                "candidate_paths": ["lib/app/app.dart", "lib/app/router/app_router.dart"],
                "expected_change": "Keep the same GoRouter configuration while removing the one-use forwarding facade.",
                "invariants": ["MaterialApp.router continues to receive AppRouteTable.routes", "No route path, module metadata, or public package API changes", "No AGENTS.md-generated document changes"],
                "validation": ["flutter_analyze"],
                "dependencies": [],
                "risk": "LOW",
                "status": "READY",
                "rules": sorted(set(_rules_for(app, root) + _rules_for(router, root))),
            }
    completed = completed or []
    tasks = [task] if task else []
    for item in tasks:
        if item["task_id"] in completed:
            item["status"] = "DONE"
    blocked = [] if task else [{"task_id": "app-router-private-facade", "reason": "exact facade evidence no longer matches current source"}]
    return {
        "program_id": "flutter-study-refactor-program",
        "repository": repository_id,
        "base_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
        "architecture_summary": "The root Flutter application owns bootstrap and routing; lib/modules contains teaching capabilities; packages are manifest-backed internal development units. The G-code visualizer controller combines file picking, incremental parsing, animation playback, and UI state, so its ownership split requires an explicit lifecycle decision rather than an automatic refactor.",
        "development_units": units,
        "workstreams": ["app orchestration boundary", "module capability boundaries", "internal package call topology"],
        "architecture_issues": [
            {"issue": "private routing facade", "evidence": task["evidence"] if task else [], "status": "ACTIONABLE" if task else "NO_LONGER_ACTIONABLE"},
            {"issue": "large capability implementations require module-specific evidence before refactoring", "evidence": [_ref(table, root, "final List<ModuleEntry> _modules")], "status": "DEFERRED"},
            {"issue": "G-code controller mixes platform picking, parser pipeline, animation and read-model state", "evidence": [_ref(root / "lib/modules/ui/gcode_visualizer/state/gcode_player_controller.dart", root, "class GcodePlayerController"), _ref(root / "lib/modules/ui/gcode_visualizer/state/gcode_player_controller.dart", root, "pickFilePathAndLoad"), _ref(root / "lib/modules/ui/gcode_visualizer/state/gcode_player_controller.dart", root, "AnimationController")], "status": "BLOCKED_DECISION", "reason": "A behavior-preserving split needs a decided owner for TickerProvider/lifecycle and FilePicker failure presentation."},
            {"issue": "CategoryNavigation is a platform-navigation boundary rather than a duplicate facade", "evidence": [_ref(root / "lib/app/category_navigation.dart", root, "class CategoryNavigation"), _ref(root / "lib/app/category_navigation.dart", root, "MultiWindowManager.instance.createCategoryWindow")], "status": "NO_ACTION"},
        ],
        "tasks": tasks,
        "dependency_dag": {str(item["task_id"]): item["dependencies"] for item in tasks},
        "execution_order": [str(item["task_id"]) for item in tasks],
        "current_task": None,
        "completed_tasks": completed,
        "blocked_tasks": blocked,
        "status": "READY" if any(item["status"] == "READY" for item in tasks) else "COMPLETED",
    }


def _select(program: dict[str, object]) -> dict[str, object] | None:
    completed = set(program.get("completed_tasks", []))
    candidates = [task for task in program.get("tasks", []) if task.get("status") == "READY" and set(task.get("dependencies", [])).issubset(completed)]
    return min(candidates, key=lambda task: (task.get("risk") != "LOW", task["task_id"])) if candidates else None


def build_development_graph(config: WorkspaceConfig):
    provider = RuntimeWorkspaceProvider.from_config(config)

    def bootstrap_runtime(state: DevelopmentState):
        return {"result": {"runtime_workspace": provider.workspace.model_dump(mode="json")}}

    def resolve_requirement_context(state: DevelopmentState):
        existing = state.get("program")
        if existing:
            if "apply approved" in state.get("requirement", "").lower():
                for item in existing.get("tasks", []):
                    if item.get("task_id") == "app-router-private-facade" and item.get("status") == "DONE":
                        item["status"] = "APPROVED"; existing["current_task"] = item["task_id"]
                        existing["completed_tasks"] = [value for value in existing.get("completed_tasks", []) if value != item["task_id"]]
                        existing["status"] = "READY"
                return {"program": existing}
            if "retry primary validation" in state.get("requirement", "").lower():
                return {"program": existing}
            if "extend" in state.get("requirement", "").lower() or "inventory" in state.get("requirement", "").lower():
                return {"program": _new_program(config, state.get("repository_id", "flutter_study"), list(existing.get("completed_tasks", [])))}
            retryable = any(item.get("reason") == "dependency_preflight" for item in existing.get("blocked_tasks", []) if isinstance(item, dict))
            if "retry" not in state.get("requirement", "").lower() or not retryable:
                return {}
        # Retain the narrow frozen-task bridge contract for callers that have
        # already performed planning outside this graph (and its existing test).
        supplied = state.get("development_task")
        if isinstance(supplied, dict):
            task_id = str(supplied.get("task_id", "externally-frozen-task"))
            return {"program": {"program_id": "externally-frozen-task", "repository": "flutter_study", "tasks": [{"task_id": task_id, "candidate_paths": supplied.get("allowed_paths", []), "expected_change": supplied.get("requirement", ""), "validation": supplied.get("validation", []), "dependencies": [], "risk": "LOW", "status": "READY"}], "dependency_dag": {task_id: []}, "completed_tasks": [], "blocked_tasks": [], "current_task": None, "status": "READY"}}
        return {"program": _new_program(config, state.get("repository_id", "flutter_study"))}

    def plan_change(state: DevelopmentState):
        return {}

    def policy_gate(state: DevelopmentState):
        return {}

    def prepare_task_workspace(state: DevelopmentState):
        program = state["program"]
        if "apply approved" in state.get("requirement", "").lower() and program.get("current_task"):
            return {}
        selected = _select(program)
        if selected is None:
            return {"result": {**state.get("result", {}), "status": program["status"], "program": program}}
        if program["program_id"] == "externally-frozen-task":
            program["current_task"] = selected["task_id"]
            return {"program": program}
        root = Path(registry_api.get_repository(config, str(program["repository"])).path)
        frozen = {
            "repository": "flutter_study",
            "base_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
            "task_id": selected["task_id"],
            "requirement": selected["expected_change"],
            "allowed_paths": selected["candidate_paths"],
            "validation": selected["validation"],
        }
        program["current_task"] = selected["task_id"]
        return {"program": program, "development_task": frozen}

    def execute_code(state: DevelopmentState):
        if "apply approved" in state.get("requirement", "").lower() or "retry primary validation" in state.get("requirement", "").lower(): return {}
        task = state.get("development_task")
        return {"worker_result": _call_worker(task)} if isinstance(task, dict) else {}

    def validate(state: DevelopmentState):
        return {}

    def review(state: DevelopmentState):
        worker, program = state.get("worker_result"), state["program"]
        if not isinstance(worker, dict):
            return {}
        task_id = program.get("current_task")
        task = next((item for item in program["tasks"] if item["task_id"] == task_id), None)
        approved = worker.get("status") in {"READY_FOR_HUMAN_REVIEW", "SUCCESS"} and worker.get("review") == "APPROVED" and not worker.get("unauthorized_files")
        if task and approved:
            task["status"] = "APPROVED"
        elif task:
            task["status"] = "BLOCKED"
            program["blocked_tasks"] = [*program.get("blocked_tasks", []), {"task_id": task_id, "reason": worker.get("reason", worker.get("status")), "worker_result": worker}]
            program["current_task"] = None
            program["status"] = "BLOCKED"
        return {"program": program}

    def apply_approved_diff(state: DevelopmentState):
        program, task = state["program"], state.get("development_task")
        if program.get("program_id") == "externally-frozen-task": return {}
        if not isinstance(task, dict) or not isinstance(state.get("worker_result"), dict): return {}
        root=Path(registry_api.get_repository(config, str(program["repository"])).path)
        retry="retry primary validation" in state.get("requirement", "").lower()
        result=validate_applied(root,task) if retry else apply_approved(root,task,state["worker_result"])
        task_state=next((item for item in program["tasks"] if item["task_id"]==(program.get("current_task") or task.get("task_id"))),None)
        if task_state and result.get("status")=="APPLIED":
            task_state["status"]="DONE"; task_state["applied_to_primary"]=True
            program["completed_tasks"]=[*program.get("completed_tasks",[]),task_state["task_id"]]; program["current_task"]=None; program["status"]="COMPLETED" if not _select(program) else "READY"
        elif task_state:
            task_state["status"]="BLOCKED"; program["blocked_tasks"]=[*program.get("blocked_tasks",[]),result]; program["current_task"]=None; program["status"]="BLOCKED"
        return {"program":program,"primary_apply":result}

    def build_result(state: DevelopmentState):
        program, worker = state["program"], state.get("worker_result")
        status = worker.get("status") if isinstance(worker, dict) and worker.get("review") == "APPROVED" else state.get("result", {}).get("status", program["status"])
        return {"result": {**state.get("result", {}), **(worker or {}), "status": state.get("primary_apply",{}).get("status",status), "program": program, "frozen_development_task": state.get("development_task"), "worker_result": worker, "primary_apply":state.get("primary_apply"), "execution_enabled": isinstance(worker, dict)}}

    graph = StateGraph(DevelopmentState)
    chain = [("bootstrap_runtime", bootstrap_runtime), ("resolve_requirement_context", resolve_requirement_context), ("plan_change", plan_change), ("policy_gate", policy_gate), ("prepare_task_workspace", prepare_task_workspace), ("execute_code", execute_code), ("validate", validate), ("review", review), ("apply_approved_diff", apply_approved_diff), ("build_result", build_result)]
    for name, function in chain:
        graph.add_node(name, function)
    graph.add_edge(START, chain[0][0])
    for (left, _), (right, _) in zip(chain, chain[1:]):
        graph.add_edge(left, right)
    graph.add_edge(chain[-1][0], END)
    return graph.compile()
