"""Flutter Forge project facts used by its decomposition adapter.

This module is deliberately independent from the graph.  The graph must not
know which packages, app roots, or capability owners belong to Flutter Forge.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path


def _pubspec(path: Path) -> tuple[str, list[str]]:
    text = path.read_text(encoding="utf-8")
    name = re.search(r"^name:\s*(\S+)", text, re.M)
    dependencies = re.findall(r"^\s{2}([a-zA-Z_][\w_]*):\s*$", text, re.M)
    return (name.group(1) if name else path.parent.name, dependencies)


def _project_work_queue(repository_root: Path) -> list[dict[str, object]]:
    """Project the generator-owned Forge queue without granting execution scope."""
    plan = repository_root / "REFACTOR_PLAN.md"
    if not plan.is_file():
        return []
    payload = json.loads(plan.read_text(encoding="utf-8"))
    entries = payload.get("work_queue", [])
    if not isinstance(entries, list):
        return []
    projected = []
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("id"):
            continue
        projected.append({
            "task_id": str(entry["id"]),
            "priority": entry.get("priority"),
            "project_status": str(entry.get("status") or "unknown"),
            "depends_on": list(entry.get("depends_on") or []),
            "targets": list(entry.get("targets") or []),
            "acceptance": list(entry.get("acceptance") or []),
            "evidence": list(entry.get("evidence") or []),
            "allowed_paths_by_repository": {},
            "execution_authority": "FROZEN_PROPOSAL_REQUIRED",
        })
    return projected


def _module_platforms(contract: dict[str, object]) -> list[str]:
    """Read both the legacy platform list and the current inclusion/exclusion model."""
    support = contract.get("platform_support")
    if isinstance(support, dict):
        targets = list(support.get("target_platforms") or [])
        excluded = set(support.get("excluded_platforms") or [])
        return [platform for platform in targets if platform not in excluded]
    return list(contract.get("supported_platforms") or [])


def _repository_observation(repository_root: Path) -> dict[str, object]:
    """Record the exact checkout observed by inventory without changing it."""
    try:
        revision = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=repository_root, text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        status = subprocess.check_output(
            ["git", "status", "--short"], cwd=repository_root, text=True,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return {"revision": None, "worktree_status": "UNKNOWN", "changed_paths": []}
    changed_paths = [line[3:] for line in status.splitlines() if len(line) > 3]
    return {
        "revision": revision,
        "worktree_status": "DIRTY" if changed_paths else "CLEAN",
        "changed_paths": changed_paths,
    }


def build_program(root: Path, context: dict[str, object]) -> dict[str, object]:
    primary = str(context.get("primary_repository_id") or "flutter_forge")
    paths = context.get("repository_paths")
    repository_root = Path(str(paths.get(primary))) if isinstance(paths, dict) and paths.get(primary) else root / primary
    project_work_queue = _project_work_queue(repository_root)
    repository_observation = _repository_observation(repository_root)
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
        {
            "task_id": "responsive_navigation_policy",
            "title": "Separate mobile in-app navigation from desktop multi-window navigation",
            "source_units": ["flutter_forge/apps/flutter_forge"],
            "target_units": ["flutter_forge/apps/flutter_forge"],
            "depends_on": [],
            "allowed_operations": ["CREATE", "DEPENDENCY_REWRITE"],
            "allowed_paths_by_repository": {"flutter_forge": [
                "apps/flutter_forge/lib/app/category_navigation.dart",
                "apps/flutter_forge/lib/app/module_home_page.dart",
                "apps/flutter_forge/lib/app/navigation_policy.dart",
                "apps/flutter_forge/test/shared/navigation_policy_test.dart",
                "AGENTS.md",
                "docs/adr/0005-responsive-navigation-topology.md",
                "tool/generate_agent_indexes.js",
            ]},
            "acceptance": [
                "Android/iOS/Web use in-app navigation",
                "desktop widths below 600dp use in-app navigation",
                "desktop widths at or above 600dp may use multi-window",
                "NavigationPolicy is covered by boundary tests",
            ],
            "status": "DONE",
            "evidence": ["Flutter Forge navigation policy is an app-owned concern; desktop_multi_window remains a host capability"],
        },
        {
            "task_id": "android_mobile_navigation_baseline",
            "title": "Establish Android small-screen navigation and layout baseline",
            "source_units": ["flutter_forge/apps/flutter_forge"],
            "target_units": ["flutter_forge/apps/flutter_forge"],
            "depends_on": ["responsive_navigation_policy"],
            "allowed_operations": ["CREATE", "DEPENDENCY_REWRITE"],
            "execution_instructions": [
                "Create or update Android-targeted integration evidence for the 360dp navigation and SafeArea baseline.",
                "Keep Android navigation in-app and do not add desktop multi-window behavior.",
                "Run the targeted Flutter test and leave the evidence inside the frozen integration_test or test paths.",
            ],
            "allowed_paths_by_repository": {"flutter_forge": [
                "apps/flutter_forge/lib/app",
                "apps/flutter_forge/lib/modules",
                "apps/flutter_forge/test",
                "apps/flutter_forge/integration_test",
            ]},
            "acceptance": [
                "360dp module home has no overflow",
                "category home has safe area and usable touch targets",
                "Android uses in-app category navigation",
                "targeted widget or integration evidence exists",
                "Android-targeted test asset is present in the frozen checkout",
            ],
            "status": "DONE",
            "evidence": ["REFACTOR_PLAN mobile_layout_baseline target width is 360dp"],
        },
        {
            "task_id": "pc_window_lifecycle_baseline",
            "title": "Close the PC multi-window lifecycle baseline",
            "source_units": ["flutter_forge/apps/flutter_forge"],
            "target_units": ["flutter_forge/apps/flutter_forge"],
            "depends_on": ["responsive_navigation_policy"],
            "allowed_operations": ["CREATE", "DEPENDENCY_REWRITE"],
            "allowed_paths_by_repository": {"flutter_forge": [
                "apps/flutter_forge/lib/app",
                "apps/flutter_forge/lib/shared/multi_window",
                "apps/flutter_forge/test",
                "apps/flutter_forge/macos",
                "docs/adr",
            ]},
            "acceptance": [
                "three_category_windows",
                "close_reopen",
                "no_black_surface",
                "no_invalid_engine_handle",
            ],
            "status": "DONE",
            "evidence": ["PC multi-window is navigation infrastructure and must be closed before business-module expansion"],
        },
        {
            "task_id": "pc_build_matrix",
            "title": "Verify the PC build matrix before maintainability freeze",
            "source_units": ["flutter_forge/apps/flutter_forge"],
            "target_units": ["flutter_forge/apps/flutter_forge"],
            "depends_on": ["pc_window_lifecycle_baseline"],
            "allowed_operations": ["CREATE"],
            "allowed_paths_by_repository": {"flutter_forge": [
                "apps/flutter_forge/macos",
                "apps/flutter_forge/windows",
                "docs/reports",
            ]},
            "acceptance": ["macos_release_build", "windows_release_build", "pc_quality_gate"],
            "status": "DONE",
            "evidence": ["Windows build evidence requires a Windows host or CI; macOS refusal is not a pass"],
        },
        {
            "task_id": "android_host_readiness",
            "title": "Prepare Android host and plugin capability baseline",
            "source_units": ["flutter_forge/apps/flutter_forge"],
            "target_units": ["flutter_forge/apps/flutter_forge"],
            "depends_on": ["android_mobile_navigation_baseline"],
            "allowed_operations": ["CREATE", "DEPENDENCY_REWRITE"],
            "allowed_paths_by_repository": {"flutter_forge": [
                "apps/flutter_forge/android",
                "apps/flutter_forge/pubspec.yaml",
                "AI_PROJECT_CONTEXT.md",
                "REFACTOR_PLAN.md",
            ]},
            "acceptance": [
                "Android host directory exists",
                "plugin support matrix is recorded",
                "usb_android_method_channel replaces the incompatible usb_serial plugin",
                "debug APK builds",
                "emulator smoke test passes",
            ],
            "status": "DONE",
            "evidence": ["REFACTOR_PLAN android_host depends on platform audit and mobile layout baseline"],
        },
        {"task_id": "establish-package-boundary-contracts", "title": "Add per-package ownership contracts, independent test entries, and version pins", "source_units": [], "target_units": ["packages/gcode_core", "packages/file_picker_bridge", "packages/flutter_study_learning", "packages/flutter_ioc_core"], "depends_on": ["relocate-flutter-forge-app"], "allowed_operations": [], "allowed_paths_by_repository": {"flutter_forge": ["packages/gcode_core", "packages/file_picker_bridge", "packages/flutter_study_learning", "packages/flutter_ioc_core"]}, "target_creation_allowed": False, "status": "DONE", "evidence": ["workspace declares four package members consumed only by apps/flutter_forge"]},
        {"task_id": "android_usb_permission_boundary", "title": "Harden Android USB permission and enumeration fallback", "source_units": ["flutter_forge/apps/flutter_forge"], "target_units": ["flutter_forge/apps/flutter_forge"], "depends_on": ["android_host"], "allowed_operations": ["CREATE", "DEPENDENCY_REWRITE"], "allowed_paths_by_repository": {"flutter_forge": ["apps/flutter_forge/android/app/src/main/kotlin", "apps/flutter_forge/android/app/src/main/AndroidManifest.xml", "apps/flutter_forge/lib/modules/platform/usb_detector", "apps/flutter_forge/test/modules/platform/usb_detector"]}, "acceptance": ["usb_permission_denied_is_observable", "device_enumeration_falls_back_without_crash", "android_usb_channel_contract_tested"], "status": "DONE", "evidence": ["托管仓库 REFACTOR_PLAN marks android_usb_permission_boundary completed", "Android MainActivity reports permission-safe USB enumeration and APK validation passed"]},
        {"task_id": "module_scaffold_generation", "title": "Validate the reusable module scaffold generator", "source_units": ["flutter_forge/tool/module_scaffold.dart"], "target_units": ["flutter_forge/tool/module_scaffold.dart"], "depends_on": ["android_usb_permission_boundary"], "allowed_operations": ["CREATE", "DEPENDENCY_REWRITE"], "allowed_paths_by_repository": {"flutter_forge": ["tool/module_scaffold.dart", "tool/module_scaffold_test.dart", "REFACTOR_PLAN.md", "tool/generate_agent_indexes.js"]}, "execution_instructions": ["Run the scaffold CLI acceptance test.", "Keep preview mode non-mutating and do not register a module automatically.", "Validate generated module contracts through the owning project validators."], "acceptance": ["preview_does_not_write_formal_module", "apply_generates_module_entry_and_learning_page", "generated_analysis_contract_is_valid", "invalid_module_arguments_fail_with_usage_code", "route_registration_remains_explicit"], "status": "DONE", "evidence": ["tool/module_scaffold.dart and tool/module_scaffold_test.dart passed local CLI acceptance", "Agent Hub Worker revalidated the committed scaffold baseline"]},
    ]
    # Refresh platform-module admission from generator-owned module contracts.
    # This keeps the control-plane index aligned while preserving historical
    # implementation tasks as evidence rather than current route authority.
    video_path = "apps/flutter_forge/lib/modules/platform/online_video_player"
    video_contract = repository_root / video_path / "AI_ANALYSIS.md"
    if video_contract.is_file():
        contract = json.loads(video_contract.read_text(encoding="utf-8"))
        video_capability = next(
            capability for capability in capabilities
            if capability["capability_id"] == "windows-resilient-online-video-playback"
        )
        video_platforms = _module_platforms(contract)
        video_capability.update(
            dependencies=list(contract.get("depends", [])),
            supported_platforms=[platform for platform in video_platforms if platform != "web"],
            supports_web="web" in video_platforms or bool(contract.get("supports_web", False)),
            route=contract.get("route"),
            evidence=[f"{video_path}/AI_ANALYSIS.md"],
        )
        if "android" in video_capability["supported_platforms"]:
            tasks.append({
                "task_id": "android_online_video_playback",
                "title": "Track Android online-video admission",
                "source_units": [f"{primary}/{video_path}"],
                "target_units": [f"{primary}/{video_path}"],
                "depends_on": ["android_host_readiness"],
                "allowed_operations": [], "allowed_paths_by_repository": {},
                "status": "PARTIAL",
                "evidence": ["Android route and compact widget contracts are present; device playback evidence remains pending"],
            })
    usb_path = "apps/flutter_forge/lib/modules/platform/usb_detector"
    usb_contract = repository_root / usb_path / "AI_ANALYSIS.md"
    if usb_contract.is_file():
        contract = json.loads(usb_contract.read_text(encoding="utf-8"))
        usb_platforms = _module_platforms(contract)
        capabilities.append({
            "capability_id": "usb-device-observation",
            "current_owners": [f"{primary}/{usb_path}"],
            "source_paths": [f"{primary}/{usb_path}"],
            "consumers": [f"{primary}:usb_detector"],
            "dependencies": list(contract.get("depends", [])),
            "supported_platforms": usb_platforms,
            "route": contract.get("route"),
            "availability": "DISABLED_PENDING_WORKFLOW" if not usb_platforms else "AVAILABLE",
            "flutter_dependency": True, "platform_dependency": True,
            "native_dependency": True, "state_dependency": True,
            "reuse_scope": "app", "classification": "KEEP_APP_ONLY",
            "target_package": "apps/flutter_forge",
            "evidence": [f"{usb_path}/AI_ANALYSIS.md", "REFACTOR_PLAN.md"],
        })
        app_candidate = next(c for c in candidates if c["package_id"] == "apps/flutter_forge")
        app_candidate["owned_capabilities"].append("usb-device-observation")
        if not usb_platforms:
            usb_task = next(task for task in tasks if task["task_id"] == "android_usb_permission_boundary")
            usb_task.update(
                status="SUPERSEDED",
                allowed_operations=[],
                allowed_paths_by_repository={},
                evidence=["Current module contract admits no host routes; a concrete OTG workflow is required before re-admission"],
            )
    file_picker_path = "apps/flutter_forge/lib/modules/platform/file_picker"
    file_picker_contract = repository_root / file_picker_path / "AI_ANALYSIS.md"
    if file_picker_contract.is_file():
        contract = json.loads(file_picker_contract.read_text(encoding="utf-8"))
        support = dict(contract.get("platform_support") or {})
        capabilities.append({
            "capability_id": "cross-platform-file-picker-learning-flow",
            "current_owners": [f"{primary}/{file_picker_path}"],
            "source_paths": [f"{primary}/{file_picker_path}"],
            "consumers": [f"{primary}:file_picker"],
            "dependencies": list(contract.get("depends", [])),
            "target_platforms": list(support.get("target_platforms", [])),
            "excluded_platforms": list(support.get("excluded_platforms", [])),
            "route": contract.get("route"),
            "flutter_dependency": True, "platform_dependency": True,
            "native_dependency": True, "state_dependency": True,
            "reuse_scope": "app", "classification": "KEEP_APP_ONLY",
            "target_package": "apps/flutter_forge",
            "evidence": [f"{file_picker_path}/AI_ANALYSIS.md"],
        })
        app_candidate = next(c for c in candidates if c["package_id"] == "apps/flutter_forge")
        app_candidate["owned_capabilities"].append("cross-platform-file-picker-learning-flow")
    registry_path = "apps/flutter_forge/lib/module_registry"
    registry_contract = repository_root / registry_path / "AI_ANALYSIS.md"
    if registry_contract.is_file():
        contract = json.loads(registry_contract.read_text(encoding="utf-8"))
        capabilities.append({
            "capability_id": "immutable-platform-snapshot-and-route-guard",
            "current_owners": [f"{primary}/{registry_path}", f"{primary}/apps/flutter_forge/lib/app/router"],
            "source_paths": [f"{primary}/{registry_path}", f"{primary}/apps/flutter_forge/lib/app/router"],
            "consumers": [f"{primary}:module_routes"],
            "dependencies": list(contract.get("depends", [])),
            "flutter_dependency": True, "platform_dependency": True,
            "native_dependency": False, "state_dependency": True,
            "reuse_scope": "app", "classification": "KEEP_APP_ONLY",
            "target_package": "apps/flutter_forge",
            "evidence": [f"{registry_path}/AI_ANALYSIS.md", "REFACTOR_PLAN.md"],
        })
        app_candidate = next(c for c in candidates if c["package_id"] == "apps/flutter_forge")
        app_candidate["owned_capabilities"].append("immutable-platform-snapshot-and-route-guard")
    app_contract_path = "apps/flutter_forge/lib/app/AI_ANALYSIS.md"
    app_contract = repository_root / app_contract_path
    if app_contract.is_file():
        contract = json.loads(app_contract.read_text(encoding="utf-8"))
        capabilities.append({
            "capability_id": "adaptive-creator-navigation-shell",
            "current_owners": [f"{primary}/apps/flutter_forge/lib/app"],
            "source_paths": [f"{primary}/apps/flutter_forge/lib/app"],
            "consumers": [f"{primary}:application_shell"],
            "dependencies": list(contract.get("depends", [])),
            "entrypoints": list(contract.get("entrypoints", [])),
            "owned_contracts": list(contract.get("owns", [])),
            "flutter_dependency": True, "platform_dependency": True,
            "native_dependency": False, "state_dependency": True,
            "reuse_scope": "app", "classification": "KEEP_APP_ONLY",
            "target_package": "apps/flutter_forge",
            "evidence": [app_contract_path, "docs/adr/0012-adaptive-navigation-shell.md"],
        })
        app_candidate = next(c for c in candidates if c["package_id"] == "apps/flutter_forge")
        app_candidate["owned_capabilities"].append("adaptive-creator-navigation-shell")
    # Web is an application host, distinct from the native embedded WebView
    # capability discovered below. Index it only when the checkout contains the
    # host and its checked release-build contract.
    web_host = repository_root / "apps/flutter_forge/web"
    web_build = repository_root / "tool/build_web_release.sh"
    if web_host.is_dir() and web_build.is_file():
        capabilities.append({
            "capability_id": "flutter-web-application-host",
            "current_owners": [f"{primary}/apps/flutter_forge"],
            "source_paths": [f"{primary}/apps/flutter_forge/web", f"{primary}/tool/build_web_release.sh"],
            "consumers": [f"{primary}:web-capable-modules"],
            "dependencies": ["flutter_web"],
            "supported_platforms": ["web"],
            "flutter_dependency": True, "platform_dependency": True,
            "native_dependency": False, "state_dependency": False,
            "reuse_scope": "app", "classification": "KEEP_APP_ONLY",
            "target_package": "apps/flutter_forge",
            "evidence": ["apps/flutter_forge/web/index.html", "tool/build_web_release.sh"],
        })
        app_candidate = next(c for c in candidates if c["package_id"] == "apps/flutter_forge")
        app_candidate["owned_capabilities"].append("flutter-web-application-host")
        tasks.append({
            "task_id": "web_host_readiness",
            "title": "Register the Flutter Web host and compatibility boundary",
            "source_units": [f"{primary}/apps/flutter_forge"],
            "target_units": [f"{primary}/apps/flutter_forge/web"],
            "depends_on": ["responsive_navigation_policy"],
            "allowed_operations": [], "allowed_paths_by_repository": {},
            "acceptance": [
                "web host directory exists",
                "checked Web release build is defined",
                "Web uses in-app navigation",
                "unsupported modules remain filtered by platform metadata",
            ],
            "status": "DONE",
            "evidence": [
                "apps/flutter_forge/web/index.html",
                "tool/build_web_release.sh",
                "docs/reports/WEB_COMPATIBILITY_REPORT-20260908.md",
            ],
        })
    delivery_stage = dict(context.get("delivery_stage") or {})
    supported_platforms = list(delivery_stage.get("supported_platforms") or [])
    if delivery_stage.get("status") == "COMPLETE" and supported_platforms:
        tasks.extend([
            {
                "task_id": "cross_platform_foundation_v1",
                "title": "Freeze the stage-one cross-platform foundation",
                "source_units": [f"{primary}/apps/flutter_forge"],
                "target_units": [f"{primary}/apps/flutter_forge"],
                "depends_on": ["pc_build_matrix", "android_host_readiness", "web_host_readiness"],
                "allowed_operations": [],
                "allowed_paths_by_repository": {},
                "acceptance": [f"{platform}_support_baseline" for platform in supported_platforms],
                "status": "DONE",
                "evidence": [
                    "workspace/projects.json delivery_stage is COMPLETE",
                    "platform-specific build, navigation and unavailable-state contracts remain authoritative",
                ],
            },
            {
                "task_id": "feature_expansion_intake",
                "title": "Accept the next scoped feature proposal",
                "source_units": [f"{primary}/apps/flutter_forge"],
                "target_units": [f"{primary}/apps/flutter_forge"],
                "depends_on": ["cross_platform_foundation_v1"],
                "allowed_operations": [],
                "allowed_paths_by_repository": {},
                "acceptance": [
                    "feature capability and owner are named",
                    "supported and unavailable platform behavior is explicit",
                    "candidate paths and regression tests are frozen before execution",
                    "release and device evidence boundaries are preserved",
                ],
                "status": "PLANNED",
                "evidence": ["Next-stage intake is proposal-only and grants no repository write scope"],
            },
        ])
    # Discover the integrated WebView contract only when present in this checkout.
    webview_path = "apps/flutter_forge/lib/modules/platform/webview"
    webview_contract = repository_root / webview_path / "AI_ANALYSIS.md"
    if webview_contract.is_file():
        contract = json.loads(webview_contract.read_text(encoding="utf-8"))
        capabilities.append({
            "capability_id": "embedded-webview-navigation",
            "current_owners": [f"{primary}/{webview_path}"],
            "source_paths": [f"{primary}/{webview_path}"],
            "consumers": [f"{primary}:webview"],
            "dependencies": list(contract.get("depends", [])),
            "supported_platforms": list(contract.get("supported_platforms", [])),
            "route": contract.get("route"),
            "flutter_dependency": True, "platform_dependency": True,
            "native_dependency": True, "state_dependency": True,
            "reuse_scope": "app", "classification": "KEEP_APP_ONLY",
            "target_package": "apps/flutter_forge",
            "evidence": [f"{webview_path}/AI_ANALYSIS.md", f"{webview_path}/SOURCE.md"],
        })
        app_candidate = next(c for c in candidates if c["package_id"] == "apps/flutter_forge")
        app_candidate["owned_capabilities"].append("embedded-webview-navigation")
        app_candidate["dependencies"] = sorted(set(app_candidate["dependencies"] + ["webview_flutter", "webview_windows"]))
        commits = subprocess.check_output([
            "git", "log", "-1", "--format=%H", "--fixed-strings",
            "--grep=[integrate-historical-webview-module]",
        ], cwd=repository_root, text=True).strip()
        if commits:
            tasks.append({
                "task_id": "integrate-historical-webview-module",
                "title": "Integrate Android, macOS and Windows WebView module",
                "source_units": [], "target_units": [f"{primary}/{webview_path}"],
                "depends_on": [], "allowed_operations": [],
                "allowed_paths_by_repository": {}, "status": "DONE",
                "integration_commits": {primary: commits},
                "evidence": [f"git:{commits}", f"{webview_path}/AI_ANALYSIS.md"],
                "native_runtime_acceptance": "NOT_VERIFIED_BY_INVENTORY",
            })
    # Flutter Scene is an app-owned teaching capability.  Its generated module
    # contract is the source of truth for platform admission; the proposal
    # contract below only freezes write scope and must not become the index.
    scene_path = "apps/flutter_forge/lib/modules/ui/flutter_scene_3d"
    scene_contract = repository_root / scene_path / "AI_ANALYSIS.md"
    if scene_contract.is_file():
        contract = json.loads(scene_contract.read_text(encoding="utf-8"))
        scene_dependencies = list(contract.get("depends", []))
        scene_platforms = _module_platforms(contract)
        capabilities.append({
            "capability_id": "interactive-flutter-scene-3d-viewer",
            "current_owners": [f"{primary}/{scene_path}"],
            "source_paths": [f"{primary}/{scene_path}"],
            "consumers": [f"{primary}:flutter_scene_3d"],
            "dependencies": scene_dependencies,
            "supported_platforms": scene_platforms,
            "route": contract.get("route"),
            "interaction_modes": {
                "macOS": "interactive",
                "windows": "interactive",
                "android": "view_only",
            },
            "flutter_dependency": True,
            "platform_dependency": True,
            "native_dependency": True,
            "state_dependency": True,
            "reuse_scope": "app",
            "classification": "KEEP_APP_ONLY",
            "target_package": "apps/flutter_forge",
            "evidence": [
                f"{scene_path}/AI_ANALYSIS.md",
                "docs/adr/0008-flutter-scene-platform-evidence-boundary.md",
                "REFACTOR_PLAN.md",
            ],
        })
        app_candidate = next(c for c in candidates if c["package_id"] == "apps/flutter_forge")
        app_candidate["owned_capabilities"].append("interactive-flutter-scene-3d-viewer")
        app_candidate["dependencies"] = sorted(set(
            app_candidate["dependencies"]
            + [dependency for dependency in scene_dependencies if dependency in {"flutter_scene", "vector_math"}]
        ))
        tasks.extend([
            {
                "task_id": "flutter_scene_3d_macos_baseline",
                "title": "Index the accepted macOS Flutter Scene baseline",
                "source_units": [f"{primary}/{scene_path}"],
                "target_units": [f"{primary}/{scene_path}"],
                "depends_on": ["feature_expansion_intake"],
                "allowed_operations": [], "allowed_paths_by_repository": {},
                "status": "DONE",
                "evidence": ["REFACTOR_PLAN marks the macOS baseline completed"],
            },
            {
                "task_id": "flutter_scene_3d_interaction_acceptance",
                "title": "Track camera, picking and rendered interaction acceptance",
                "source_units": [f"{primary}/{scene_path}"],
                "target_units": [f"{primary}/{scene_path}"],
                "depends_on": ["flutter_scene_3d_macos_baseline"],
                "allowed_operations": [], "allowed_paths_by_repository": {},
                "status": "PARTIAL",
                "evidence": ["Automated camera and selection coverage exists; macOS visual pointer acceptance remains pending"],
            },
            {
                "task_id": "flutter_scene_3d_windows_admission",
                "title": "Track Windows Flutter Scene admission",
                "source_units": [f"{primary}/{scene_path}"],
                "target_units": [f"{primary}/{scene_path}"],
                "depends_on": ["flutter_scene_3d_interaction_acceptance"],
                "allowed_operations": [], "allowed_paths_by_repository": {},
                "status": "PARTIAL",
                "evidence": ["Catalog and automated desktop flow are present; Windows host, GPU, DPI and installer evidence remain pending"],
            },
            {
                "task_id": "flutter_scene_3d_android_view_only_admission",
                "title": "Track Android view-only Flutter Scene admission",
                "source_units": [f"{primary}/{scene_path}"],
                "target_units": [f"{primary}/{scene_path}"],
                "depends_on": ["flutter_scene_3d_macos_baseline"],
                "allowed_operations": [], "allowed_paths_by_repository": {},
                "status": "PARTIAL",
                "evidence": ["View-only policy and widget contracts are present; Android host build and GPU first-frame evidence remain pending"],
            },
        ])
    # gcode_core is independently maintained; Forge only consumes its Git API.
    upstream = (paths or {}).get("gcode_core") if isinstance(paths, dict) else None
    if upstream:
        repositories.append({"repository_id": "gcode_core", "path": str(upstream), "role": "REFERENCE", "consumers": ["flutter_forge"]})
        for capability in capabilities:
            if capability["capability_id"] == "gcode-parser-toolpath":
                capability.update(current_owners=["gcode_core"], source_paths=["gcode_core/lib"], target_package="gcode_core", classification="KEEP_PACKAGE")
        candidates = [c for c in candidates if c["package_id"] != "packages/gcode_core"]
        for candidate in candidates:
            candidate["dependencies"] = ["gcode_core" if dep == "packages/gcode_core" else dep for dep in candidate.get("dependencies", [])]
        for task in tasks:
            if task["task_id"] == "merge-gcode-core-owners":
                task.update(title="Historical consolidation superseded by independent gcode_core ownership", source_units=["gcode_core"], target_units=["gcode_core"], allowed_paths_by_repository={}, evidence=["gcode_core is a configured independent repository consumed through pinned Git URL"])
            if task["task_id"] == "establish-package-boundary-contracts":
                task["target_units"] = [p for p in task.get("target_units", []) if p != "packages/gcode_core"]
                task["allowed_paths_by_repository"][primary] = [p for p in task["allowed_paths_by_repository"].get(primary, []) if p != "packages/gcode_core"]
    return {
        "project_id": str(context.get("project_id") or "flutter-forge"),
        "program_id": str(context.get("program_id") or "flutter-forge-decomposition-program"),
        "adapter": "flutter_forge",
        "primary_repository_id": primary,
        "cluster_root": str(root),
        "repositories": repositories,
        "capabilities": capabilities,
        "package_candidates": candidates,
        "target_dependency_graph": {"nodes": [item["package_id"] for item in candidates] + (["gcode_core"] if upstream else []), "edges": [["apps/flutter_forge", item] for item in (["gcode_core"] if upstream else ["packages/gcode_core"]) + ["packages/file_picker_bridge", "packages/flutter_study_learning", "packages/flutter_ioc_core"]], "cycles": []},
        "migration_tasks": tasks,
        "project_work_queue": project_work_queue,
        "orchestration_sync": {
            "source": "REFACTOR_PLAN.md",
            "source_revision": repository_observation["revision"],
            "source_worktree_status": repository_observation["worktree_status"],
            "source_changed_paths": repository_observation["changed_paths"],
            "task_count": len(project_work_queue),
            "completed": [task["task_id"] for task in project_work_queue if task["project_status"] == "completed"],
            "open": [task["task_id"] for task in project_work_queue if task["project_status"] != "completed"],
            "execution_authority": "FROZEN_PROPOSAL_REQUIRED",
        },
        "delivery_stage": delivery_stage,
        "next_phase": {
            "phase_id": str(delivery_stage.get("next_stage") or "feature-expansion"),
            "status": str(delivery_stage.get("next_stage_status") or "READY_FOR_PROPOSALS"),
            "intake_task_id": "feature_expansion_intake",
            "execution_requires_frozen_proposal": True,
        },
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
        "responsive_navigation_policy": {"flutter_forge": ["apps/flutter_forge/lib/app", "apps/flutter_forge/test/shared", "AGENTS.md", "docs/adr", "tool/generate_agent_indexes.js"]},
        "android_mobile_navigation_baseline": {"flutter_forge": ["apps/flutter_forge/lib/app", "apps/flutter_forge/lib/modules", "apps/flutter_forge/test", "apps/flutter_forge/integration_test"]},
        "pc_window_lifecycle_baseline": {"flutter_forge": ["apps/flutter_forge/lib/app", "apps/flutter_forge/lib/shared/multi_window", "apps/flutter_forge/test", "apps/flutter_forge/macos", "docs/adr"]},
        "pc_build_matrix": {"flutter_forge": ["apps/flutter_forge/macos", "apps/flutter_forge/windows", "docs/reports"]},
        "android_host_readiness": {"flutter_forge": ["apps/flutter_forge/android", "apps/flutter_forge/pubspec.yaml", "AI_PROJECT_CONTEXT.md", "REFACTOR_PLAN.md"]},
        "web_host_readiness": {"flutter_forge": ["apps/flutter_forge/web", "apps/flutter_forge/lib/app", "apps/flutter_forge/lib/module_registry", "tool/build_web_release.sh", "docs/reports"]},
    }.get(task_id, {}).get(repository, [])

def architecture_guard(task: dict[str, object], worker: dict[str, object], program: dict[str, object]) -> dict[str, object]:
    if task.get("task_id") == "consume-independent-gcode-core":
        diff = str(worker.get("repositories", {}).get("flutter_forge", {}).get("diff", ""))
        valid = "+      url: https://github.com/lizy-coding/gcode_core.git" in diff and "+      ref: 7a5228126d6e43b0cb9175b035cd2e1701950779" in diff
        return {"status": "PASS" if valid else "REJECT", "guard_kind": "independent_gcode_git_owner", "capability_owner_after": ["gcode_core"]}
    """Prove that a merge preserves a concrete target capability owner."""
    from agent_hub.graphs.decomposition import _ensure_worktree, _primary_repository, _worker_change_set
    repositories = worker.get("repositories", {})
    if not isinstance(repositories, dict):
        return {"status": "REJECT", "reason": "missing_repository_results"}
    target_units = [str(unit) for unit in task.get("target_units", [])]
    if not target_units:
        return {"status": "REJECT", "reason": "merge_task_has_no_target_units"}
    deleted = [
        line.removeprefix("deleted file mode ").strip()
        for result in repositories.values()
        if isinstance(result, dict)
        for line in str(result.get("diff", "")).splitlines()
        if line.startswith("deleted file mode ")
    ]
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
    if spec.get("task_id") == "add-flutter-scene-3d-learning-module":
        from agent_hub.projects.adapters import GenericProjectAdapter

        paths = [
            "CONTEXT.md",
            "docs/adr/0008-flutter-scene-platform-evidence-boundary.md",
            "pubspec.lock",
            "tool/generate_agent_indexes.js",
            "AI_PROJECT_CONTEXT.md",
            "REFACTOR_PLAN.md",
            "apps/flutter_forge/pubspec.yaml",
            "apps/flutter_forge/hook/build.dart",
            "apps/flutter_forge/flutter_scene_generated/.gitignore",
            "apps/flutter_forge/macos/Runner/Info.plist",
            "apps/flutter_forge/windows/runner/main.cpp",
            "apps/flutter_forge/lib/app/router/app_route_table.dart",
            "apps/flutter_forge/lib/AI_MODULE_INDEX.md",
            "apps/flutter_forge/lib/modules/AI_ANALYSIS.md",
            "apps/flutter_forge/lib/modules/ui/AI_ANALYSIS.md",
            "apps/flutter_forge/lib/modules/ui/flutter_scene_3d",
            "apps/flutter_forge/test/modules/ui/flutter_scene_3d",
        ]
        task = GenericProjectAdapter().proposal_inventory(
            program,
            {**spec, "candidate_paths": paths},
        )
        task["evidence"] = [
            "Flutter Forge generator owns module registration and agent documents",
            "Flutter 3.47.2 satisfies flutter_scene 0.23.0 minimum SDK",
            "macOS admission and unverified-platform fallback are frozen explicitly",
        ]
        task["target_creation_allowed"] = True
        return task
    if spec.get("task_id") == "normalize-webview-naming":
        from agent_hub.projects.adapters import GenericProjectAdapter
        primary = str(program.get("primary_repository_id") or "flutter_forge")
        root = Path(next(r["path"] for r in program["repositories"] if r["repository_id"] == primary))
        paths = [str(p.relative_to(root)) for folder in ("apps/flutter_forge/lib/modules/platform/webview", "apps/flutter_forge/test/modules/platform/webview") for p in (root / folder).rglob("*") if p.is_file()]
        paths += ["apps/flutter_forge/lib/modules/platform/webview/platforms/webview_flutter_backend.dart", "apps/flutter_forge/lib/modules/platform/webview/platforms/webview2_backend.dart", "apps/flutter_forge/integration_test/webview_macos_test.dart", "apps/flutter_forge/lib/app/router/app_route_table.dart", "tool/generate_agent_indexes.js", "CONTEXT.md", "docs/reports/WEBVIEW_INTEGRATION.md"]
        task = GenericProjectAdapter().proposal_inventory(program, {**spec, "candidate_paths": sorted(set(paths))})
        task["evidence"] = ["Existing module and tests discovered in current Forge checkout", "User approved naming-only change; route, dependencies and runtime behavior preserved"]
        return task
    if spec.get("task_id") == "integrate-historical-webview-module":
        from agent_hub.projects.adapters import GenericProjectAdapter
        primary = str(program.get("primary_repository_id") or "flutter_forge")
        root = Path(next(r["path"] for r in program["repositories"] if r["repository_id"] == primary))
        tracked = subprocess.check_output(["git", "ls-files"], cwd=root, text=True).splitlines()
        paths = [p for p in tracked if p.endswith("AI_ANALYSIS.md") or p.endswith("AI_MODULE_INDEX.md")]
        paths += ["AI_ANALYSIS_SCHEMA.json", "AI_PROJECT_CONTEXT.md", "REFACTOR_PLAN.md", "pubspec.lock", "apps/flutter_forge/pubspec.yaml", "tool/generate_agent_indexes.js", "apps/flutter_forge/lib/app/router/app_route_table.dart", "docs/reports/WEBVIEW_INTEGRATION.md"]
        module = "apps/flutter_forge/lib/modules/platform/webview/"
        paths += [module + p for p in ["module_entry.dart", "module_root.dart", "AI_ANALYSIS.md", "SOURCE.md", "core/webview_session.dart", "core/webview_backend.dart", "platforms/webview_flutter_backend.dart", "platforms/webview2_backend.dart", "widgets/webview_navigation_bar.dart", "widgets/loading_placeholder.dart"]]
        paths += ["apps/flutter_forge/test/modules/platform/webview/" + p for p in ["webview_test.dart", "webview_session_test.dart"]]
        paths += [p for p in tracked if p.startswith("apps/flutter_forge/") and ("GeneratedPluginRegistrant" in p or "generated_plugin" in p or p.endswith("Podfile.lock"))]
        task = GenericProjectAdapter().proposal_inventory(program, {**spec, "candidate_paths": sorted(set(paths))})
        task["evidence"] = ["Forge manifest and generator define the application owner", "historical webview_plugin source revision: 1e160be430a55612bd1c1711f56be7ed94a4957b", "anticipated module and behavior test paths frozen by Flutter Forge adapter"]
        task["target_creation_allowed"] = True
        return task
    if spec.get("task_id") == "consume-independent-gcode-core":
        from agent_hub.projects.adapters import GenericProjectAdapter
        root = Path(next(r["path"] for r in program["repositories"] if r["repository_id"] == "flutter_forge"))
        tracked = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", "HEAD"], cwd=root, text=True).splitlines()
        paths = [p for p in tracked if p.endswith("AI_ANALYSIS.md") or p.endswith("AI_MODULE_INDEX.md") or p.startswith("packages/gcode_core/")]
        paths += ["apps/flutter_forge/pubspec.yaml", "pubspec.yaml", "pubspec.lock", "AI_ANALYSIS_SCHEMA.json", "AI_PROJECT_CONTEXT.md", "REFACTOR_PLAN.md", "tool/generate_agent_indexes.js", "tool/validate_agent_docs.js", "tool/test_all.sh"]
        task = GenericProjectAdapter().proposal_inventory(program, {**spec, "candidate_paths": sorted(set(paths))})
        task.update(packaging_change=True, manual_review=True)
        return task
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


# --- GitHub installer release hosting (scene#22 CI/CD) ---------------------
#
# Flutter Forge installer packages are staged by CI or a local build under
# ``<repo>/release/<version>/`` and named ``FlutterForge-<version>-<platform>.<ext>``.
# The adapter freezes that staging directory into a ReleaseProgram; the graph
# verifies checksums and publishes through the release lane.  This module
# never runs builds and never talks to GitHub.

_RELEASE_ASSET_EXTENSIONS = ("apk", "aab", "dmg", "exe", "msix", "zip", "ipa", "tar.gz")


def _app_version(repository_root: Path) -> str:
    for pubspec in (repository_root / "apps/flutter_forge/pubspec.yaml", repository_root / "pubspec.yaml"):
        if pubspec.is_file():
            match = re.search(r"^version:\s*(\d+\.\d+\.\d+)", pubspec.read_text(encoding="utf-8"), re.M)
            if match:
                return match.group(1)
    return ""


def _sha256sums(directory: Path) -> dict[str, str]:
    manifest = directory / "SHA256SUMS"
    checksums: dict[str, str] = {}
    if not manifest.is_file():
        return checksums
    for line in manifest.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([0-9a-fA-F]{64})\s+\*?(\S+)$", line.strip())
        if match:
            checksums[match.group(2)] = match.group(1).lower()
    return checksums


def _release_asset_convention(version: str) -> re.Pattern[str]:
    extensions = "|".join(extension.replace(".", r"\.") for extension in _RELEASE_ASSET_EXTENSIONS)
    return re.compile(rf"^FlutterForge-{re.escape(version)}-.+\.(?:{extensions})$")


def release_inventory(context: dict[str, object], spec: dict[str, object]) -> dict[str, object]:
    """Freeze a Flutter Forge installer release from its staging directory."""
    from agent_hub.projects.release_program import (
        artifact_entries,
        blocked_release_program,
        build_release_program,
        is_publishable_artifact,
        is_flutter_forge_android_arm64,
        normalize_artifact_paths,
        release_context,
        valid_release_tag,
    )
    context = {**(context or {}), "adapter": "flutter_forge"}
    context.setdefault("program_id", f"{context.get('project_id') or 'flutter-forge'}-release-program")
    config = release_context(context)
    if not str(config.get("github_repo") or "").strip():
        return blocked_release_program(context, "RELEASE_NOT_CONFIGURED", "release.github_repo is not configured in workspace/projects.json; freeze the Flutter Forge repository slug before planning a release.")
    primary = str(context.get("primary_repository_id") or "flutter_forge")
    paths = context.get("repository_paths")
    repository_root = Path(str(paths.get(primary))) if isinstance(paths, dict) and paths.get(primary) else Path(str(context.get("cluster_root") or ".")) / primary
    spec = spec if isinstance(spec, dict) else {}
    version = str(spec.get("version") or "") or _app_version(repository_root)
    if not version:
        return blocked_release_program(context, "RELEASE_VERSION_REQUIRED", "No version in the spec and no apps/flutter_forge pubspec version; supply an explicit semver version.")
    tag = str(spec.get("tag") or f"{config.get('tag_prefix') or 'v'}{version}")
    if not valid_release_tag(tag):
        return blocked_release_program(context, "RELEASE_TAG_INVALID", f"release tag is not semver-shaped: {tag}")
    evidence: list[str] = []
    explicit = spec.get("artifacts")
    if isinstance(explicit, list) and explicit:
        artifact_paths, error = normalize_artifact_paths(explicit)
        if error:
            return blocked_release_program(context, "RELEASE_ARTIFACTS_INVALID", error)
        checksums = {Path(str(item.get("path"))).name: str(item.get("sha256")).lower() for item in explicit if isinstance(item, dict) and item.get("sha256") and re.fullmatch(r"[0-9a-fA-F]{64}", str(item["sha256"]))}
        evidence.append("artifacts supplied explicitly by the release spec")
    else:
        staging = repository_root / str(config.get("artifact_root") or "release").strip("/") / version
        if not staging.is_dir():
            return blocked_release_program(context, "RELEASE_ARTIFACTS_MISSING", f"installer staging directory not found: {staging}; build the installers and stage them under {staging.relative_to(repository_root)} first.")
        convention = _release_asset_convention(version)
        discovered = sorted(path for path in staging.iterdir() if is_publishable_artifact(path))
        android_candidates = [path for path in discovered if path.suffix.lower() in {".apk", ".aab"}]
        rejected_android = [path.name for path in android_candidates if not is_flutter_forge_android_arm64(path)]
        if rejected_android:
            evidence.append("ignored non-arm64 Android files: " + ", ".join(rejected_android))
        discovered = [path for path in discovered if path not in android_candidates or is_flutter_forge_android_arm64(path)]
        ignored = [path.name for path in discovered if not convention.match(path.name)]
        kept = [path for path in discovered if convention.match(path.name)]
        if ignored:
            evidence.append("ignored non-convention files: " + ", ".join(ignored))
        if not kept:
            return blocked_release_program(context, "RELEASE_ARTIFACTS_MISSING", f"no supported FlutterForge-{version} installer packages found in {staging.relative_to(repository_root)}; Android accepts only arm64-v8a APKs plus AAB.")
        root_prefix = str(config.get("artifact_root") or "release").strip("/")
        artifact_paths = [f"{root_prefix}/{version}/{path.name}" for path in kept]
        checksums = _sha256sums(staging)
        evidence.append(f"artifacts discovered in {root_prefix}/{version}/" + (" with SHA256SUMS cross-check" if checksums else ""))
    artifacts = artifact_entries(artifact_paths, checksums)
    name = str(spec.get("name") or f"FlutterForge {tag}")
    notes = str(spec.get("notes") or "FlutterForge " + tag + " installer packages.\n\n" + "\n".join(f"- {entry['asset_name']}" for entry in artifacts))
    return build_release_program(
        context,
        version=version,
        tag=tag,
        name=name,
        notes=notes,
        draft=bool(spec.get("draft", config.get("default_draft", False))),
        prerelease=bool(spec.get("prerelease", config.get("default_prerelease", False))),
        artifacts=artifacts,
        evidence=evidence,
    )
