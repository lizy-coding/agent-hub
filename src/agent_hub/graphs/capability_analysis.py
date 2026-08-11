from typing import TypedDict
from langgraph.graph import START, END, StateGraph
from agent_hub.capability.analyzer import CapabilityAnalyzer
from agent_hub.workspace.config import WorkspaceConfig
class CapabilityState(TypedDict,total=False): requirement:str; target_repository:str; capability_analysis:dict[str,object]
def build_capability_analysis_graph(config:WorkspaceConfig):
 analyzer=CapabilityAnalyzer(config)
 def resolve_context(state): return {}
 def discover_capabilities(state): return {}
 def analyze_coupling(state): return {}
 def classify_ownership(state): return {}
 def match_workspace_capabilities(state): return {}
 def assess_extraction(state): return {}
 def build_analysis(state): return {'capability_analysis':analyzer.analyze_capabilities(state['requirement'],state['target_repository']).model_dump(mode='json')}
 graph=StateGraph(CapabilityState)
 for name,fn in [('resolve_context',resolve_context),('discover_capabilities',discover_capabilities),('analyze_coupling',analyze_coupling),('classify_ownership',classify_ownership),('match_workspace_capabilities',match_workspace_capabilities),('assess_extraction',assess_extraction),('build_analysis',build_analysis)]: graph.add_node(name,fn)
 chain=['resolve_context','discover_capabilities','analyze_coupling','classify_ownership','match_workspace_capabilities','assess_extraction','build_analysis']; graph.add_edge(START,chain[0])
 for a,b in zip(chain,chain[1:]): graph.add_edge(a,b)
 graph.add_edge(chain[-1],END); return graph.compile()
