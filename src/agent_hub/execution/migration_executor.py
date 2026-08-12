"""Guarded executor primitives; business changes remain limited to a worktree."""
import subprocess
from pathlib import Path

class ScopeGuard:
 def __init__(self,worktree,allowed): self.worktree=Path(worktree).resolve();self.allowed={Path(x).resolve() for x in allowed}
 def verify_diff(self):
  changed=subprocess.check_output(['git','status','--porcelain'],cwd=self.worktree,text=True).splitlines();paths={self.worktree/line[3:] for line in changed}
  return [],[str(path) for path in paths if path.resolve() not in self.allowed]
class WorktreeManager:
 def __init__(self,worktree,canonical):self.worktree=Path(worktree).resolve();self.canonical=Path(canonical).resolve()
 def canonical_relative_ok(self): return (self.worktree/'../gcode_core').resolve()==self.canonical
class ValidationRunner:
 def run(self,command,cwd):
  done=subprocess.run(command,cwd=cwd,shell=True,text=True,capture_output=True)
  return {'command':command,'exit_code':done.returncode,'stdout':done.stdout,'stderr':done.stderr}
class MigrationExecutor:
 def __init__(self,worktree,allowed,canonical):self.scope=ScopeGuard(worktree,allowed);self.worktree=WorktreeManager(worktree,canonical);self.validation=ValidationRunner()
 def verify(self):
  allowed,forbidden=self.scope.verify_diff()
  return {'canonical_relative_ok':self.worktree.canonical_relative_ok(),'allowed_changes':allowed,'forbidden_changes':forbidden,'scope_ok':not forbidden}
