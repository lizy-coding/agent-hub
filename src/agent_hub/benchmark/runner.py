"""Independent-expectation scoring for Context and Capability analysis."""
import json
from pathlib import Path
from agent_hub.capability.analyzer import CapabilityAnalyzer
from agent_hub.context.resolver import ContextLimits, ContextResolver
from agent_hub.workspace.config import WorkspaceConfig

class ShadowBenchmarkRunner:
 def __init__(self,config:WorkspaceConfig,scenario_path:Path|None=None):
  self.config=config; self.context=ContextResolver(config); self.capability=CapabilityAnalyzer(config); self.scenario_path=scenario_path or Path(__file__).resolve().parents[3]/'benchmarks/shadow_cases/cases.json'; self.results=[]
 def load_scenarios(self): return json.loads(self.scenario_path.read_text())
 def load_reviewed_goldens(self):
  root=self.scenario_path.parents[1]/'architecture_goldens'
  candidates={x['id']:x for x in json.loads((root/'candidates.json').read_text())}
  decisions=json.loads((root/'review-decisions.json').read_text())
  return [(candidates[x['id']],x) for x in decisions if x['state'].startswith('approved') and x['accepted_ownership']]
 def run_shadow_case(self,scenario):
  limits=ContextLimits(**scenario['limits']); context=self.context.resolve_context(scenario['requirement'],scenario['target_repository'],limits); analysis=self.capability.analyze_capabilities(scenario['requirement'],scenario['target_repository']); result=self.score_shadow_case(scenario,context,analysis); self.results.append(result); return result
 def score_shadow_case(self,scenario,context,analysis):
  expected=scenario['expected']; repos=set(context.scope['repositories']); required=set(expected['repositories']['must_include']); predicted=set(context.scope['repositories'])
  required_paths=expected['evidence']['require_paths']; refs=[edge.evidence.path for edge in context.dependencies]+[ref.split(':')[0] for c in context.candidates for ref in c.evidence_refs]
  rules=[rule.path for rule in context.rules]; unknown_ok=len(context.unknowns)>=expected['unknowns']['minimum_expected']; negative=scenario['category']=='negative'; unsupported=negative and bool(context.symbols)
  return {'id':scenario['id'],'passed':required.issubset(repos) and all(path in refs or any(path in file.relative_path for file in context.files) for path in required_paths) and set(expected['rules']['must_include']).issubset(rules) and unknown_ok and not unsupported,'repository_precision':len(required&predicted)/len(predicted) if predicted else None,'repository_recall':len(required&predicted)/len(required) if required else None,'evidence_coverage':sum(1 for path in required_paths if path in refs or any(path in file.relative_path for file in context.files))/len(required_paths) if required_paths else None,'rule_coverage':sum(1 for rule in expected['rules']['must_include'] if rule in rules)/len(expected['rules']['must_include']) if expected['rules']['must_include'] else None,'unknown_preservation':1.0 if unknown_ok else 0.0,'false_positive':1 if unsupported else 0,'metrics':context.metrics,'failures':([] if required.issubset(repos) else ['required repository missing'])+([] if not unsupported else ['negative case returned exact symbol evidence']) ,'review_state':scenario['review_state']}
 def run_shadow_suite(self):
  self.results=[]
  for scenario in self.load_scenarios(): self.run_shadow_case(scenario)
  return self.get_shadow_metrics()
 def get_shadow_metrics(self):
  vals=lambda name:[r[name] for r in self.results if r[name] is not None]
  average=lambda name:sum(vals(name))/len(vals(name)) if vals(name) else None
  architecture=self.score_reviewed_architecture()
  ready=all(x['passed'] for x in self.results) and architecture['ownership_accuracy']>=.85 and architecture['extraction_accuracy']>=.80 and architecture['unsupported_promotions']==0
  return {'cases':self.results,'repository_precision':average('repository_precision'),'repository_recall':average('repository_recall'),'evidence_coverage':average('evidence_coverage'),'rule_coverage':average('rule_coverage'),'unknown_preservation':average('unknown_preservation'),'false_positive_rate':sum(r['false_positive'] for r in self.results)/len(self.results) if self.results else None,'architecture':architecture,'readiness':'READY_FOR_MIGRATION_PLANNER' if ready else 'READY_FOR_ANALYZER_CALIBRATION'}
 def score_reviewed_architecture(self):
  rows=[]
  for candidate,truth in self.load_reviewed_goldens():
   analysis=self.capability.analyze_capabilities(candidate['title']+' '+candidate['capability_scope'],candidate['target_repository'])
   evidence=set(candidate['evidence']['files'])
   ranked=sorted(analysis.capabilities,key=lambda node:len(evidence & set(node.files)),reverse=True)
   node=ranked[0] if ranked and evidence & set(ranked[0].files) else None
   prediction=node.ownership if node else 'UNKNOWN'
   assessment=next((x for x in analysis.extraction_assessments if node and x.capability_id==node.capability_id),None)
   extraction=assessment.decision if assessment else 'UNKNOWN'
   target=assessment.target_unit if assessment else None
   accepted_ownership=truth['accepted_ownership']; accepted_extraction=truth['accepted_extraction']
   promotion=accepted_extraction=='UNKNOWN' and extraction not in ('UNKNOWN','NOT_ENOUGH_EVIDENCE')
   rows.append({'id':truth['id'],'predicted_ownership':prediction,'accepted_ownership':accepted_ownership,'ownership_match':prediction==accepted_ownership,'predicted_extraction':extraction,'accepted_extraction':accepted_extraction,'extraction_match':extraction==accepted_extraction,'predicted_target_unit':target,'accepted_target_unit':candidate['proposed_extraction'].get('target_unit'),'target_scored':accepted_extraction in ('MOVE_TO_EXISTING_UNIT','EXTEND_EXISTING_UNIT') and bool(candidate['proposed_extraction'].get('target_unit')),'target_match':target==candidate['proposed_extraction'].get('target_unit') if accepted_extraction in ('MOVE_TO_EXISTING_UNIT','EXTEND_EXISTING_UNIT') else None,'unsupported_promotion':promotion,'evidence_used':node.evidence_refs if node else [],'failure_classification':'clustering' if node is None else 'ownership' if prediction!=accepted_ownership else 'extraction' if extraction!=accepted_extraction else None})
  avg=lambda values:sum(values)/len(values) if values else None
  return {'goldens':rows,'ownership_accuracy':avg([x['ownership_match'] for x in rows]),'extraction_accuracy':avg([x['extraction_match'] for x in rows]),'extraction_target_accuracy':avg([x['target_match'] for x in rows if x['target_scored']]),'unsupported_promotions':sum(x['unsupported_promotion'] for x in rows),'architecture_disagreement_count':sum(not x['ownership_match'] or not x['extraction_match'] for x in rows)}
 def validate_benchmark_result(self,metrics):
  errors=[]
  if len(metrics['cases'])<6: errors.append('fewer than six cases')
  if any(not r['passed'] for r in metrics['cases']): errors.append('scenario assertion failure')
  if any(r['false_positive'] for r in metrics['cases']): errors.append('unsupported fact promotion')
  if metrics['architecture']['unsupported_promotions']: errors.append('unsupported architecture promotion')
  return errors
