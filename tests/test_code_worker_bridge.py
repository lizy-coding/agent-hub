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
from agent_hub.workspace.config import WorkspaceConfig


class CodeWorkerRequestTest(unittest.TestCase):
    def payload(self, **changes):
        value = {"repository": "flutter_study", "base_revision": "abc", "requirement": "x", "allowed_paths": ["lib/x.dart"], "validation": ["flutter_test:test/x_test.dart"]}
        value.update(changes)
        return value

    def test_rejects_invalid_repository_and_unbounded_paths(self):
        with self.assertRaisesRegex(ValueError, "invalid_repository"):
            WorkerRequest.from_json(self.payload(repository="other"), "flutter_study")
        with self.assertRaisesRegex(ValueError, "invalid_allowed_paths"):
            WorkerRequest.from_json(self.payload(allowed_paths=[]), "flutter_study")
        with self.assertRaisesRegex(ValueError, "invalid_allowed_paths"):
            WorkerRequest.from_json(self.payload(allowed_paths=["../outside.dart"]), "flutter_study")

    def test_rejects_arbitrary_shell(self):
        with self.assertRaisesRegex(ValueError, "arbitrary_shell_forbidden"):
            WorkerRequest.from_json(self.payload(validation=["rm -rf /"]), "flutter_study")

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
        result = execute_request({}, LocalCodeExecutor(Path.cwd(), repository_id="flutter_study"))
        self.assertEqual(result["status"], "CODEX_EXECUTION_FAILED")
        self.assertIn("stderr_tail", result)


class CodeWorkerProcessTest(unittest.TestCase):
    def request(self):
        return WorkerRequest(repository="flutter_study", base_revision="base", task_id="task", requirement="x", allowed_paths=["lib/x.dart"], validation=[])

    def test_codex_nonzero_returns_after_process_exit(self):
        class Process:
            pid = 1
            returncode = 7
            def communicate(self, timeout=None): return ("out", "err")
        with patch("agent_hub.execution.code_worker.subprocess.Popen", return_value=Process()):
            outcome, code, stdout, stderr = LocalCodeExecutor(Path.cwd(), repository_id="flutter_study")._codex_run(Path.cwd(), self.request())
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
            outcome, code, stdout, stderr = LocalCodeExecutor(Path.cwd(), repository_id="flutter_study")._codex_run(Path.cwd(), self.request())
        self.assertEqual((outcome, code, stdout, stderr), ("timeout", -15, "out", "err"))
        killpg.assert_called_once()

    def test_workspace_member_external_path_dependency_is_linked(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "source"
            worktree = root / "isolated" / "flutter_study"
            provider = root / "flutterguard"
            (source / "apps/app").mkdir(parents=True)
            (worktree / "apps/app").mkdir(parents=True)
            provider.mkdir()
            manifest = "dev_dependencies:\n  flutterguard_cli:\n    path: ../../../flutterguard\n"
            (source / "apps/app/pubspec.yaml").write_text(manifest)
            (worktree / "apps/app/pubspec.yaml").write_text(manifest)
            subprocess.run(["git", "init", "-q"], cwd=worktree)
            subprocess.run(["git", "add", "apps/app/pubspec.yaml"], cwd=worktree)
            executor = LocalCodeExecutor(source, repository_id="flutter_study")
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
                config = WorkspaceConfig(workspace_root=root, allowed_paths=[root], registry_path=root / "registry.json")
                result = build_development_graph(config).invoke({"development_task": {"repository": "flutter_study", "base_revision": "a", "requirement": "x", "allowed_paths": ["lib/x.dart"], "validation": []}})["result"]
            self.assertEqual(result["status"], "READY_FOR_HUMAN_REVIEW")
            self.assertEqual(result["review"], "APPROVED")
        finally:
            server.shutdown()
            server.server_close()
            if old is None: os.environ.pop("AGENT_HUB_CODE_WORKER_ENDPOINT", None)
            else: os.environ["AGENT_HUB_CODE_WORKER_ENDPOINT"] = old
