"""Frozen validation identifiers, argv execution and content-bound receipts."""
from __future__ import annotations

import platform
import subprocess
import sys
from pathlib import Path, PurePosixPath

from agent_hub.execution.control import ControlError, digest


def relative(value: str) -> str:
    if not isinstance(value, str):
        raise ControlError("VALIDATION_PATH_INVALID")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value or "\\" in value or any(c in value for c in "\0\r\n"):
        raise ControlError("VALIDATION_PATH_INVALID")
    return value


def command(check: str) -> list[str]:
    simple = {"flutter_analyze": ["flutter", "analyze"], "flutter_test": ["flutter", "test"],
              "dart_analyze": ["dart", "analyze"], "dart_test": ["dart", "test"]}
    if check in simple:
        return simple[check]
    if check == "flutter_build":
        return ["flutter", "build", "macos", "--debug"]
    if check in {"flutter_build:macos", "flutter_build:windows", "flutter_build:apk"}:
        return ["flutter", "build", check.split(":", 1)[1], "--debug"]
    if check.startswith("flutter_test:"):
        return ["flutter", "test", relative(check.split(":", 1)[1])]
    if check.startswith("python_unittest:"):
        module = check.split(":", 1)[1]
        if not module or not all(part.isidentifier() for part in module.split(".")):
            raise ControlError("VALIDATION_COMMAND_INVALID")
        return [sys.executable, "-m", "unittest", module]
    raise ControlError("VALIDATION_COMMAND_INVALID")


def freeze_checks(task: dict, repositories: list[str]) -> dict:
    declared = task.get("validation_by_repository")
    if not isinstance(declared, dict) or set(declared) != set(repositories):
        raise ControlError("REQUIRED_VALIDATION_MISSING")
    frozen = {}
    for repository in repositories:
        checks = declared[repository]
        if not isinstance(checks, list) or not checks:
            raise ControlError("REQUIRED_VALIDATION_MISSING")
        frozen[repository] = []
        for item in checks:
            if not isinstance(item, dict) or set(item) - {"check_id", "cwd", "timeout_seconds"}:
                raise ControlError("VALIDATION_CONTRACT_INVALID")
            check = str(item.get("check_id", ""))
            command(check)
            timeout = item.get("timeout_seconds", 300)
            if type(timeout) is not int or not 0 < timeout <= 1800:
                raise ControlError("VALIDATION_TIMEOUT_INVALID")
            frozen[repository].append({"check_id": check, "cwd": relative(item.get("cwd", ".")),
                                       "timeout_seconds": timeout})
        if len({(item["check_id"], item["cwd"]) for item in frozen[repository]}) != len(checks):
            raise ControlError("VALIDATION_CONTRACT_INVALID")
    return frozen


def run_checks(root: Path, checks: list[dict], tree_oid: str) -> list[dict]:
    receipts = []
    for check in checks:
        cwd = (root / check["cwd"]).resolve()
        if cwd != root.resolve() and root.resolve() not in cwd.parents:
            raise ControlError("VALIDATION_PATH_ESCAPE")
        status, code, output = "FAIL", None, ""
        try:
            result = subprocess.run(command(check["check_id"]), cwd=cwd,
                                    capture_output=True, text=True, timeout=check["timeout_seconds"])
            code, output = result.returncode, result.stdout + result.stderr
            status = "PASS" if code == 0 else "FAIL"
        except (OSError, subprocess.TimeoutExpired) as error:
            output = type(error).__name__
        receipts.append({**check, "status": status, "exit_code": code, "output_tree_oid": tree_oid,
                         "environment": {"os": platform.system(), "machine": platform.machine()},
                         "log_sha256": digest(output), "output_tail": output[-2000:]})
    return receipts


def receipts_pass(checks: list[dict], receipts: list[dict], tree_oid: str) -> bool:
    if len(checks) != len(receipts) or not checks:
        return False
    for check, receipt in zip(checks, receipts):
        if any(receipt.get(key) != check[key] for key in ("check_id", "cwd", "timeout_seconds")):
            return False
        if receipt.get("status") != "PASS" or receipt.get("exit_code") != 0 or receipt.get("output_tree_oid") != tree_oid:
            return False
        if not receipt.get("environment") or not receipt.get("log_sha256"):
            return False
    return True
