"""Persistent, guarded execution of the cluster decomposition plan."""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict
from urllib.request import Request, urlopen

from langgraph.graph import END, START, StateGraph
from agent_hub.projects.decomposition_config import load_decomposition_project

_DEFAULT_PROJECT = load_decomposition_project()
CLUSTER = _DEFAULT_PROJECT.cluster_root
DEFAULT_PRIMARY_REPOSITORY = _DEFAULT_PROJECT.primary_repository_id
DEFAULT_PROJECT_ID = _DEFAULT_PROJECT.project_id
MANAGED_ROOT = Path(__file__).resolve().parents[3] / ".decomposition"
LOGGER = logging.getLogger(__name__)

# Terminal Worker/guard outcomes that carry no integration result to apply,
# so a task-scoped human retry may safely return the task to READY.  Worker
# execution failures (codex non-zero/timeout) are external and resumable too.
RETRYABLE_BLOCKERS = frozenset({
    "MIGRATION_NO_EFFECT",
    "source_deleted_without_target_owner",
    "WORKER_DISPATCH_FAILED",
    "WORKER_DISPATCH_TIMEOUT",
    "WORKER_SCOPE_CONFIGURATION_ERROR",
    "INTEGRATION_FAILED",
    "CODEX_EXECUTION_FAILED",
    "CODEX_EXECUTION_TIMEOUT",
    "app_target_missing",
    "root_app_owner_retained",
    "root_flutter_application_manifest_retained",
    "workspace_package_owner_missing",
    "workspace_capability_moved_into_app",
    "missing_repository_results",
    "merge_task_has_no_target_units",
})


class State(TypedDict, total=False):
    decomposition_program: dict[str, object]
    cluster_root: str
    project_context: dict[str, object]
    decision: dict[str, object]
    execute: bool
    worker_endpoint: str
    migration_request: dict[str, object]
    worker_result: dict[str, object]
    integration_result: dict[str, object]
    reconcile_only: bool
    proposal_spec: dict[str, object]
    sync_base: dict[str, object]
    sync_result: dict[str, object]
    revalidate_worker: bool


def _pubspec(path: Path) -> tuple[str, list[str]]:
    text = path.read_text(encoding="utf-8")
    name = re.search(r"^name:\s*(\S+)", text, re.M)
    deps = re.findall(r"^\s{2}([a-zA-Z_][\w_]*):\s*$", text, re.M)
    return (name.group(1) if name else path.parent.name, deps)


def _primary_repository(program: dict[str, object] | None = None) -> str:
    return str((program or {}).get("primary_repository_id") or DEFAULT_PRIMARY_REPOSITORY)


def _repositories_for(task: dict[str, object], program: dict[str, object] | None = None) -> list[str]:
    primary = _primary_repository(program)
    names: list[str] = []
    for unit in [*task.get("source_units", []), *task.get("target_units", [])]:
        text = str(unit)
        if text.startswith(("packages/", "plugins/")):
            names.append(primary)
        elif text.startswith("apps/"):
            names.append(primary)
        elif "/" in text:
            names.append(text.split("/", 1)[0])
    return sorted(set(names))


def _ensure_worktree(repository: str, program: dict[str, object] | None = None) -> tuple[Path, str]:
    context = program or {}
    cluster = Path(str(context.get("cluster_root") or CLUSTER)).resolve()
    project_id = str(context.get("project_id") or DEFAULT_PROJECT_ID)
    managed_root = MANAGED_ROOT if project_id == DEFAULT_PROJECT_ID else MANAGED_ROOT / project_id
    source, target, branch = cluster / repository, managed_root / repository, f"decomposition/{repository}"
    if target.is_dir():
        return target, branch
    managed_root.mkdir(parents=True, exist_ok=True)
    exists = bool(subprocess.check_output(["git", "branch", "--list", branch], cwd=source, text=True).strip())
    command = ["git", "worktree", "add"] + ([] if exists else ["-b", branch]) + [str(target), branch if exists else "HEAD"]
    subprocess.run(command, cwd=source, check=True, capture_output=True, text=True)
    return target, branch


def _changes(root: Path) -> list[str]:
    tracked = subprocess.check_output(["git", "diff", "--name-only"], cwd=root, text=True).splitlines()
    untracked = subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard"], cwd=root, text=True).splitlines()
    return sorted(set(tracked + untracked))


def _stage_validated_changes(root: Path, changed: list[str]) -> dict[str, object]:
    """Stage only the guard-validated Git truth, including deletions/renames."""
    if not changed:
        return {"status": "INTEGRATION_NO_CHANGES", "changed_files": []}
    command = ["git", "add", "-A", "--", *changed]
    staged = subprocess.run(command, cwd=root, capture_output=True, text=True)
    if staged.returncode:
        return {"status": "INTEGRATION_STAGING_FAILED", "command": command, "exit_code": staged.returncode, "stderr": staged.stderr[-2000:], "changed_files": changed}
    cached = subprocess.check_output(["git", "diff", "--cached", "--no-renames", "--name-only"], cwd=root, text=True).splitlines()
    if sorted(cached) != sorted(changed):
        return {"status": "INTEGRATION_STAGING_MISMATCH", "changed_files": changed, "staged_files": cached}
    return {"status": "STAGED", "changed_files": changed}


def _allowed(task: dict[str, object], repository: str) -> list[str]:
    frozen = task.get("allowed_paths_by_repository")
    if isinstance(frozen, dict) and isinstance(frozen.get(repository), list):
        return [str(path) for path in frozen[repository]]
    task_id = str(task.get("task_id", ""))
    known = {
        "merge-gcode-core-owners": {"flutter_study": ["packages/gcode_core"]},
        "merge-file-picker-bridge-owners": {"flutter_study": ["packages/file_picker_bridge"]},
        "relocate-flutter-study-app": {"flutter_study": ["lib/app", "lib", "pubspec.yaml", "flutterguard.yaml"]},
    }
    return known.get(task_id, {}).get(repository, [])


def _scope_ok(changed: list[str], allowed: list[str]) -> bool:
    return all(any(prefix in {"", "."} or path == prefix or path.startswith(prefix.rstrip("/") + "/") for prefix in allowed) for path in changed)


def _classify_managed_dirty(task: dict[str, object], repository: str, worktree: Path, expected_head: str) -> dict[str, object]:
    """Classify dirty state only when branch, base, and task scope all agree."""
    changed = _changes(worktree)
    if not changed:
        return {"classification": "CLEAN", "changed_files": []}
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=worktree, text=True).strip()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=worktree, text=True).strip()
    allowed = _allowed(task, repository)
    if branch == f"decomposition/{repository}" and head == expected_head and _scope_ok(changed, allowed):
        return {"classification": "AGENT_STALE_DIRTY", "changed_files": changed, "branch": branch, "head": head, "base_revision": expected_head}
    return {"classification": "USER_UNKNOWN_DIRTY", "changed_files": changed, "branch": branch, "head": head, "base_revision": expected_head}


def _restore_agent_owned_dirty(worktree: Path, base_revision: str, paths: list[str]) -> dict[str, object]:
    """Restore only a proven Agent-owned path set; never clean or reset a tree."""
    command = ["git", "restore", "--source", base_revision, "--staged", "--worktree", "--", *paths]
    result = subprocess.run(command, cwd=worktree, capture_output=True, text=True)
    return {"status": "RESTORED" if result.returncode == 0 and not _changes(worktree) else "RESTORE_FAILED", "command": command, "exit_code": result.returncode, "stderr": result.stderr[-2000:], "remaining_changes": _changes(worktree)}


def _worker_change_set(worker: dict[str, object], repository: str) -> list[str]:
    repositories = worker.get("repositories", {})
    result = repositories.get(repository, {}) if isinstance(repositories, dict) else {}
    paths = result.get("changed_files", []) if isinstance(result, dict) else []
    return sorted(str(path) for path in paths)


