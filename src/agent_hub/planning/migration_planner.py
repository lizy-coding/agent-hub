"""Evidence-driven, read-only planning of real migration deltas only."""
from hashlib import sha256
from pathlib import Path

from agent_hub.capability.analyzer import CapabilityAnalyzer
from agent_hub.projects import api as registry_api
from agent_hub.schemas.models import BlockedItem, CapabilityAnalysis, ContextRule, MigrationDelta, MigrationPlan, MigrationTask
from agent_hub.tools.path_guard import is_allowed_business_path
from agent_hub.workspace.config import WorkspaceConfig

INVARIANTS=["application_orchestration_remains_in_application","WorkspaceSession/editor/navigation/dialog/application_lifecycle_coordination_not_auto_pluginized","adapter_is_application_integration_boundary","UNKNOWN_never_promoted_by_Planner","current_file_location_does_not_prove_future_owner","source_cleanup_occurs_only_after_replacement_and_validation","breaking_public_API_change_must_be_explicit","cross_repo_dependency_change_must_be_explicit_task"]
NON_CAPABILITY_SUFFIXES={'.md','.json','.yaml','.yml','.lock','.xcfilelist','.plist','.xib'}
NON_CAPABILITY_NAMES={'agents.md','agents.override.md','readme.md','pubspec.yaml','pubspec.lock','cmakelists.txt'}

