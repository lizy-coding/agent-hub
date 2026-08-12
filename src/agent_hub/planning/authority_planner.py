"""Use approved canonical targets only after exact delta comparison."""
import hashlib,json
from pathlib import Path
from agent_hub.planning.migration_planner import MigrationPlanner
from agent_hub.projects import api as registry_api
from agent_hub.schemas.models import MigrationDelta
class AuthorityPlanner(MigrationPlanner):
 def build_with_authority(self,requirement,target_repository,base,authority_path):
  authority=json.loads(Path(authority_path).read_text());tasks=[];comparisons=[];host=registry_api.get_repository(self.config,target_repository);manifest=(host.path/'pubspec.yaml').resolve()
  for item in authority['canonical_targets']:
   source=registry_api.get_development_unit(self.config,item['source_candidate']);target=registry_api.get_repository(self.config,item['canonical_repository'])
   if not source or not target:continue
   source_repo=registry_api.get_repository(self.config,source.repo_id);source_lib=(source_repo.path/source.relative_path/'lib').resolve();target_lib=(target.path/'lib').resolve()
   hashes=lambda base:{p.relative_to(base):hashlib.sha256(p.read_bytes()).hexdigest() for p in base.rglob('*.dart')}; identical=hashes(source_lib)==hashes(target_lib);comparisons.append({'source_unit':source.unit_id,'canonical_repository':target.repo_id,'lib_identity':'IDENTICAL_ALREADY_CANONICAL' if identical else 'DIVERGED','evidence':[str(source_lib),str(target_lib),str(manifest)]})
   old=f'path: {source.relative_path}'
   if not identical or old not in manifest.read_text():continue
   imports=[]
   for path in (host.path/'lib').rglob('*.dart'):
    for line,line_text in enumerate(path.read_text(encoding='utf-8').splitlines(),1):
     if f'package:{target.repo_id}/' in line_text:imports.append(f'{path.relative_to(self.config.workspace_root)}:{line}')
   if not imports:continue
   delta=MigrationDelta(capability_id=f'adoption:{source.unit_id}->{target.repo_id}',current_owner_repo=source.repo_id,current_owner_unit=source.unit_id,current_paths=[str(source_lib)],intended_owner_repo=target.repo_id,intended_owner_unit=f'{target.repo_id}: .',destination_paths=[str(target_lib)],consumer_paths=[x.rsplit(':',1)[0] for x in imports],dependency_delta=[f'{manifest}: {old} -> path: ../{target.repo_id}'],evidence_refs=imports+[str(manifest)],status='ADOPTION_ONLY')
   paths=[str(manifest)]+[str(self.config.workspace_root/x.rsplit(':',1)[0]) for x in imports]; node=type('Node',(),{'capability_id':delta.capability_id,'target_repo':target_repository})();assessment=type('Assessment',(),{'target_repo':target.repo_id,'target_unit':delta.intended_owner_unit})()
   dependency=self._task('adopt-dependency','Adopt approved canonical dependency','UPDATE_DEPENDENCY',node,assessment,delta,paths,risk='MEDIUM',validation=self._host_validation(target_repository)); integration=self._task('validate-host','Validate host adoption','VALIDATE_INTEGRATION',node,assessment,delta,paths,[dependency.task_id],risk='MEDIUM',validation=self._host_validation(target_repository));tasks.extend([dependency,integration])
  base.migration_tasks=tasks;base.dependency_dag={x.task_id:x.dependency_tasks for x in tasks};base.metrics['task_count']=len(tasks);base.source_analysis_ref['architecture_authority']=str(authority_path);base.source_analysis_ref['canonical_comparisons']=comparisons;base.status='READY_FOR_HUMAN_PLAN_REVIEW' if not self.validate_plan(base) else 'PLAN_STILL_INVALID';return base
