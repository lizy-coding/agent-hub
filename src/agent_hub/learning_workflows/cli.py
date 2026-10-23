"""Single-user maintenance entrypoint; never publishes or invokes a model."""

import argparse
import json
import os
from pathlib import Path
import secrets
import sqlite3
import sys

from .catalog import Catalog, DEFAULT_CATALOG
from .maintenance import inspect, maintain, restore
from .server import WorkflowServer
from .store import WorkflowStore


def default_state():
    root = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return root / "agent-hub" / "workflows-v2.sqlite3"


def state_lease(path, *, create=False):
    # This host is POSIX. A persistent lock file avoids unlink/recreate races.
    import fcntl
    path = Path(path).resolve()
    if not create and not path.is_file():
        raise ValueError("State does not exist")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(str(path) + ".lock", os.O_CREAT | os.O_RDWR, 0o600)
    file = os.fdopen(descriptor, "r+")
    try:
        fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as error:
        file.close()
        raise ValueError("State is already in use; use inspect or stop the service before maintenance") from error
    return file


def main(argv=None):
    parser = argparse.ArgumentParser(prog="./agent workflow", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("serve", "inspect", "maintain", "restore"):
        child = commands.add_parser(name)
        child.add_argument("--state", type=Path, default=default_state())
        if name in {"serve", "maintain", "restore"}:
            child.add_argument("--retention-days", type=int, default=30, choices=range(1, 3651), metavar="1..3650")
        if name in {"serve", "maintain"}:
            child.add_argument("--backup-count", type=int, default=7, choices=range(1, 101), metavar="1..100")
        if name == "serve":
            child.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
            child.add_argument("--token-file", type=Path)
            child.add_argument("--port", type=int, default=8768)
            child.add_argument("--allow-origin", action="append", default=[])
        elif name == "maintain":
            child.add_argument("--force-backup", action="store_true")
        elif name == "restore":
            child.add_argument("--source", type=Path, required=True)
    args = parser.parse_args(argv)
    lease = None
    try:
        if args.command == "inspect":
            result = inspect(args.state)
        elif args.command == "restore":
            result = restore(args.source, args.state, retention_days=args.retention_days)
        elif args.command == "maintain":
            lease = state_lease(args.state)
            store = WorkflowStore(args.state, activate=False)
            try:
                result = maintain(store, retention_days=args.retention_days, backup_count=args.backup_count, force_backup=args.force_backup)
            finally:
                store.close()
        else:
            # Validate the Git-owned declaration before touching state or credentials.
            catalog = Catalog.load(args.catalog)
            lease = state_lease(args.state, create=True)
            token_file = args.token_file or args.state.with_name("workflows.token")
            token_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            token = secrets.token_urlsafe(32)
            fd = os.open(token_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            try:
                with os.fdopen(fd, "w") as file:
                    file.write(token)
                store = None
                try:
                    with WorkflowServer(("127.0.0.1", args.port), None, token, args.allow_origin,
                                        retention_days=args.retention_days, backup_count=args.backup_count) as server:
                        store = WorkflowStore(args.state, catalog=catalog)
                        server.store = store
                        server.run_maintenance()
                        print(f"Workflow Hub: http://127.0.0.1:{server.server_port}; token file: {token_file}", flush=True)
                        try:
                            server.serve_forever()
                        except KeyboardInterrupt:
                            pass
                finally:
                    if store is not None:
                        store.close()
            finally:
                token_file.unlink(missing_ok=True)
            return 0
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, sqlite3.Error) as error:
        print(f"WORKFLOW_ERROR: {error}", file=sys.stderr)
        return 2
    finally:
        if lease is not None:
            lease.close()
