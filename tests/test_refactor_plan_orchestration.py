import json
import os
import tempfile
import types
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from agent_hub.execution.code_worker import WorkerRequest, _build_target
from agent_hub.graphs.context_analysis import planned_capabilities
from agent_hub.graphs.development import _load_refactor_plan, _new_program, _normalise_plan_target, _plan_task, reconcile_program
from agent_hub.workspace.config import WorkspaceConfig

PLAN_PAYLOAD = {
    "schema": "flutter_forge.agent_docs.refactor_plan.v1",
    "work_queue": [
        {"id": "module_platform_contract", "priority": 1, "status": "pending", "changes": ["ModuleEntry.platform_support", "ModuleHomePage.availability_state"], "acceptance": ["catalog_platform_metadata_complete", "unsupported_module_state_visible"]},
        {"id": "platform_plugin_audit", "priority": 2, "status": "pending", "targets": ["desktop_multi_window", "file_picker_bridge", "usb_serial", "device_info_plus"], "acceptance": ["android_support_matrix", "unsupported_fallbacks"]},
        {"id": "usb_platform_boundary", "priority": 3, "status": "pending", "targets": ["lib/modules/platform/usb_detector"], "acceptance": ["no_windows_hardcode", "android_system_info", "error_branch_test"]},
        {"id": "mobile_layout_baseline", "priority": 4, "status": "pending", "targets": ["module_home", "category_home"], "acceptance": ["no_overflow", "safe_area"]},
        {"id": "android_host", "priority": 5, "status": "blocked_by_dependencies", "depends_on": ["module_platform_contract", "platform_plugin_audit", "mobile_layout_baseline"], "acceptance": ["android_directory", "manifest_capabilities", "debug_apk", "emulator_smoke"]},
    ],
}


@contextmanager
def _plan_repo_fixture(plan_payload=None):
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        app = root / "apps" / "flutter_forge"
        app.mkdir(parents=True)
        (app / "pubspec.yaml").write_text("name: flutter_forge_app\n")
        (root / "REFACTOR_PLAN.md").write_text(json.dumps(plan_payload or PLAN_PAYLOAD))
        yield root


class RefactorPlanLoaderTest(unittest.TestCase):
    def test_loads_work_queue_from_plan(self):
        with _plan_repo_fixture() as root:
            entries = _load_refactor_plan(root)
        self.assertEqual([entry["id"] for entry in entries], ["module_platform_contract", "platform_plugin_audit", "usb_platform_boundary", "mobile_layout_baseline", "android_host"])

    def test_missing_plan_falls_back_to_none(self):
        with tempfile.TemporaryDirectory() as raw:
            self.assertIsNone(_load_refactor_plan(Path(raw)))

    def test_malformed_plan_falls_back_to_none(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "REFACTOR_PLAN.md").write_text("not json {")
            self.assertIsNone(_load_refactor_plan(root))

    def test_real_flutter_forge_plan_matches_current_work_queue_contract(self):
        entries = _load_refactor_plan(Path("/Users/forest/code/langGraph/flutter_forge"))
        self.assertEqual(
            [entry["id"] for entry in entries],
            [
                "module_platform_contract",
                "responsive_navigation_policy",
                "platform_plugin_audit",
                "usb_platform_boundary",
                "mobile_layout_baseline",
                "android_host",
                "android_compatibility_plan",
                "web_compatibility_boundary",
                "android_usb_permission_boundary",
                "module_scaffold_generation",
                "pc_window_lifecycle_baseline",
                "pc_build_matrix",
            ],
        )
        android_plan = next(entry for entry in entries if entry["id"] == "android_compatibility_plan")
        self.assertEqual(android_plan["status"], "planned")
        web_plan = next(entry for entry in entries if entry["id"] == "web_compatibility_boundary")
        self.assertEqual(web_plan["status"], "planned")
        scaffold_plan = next(entry for entry in entries if entry["id"] == "module_scaffold_generation")
        self.assertEqual(scaffold_plan["status"], "completed")


