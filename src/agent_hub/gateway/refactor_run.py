"""Read-only client helpers plus local Worker lifecycle for refactor-run."""
from __future__ import annotations
import json, os, socket, subprocess, time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from agent_hub.gateway.refactor_dashboard import fetch_state, render, resolve_thread
from agent_hub.projects.decomposition_config import load_decomposition_project

def _requirement(program_id):
    return f"Continue {program_id}. Rescan all DevelopmentUnits after reconciling the integration branch, preserve Git-proven DONE tasks, refresh evidence-backed tasks and the dependency DAG, and execute only frozen READY tasks through development graph -> Worker -> Codex -> ScopeGuard -> validation -> Reviewer -> integration validation -> local integration commit. Do not push, merge, release, or modify .hermes."

def _call(method, url, payload=None):
    request=Request(url, data=json.dumps(payload).encode() if payload else None, headers={"Content-Type":"application/json"}, method=method)
    with urlopen(request, timeout=10) as response: return json.loads(response.read())

def _port(endpoint): return int(endpoint.split(":")[2].split("/")[0])
def _ready(endpoint):
    try:
        with socket.create_connection(("127.0.0.1", _port(endpoint)), timeout=1): return True
    except OSError: return False
def _active(state):
    """A failed checkpoint is resumable history, not an active run."""
    tasks = state.get("tasks") or []
    if tasks and all(isinstance(task, dict) and task.get("error") for task in tasks):
        return False
    return bool(state.get("next") or tasks)

def _start_worker(root, endpoint, project):
    env=os.environ.copy(); env["AGENT_HUB_CODE_WORKER_PORT"]=str(_port(endpoint))
    for file in (root/".env", root/".env.local"):
        if file.exists():
            for line in file.read_text().splitlines():
                line=line.removeprefix("export ")
                if "=" in line and not line.startswith("#"):
                    key,value=line.split("=",1); env.setdefault(key,value)
    integration=root/".integration"/project.primary_repository_id
    env["AGENT_HUB_PRIMARY_REPOSITORY_PATH"]=str(integration)
    env["AGENT_HUB_PRIMARY_REPOSITORY"]=project.primary_repository_id
    env["AGENT_HUB_INTEGRATION_WORKTREE"]=str(integration)
    return subprocess.Popen([str(root/".venv/bin/python"),"-m","agent_hub.gateway.code_worker"],cwd=root,env=env,start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)

def refactor_run(server, thread_id, root, output=print, project_id=None):
    root = Path(root)
    project = load_decomposition_project(project_id)
    try:
        if not _call("GET",server.rstrip("/")+"/ok").get("ok"): raise OSError("health check failed")
    except (URLError,HTTPError,OSError,ValueError) as error:
        output(f"DISCONNECTED: LangGraph unavailable: {error}"); return 2
    thread_id = resolve_thread(server, thread_id, project.project_id)
    if not thread_id:
        thread_id = _call("POST", server.rstrip("/") + "/threads", {"metadata": {"program_type": "development", "program_id": project.refactor_program_id, "project_id": project.project_id, "repository_id": project.primary_repository_id}})["thread_id"]
    endpoint=os.environ.get("AGENT_HUB_CODE_WORKER_ENDPOINT","http://127.0.0.1:8765/execute"); owned=None
    integration = root / ".integration" / project.primary_repository_id
    os.environ.setdefault("AGENT_HUB_INTEGRATION_WORKTREE", str(integration))
    if not _ready(endpoint):
        owned=_start_worker(root,endpoint,project)
        for _ in range(20):
            if _ready(endpoint): break
            time.sleep(.25)
        if not _ready(endpoint): output("WORKER_UNAVAILABLE"); return 3
        output(f"Worker started (pid={owned.pid})")
    try:
        state=fetch_state(server,thread_id)
        if _active(state): output("Attached to active LangGraph run")
        else:
            assistants=_call("POST",server.rstrip("/")+"/assistants/search",{"limit":50,"offset":0})
            assistant=next(x["assistant_id"] for x in assistants if x["graph_id"]=="development")
            result=_call("POST",f"{server.rstrip('/')}/threads/{thread_id}/runs",{"assistant_id":assistant,"input":{"repository_id":project.primary_repository_id,"requirement":_requirement(project.refactor_program_id),"worker_endpoint":endpoint},"multitask_strategy":"reject"})
            output(f"Submitted run {result['run_id']}")
        while True:
            state=fetch_state(server,thread_id); print("\033[2J\033[H",end=""); output(render(state))
            if not _active(state): return 0
            time.sleep(2)
    except KeyboardInterrupt:
        output("\nDetached; LangGraph run continues."); return 0
    except (URLError,HTTPError,OSError,ValueError) as error:
        output(f"DISCONNECTED: {error}"); return 2
    finally:
        if owned and owned.poll() is None:
            try:
                if not _active(fetch_state(server,thread_id)): owned.terminate()
            except (URLError,OSError,ValueError): pass