class MigrationPlanner:
 def __init__(self,config:WorkspaceConfig): self.config=config; self.analyzer=CapabilityAnalyzer(config)
 def _analysis(self,requirement,target,provided): return provided if provided else self.analyzer.analyze_capabilities(requirement,target)
 def _absolute(self,item): return (self.config.workspace_root/item).resolve()
 def _migratable(self,node):
  return bool(node.files) and all(Path(path).name.lower() not in NON_CAPABILITY_NAMES and Path(path).suffix.lower() not in NON_CAPABILITY_SUFFIXES and '/test/' not in f'/{path}' and '/build/' not in f'/{path}' and '/.dart_tool/' not in f'/{path}' for path in node.files)
 def _rules(self,paths):
  result=[]; seen=set()
  # Registry records per-unit rules; add all ancestor control contracts and
  # ADR metadata in scope so current project rules reach frozen tasks.
  for raw in paths:
   path=Path(raw)
   if not is_allowed_business_path(path,self.config): continue
   for parent in (path,*path.parents):
    if parent == self.config.workspace_root.parent: break
    for name in ('AGENTS.md','AGENTS.override.md','CONTEXT.md','AI_PROJECT_CONTEXT.md','AI_ANALYSIS_SCHEMA.json','REFACTOR_PLAN.md'):
     candidate=parent/name
     if candidate.is_file() and is_allowed_business_path(candidate,self.config):
      key=str(candidate)
      if key not in seen: seen.add(key); result.append(ContextRule(path=str(candidate),scope=str(parent),applies_to=str(path),provenance='filesystem_rule_scope'))
    adr=parent/'docs'/'adr'
    if adr.is_dir():
     for candidate in adr.glob('*.md'):
      if is_allowed_business_path(candidate,self.config):
       key=str(candidate)
       if key not in seen: seen.add(key); result.append(ContextRule(path=str(candidate),scope=str(adr),applies_to=str(path),provenance='filesystem_rule_scope'))
  return result
 def _validation(self,*units):
  seen=set(); commands=[]
  for unit in units:
   if not unit: continue
   for command in registry_api.get_validation_commands(self.config,unit):
    key=(command.category,command.command,command.working_directory)
    if key not in seen: seen.add(key); commands.append(command)
  return commands
 def _host_validation(self,target_repo):
  repo=registry_api.get_repository(self.config,target_repo)
  return self._validation(*[unit.unit_id for unit in repo.development_units]) if repo else []
 def _delta(self,node,assessment):
  current=[str(self._absolute(Path(path))) for path in node.files]; source_unit=node.development_units[0] if len(node.development_units)==1 else None; target=assessment.target_unit
  if not source_unit or not target: return MigrationDelta(capability_id=node.capability_id,current_owner_repo=node.target_repo,current_owner_unit=source_unit,current_paths=current,intended_owner_repo=assessment.target_repo,intended_owner_unit=target,evidence_refs=node.evidence_refs,status='TARGET_AMBIGUOUS')
  if source_unit==target: return MigrationDelta(capability_id=node.capability_id,current_owner_repo=node.target_repo,current_owner_unit=source_unit,current_paths=current,intended_owner_repo=assessment.target_repo,intended_owner_unit=target,destination_paths=current,evidence_refs=node.evidence_refs,status='ALREADY_IN_TARGET')
  # The bounded analysis has not supplied a distinct destination file or caller.
  return MigrationDelta(capability_id=node.capability_id,current_owner_repo=node.target_repo,current_owner_unit=source_unit,current_paths=current,intended_owner_repo=assessment.target_repo,intended_owner_unit=target,evidence_refs=node.evidence_refs,status='TARGET_AMBIGUOUS')
 def _blocked(self,node,assessment,reason): return BlockedItem(capability_id=node.capability_id,reason=reason,missing_evidence=assessment.blockers or ['Distinct source-to-target delta, consumer callsite, and canonical target ownership evidence.'],prohibited_decisions=['MOVE_TO_EXISTING_UNIT','EXTEND_EXISTING_UNIT','REMOVE_OLD_IMPLEMENTATION'],evidence_refs=assessment.evidence_refs)
 def _task(self,key,title,action,node,assessment,delta,paths,deps=(),risk='MEDIUM',validation=()):
  paths=[str(Path(path).resolve()) for path in paths if is_allowed_business_path(Path(path),self.config)]
  rules=self._rules(paths)
  return MigrationTask(task_id=f'{node.capability_id}:{key}',title=title,action_type=action,source_repo=node.target_repo,target_repo=assessment.target_repo,source_units=[delta.current_owner_unit] if delta.current_owner_unit else [],target_units=[delta.intended_owner_unit] if delta.intended_owner_unit else [],allowed_paths=paths,context_refs=delta.evidence_refs,applicable_rules=rules,dependency_tasks=list(deps),preconditions=['Concrete, nonempty MigrationDelta remains valid.'],expected_changes=['Plan only: no business write is authorized.'],invariants=INVARIANTS,acceptance=['All paths and evidence are distinct and traceable.'],validation=list(validation),rollback_boundary='No P6.1 execution; reject or revise this task at human review.',risk='BLOCKED' if not rules else risk,status='PLANNED' if rules else 'BLOCKED',migration_delta=delta)
 def build_plan(self,requirement,target_repository,capability_analysis:CapabilityAnalysis|None=None,evidence_resolutions=()):
  analysis=self._analysis(requirement,target_repository,capability_analysis); nodes={n.capability_id:n for n in analysis.capabilities}; tasks=[]; blocked=[]
  for assessment in analysis.extraction_assessments:
   node=nodes[assessment.capability_id]
   if not self._migratable(node): continue
   if assessment.decision in ('KEEP_IN_APPLICATION','ADAPTER_ONLY'): continue
   if assessment.decision in ('UNKNOWN','NOT_ENOUGH_EVIDENCE','NEW_SHARED_CORE_CANDIDATE','NEW_PLUGIN_CANDIDATE'):
    blocked.append(self._blocked(node,assessment,f'extraction decision={assessment.decision}')); continue
   if assessment.decision not in ('MOVE_TO_EXISTING_UNIT','EXTEND_EXISTING_UNIT'): continue
   delta=self._delta(node,assessment)
   if delta.status in ('ALREADY_IN_TARGET','NO_MIGRATION_REQUIRED'): continue
   # A plan may not manufacture a target based on names/current location alone.
   blocked.append(self._blocked(node,assessment,f'Migration delta={delta.status}; no distinct canonical source/target/caller evidence.'))
  dag={task.task_id:task.dependency_tasks for task in tasks}; plan_id='migration-'+sha256((target_repository+'\n'+requirement).encode()).hexdigest()[:12]
  plan=MigrationPlan(plan_id=plan_id,requirement=requirement,target_repository=target_repository,source_analysis_ref={'requirement':analysis.requirement,'context_ref':analysis.context_ref,'metrics':analysis.metrics},architecture_invariants=INVARIANTS,migration_tasks=tasks,dependency_dag=dag,blocked_items=blocked,unknowns=analysis.unknowns,validation_strategy=self._host_validation(target_repository),risk_summary={'LOW':0,'MEDIUM':0,'HIGH':0,'BLOCKED':len(blocked)},metrics={'task_count':len(tasks),'blocked_count':len(blocked),'already_in_target_count':sum(self._delta(nodes[a.capability_id],a).status=='ALREADY_IN_TARGET' for a in analysis.extraction_assessments if a.capability_id in nodes and self._migratable(nodes[a.capability_id]))},status='READY_FOR_HUMAN_PLAN_REVIEW',evidence_resolutions=list(evidence_resolutions))
  errors=self.validate_plan(plan)
  if errors: plan.status='PLAN_STILL_INVALID'; plan.unknowns.extend(errors)
  return plan
 def validate_plan(self,plan):
  errors=[]; ids={task.task_id for task in plan.migration_tasks}
  if len(ids)!=len(plan.migration_tasks): errors.append('duplicate task ids')
  for task in plan.migration_tasks:
   delta=task.migration_delta
   if any(dep not in ids for dep in task.dependency_tasks): errors.append(f'missing dependency: {task.task_id}')
   if any(not is_allowed_business_path(Path(path),self.config) for path in task.allowed_paths): errors.append(f'out-of-bound path: {task.task_id}')
   if not delta or delta.status not in ('REAL_MIGRATION','EXTENSION_REQUIRED','ADOPTION_ONLY'): errors.append(f'nonempty delta required: {task.task_id}')
   if task.action_type.startswith('MOVE') and delta and delta.current_owner_unit==delta.intended_owner_unit: errors.append(f'self move: {task.task_id}')
   if task.action_type=='REMOVE_OLD_IMPLEMENTATION' and (not delta or set(delta.current_paths)&set(delta.destination_paths)): errors.append(f'cleanup overlaps target: {task.task_id}')
   if task.action_type=='UPDATE_CALLER' and (not delta or not delta.consumer_paths): errors.append(f'caller evidence missing: {task.task_id}')
   if task.action_type=='VALIDATE_INTEGRATION' and task.source_repo not in task.source_repo: errors.append(f'host validation missing: {task.task_id}')
   if task.status=='PLANNED' and not task.applicable_rules: errors.append(f'rules unresolved: {task.task_id}')
  visiting=set(); visited=set()
  def visit(task_id):
   if task_id in visiting:return True
   if task_id in visited:return False
   visiting.add(task_id); answer=any(visit(dep) for dep in plan.dependency_dag[task_id]); visiting.remove(task_id); visited.add(task_id); return answer
  if any(visit(task_id) for task_id in ids): errors.append('dependency cycle')
  return errors