class RefactorPlanTaskGenerationTest(unittest.TestCase):
    def _entry(self, task_id):
        return next(entry for entry in PLAN_PAYLOAD["work_queue"] if entry["id"] == task_id)

    def test_module_platform_contract_maps_paths_and_validation(self):
        with _plan_repo_fixture() as root:
            task = _plan_task(self._entry("module_platform_contract"), root, "flutter_forge", [])
        self.assertEqual(task["task_id"], "module_platform_contract")
        self.assertEqual(task["candidate_paths"], ["apps/flutter_forge/lib/module_registry/module_entry.dart", "apps/flutter_forge/lib/app/module_home_page.dart"])
        self.assertEqual(task["validation"], ["flutter_analyze", "flutter_build"])
        self.assertEqual(task["status"], "READY")
        self.assertEqual(task["dependencies"], [])

    def test_usb_platform_boundary_uses_targets_as_paths(self):
        with _plan_repo_fixture() as root:
            task = _plan_task(self._entry("usb_platform_boundary"), root, "flutter_forge", [])
        self.assertEqual(task["candidate_paths"], ["apps/flutter_forge/lib/modules/platform/usb_detector"])
        self.assertEqual(task["status"], "READY")

    def test_mobile_layout_baseline_is_blocked_decision(self):
        with _plan_repo_fixture() as root:
            task = _plan_task(self._entry("mobile_layout_baseline"), root, "flutter_forge", [])
        self.assertEqual(task["status"], "BLOCKED_DECISION")
        self.assertEqual(task["reason"], "visual_acceptance_required")
        self.assertEqual(task["entry_type"], "decision")

    def test_android_host_blocked_until_deps_complete(self):
        with _plan_repo_fixture() as root:
            blocked = _plan_task(self._entry("android_host"), root, "flutter_forge", [])
            ready = _plan_task(self._entry("android_host"), root, "flutter_forge", ["module_platform_contract", "platform_plugin_audit", "mobile_layout_baseline"])
        self.assertEqual(blocked["status"], "BLOCKED_DECISION")
        self.assertEqual(blocked["reason"], "depends_on_incomplete")
        self.assertEqual(ready["status"], "READY")
        self.assertEqual(blocked["dependencies"], ["module_platform_contract", "platform_plugin_audit", "mobile_layout_baseline"])

    def test_android_host_uses_apk_build_validation(self):
        with _plan_repo_fixture() as root:
            task = _plan_task(self._entry("android_host"), root, "flutter_forge", ["module_platform_contract", "platform_plugin_audit", "mobile_layout_baseline"])
        self.assertEqual(task["candidate_paths"], ["apps/flutter_forge/android/", "apps/flutter_forge/pubspec.yaml"])
        self.assertEqual(task["validation"], ["flutter_analyze", "flutter_build:apk"])

    def test_repository_qualified_targets_are_not_prefixed_twice(self):
        with _plan_repo_fixture() as root:
            self.assertEqual(
                _normalise_plan_target(root, "apps/flutter_forge/lib/modules/platform/usb_detector"),
                "apps/flutter_forge/lib/modules/platform/usb_detector",
            )

    def test_completed_plan_entry_is_not_reoffered_as_ready(self):
        entry = {"id": "completed_task", "status": "completed", "targets": ["lib/app"]}
        with _plan_repo_fixture() as root:
            task = _plan_task(entry, root, "flutter_forge", ["completed_task"])
        self.assertEqual(task["status"], "DONE")


