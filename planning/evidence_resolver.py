"""Targeted, checkpointed evidence closure for P6.1 blocked capabilities."""
import hashlib, json, os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from agent_hub.planning.migration_planner import NON_CAPABILITY_NAMES, NON_CAPABILITY_SUFFIXES
from agent_hub.projects import api as registry_api
from agent_hub.schemas.models import CapabilityResolution, ContextRule, MigrationDelta
from agent_hub.tools.path_guard import is_allowed_business_path
from agent_hub.workspace.config import WorkspaceConfig

def _now(): return datetime.now(timezone.utc).isoformat()
def _digest(value): return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
def _atomic(path,value):
 path.parent.mkdir(parents=True,exist_ok=True); temp=path.with_name('.'+path.name+'.'+uuid4().hex+'.tmp')
 with temp.open('w',encoding='utf-8') as out: json.dump(value,out,ensure_ascii=False,indent=2);out.write('\n');out.flush();os.fsync(out.fileno())
 temp.replace(path)

class MigrationEvidenceResolver:
 def __init__(self,config:WorkspaceConfig,run_root:Path): self.config=config;self.run_root=run_root
 def _artifact(self,path):
  p=Path(path);return p.name.lower() in NON_CAPABILITY_NAMES or p.suffix.lower() in NON_CAPABILITY_SUFFIXES or any(x in p.parts for x in ('test','build','.dart_tool','ephemeral'))
 def _rules(self,path):
  rules=[];seen=set();path=Path(path)
  for parent in (path,*path.parents):
   if parent==self.config.workspace_root.parent:break
   for name in ('AGENTS.md','AGENTS.override.md'):
    rule=parent/name
    if rule.is_file() and is_allowed_business_path(rule,self.config) and str(rule) not in seen:seen.add(str(rule));rules.append(ContextRule(path=str(rule),scope=str(parent),applies_to=str(path),provenance='filesystem_rule_scope'))
  return rules
 def _unit_for(self,path): return registry_api.find_unit_by_path(self.config,Path(path))
 def resolve(self,blocked):
  evidence=[ref for ref in blocked.evidence_refs if ':' in ref]
  source_refs=[ref for ref in evidence if Path(ref.rsplit(':',1)[0]).suffix]
  source_paths=[str((self.config.workspace_root/ref.rsplit(':',1)[0]).resolve()) for ref in source_refs]
  source_paths=[p for p in source_paths if is_allowed_business_path(Path(p),self.config)]
  primary=source_paths[0] if source_paths else None;unit=self._unit_for(primary) if primary else None
  if not primary or self._artifact(primary):
   return CapabilityResolution(capability_id=blocked.capability_id,prior_block_reason=blocked.reason,terminal_state='NO_MIGRATION_REQUIRED',source_paths=source_paths,missing_evidence=['Artifact is context only, not a migratable capability.'],confidence='HIGH',evidence_refs=blocked.evidence_refs)
  text=Path(primary).read_text(encoding='utf-8',errors='ignore')[:16000]; symbol=Path(primary).stem
  imports=[]; calls=[]
  # Restrict exact evidence lookup to the owner unit and one-hop dependents.
  candidates=[unit] if unit else []
  if unit:
   for edge in registry_api.get_dependents(self.config,unit.unit_id)+registry_api.get_dependencies(self.config,unit.unit_id):
    other=registry_api.get_development_unit(self.config,edge.source if edge.target==unit.unit_id else edge.target)
    if other and other not in candidates:candidates.append(other)
  for candidate in candidates:
   repo=registry_api.get_repository(self.config,candidate.repo_id);base=(repo.path/candidate.relative_path).resolve()
   for path in base.rglob('*.dart'):
    if path==Path(primary) or not is_allowed_business_path(path,self.config) or any(x in path.parts for x in ('build','.dart_tool','.git')):continue
    try: lines=path.read_text(encoding='utf-8').splitlines()
    except UnicodeDecodeError:continue
    for number,line in enumerate(lines,1):
     if symbol in line and ('import ' in line or f'{symbol}(' in line):
      ref=f'{path.relative_to(self.config.workspace_root)}:{number}';(imports if 'import ' in line else calls).append(ref);break
  owner_unit=unit.unit_id if unit else None; owner_repo=unit.repo_id if unit else None
  rules=self._rules(primary); validation=registry_api.get_validation_commands(self.config,owner_unit) if owner_unit else []
  state='NOT_ENOUGH_EVIDENCE';missing=['No independent canonical target and distinct destination delta established.'];confidence='LOW'
  if 'UNKNOWN' in blocked.reason: state='HUMAN_DECISION_REQUIRED';missing=['Architecture ownership is UNKNOWN; source evidence cannot select a future boundary.'];confidence='LOW'
  if imports or calls: confidence='MEDIUM'
  return CapabilityResolution(capability_id=blocked.capability_id,prior_block_reason=blocked.reason,terminal_state=state,current_owner_repo=owner_repo,current_owner_unit=owner_unit,source_paths=source_paths,consumer_paths=[x.rsplit(':',1)[0] for x in calls],public_contract_paths=[],dependency_evidence=[x for x in blocked.evidence_refs if 'pubspec' in x],callsite_evidence=calls+imports,applicable_rules=rules,validation_evidence=validation,migration_delta=MigrationDelta(capability_id=blocked.capability_id,current_owner_repo=owner_repo or 'unknown',current_owner_unit=owner_unit,current_paths=source_paths,evidence_refs=blocked.evidence_refs,status='BLOCKED'),missing_evidence=missing,confidence=confidence,evidence_refs=blocked.evidence_refs)
 def resolve_all(self,blocked_items):
  run_id='p6-2-'+_digest([x.model_dump(mode='json') for x in blocked_items])[:12];root=self.run_root/run_id;results=[]
  for blocked in blocked_items:
   path=root/(hashlib.sha256(blocked.capability_id.encode()).hexdigest()[:16]+'.json')
   if path.exists():
    try: results.append(CapabilityResolution.model_validate(json.loads(path.read_text())));continue
    except (json.JSONDecodeError,ValueError):pass
   record=self.resolve(blocked);_atomic(path,record.model_dump(mode='json'));results.append(record)
  return run_id,results
