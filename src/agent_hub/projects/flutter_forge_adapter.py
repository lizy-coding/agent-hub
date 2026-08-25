"""Flutter Forge project facts used by its decomposition adapter.

This module is deliberately independent from the graph.  The graph must not
know which packages, app roots, or capability owners belong to Flutter Forge.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path


def _pubspec(path: Path) -> tuple[str, list[str]]:
    text = path.read_text(encoding="utf-8")
    name = re.search(r"^name:\s*(\S+)", text, re.M)
    dependencies = re.findall(r"^\s{2}([a-zA-Z_][\w_]*):\s*$", text, re.M)
    return (name.group(1) if name else path.parent.name, dependencies)


def build_program(root: Path, context: dict[str, object]) -> dict[str, object]:
    primary = str(context.get("primary_repository_id") or "flutter_forge")
    paths = context.get("repository_paths")
    repository_root = Path(str(paths.get(primary))) if isinstance(paths, dict) and paths.get(primary) else root / primary
    repositories = []
    manifest = repository_root / "pubspec.yaml"
    if manifest.is_file():
        package_name, dependencies = _pubspec(manifest)
        repositories.append({
            "repository_id": primary,
            "path": str(repository_root),
            "role": "APP",
            "package_name": package_name,
            "pubspec": str(manifest),
            "dependencies": dependencies,
            "consumers": [],
        })
    capabilities = [
        {"capability_id": "gcode-parser-toolpath", "current_owners": ["flutter_forge/packages/gcode_core"], "source_paths": ["flutter_forge/packages/gcode_core/lib"], "consumers": ["flutter_forge:gcode_visualizer"], "dependencies": ["flutter"], "flutter_dependency": True, "platform_dependency": False, "native_dependency": False, "state_dependency": False, "reuse_scope": "cluster", "classification": "KEEP_PACKAGE", "target_package": "packages/gcode_core"},
        {"capability_id": "file-picker-platform-bridge", "current_owners": ["flutter_forge/packages/file_picker_bridge"], "source_paths": ["flutter_forge/packages/file_picker_bridge/lib"], "consumers": ["flutter_forge:file_picker", "flutter_forge:gcode_visualizer", "flutter_forge:font_picker"], "dependencies": ["flutter/services"], "flutter_dependency": True, "platform_dependency": True, "native_dependency": False, "state_dependency": False, "reuse_scope": "cluster", "classification": "KEEP_PACKAGE", "target_package": "packages/file_picker_bridge"},
        {"capability_id": "learning-scaffold", "current_owners": ["flutter_forge/packages/flutter_study_learning"], "source_paths": ["flutter_forge/packages/flutter_study_learning/lib"], "consumers": ["flutter_forge:modules"], "dependencies": ["flutter"], "flutter_dependency": True, "platform_dependency": False, "native_dependency": False, "state_dependency": False, "reuse_scope": "cluster", "classification": "KEEP_PACKAGE", "target_package": "packages/flutter_study_learning"},
        {"capability_id": "ioc-composition-services", "current_owners": ["flutter_forge/packages/flutter_ioc_core"], "source_paths": ["flutter_forge/packages/flutter_ioc_core/lib"], "consumers": ["flutter_forge:modules"], "dependencies": ["flutter"], "flutter_dependency": True, "platform_dependency": False, "native_dependency": False, "state_dependency": False, "reuse_scope": "cluster", "classification": "KEEP_PACKAGE", "target_package": "packages/flutter_ioc_core"},
        {"capability_id": "app-composition-routing", "current_owners": ["flutter_forge/apps/flutter_forge"], "source_paths": ["flutter_forge/apps/flutter_forge/lib"], "consumers": [], "dependencies": ["go_router", "flutter"], "flutter_dependency": True, "platform_dependency": False, "native_dependency": False, "state_dependency": True, "reuse_scope": "app", "classification": "KEEP_APP_ONLY", "target_package": "apps/flutter_forge"},
        {"capability_id": "windows-resilient-online-video-playback", "current_owners": ["flutter_forge/apps/flutter_forge/lib/modules/platform/online_video_player"], "source_paths": ["flutter_forge/apps/flutter_forge/lib/modules/platform/online_video_player"], "consumers": ["flutter_forge:online_video_player"], "dependencies": ["dio", "video_player", "video_player_win"], "flutter_dependency": True, "platform_dependency": True, "native_dependency": True, "state_dependency": True, "reuse_scope": "app", "classification": "KEEP_APP_ONLY", "target_package": "apps/flutter_forge"},
    ]
    candidates = [
        {"package_id": "packages/gcode_core", "package_type": "FLUTTER_PACKAGE", "target_path": "packages/gcode_core", "owned_capabilities": ["gcode-parser-toolpath"], "dependencies": [], "public_api_intent": "parser and toolpath API", "migration_priority": 1},
        {"package_id": "packages/file_picker_bridge", "package_type": "FLUTTER_PACKAGE", "target_path": "packages/file_picker_bridge", "owned_capabilities": ["file-picker-platform-bridge"], "dependencies": [], "public_api_intent": "platform-neutral file picker API", "migration_priority": 1},
        {"package_id": "packages/flutter_ioc_core", "package_type": "FLUTTER_PACKAGE", "target_path": "packages/flutter_ioc_core", "owned_capabilities": ["ioc-composition-services"], "dependencies": [], "public_api_intent": "composition IoC services", "migration_priority": 2},
        {"package_id": "packages/flutter_study_learning", "package_type": "FLUTTER_PACKAGE", "target_path": "packages/flutter_study_learning", "owned_capabilities": ["learning-scaffold"], "dependencies": [], "public_api_intent": "learning UI templates", "migration_priority": 2},
        {"package_id": "apps/flutter_forge", "package_type": "APP_ONLY", "target_path": "apps/flutter_forge", "owned_capabilities": ["app-composition-routing", "windows-resilient-online-video-playback"], "dependencies": ["packages/gcode_core", "packages/file_picker_bridge", "packages/flutter_study_learning", "packages/flutter_ioc_core", "dio", "video_player", "video_player_win"], "public_api_intent": "application composition and platform-specific teaching capabilities", "migration_priority": 3},
    ]
    tasks = [
        {"task_id": "merge-gcode-core-owners", "title": "Confirm the G-code package owner", "source_units": ["flutter_forge/packages/gcode_core"], "target_units": ["packages/gcode_core"], "depends_on": [], "allowed_operations": [], "allowed_paths_by_repository": {"flutter_forge": ["packages/gcode_core"]}, "acceptance": ["single owner remains packages/gcode_core"], "status": "DONE", "evidence": ["registry discovers packages/gcode_core only inside flutter_forge"]},
        {"task_id": "merge-file-picker-bridge-owners", "title": "Confirm the file picker bridge package owner", "source_units": ["flutter_forge/packages/file_picker_bridge"], "target_units": ["packages/file_picker_bridge"], "depends_on": [], "allowed_operations": [], "allowed_paths_by_repository": {"flutter_forge": ["packages/file_picker_bridge"]}, "target_creation_allowed": False, "dependency_constraints": ["flutter_forge depends only on packages/file_picker_bridge", "packages/file_picker_bridge must not depend on apps/flutter_forge", "no dependency cycle"], "acceptance": ["exactly one reusable file picker owner remains packages/file_picker_bridge"], "status": "DONE", "evidence": ["registry discovers packages/file_picker_bridge only inside flutter_forge"]},
        {**app_relocation_contract(), "status": "DONE"},
        {"task_id": "establish-package-boundary-contracts", "title": "Add per-package ownership contracts, independent test entries, and version pins", "source_units": [], "target_units": ["packages/gcode_core", "packages/file_picker_bridge", "packages/flutter_study_learning", "packages/flutter_ioc_core"], "depends_on": ["relocate-flutter-forge-app"], "allowed_operations": [], "allowed_paths_by_repository": {"flutter_forge": ["packages/gcode_core", "packages/file_picker_bridge", "packages/flutter_study_learning", "packages/flutter_ioc_core"]}, "target_creation_allowed": False, "status": "READY", "evidence": ["workspace declares four package members consumed only by apps/flutter_forge"]},
    ]
    return {
        "project_id": str(context.get("project_id") or "flutter-forge"),
        "program_id": str(context.get("program_id") or "flutter-forge-decomposition-program"),
        "adapter": "flutter_forge",
        "primary_repository_id": primary,
        "cluster_root": str(root),
        "repositories": repositories,
        "capabilities": capabilities,
        "package_candidates": candidates,
        "target_dependency_graph": {"nodes": [item["package_id"] for item in candidates], "edges": [["apps/flutter_forge", item] for item in ["packages/gcode_core", "packages/file_picker_bridge", "packages/flutter_study_learning", "packages/flutter_ioc_core"]], "cycles": []},
        "migration_tasks": tasks,
        "human_decisions": [],
        "integration_head": None,
        "execution_mode": "PLAN_ONLY",
        "status": "PLANNING_COMPLETE",
    }


def app_relocation_contract() -> dict[str, object]:
    return {
        "task_id": "relocate-flutter-forge-app",
        "title": "Create apps/flutter_forge as the only Flutter Application owner",
        "source_units": ["flutter_forge/root_flutter_application"],
        "target_units": ["apps/flutter_forge"],
        "depends_on": ["merge-gcode-core-owners", "merge-file-picker-bridge-owners"],
        "allowed_operations": ["MOVE", "RENAME", "DEPENDENCY_REWRITE", "API_BREAK"],
        "target_creation_allowed": True,
        "allowed_paths_by_repository": {"flutter_forge": ["apps/flutter_forge", "lib", "macos", "windows", "android", "ios", "linux", "web", "assets", "test", "integration_test", "pubspec.yaml", "pubspec.lock", ".metadata", "analysis_options.yaml", "l10n.yaml", "flutterguard.yaml"]},
        "dependency_constraints": ["apps/flutter_forge may depend on packages/* and plugins/*", "packages/* and plugins/* must not depend on apps/flutter_forge", "workspace dependency cycles must remain zero"],
        "execution_instructions": ["Create apps/flutter_forge as a Flutter application with pubspec.yaml and lib/main.dart.", "Move only app-owned runtime sources, hosts, assets, tests and configuration after inspecting ownership; do not move packages/* or plugins/*.", "Rewrite app package paths relative to apps/flutter_forge and retain root pubspec.yaml only as a workspace/container manifest without Flutter Application ownership.", "Move the existing macos and windows hosts; move other platform hosts only when they exist."],
        "acceptance": ["apps/flutter_forge/pubspec.yaml and apps/flutter_forge/lib/main.dart exist", "root has no lib/main.dart or lib/app duplicate App owner", "packages/* and plugins/* remain at workspace root", "app package paths resolve from apps/flutter_forge", "changed repository receives one integration commit"],
        "status": "READY",
        "evidence": ["root pubspec.yaml currently owns Flutter application dependencies and workspace members", "lib/main.dart bootstraps lib/app", "macos and windows are the actual root platform hosts"],
    }


def file_picker_contract_preflight(program: dict[str, object] | None = None) -> dict[str, object]:
    from agent_hub.graphs.decomposition import _ensure_worktree, _primary_repository
    primary = _primary_repository(program)
    target = _ensure_worktree(primary, program)[0] / "packages/file_picker_bridge"
    target_ready = (target / "pubspec.yaml").is_file() and (target / "lib").is_dir()
    return {"status": "PASS" if target_ready else "REJECT", "capability_owner": "flutter_forge/packages/file_picker_bridge", "target_package_root": "packages/file_picker_bridge", "required_dependency_rewrites": [], "reason": "workspace package owner is present" if target_ready else "workspace package owner cannot be proven"}


def default_allowed_paths(task_id: str, repository: str) -> list[str]:
    return {
        "merge-gcode-core-owners": {"flutter_forge": ["packages/gcode_core"]},
        "merge-file-picker-bridge-owners": {"flutter_forge": ["packages/file_picker_bridge"]},
        "relocate-flutter-forge-app": {"flutter_forge": ["lib/app", "lib", "pubspec.yaml", "flutterguard.yaml"]},
    }.get(task_id, {}).get(repository, [])

def architecture_guard(task: dict[str, object], worker: dict[str, object], program: dict[str, object]) -> dict[str, object]:
    """Prove that a merge preserves a concrete target capability owner."""
    from agent_hub.graphs.decomposition import _ensure_worktree, _primary_repository, _worker_change_set
    repositories = worker.get("repositories", {})
    if not isinstance(repositories, dict):
        return {"status": "REJECT", "reason": "missing_repository_results"}
    target_units = [str(unit) for unit in task.get("target_units", [])]
    if not target_units:
        return {"status": "REJECT", "reason": "merge_task_has_no_target_units"}
    deleted = [path for result in repositories.values() if isinstance(result, dict) for path in result.get("changed_files", [])]
    source_deleted = bool(deleted)
    primary = _primary_repository(program)
    if task.get("task_id") == "rename-project-to-flutter-forge":
        changed = _worker_change_set(worker, primary)
        required = {
            "pubspec.yaml",
            "apps/flutter_study/pubspec.yaml",
            "apps/flutter_forge/pubspec.yaml",
            "apps/flutter_study/lib/main.dart",
            "apps/flutter_forge/lib/main.dart",
        }
        missing = sorted(required - set(changed))
        if missing:
            return {
                "status": "REJECT",
                "reason": "flutter_forge_rename_incomplete",
                "missing_changed_paths": missing,
                "changed_files": changed,
            }
        if any(path.startswith(("packages/", "plugins/")) for path in changed):
            return {
                "status": "REJECT",
                "reason": "flutter_forge_rename_crossed_package_boundary",
                "changed_files": changed,
            }
        diff = str((worker.get("repositories") or {}).get(primary, {}).get("diff", ""))
        added = "\n".join(
            line for line in diff.splitlines()
            if line.startswith("+") and not line.startswith("+++")
        )
        if (
            "name: flutter_forge_workspace" not in added
            or "apps/flutter_forge" not in added
            or "name: flutter_forge_app" not in added
            or "package:flutter_study_app/" in added
        ):
            return {
                "status": "REJECT",
                "reason": "flutter_forge_identity_evidence_missing",
            }
        return {
            "status": "PASS",
            "guard_kind": "project_identity_rename",
            "project_identity_before": "flutter_study",
            "project_identity_after": "flutter_forge",
            "app_owner_before": "apps/flutter_study",
            "app_owner_after": "apps/flutter_forge",
            "independent_package_boundary": "PASS",
        }
    if task.get("task_id") == "replace-media-plugin-with-video-player":
        changed = _worker_change_set(worker, primary)
        required = {
            "apps/flutter_forge/pubspec.yaml",
            "apps/flutter_forge/lib/modules/platform/online_video_player/module_root.dart",
            "apps/flutter_forge/lib/modules/platform/online_video_player/state/media_kit_player_adapter.dart",
            "apps/flutter_forge/lib/modules/platform/online_video_player/state/video_player_adapter.dart",
            "apps/flutter_forge/test/modules/platform/online_video_player/online_video_player_test.dart",
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
        required = {"apps/flutter_forge/pubspec.yaml", ".run/Flutter_Forge_macOS.run.xml"}
        if not required.issubset(set(changed)):
            return {"status": "REJECT", "reason": "package_rename_incomplete", "missing_changed_paths": sorted(required - set(changed))}
        if any(path.startswith(("packages/", "plugins/")) for path in changed):
            return {"status": "REJECT", "reason": "package_rename_crossed_package_boundary", "changed_files": changed}
        diff = str((worker.get("repositories") or {}).get(primary, {}).get("diff", ""))
        added = "\n".join(line for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++"))
        if "name: flutter_forge_app" not in added or "package:flutter_forge_app/" not in added or "package:main_app/" in added:
            return {"status": "REJECT", "reason": "package_rename_evidence_missing"}
        return {"status": "PASS", "guard_kind": "dart_package_rename", "capability_owner_before": ["main_app"], "capability_owner_after": ["flutter_forge_app"], "run_configuration": "PRESENT", "package_boundary": "PASS"}
    if task.get("task_id") == "relocate-flutter-forge-app":
        root = _ensure_worktree(primary, program)[0]
        target = root / "apps/flutter_forge"
        target_pubspec, target_main = target / "pubspec.yaml", target / "lib/main.dart"
        root_pubspec = root / "pubspec.yaml"
        root_manifest = root_pubspec.read_text(encoding="utf-8") if root_pubspec.is_file() else ""
        packages_preserved = all((root / path).is_dir() for path in ("packages/gcode_core", "packages/file_picker_bridge", "packages/flutter_study_learning"))
        app_changes = _worker_change_set(worker, primary)
        # Before integration, the verified target exists only in the isolated
        # Worker diff.  After integration, prove the same facts on disk.
        if not target_pubspec.is_file() or not target_main.is_file():
            required = {"apps/flutter_forge/pubspec.yaml", "apps/flutter_forge/lib/main.dart", "lib/main.dart", "pubspec.yaml"}
            if not required.issubset(set(app_changes)):
                return {"status": "REJECT", "reason": "app_target_missing", "target": "apps/flutter_forge", "required": sorted(required), "changed_files": app_changes}
            if any(path.startswith(("packages/", "plugins/")) for path in app_changes):
                return {"status": "REJECT", "reason": "workspace_capability_moved_into_app", "changed_files": app_changes}
            return {"status": "PASS", "capability_owner_before": ["flutter_forge/root_flutter_application"], "capability_owner_after": ["apps/flutter_forge"], "target_app_root": "apps/flutter_forge", "root_app_removal_pending_in_approved_diff": True, "package_survival": "PASS", "dependency_direction": "PASS"}
        if (root / "lib/main.dart").exists() or (root / "lib/app").exists():
            return {"status": "REJECT", "reason": "root_app_owner_retained", "root_duplicates": [path for path in ("lib/main.dart", "lib/app") if (root / path).exists()]}
        if re.search(r"^\s*flutter:\s*$", root_manifest, re.M):
            return {"status": "REJECT", "reason": "root_flutter_application_manifest_retained"}
        if not packages_preserved:
            return {"status": "REJECT", "reason": "workspace_package_owner_missing"}
        return {"status": "PASS", "capability_owner_before": ["flutter_forge/root_flutter_application"], "capability_owner_after": ["apps/flutter_forge"], "target_app_root": "apps/flutter_forge", "root_app_removed": True, "package_survival": "PASS", "dependency_direction": "PASS"}
    retained: list[str] = []
    for unit in target_units:
        # Target units may be repository-qualified in a frozen multi-repo
        # contract (for example ``flutter_forge/packages/...``).  Ownership
        # validation is evaluated inside the Flutter worktree, so remove that
        # qualifier before testing the retained package owner.
        if unit.startswith("flutter_forge/"):
            unit = unit.removeprefix("flutter_forge/")
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

def proposal_inventory(program: dict[str, object], spec: dict[str, object]) -> dict[str, object]:
    """Build a frozen task from tracked-file evidence without touching a worktree."""
    from agent_hub.graphs.decomposition import CLUSTER
    primary_repository = str(program.get("primary_repository_id") or "flutter_forge")
    repository = next((item for item in program.get("repositories", []) if item.get("repository_id") == primary_repository), None)
    root = Path(str(repository.get("path"))) if isinstance(repository, dict) else Path(str(program.get("cluster_root", CLUSTER))) / primary_repository
    if not root.is_dir():
        return {"task_id": spec.get("task_id"), "title": spec.get("title"), "status": "BLOCKED_DECISION", "evidence": [], "candidate_paths": [], "allowed_paths_by_repository": {}, "blocked_decisions": ["flutter_forge repository is unavailable for read-only discovery"]}
    tracked = subprocess.check_output(["git", "ls-files"], cwd=root, text=True).splitlines()
    if spec.get("task_id") == "rename-project-to-flutter-forge":
        candidates: set[str] = set()
        evidence: list[str] = []
        old_tokens = (
            "flutter_study_workspace",
            "flutter_study_app",
            "apps/flutter_study",
            "Flutter Study",
            "Flutter_Study",
        )
        for relative in tracked:
            path = root / relative
            if relative.startswith("apps/flutter_study/"):
                candidates.add(relative)
                candidates.add("apps/flutter_forge/" + relative.removeprefix("apps/flutter_study/"))
            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            matches = [token for token in old_tokens if token in content]
            if matches:
                candidates.add(relative)
                evidence.append(f"{relative}: references {', '.join(matches)}")
        for old, new in (
            (".run/Flutter_Study_macOS.run.xml", ".run/Flutter_Forge_macOS.run.xml"),
        ):
            if old in tracked:
                candidates.update((old, new))
        blocked: list[str] = []
        required_evidence = {
            "pubspec.yaml": "root workspace manifest",
            "apps/flutter_study/pubspec.yaml": "application package manifest",
            "apps/flutter_study/lib/main.dart": "application entrypoint",
        }
        for path, label in required_evidence.items():
            if path not in candidates:
                blocked.append(f"missing {label}: {path}")
        frozen = sorted(candidates)
        return {
            "task_id": str(spec.get("task_id", "")),
            "title": str(spec.get("title", "")),
            "intent": str(spec.get("intent", "")),
            "source_units": list(spec.get("source_units", ["apps/flutter_study"])),
            "target_units": list(spec.get("target_units", ["apps/flutter_forge"])),
            "depends_on": list(spec.get("depends_on", [])),
            "allowed_operations": list(spec.get("allowed_operations", ["RENAME", "MOVE", "DEPENDENCY_REWRITE", "CREATE", "DELETE"])),
            "candidate_paths": frozen,
            "allowed_paths_by_repository": {primary_repository: frozen} if not blocked else {},
            "evidence": evidence,
            "execution_instructions": list(spec.get("execution_instructions", [])),
            "invariants": list(spec.get("invariants", [])),
            "acceptance": list(spec.get("acceptance", [])),
            "blocked_decisions": blocked,
            "proposal": {
                "status": "FROZEN" if not blocked else "PENDING_EVIDENCE",
                "read_only": True,
            },
            "status": "READY" if not blocked else "BLOCKED_DECISION",
        }
    if spec.get("task_id") == "rename-main-app-package":
        candidates: list[str] = []
        evidence: list[str] = []
        for relative in tracked:
            path = root / relative
            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if relative == "apps/flutter_forge/pubspec.yaml" and re.search(r"^name:\s*main_app\s*$", content, re.M):
                candidates.append(relative)
                evidence.append(f"{relative}: declares name main_app")
            elif relative.endswith(".dart") and "package:main_app/" in content:
                candidates.append(relative)
                evidence.append(f"{relative}: imports package:main_app")
        run_config = ".run/Flutter_Forge_macOS.run.xml"
        candidates.append(run_config)
        blocked: list[str] = []
        if "apps/flutter_forge/pubspec.yaml" not in candidates:
            blocked.append("main_app pubspec declaration not found")
        if not any(path.endswith(".dart") for path in candidates):
            blocked.append("package:main_app callsites not found")
        frozen = sorted(set(candidates))
        return {
            "task_id": str(spec.get("task_id", "")), "title": str(spec.get("title", "")), "intent": str(spec.get("intent", "")),
            "source_units": list(spec.get("source_units", ["apps/flutter_forge"])), "target_units": list(spec.get("target_units", ["apps/flutter_forge"])),
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
        elif relative.startswith("apps/flutter_forge/") and (
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
    adapter = "apps/flutter_forge/lib/modules/platform/online_video_player/state/video_player_adapter.dart"
    if adapter not in candidates:
        candidates.append(adapter)
    candidates = sorted(set(candidates))
    allowed = [path for path in candidates if not path.startswith(".hermes/")]
    blocked: list[str] = []
    required_groups = {
        "dependency manifest": lambda p: p == "apps/flutter_forge/pubspec.yaml",
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
        "source_units": list(spec.get("source_units", ["flutter_forge/media_playback"])),
        "target_units": list(spec.get("target_units", ["flutter_forge/media_playback"])),
        "depends_on": list(spec.get("depends_on", [])),
        "allowed_operations": list(spec.get("allowed_operations", ["DEPENDENCY_REWRITE", "API_BREAK", "CREATE", "DELETE"])),
        "candidate_paths": candidates,
        "allowed_paths_by_repository": {"flutter_forge": allowed} if allowed and not blocked else {},
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