class RefactorPlanProgramTest(unittest.TestCase):
    def _program(self, root, completed=None):
        config = WorkspaceConfig(workspace_root=root, allowed_paths=[root], registry_path=root / "bootstrap.json")
        repo = types.SimpleNamespace(development_units=[])
        with patch("agent_hub.graphs.development.registry_api.get_repository", return_value=repo), \
             patch("agent_hub.graphs.development.registry_api.refresh"), \
             patch("agent_hub.graphs.development._git", side_effect=lambda _r, *a: "main" if a[0] == "branch" else "base"), \
             patch.dict(os.environ, {"AGENT_HUB_INTEGRATION_WORKTREE": str(root)}):
            return _new_program(config, "flutter_forge", completed)

    def test_program_materializes_plan_tasks_with_dependency_dag(self):
        with _plan_repo_fixture() as root:
            program = self._program(root)
        task_ids = {task["task_id"] for task in program["tasks"]}
        self.assertEqual(task_ids, {"module_platform_contract", "platform_plugin_audit", "usb_platform_boundary", "android_host"})
        self.assertEqual(program["dependency_dag"]["android_host"], ["module_platform_contract", "platform_plugin_audit", "mobile_layout_baseline"])
        self.assertEqual(program["dependency_dag"]["module_platform_contract"], [])

    def test_program_preserves_historical_tasks_only_as_completed(self):
        with _plan_repo_fixture() as root:
            program = self._program(root)
        self.assertIn("app-router-private-facade", program["completed_tasks"])
        self.assertIn("gcode-controller-file-picking-capability", program["completed_tasks"])
        self.assertNotIn("app-router-private-facade", {task["task_id"] for task in program["tasks"]})

    def test_mobile_layout_baseline_surfaces_as_blocked(self):
        with _plan_repo_fixture() as root:
            program = self._program(root)
        mobile = next(item for item in program["blocked_tasks"] if item["task_id"] == "mobile_layout_baseline")
        self.assertEqual(mobile["status"], "BLOCKED_DECISION")
        self.assertEqual(mobile["reason"], "visual_acceptance_required")

    def test_program_without_plan_keeps_hardcoded_fallback(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            app = root / "apps" / "flutter_forge"
            lib_app = app / "lib" / "app"
            lib_app.mkdir(parents=True)
            (app / "pubspec.yaml").write_text("name: flutter_forge_app\n")
            (lib_app / "app.dart").write_text("AppRouter.router\n")
            router = app / "lib" / "app" / "router"
            router.mkdir(parents=True)
            (router / "app_router.dart").write_text("static final GoRouter router\n")
            controller = app / "lib" / "modules" / "ui" / "gcode_visualizer" / "state"
            controller.mkdir(parents=True)
            (controller / "gcode_player_controller.dart").write_text("class GcodePlayerController {\n  void pickFilePathAndLoad() {}\n}\n")
            (lib_app / "category_navigation.dart").write_text("class CategoryNavigation {}\n")
            program = self._program(root)
        task_ids = {task["task_id"] for task in program["tasks"]}
        self.assertIn("app-router-private-facade", task_ids)
        self.assertEqual(task_ids & {"module_platform_contract", "platform_plugin_audit", "usb_platform_boundary", "android_host", "mobile_layout_baseline"}, set())
        self.assertTrue(any(item["task_id"] == "gcode-controller-ownership" for item in program["blocked_tasks"]))

    def test_reconcile_unblocks_android_host_when_deps_complete(self):
        program = {
            "repository": "flutter_forge",
            "tasks": [{"task_id": "android_host", "status": "BLOCKED_DECISION", "reason": "depends_on_incomplete", "dependencies": ["module_platform_contract", "platform_plugin_audit", "mobile_layout_baseline"]}],
            "blocked_tasks": [{"task_id": "android_host", "status": "BLOCKED_DECISION", "reason": "depends_on_incomplete"}],
            "completed_tasks": ["module_platform_contract", "platform_plugin_audit", "mobile_layout_baseline"],
            "architecture_issues": [],
        }
        with patch("agent_hub.graphs.development._git", side_effect=lambda _r, *a: "" if a[0] == "log" else "main"):
            reconciled = reconcile_program(program, Path("/tmp/plan"))
        self.assertEqual(reconciled["tasks"][0]["status"], "READY")
        self.assertEqual(reconciled["blocked_tasks"], [])

    def test_reconcile_keeps_android_host_blocked_when_deps_missing(self):
        program = {
            "repository": "flutter_forge",
            "tasks": [{"task_id": "android_host", "status": "BLOCKED_DECISION", "reason": "depends_on_incomplete", "dependencies": ["module_platform_contract", "platform_plugin_audit", "mobile_layout_baseline"]}],
            "blocked_tasks": [{"task_id": "android_host", "status": "BLOCKED_DECISION", "reason": "depends_on_incomplete"}],
            "completed_tasks": ["module_platform_contract"],
            "architecture_issues": [],
        }
        with patch("agent_hub.graphs.development._git", side_effect=lambda _r, *a: "" if a[0] == "log" else "main"):
            reconciled = reconcile_program(program, Path("/tmp/plan"))
        self.assertEqual(reconciled["tasks"][0]["status"], "BLOCKED_DECISION")
        self.assertEqual(reconciled["blocked_tasks"][0]["task_id"], "android_host")


class WorkerBuildMatrixTest(unittest.TestCase):
    def payload(self, **changes):
        value = {"repository": "flutter_forge", "base_revision": "abc", "requirement": "x", "allowed_paths": ["lib/x.dart"], "validation": ["flutter_test:test/x_test.dart"]}
        value.update(changes)
        return value

    def test_accepts_target_qualified_build_validation_tokens(self):
        request = WorkerRequest.from_json(self.payload(validation=["flutter_analyze", "flutter_build:macos", "flutter_build:windows", "flutter_build:apk"]), "flutter_forge")
        self.assertEqual(request.validation, ["flutter_analyze", "flutter_build:macos", "flutter_build:windows", "flutter_build:apk"])

    def test_build_target_mapping(self):
        self.assertEqual(_build_target("flutter_build"), "macos")
        self.assertEqual(_build_target("flutter_build:macos"), "macos")
        self.assertEqual(_build_target("flutter_build:windows"), "windows")
        self.assertEqual(_build_target("flutter_build:apk"), "apk")

    def test_macos_target_runs_on_darwin_and_skips_elsewhere(self):
        from agent_hub.execution.code_worker import LocalCodeExecutor
        class Result:
            returncode = 0
            stderr = ""
        executor = LocalCodeExecutor(Path.cwd(), repository_id="flutter_forge")
        with patch("agent_hub.execution.code_worker.platform.system", return_value="Darwin"), patch("agent_hub.execution.code_worker.subprocess.run", return_value=Result()):
            passed = executor._run_build(Path.cwd(), "macos")
        self.assertEqual(passed["status"], "PASS")
        with patch("agent_hub.execution.code_worker.platform.system", return_value="Linux"):
            skipped = executor._run_build(Path.cwd(), "macos")
        self.assertEqual(skipped["status"], "SKIPPED")
        self.assertEqual(skipped["reason"], "non_darwin_host")

    def test_windows_target_skips_on_darwin(self):
        from agent_hub.execution.code_worker import LocalCodeExecutor
        executor = LocalCodeExecutor(Path.cwd(), repository_id="flutter_forge")
        with patch("agent_hub.execution.code_worker.platform.system", return_value="Darwin"):
            result = executor._run_build(Path.cwd(), "windows")
        self.assertEqual(result["status"], "SKIPPED")
        self.assertEqual(result["reason"], "non_windows_host")

    def test_apk_target_runs_with_toolchain_and_skips_without(self):
        from agent_hub.execution.code_worker import LocalCodeExecutor
        class Result:
            returncode = 0
            stderr = ""
        executor = LocalCodeExecutor(Path.cwd(), repository_id="flutter_forge")
        with patch("agent_hub.execution.code_worker.shutil.which", return_value="/usr/bin/adb"), patch("agent_hub.execution.code_worker.subprocess.run", return_value=Result()):
            ran = executor._run_build(Path.cwd(), "apk")
        self.assertEqual(ran["status"], "PASS")
        with patch("agent_hub.execution.code_worker.shutil.which", return_value=None):
            skipped = executor._run_build(Path.cwd(), "apk")
        self.assertEqual(skipped["status"], "SKIPPED")
        self.assertEqual(skipped["reason"], "android_toolchain_unavailable")

    def test_unsupported_target_is_fatal(self):
        from agent_hub.execution.code_worker import LocalCodeExecutor
        executor = LocalCodeExecutor(Path.cwd(), repository_id="flutter_forge")
        result = executor._run_build(Path.cwd(), "ios")
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["reason"], "unsupported_build_target")

    def test_run_builds_aggregates_skips(self):
        from agent_hub.execution.code_worker import LocalCodeExecutor
        executor = LocalCodeExecutor(Path.cwd(), repository_id="flutter_forge")
        with patch.object(executor, "_run_build", side_effect=lambda _w, target: {"status": "SKIPPED", "reason": "non_darwin_host", "target": target}):
            result = executor._run_builds(Path.cwd(), ["flutter_build:macos", "flutter_build:windows"])
        self.assertEqual(result["status"], "SKIPPED")


