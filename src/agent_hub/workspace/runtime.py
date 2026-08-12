"""Stable repository identity mapped to an ephemeral runtime checkout path."""
import os
from datetime import datetime, timezone
from pathlib import Path
from agent_hub.schemas.models import ProjectSource, RuntimeRepository, RuntimeWorkspace

class RuntimeWorkspaceProvider:
 def __init__(self,workspace):self.workspace=workspace
 @classmethod
 def from_config(cls,config):
  payload=config.runtime or {}; env=os.environ.get('AGENT_HUB_RUNTIME_ENV',payload.get('environment','LOCAL')); root=Path(os.environ.get('AGENT_HUB_WORKSPACE_ROOT',payload.get('runtime_root',config.workspace_root))).resolve(); checkout=Path(os.environ.get('AGENT_HUB_CHECKOUT_ROOT',payload.get('checkout_root',root))).resolve(); primary=os.environ.get('AGENT_HUB_PRIMARY_REPOSITORY',payload.get('primary_repository_id','flutter_study')); repositories=[]
  for repository_id,entry in payload.get('repositories',{}).items():
   path=Path(entry.get('runtime_path',checkout/repository_id)).resolve(); source=ProjectSource(repository_id=repository_id,source_type=entry.get('source_type','PRECHECKED_OUT'),source_locator=entry.get('source_locator',str(path)),revision=entry.get('revision'),checkout_policy=entry.get('checkout_policy','PRECHECKED_OUT'),managed=entry.get('managed',False)); repositories.append(RuntimeRepository(repository_id=repository_id,runtime_path=path,source=source,revision=entry.get('revision'),role=entry.get('role','REFERENCE'),managed=entry.get('managed',False),writable=entry.get('writable',False),development_units=entry.get('development_units',[])))
  if not repositories: repositories=[RuntimeRepository(repository_id=primary,runtime_path=(root/primary).resolve(),source=ProjectSource(repository_id=primary,source_type='LOCAL_PATH',source_locator=str(root/primary),managed=True),role='PRIMARY',managed=True,writable=True)]
  return cls(RuntimeWorkspace(runtime_id=payload.get('runtime_id',f'{env.lower()}-runtime'),runtime_root=root,checkout_root=checkout,repositories=repositories,primary_repository_id=primary,environment=env,created_at=datetime.now(timezone.utc).isoformat()))
 def get_repository(self,repository_id): return next((x for x in self.workspace.repositories if x.repository_id==repository_id),None)
 def get_primary_repository(self): return self.get_repository(self.workspace.primary_repository_id)
 def resolve_path(self,repository_id,relative_path):
  repository=self.get_repository(repository_id)
  if not repository: raise KeyError(repository_id)
  path=(repository.runtime_path/relative_path).resolve()
  if repository.runtime_path not in (path,*path.parents): raise ValueError('runtime path escape')
  return path
 def assert_readable(self,repository_id,relative_path):
  path=self.resolve_path(repository_id,relative_path)
  if not path.exists(): raise FileNotFoundError(path)
  return path
 def assert_writable(self,repository_id,relative_path):
  repository=self.get_repository(repository_id)
  if not repository or not repository.managed or not repository.writable: raise PermissionError(f'repository is read-only: {repository_id}')
  return self.resolve_path(repository_id,relative_path)

class LocalPathMaterializer:
 def materialize(self,source,checkout_root):
  path=Path(source.source_locator).resolve()
  if not path.is_dir(): raise FileNotFoundError(path)
  return path
class PrecheckedOutMaterializer(LocalPathMaterializer): pass
class GitMaterializer:
 def materialize(self,source,checkout_root): raise RuntimeError('Git materialization requires separately configured credentials and remote')
