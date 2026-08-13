"""PLAN_ONLY capability decomposition for the LangGraph Flutter cluster."""
from __future__ import annotations
import re
from pathlib import Path
from typing import TypedDict
from langgraph.graph import START, END, StateGraph

CLUSTER = Path("/Users/forest/code/langGraph")

class State(TypedDict, total=False):
    decomposition_program: dict[str, object]
    cluster_root: str
    decision: dict[str, object]

def _pubspec(path: Path) -> tuple[str, list[str]]:
    text = path.read_text(encoding="utf-8")
    name = re.search(r"^name:\s*(\S+)", text, re.M)
    deps = re.findall(r"^\s{2}([a-zA-Z_][\w_]*):\s*$", text, re.M)
    return (name.group(1) if name else path.parent.name, deps)

def _program(root: Path) -> dict[str, object]:
    repos=[]
    for directory in (root / "flutter_study", root / "gcode_core", root / "file_picker_bridge", root / "flutter_study_learning"):
        pubspec=directory/"pubspec.yaml"
        if not pubspec.is_file(): continue
        name,deps=_pubspec(pubspec)
        repos.append({"repository_id":directory.name,"path":str(directory),"role":"APP" if directory.name=="flutter_study" else "SIBLING_PACKAGE_CANDIDATE","package_name":name,"pubspec":str(pubspec),"dependencies":deps,"consumers":[]})
    capabilities=[
      {"capability_id":"gcode-parser-toolpath","current_owners":["flutter_study/packages/gcode_core","gcode_core"],"source_paths":["flutter_study/packages/gcode_core/lib","gcode_core/lib"],"consumers":["flutter_study:gcode_visualizer"],"dependencies":["flutter"],"flutter_dependency":True,"platform_dependency":False,"native_dependency":False,"state_dependency":False,"reuse_scope":"cluster","classification":"MERGE","target_package":"packages/gcode_core"},
      {"capability_id":"file-picker-platform-bridge","current_owners":["flutter_study/packages/file_picker_bridge","file_picker_bridge"],"source_paths":["flutter_study/packages/file_picker_bridge/lib","file_picker_bridge/lib"],"consumers":["flutter_study:file_picker","flutter_study:gcode_visualizer","flutter_study:font_picker"],"dependencies":["flutter/services"],"flutter_dependency":True,"platform_dependency":True,"native_dependency":False,"state_dependency":False,"reuse_scope":"cluster","classification":"MERGE","target_package":"plugins/file_picker_bridge"},
      {"capability_id":"learning-scaffold","current_owners":["flutter_study/packages/flutter_study_learning","flutter_study_learning"],"source_paths":["flutter_study/packages/flutter_study_learning/lib","flutter_study_learning/lib"],"consumers":["flutter_study:modules"],"dependencies":["flutter"],"flutter_dependency":True,"platform_dependency":False,"native_dependency":False,"state_dependency":False,"reuse_scope":"cluster","classification":"MERGE","target_package":"packages/flutter_study_learning"},
      {"capability_id":"app-composition-routing","current_owners":["flutter_study/lib/app"],"source_paths":["flutter_study/lib/app"],"consumers":[],"dependencies":["go_router","flutter"],"flutter_dependency":True,"platform_dependency":False,"native_dependency":False,"state_dependency":True,"reuse_scope":"app","classification":"KEEP_APP_ONLY","target_package":"apps/flutter_study"},
    ]
    candidates=[
      {"package_id":"packages/gcode_core","package_type":"FLUTTER_PACKAGE","target_path":"packages/gcode_core","owned_capabilities":["gcode-parser-toolpath"],"dependencies":[],"public_api_intent":"parser and toolpath API","migration_priority":1},
      {"package_id":"plugins/file_picker_bridge","package_type":"FLUTTER_PLUGIN","target_path":"plugins/file_picker_bridge","owned_capabilities":["file-picker-platform-bridge"],"dependencies":[],"public_api_intent":"platform-neutral file picker API","migration_priority":1},
      {"package_id":"packages/flutter_study_learning","package_type":"FLUTTER_PACKAGE","target_path":"packages/flutter_study_learning","owned_capabilities":["learning-scaffold"],"dependencies":[],"public_api_intent":"learning UI templates","migration_priority":2},
      {"package_id":"apps/flutter_study","package_type":"APP_ONLY","target_path":"apps/flutter_study","owned_capabilities":["app-composition-routing"],"dependencies":["packages/gcode_core","plugins/file_picker_bridge","packages/flutter_study_learning"],"public_api_intent":"bootstrap and composition only","migration_priority":3},
    ]
    tasks=[
      {"task_id":"merge-gcode-core-owners","title":"Choose and consolidate the G-code package owner","source_units":["flutter_study/packages/gcode_core","gcode_core"],"target_units":["packages/gcode_core"],"depends_on":[],"allowed_operations":["MOVE","DELETE","API_BREAK","DEPENDENCY_REWRITE","PACKAGE_MERGE"],"acceptance":["single owner","consumers migrate before legacy deletion"],"status":"READY","evidence":["two pubspec owners discovered"]},
      {"task_id":"merge-file-picker-bridge-owners","title":"Choose and consolidate file picker plugin ownership","source_units":["flutter_study/packages/file_picker_bridge","file_picker_bridge"],"target_units":["plugins/file_picker_bridge"],"depends_on":[],"allowed_operations":["MOVE","DELETE","API_BREAK","DEPENDENCY_REWRITE","PACKAGE_MERGE"],"acceptance":["single plugin boundary"],"status":"READY","evidence":["three app consumers import file_picker_bridge"]},
      {"task_id":"relocate-flutter-study-app","title":"Relocate app composition after package ownership stabilizes","source_units":["flutter_study/lib/app"],"target_units":["apps/flutter_study"],"depends_on":["merge-gcode-core-owners","merge-file-picker-bridge-owners"],"allowed_operations":["MOVE","DEPENDENCY_REWRITE","API_BREAK"],"acceptance":["app has no reusable implementation"],"status":"READY","evidence":["app pubspec owns workspace composition"]},
    ]
    return {"program_id":"flutter-study-decomposition-program","cluster_root":str(root),"repositories":repos,"capabilities":capabilities,"package_candidates":candidates,"target_dependency_graph":{"nodes":[x["package_id"] for x in candidates],"edges":[["apps/flutter_study",x] for x in ["packages/gcode_core","plugins/file_picker_bridge","packages/flutter_study_learning"]],"cycles":[]},"migration_tasks":tasks,"human_decisions":[],"integration_head":None,"execution_mode":"PLAN_ONLY","status":"PLANNING_COMPLETE"}

def build_decomposition_graph():
    graph=StateGraph(State)
    def plan(state: State):
        root=Path(state.get("cluster_root") or CLUSTER)
        program=_program(root)
        if isinstance(state.get("decision"),dict):
            program["human_decisions"]=[state["decision"]]
        return {"decomposition_program":program}
    graph.add_node("plan",plan); graph.add_edge(START,"plan"); graph.add_edge("plan",END)
    return graph.compile()
