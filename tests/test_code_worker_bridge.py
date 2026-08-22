import json
import os
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from agent_hub.execution.code_worker import LocalCodeExecutor, WorkerRequest, _changed_files, _complete_diff, execute_request
from agent_hub.graphs.development import build_development_graph
from agent_hub.projects.discovery import discover
from agent_hub.workspace.config import WorkspaceConfig


class _SubprocessResult:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class CodeWorkerRequestTest(unittest.TestCase):
    def payload(self, **changes):
        value = {"repository": "flutter_forge", "base_revision": "abc", "requirement": "x", "allowed_paths": ["lib/x.dart"], "validation": ["flutter_test:test/x_test.dart"]}
        value.update(changes)
        return value

    def test_rejects_invalid_repository_and_unbounded_paths(self):
        with self.assertRaisesRegex(ValueError, "invalid_repository"):
            WorkerRequest.from_json(self.payload(repository="other"), "flutter_forge")
        with self.assertRaisesRegex(ValueError, "invalid_allowed_paths"):
            WorkerRequest.from_json(self.payload(allowed_paths=[]), "flutter_forge")
        with self.assertRaisesRegex(ValueError, "invalid_allowed_paths"):
            WorkerRequest.from_json(self.payload(allowed_paths=["../outside.dart"]), "flutter_forge")

    def test_rejects_arbitrary_shell(self):
        with self.assertRaisesRegex(ValueError, "arbitrary_shell_forbidden"):
            WorkerRequest.from_json(self.payload(validation=["rm -rf /"]), "flutter_forge")

    def test_accepts_flutter_build_validation_token(self):
        request = WorkerRequest.from_json(self.payload(validation=["flutter_analyze", "flutter_build"]), "flutter_forge")
        self.assertEqual(request.validation, ["flutter_analyze", "flutter_build"])

    def test_run_build_skips_on_non_darwin_host(self):
        with patch("agent_hub.execution.code_worker.platform.system", return_value="Linux"):
            result = LocalCodeExecutor(Path.cwd(), repository_id="flutter_forge")._run_build(Path.cwd())
        self.assertEqual(result["status"], "SKIPPED")

    def test_run_build_reports_failure_on_build_error(self):
        class Result:
            returncode = 1
            stderr = "build failed"
        with patch("agent_hub.execution.code_worker.platform.system", return_value="Darwin"), patch("agent_hub.execution.code_worker.subprocess.run", return_value=Result()):
            result = LocalCodeExecutor(Path.cwd(), repository_id="flutter_forge")._run_build(Path.cwd())
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("build failed", result["stderr_tail"])

    def test_run_build_passes_on_success(self):
        class Result:
            returncode = 0
            stderr = ""
        with patch("agent_hub.execution.code_worker.platform.system", return_value="Darwin"), patch("agent_hub.execution.code_worker.subprocess.run", return_value=Result()):
            result = LocalCodeExecutor(Path.cwd(), repository_id="flutter_forge")._run_build(Path.cwd())
        self.assertEqual(result["status"], "PASS")

    def test_flutter_build_failure_returns_validation_failed(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            os.system(f"git init -q {root}")
            os.system(f"git -C {root} config user.email test@example.com")
            os.system(f"git -C {root} config user.name test")
            (root / "pubspec.yaml").write_text("name: x\n")
            os.system(f"git -C {root} add pubspec.yaml && git -C {root} commit -qm base")
            base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
            executor = LocalCodeExecutor(root, repository_id="flutter_forge")
            request = WorkerRequest(repository="flutter_forge", base_revision=base, task_id="t", requirement="x", allowed_paths=["lib/x.dart"], validation=["flutter_build"])
            with patch.object(executor, "_codex_run", return_value=("completed", 0, "out", "err")), \
                 patch("agent_hub.execution.code_worker._changed_files", return_value=[]), \
                 patch.object(executor, "_link_path_dependencies", return_value=None), \
                 patch.object(executor, "_run_build", return_value={"status": "FAIL", "exit_code": 1}), \
                 patch("agent_hub.execution.code_worker.subprocess.run", return_value=_SubprocessResult(0)), \
                 patch("agent_hub.execution.code_worker.subprocess.check_output", return_value=base):
                result = executor.execute(request)
            self.assertEqual(result["status"], "VALIDATION_FAILED")
            self.assertEqual(result["validation"]["build"]["status"], "FAIL")

    def test_collects_untracked_changes_in_complete_diff(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            os.system(f"git init -q {root}")
            os.system(f"git -C {root} config user.email test@example.com")
            os.system(f"git -C {root} config user.name test")
            (root / "tracked.txt").write_text("before\n")
            os.system(f"git -C {root} add tracked.txt && git -C {root} commit -qm initial")
            (root / "tracked.txt").write_text("after\n")
            (root / "new.txt").write_text("new\n")
            changed = _changed_files(root)
            self.assertEqual(changed, ["new.txt", "tracked.txt"])
            diff = _complete_diff(root, changed)
            self.assertIn("a/tracked.txt", diff)
            self.assertIn("a/new.txt", diff)

    def test_invalid_request_has_terminal_structured_response(self):
        result = execute_request({}, LocalCodeExecutor(Path.cwd(), repository_id="flutter_forge"))
        self.assertEqual(result["status"], "CODEX_EXECUTION_FAILED")
        self.assertIn("stderr_tail", result)


class CodeWorkerProcessTest(unittest.TestCase):
    def request(self):
        return WorkerRequest(repository="flutter_forge", base_revision="base", task_id="task", requirement="x", allowed_paths=["lib/x.dart"], validation=[])

    def test_codex_nonzero_returns_after_process_exit(self):
        class Process:
            pid = 1
            returncode = 7
            def communicate(self, timeout=None): return ("out", "err")
        with patch("agent_hub.execution.code_worker.subprocess.Popen", return_value=Process()):
            outcome, code, stdout, stderr = LocalCodeExecutor(Path.cwd(), repository_id="flutter_forge")._codex_run(Path.cwd(), self.request())
        self.assertEqual((outcome, code, stdout, stderr), ("completed", 7, "out", "err"))

    def test_codex_timeout_terminates_process_group_and_returns(self):
        class Process:
            pid = 12
            returncode = -15
            calls = 0
            def communicate(self, timeout=None):
                self.calls += 1
                if self.calls == 1: raise subprocess.TimeoutExpired("codex", timeout)
                return ("out", "err")
        process = Process()
        with patch("agent_hub.execution.code_worker.subprocess.Popen", return_value=process), patch("agent_hub.execution.code_worker.os.killpg") as killpg:
            outcome, code, stdout, stderr = LocalCodeExecutor(Path.cwd(), repository_id="flutter_forge")._codex_run(Path.cwd(), self.request())
        self.assertEqual((outcome, code, stdout, stderr), ("timeout", -15, "out", "err"))
        killpg.assert_called_once()

    def test_workspace_member_external_path_dependency_is_linked(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "source"
            worktree = root / "isolated" / "flutter_forge"
            provider = root / "flutterguard"
            (source / "apps/app").mkdir(parents=True)
            (worktree / "apps/app").mkdir(parents=True)
            provider.mkdir()
            manifest = "dev_dependencies:\n  flutterguard_cli:\n    path: ../../../flutterguard\n"
            (source / "apps/app/pubspec.yaml").write_text(manifest)
            (worktree / "apps/app/pubspec.yaml").write_text(manifest)
            subprocess.run(["git", "init", "-q"], cwd=worktree)
            subprocess.run(["git", "add", "apps/app/pubspec.yaml"], cwd=worktree)
            executor = LocalCodeExecutor(source, repository_id="flutter_forge")
            with patch.dict(os.environ, {"AGENT_HUB_PATH_DEPENDENCY_FLUTTERGUARD_CLI": str(provider)}):
                executor._link_path_dependencies(worktree, worktree.parent)
            self.assertEqual((worktree / "apps/app/../../../flutterguard").resolve(), provider.resolve())
            self.assertTrue((worktree / "apps/app/../../../flutterguard").is_symlink())


class _Worker(BaseHTTPRequestHandler):
    body = {"status": "READY_FOR_HUMAN_REVIEW", "changed_files": ["lib/x.dart"], "diff": "diff", "tests": {"x": 0}, "review": "APPROVED"}
    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        data = json.dumps(self.body).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
    def log_message(self, *_): pass


class DevelopmentGraphWorkerTest(unittest.TestCase):
    def test_worker_result_reaches_graph_result(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), _Worker)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        old = os.environ.get("AGENT_HUB_CODE_WORKER_ENDPOINT")
        os.environ["AGENT_HUB_CODE_WORKER_ENDPOINT"] = f"http://127.0.0.1:{server.server_port}"
        try:
            with tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                repo = root / "flutter_forge"
                repo.mkdir()
                subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
                subprocess.run(["git", "-C", repo, "config", "user.email", "test@example.com"], check=True)
                subprocess.run(["git", "-C", repo, "config", "user.name", "test"], check=True)
                (repo / "pubspec.yaml").write_text("name: flutter_forge_app\n")
                subprocess.run(["git", "-C", repo, "add", "pubspec.yaml"], check=True)
                subprocess.run(["git", "-C", repo, "commit", "-qm", "base"], check=True)
                base = subprocess.check_output(["git", "-C", repo, "rev-parse", "HEAD"], text=True).strip()
                config = WorkspaceConfig(
                    workspace_root=root,
                    allowed_paths=[root],
                    registry_path=root / "bootstrap.json",
                    registry_storage_path=root / "registry.json",
                )
                workspace = discover(config)
                (root / "registry.json").write_text(json.dumps(workspace.model_dump(mode="json")))
                result = build_development_graph(config).invoke({"development_task": {"repository": "flutter_forge", "base_revision": base, "requirement": "x", "allowed_paths": ["lib/x.dart"], "validation": []}})["result"]
            self.assertEqual(result["status"], "READY_FOR_HUMAN_REVIEW")
            self.assertEqual(result["review"], "APPROVED")
        finally:
            server.shutdown()
            server.server_close()
            if old is None: os.environ.pop("AGENT_HUB_CODE_WORKER_ENDPOINT", None)
            else: os.environ["AGENT_HUB_CODE_WORKER_ENDPOINT"] = old
