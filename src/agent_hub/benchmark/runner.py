"""Independent scoring plus resumable orchestration for bounded benchmarks."""
import hashlib
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from agent_hub.capability.analyzer import CapabilityAnalyzer
from agent_hub.context.resolver import ContextLimits, ContextResolver
from agent_hub.workspace.config import WorkspaceConfig


def _now(): return datetime.now(timezone.utc).isoformat()
def _hash_file(path: Path): return hashlib.sha256(path.read_bytes()).hexdigest()
def _hash_value(value): return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
def _atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n"); handle.flush(); os.fsync(handle.fileno())
    temporary.replace(path)


class ShadowBenchmarkRunner:
 def __init__(self,config:WorkspaceConfig,scenario_path:Path|None=None):
  self.config=config; self.context=ContextResolver(config); self.capability=CapabilityAnalyzer(config); self.scenario_path=scenario_path or Path(__file__).resolve().parents[3]/'benchmarks/shadow_cases/cases.json'; self.results=[]
 def load_scenarios(self): return json.loads(self.scenario_path.read_text())
 def load_reviewed_goldens(self):
  root=self.scenario_path.parents[1]/'architecture_goldens'; candidates={x['id']:x for x in json.loads((root/'candidates.json').read_text())}; decisions=json.loads((root/'review-decisions.json').read_text())
  return [(candidates[x['id']],x) for x in decisions if x['state'].startswith('approved') and x['accepted_ownership']]
 def run_shadow_case(self,scenario):
  limits=ContextLimits(**scenario['limits']); context=self.context.resolve_context(scenario['requirement'],scenario['target_repository'],limits); analysis=self.capability.analyze_capabilities(scenario['requirement'],scenario['target_repository']); result=self.score_shadow_case(scenario,context,analysis); self.results.append(result); return result
 def score_shadow_case(self,scenario,context,analysis):
  expected=scenario['expected']; repos=set(context.scope['repositories']); required=set(expected['repositories']['must_include']); predicted=set(context.scope['repositories']); required_paths=expected['evidence']['require_paths']; refs=[edge.evidence.path for edge in context.dependencies]+[ref.split(':')[0] for c in context.candidates for ref in c.evidence_refs]; rules=[rule.path for rule in context.rules]; unknown_ok=len(context.unknowns)>=expected['unknowns']['minimum_expected']; negative=scenario['category']=='negative'; unsupported=negative and bool(context.symbols)
  return {'id':scenario['id'],'passed':required.issubset(repos) and all(path in refs or any(path in file.relative_path for file in context.files) for path in required_paths) and set(expected['rules']['must_include']).issubset(rules) and unknown_ok and not unsupported,'repository_precision':len(required&predicted)/len(predicted) if predicted else None,'repository_recall':len(required&predicted)/len(required) if required else None,'evidence_coverage':sum(1 for path in required_paths if path in refs or any(path in file.relative_path for file in context.files))/len(required_paths) if required_paths else None,'rule_coverage':sum(1 for rule in expected['rules']['must_include'] if rule in rules)/len(expected['rules']['must_include']) if expected['rules']['must_include'] else None,'unknown_preservation':1.0 if unknown_ok else 0.0,'false_positive':1 if unsupported else 0,'metrics':context.metrics,'failures':([] if required.issubset(repos) else ['required repository missing'])+([] if not unsupported else ['negative case returned exact symbol evidence']),'review_state':scenario['review_state']}
 def score_golden_case(self,candidate,truth):
  analysis=self.capability.analyze_capabilities(candidate['title']+' '+candidate['capability_scope'],candidate['target_repository']); evidence=set(candidate['evidence']['files']); ranked=sorted(analysis.capabilities,key=lambda node:len(evidence & set(node.files)),reverse=True); node=ranked[0] if ranked and evidence & set(ranked[0].files) else None; prediction=node.ownership if node else 'UNKNOWN'; assessment=next((x for x in analysis.extraction_assessments if node and x.capability_id==node.capability_id),None); extraction=assessment.decision if assessment else 'UNKNOWN'; target=assessment.target_unit if assessment else None; accepted_ownership=truth['accepted_ownership']; accepted_extraction=truth['accepted_extraction']; promotion=accepted_extraction=='UNKNOWN' and extraction not in ('UNKNOWN','NOT_ENOUGH_EVIDENCE')
  return {'id':truth['id'],'predicted_ownership':prediction,'accepted_ownership':accepted_ownership,'ownership_match':prediction==accepted_ownership,'predicted_extraction':extraction,'accepted_extraction':accepted_extraction,'extraction_match':extraction==accepted_extraction,'predicted_target_unit':target,'accepted_target_unit':candidate['proposed_extraction'].get('target_unit'),'target_scored':accepted_extraction in ('MOVE_TO_EXISTING_UNIT','EXTEND_EXISTING_UNIT') and bool(candidate['proposed_extraction'].get('target_unit')),'target_match':target==candidate['proposed_extraction'].get('target_unit') if accepted_extraction in ('MOVE_TO_EXISTING_UNIT','EXTEND_EXISTING_UNIT') else None,'unsupported_promotion':promotion,'evidence_used':node.evidence_refs if node else [],'failure_classification':'clustering' if node is None else 'ownership' if prediction!=accepted_ownership else 'extraction' if extraction!=accepted_extraction else None}
 def run_shadow_suite(self): self.results=[]; [self.run_shadow_case(x) for x in self.load_scenarios()]; return self.get_shadow_metrics()
 def get_shadow_metrics(self):
  vals=lambda name:[r[name] for r in self.results if r[name] is not None]; average=lambda name:sum(vals(name))/len(vals(name)) if vals(name) else None; architecture=self.score_reviewed_architecture(); ready=all(x['passed'] for x in self.results) and architecture['ownership_accuracy']>=.85 and architecture['extraction_accuracy']>=.80 and architecture['unsupported_promotions']==0
  return {'cases':self.results,'repository_precision':average('repository_precision'),'repository_recall':average('repository_recall'),'evidence_coverage':average('evidence_coverage'),'rule_coverage':average('rule_coverage'),'unknown_preservation':average('unknown_preservation'),'false_positive_rate':sum(r['false_positive'] for r in self.results)/len(self.results) if self.results else None,'architecture':architecture,'readiness':'READY_FOR_MIGRATION_PLANNER' if ready else 'READY_FOR_ANALYZER_CALIBRATION'}
 def score_reviewed_architecture(self):
  rows=[self.score_golden_case(candidate,truth) for candidate,truth in self.load_reviewed_goldens()]; avg=lambda values:sum(values)/len(values) if values else None
  return {'goldens':rows,'ownership_accuracy':avg([x['ownership_match'] for x in rows]),'extraction_accuracy':avg([x['extraction_match'] for x in rows]),'extraction_target_accuracy':avg([x['target_match'] for x in rows if x['target_scored']]),'unsupported_promotions':sum(x['unsupported_promotion'] for x in rows),'architecture_disagreement_count':sum(not x['ownership_match'] or not x['extraction_match'] for x in rows)}
 def validate_benchmark_result(self,metrics):
  errors=[]
  if len(metrics['cases'])<6: errors.append('fewer than six cases')
  if any(not r['passed'] for r in metrics['cases']): errors.append('scenario assertion failure')
  if any(r['false_positive'] for r in metrics['cases']): errors.append('unsupported fact promotion')
  if metrics['architecture']['unsupported_promotions']: errors.append('unsupported architecture promotion')
  return errors


