"""Local, durable execution identity and single-writer coordination.

Graph and Worker must use the same trusted control directory. Request data
cannot select it. OS locks are authoritative; saved PIDs are diagnostic only.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from contextlib import contextmanager, ExitStack
from pathlib import Path
from uuid import uuid4

DEFAULT_CONTROL_ROOT = Path(__file__).resolve().parents[3] / ".execution" / "control"


class ControlError(RuntimeError):
    pass


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(value, handle, sort_keys=True, ensure_ascii=False, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def file_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        try:
            if os.name == "nt":
                import msvcrt
                if path.stat().st_size == 0:
                    handle.write(b"\0"); handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise ControlError("EXECUTION_BUSY") from error
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def contract_payload(request: dict) -> dict:
    return {key: value for key, value in request.items()
            if key not in {"attempt_id", "generation", "contract_sha256"}}


class ExecutionStore:
    def __init__(self, root: Path | None = None):
        self.root = root or DEFAULT_CONTROL_ROOT

    def path(self, request: dict) -> Path:
        identity = [request.get("project_id"), request.get("task_id")]
        if not all(isinstance(value, str) and value for value in identity):
            raise ControlError("EXECUTION_IDENTITY_MISSING")
        return self.root / "attempts" / f"{digest(identity)}.json"

    @contextmanager
    def repositories(self, request: dict):
        paths = request.get("repository_paths")
        repositories = request.get("repositories")
        if not isinstance(paths, dict) or not isinstance(repositories, list) or not repositories:
            raise ControlError("REPOSITORY_MAPPING_MISSING")
        names = [item.get("repository") for item in repositories if isinstance(item, dict)]
        if len(names) != len(repositories) or len(set(names)) != len(names) or any(name not in paths for name in names):
            raise ControlError("REPOSITORY_MAPPING_MISMATCH")
        if any(not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", name) or name in {".", ".."} for name in names):
            raise ControlError("REPOSITORY_ID_INVALID")
        canonical = []
        for name in names:
            root = Path(paths[name]).resolve()
            try:
                common = subprocess.check_output(["git", "-C", str(root), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                                                 stderr=subprocess.PIPE, timeout=10, text=True).strip()
            except (OSError, subprocess.SubprocessError) as error:
                raise ControlError("REPOSITORY_GIT_IDENTITY_UNAVAILABLE") from error
            canonical.append(str(Path(common).resolve()))
        if len(set(canonical)) != len(canonical):
            raise ControlError("REPOSITORY_MAPPING_MISMATCH")
        with ExitStack() as stack:
            for value in sorted(canonical):
                stack.enter_context(file_lock(self.root / "locks" / f"{digest(value)}.lock"))
            # Serialize task identities even if a new attempt changes repos.
            stack.enter_context(file_lock(self.path(request).with_suffix(".lock")))
            yield

    def load(self, request: dict) -> dict:
        try:
            value = json.loads(self.path(request).read_text())
        except (OSError, ValueError) as error:
            raise ControlError("EXECUTION_RECORD_MISSING") from error
        if not isinstance(value, dict) or value.get("schema") != "execution-control.v1" or not isinstance(value.get("request"), dict):
            raise ControlError("EXECUTION_RECORD_INVALID")
        return value

    def reserve(self, request: dict, previous: dict | None = None) -> dict:
        if any(not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", str(item.get("base_revision", "")))
               for item in request.get("repositories", [])):
            raise ControlError("SOURCE_REVISION_INVALID")
        with self.repositories(request):
            path = self.path(request)
            old = self.load(request) if path.exists() else {}
            if old.get("phase") == "INTEGRATING" or any(
                step.get("phase") in {"APPLYING", "COMMITTED"}
                for step in old.get("integration", {}).values()
            ) and old.get("phase") != "INTEGRATED":
                raise ControlError("INTEGRATION_RECOVERY_REQUIRED")
            # Retrying a failed/abandoned reservation requires the previous
            # identity from Graph checkpoint; competing fresh runs cannot steal it.
            if old and old.get("phase") != "INTEGRATED":
                if not previous or any(previous.get(k) != old.get("request", {}).get(k)
                                       for k in ("attempt_id", "generation", "contract_sha256")):
                    raise ControlError("EXECUTION_ALREADY_RESERVED")
            frozen = {**request, "attempt_id": str(uuid4()),
                      "generation": int(old.get("request", {}).get("generation", 0)) + 1,
                      "contract_sha256": digest(contract_payload(request))}
            atomic_json(path, {"schema": "execution-control.v1", "request": frozen,
                               "phase": "RESERVED", "integration": {}})
            return frozen

    def verify(self, request: dict) -> dict:
        record = self.load(request)
        saved = record.get("request", {})
        if any(request.get(key) != saved.get(key) for key in
               ("attempt_id", "generation", "contract_sha256", "project_id", "task_id")):
            raise ControlError("STALE_EXECUTION_RESULT")
        if digest(contract_payload(request)) != saved.get("contract_sha256") or request != saved:
            raise ControlError("EXECUTION_CONTRACT_MISMATCH")
        return record

    def save(self, request: dict, record: dict) -> None:
        self.verify(request)
        atomic_json(self.path(request), record)

    def result_matches(self, request: dict, result: dict) -> bool:
        return all(result.get(key) == request.get(key) for key in
                   ("attempt_id", "generation", "contract_sha256", "project_id", "task_id"))
