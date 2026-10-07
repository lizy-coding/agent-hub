from typing import TypedDict
from langgraph.graph import START,END,StateGraph
class ExecutionState(TypedDict,total=False): execution_result:dict[str,object]
def build_migration_execution_graph():
 graph=StateGraph(ExecutionState)
 graph.add_node('reject_unimplemented', lambda state: {'execution_result': {
     'status': 'EXECUTION_NOT_IMPLEMENTED', 'complete': False, 'executed': False,
     'reason': 'Use the frozen decomposition execution lane; migration_execution has no executor.'}})
 graph.add_edge(START,'reject_unimplemented');graph.add_edge('reject_unimplemented',END)
 return graph.compile()