def _worker(request: dict[str, object], endpoint: str | None) -> dict[str, object]:
    endpoint = endpoint or os.environ.get("AGENT_HUB_CODE_WORKER_ENDPOINT")
    if not endpoint:
        return {"status": "WORKER_DISPATCH_FAILED", "reason": "code_worker_endpoint_unconfigured"}
    url = endpoint.rstrip("/") + ("" if endpoint.rstrip("/").endswith("/execute") else "/execute")
    try:
        call = Request(url, data=json.dumps(request).encode(), headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(call, timeout=int(os.environ.get("AGENT_HUB_CODEX_TIMEOUT_SECONDS", "1800")) + 60) as response:
            return json.loads(response.read())
    except TimeoutError as error:
        return {"status": "WORKER_DISPATCH_TIMEOUT", "reason": "code_worker_timeout", "detail": str(error)}
    except (json.JSONDecodeError, ValueError) as error:
        return {"status": "WORKER_DISPATCH_FAILED", "reason": "code_worker_invalid_response", "detail": str(error)}
    except OSError as error:
        return {"status": "WORKER_DISPATCH_FAILED", "reason": "code_worker_unreachable", "detail": str(error)}


def _program(root: Path, project_context: dict[str, object] | None = None) -> dict[str, object]:
    context = project_context or {}
    primary_repository = str(context.get("primary_repository_id") or "flutter_study")
    repository_paths = context.get("repository_paths") if isinstance(context.get("repository_paths"), dict) else {}
    primary_path = Path(str(repository_paths.get(primary_repository) or root / primary_repository))
    repos = []
    for directory in (primary_path,):
        pubspec = directory / "pubspec.yaml"
        if pubspec.is_file():
            name, deps = _pubspec(pubspec)
            repos.append({"repository_id": directory.name, "path": str(directory), "role": "APP", "package_name": name, "pubspec": str(pubspec), "dependencies": deps, "consumers": []})
    capabilities = [
        {"capability_id":"gcode-parser-toolpath","current_owners":["flutter_study/packages/gcode_core"],"source_paths":["flutter_study/packages/gcode_core/lib"],"consumers":["flutter_study:gcode_visualizer"],"dependencies":["flutter"],"flutter_dependency":True,"platform_dependency":False,"native_dependency":False,"state_dependency":False,"reuse_scope":"cluster","classification":"KEEP_PACKAGE","target_package":"packages/gcode_core"},
        {"capability_id":"file-picker-platform-bridge","current_owners":["flutter_study/packages/file_picker_bridge"],"source_paths":["flutter_study/packages/file_picker_bridge/lib"],"consumers":["flutter_study:file_picker","flutter_study:gcode_visualizer","flutter_study:font_picker"],"dependencies":["flutter/services"],"flutter_dependency":True,"platform_dependency":True,"native_dependency":False,"state_dependency":False,"reuse_scope":"cluster","classification":"KEEP_PACKAGE","target_package":"packages/file_picker_bridge"},
        {"capability_id":"learning-scaffold","current_owners":["flutter_study/packages/flutter_study_learning"],"source_paths":["flutter_study/packages/flutter_study_learning/lib"],"consumers":["flutter_study:modules"],"dependencies":["flutter"],"flutter_dependency":True,"platform_dependency":False,"native_dependency":False,"state_dependency":False,"reuse_scope":"cluster","classification":"KEEP_PACKAGE","target_package":"packages/flutter_study_learning"},
        {"capability_id":"ioc-composition-services","current_owners":["flutter_study/packages/flutter_ioc_core"],"source_paths":["flutter_study/packages/flutter_ioc_core/lib"],"consumers":["flutter_study:modules"],"dependencies":["flutter"],"flutter_dependency":True,"platform_dependency":False,"native_dependency":False,"state_dependency":False,"reuse_scope":"cluster","classification":"KEEP_PACKAGE","target_package":"packages/flutter_ioc_core"},
        {"capability_id":"app-composition-routing","current_owners":["flutter_study/apps/flutter_study"],"source_paths":["flutter_study/apps/flutter_study/lib"],"consumers":[],"dependencies":["go_router","flutter"],"flutter_dependency":True,"platform_dependency":False,"native_dependency":False,"state_dependency":True,"reuse_scope":"app","classification":"KEEP_APP_ONLY","target_package":"apps/flutter_study"},
    ]
    candidates = [{"package_id":"packages/gcode_core","package_type":"FLUTTER_PACKAGE","target_path":"packages/gcode_core","owned_capabilities":["gcode-parser-toolpath"],"dependencies":[],"public_api_intent":"parser and toolpath API","migration_priority":1},{"package_id":"packages/file_picker_bridge","package_type":"FLUTTER_PACKAGE","target_path":"packages/file_picker_bridge","owned_capabilities":["file-picker-platform-bridge"],"dependencies":[],"public_api_intent":"platform-neutral file picker API","migration_priority":1},{"package_id":"packages/flutter_ioc_core","package_type":"FLUTTER_PACKAGE","target_path":"packages/flutter_ioc_core","owned_capabilities":["ioc-composition-services"],"dependencies":[],"public_api_intent":"composition IoC services","migration_priority":2},{"package_id":"packages/flutter_study_learning","package_type":"FLUTTER_PACKAGE","target_path":"packages/flutter_study_learning","owned_capabilities":["learning-scaffold"],"dependencies":[],"public_api_intent":"learning UI templates","migration_priority":2},{"package_id":"apps/flutter_study","package_type":"APP_ONLY","target_path":"apps/flutter_study","owned_capabilities":["app-composition-routing"],"dependencies":["packages/gcode_core","packages/file_picker_bridge","packages/flutter_study_learning","packages/flutter_ioc_core"],"public_api_intent":"bootstrap and composition only","migration_priority":3}]
    tasks = [
        {"task_id":"merge-gcode-core-owners","title":"Confirm the G-code package owner","source_units":["flutter_study/packages/gcode_core"],"target_units":["packages/gcode_core"],"depends_on":[],"allowed_operations":[],"allowed_paths_by_repository":{"flutter_study":["packages/gcode_core"]},"acceptance":["single owner remains packages/gcode_core"],"status":"DONE","evidence":["registry discovers packages/gcode_core only inside flutter_study","standalone owner was removed before this program state"]},
        {"task_id":"merge-file-picker-bridge-owners","title":"Confirm the file picker bridge package owner","source_units":["flutter_study/packages/file_picker_bridge"],"target_units":["packages/file_picker_bridge"],"depends_on":[],"allowed_operations":[],"allowed_paths_by_repository":{"flutter_study":["packages/file_picker_bridge"]},"target_creation_allowed":False,"dependency_constraints":["flutter_study depends only on packages/file_picker_bridge","packages/file_picker_bridge must not depend on apps/flutter_study","no dependency cycle"],"acceptance":["exactly one reusable file picker owner remains packages/file_picker_bridge","workspace package pubspec/lib/public API remain present","all app call sites resolve package:file_picker_bridge/file_picker_bridge.dart"],"status":"DONE","evidence":["registry discovers packages/file_picker_bridge only inside flutter_study","flutter_study/pubspec.yaml workspace and path dependency point to packages/file_picker_bridge","three app consumers import package:file_picker_bridge/file_picker_bridge.dart"]},
        {**_app_relocation_contract(), "status": "DONE"},
        {"task_id":"establish-package-boundary-contracts","title":"Add per-package ownership contracts, independent test entries, and version pins","source_units":[],"target_units":["packages/gcode_core","packages/file_picker_bridge","packages/flutter_study_learning","packages/flutter_ioc_core"],"depends_on":["relocate-flutter-study-app"],"allowed_operations":[],"allowed_paths_by_repository":{"flutter_study":["packages/gcode_core","packages/file_picker_bridge","packages/flutter_study_learning","packages/flutter_ioc_core"]},"target_creation_allowed":False,"dependency_constraints":["packages/* and plugins/* must not depend on apps/flutter_study","workspace dependency cycles must remain zero"],"execution_instructions":["For each of packages/gcode_core, packages/file_picker_bridge, packages/flutter_study_learning and packages/flutter_ioc_core: create OWNERS.md at the package root declaring the package name, its public contract (boundary: public API intent and what it must not own) and its maintenance owners.","Ensure each package has an independent runnable test entry under packages/<package>/test/ (create test/<package>_test.dart only when the package has no test file).","Ensure each package pubspec.yaml declares an explicit semver version field (do not publish).","Do not modify apps/flutter_study or any existing lib/ source; only add contract/test/version content inside the four package directories.","Do not delete or move any existing file."],"acceptance":["each of the four packages has a boundary contract file (OWNERS.md)","each package has an independent runnable test entry","each package pubspec.yaml declares an explicit version","no apps/flutter_study or lib/ source changes","changed repository receives one integration commit"],"status":"READY","evidence":["workspace declares four package members consumed only by apps/flutter_study","registry lists each package as a development unit"]},
    ]
    return {"project_id":str(context.get("project_id") or "flutter-study"),"program_id":str(context.get("program_id") or "flutter-study-decomposition-program"),"adapter":str(context.get("adapter") or "flutter_study"),"primary_repository_id":primary_repository,"cluster_root":str(root),"repositories":repos,"capabilities":capabilities,"package_candidates":candidates,"target_dependency_graph":{"nodes":[x["package_id"] for x in candidates],"edges":[["apps/flutter_study",x] for x in ["packages/gcode_core","packages/file_picker_bridge","packages/flutter_study_learning","packages/flutter_ioc_core"]],"cycles":[]},"migration_tasks":tasks,"human_decisions":[],"integration_head":None,"execution_mode":"PLAN_ONLY","status":"PLANNING_COMPLETE"}


def _app_relocation_contract() -> dict[str, object]:
    """Frozen contract for the explicitly authorised single App owner."""
    return {
        "task_id": "relocate-flutter-study-app",
        "title": "Create apps/flutter_study as the only Flutter Application owner",
        "source_units": ["flutter_study/root_flutter_application"],
        "target_units": ["apps/flutter_study"],
        "depends_on": ["merge-gcode-core-owners", "merge-file-picker-bridge-owners"],
        "allowed_operations": ["MOVE", "RENAME", "DEPENDENCY_REWRITE", "API_BREAK"],
        "target_creation_allowed": True,
        "allowed_paths_by_repository": {"flutter_study": ["apps/flutter_study", "lib", "macos", "windows", "android", "ios", "linux", "web", "assets", "test", "integration_test", "pubspec.yaml", "pubspec.lock", ".metadata", "analysis_options.yaml", "l10n.yaml", "flutterguard.yaml"]},
        "dependency_constraints": ["apps/flutter_study may depend on packages/* and plugins/*", "packages/* and plugins/* must not depend on apps/flutter_study", "workspace dependency cycles must remain zero"],
        "execution_instructions": ["Create apps/flutter_study as a Flutter application with pubspec.yaml and lib/main.dart.", "Move only app-owned runtime sources, hosts, assets, tests and configuration after inspecting ownership; do not move packages/* or plugins/*.", "Rewrite app package paths relative to apps/flutter_study and retain root pubspec.yaml only as a workspace/container manifest without Flutter Application ownership.", "Move the existing macos and windows hosts; move other platform hosts only when they exist."],
        "acceptance": ["apps/flutter_study/pubspec.yaml and apps/flutter_study/lib/main.dart exist", "root has no lib/main.dart or lib/app duplicate App owner", "packages/* and plugins/* remain at workspace root", "app package paths resolve from apps/flutter_study", "changed repository receives one integration commit"],
        "status": "READY",
        "evidence": ["root pubspec.yaml currently owns Flutter application dependencies and workspace members", "lib/main.dart bootstraps lib/app", "macos and windows are the actual root platform hosts"],
    }


def _select(program: dict[str, object]) -> dict[str, object] | None:
    done = {task.get("task_id") for task in program.get("migration_tasks", []) if task.get("status") == "DONE"}
    return next((task for task in program.get("migration_tasks", []) if task.get("status") == "READY" and set(task.get("depends_on", [])).issubset(done)), None)


def _mutation_repositories(task: dict[str, object], program: dict[str, object] | None = None) -> dict[str, str]:
    """Derive writable repository roles solely from the frozen task contract."""
    primary = _primary_repository(program)
    sources = _repositories_for({"source_units": task.get("source_units", []), "target_units": []}, program)
    targets = [primary if str(unit).startswith(("packages/", "plugins/", "apps/")) else repository for unit in task.get("target_units", []) for repository in _repositories_for({"source_units": [unit], "target_units": []}, program)]
    targets = sorted(set(targets))
    operations = set(task.get("allowed_operations", []))
    roles: dict[str, str] = {}
    if not operations or operations & {"DELETE", "MOVE", "PACKAGE_MERGE", "RENAME"}:
        roles.update({repository: "source" for repository in sources})
    if not operations or operations & {"MOVE", "PACKAGE_MERGE", "DEPENDENCY_REWRITE", "API_BREAK", "RENAME"}:
        for repository in targets:
            roles[repository] = "source_target" if repository in roles else "target"
    # A dependency rewrite can be frozen against a source repository too.
    if "DEPENDENCY_REWRITE" in operations:
        for repository in sources:
            roles.setdefault(repository, "source")
    return roles


def _architecture_guard(task: dict[str, object], worker: dict[str, object], program: dict[str, object]) -> dict[str, object]:
    """Prove that a merge preserves a concrete target capability owner."""
    repositories = worker.get("repositories", {})
    if not isinstance(repositories, dict):
        return {"status": "REJECT", "reason": "missing_repository_results"}
    target_units = [str(unit) for unit in task.get("target_units", [])]
    if not target_units:
        return {"status": "REJECT", "reason": "merge_task_has_no_target_units"}
    deleted = [path for result in repositories.values() if isinstance(result, dict) for path in result.get("changed_files", [])]
    source_deleted = bool(deleted)
    primary = _primary_repository(program)
    if task.get("task_id") == "replace-media-plugin-with-video-player":
        changed = _worker_change_set(worker, primary)
        required = {
            "apps/flutter_study/pubspec.yaml",
            "apps/flutter_study/lib/modules/platform/online_video_player/module_root.dart",
            "apps/flutter_study/lib/modules/platform/online_video_player/state/media_kit_player_adapter.dart",
            "apps/flutter_study/lib/modules/platform/online_video_player/state/video_player_adapter.dart",
            "apps/flutter_study/test/modules/platform/online_video_player/online_video_player_test.dart",
        }
        missing = sorted(required - set(changed))
        if missing:
            return {"status": "REJECT", "reason": "backend_replacement_incomplete", "missing_changed_paths": missing, "changed_files": changed}
        if any(path.startswith(("packages/", "plugins/")) for path in changed):
            return {"status": "REJECT", "reason": "backend_replacement_crossed_package_boundary", "changed_files": changed}
        diff = str((worker.get("repositories") or {}).get(primary, {}).get("diff", ""))
        if "video_player" not in diff or "media_kit_player_adapter.dart" not in diff:
            return {"status": "REJECT", "reason": "backend_replacement_evidence_missing"}
        return {"status": "PASS", "guard_kind": "backend_replacement", "capability_owner_before": list(task.get("source_units", [])), "capability_owner_after": list(task.get("target_units", [])), "required_changed_paths": sorted(required), "package_boundary": "PASS", "dependency_rewrite": "PRESENT"}
    if task.get("task_id") == "rename-main-app-package":
        changed = _worker_change_set(worker, primary)
        required = {"apps/flutter_study/pubspec.yaml", ".run/Flutter_Study_macOS.run.xml"}
        if not required.issubset(set(changed)):
            return {"status": "REJECT", "reason": "package_rename_incomplete", "missing_changed_paths": sorted(required - set(changed))}
        if any(path.startswith(("packages/", "plugins/")) for path in changed):
            return {"status": "REJECT", "reason": "package_rename_crossed_package_boundary", "changed_files": changed}
        diff = str((worker.get("repositories") or {}).get(primary, {}).get("diff", ""))
        added = "\n".join(line for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++"))
        if "name: flutter_study_app" not in added or "package:flutter_study_app/" not in added or "package:main_app/" in added:
            return {"status": "REJECT", "reason": "package_rename_evidence_missing"}
        return {"status": "PASS", "guard_kind": "dart_package_rename", "capability_owner_before": ["main_app"], "capability_owner_after": ["flutter_study_app"], "run_configuration": "PRESENT", "package_boundary": "PASS"}
    if task.get("task_id") == "relocate-flutter-study-app":
        root = _ensure_worktree(primary, program)[0]
        target = root / "apps/flutter_study"
        target_pubspec, target_main = target / "pubspec.yaml", target / "lib/main.dart"
        root_pubspec = root / "pubspec.yaml"
        root_manifest = root_pubspec.read_text(encoding="utf-8") if root_pubspec.is_file() else ""
        packages_preserved = all((root / path).is_dir() for path in ("packages/gcode_core", "packages/file_picker_bridge", "packages/flutter_study_learning"))
        app_changes = _worker_change_set(worker, primary)
        # Before integration, the verified target exists only in the isolated
        # Worker diff.  After integration, prove the same facts on disk.
        if not target_pubspec.is_file() or not target_main.is_file():
            required = {"apps/flutter_study/pubspec.yaml", "apps/flutter_study/lib/main.dart", "lib/main.dart", "pubspec.yaml"}
            if not required.issubset(set(app_changes)):
                return {"status": "REJECT", "reason": "app_target_missing", "target": "apps/flutter_study", "required": sorted(required), "changed_files": app_changes}
            if any(path.startswith(("packages/", "plugins/")) for path in app_changes):
                return {"status": "REJECT", "reason": "workspace_capability_moved_into_app", "changed_files": app_changes}
            return {"status": "PASS", "capability_owner_before": ["flutter_study/root_flutter_application"], "capability_owner_after": ["apps/flutter_study"], "target_app_root": "apps/flutter_study", "root_app_removal_pending_in_approved_diff": True, "package_survival": "PASS", "dependency_direction": "PASS"}
        if (root / "lib/main.dart").exists() or (root / "lib/app").exists():
            return {"status": "REJECT", "reason": "root_app_owner_retained", "root_duplicates": [path for path in ("lib/main.dart", "lib/app") if (root / path).exists()]}
        if re.search(r"^\s*flutter:\s*$", root_manifest, re.M):
            return {"status": "REJECT", "reason": "root_flutter_application_manifest_retained"}
        if not packages_preserved:
            return {"status": "REJECT", "reason": "workspace_package_owner_missing"}
        return {"status": "PASS", "capability_owner_before": ["flutter_study/root_flutter_application"], "capability_owner_after": ["apps/flutter_study"], "target_app_root": "apps/flutter_study", "root_app_removed": True, "package_survival": "PASS", "dependency_direction": "PASS"}
    retained: list[str] = []
    for unit in target_units:
        # Target units may be repository-qualified in a frozen multi-repo
        # contract (for example ``flutter_study/packages/...``).  Ownership
        # validation is evaluated inside the Flutter worktree, so remove that
        # qualifier before testing the retained package owner.
        if unit.startswith("flutter_study/"):
            unit = unit.removeprefix("flutter_study/")
        if unit.startswith("packages/") or unit.startswith("plugins/"):
            target = _ensure_worktree(primary, program)[0] / unit
            required = [target / "pubspec.yaml", target / "lib"]
            if all(path.exists() for path in required):
                retained.extend(str(path.relative_to(_ensure_worktree(primary, program)[0])) for path in required)
    if source_deleted and not retained:
        return {"status": "REJECT", "reason": "source_deleted_without_target_owner", "source_deleted_paths": deleted}
    if task.get("task_id") == "merge-file-picker-bridge-owners":
        target = _ensure_worktree(primary, program)[0] / "packages/file_picker_bridge"
        if not ((target / "pubspec.yaml").is_file() and (target / "lib").is_dir()):
            return {"status": "REJECT", "reason": "workspace_package_owner_missing", "target_package_root": "packages/file_picker_bridge"}
    return {"status": "PASS", "capability_owner_before": list(task.get("source_units", [])), "capability_owner_after": target_units, "source_deleted_paths": deleted, "target_added_or_retained_paths": retained, "package_survival": "PASS", "dependency_direction": "PASS"}


def _file_picker_contract_preflight(program: dict[str, object] | None = None) -> dict[str, object]:
    primary = _primary_repository(program)
    target = _ensure_worktree(primary, program)[0] / "packages/file_picker_bridge"
    target_ready = (target / "pubspec.yaml").is_file() and (target / "lib").is_dir()
    return {"status": "PASS" if target_ready else "REJECT", "capability_owner": "flutter_study/packages/file_picker_bridge", "target_package_root": "packages/file_picker_bridge", "required_dependency_rewrites": [], "reason": "workspace package owner is present" if target_ready else "workspace package owner cannot be proven"}


def _proposal_inventory(program: dict[str, object], spec: dict[str, object]) -> dict[str, object]:
    """Build a frozen task from tracked-file evidence without touching a worktree."""
    primary_repository = str(program.get("primary_repository_id") or "flutter_study")
    repository = next((item for item in program.get("repositories", []) if item.get("repository_id") == primary_repository), None)
    root = Path(str(repository.get("path"))) if isinstance(repository, dict) else Path(str(program.get("cluster_root", CLUSTER))) / primary_repository
    if not root.is_dir():
        return {"task_id": spec.get("task_id"), "title": spec.get("title"), "status": "BLOCKED_DECISION", "evidence": [], "candidate_paths": [], "allowed_paths_by_repository": {}, "blocked_decisions": ["flutter_study repository is unavailable for read-only discovery"]}
    tracked = subprocess.check_output(["git", "ls-files"], cwd=root, text=True).splitlines()
    if spec.get("task_id") == "rename-main-app-package":
        candidates: list[str] = []
        evidence: list[str] = []
        for relative in tracked:
            path = root / relative
            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if relative == "apps/flutter_study/pubspec.yaml" and re.search(r"^name:\s*main_app\s*$", content, re.M):
                candidates.append(relative)
                evidence.append(f"{relative}: declares name main_app")
            elif relative.endswith(".dart") and "package:main_app/" in content:
                candidates.append(relative)
                evidence.append(f"{relative}: imports package:main_app")
        run_config = ".run/Flutter_Study_macOS.run.xml"
        candidates.append(run_config)
        blocked: list[str] = []
        if "apps/flutter_study/pubspec.yaml" not in candidates:
            blocked.append("main_app pubspec declaration not found")
        if not any(path.endswith(".dart") for path in candidates):
            blocked.append("package:main_app callsites not found")
        frozen = sorted(set(candidates))
        return {
            "task_id": str(spec.get("task_id", "")), "title": str(spec.get("title", "")), "intent": str(spec.get("intent", "")),
            "source_units": list(spec.get("source_units", ["apps/flutter_study"])), "target_units": list(spec.get("target_units", ["apps/flutter_study"])),
            "depends_on": list(spec.get("depends_on", [])), "allowed_operations": list(spec.get("allowed_operations", ["DEPENDENCY_REWRITE", "CREATE"])),
            "candidate_paths": frozen, "allowed_paths_by_repository": {primary_repository: frozen} if not blocked else {}, "evidence": evidence,
            "execution_instructions": list(spec.get("execution_instructions", [])), "invariants": list(spec.get("invariants", [])), "acceptance": list(spec.get("acceptance", [])),
            "blocked_decisions": blocked, "proposal": {"status": "FROZEN" if not blocked else "PENDING_EVIDENCE", "read_only": True}, "status": "READY" if not blocked else "BLOCKED_DECISION",
        }
    needles = ("media_kit", "media_kit_video", "media_kit_libs_video", "online_video_player")
    candidates: list[str] = []
    evidence: list[str] = []
    for relative in tracked:
        path = root / relative
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        matches = sorted({needle for needle in needles if needle in content})
        if matches:
            candidates.append(relative)
            evidence.append(f"{relative}: references {', '.join(matches)}")
        elif relative.startswith("apps/flutter_study/") and (
            relative.endswith("Podfile.lock")
            or "GeneratedPluginRegistrant" in relative
            or relative.endswith("generated_plugin_registrant.cc")
            or relative.endswith("generated_plugin_registrant.h")
            or relative.endswith("generated_plugins.cmake")
        ):
            candidates.append(relative)
            evidence.append(f"{relative}: tracked generated platform plugin configuration")
    # The replacement adapter is an exact, anticipated CREATE target.  No
    # directory prefix is frozen, so ScopeGuard still rejects unrelated files.
    adapter = "apps/flutter_study/lib/modules/platform/online_video_player/state/video_player_adapter.dart"
    if adapter not in candidates:
        candidates.append(adapter)
    candidates = sorted(set(candidates))
    allowed = [path for path in candidates if not path.startswith(".hermes/")]
    blocked: list[str] = []
    required_groups = {
        "dependency manifest": lambda p: p == "apps/flutter_study/pubspec.yaml",
        "lockfile": lambda p: p == "pubspec.lock",
        "direct media API": lambda p: p.endswith("media_kit_player_adapter.dart"),
        "lifecycle/bootstrap": lambda p: p.endswith("app_bootstrap.dart") or p.endswith("module_root.dart"),
        "tests": lambda p: "/test/" in f"/{p}" or p.startswith("test/"),
    }
    for label, predicate in required_groups.items():
        if not any(predicate(path) for path in candidates):
            blocked.append(f"missing {label} evidence")
    contract = {
        "task_id": str(spec.get("task_id", "")),
        "title": str(spec.get("title", "")),
        "intent": str(spec.get("intent", "")),
        "source_units": list(spec.get("source_units", ["flutter_study/media_playback"])),
        "target_units": list(spec.get("target_units", ["flutter_study/media_playback"])),
        "depends_on": list(spec.get("depends_on", [])),
        "allowed_operations": list(spec.get("allowed_operations", ["DEPENDENCY_REWRITE", "API_BREAK", "CREATE", "DELETE"])),
        "candidate_paths": candidates,
        "allowed_paths_by_repository": {"flutter_study": allowed} if allowed and not blocked else {},
        "evidence": evidence,
        "discovery": list(spec.get("required_discovery", [])),
        "invariants": list(spec.get("invariants", [])),
        "acceptance": list(spec.get("acceptance", [])),
        "risks": [
            "media_kit stream subscriptions map to video_player ValueNotifier/controller listeners with different error and readiness semantics",
            "volume and playback speed support must be verified on every enabled platform",
            "global MediaKit.ensureInitialized removal and controller initialization/disposal ordering are lifecycle-sensitive",
            "generated plugin registrants and platform lockfiles may change only as dependency-resolution effects",
        ],
        "blocked_decisions": blocked,
        "proposal": {"status": "FROZEN" if candidates and not blocked else "PENDING_EVIDENCE", "read_only": True},
        "status": "READY" if candidates and not blocked else "BLOCKED_DECISION",
    }
    return contract


def build_decomposition_graph():
    graph = StateGraph(State)

    def reconcile(state: State):
        program = state.get("decomposition_program")
        if not isinstance(program, dict):
            context = state.get("project_context") if isinstance(state.get("project_context"), dict) else {}
            # Only decomposition-plan may initialise a Program.  An execute
            # or recovery Run without checkpoint state is not allowed to
            # silently invent a replacement plan.
            if state.get("execute"):
                return {"decomposition_program": {"project_id": context.get("project_id", "flutter-study"), "program_id": context.get("program_id", "flutter-study-decomposition-program"), "status": "STATE_NOT_LOADED", "migration_tasks": [], "execution_blocker": {"status": "STATE_NOT_LOADED", "reason": "No persisted DecompositionProgram was supplied."}}}
            root = Path(state.get("cluster_root") or CLUSTER)
            return {"decomposition_program": _program(root, context)}
        program = dict(program)
        # A retry is deliberately task-scoped: it can only release a terminal
        # no-effect/dispatch outcome that has no integration result to apply.
        decision = state.get("decision")
        if isinstance(decision, dict) and decision.get("choice") == "CREATE_APPS_FLUTTER_STUDY":
            decision_id = str(decision.get("decision_id", ""))
            task_id = decision_id.removeprefix("retry:")
            blocker = program.get("execution_blocker")
            task = next((item for item in program.get("migration_tasks", []) if item.get("task_id") == task_id and item.get("status") == "BLOCKED_DECISION"), None)
            if task_id == "relocate-flutter-study-app" and isinstance(blocker, dict) and blocker.get("task_id") == task_id and isinstance(task, dict):
                contract = _app_relocation_contract()
                task.clear(); task.update(contract)
                program.update({"status": "PLANNING_COMPLETE", "current_migration_task": task_id})
                program.pop("execution_blocker", None)
                program.setdefault("human_decisions", []).append({"decision_id": decision_id, "choice": "CREATE_APPS_FLUTTER_STUDY", "task_id": task_id, "reason": str(decision.get("reason", "")), "status": "APPLIED"})
                return {"decomposition_program": program, "worker_result": {}, "integration_result": {"status": "APP_RELOCATION_CONTRACT_AUTHORIZED", "task_id": task_id}, "decision": {}}
        if isinstance(decision, dict) and decision.get("choice") == "retry":
            decision_id = str(decision.get("decision_id", ""))
            task_id = decision_id.removeprefix("retry:")
            blocker = program.get("execution_blocker")
            task = next((item for item in program.get("migration_tasks", []) if item.get("task_id") == task_id and item.get("status") == "BLOCKED_DECISION"), None)
            if isinstance(blocker, dict) and isinstance(task, dict) and blocker.get("task_id") == task_id and blocker.get("status") in RETRYABLE_BLOCKERS:
                worker = state.get("worker_result")
                if blocker.get("status") == "source_deleted_without_target_owner" and isinstance(worker, dict) and worker.get("task_id") == task_id and worker.get("status") == "SUCCESS":
                    task["status"] = "RUNNING"
                    program["status"] = "RUNNING"
                    program["current_migration_task"] = task_id
                    program.pop("execution_blocker", None)
                    program.setdefault("human_decisions", []).append({"decision_id": decision_id, "choice": "retry", "task_id": task_id, "reason": str(decision.get("reason", "")), "status": "REVIEW_RETRY_APPLIED"})
                    return {"decomposition_program": program, "decision": {}, "revalidate_worker": True}
                task.pop("worker_execution", None)
                task["status"] = "READY"
                program["status"] = "PLANNING_COMPLETE"
                program["current_migration_task"] = task_id
                program.pop("execution_blocker", None)
                program.setdefault("human_decisions", []).append({"decision_id": decision_id, "choice": "retry", "task_id": task_id, "reason": str(decision.get("reason", "")), "status": "APPLIED"})
                return {"decomposition_program": program, "worker_result": {}, "migration_request": {}, "integration_result": {"status": "RETRY_AUTHORIZED", "task_id": task_id}, "decision": {}}
        # Older checkpoints predate explicit retry metadata.  Normalize only
        # the known, safely retryable terminal outcomes; no task state changes.
        blocker = program.get("execution_blocker")
        if isinstance(blocker, dict) and blocker.get("status") in RETRYABLE_BLOCKERS and not blocker.get("decision_id"):
            blocked = next((item for item in program.get("migration_tasks", []) if item.get("task_id") == blocker.get("task_id") and item.get("status") == "BLOCKED_DECISION"), None)
            if isinstance(blocked, dict):
                program["execution_blocker"] = {**blocker, "decision_id": f"retry:{blocked['task_id']}", "choices": ["retry"]}
                return {"decomposition_program": program}
        # Correct only the known, previously frozen bad path before the task
        # is dispatched.  This is a contract recovery, not a re-plan.
        file_picker = next((item for item in program.get("migration_tasks", []) if item.get("task_id") == "merge-file-picker-bridge-owners" and item.get("status") == "READY"), None)
        if file_picker and file_picker.get("target_units") == ["plugins/file_picker_bridge"]:
            recovered = _program(Path(str(program.get("cluster_root") or CLUSTER)), {key: program.get(key) for key in ("project_id", "program_id", "adapter", "primary_repository_id")})
            correct = next(item for item in recovered["migration_tasks"] if item.get("task_id") == "merge-file-picker-bridge-owners")
            file_picker.clear(); file_picker.update(correct)
            file_picker["contract_recovery"] = {"status": "FROZEN_CONTRACT_CORRECTED", "reason": "plugins/file_picker_bridge did not exist; the workspace owner is packages/file_picker_bridge."}
        if file_picker:
            file_picker["architecture_preflight"] = _file_picker_contract_preflight(program)
            if file_picker["architecture_preflight"]["status"] != "PASS":
                program.update({"status": "PROGRAM_BLOCKED", "current_migration_task": file_picker["task_id"], "execution_blocker": {"status": "CONTRACT_PREFLIGHT_FAILED", "task_id": file_picker["task_id"], "detail": file_picker["architecture_preflight"]}})
                return {"decomposition_program": program}
        # A checkpoint can be written after review but before a real
        # integration commit is recorded.  Treat DONE as a Git-truth claim,
        # never as a projection of Worker success alone.  Only the current
        # durable WorkerResult can repair/invalidates a task automatically.
        worker = state.get("worker_result")
        # A server restart can restore the checkpoint from receive (RUNNING)
        # instead of the terminal integrate projection.  A successful Worker
        # with no repository delta is still not an executable migration.
        if isinstance(worker, dict) and worker.get("status") == "SUCCESS":
            results = worker.get("repositories", {}) if isinstance(worker.get("repositories"), dict) else {}
            changed = [path for result in results.values() if isinstance(result, dict) for path in result.get("changed_files", [])]
            empty = next((item for item in program.get("migration_tasks", []) if item.get("task_id") == worker.get("task_id") and item.get("status") in {"RUNNING", "DISPATCHING"}), None)
            if isinstance(empty, dict) and not changed:
                empty["status"] = "BLOCKED_DECISION"
                program.update({"status": "PROGRAM_BLOCKED", "current_migration_task": empty["task_id"], "execution_blocker": {"status": "MIGRATION_NO_EFFECT", "task_id": empty["task_id"], "reason": "MigrationTask completed with no business diff; its target creation and package-boundary contract require an explicit decision."}})
                return {"decomposition_program": program, "integration_result": {"status": "MIGRATION_NO_EFFECT", "task_id": empty["task_id"]}}
        # A completed Worker with an architecture rejection is terminal for
        # this frozen task.  It must never be projected as RUNNING merely
        # because the bridge itself returned HTTP success.
        if isinstance(worker, dict) and worker.get("architecture_verdict") == "REJECTED":
            rejected = next((item for item in program.get("migration_tasks", []) if item.get("task_id") == worker.get("task_id") and item.get("status") in {"DISPATCHING", "RUNNING"}), None)
            if rejected:
                guard = (worker.get("validation") or {}).get("architecture_guard", {}) if isinstance(worker.get("validation"), dict) else {}
                rejected["status"] = "BLOCKED_DECISION"
                reason = str(guard.get("reason", "ARCHITECTURE_GUARD_REJECTED"))
                program.update({"status": "PROGRAM_BLOCKED", "current_migration_task": rejected["task_id"], "execution_blocker": {"status": reason, "task_id": rejected["task_id"], "worker_execution_id": worker.get("worker_execution_id"), "reason": "ArchitectureGuard rejected the completed Worker result; no integration commit was created.", "detail": guard, **({"decision_id": f"retry:{rejected['task_id']}", "choices": ["retry"]} if reason == "MIGRATION_NO_EFFECT" else {})}})
                return {"decomposition_program": program, "integration_result": {"status": "ARCHITECTURE_GUARD_REJECTED", "task_id": rejected["task_id"]}}
            recoverable = next((item for item in program.get("migration_tasks", []) if item.get("task_id") == worker.get("task_id") and item.get("status") == "BLOCKED_DECISION"), None)
            if isinstance(recoverable, dict) and recoverable.get("task_id") == "relocate-flutter-study-app":
                updated_guard = _architecture_guard(recoverable, worker, program)
                if updated_guard.get("status") == "PASS":
                    recoverable["status"] = "RUNNING"
                    program.update({"status": "RUNNING", "current_migration_task": recoverable["task_id"]})
                    program.pop("execution_blocker", None)
                    return {"decomposition_program": program, "worker_result": {**worker, "validation": {**(worker.get("validation") or {}), "architecture_guard": updated_guard}, "review": "APPROVED", "architecture_verdict": "APPROVED"}, "integration_result": {"status": "APP_RELOCATION_GUARD_RECONCILED", "task_id": recoverable["task_id"]}}
        if isinstance(worker, dict):
            completed = next((item for item in program.get("migration_tasks", []) if item.get("task_id") == worker.get("task_id") and item.get("status") == "DONE"), None)
            if completed:
                results = worker.get("repositories", {}) if isinstance(worker.get("repositories"), dict) else {}
                changed = [repository for repository, result in results.items() if isinstance(result, dict) and result.get("changed_files")]
                commits = completed.get("integration_commits") if isinstance(completed.get("integration_commits"), dict) else {}
                architecture = (worker.get("validation") or {}).get("architecture_guard", {}) if isinstance(worker.get("validation"), dict) else {}
                valid = (worker.get("status") == "SUCCESS" and worker.get("scope_guard") == "PASS" and architecture.get("status") == "PASS" and worker.get("architecture_verdict") == "APPROVED" and all(commits.get(repository) for repository in changed))
                if not valid:
                    if not changed:
                        completed.pop("integration_commits", None)
                        completed.pop("completed_at", None)
                        completed["status"] = "BLOCKED_DECISION"
                        program.update({"status": "PROGRAM_BLOCKED", "current_migration_task": completed["task_id"], "execution_blocker": {"status": "MIGRATION_NO_EFFECT", "task_id": completed["task_id"], "reason": "MigrationTask completed with no business diff; its target creation and package-boundary contract require an explicit decision.", "detail": architecture}})
                        return {"decomposition_program": program, "integration_result": {"status": "MIGRATION_NO_EFFECT", "task_id": completed["task_id"]}}
                    completed.pop("integration_commits", None)
                    completed.pop("completed_at", None)
                    completed.pop("worker_execution", None)
                    completed["status"] = "READY"
                    program.update({"status": "PLANNING_COMPLETE", "current_migration_task": completed["task_id"], "done_reconciliation": {"status": "INTEGRATION_COMMIT_MISSING", "task_id": completed["task_id"], "changed_repositories": changed, "reason": "DONE lacked a validated architecture verdict and/or integration commit truth; it was returned to READY."}})
                    return {"decomposition_program": program, "integration_result": {"status": "INTEGRATION_COMMIT_MISSING", "task_id": completed["task_id"]}}
        # Preflight ownership-aware cleanup for a READY task.  A managed path
        # is not automatically ours: branch, base revision and exact scope
        # must all prove the stale change set first.
        candidate = next((item for item in program.get("migration_tasks", []) if item.get("task_id") == program.get("current_migration_task") and item.get("status") == "READY"), None)
        if candidate:
            evidence = []
            unknown = []
            for managed in program.get("managed_worktrees", []):
                repository = str(managed.get("repository", ""))
                if repository not in _repositories_for(candidate, program):
                    continue
                worktree = Path(str(managed.get("worktree", "")))
                if not worktree.is_dir():
                    continue
                classified = _classify_managed_dirty(candidate, repository, worktree, str(managed.get("head", "")))
                if classified["classification"] == "AGENT_STALE_DIRTY":
                    restored = _restore_agent_owned_dirty(worktree, str(managed.get("head")), list(classified["changed_files"]))
                    evidence.append({"repository": repository, **classified, "recovery": restored})
                    if restored["status"] != "RESTORED":
                        unknown.append({"repository": repository, **classified, "recovery": restored})
                elif classified["classification"] == "USER_UNKNOWN_DIRTY":
                    unknown.append({"repository": repository, **classified})
            if unknown:
                program.update({"status": "PROGRAM_BLOCKED", "execution_blocker": {"status": "USER_INTEGRATION_DIRTY", "task_id": candidate["task_id"], "repositories": unknown, "reason": "Managed worktree changes could not be proven Agent-owned."}})
                return {"decomposition_program": program}
            if evidence:
                program["stale_recovery"] = {"status": "AGENT_STALE_INTEGRATION_RECOVERED", "task_id": candidate["task_id"], "repositories": evidence}
                program.pop("execution_blocker", None)
                program["status"] = "PLANNING_COMPLETE"
        # A server restart can interrupt a Run after ``freeze`` has marked a
        # task DISPATCHING but before the Worker request has been created.  A
        # DISPATCHING task is only durable while it has concrete execution
        # evidence.  Never guess when there is any evidence or worktree diff:
        # retain the evidence and make the ambiguity visible to the operator.
        for task in program.get("migration_tasks", []):
            if task.get("status") != "DISPATCHING":
                continue
            task_id = str(task.get("task_id", ""))
            execution = task.get("worker_execution")
            execution = execution if isinstance(execution, dict) else {}
            evidence = {
                key: value
                for key, value in {
                    "worker_execution_id": execution.get("worker_execution_id") or task.get("worker_execution_id"),
                    "worker_workspace": execution.get("worker_workspace") or task.get("worker_workspace"),
                    "worker_started_at": execution.get("worker_started_at") or execution.get("dispatched_at") or task.get("worker_started_at"),
                }.items()
                if value
            }
            persisted_result = isinstance(worker, dict) and worker.get("task_id") == task_id
            repositories = _repositories_for(task, program)
            dirty = [
                {"repository": repository, "changed_files": _changes(_ensure_worktree(repository, program)[0])}
                for repository in repositories
                if _changes(_ensure_worktree(repository, program)[0])
            ]
            if not evidence and not persisted_result and not dirty:
                task.pop("worker_execution", None)
                task.pop("worker_execution_id", None)
                task.pop("worker_workspace", None)
                task.pop("worker_started_at", None)
                task["status"] = "READY"
                program.update({"status": "PLANNING_COMPLETE", "current_migration_task": task_id})
                program.pop("execution_blocker", None)
                continue
            task["status"] = "BLOCKED_DECISION"
            program.update({
                "status": "PROGRAM_BLOCKED",
                "current_migration_task": task_id,
                "execution_blocker": {
                    "status": "STALE_DISPATCHING_CONFLICT",
                    "task_id": task_id,
                    "worker_execution": evidence,
                    "has_worker_result": persisted_result,
                    "repositories": dirty,
                    "reason": "A DISPATCHING task has execution evidence, a persisted result, or unmanaged changes; it cannot be safely returned to READY.",
                },
            })
            return {"decomposition_program": program}
        blocker = program.get("execution_blocker") or {}
        recovering_task = str(blocker.get("task_id", ""))
        # A cancelled/restarted Run may have replaced INTEGRATION_FAILED with a
        # stale projection.  The durable WorkerResult is still authoritative
        # when every managed change equals its guarded per-repository result.
        recovered = next((item for item in program.get("migration_tasks", []) if item.get("task_id") == (worker or {}).get("task_id")), None) if isinstance(worker, dict) else None
        architecture = (worker.get("validation") or {}).get("architecture_guard", {}) if isinstance(worker, dict) and isinstance(worker.get("validation"), dict) else {}
        resumable = isinstance(worker, dict) and worker.get("status") == "SUCCESS" and worker.get("review") == "APPROVED" and worker.get("architecture_verdict") == "APPROVED" and architecture.get("status") == "PASS"
        if recovered and resumable:
            repositories = _repositories_for(recovered, program)
            matches = all(_changes(_ensure_worktree(repository, program)[0]) == _worker_change_set(worker, repository) for repository in repositories)
            if matches:
                recovered["status"] = "RUNNING"
                program.update({"status": "RUNNING", "current_migration_task": recovered["task_id"]})
                program.pop("execution_blocker", None)
                recovering_task = recovered["task_id"]
        if blocker.get("status") == "INTEGRATION_FAILED":
            task = next((item for item in program.get("migration_tasks", []) if item.get("task_id") == blocker.get("task_id")), None)
            if task and resumable:
                task["status"] = "RUNNING"
                program.update({"status": "RUNNING", "current_migration_task": task["task_id"]})
                program.pop("execution_blocker", None)
        # A historical integration failure has a worker-owned diff.  It is
        # explicitly resumable, not an unknown stale-running mutation.
        protected = recovering_task
        for task in program.get("migration_tasks", []):
            if task.get("status") != "RUNNING" or task.get("task_id") == protected:
                continue
            evidence = task.get("worker_execution")
            if isinstance(evidence, dict) and evidence.get("worker_execution_id"):
                continue
            repositories = _repositories_for(task, program)
            dirty = [{"repository": repo, "changed_files": _changes(_ensure_worktree(repo, program)[0])} for repo in repositories if _changes(_ensure_worktree(repo, program)[0])]
            if dirty:
                task["status"] = "BLOCKED_DECISION"
                program.update({"status": "PROGRAM_BLOCKED", "current_migration_task": task.get("task_id"), "execution_blocker": {"status": "STALE_RUNNING_PARTIAL_OUTPUT", "task_id": task.get("task_id"), "repositories": dirty, "reason": "A stale RUNNING task has unowned managed-worktree changes; it was not cleaned automatically."}})
            else:
                task["status"] = "READY"
                task.pop("worker_execution", None)
                if program.get("current_migration_task") == task.get("task_id"):
                    program["current_migration_task"] = None
                program.pop("execution_blocker", None)
                program["status"] = "PLANNING_COMPLETE"
        blocker = program.get("execution_blocker") or {}
        if blocker.get("status") in {"STALE_RUNNING_PARTIAL_OUTPUT", "INTEGRATION_FAILED"}:
            task_id = str(blocker.get("task_id", ""))
            task = next((item for item in program.get("migration_tasks", []) if item.get("task_id") == task_id), None)
            if task and not (isinstance(state.get("worker_result"), dict) and state["worker_result"].get("task_id") == task_id and state["worker_result"].get("status") == "SUCCESS"):
                task["status"] = "BLOCKED_DECISION"
                program.update({"status": "PROGRAM_BLOCKED", "current_migration_task": task_id, "execution_blocker": {**blocker, "status": "RETRY_REQUIRED", "task_id": task_id, "reason": "Managed integration changes exist but the durable WorkerResult is unavailable; retry requires explicit recovery authority."}})
                return {"decomposition_program": program}
        return {"decomposition_program": program}

    def propose_task(state: State):
        program = dict(state.get("decomposition_program") or {})
        program["execution_mode"] = "PLAN_ONLY"
        spec = state.get("proposal_spec")
        if not isinstance(spec, dict):
            return {"decomposition_program": program}
        tasks = list(program.get("migration_tasks", []))
        task_id = str(spec.get("task_id", ""))
        existing = next((task for task in tasks if task.get("task_id") == task_id), None)
        if existing is None:
            frozen = _proposal_inventory(program, spec)
            tasks.append(frozen)
            program["migration_tasks"] = tasks
            if frozen.get("status") == "READY" and not program.get("current_migration_task"):
                program["current_migration_task"] = task_id
            program["last_proposal"] = {"task_id": task_id, "status": frozen.get("status"), "idempotent": False}
        else:
            proposal = existing.get("proposal")
            if isinstance(proposal, dict) and proposal.get("read_only") and existing.get("status") in {"READY", "BLOCKED_DECISION"} and not existing.get("worker_execution"):
                frozen = _proposal_inventory(program, spec)
                tasks[tasks.index(existing)] = frozen
                program["migration_tasks"] = tasks
                existing = frozen
            program["last_proposal"] = {"task_id": task_id, "status": existing.get("status"), "idempotent": True}
        return {"decomposition_program": program, "proposal_spec": {}, "worker_result": {}, "migration_request": {}, "integration_result": {}}

    def sync_base(state: State):
        program = dict(state.get("decomposition_program") or {})
        request = state.get("sync_base")
        if not isinstance(request, dict):
            return {"decomposition_program": program}
        repository = str(request.get("repository") or _primary_repository(program))
        target_revision = str(request.get("target_revision") or "")
        worktree, branch = _ensure_worktree(repository, program)
        current = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=worktree, text=True).strip()
        changed = _changes(worktree)
        if changed:
            result = {"status": "SYNC_DIRTY", "repository": repository, "current_revision": current, "target_revision": target_revision, "changed_files": changed}
        elif not target_revision or subprocess.run(["git", "cat-file", "-e", f"{target_revision}^{{commit}}"], cwd=worktree, capture_output=True).returncode:
            result = {"status": "SYNC_TARGET_NOT_FOUND", "repository": repository, "current_revision": current, "target_revision": target_revision}
        elif subprocess.run(["git", "merge-base", "--is-ancestor", current, target_revision], cwd=worktree).returncode:
            result = {"status": "SYNC_DIVERGED", "repository": repository, "current_revision": current, "target_revision": target_revision}
        else:
            advanced = subprocess.run(["git", "merge", "--ff-only", target_revision], cwd=worktree, text=True, capture_output=True)
            new_head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=worktree, text=True).strip()
            result = {"status": "SYNCED" if advanced.returncode == 0 and new_head == target_revision else "SYNC_FAILED", "repository": repository, "branch": branch, "previous_revision": current, "target_revision": target_revision, "head": new_head, "stderr": advanced.stderr[-1000:]}
            if result["status"] == "SYNCED":
                program["base_sync"] = result
                program["managed_worktrees"] = [{"repository": repository, "worktree": str(worktree), "branch": branch, "head": new_head}]
        return {"decomposition_program": program, "sync_base": {}, "sync_result": result, "worker_result": {}, "migration_request": {}, "integration_result": {}}

    def freeze(state: State):
        program = state["decomposition_program"]
        if state.get("reconcile_only"):
            return {"decomposition_program": program}
        if program.get("status") == "STATE_NOT_LOADED":
            return {"decomposition_program": program}
        if not state.get("execute"):
            return {}
        if program.get("status") == "PROGRAM_BLOCKED":
            return {"decomposition_program": program}
        program["execution_mode"] = "EXECUTE"
        task = next((item for item in program.get("migration_tasks", []) if item.get("task_id") == program.get("current_migration_task") and item.get("status") == "RUNNING"), None)
        if task and isinstance(state.get("worker_result"), dict) and state["worker_result"].get("status") == "SUCCESS":
            return {}
        task = _select(program)
        if task is None:
            program["status"] = "PROGRAM_COMPLETED"
            return {"decomposition_program": program}
        repositories = _repositories_for(task, program)
        managed, dirty = [], []
        for repository in repositories:
            worktree, branch = _ensure_worktree(repository, program)
            changed = _changes(worktree)
            managed.append({"repository": repository, "worktree": str(worktree), "branch": branch, "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=worktree, text=True).strip()})
            if changed:
                dirty.append({"repository": repository, "worktree": str(worktree), "changed_files": changed})
        program["managed_worktrees"] = managed
        if dirty:
            program.update({"status": "PROGRAM_BLOCKED", "current_migration_task": task["task_id"], "execution_blocker": {"status": "USER_INTEGRATION_DIRTY", "task_id": task["task_id"], "repositories": dirty, "reason": "A task-scoped managed decomposition worktree has pre-existing changes."}})
            return {"decomposition_program": program}
        allowed = {repo: _allowed(task, repo) for repo in repositories}
        if not all(allowed.values()):
            program.update({"status": "PROGRAM_BLOCKED", "current_migration_task": task["task_id"], "execution_blocker": {"status": "WORKER_DISPATCH_FAILED", "task_id": task["task_id"], "reason": "No frozen exact allowed paths for this MigrationTask."}})
            return {"decomposition_program": program}
        task["status"] = "DISPATCHING"
        program.update({"status": "DISPATCHING", "current_migration_task": task["task_id"]})
        roles = _mutation_repositories(task, program)
        if set(roles) != set(repositories):
            program.update({"status": "PROGRAM_BLOCKED", "current_migration_task": task["task_id"], "execution_blocker": {"status": "WORKER_SCOPE_CONFIGURATION_ERROR", "task_id": task["task_id"], "reason": "Frozen mutation repositories do not match the frozen workspace repositories."}})
            return {"decomposition_program": program}
        request = {"execution_kind": "decomposition_migration", "task_id": task["task_id"], "requirement": str(task.get("title", task["task_id"])) + ". Source units: " + ", ".join(task["source_units"]) + ". Target units: " + ", ".join(task["target_units"]), "source_units": task["source_units"], "target_units": task["target_units"], "allowed_operations": task["allowed_operations"], "target_creation_allowed": bool(task.get("target_creation_allowed", False)), "dependency_constraints": task.get("dependency_constraints", []), "execution_instructions": task.get("execution_instructions", []), "architecture_preflight": task.get("architecture_preflight", {}), "timeout_seconds": int(os.environ.get("AGENT_HUB_CODEX_TIMEOUT_SECONDS", "1800")), "allowed_paths_by_repository": allowed, "writable_repositories": [{"repository": repository, "role": roles[repository], "writable": True, "allowed_paths": allowed[repository]} for repository in repositories], "repositories": [{"repository": item["repository"], "base_revision": item["head"], "role": roles[item["repository"]], "writable": True, "allowed_paths": allowed[item["repository"]]} for item in managed]}
        return {"decomposition_program": program, "migration_request": request}

    def dispatch(state: State):
        request = state.get("migration_request")
        if not isinstance(request, dict):
            return {}
        task_id = str(request.get("task_id", ""))
        LOGGER.info("DECOMPOSITION_DISPATCH_ENTER task_id=%s", task_id)
        try:
            worker = _worker(request, state.get("worker_endpoint"))
        except Exception as error:
            # A graph-node exception would leave freeze's DISPATCHING
            # checkpoint behind.  Convert every bridge failure into the same
            # terminal result consumed by receive/reconciliation.
            LOGGER.exception("DECOMPOSITION_DISPATCH_FAILED task_id=%s", task_id)
            worker = {"status": "WORKER_DISPATCH_FAILED", "task_id": task_id, "reason": "worker_bridge_exception", "detail": str(error)}
        LOGGER.info("DECOMPOSITION_WORKER_INVOKED task_id=%s status=%s execution_id=%s", task_id, worker.get("status"), worker.get("worker_execution_id", ""))
        return {"worker_result": worker}

    def receive(state: State):
        program, worker = state["decomposition_program"], state.get("worker_result") or {}
        task = next((item for item in program.get("migration_tasks", []) if item.get("task_id") == program.get("current_migration_task")), None)
        if not task:
            return {}
        if worker.get("status") == "SUCCESS" and worker.get("worker_execution_id"):
            task.update({"status": "RUNNING", "worker_execution": {key: worker.get(key) for key in ("worker_execution_id", "worker_workspace", "dispatched_at")}})
            program["status"] = "RUNNING"
        else:
            task["status"] = "BLOCKED_DECISION"
            program.update({"status": "PROGRAM_BLOCKED", "execution_blocker": {"status": worker.get("status", "WORKER_DISPATCH_FAILED"), "task_id": task["task_id"], "reason": str(worker.get("reason", "worker_dispatch_failed")), "detail": worker.get("detail", "")}, "current_migration_task": None})
        return {"decomposition_program": program}

    def validate(state: State):
        worker = state.get("worker_result") or {}
        program = state.get("decomposition_program") or {}
        task = next((item for item in program.get("migration_tasks", []) if item.get("task_id") == worker.get("task_id")), {}) if isinstance(program, dict) else {}
        results = worker.get("repositories", {}) if isinstance(worker.get("repositories"), dict) else {}
        changed = [path for result in results.values() if isinstance(result, dict) for path in result.get("changed_files", [])]
        if isinstance(task, dict) and worker.get("status") == "SUCCESS" and not changed:
            guard = {"status": "REJECT", "reason": "MIGRATION_NO_EFFECT", "detail": "MigrationTask produced no repository changes; a move/create contract cannot be inferred or approved."}
        else:
            guard = _architecture_guard(task, worker, program) if isinstance(task, dict) and worker.get("status") == "SUCCESS" else {"status": "REJECT", "reason": "worker_not_successful"}
        return {"worker_result": {**worker, "validation": {"scope_guard": "PASS" if worker.get("scope_guard") == "PASS" else "FAILED", "architecture_guard": guard}}, "revalidate_worker": False}

    def review(state: State):
        worker = state.get("worker_result") or {}
        architecture = (worker.get("validation") or {}).get("architecture_guard", {}) if isinstance(worker.get("validation"), dict) else {}
        approved = worker.get("status") == "SUCCESS" and worker.get("scope_guard") == "PASS" and not worker.get("unauthorized_files") and architecture.get("status") == "PASS"
        return {"worker_result": {**worker, "review": "APPROVED" if approved else "CHANGES_REQUIRED", "architecture_verdict": "APPROVED" if approved else "REJECTED"}}

    def integrate(state: State):
        program, worker = state["decomposition_program"], state.get("worker_result") or {}
        task = next((item for item in program.get("migration_tasks", []) if item.get("task_id") == program.get("current_migration_task")), None)
        if not task:
            return {}
        if worker.get("status") != "SUCCESS" or worker.get("review") != "APPROVED" or worker.get("architecture_verdict") != "APPROVED":
            guard = (worker.get("validation") or {}).get("architecture_guard", {}) if isinstance(worker.get("validation"), dict) else {}
            task["status"] = "BLOCKED_DECISION"
            program.update({"status": "PROGRAM_BLOCKED", "current_migration_task": task["task_id"], "execution_blocker": {"status": str(guard.get("reason", worker.get("status", "REVIEW_REJECTED"))), "task_id": task["task_id"], "worker_execution_id": worker.get("worker_execution_id"), "reason": "Worker/architecture review did not satisfy the integration gate.", "detail": guard}})
            return {"decomposition_program": program, "integration_result": {"status": "ARCHITECTURE_GUARD_REJECTED", "task_id": task["task_id"]}}
        commits: dict[str, str] = {}
        try:
            for repository, result in worker.get("repositories", {}).items():
                worktree, _ = _ensure_worktree(repository, program)
                allowed, diff = _allowed(task, repository), str(result.get("diff", ""))
                worker_changed = _worker_change_set(worker, repository)
                changed = _changes(worktree)
                if diff and not changed:
                    checked = subprocess.run(["git", "apply", "--check", "--whitespace=nowarn", "-"], cwd=worktree, input=diff, text=True, capture_output=True)
                    if checked.returncode:
                        raise RuntimeError(f"APPLY_CONFLICT {repository}: {checked.stderr[-500:]}")
                    subprocess.run(["git", "apply", "--whitespace=nowarn", "-"], cwd=worktree, input=diff, text=True, check=True, capture_output=True)
                changed = _changes(worktree)
                if worker_changed and sorted(changed) != worker_changed:
                    raise RuntimeError(f"INTEGRATION_WORKTREE_MISMATCH {repository}: expected {worker_changed}, found {changed}")
                if not _scope_ok(changed, allowed):
                    raise RuntimeError(f"INTEGRATION_SCOPE_VIOLATION {repository}: {changed}")
                if changed:
                    stage = _stage_validated_changes(worktree, changed)
                    if stage.get("status") != "STAGED":
                        raise RuntimeError(f"{stage.get('status')} {repository}: {stage.get('stderr', '')}")
                    committed = subprocess.run(["git", "commit", "--no-verify", "-m", f"refactor: {task['task_id']} [{task['task_id']}]"], cwd=worktree, capture_output=True, text=True)
                    if committed.returncode:
                        raise RuntimeError(f"COMMIT_FAILED {repository}: {committed.stderr[-500:]}")
                    commits[repository] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=worktree, text=True).strip()
            task.update({"status": "DONE", "worker_execution": task.get("worker_execution"), "integration_commits": commits, "completed_at": datetime.now(UTC).isoformat()})
            program.update({"integration_head": commits, "current_migration_task": None, "status": "PLANNING_COMPLETE"})
            return {"decomposition_program": program, "integration_result": {"status": "COMMITTED", "commits": commits}}
        except Exception as error:
            task["status"] = "BLOCKED_DECISION"
            program.update({"status": "PROGRAM_BLOCKED", "current_migration_task": task["task_id"], "execution_blocker": {"status": "INTEGRATION_FAILED", "task_id": task["task_id"], "reason": str(error)}})
            return {"decomposition_program": program, "integration_result": {"status": "INTEGRATION_FAILED", "reason": str(error)}}

    graph.add_node("reconcile", reconcile)
    graph.add_node("propose_task", propose_task)
    graph.add_node("sync_base", sync_base)
    graph.add_node("freeze", freeze)
    graph.add_node("dispatch", dispatch)
    graph.add_node("receive", receive)
    graph.add_node("validate", validate)
    graph.add_node("review", review)
    graph.add_node("integrate", integrate)
    graph.add_edge(START, "reconcile")
    def route_after_reconcile(state: State):
        if state.get("reconcile_only"):
            return END
        if isinstance(state.get("sync_base"), dict) and state.get("sync_base"):
            return "sync_base"
        if isinstance(state.get("proposal_spec"), dict) and state.get("proposal_spec"):
            return "propose_task"
        if state.get("revalidate_worker"):
            return "validate"
        program = state.get("decomposition_program")
        worker = state.get("worker_result")
        current = program.get("current_migration_task") if isinstance(program, dict) else None
        if current and isinstance(worker, dict) and worker.get("status") == "SUCCESS" and worker.get("task_id") == current:
            return "integrate"
        return "freeze"

    graph.add_conditional_edges("reconcile", route_after_reconcile, {END: END, "sync_base": "sync_base", "propose_task": "propose_task", "validate": "validate", "integrate": "integrate", "freeze": "freeze"})
    graph.add_edge("sync_base", END)
    graph.add_edge("propose_task", END)
    graph.add_conditional_edges("freeze", lambda state: "dispatch" if state.get("migration_request") else END, {"dispatch": "dispatch", END: END})
    graph.add_edge("dispatch", "receive")
    graph.add_conditional_edges("receive", lambda state: "validate" if (state.get("worker_result") or {}).get("status") == "SUCCESS" else END, {"validate": "validate", END: END})
    graph.add_edge("validate", "review")
    graph.add_edge("review", "integrate")
    graph.add_edge("integrate", END)
    return graph.compile()
