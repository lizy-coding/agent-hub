"""Apply human ArchitectureAuthority without bypassing physical delta checks."""
import hashlib,json
from pathlib import Path
from agent_hub.planning.migration_planner import MigrationPlanner
from agent_hub.projects import api as registry_api
from agent_hub.schemas.models import MigrationDelta,MigrationTask

class AuthorityPlanner(MigrationPlanner):
 def build_with_authority(self,requirement,target_repository,base_plan,authority_path):
  authority=json.loads(Path(authority_path).read_text()); tasks=[]; comparisons=[]
  host=registry_api.get_repository(self.config,target_repository)
  host_manifest=(host.path/'pubspec.yaml').resolve()
  for item in authority['canonical_targets']:
   source=registry_api.get_development_unit(self.config,item['source_candidate']); target_repo=registry_api.get_repository(self.config,item['canonical_repository'])
   if not source or not target_repo: continue
   source_repo=registry_api.get_repository(self.config,source.repo_id); source_lib=(source_repo.path/source.relative_path/'lib').resolve(); target_lib=(target_repo.path/'lib').resolve()
   source_files={p.relative_to(source_lib):hashlib.sha256(p.read_bytes()).hexdigest() for p in source_lib.rglob('*.dart')}; target_files={p.relative_to(target_lib):hashlib.sha256(p.read_bytes()).hexdigest() for p in target_lib.rglob('*.dart')}
   identical=source_files==target_files
   comparison={'source_unit':source.unit_id,'canonical_repository':target_repo.repo_id,'lib_identity':'IDENTICAL_ALREADY_CANONICAL' if identical else 'DIVERGED','source_file_count':len(source_files),'target_file_count':len(target_files),'evidence':[str(source_lib),str(target_lib),str(host_manifest)]};comparisons.append(comparison)
   if not identical: continue
   manifest=host_manifest.read_text(); old=f'path: {source.relative_path}'
   if old not in manifest: continue
   # Host already has exact imports of the public package API; switching its
   # dependency is a distinct, reversible adoption delta, not a source move.
   imports=[]
   package=target_repo.repo_id
   for path in (host.path/'lib').rglob('*.dart'):
    for n,line in enumerate(path.read_text(encoding='utf-8').splitlines(),1):
     if f'package:{package}/' in line: imports.append(f'{path.relative_to(self.config.workspace_root)}:{n}')
   if not imports: continue
   delta=MigrationDelta(capability_id=f'adoption:{source.unit_id}->{target_repo.repo_id}',current_owner_repo=source.repo_id,current_owner_unit=source.unit_id,current_paths=[str(source_lib)],intended_owner_repo=target_repo.repo_id,intended_owner_unit=f'{target_repo.repo_id}: .',destination_paths=[str(target_lib)],consumer_paths=[x.rsplit(':',1)[0] for x in imports],dependency_delta=[f'{host_manifest}: {old} -> path: ../{target_repo.repo_id}'],evidence_refs=imports+[str(host_manifest)],status='ADOPTION_ONLY')
   paths=[str(host_manifest)]+[str(self.config.workspace_root/x.rsplit(':',1)[0]) for x in imports]
   dep=self._task('adopt-dependency','Adopt approved canonical dependency','UPDATE_DEPENDENCY',type('Node',(),{'capability_id':delta.capability_id,'target_repo':target_repository})(),type('Assessment',(),{'target_repo':target_repo.repo_id,'target_unit':delta.intended_owner_unit})(),delta,paths,risk='MEDIUM',validation=self._host_validation(target_repository))
   caller=self._task('validate-host','Validate host adoption','VALIDATE_INTEGRATION',type('Node',(),{'capability_id':delta.capability_id,'target_repo':target_repository})(),type('Assessment',(),{'target_repo':target_repo.repo_id,'target_unit':delta.intended_owner_unit})(),delta,paths,[dep.task_id],risk='MEDIUM',validation=self._host_validation(target_repository))
   tasks.extend([dep,caller])
  base_plan.migration_tasks=tasks;base_plan.dependency_dag={x.task_id:x.dependency_tasks for x in tasks};base_plan.metrics['task_count']=len(tasks);base_plan.source_analysis_ref['architecture_authority']=str(authority_path);base_plan.source_analysis_ref['canonical_comparisons']=comparisons
  base_plan.status='READY_FOR_HUMAN_PLAN_REVIEW' if not self.validate_plan(base_plan) else 'PLAN_STILL_INVALID';return base_plan
