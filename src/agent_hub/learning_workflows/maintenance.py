"""Bounded local retention, SQLite snapshots and offline restore."""

import json
import os
from pathlib import Path
import sqlite3
import tempfile
from contextlib import closing

from .store import APPLICATION_ID, STATE_VERSION, WorkflowStore

DAY = 86400


def validate_state(db):
    if db.execute("PRAGMA user_version").fetchone()[0] != STATE_VERSION or db.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID:
        raise ValueError("Unsupported state database; no legacy migration is provided")


def inspect(path):
    path = Path(path).resolve(strict=True)
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        validate_state(db)
        metadata = {k: json.loads(v) for k, v in db.execute("SELECT key,value FROM metadata")}
        return {
            "state": str(path), "stateVersion": STATE_VERSION,
            "catalogDigest": metadata.get("catalogDigest"),
            "workflows": [{"id": f["id"], "version": f["version"]} for f in metadata["catalog"]["workflows"]],
            "runs": dict(db.execute("SELECT state,COUNT(*) FROM runs GROUP BY state")),
            "lastMaintenance": metadata.get("maintenance"),
            "lastBackup": metadata.get("backup"),
            "maintenanceError": metadata.get("maintenanceError"),
        }


def maintain(store, *, retention_days=30, backup_count=7, force_backup=False):
    if type(retention_days) is not int or not 1 <= retention_days <= 3650:
        raise ValueError("retention_days must be 1..3650")
    if type(backup_count) is not int or not 1 <= backup_count <= 100:
        raise ValueError("backup_count must be 1..100")
    with store.lock:
        now = store.clock()
        with store.db:
            store._expire()
            cutoff = now - retention_days * DAY
            condition = "state IN ('succeeded','failed','cancelled') AND finished<?"
            store.db.execute(f"DELETE FROM events WHERE run_id IN (SELECT id FROM runs WHERE {condition})", (cutoff,))
            removed = store.db.execute(f"DELETE FROM runs WHERE {condition}", (cutoff,)).rowcount
            result = {"at": now, "removedRuns": removed, "retentionDays": retention_days, "backupCount": backup_count}
            store.set_metadata("maintenance", result)
        previous = store.metadata("backup", {})
        if store.path and (force_backup or not previous or now - previous["at"] >= DAY):
            directory = store.path.with_name(store.path.name + ".backups")
            directory.mkdir(mode=0o700, exist_ok=True)
            sequence = previous.get("sequence", -1) + 1
            destination = directory / f"backup-{sequence % backup_count:03}.sqlite3"
            fd, name = tempfile.mkstemp(prefix=".snapshot-", dir=directory)
            os.close(fd)
            temporary = Path(name)
            try:
                target = sqlite3.connect(temporary)
                try:
                    store.db.backup(target)
                    if target.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                        raise ValueError("Backup integrity check failed")
                finally:
                    target.close()
                os.replace(temporary, destination)
            finally:
                temporary.unlink(missing_ok=True)
            for slot in range(backup_count, 100):
                (directory / f"backup-{slot:03}.sqlite3").unlink(missing_ok=True)
            with store.db:
                store.set_metadata("backup", {"at": now, "sequence": sequence, "path": str(destination)})
        with store.db:
            store.set_metadata("maintenanceError", None)
        return {**result, "backup": store.metadata("backup")}


def restore(source, destination, *, retention_days=30):
    if type(retention_days) is not int or not 1 <= retention_days <= 3650:
        raise ValueError("retention_days must be 1..3650")
    source, destination = Path(source).resolve(strict=True), Path(destination).absolute()
    if destination.exists():
        raise ValueError("Restore destination must not exist")
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix=".restore-", dir=destination.parent)
    os.close(fd)
    temporary = Path(name)
    try:
        src = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)
        dst = sqlite3.connect(temporary)
        try:
            validate_state(src)
            if src.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("Restore source integrity check failed")
            src.backup(dst)
        finally:
            src.close()
            dst.close()
        store = WorkflowStore(temporary, activate=False)
        try:
            with store.lock, store.db:
                interrupted = store.interrupt("恢复终止：备份中的未完成任务不自动重放")
            # Do not make a backup of the restored file before applying retention.
            with store.db:
                cutoff = store.clock() - retention_days * DAY
                store.db.execute("DELETE FROM events WHERE run_id IN (SELECT id FROM runs WHERE finished<?)", (cutoff,))
                removed = store.db.execute("DELETE FROM runs WHERE finished<?", (cutoff,)).rowcount
                store.set_metadata("backup", {})
                store.set_metadata("maintenance", {"at": store.clock(), "removedRuns": removed, "retentionDays": retention_days})
                store.set_metadata("maintenanceError", None)
        finally:
            store.close()
        # A hard link installs atomically without ever replacing an existing state.
        os.link(temporary, destination)
        return {"state": str(destination), "interrupted": interrupted, "removedRuns": removed}
    finally:
        temporary.unlink(missing_ok=True)
