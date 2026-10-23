import tempfile
from pathlib import Path
import threading
import unittest
import json
from copy import deepcopy
from contextlib import redirect_stdout, redirect_stderr
import io
import sqlite3
import select
import signal
import subprocess
import sys
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from agent_hub.learning_workflows.catalog import Catalog
from agent_hub.learning_workflows.store import Conflict, WorkflowStore
from agent_hub.learning_workflows.server import WorkflowServer
from agent_hub.learning_workflows.maintenance import DAY, inspect, maintain, restore
from agent_hub.learning_workflows.cli import main

CATALOG = Catalog.load()
FLOW = CATALOG.document["workflows"][0]
CAPABILITIES = CATALOG.document["capabilities"]


def next_catalog(version=2):
    document = deepcopy(CATALOG.document)
    document["workflows"][0]["version"] = version
    document["workflows"][0]["title"] = f"文章数据探索 v{version}"
    return Catalog(document)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "runs.sqlite3"
        self.now = 100.0
        self.store = WorkflowStore(self.path, clock=lambda: self.now)
        self.store.register("forge", CAPABILITIES)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def run_and_claim(self, key="request"):
        run = self.store.create("forge", key, {})
        claim = self.store.claim("forge")
        self.assertEqual(run["id"], claim["id"])
        return run["id"], claim["leaseToken"]

    def event(self, run, lease, key, value):
        return self.store.append(run, "forge", lease, key, value)

    def test_immutable_versions_idempotent_requests_and_restart(self):
        self.store.activate(CATALOG)
        with self.assertRaises(Conflict):
            document = deepcopy(CATALOG.document)
            document["workflows"][0]["title"] = "changed"
            self.store.activate(Catalog(document))
        run = self.store.create("forge", "same", {})
        self.assertEqual(self.store.create("forge", "same", {})["id"], run["id"])
        with self.assertRaises(Conflict):
            self.store.create("forge", "same", {"query": "different"})
        self.store.close()
        self.store = WorkflowStore(self.path, clock=lambda: self.now)
        self.assertEqual(self.store.get(run["id"])["definition"], FLOW)

    def test_order_lease_and_exactly_once_completion(self):
        run, lease = self.run_and_claim()
        self.assertIsNone(self.store.claim("forge"))
        with self.assertRaises(Conflict):
            self.event(run, "wrong", "wrong", {"kind": "failed"})
        with self.assertRaises(Conflict):
            self.event(run, lease, "out-of-order", {"kind": "step_started", "stepId": "organize"})
        for step in ["fetch", "organize"]:
            for kind in ["step_started", "step_succeeded"]:
                event = {"kind": kind, "stepId": step}
                self.event(run, lease, step + kind, event)
                self.event(run, lease, step + kind, event)
        event = {"kind": "succeeded", "result": {"columns": FLOW["output"]["columns"], "rows": [["1", "title", "user"]]}}
        result = self.event(run, lease, "success", event)
        self.assertEqual(result["state"], "succeeded")
        self.assertEqual(result, self.event(run, lease, "success", event))
        with self.assertRaises(Conflict):
            self.event(run, lease, "late", {"kind": "failed"})
        self.assertNotIn("leaseToken", result)

    def test_cancel_expiry_and_retry(self):
        queued = self.store.create("forge", "queued", {})
        self.assertEqual(self.store.cancel(queued["id"])["state"], "cancelled")
        run, lease = self.run_and_claim()
        self.assertEqual(self.store.cancel(run)["state"], "cancelling")
        with self.assertRaises(Conflict):
            self.event(run, lease, "late", {"kind": "step_started", "stepId": "fetch"})
        self.event(run, lease, "cancel", {"kind": "cancelled"})
        retry = self.store.create("forge", "retry", {}, retry_of=run)
        self.assertEqual(retry["retryOf"], run)
        claim = self.store.claim("forge")
        self.now += 46
        self.assertEqual(self.store.get(retry["id"])["state"], "failed")
        with self.assertRaises(Conflict):
            self.event(retry["id"], claim["leaseToken"], "too-late", {"kind": "cancelled"})

    def test_limits_and_manifest(self):
        for values in [{"page": True}, {"delayMs": 6000}, {"url": "https://example.invalid"}]:
            with self.assertRaises(ValueError):
                self.store.create("forge", "invalid", values)
        with self.assertRaises(ValueError):
            self.store.register("other", [])

    def test_unclaimed_expiry_and_empty_lease(self):
        run = self.store.create("forge", "unclaimed", {})
        with self.assertRaises(Conflict):
            self.event(run["id"], "", "forged", {"kind": "failed"})
        self.now += 121
        self.assertEqual(self.store.get(run["id"])["state"], "failed")

    def test_concurrent_claim_has_one_winner(self):
        self.store.create("forge", "concurrent", {})
        results = []
        threads = [threading.Thread(target=lambda: results.append(self.store.claim("forge"))) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sum(result is not None for result in results), 1)

    def test_upgrade_interrupts_inflight_invalidates_lease_and_retries_latest(self):
        run, lease = self.run_and_claim()
        queued = self.store.create("forge", "queued", {})
        result = self.store.activate(next_catalog())
        self.assertEqual(result["interrupted"], 2)
        for run_id in (run, queued["id"]):
            state = self.store.get(run_id)
            self.assertEqual(state["state"], "cancelled")
            self.assertIn("升级终止", state["error"])
            self.assertEqual(state["definition"], FLOW)
            self.assertEqual(state["finishedAt"], self.now)
        with self.assertRaises(Conflict):
            self.event(run, lease, "late", {"kind": "failed"})
        with self.assertRaises(ValueError):
            self.store.claim("forge")
        self.store.register("forge", CAPABILITIES)
        retry = self.store.create("forge", "retry", {}, version=1, retry_of=run)
        self.assertNotEqual(retry["id"], run)
        self.assertEqual(retry["definition"]["version"], 2)
        self.assertEqual(retry["retryOf"], run)
        with self.assertRaises(Conflict):
            self.store.create("forge", "stale", {}, version=1)
        self.assertEqual([f["version"] for f in self.store.definitions()], [2])

    def test_failed_activation_rolls_back_and_same_catalog_does_not_interrupt(self):
        run, lease = self.run_and_claim()
        self.assertEqual(self.store.activate(CATALOG)["interrupted"], 0)
        changed = deepcopy(CATALOG.document)
        changed["workflows"][0]["title"] = "invalid same version"
        with self.assertRaises(Conflict):
            self.store.activate(Catalog(changed))
        self.assertEqual(self.store.get(run)["state"], "running")
        self.event(run, lease, "still-live", {"kind": "failed"})

    def test_partial_catalog_install_is_rolled_back_on_later_conflict(self):
        document = deepcopy(CATALOG.document)
        document["workflows"].append({**deepcopy(FLOW), "id": "other"})
        self.store.activate(Catalog(document))
        original_digest = self.store.metadata("catalogDigest")
        changed = deepcopy(document)
        changed["workflows"][0]["version"] = 2
        changed["workflows"][1]["title"] = "same-version conflict"
        with self.assertRaises(Conflict):
            self.store.activate(Catalog(changed))
        self.assertEqual(self.store.metadata("catalogDigest"), original_digest)
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM versions WHERE version=2").fetchone()[0], 0)

    def test_schema_is_from_current_declaration_and_retry_does_not_guess(self):
        run, lease = self.run_and_claim()
        self.event(run, lease, "fail", {"kind": "failed"})
        document = next_catalog().document
        document["workflows"][0]["inputSchema"]["properties"].pop("query")
        document["workflows"][0]["inputSchema"]["properties"]["page"]["maximum"] = 2
        self.store.activate(Catalog(document))
        self.store.register("forge", CAPABILITIES)
        for values in ({"query": "old"}, {"page": 3}):
            with self.assertRaises(ValueError):
                self.store.create("forge", "retry-invalid", values, retry_of=run)
        self.assertEqual(self.store.get(run)["definition"], FLOW)

    def test_single_user_can_retry_after_executor_identity_changes(self):
        run, lease = self.run_and_claim()
        self.event(run, lease, "fail", {"kind": "failed"})
        self.store.activate(next_catalog())
        self.store.register("forge-reconnected", CAPABILITIES)
        retry = self.store.create("forge-reconnected", "retry", {}, retry_of=run)
        self.assertEqual(retry["executorId"], "forge-reconnected")
        self.assertEqual(retry["definition"]["version"], 2)
        self.assertEqual(self.store.get(run)["executorId"], "forge")

    def test_idempotent_request_after_upgrade_preserves_original_run(self):
        run = self.store.create("forge", "same", {})
        self.store.activate(next_catalog())
        self.store.register("forge", CAPABILITIES)
        replay = self.store.create("forge", "same", {})
        self.assertEqual(replay["id"], run["id"])
        self.assertEqual(replay["definition"]["version"], 1)

    def test_upgrade_and_claim_race_cannot_leave_old_run_running(self):
        run = self.store.create("forge", "race", {})
        barrier = threading.Barrier(2)
        errors = []
        def claim():
            barrier.wait()
            try:
                self.store.claim("forge")
            except ValueError:
                pass  # Upgrade removed the old registration first.
            except Exception as error:
                errors.append(error)
        worker = threading.Thread(target=claim)
        worker.start()
        barrier.wait()
        self.store.activate(next_catalog())
        worker.join()
        self.assertFalse(errors)
        self.assertEqual(self.store.get(run["id"])["state"], "cancelled")

    def test_retention_cascades_events_keeps_live_runs_and_rotates_backups(self):
        old = self.store.create("forge", "old", {})
        self.store.cancel(old["id"])
        maintain(self.store, backup_count=2)
        self.now += 31 * DAY
        live = self.store.create("forge", "live", {})
        result = maintain(self.store, backup_count=2)
        self.assertEqual(result["removedRuns"], 1)
        with self.assertRaises(KeyError):
            self.store.get(old["id"])
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM events WHERE run_id=?", (old["id"],)).fetchone()[0], 0)
        self.assertEqual(self.store.get(live["id"])["state"], "queued")
        maintain(self.store, backup_count=2, force_backup=True)
        files = list(self.path.with_name(self.path.name + ".backups").iterdir())
        self.assertEqual(len(files), 2)
        for file in files:
            self.assertEqual(file.stat().st_mode & 0o777, 0o600)
            self.assertEqual(inspect(file)["stateVersion"], 2)

    def test_backup_failure_is_not_reported_as_success(self):
        with patch("agent_hub.learning_workflows.maintenance.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                maintain(self.store)
        self.assertIsNone(self.store.metadata("backup"))

    def test_restore_expires_history_and_never_replays_live_tasks(self):
        old = self.store.create("forge", "old", {})
        self.store.cancel(old["id"])
        run, _ = self.run_and_claim()
        snapshot = maintain(self.store)["backup"]["path"]
        destination = Path(self.temp.name) / "restored.sqlite3"
        result = restore(snapshot, destination)
        self.assertEqual(result["interrupted"], 1)
        restored = WorkflowStore(destination, activate=False)
        try:
            with self.assertRaises(KeyError):
                restored.get(old["id"])
            self.assertEqual(restored.get(run)["state"], "cancelled")
            self.assertIn("恢复终止", restored.get(run)["error"])
            with self.assertRaises(ValueError):
                restored.claim("forge")
        finally:
            restored.close()
        with self.assertRaises(ValueError):
            restore(snapshot, destination)

    def test_inspect_is_read_only_and_legacy_database_is_not_migrated(self):
        before = self.path.read_bytes()
        self.assertEqual(inspect(self.path)["workflows"][0]["version"], 1)
        self.assertEqual(before, self.path.read_bytes())
        legacy = Path(self.temp.name) / "legacy.sqlite3"
        db = sqlite3.connect(legacy)
        db.execute("CREATE TABLE runs(id TEXT)")
        db.commit(); db.close()
        before = legacy.read_bytes()
        with self.assertRaisesRegex(ValueError, "Unsupported state"):
            WorkflowStore(legacy)
        self.assertEqual(before, legacy.read_bytes())


class CatalogTests(unittest.TestCase):
    def test_rejects_executable_unknown_or_unbounded_declarations(self):
        variants = []
        extra = deepcopy(CATALOG.document)
        extra["shell"] = "echo unsafe"
        variants.append(extra)
        unknown = deepcopy(CATALOG.document)
        unknown["workflows"][0]["steps"][0]["capability"] = "unknown"
        variants.append(unknown)
        unbounded = deepcopy(CATALOG.document)
        del unbounded["workflows"][0]["inputSchema"]["properties"]["query"]["maxLength"]
        variants.append(unbounded)
        for document in variants:
            with self.subTest(document=document), self.assertRaises(ValueError):
                Catalog(document)

    def test_invalid_cli_and_readonly_inspect_do_not_create_state(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "absent.sqlite3"
            with redirect_stderr(io.StringIO()):
                self.assertEqual(main(["inspect", "--state", str(missing)]), 2)
                self.assertEqual(main(["maintain", "--state", str(missing)]), 2)
            self.assertFalse(missing.exists())
            with redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit) as result:
                    main(["--help"])
            self.assertEqual(result.exception.code, 0)

    def test_serve_failure_cleans_its_token_but_never_overwrites_existing_token(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.sqlite3"
            token = Path(directory) / "token"
            args = ["serve", "--state", str(state), "--token-file", str(token), "--port", "0"]
            with patch("agent_hub.learning_workflows.cli.WorkflowServer", side_effect=OSError("bind failed")), redirect_stderr(io.StringIO()):
                self.assertEqual(main(args), 2)
            self.assertFalse(token.exists())
            token.write_text("existing test token")
            with redirect_stderr(io.StringIO()):
                self.assertEqual(main(args), 2)
            self.assertEqual(token.read_text(), "existing test token")


class HttpTests(unittest.TestCase):
    def test_auth_origin_and_remote_submission(self):
        store = WorkflowStore(":memory:")
        server = WorkflowServer(("127.0.0.1", 0), store, "temporary", ["http://localhost:7357"])
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        def request(path, data=None, token="temporary", origin=None):
            headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
            if origin:
                headers["Origin"] = origin
            with urlopen(Request(base + path, data=None if data is None else json.dumps(data).encode(), headers=headers), timeout=5) as response:
                return json.load(response)
        try:
            for token, origin, code in [("wrong", None, 401), ("temporary", "https://other.invalid", 403)]:
                with self.assertRaises(HTTPError) as error:
                    request("/v1/workflows", token=token, origin=origin)
                self.assertEqual(error.exception.code, code)
                error.exception.close()
            request("/v1/executors", {"executorId": "forge", "capabilities": CAPABILITIES})
            run = request("/v1/runs", {"executorId": "forge", "requestKey": "from-hub", "workflowId": FLOW["id"], "workflowVersion": 1, "inputs": {}})
            claim = request("/v1/executors/forge/claim", {})
            self.assertEqual(run["id"], claim["id"])
            self.assertEqual(request(f"/v1/runs/{run['id']}/cancel", {})["state"], "cancelling")
            store.activate(next_catalog())
            self.assertEqual(request("/v1/workflows")["workflows"][0]["version"], 2)
            request("/v1/executors", {"executorId": "forge", "capabilities": CAPABILITIES})
            with self.assertRaises(HTTPError) as error:
                request(f"/v1/runs/{run['id']}/events", {"executorId": "forge", "leaseToken": claim["leaseToken"], "eventKey": "late", "event": {"kind": "failed"}})
            self.assertEqual(error.exception.code, 409)
            error.exception.close()
            retry = request("/v1/runs", {"executorId": "forge", "requestKey": "retry", "workflowId": FLOW["id"], "workflowVersion": 1, "inputs": {}, "retryOf": run["id"]})
            self.assertEqual(retry["definition"]["version"], 2)
            server.next_maintenance = 0
            with patch("agent_hub.learning_workflows.server.maintain", side_effect=OSError("disk full")):
                server.service_actions()
            self.assertEqual(request("/v1/status")["maintenanceError"], "OSError")
            server.run_maintenance()
            self.assertIsNone(request("/v1/status")["maintenanceError"])
        finally:
            server.shutdown(); server.server_close(); thread.join(); store.close()


class CliLifecycleTests(unittest.TestCase):
    def test_real_entrypoint_boots_backs_up_and_removes_token_on_shutdown(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.sqlite3"
            token = Path(directory) / "test.token"
            process = subprocess.Popen(
                [sys.executable, str(root / "agent"), "workflow", "serve", "--state", str(state),
                 "--token-file", str(token), "--port", "0"], cwd=root,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            try:
                self.assertTrue(select.select([process.stdout], [], [], 10)[0], "server did not start")
                line = process.stdout.readline()
                self.assertTrue(line.startswith("Workflow Hub: http://127.0.0.1:"), line)
                endpoint = line.split("Workflow Hub: ", 1)[1].split(";", 1)[0]
                with urlopen(Request(endpoint + "/v1/status", headers={"Authorization": "Bearer " + token.read_text()}), timeout=5) as response:
                    status = json.load(response)
                self.assertIsNone(status["maintenanceError"])
                self.assertTrue(Path(status["backup"]["path"]).is_file())
                self.assertEqual(status["maintenance"]["retentionDays"], 30)
                with redirect_stderr(io.StringIO()):
                    self.assertEqual(main(["maintain", "--state", str(state)]), 2)
                    self.assertEqual(main(["serve", "--state", str(state), "--token-file", str(token.with_name("second.token")), "--port", "0"]), 2)
                self.assertFalse(token.with_name("second.token").exists())
                self.assertEqual(inspect(state)["catalogDigest"], status["catalogDigest"])
                process.send_signal(signal.SIGINT)
                stdout, stderr = process.communicate(timeout=10)
                self.assertEqual(process.returncode, 0, stdout + stderr)
                self.assertFalse(token.exists())
                self.assertEqual(inspect(state)["workflows"][0]["id"], "articles.explore")
            finally:
                if process.poll() is None:
                    process.kill()
                process.communicate(timeout=5)


if __name__ == "__main__":
    unittest.main()
