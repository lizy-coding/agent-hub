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
  return {'cases':self.results,'repository_precision':average('repository_precision'),'repository_recall':average('repository_recall'),'evidence_coverage':average('evidence_coverage'),'rule_coverage':average('rule_coverage'),'unknown_preservation':average('unknown_preservation'),'false_positive_rate':sum(r['false_positive'] for r in self.results)/len(self.results) if self.results else None,'readiness':'READY_FOR_MORE_SHADOW_CASES'}
 def validate_benchmark_result(self,metrics):
  errors=[]
  if len(metrics['cases'])<6: errors.append('fewer than six cases')
  if any(not r['passed'] for r in metrics['cases']): errors.append('scenario assertion failure')
  if any(r['false_positive'] for r in metrics['cases']): errors.append('unsupported fact promotion')
  return errors
