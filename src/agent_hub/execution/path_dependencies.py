"""Preflight all local path dependencies before a scoped pilot mutation."""
from pathlib import Path
import yaml

class RelativePathDependencyAvailabilityGuard:
 def inspect(self,worktree,approved_name=None):
  root=Path(worktree).resolve();data=yaml.safe_load((root/'pubspec.yaml').read_text());out=[]
  for section in ('dependencies','dev_dependencies'):
   for name,value in (data.get(section) or {}).items():
    if not isinstance(value,dict) or 'path' not in value:continue
    resolved=(root/value['path']).resolve();manifest=resolved/'pubspec.yaml';identity=None
    if manifest.exists(): identity=yaml.safe_load(manifest.read_text()).get('name')
    out.append({'dependency_name':name,'declared_path':value['path'],'resolved_path':str(resolved),'realpath':str(resolved),'exists':manifest.exists(),'package_identity':identity,'role':'MIGRATION_TARGET' if name==approved_name else 'EXISTING_PREREQUISITE'})
  return out