class ResumableShadowBenchmark:
 """Checkpoint orchestration; scoring stays entirely in ShadowBenchmarkRunner."""
 def __init__(self, runner: ShadowBenchmarkRunner): self.runner=runner; self.root=runner.scenario_path.parents[1]; self.runs=self.root/'runs'
 def identity(self):
  source=Path(__file__).resolve(); project=source.parents[3]; config=self.runner.config
  revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=project,text=True).strip()
  case_ids=[x['id'] for x in self.runner.load_scenarios()]+[truth['id'] for _,truth in self.runner.load_reviewed_goldens()]
  registry=Path(config.registry_path)
  return {'stage':'P5.6.1','source_revision':revision,'analyzer_source_hash':_hash_file(project/'src/agent_hub/capability/analyzer.py'),'resolver_source_hash':_hash_file(project/'src/agent_hub/context/resolver.py'),'benchmark_source_hash':_hash_file(source),'benchmark_config_hash':_hash_file(self.runner.scenario_path),'candidates_hash':_hash_file(self.root/'architecture_goldens/candidates.json'),'review_decisions_hash':_hash_file(self.root/'architecture_goldens/review-decisions.json'),'registry_snapshot_identity':_hash_file(registry) if registry.exists() else 'missing','case_ids':case_ids}
 def _valid_manifest(self,path,identity):
  try: manifest=json.loads(path.read_text()); return manifest if all(manifest.get(k)==v for k,v in identity.items()) and manifest.get('status') in ('RUNNING','COMPLETE') else None
  except (OSError,json.JSONDecodeError): return None
 def load_or_create(self):
  identity=self.identity(); self.runs.mkdir(parents=True,exist_ok=True); valid=[]
  for manifest_path in self.runs.glob('*/manifest.json'):
   manifest=self._valid_manifest(manifest_path,identity)
   if manifest: valid.append((manifest_path.parent,manifest))
   else:
    try:
     old=json.loads(manifest_path.read_text()); old['status']='INVALIDATED'; _atomic_json(manifest_path,old)
    except (OSError,json.JSONDecodeError): pass
  if valid: return sorted(valid,key=lambda item:item[1]['created_at'])[-1][0],sorted(valid,key=lambda item:item[1]['created_at'])[-1][1],False
  run_id=f"p5-6-1-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"; directory=self.runs/run_id; manifest={'run_id':run_id,'created_at':_now(),'status':'RUNNING',**identity}; _atomic_json(directory/'manifest.json',manifest); return directory,manifest,True
 def _case_input(self,case_id):
  for item in self.runner.load_scenarios():
   if item['id']==case_id: return item
  for candidate,truth in self.runner.load_reviewed_goldens():
   if truth['id']==case_id: return {'candidate':candidate,'truth':truth}
  raise KeyError(case_id)
 def _valid_case(self,path,run_id,input_identity):
  try:
   case=json.loads(path.read_text()); expected=case.pop('result_hash',None); return case if case.get('status')=='COMPLETE' and case.get('run_id')==run_id and case.get('input_identity')==input_identity and expected==_hash_value(case) else None
  except (OSError,json.JSONDecodeError): return None
 def run(self):
  directory,manifest,created=self.load_or_create(); executed=skipped=0; results={}; records={}
  for case_id in manifest['case_ids']:
   payload=self._case_input(case_id); input_identity=_hash_value(payload); case_path=directory/'cases'/f'{case_id}.json'; existing=self._valid_case(case_path,manifest['run_id'],input_identity)
   if existing: results[case_id]=existing['prediction']; records[case_id]=existing; skipped+=1; continue
   started=_now(); began=time.monotonic()
   try:
    prediction=self.runner.run_shadow_case(payload) if case_id.startswith('SHADOW_') else self.runner.score_golden_case(payload['candidate'],payload['truth'])
    case={'run_id':manifest['run_id'],'case_id':case_id,'status':'COMPLETE','started_at':started,'completed_at':_now(),'duration_seconds':round(time.monotonic()-began,3),'input_identity':input_identity,'prediction':prediction,'truth_assertions':payload.get('expected',payload.get('truth',{})),'metrics':prediction.get('metrics',{}),'evidence_refs':prediction.get('evidence_used',[]),'failures':prediction.get('failures',[])}
   except Exception as error:
    case={'run_id':manifest['run_id'],'case_id':case_id,'status':'FAILED','started_at':started,'completed_at':_now(),'duration_seconds':round(time.monotonic()-began,3),'input_identity':input_identity,'prediction':None,'truth_assertions':payload.get('expected',payload.get('truth',{})),'metrics':{},'evidence_refs':[],'failures':[f'{type(error).__name__}: {error}']}
   case['result_hash']=_hash_value(case); _atomic_json(case_path,case); results[case_id]=case['prediction']; records[case_id]=case; executed+=1
  cases=[results[case_id] for case_id in manifest['case_ids'] if case_id.startswith('SHADOW_')]; goldens=[results[case_id] for case_id in manifest['case_ids'] if case_id.startswith('GOLDEN_')]
  if any(x is None for x in cases+goldens): manifest['status']='FAILED'; _atomic_json(directory/'manifest.json',manifest); return {'complete':False,'run_id':manifest['run_id'],'executed':executed,'skipped':skipped}
  vals=lambda name:[r[name] for r in cases if r[name] is not None]; avg=lambda name:sum(vals(name))/len(vals(name)) if vals(name) else None; scored_targets=[x for x in goldens if x['target_scored']]; architecture={'goldens':goldens,'ownership_accuracy':sum(x['ownership_match'] for x in goldens)/len(goldens),'extraction_accuracy':sum(x['extraction_match'] for x in goldens)/len(goldens),'extraction_target_accuracy':sum(x['target_match'] for x in scored_targets)/len(scored_targets) if scored_targets else None,'unsupported_promotions':sum(x['unsupported_promotion'] for x in goldens),'architecture_disagreement_count':sum(not x['ownership_match'] or not x['extraction_match'] for x in goldens)}
  ready=all(x['passed'] for x in cases) and architecture['ownership_accuracy']>=.85 and architecture['extraction_accuracy']>=.80 and architecture['unsupported_promotions']==0
  aggregate={'run_id':manifest['run_id'],'stage':'P5.6.1','generated_at':_now(),'source_revision':manifest['source_revision'],'cases':cases,'repository_precision':avg('repository_precision'),'repository_recall':avg('repository_recall'),'evidence_coverage':avg('evidence_coverage'),'rule_coverage':avg('rule_coverage'),'unknown_preservation':avg('unknown_preservation'),'false_positive_rate':sum(r['false_positive'] for r in cases)/len(cases),'architecture':architecture,'readiness':'READY_FOR_MIGRATION_PLANNER' if ready else 'READY_FOR_TARGETED_CALIBRATION','performance':{'total_duration_seconds':sum(x['duration_seconds'] for x in records.values()),'case_duration_seconds':{k:v['duration_seconds'] for k,v in records.items()},'slowest_cases':sorted(({"id":k,"duration_seconds":v['duration_seconds']} for k,v in records.items()),key=lambda x:-x['duration_seconds'])[:5], 'searched_files':{k:v.get('metrics',{}).get('searched_files') for k,v in records.items()},'selected_files':{k:v.get('metrics',{}).get('selected_files') for k,v in records.items()},'evidence_count':{k:v.get('metrics',{}).get('evidence_count') for k,v in records.items()}}}
  _atomic_json(directory/'aggregate.json',aggregate); manifest['status']='COMPLETE'; manifest['completed_at']=_now(); _atomic_json(directory/'manifest.json',manifest); _atomic_json(self.root/'shadow-results.json',aggregate); return {'complete':True,'run_id':manifest['run_id'],'executed':executed,'skipped':skipped,'aggregate':aggregate,'created':created}
