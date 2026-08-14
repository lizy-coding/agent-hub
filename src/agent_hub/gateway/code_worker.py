"""Minimal local HTTP server for the frozen-task Code Worker."""
from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from agent_hub.execution.code_worker import LocalCodeExecutor, execute_request
from agent_hub.execution.decomposition_worker import DecompositionCodeExecutor


class CodeWorkerHandler(BaseHTTPRequestHandler):
    executor: LocalCodeExecutor

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/execute":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length))
            result = DecompositionCodeExecutor().execute(payload) if payload.get("execution_kind") == "decomposition_migration" else execute_request(payload, self.executor)
            body = json.dumps(result).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (json.JSONDecodeError, ValueError) as error:
            self.send_error(400, str(error))
        except Exception as error:
            body = json.dumps({"status": "CODEX_EXECUTION_FAILED", "task_id": "", "repository": "", "base_revision": "", "exit_code": None, "changed_files": [], "diff": "", "validation": {}, "scope_guard": "NOT_RUN", "stdout_tail": "", "stderr_tail": str(error)[-2000:]}).encode()
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def log_message(self, *_: object) -> None:
        return


def run() -> None:
    repository = Path(os.environ["AGENT_HUB_PRIMARY_REPOSITORY_PATH"])
    CodeWorkerHandler.executor = LocalCodeExecutor(repository)
    ThreadingHTTPServer((os.environ.get("AGENT_HUB_CODE_WORKER_HOST", "127.0.0.1"), int(os.environ.get("AGENT_HUB_CODE_WORKER_PORT", "8787"))), CodeWorkerHandler).serve_forever()


if __name__ == "__main__":
    run()
