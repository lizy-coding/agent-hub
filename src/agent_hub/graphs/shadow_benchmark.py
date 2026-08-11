from typing import TypedDict
from langgraph.graph import START,END,StateGraph
from agent_hub.benchmark.runner import ShadowBenchmarkRunner
from agent_hub.workspace.config import WorkspaceConfig
class BenchmarkState(TypedDict,total=False): benchmark_result:dict[str,object]
def build_shadow_benchmark_graph(config:WorkspaceConfig):
 runner=ShadowBenchmarkRunner(config)
 def load_scenarios(s): return {}
 def run_context_analysis(s): return {}
 def run_capability_analysis(s): return {}
 def score_evidence(s): return {}
 def aggregate_metrics(s): return {}
 def evaluate_gate(s): return {'benchmark_result':runner.run_shadow_suite()}
 graph=StateGraph(BenchmarkState); chain=[('load_scenarios',load_scenarios),('run_context_analysis',run_context_analysis),('run_capability_analysis',run_capability_analysis),('score_evidence',score_evidence),('aggregate_metrics',aggregate_metrics),('evaluate_gate',evaluate_gate)]
 for n,f in chain: graph.add_node(n,f)
 graph.add_edge(START,chain[0][0])
 for (a,_),(b,_) in zip(chain,chain[1:]):graph.add_edge(a,b)
 graph.add_edge(chain[-1][0],END);return graph.compile()
