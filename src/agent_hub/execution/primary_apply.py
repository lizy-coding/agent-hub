"""Apply a reviewed, scope-limited Worker diff to the configured PRIMARY."""
from __future__ import annotations
import subprocess
import os
from datetime import UTC, datetime
from pathlib import Path

def _changed(root: Path) -> list[str]:
    tracked=subprocess.check_output(["git","diff","--name-only"],cwd=root,text=True).splitlines()
    untracked=subprocess.check_output(["git","ls-files","--others","--exclude-standard"],cwd=root,text=True).splitlines()
    return sorted(set(tracked+untracked))

def apply_approved(root: Path, task: dict[str, object], worker: dict[str, object]) -> dict[str, object]:
    allowed=set(task.get("allowed_paths",[])); base=str(task.get("base_revision",""))
    if worker.get("review")!="APPROVED" or worker.get("status") not in {"SUCCESS","READY_FOR_HUMAN_REVIEW"}:
        return {"status":"APPLY_REJECTED","reason":"review_not_approved"}
    if subprocess.check_output(["git","rev-parse","HEAD"],cwd=root,text=True).strip()!=base:
        return {"status":"APPLY_CONFLICT","reason":"base_revision_mismatch"}
    dirty=[p for p in _changed(root) if not p.startswith(".hermes/")]
    if dirty: return {"status":"PRIMARY_DIRTY","changed_files":dirty}
    diff=str(worker.get("diff", ""))
    if not diff: return {"status":"APPLY_REJECTED","reason":"approved_diff_missing"}
    check=subprocess.run(["git","apply","--check","--whitespace=nowarn","-"],cwd=root,input=diff,text=True,capture_output=True)
    if check.returncode: return {"status":"APPLY_CONFLICT","stderr":check.stderr[-2000:]}
    applied=subprocess.run(["git","apply","--whitespace=nowarn","-"],cwd=root,input=diff,text=True,capture_output=True)
    if applied.returncode: return {"status":"APPLY_CONFLICT","stderr":applied.stderr[-2000:]}
    changed=_changed(root); unauthorized=sorted(set(changed)-allowed-{p for p in changed if p.startswith(".hermes/")})
    if unauthorized: return {"status":"PRIMARY_SCOPE_VIOLATION","changed_files":changed,"unauthorized_files":unauthorized}
    dart=[p for p in changed if p.endswith(".dart")]
    if dart: subprocess.run(["dart","format",*dart],cwd=root,check=True,capture_output=True)
    analyze=subprocess.run(["flutter","analyze"],cwd=root,text=True,capture_output=True)
    if analyze.returncode: return {"status":"PRIMARY_VALIDATION_FAILED","changed_files":_changed(root),"validation":{"analyze":{"status":"FAIL","output":analyze.stdout[-2000:]+analyze.stderr[-2000:]}}}
    return {"status":"APPLIED","changed_files":_changed(root),"scope_guard":"PASS","validation":{"analyze":{"status":"PASS"}},"applied_to_primary":True}

def validate_applied(root: Path, task: dict[str, object]) -> dict[str, object]:
    changed=_changed(root); allowed=set(task.get("allowed_paths",[]))
    unauthorized=sorted(p for p in changed if p not in allowed and not p.startswith(".hermes/"))
    if unauthorized: return {"status":"PRIMARY_SCOPE_VIOLATION","changed_files":changed,"unauthorized_files":unauthorized}
    # Mirror the Worker-only topology repair for the declared sibling dev
    # dependency; this is outside the repository and never changes pubspec.
    target=(root / "../flutterguard").resolve()
    source=os.environ.get("AGENT_HUB_PATH_DEPENDENCY_FLUTTERGUARD")
    if source and Path(source).is_dir() and not target.exists(): target.symlink_to(Path(source).resolve(), target_is_directory=True)
    analyze=subprocess.run(["flutter","analyze"],cwd=root,text=True,capture_output=True)
    if analyze.returncode: return {"status":"PRIMARY_VALIDATION_FAILED","changed_files":changed,"validation":{"analyze":{"status":"FAIL","output":analyze.stdout[-2000:]+analyze.stderr[-2000:]}}}
    return {"status":"APPLIED","changed_files":changed,"scope_guard":"PASS","validation":{"analyze":{"status":"PASS"}},"applied_to_primary":True}

def commit_approved(root: Path, task: dict[str, object], worker: dict[str, object]) -> dict[str, object]:
    result=apply_approved(root,task,worker)
    if result.get("status") != "APPLIED": return result
    paths=list(task.get("allowed_paths", []))
    subprocess.run(["git","add","--",*paths],cwd=root,check=True,capture_output=True)
    subprocess.run(["git","add","-u","--",*{str(Path(path).parent) for path in paths}],cwd=root,check=True,capture_output=True)
    message=f"refactor: {task.get('task_id', 'approved task')} [{task.get('task_id', 'task')}]"
    committed=subprocess.run(["git","commit","--no-verify","-m",message],cwd=root,text=True,capture_output=True)
    if committed.returncode: return {"status":"COMMIT_FAILED","stderr":committed.stderr[-2000:],**result}
    return {"status":"COMMITTED","commit_hash":subprocess.check_output(["git","rev-parse","HEAD"],cwd=root,text=True).strip(),"committed_at":datetime.now(UTC).isoformat(),**result}
