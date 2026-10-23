"""A bounded, durable control plane for the first Forge execution adapter."""

import json
from pathlib import Path
import secrets
import sqlite3
import threading
import time

from .catalog import Catalog, SCHEMA, encode, identifier, validate_inputs

TERMINAL = {"succeeded", "failed", "cancelled"}
STATE_VERSION = 2
APPLICATION_ID = 0x41485746


class Conflict(ValueError):
    pass


class WorkflowStore:
    def __init__(self, path, *, clock=time.time, lease_seconds=45, catalog=None, activate=True):
        self.clock, self.lease_seconds = clock, lease_seconds
        self.path = Path(path) if str(path) != ":memory:" else None
        self.lock = threading.RLock()
        if self.path:
            if not activate and not self.path.is_file():
                raise ValueError("State does not exist")
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        try:
            tables = self.db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if tables:
                if self.db.execute("PRAGMA user_version").fetchone()[0] != STATE_VERSION or self.db.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID:
                    raise ValueError("Unsupported state database; use a new state path. No legacy migration is provided.")
            elif not activate:
                raise ValueError("Empty state database")
            else:
                self.db.executescript("""
            CREATE TABLE IF NOT EXISTS versions(id TEXT,version INTEGER,definition TEXT,PRIMARY KEY(id,version));
            CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS executors(id TEXT PRIMARY KEY,manifest TEXT,seen REAL);
            CREATE TABLE IF NOT EXISTS runs(
                id TEXT PRIMARY KEY,executor TEXT,request_key TEXT,fingerprint TEXT,
                definition TEXT,inputs TEXT,state TEXT,lease TEXT,expires REAL,
                result TEXT,error TEXT,retry_of TEXT,created REAL,finished REAL,
                UNIQUE(executor,request_key));
            CREATE TABLE IF NOT EXISTS events(run_id TEXT,seq INTEGER,event_key TEXT,payload TEXT,
                PRIMARY KEY(run_id,seq),UNIQUE(run_id,event_key));
                """)
                self.db.execute(f"PRAGMA user_version={STATE_VERSION}")
                self.db.execute(f"PRAGMA application_id={APPLICATION_ID}")
            if activate:
                self.activate(catalog or Catalog.load())
            if self.path:
                self.path.chmod(0o600)
        except Exception:
            self.db.close()
            raise

    def close(self):
        self.db.close()

    def metadata(self, key, default=None):
        row = self.db.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_metadata(self, key, value):
        self.db.execute("INSERT OR REPLACE INTO metadata VALUES(?,?)", (key, encode(value)))

    def current(self):
        return self.metadata("catalog")

    @property
    def capabilities(self):
        return self.current()["capabilities"]

    def interrupt(self, reason):
        rows = self.db.execute("SELECT id FROM runs WHERE state IN ('queued','running','cancelling')").fetchall()
        for row in rows:
            self.db.execute("UPDATE runs SET state='cancelled',error=?,lease=NULL,expires=NULL,finished=? WHERE id=?",
                            (reason, self.clock(), row[0]))
            self._event(row[0], "interrupted", {"kind": "cancelled", "message": reason})
        self.db.execute("DELETE FROM executors")
        return len(rows)

    def activate(self, catalog):
        catalog = Catalog(catalog.document)
        with self.lock, self.db:
            # Begin a write transaction before reads, serializing activation and claims.
            self.db.execute("INSERT OR IGNORE INTO metadata VALUES('initialized','true')")
            previous = self.metadata("catalogDigest")
            for definition in catalog.document["workflows"]:
                encoded = encode(definition)
                row = self.db.execute("SELECT definition FROM versions WHERE id=? AND version=?",
                                      (definition["id"], definition["version"])).fetchone()
                if row and row[0] != encoded:
                    raise Conflict("Workflow version is immutable; increment the version")
                self.db.execute("INSERT OR IGNORE INTO versions VALUES(?,?,?)",
                                (definition["id"], definition["version"], encoded))
            interrupted = self.interrupt("升级终止：当前工作流目录已更新") if previous and previous != catalog.digest else 0
            self.set_metadata("catalog", catalog.document)
            self.set_metadata("catalogDigest", catalog.digest)
            return {"catalogDigest": catalog.digest, "interrupted": interrupted}

    def definitions(self):
        with self.lock:
            return self.current()["workflows"]

    def register(self, executor, manifest):
        identifier(executor)
        with self.lock, self.db:
            self.db.execute("INSERT OR IGNORE INTO metadata VALUES('initialized','true')")
            if manifest != self.capabilities:
                raise ValueError("Executor capability manifest does not match the current catalog")
            self.db.execute("INSERT OR REPLACE INTO executors VALUES(?,?,?)",
                            (executor, json.dumps(manifest), self.clock()))
        return {"executorId": executor, "capabilities": manifest}

    def _row(self, run):
        row = self.db.execute("SELECT * FROM runs WHERE id=?", (identifier(run),)).fetchone()
        if not row:
            raise KeyError("Run not found")
        return row

    def _event(self, run, key, payload):
        seq = self.db.execute("SELECT COALESCE(MAX(seq),0)+1 FROM events WHERE run_id=?", (run,)).fetchone()[0]
        self.db.execute("INSERT INTO events VALUES(?,?,?,?)", (run, seq, key, json.dumps(payload)))

    def _expire(self):
        for row in self.db.execute("SELECT id FROM runs WHERE state='queued' AND created<?", (self.clock() - 120,)).fetchall():
            self.db.execute("UPDATE runs SET state='failed',error='executor did not claim task',finished=? WHERE id=?", (self.clock(), row[0]))
            self._event(row[0], "queue-expired", {"kind": "failed", "message": "executor did not claim task"})
        for row in self.db.execute("SELECT id FROM runs WHERE state IN ('running','cancelling') AND expires<?", (self.clock(),)).fetchall():
            self.db.execute("UPDATE runs SET state='failed',error='executor lease expired',finished=? WHERE id=?", (self.clock(), row[0]))
            self._event(row[0], "lease-expired", {"kind": "failed", "message": "executor lease expired"})

    def create(self, executor, key, arguments, workflow="articles.explore", version=None, retry_of=None):
        identifier(executor); identifier(key)
        identifier(workflow)
        if version is not None and (type(version) is not int or version < 1):
            raise ValueError("Invalid workflow version")
        if not isinstance(arguments, dict):
            raise ValueError("Inputs must be an object")
        fingerprint = encode([workflow, version, arguments, retry_of])
        with self.lock, self.db:
            self.db.execute("INSERT OR IGNORE INTO metadata VALUES('initialized','true')")
            if not self.db.execute("SELECT 1 FROM executors WHERE id=?", (executor,)).fetchone():
                raise ValueError("Register executor first")
            row = self.db.execute("SELECT id,fingerprint FROM runs WHERE executor=? AND request_key=?", (executor, key)).fetchone()
            if row:
                if row[1] != fingerprint:
                    raise Conflict("Request key reused with different inputs")
                run = row[0]
            else:
                definition = next((f for f in self.definitions() if f["id"] == workflow), None)
                if not definition:
                    raise ValueError("Workflow is not active")
                if retry_of:
                    previous = self._row(retry_of)
                    if previous["state"] not in {"failed", "cancelled"} or json.loads(previous["definition"])["id"] != workflow:
                        raise Conflict("Retry must refer to a failed/cancelled run of the same workflow")
                elif version is not None and version != definition["version"]:
                    raise Conflict("Requested version is not active; refresh the catalog")
                values = validate_inputs(definition["inputSchema"], arguments)
                run = secrets.token_hex(12)
                self.db.execute("INSERT INTO runs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (run, executor, key, fingerprint, encode(definition), json.dumps(values), "queued", None, None, None, None, retry_of, self.clock(), None))
                self._event(run, "created", {"kind": "queued"})
        return self.get(run)

    def get(self, run):
        with self.lock, self.db:
            self._expire()
            row = self._row(run)
            return {
                "schema": SCHEMA, "id": row["id"], "executorId": row["executor"],
                "definition": json.loads(row["definition"]), "inputs": json.loads(row["inputs"]),
                "state": row["state"], "retryOf": row["retry_of"], "createdAt": row["created"], "finishedAt": row["finished"],
                "result": json.loads(row["result"]) if row["result"] else None, "error": row["error"],
                "events": [{"seq": e[0], **json.loads(e[1])} for e in self.db.execute(
                    "SELECT seq,payload FROM events WHERE run_id=? ORDER BY seq", (run,))],
            }

    def list_runs(self, executor):
        identifier(executor)
        with self.lock:
            ids = [r[0] for r in self.db.execute("SELECT id FROM runs WHERE executor=? ORDER BY created DESC LIMIT 30", (executor,))]
        return [self.get(run) for run in ids]

    def claim(self, executor):
        identifier(executor)
        with self.lock, self.db:
            self._expire()
            if not self.db.execute("SELECT 1 FROM executors WHERE id=?", (executor,)).fetchone():
                raise ValueError("Unknown executor")
            self.db.execute("UPDATE executors SET seen=? WHERE id=?", (self.clock(), executor))
            if self.db.execute("SELECT 1 FROM runs WHERE executor=? AND state IN ('running','cancelling')", (executor,)).fetchone():
                return None
            row = self.db.execute("SELECT id FROM runs WHERE executor=? AND state='queued' ORDER BY created LIMIT 1", (executor,)).fetchone()
            if not row:
                return None
            run, lease = row[0], secrets.token_urlsafe(24)
            self.db.execute("UPDATE runs SET state='running',lease=?,expires=? WHERE id=?",
                            (lease, self.clock() + self.lease_seconds, run))
            self._event(run, "claimed", {"kind": "running"})
        return {**self.get(run), "leaseToken": lease}

    def cancel(self, run):
        with self.lock, self.db:
            self._expire()
            row = self._row(run)
            if row["state"] not in TERMINAL and row["state"] != "cancelling":
                state = "cancelled" if row["state"] == "queued" else "cancelling"
                self.db.execute("UPDATE runs SET state=?,finished=? WHERE id=?", (state, self.clock() if state == "cancelled" else None, run))
                self._event(run, "cancel-requested", {"kind": state})
        return self.get(run)

    def append(self, run, executor, lease, key, event):
        identifier(key)
        if not isinstance(event, dict) or len(json.dumps(event)) > 40000:
            raise ValueError("Invalid event")
        kind = event.get("kind")
        if kind not in {"step_started", "step_succeeded", "succeeded", "failed", "cancelled"}:
            raise ValueError("Unknown event kind")
        allowed = {"kind", "stepId"} if kind.startswith("step_") else {"kind", "result"} if kind == "succeeded" else {"kind", "message"}
        if set(event) - allowed:
            raise ValueError("Unknown event field")
        with self.lock, self.db:
            self._expire()
            row = self._row(run)
            if not row["lease"] or row["executor"] != executor or not isinstance(lease, str) or not secrets.compare_digest(row["lease"], lease):
                raise Conflict("Wrong executor lease")
            previous = self.db.execute("SELECT payload FROM events WHERE run_id=? AND event_key=?", (run, key)).fetchone()
            if previous:
                if json.loads(previous[0]) != event:
                    raise Conflict("Event key reused")
            else:
                if row["state"] in TERMINAL or (row["state"] == "cancelling" and kind != "cancelled"):
                    raise Conflict("Run no longer accepts this event")
                history = [json.loads(e[0]) for e in self.db.execute("SELECT payload FROM events WHERE run_id=? ORDER BY seq", (run,))]
                steps = [s["id"] for s in json.loads(row["definition"])["steps"]]
                completed = [e["stepId"] for e in history if e["kind"] == "step_succeeded"]
                started = [e["stepId"] for e in history if e["kind"] == "step_started"]
                if kind.startswith("step_"):
                    index = len(completed)
                    if index >= len(steps) or event.get("stepId") != steps[index]:
                        raise Conflict("Step order mismatch")
                    if (kind == "step_started" and len(started) != index) or (kind == "step_succeeded" and len(started) != index + 1):
                        raise Conflict("Step lifecycle mismatch")
                if kind == "succeeded":
                    if completed != steps:
                        raise Conflict("Complete all steps before success")
                    result = event.get("result")
                    columns = json.loads(row["definition"])["output"]["columns"]
                    if not isinstance(result, dict) or set(result) != {"columns", "rows"} or result["columns"] != columns:
                        raise ValueError("Invalid table result")
                    if not isinstance(result["rows"], list) or len(result["rows"]) > 20 or any(
                        not isinstance(r, list) or len(r) != len(columns) or any(not isinstance(c, str) or len(c) > 512 for c in r) for r in result["rows"]):
                        raise ValueError("Invalid table rows")
                    self.db.execute("UPDATE runs SET state='succeeded',result=? WHERE id=?", (json.dumps(result), run))
                elif kind in {"failed", "cancelled"}:
                    message = event.get("message", kind)
                    if not isinstance(message, str) or len(message) > 500:
                        raise ValueError("Invalid terminal message")
                    self.db.execute("UPDATE runs SET state=?,error=? WHERE id=?", (kind, message, run))
                if kind in TERMINAL:
                    self.db.execute("UPDATE runs SET finished=? WHERE id=?", (self.clock(), run))
                self.db.execute("UPDATE runs SET expires=? WHERE id=?", (self.clock() + self.lease_seconds, run))
                self._event(run, key, event)
        return self.get(run)
