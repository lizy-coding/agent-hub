from typing import TypedDict
from langgraph.graph import START,END,StateGraph
class ExecutionState(TypedDict,total=False): execution_result:dict[str,object]
def build_migration_execution_graph():
 graph=StateGraph(ExecutionState); chain=['load_approved_plan','verify_authority','verify_source_freshness','prepare_worktree','resolve_task_context','execute_task','verify_diff_scope','validate_task','validate_integration','collect_diff','build_execution_result']
 for name in chain:graph.add_node(name,lambda state:{})
 graph.add_edge(START,chain[0])
 for left,right in zip(chain,chain[1:]):graph.add_edge(left,right)
 graph.add_edge(chain[-1],END);return graph.compile()
