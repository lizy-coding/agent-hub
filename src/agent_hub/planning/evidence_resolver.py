"""Targeted, checkpointed evidence closure for P6.1 blocked capabilities."""
import hashlib,json,os
from datetime import datetime,timezone
from pathlib import Path
from uuid import uuid4
from agent_hub.planning.migration_planner import NON_CAPABILITY_NAMES,NON_CAPABILITY_SUFFIXES
from agent_hub.projects import api as registry_api
from agent_hub.schemas.models import CapabilityResolution,ContextRule,MigrationDelta
from agent_hub.tools.path_guard import is_allowed_business_path
from agent_hub.workspace.config import WorkspaceConfig
def _digest(x):return hashlib.sha256(json.dumps(x,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
def _atomic(path,value):
 path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_name('.'+path.name+'.'+uuid4().hex+'.tmp')
 with tmp.open('w',encoding='utf-8') as out:json.dump(value,out,ensure_ascii=False,indent=2);out.write('\n');out.flush();os.fsync(out.fileno())
 tmp.replace(path)
class MigrationEvidenceResolver:
 def __init__(self,config,run_root):self.config=config;self.run_root=run_root
 def _artifact(self,path):
  p=Path(path);return p.name.lower() in NON_CAPABILITY_NAMES or p.suffix.lower() in NON_CAPABILITY_SUFFIXES or any(x in p.parts for x in ('test','build','.dart_tool','ephemeral'))
 def _rules(self,path):
  out=[];seen=set();path=Path(path)
  for parent in (path,*path.parents):
   if parent==self.config.workspace_root.parent:break
   for name in ('AGENTS.md','AGENTS.override.md'):
    rule=parent/name
    if rule.is_file() and is_allowed_business_path(rule,self.config) and str(rule) not in seen:seen.add(str(rule));out.append(ContextRule(path=str(rule),scope=str(parent),applies_to=str(path),provenance='filesystem_rule_scope'))
  return out
 def resolve(self,blocked):
  refs=[x for x in blocked.evidence_refs if ':' in x];paths=[str((self.config.workspace_root/x.rsplit(':',1)[0]).resolve()) for x in refs if Path(x.rsplit(':',1)[0]).suffix];paths=[x for x in paths if is_allowed_business_path(Path(x),self.config)];primary=paths[0] if paths else None;unit=registry_api.find_unit_by_path(self.config,Path(primary)) if primary else None
  if not primary or self._artifact(primary):return CapabilityResolution(capability_id=blocked.capability_id,prior_block_reason=blocked.reason,terminal_state='NO_MIGRATION_REQUIRED',source_paths=paths,missing_evidence=['Artifact is context only, not a migratable capability.'],confidence='HIGH',evidence_refs=blocked.evidence_refs)
  symbol=Path(primary).stem;calls=[];candidates=[unit] if unit else []
  if unit:
   for edge in registry_api.get_dependents(self.config,unit.unit_id)+registry_api.get_dependencies(self.config,unit.unit_id):
    other=registry_api.get_development_unit(self.config,edge.source if edge.target==unit.unit_id else edge.target)
    if other and other not in candidates:candidates.append(other)
  for candidate in candidates:
   repo=registry_api.get_repository(self.config,candidate.repo_id)
   for path in (repo.path/candidate.relative_path).rglob('*.dart'):
    if path==Path(primary) or not is_allowed_business_path(path,self.config) or any(x in path.parts for x in ('build','.dart_tool','.git')):continue
    try:lines=path.read_text(encoding='utf-8').splitlines()
    except UnicodeDecodeError:continue
    for no,line in enumerate(lines,1):
     if symbol in line and ('import ' in line or f'{symbol}(' in line):calls.append(f'{path.relative_to(self.config.workspace_root)}:{no}');break
  state='HUMAN_DECISION_REQUIRED' if 'UNKNOWN' in blocked.reason else 'NOT_ENOUGH_EVIDENCE';missing=['Architecture ownership is UNKNOWN; source evidence cannot select a future boundary.'] if state=='HUMAN_DECISION_REQUIRED' else ['No independent canonical target and distinct destination delta established.']
  return CapabilityResolution(capability_id=blocked.capability_id,prior_block_reason=blocked.reason,terminal_state=state,current_owner_repo=unit.repo_id if unit else None,current_owner_unit=unit.unit_id if unit else None,source_paths=paths,consumer_paths=[x.rsplit(':',1)[0] for x in calls],dependency_evidence=[x for x in blocked.evidence_refs if 'pubspec' in x],callsite_evidence=calls,applicable_rules=self._rules(primary),validation_evidence=registry_api.get_validation_commands(self.config,unit.unit_id) if unit else [],migration_delta=MigrationDelta(capability_id=blocked.capability_id,current_owner_repo=unit.repo_id if unit else 'unknown',current_owner_unit=unit.unit_id if unit else None,current_paths=paths,evidence_refs=blocked.evidence_refs,status='BLOCKED'),missing_evidence=missing,confidence='MEDIUM' if calls else 'LOW',evidence_refs=blocked.evidence_refs)
 def resolve_all(self,items):
  run='p6-2-'+_digest([x.model_dump(mode='json') for x in items])[:12];out=[]
  for item in items:
   path=self.run_root/run/(hashlib.sha256(item.capability_id.encode()).hexdigest()[:16]+'.json')
   if path.exists():
    try:out.append(CapabilityResolution.model_validate(json.loads(path.read_text())));continue
    except (ValueError,json.JSONDecodeError):pass
   resolution=self.resolve(item);_atomic(path,resolution.model_dump(mode='json'));out.append(resolution)
  return run,out
