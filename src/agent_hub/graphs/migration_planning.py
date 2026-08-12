from typing import TypedDict
from langgraph.graph import START, END, StateGraph
from agent_hub.planning.migration_planner import MigrationPlanner
from agent_hub.schemas.models import CapabilityAnalysis
from agent_hub.workspace.config import WorkspaceConfig

class MigrationPlanningState(TypedDict,total=False):
 requirement:str; target_repository:str; capability_analysis:dict[str,object]; migration_plan:dict[str,object]

def build_migration_planning_graph(config:WorkspaceConfig):
 planner=MigrationPlanner(config)
 def resolve_capability_analysis(state): return {}
 def derive_architecture_invariants(state): return {}
 def generate_migration_tasks(state): return {}
 def build_dependency_dag(state): return {}
 def resolve_task_rules(state): return {}
 def attach_validation(state): return {}
 def assess_risk(state): return {}
 def validate_plan(state): return {}
 def build_plan(state):
  supplied=CapabilityAnalysis.model_validate(state['capability_analysis']) if state.get('capability_analysis') else None
  return {'migration_plan':planner.build_plan(state['requirement'],state['target_repository'],supplied).model_dump(mode='json')}
 graph=StateGraph(MigrationPlanningState); chain=[('resolve_capability_analysis',resolve_capability_analysis),('derive_architecture_invariants',derive_architecture_invariants),('generate_migration_tasks',generate_migration_tasks),('build_dependency_dag',build_dependency_dag),('resolve_task_rules',resolve_task_rules),('attach_validation',attach_validation),('assess_risk',assess_risk),('validate_plan',validate_plan),('build_plan',build_plan)]
 for name,func in chain: graph.add_node(name,func)
 graph.add_edge(START,chain[0][0])
 for (left,_),(right,_) in zip(chain,chain[1:]): graph.add_edge(left,right)
 graph.add_edge(chain[-1][0],END)
 return graph.compile()