class ContextPlannedCapabilitiesTest(unittest.TestCase):
    def _config(self, root, plan_payload):
        app = root / "flutter_forge"
        app.mkdir(parents=True)
        if plan_payload is not None:
            (app / "REFACTOR_PLAN.md").write_text(json.dumps(plan_payload))
        config = WorkspaceConfig(workspace_root=root, allowed_paths=[root], registry_path=root / "bootstrap.json")
        config.runtime = {"repositories": {"flutter_forge": {"runtime_path": str(app)}}}
        return config

    def test_pending_entry_surfaces_when_paths_intersect(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            config = self._config(root, PLAN_PAYLOAD)
            package = {"files": [{"relative_path": "flutter_forge/lib/modules/platform/usb_detector/usb_detector.dart"}]}
            planned = planned_capabilities(package, config)
        ids = [item["task_id"] for item in planned]
        self.assertIn("usb_platform_boundary", ids)
        self.assertNotIn("android_host", ids)
        self.assertNotIn("mobile_layout_baseline", ids)
        self.assertNotIn("module_platform_contract", ids)

    def test_no_plan_file_yields_empty_planned_capabilities(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            config = self._config(root, None)
            package = {"files": [{"relative_path": "flutter_forge/lib/modules/platform/usb_detector/usb_detector.dart"}]}
            self.assertEqual(planned_capabilities(package, config), [])

    def test_non_matching_paths_yield_empty_planned_capabilities(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            config = self._config(root, PLAN_PAYLOAD)
            package = {"files": [{"relative_path": "flutter_forge/lib/modules/state/foo_module/module_entry.dart"}]}
            self.assertEqual(planned_capabilities(package, config), [])


if __name__ == "__main__":
    unittest.main()
