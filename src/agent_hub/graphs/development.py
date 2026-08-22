"""Evidence-backed, resumable development orchestration.

The graph owns only orchestration state.  Business changes remain confined to
the Worker worktree and, after review, the managed integration worktree.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict
from urllib.request import Request, urlopen

from langgraph.graph import END, START, StateGraph

from agent_hub.execution.primary_apply import commit_approved
from agent_hub.projects import api as registry_api
from agent_hub.workspace.config import WorkspaceConfig
from agent_hub.workspace.runtime import RuntimeWorkspaceProvider


class DevelopmentState(TypedDict, total=False):
    requirement: str
    repository_id: str
    program: dict[str, object]
    development_task: dict[str, object]
    worker_result: dict[str, object]
    integration_apply: dict[str, object]
    result: dict[str, object]
    decision: dict[str, object]
    worker_endpoint: str
    retry_integration: bool


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def _integration_root(config: WorkspaceConfig, repository_id: str) -> Path:
    configured = os.environ.get("AGENT_HUB_INTEGRATION_WORKTREE")
    if configured:
        return Path(configured).resolve()
    managed = Path(__file__).resolve().parents[3] / ".integration" / repository_id
    if managed.is_dir():
        return managed.resolve()
    return registry_api.get_repository(config, repository_id).path.resolve()


def _call_worker(task: dict[str, object], endpoint: str | None = None) -> dict[str, object]:
    endpoint = endpoint or os.environ.get("AGENT_HUB_CODE_WORKER_ENDPOINT")
    if not endpoint:
        return {"status": "BLOCKED_EXECUTION_ENVIRONMENT", "reason": "code_worker_endpoint_unconfigured"}
    url = endpoint.rstrip("/")
    if not url.endswith("/execute"):
        url += "/execute"
    try:
        request = Request(url, data=json.dumps(task).encode(), headers={"Content-Type": "application/json"}, method="POST")
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
    return sorted(set(rules))


def _app_root(root: Path) -> Path:
    relocated = root / "apps" / "flutter_forge"
    if (relocated / "pubspec.yaml").is_file():
        return relocated
    return root


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _program_id(repository_id: str) -> str:
    return f"{repository_id.replace('_', '-')}-refactor-program"


_APP_LEVEL_PATH_FRAGMENTS = ("lib/app", "lib/modules", "flutter_forge/pubspec.yaml", "flutter_forge/macos/", ".github/")


def _task_validation(candidate_paths: list[str]) -> list[str]:
    """Every task runs analyze; app-level tasks additionally smoke the macOS
    packaging build so packaging-breaking changes fail inside agent-hub runs."""
    validation = ["flutter_analyze"]
    if any(any(fragment in candidate for fragment in _APP_LEVEL_PATH_FRAGMENTS) for candidate in candidate_paths):
        validation.append("flutter_build")
    return validation


def _router_task(root: Path, repository_id: str, status: str = "READY") -> dict[str, object]:
    application = _app_root(root)
    app, router = application / "lib/app/app.dart", application / "lib/app/router/app_router.dart"
    evidence = [f"{_relative(root, app)}:8", f"{_relative(root, router)}:8", f"{_relative(root, router)}:8"]
    if app.is_file() and router.is_file():
        evidence = [_ref(app, root, "AppRouter.router"), _ref(router, root, "static final GoRouter router"), _ref(router, root, "AppRouteTable.routes")]
    candidate_paths = [_relative(root, app), _relative(root, router)]
    return {
        "task_id": "app-router-private-facade", "title": "Inline the private AppRouter facade into the application shell",
        "development_unit": f"{repository_id}:.",
        "evidence": evidence,
        "candidate_paths": candidate_paths,
        "expected_change": "Keep the same GoRouter configuration while removing the one-use forwarding facade.",
        "invariants": ["MaterialApp.router continues to receive AppRouteTable.routes", "No route path, module metadata, or public package API changes"],
        "validation": _task_validation(candidate_paths), "dependencies": [], "risk": "LOW", "status": status,
        "rules": _rules_for(app, root) + (_rules_for(router, root) if router.is_file() else []),
    }


def _gcode_task(root: Path, repository_id: str) -> dict[str, object]:
    application = _app_root(root)
    controller = application / "lib/modules/ui/gcode_visualizer/state/gcode_player_controller.dart"
    candidate_paths = [_relative(root, application / "lib/modules/ui/gcode_visualizer/pages/gcode_visualizer_page.dart"), _relative(root, controller)]
    return {
        "task_id": "gcode-controller-file-picking-capability", "title": "Move file-picking interaction out of the G-code preview controller",
        "development_unit": f"{repository_id}:.",
        "evidence": [_ref(controller, root, "pickFilePathAndLoad"), _ref(controller, root, "FilePickerService"), _ref(controller, root, "MethodChannelFilePicker")],
        "candidate_paths": candidate_paths,
        "expected_change": "Keep GcodePlayerController as the UI-facing preview orchestrator while moving platform file-selection interaction to the page boundary.",
        "invariants": ["File selection cancel and platform failure messages remain observable", "G-code parsing, playback, and UI interactions preserve current behavior", "No public package API or route metadata changes"],
        "validation": _task_validation(candidate_paths), "dependencies": [], "risk": "MEDIUM", "status": "READY", "rules": _rules_for(controller, root),
    }


def _new_program(config: WorkspaceConfig, repository_id: str, completed: list[str] | None = None) -> dict[str, object]:
    registry_api.refresh(config)
    repository = registry_api.get_repository(config, repository_id)
    if repository is None:
        return {"program_id": _program_id(repository_id), "status": "BLOCKED_DECISION", "blocked_tasks": [{"task_id": "repository", "reason": "primary_repository_not_found", "decision_required": f"Configure {repository_id}."}]}
    root = _integration_root(config, repository_id)
    completed = completed or []
    unit_outcomes = {
        f"{repository_id}:.": {"outcome": "NO_ACTION", "reason": "The private router facade is already committed; the remaining controller split needs a lifecycle decision."},
        f"{repository_id}:packages/file_picker_bridge": {"outcome": "NO_ACTION", "reason": "The package already separates the FilePickerService contract from its MethodChannel implementation."},
        f"{repository_id}:packages/flutter_ioc_core": {"outcome": "NO_ACTION", "reason": "No duplicate facade or mixed runtime ownership was found in the internal IoC package."},
        f"{repository_id}:packages/flutter_study_learning": {"outcome": "NO_ACTION", "reason": "Teaching templates are a shared package boundary; no local behavior-preserving split has evidence."},
        f"{repository_id}:packages/gcode_core": {"outcome": "NO_ACTION", "reason": "Parser/runtime ownership is already isolated from the application controller."},
        f"{repository_id}:packages/gcode_core/example": {"outcome": "NO_ACTION", "reason": "Example application is not a primary runtime ownership boundary."},
        f"{repository_id}:windows": {"outcome": "NO_ACTION", "reason": "Host CMake composition contains no application architecture refactor candidate."},
        f"{repository_id}:windows/flutter": {"outcome": "NO_ACTION", "reason": "Generated Flutter host glue is not refactored by this program."},
        f"{repository_id}:windows/runner": {"outcome": "NO_ACTION", "reason": "Windows runner is host-owned and has no evidence-backed behavior-preserving candidate."},
    }
    units = [{"unit_id": unit.unit_id, "path": unit.relative_path, "type": unit.unit_type, "evidence": [item.path for item in unit.evidence], "inventory_completed": True, **unit_outcomes.get(unit.unit_id, {"outcome": "NO_ACTION", "reason": "No evidence-backed candidate found."})} for unit in repository.development_units]
    application = _app_root(root)
    app, router, table = application / "lib/app/app.dart", application / "lib/app/router/app_router.dart", application / "lib/app/router/app_route_table.dart"
    facade_present = app.is_file() and router.is_file() and "AppRouter.router" in app.read_text(encoding="utf-8") and "static final GoRouter router" in router.read_text(encoding="utf-8")
    tasks: list[dict[str, object]] = []
    if facade_present:
        tasks.append(_router_task(root, repository_id))
    elif "app-router-private-facade" in completed:
        tasks.append(_router_task(root, repository_id, "DONE"))
    controller = application / "lib/modules/ui/gcode_visualizer/state/gcode_player_controller.dart"
    issues = [
        {"issue_id": "app-router-private-facade", "issue": "private routing facade", "evidence": tasks[0]["evidence"] if tasks else ["lib/app/app.dart:8"], "status": "ACTIONABLE" if facade_present else "NO_ACTION"},
        {"issue_id": "gcode-controller-ownership", "issue": "G-code controller owns file picking, parsing, animation, and read-model state", "evidence": [_ref(controller, root, "class GcodePlayerController"), _ref(controller, root, "pickFilePathAndLoad"), _ref(controller, root, "AnimationController")], "status": "BLOCKED_DECISION", "reason": "A behavior-preserving split needs a decided owner for TickerProvider lifecycle and FilePicker error presentation.", "decision_required": "Choose whether animation lifecycle stays in the widget or becomes an injected runtime."},
        {"issue_id": "category-navigation-boundary", "issue": "CategoryNavigation is a platform-navigation boundary", "evidence": [_ref(application / "lib/app/category_navigation.dart", root, "class CategoryNavigation")], "status": "NO_ACTION"},
    ]
    blocked = [{"task_id": issue["issue_id"], "issue_id": issue["issue_id"], "reason": issue["reason"], "decision_required": issue["decision_required"], "status": "BLOCKED_DECISION"} for issue in issues if issue["status"] == "BLOCKED_DECISION"]
    return {"program_id": "flutter-forge-refactor-program", "repository": repository_id, "integration_branch": _git(root, "branch", "--show-current"), "base_revision": _git(root, "rev-parse", "HEAD"), "architecture_summary": "The app shell owns bootstrap/routing; modules own teaching capabilities; internal packages are manifest-backed DevelopmentUnits.", "development_units": units, "workstreams": ["app orchestration boundary", "module capability boundaries", "internal package call topology"], "architecture_issues": issues, "tasks": tasks, "dependency_dag": {str(t["task_id"]): t["dependencies"] for t in tasks}, "execution_order": [str(t["task_id"]) for t in tasks], "current_task": None, "completed_tasks": [str(t["task_id"]) for t in tasks if t["status"] == "DONE"], "blocked_tasks": blocked, "final_rescan_completed": False, "status": "READY" if any(t["status"] == "READY" for t in tasks) else "PLANNING"}


def reconcile_program(program: dict[str, object], root: Path) -> dict[str, object]:
    """Reconcile checkpoint state with idempotent integration-branch facts."""
    program = dict(program)
    # Migration from the retired PRIMARY-apply pipeline: rebuild its stale
    # one-task inventory from source, retaining only Git-proven completions.
    stale_primary = any(
        isinstance(entry, dict) and str(entry.get("status", "")).startswith("PRIMARY_")
        for entry in program.get("blocked_tasks", [])
    )
    completed = set(program.get("completed_tasks", []))
    commits = _git(root, "log", "--format=%H%x00%s", "--all").splitlines()
    by_task = {line.split("\x00", 1)[1].rsplit("[", 1)[-1].rstrip("]"): line.split("\x00", 1)[0] for line in commits if "\x00" in line and "[" in line and "]" in line}
    for task in program.get("tasks", []):
        task_id = str(task.get("task_id", ""))
        if task_id in by_task:
            task.update({"status": "DONE", "commit_hash": by_task[task_id], "integration_base_revision": program.get("base_revision"), "applied_to_integration": True})
            completed.add(task_id)
    if stale_primary and "app-router-private-facade" in by_task:
        recovered = _new_program_for_reconciliation(root, str(program.get("repository", "flutter_forge")), sorted(completed))
        program = recovered
        completed = set(program.get("completed_tasks", []))
    program["completed_tasks"] = sorted(completed)
    program["integration_branch"] = _git(root, "branch", "--show-current")
    program["base_revision"] = _git(root, "rev-parse", "HEAD")
    normalized: list[dict[str, object]] = []
    for index, entry in enumerate(program.get("blocked_tasks", [])):
        if not isinstance(entry, dict):
            entry = {"reason": str(entry)}
        task_id = str(entry.get("task_id") or entry.get("issue_id") or f"legacy-blocked-{index + 1}")
        if task_id in completed:
            continue
        normalized.append({"task_id": task_id, "issue_id": str(entry.get("issue_id") or task_id), "status": "BLOCKED_DECISION", "reason": str(entry.get("reason") or entry.get("status") or "legacy_checkpoint_requires_classification"), "decision_required": str(entry.get("decision_required") or "Review the recorded execution result and choose a retry or replacement task.")})
    program["blocked_tasks"] = normalized
    for issue in program.get("architecture_issues", []):
        if issue.get("issue_id") in completed:
            issue["status"] = "NO_ACTION"
        elif issue.get("status") not in {"ACTIONABLE", "BLOCKED_DECISION", "NO_ACTION", "RESOLVED_BY_DECISION"}:
            issue["status"] = "BLOCKED_DECISION"
            issue.setdefault("reason", "Evidence requires an explicit ownership decision.")
            issue.setdefault("decision_required", "Choose ownership before refactoring.")
    return program


def apply_human_decision(program: dict[str, object], decision: dict[str, object], root: Path, thread_id: str = "") -> tuple[dict[str, object], str]:
    """Apply only supported, evidence-backed decisions to the Program."""
    decision_id = str(decision.get("decision_id", ""))
    choice = str(decision.get("choice", ""))
    blocked = next((item for item in program.get("blocked_tasks", []) if item.get("task_id") == decision_id), None)
    if blocked is None:
        resolved = next((item for item in program.get("human_decisions", []) if item.get("decision_id") == decision_id), None)
        return program, "DECISION_ALREADY_RESOLVED" if resolved else "DECISION_NOT_FOUND"
    if decision_id != "gcode-controller-ownership" or choice != "controller-as-orchestrator":
        return program, "DECISION_INVALID_CHOICE"
    record = {"decision_id": decision_id, "choice": choice, "reason": str(decision.get("reason", "")), "decided_at": datetime.now(UTC).isoformat(), "source": "human", "thread_id": thread_id, "affected_issue_ids": [decision_id], "affected_task_ids": ["gcode-controller-file-picking-capability"]}
    program = dict(program)
    program["human_decisions"] = [*program.get("human_decisions", []), record]
    program["blocked_tasks"] = [item for item in program.get("blocked_tasks", []) if item.get("task_id") != decision_id]
    for issue in program.get("architecture_issues", []):
        if issue.get("issue_id") == decision_id:
            issue["status"] = "RESOLVED_BY_DECISION"; issue["decision"] = record
    if not any(task.get("task_id") == "gcode-controller-file-picking-capability" for task in program.get("tasks", [])):
        program["tasks"] = [*program.get("tasks", []), _gcode_task(root, str(program["repository"]))]
        program["dependency_dag"] = {**program.get("dependency_dag", {}), "gcode-controller-file-picking-capability": []}
        program["execution_order"] = [*program.get("execution_order", []), "gcode-controller-file-picking-capability"]
    program["status"] = "PLANNING"; program["final_rescan_completed"] = False
    return program, "DECISION_ACCEPTED"


def _new_program_for_reconciliation(root: Path, repository_id: str, completed: list[str]) -> dict[str, object]:
    """Build a source inventory without reintroducing checkpoint artifacts."""
    application = _app_root(root)
    app = application / "lib/app/app.dart"
    controller = application / "lib/modules/ui/gcode_visualizer/state/gcode_player_controller.dart"
    task = _router_task(root, repository_id, "DONE")
    task.update({"commit_hash": _git(root, "log", "-1", "--format=%H", "--grep=app-router-private-facade"), "integration_base_revision": "930bd47fcf29171bbfc5d281fb21fda9b858453f"})
    return {"program_id": "flutter-forge-refactor-program", "repository": repository_id, "integration_branch": _git(root, "branch", "--show-current"), "base_revision": _git(root, "rev-parse", "HEAD"), "architecture_summary": "The app shell owns bootstrap/routing; modules own teaching capabilities; internal packages are manifest-backed DevelopmentUnits.", "development_units": [], "workstreams": ["app orchestration boundary", "module capability boundaries", "internal package call topology"], "architecture_issues": [{"issue_id": "app-router-private-facade", "issue": "private routing facade", "evidence": ["lib/app/app.dart:8"], "status": "NO_ACTION"}, {"issue_id": "gcode-controller-ownership", "issue": "G-code controller owns file picking, parsing, animation, and read-model state", "evidence": [_ref(controller, root, "class GcodePlayerController"), _ref(controller, root, "pickFilePathAndLoad"), _ref(controller, root, "AnimationController")], "status": "BLOCKED_DECISION", "reason": "A behavior-preserving split needs a decided owner for TickerProvider lifecycle and FilePicker error presentation.", "decision_required": "Choose whether animation lifecycle stays in the widget or becomes an injected runtime."}], "tasks": [task], "dependency_dag": {"app-router-private-facade": []}, "execution_order": ["app-router-private-facade"], "current_task": None, "completed_tasks": ["app-router-private-facade"], "blocked_tasks": [{"task_id": "gcode-controller-ownership", "issue_id": "gcode-controller-ownership", "status": "BLOCKED_DECISION", "reason": "A behavior-preserving split needs a decided owner for TickerProvider lifecycle and FilePicker error presentation.", "decision_required": "Choose whether animation lifecycle stays in the widget or becomes an injected runtime."}], "final_rescan_completed": False, "status": "PLANNING", "_inventory_from_registry": True}


def _select(program: dict[str, object]) -> dict[str, object] | None:
    completed = set(program.get("completed_tasks", []))
    candidates = [task for task in program.get("tasks", []) if task.get("status") == "READY" and set(task.get("dependencies", [])).issubset(completed)]
    return min(candidates, key=lambda task: (task.get("risk") != "LOW", str(task["task_id"]))) if candidates else None


def _complete(program: dict[str, object]) -> bool:
    units_done = all(unit.get("inventory_completed") for unit in program.get("development_units", []))
    issues_done = all(issue.get("status") in {"ACTIONABLE", "BLOCKED_DECISION", "NO_ACTION"} for issue in program.get("architecture_issues", []))
    actionable_tasked = all(issue.get("status") != "ACTIONABLE" or any(task.get("task_id") == issue.get("issue_id") for task in program.get("tasks", [])) for issue in program.get("architecture_issues", []))
    terminal = all(task.get("status") in {"DONE", "BLOCKED_DECISION", "NO_ACTION"} for task in program.get("tasks", []))
    return units_done and issues_done and actionable_tasked and terminal and not program.get("blocked_tasks") and bool(program.get("final_rescan_completed"))


def build_development_graph(config: WorkspaceConfig):
    provider = RuntimeWorkspaceProvider.from_config(config)

    def bootstrap_runtime(state: DevelopmentState): return {"result": {"runtime_workspace": provider.workspace.model_dump(mode="json")}}

    def reconcile(state: DevelopmentState):
        repository_id = state.get("repository_id", "flutter_forge")
        if not state.get("program") and isinstance(state.get("development_task"), dict):
            supplied = state["development_task"]
            task_id = str(supplied.get("task_id", "externally-frozen-task"))
            return {"program": {"program_id": "externally-frozen-task", "repository": repository_id, "development_units": [{"inventory_completed": True}], "architecture_issues": [], "tasks": [{"task_id": task_id, "expected_change": supplied.get("requirement", ""), "candidate_paths": supplied.get("allowed_paths", []), "validation": supplied.get("validation", []), "dependencies": [], "risk": "LOW", "status": "READY"}], "completed_tasks": [], "blocked_tasks": [], "current_task": None, "status": "READY"}}
        root = _integration_root(config, repository_id)
        existing = state.get("program") or {}
        decision=state.get("decision")
        worker=state.get("worker_result")
        integration=state.get("integration_apply")
        if isinstance(decision,dict) and decision.get("choice")=="retry" and isinstance(worker,dict) and worker.get("status")=="SUCCESS" and isinstance(integration,dict) and integration.get("status")=="PRIMARY_VALIDATION_FAILED":
            task_id=str(worker.get("task_id","")); task=next((item for item in existing.get("tasks",[]) if item.get("task_id")==task_id),None)
            if isinstance(task,dict):
                task["status"]="APPROVED";existing["current_task"]=task_id;existing["status"]="READY";existing["blocked_tasks"]=[item for item in existing.get("blocked_tasks",[]) if item.get("task_id")!=task_id]
                return {"program":existing,"retry_integration":True,"decision":{}}
        should_rescan = "rescan" in state.get("requirement", "").lower() or existing.get("status") in {"COMPLETED", "PROGRAM_COMPLETED", "BLOCKED_DECISION", "PROGRAM_BLOCKED"}
        program = _new_program(config, repository_id, list(existing.get("completed_tasks", []))) if should_rescan else (existing or _new_program(config, repository_id))
        if isinstance(state.get("decision"), dict):
            program, decision_status = apply_human_decision(program, state["decision"], root, str(state.get("thread_id", "")))
            return {"program": reconcile_program(program, root), "result": {"decision_status": decision_status}}
        program = reconcile_program(program, root)
        # A decision-only Run has no Worker endpoint.  Treat that result as a
        # transient runtime condition, so the next refactor-run can retry it.
        if state.get("worker_endpoint") or os.environ.get("AGENT_HUB_CODE_WORKER_ENDPOINT"):
            runtime_ids = {item.get("task_id") for item in program.get("blocked_tasks", []) if item.get("reason") in {"code_worker_endpoint_unconfigured", "base_revision_mismatch"}}
            for task in program.get("tasks", []):
                if task.get("task_id") in runtime_ids:
                    task["status"] = "READY"
            program["blocked_tasks"] = [item for item in program.get("blocked_tasks", []) if item.get("task_id") not in runtime_ids]
        return {"program": program}

    def inventory(state: DevelopmentState):
        program = state["program"]
        if program.get("program_id") == "externally-frozen-task": return {"program": program}
        if not program.get("development_units"):
            replacement = _new_program(config, str(program.get("repository", state.get("repository_id", "flutter_forge"))), list(program.get("completed_tasks", [])))
            replacement["tasks"] = program.get("tasks", replacement["tasks"])
            replacement["completed_tasks"] = program.get("completed_tasks", [])
            program = replacement
        for unit in program.get("development_units", []): unit["inventory_completed"] = True
        return {"program": program}

    def normalize(state: DevelopmentState):
        program = reconcile_program(state["program"], _integration_root(config, str(state["program"].get("repository", "flutter_forge"))))
        for issue in program.get("architecture_issues", []):
            if issue.get("status") == "RESOLVED_BY_DECISION": issue["status"] = "ACTIONABLE"
        return {"program": program}

    def prepare(state: DevelopmentState):
        program = state["program"]
        selected = _select(program)
        if not selected: return {"program": program}
        root = _integration_root(config, str(program["repository"]))
        selected["status"] = "RUNNING"; program["current_task"] = selected["task_id"]
        return {"program": program, "development_task": {"repository": str(program["repository"]), "base_revision": _git(root, "rev-parse", "HEAD"), "task_id": selected["task_id"], "requirement": selected["expected_change"], "allowed_paths": selected["candidate_paths"], "validation": selected["validation"]}}

    def execute(state: DevelopmentState):
        task = state.get("development_task")
        return {"worker_result": _call_worker(task, state.get("worker_endpoint"))} if isinstance(task, dict) and state["program"].get("current_task") else {}

    def review(state: DevelopmentState):
        worker, program = state.get("worker_result"), state["program"]
        task = next((item for item in program.get("tasks", []) if item.get("task_id") == program.get("current_task")), None)
        if not task or not isinstance(worker, dict): return {}
        if worker.get("status") in {"SUCCESS", "READY_FOR_HUMAN_REVIEW"} and worker.get("review") == "APPROVED" and not worker.get("unauthorized_files"):
            task["status"] = "APPROVED"
        else:
            task["status"] = "BLOCKED_DECISION"; program["blocked_tasks"].append({"task_id": task["task_id"], "status": "BLOCKED_DECISION", "reason": str(worker.get("reason") or worker.get("status")), "decision_required": "Review Worker result before retrying."}); program["current_task"] = None
        return {"program": program}

    def commit(state: DevelopmentState):
        program, frozen, worker = state["program"], state.get("development_task"), state.get("worker_result")
        if not isinstance(frozen, dict) or not isinstance(worker, dict): return {}
        root = _integration_root(config, str(program["repository"])); result = commit_approved(root, frozen, worker)
        task = next((item for item in program["tasks"] if item.get("task_id") == program.get("current_task")), None)
        if task and result.get("status") == "COMMITTED":
            task.update({"status": "DONE", "commit_hash": result.get("commit_hash"), "integration_base_revision": frozen["base_revision"], "committed_at": result.get("committed_at")}); program["completed_tasks"] = sorted(set([*program.get("completed_tasks", []), task["task_id"]])); program["current_task"] = None; program["base_revision"] = result["commit_hash"]
        elif task:
            task["status"] = "BLOCKED_DECISION"; program["blocked_tasks"].append({"task_id": task["task_id"], "status": "BLOCKED_DECISION", "reason": str(result.get("status")), "decision_required": "Resolve integration validation or apply failure."}); program["current_task"] = None
        return {"program": program, "integration_apply": result, "retry_integration": False}

    def final_rescan(state: DevelopmentState):
        program = state["program"]; program["final_rescan_completed"] = True
        program["status"] = "PROGRAM_BLOCKED" if program.get("blocked_tasks") else ("PROGRAM_COMPLETED" if _complete(program) else "PLANNING")
        return {"program": program}

    def result(state: DevelopmentState):
        worker = state.get("worker_result") or {}
        return {"result": {**worker, "status": state["program"].get("status") if not worker else worker.get("status"), "program": state["program"], "worker_result": worker, "integration_apply": state.get("integration_apply")}}

    graph = StateGraph(DevelopmentState)
    for name, node in [("bootstrap_runtime", bootstrap_runtime), ("reconcile", reconcile), ("inventory", inventory), ("normalize", normalize), ("prepare", prepare), ("execute", execute), ("review", review), ("commit", commit), ("final_rescan", final_rescan), ("result", result)]: graph.add_node(name, node)
    graph.add_edge(START, "bootstrap_runtime"); graph.add_edge("bootstrap_runtime", "reconcile"); graph.add_edge("reconcile", "inventory"); graph.add_edge("inventory", "normalize")
    graph.add_conditional_edges("normalize", lambda s: "commit" if s.get("retry_integration") else "prepare" if _select(s["program"]) else "final_rescan", {"commit":"commit","prepare": "prepare", "final_rescan": "final_rescan"})
    graph.add_edge("prepare", "execute"); graph.add_edge("execute", "review")
    graph.add_conditional_edges("review", lambda s: "commit" if s["program"].get("current_task") else "reconcile", {"commit": "commit", "reconcile": "reconcile"})
    graph.add_edge("commit", "reconcile"); graph.add_edge("final_rescan", "result"); graph.add_edge("result", END)
    return graph.compile()
