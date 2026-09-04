import unittest
from unittest.mock import patch
from agent_hub.gateway.decomposition import _needs_app_guard_reconciliation, _needs_blocked_decision_metadata, _needs_done_reconciliation, _needs_ready_dirty_reconciliation, _needs_zero_change_reconciliation, plan, propose, render, run, status
from agent_hub.gateway.decomposition_state import load as load_snapshot, save as save_snapshot, validate as validate_snapshot
from agent_hub.graphs.decomposition import _allowed, _app_relocation_contract, _classify_managed_dirty, _mutation_repositories, _program, _proposal_inventory, _repositories_for, _restore_agent_owned_dirty, _select, _stage_validated_changes, build_decomposition_graph
class DecompositionTest(unittest.TestCase):
 def test_program_maps_windows_resilient_online_video_playback_to_app_owner(self):
  import tempfile
  from pathlib import Path
  with tempfile.TemporaryDirectory() as raw:
   repo=Path(raw)/'flutter_forge'; repo.mkdir(); (repo/'pubspec.yaml').write_text('name: flutter_forge_workspace\n')
   program=_program(Path(raw))
  capability=next(item for item in program['capabilities'] if item['capability_id']=='windows-resilient-online-video-playback')
  app=next(item for item in program['package_candidates'] if item['package_id']=='apps/flutter_forge')
  self.assertEqual(capability['current_owners'],['flutter_forge/apps/flutter_forge/lib/modules/platform/online_video_player'])
  self.assertEqual(capability['dependencies'],['dio','video_player','video_player_win'])
  self.assertTrue(capability['platform_dependency']); self.assertTrue(capability['native_dependency'])
  self.assertIn(capability['capability_id'],app['owned_capabilities'])
  self.assertIn('video_player_win',app['dependencies'])

 def test_current_ready_proposal_is_selected_before_older_ready_task(self):
  program={'current_migration_task':'rename-project-to-flutter-forge','migration_tasks':[{'task_id':'older','status':'READY','depends_on':[]},{'task_id':'rename-project-to-flutter-forge','status':'READY','depends_on':[]}]}
  self.assertEqual(_select(program)['task_id'],'rename-project-to-flutter-forge')

 def test_flutter_forge_project_rename_inventory_freezes_old_and_new_paths(self):
  import tempfile
  from pathlib import Path
  with tempfile.TemporaryDirectory() as raw:
   root=Path(raw); (root/'apps/flutter_study/lib').mkdir(parents=True)
   files={
    'pubspec.yaml':'name: flutter_study_workspace\nworkspace:\n  - apps/flutter_study\n',
    'apps/flutter_study/pubspec.yaml':'name: flutter_study_app\n',
    'apps/flutter_study/lib/main.dart':"import 'package:flutter_study_app/app.dart';\n",
   }
   for name,content in files.items(): (root/name).write_text(content)
   with patch('agent_hub.graphs.decomposition.subprocess.check_output',return_value='\n'.join(files)):
    task=_proposal_inventory({'primary_repository_id':'flutter_forge','repositories':[{'repository_id':'flutter_forge','path':str(root)}]},{'task_id':'rename-project-to-flutter-forge','title':'Rename'})
  self.assertEqual(task['status'],'READY')
  allowed=task['allowed_paths_by_repository']['flutter_forge']
  self.assertIn('apps/flutter_study/lib/main.dart',allowed)
  self.assertIn('apps/flutter_forge/lib/main.dart',allowed)
  self.assertNotIn('packages/flutter_study_learning',allowed)

 def test_flutter_forge_project_rename_guard_requires_identity_and_app_move(self):
  from agent_hub.graphs.decomposition import _architecture_guard
  paths=['pubspec.yaml','apps/flutter_study/pubspec.yaml','apps/flutter_forge/pubspec.yaml','apps/flutter_study/lib/main.dart','apps/flutter_forge/lib/main.dart']
  diff='+name: flutter_forge_workspace\n+  - apps/flutter_forge\n+name: flutter_forge_app\n'
  worker={'repositories':{'flutter_forge':{'changed_files':paths,'diff':diff}}}
  guard=_architecture_guard({'task_id':'rename-project-to-flutter-forge','source_units':['apps/flutter_study'],'target_units':['apps/flutter_forge']},worker,{'primary_repository_id':'flutter_forge'})
  self.assertEqual(guard['status'],'PASS')

 def test_package_rename_inventory_freezes_pubspec_imports_and_run_config(self):
  import tempfile
  from pathlib import Path
  with tempfile.TemporaryDirectory() as raw:
   root=Path(raw); (root/'apps/flutter_forge/lib').mkdir(parents=True); (root/'apps/flutter_forge/test').mkdir(parents=True)
   files={'apps/flutter_forge/pubspec.yaml':'name: main_app\n','apps/flutter_forge/lib/main.dart':"import 'package:main_app/app.dart';\n",'apps/flutter_forge/test/app_test.dart':"import 'package:main_app/app.dart';\n"}
   for name,content in files.items(): (root/name).write_text(content)
   with patch('agent_hub.graphs.decomposition.subprocess.check_output',return_value='\n'.join(files)):
    task=_proposal_inventory({'primary_repository_id':'flutter_forge','repositories':[{'repository_id':'flutter_forge','path':str(root)}]},{'task_id':'rename-main-app-package','title':'Rename'})
  self.assertEqual(task['status'],'READY'); self.assertIn('.run/Flutter_Forge_macOS.run.xml',task['allowed_paths_by_repository']['flutter_forge']); self.assertEqual(len(task['evidence']),3)
 def test_media_backend_replacement_guard_accepts_scoped_worker_diff(self):
  from agent_hub.graphs.decomposition import _architecture_guard
  paths=['apps/flutter_forge/pubspec.yaml','apps/flutter_forge/lib/modules/platform/online_video_player/module_root.dart','apps/flutter_forge/lib/modules/platform/online_video_player/state/media_kit_player_adapter.dart','apps/flutter_forge/lib/modules/platform/online_video_player/state/video_player_adapter.dart','apps/flutter_forge/test/modules/platform/online_video_player/online_video_player_test.dart']
  worker={'repositories':{'flutter_forge':{'changed_files':paths,'diff':'video_player media_kit_player_adapter.dart'}}}
  guard=_architecture_guard({'task_id':'replace-media-plugin-with-video-player','source_units':['media'],'target_units':['media']},worker,{'primary_repository_id':'flutter_forge'})
  self.assertEqual(guard['status'],'PASS')
 def test_stale_success_from_other_task_is_not_integrated(self):
  result=build_decomposition_graph().invoke({'decomposition_program':{'status':'PLANNING_COMPLETE','current_migration_task':'media','migration_tasks':[{'task_id':'media','status':'READY'}]},'worker_result':{'task_id':'old-task','status':'SUCCESS'}})
  self.assertNotIn('integration_result',result)
  self.assertEqual(result['decomposition_program']['migration_tasks'][0]['status'],'READY')
 def test_proposal_inventory_freezes_exact_evidence_backed_paths(self):
  import tempfile
  from pathlib import Path
  with tempfile.TemporaryDirectory() as raw:
   root=Path(raw); (root/'apps/flutter_forge/lib/modules/platform/online_video_player/state').mkdir(parents=True); (root/'apps/flutter_forge/lib/app').mkdir(parents=True); (root/'apps/flutter_forge/test/modules').mkdir(parents=True)
   files={
    'apps/flutter_forge/pubspec.yaml':'  media_kit: ^1.0.0\n',
    'pubspec.lock':'media_kit:\n',
    'apps/flutter_forge/lib/modules/platform/online_video_player/state/media_kit_player_adapter.dart':'import package:media_kit/media_kit.dart;',
    'apps/flutter_forge/lib/modules/platform/online_video_player/module_root.dart':'online_video_player media_kit_video',
    'apps/flutter_forge/lib/app/app_bootstrap.dart':'MediaKit.ensureInitialized();',
    'apps/flutter_forge/test/modules/player_test.dart':'online_video_player',
   }
   for name, content in files.items(): (root/name).write_text(content)
   with patch('agent_hub.graphs.decomposition.subprocess.check_output',return_value='\n'.join(files)):
    task=_proposal_inventory({'repositories':[{'repository_id':'flutter_forge','path':str(root)}]}, {'task_id':'media','title':'Media'})
  self.assertEqual(task['status'],'READY')
  self.assertTrue(set(task['allowed_paths_by_repository']['flutter_forge']).issubset(task['candidate_paths']))
  self.assertTrue(all(not path.endswith('/') for path in task['candidate_paths']))
  self.assertTrue(task['evidence'])

 def test_proposal_without_required_evidence_is_blocked(self):
  import tempfile
  from pathlib import Path
  with tempfile.TemporaryDirectory() as raw, patch('agent_hub.graphs.decomposition.subprocess.check_output',return_value=''):
   task=_proposal_inventory({'repositories':[{'repository_id':'flutter_forge','path':raw}]}, {'task_id':'media','title':'Media'})
  self.assertEqual(task['status'],'BLOCKED_DECISION')
  self.assertEqual(task['allowed_paths_by_repository'],{})

 def test_duplicate_proposal_is_idempotent(self):
  existing={'task_id':'media','status':'READY','evidence':['frozen']}
  program=build_decomposition_graph().invoke({'proposal_spec':{'task_id':'media','title':'Media'},'decomposition_program':{'migration_tasks':[existing]}})['decomposition_program']
  self.assertEqual(program['migration_tasks'],[existing])
  self.assertTrue(program['last_proposal']['idempotent'])

 @patch('agent_hub.gateway.decomposition._submit')
 @patch('agent_hub.gateway.decomposition._resolve_thread',return_value=('thread',None))
 def test_propose_submits_read_only_graph_input_without_execute(self, resolve, submit):
  import json, tempfile
  from pathlib import Path
  submit.return_value={'run_id':'run'}; output=[]
  with tempfile.TemporaryDirectory() as raw:
   path=Path(raw)/'task.json'; path.write_text(json.dumps({'task_id':'media','title':'Media'}))
   self.assertEqual(propose('http://server','thread',path,output.append),0)
  payload=submit.call_args.args[2]
  self.assertFalse(payload['execute'])
  self.assertNotIn('worker_endpoint',payload)

 def test_propose_rejects_caller_owned_allowed_paths(self):
  import json, tempfile
  from pathlib import Path
  with tempfile.TemporaryDirectory() as raw:
   path=Path(raw)/'task.json'; path.write_text(json.dumps({'task_id':'media','title':'Media','allowed_paths':['lib']})); output=[]
   self.assertEqual(propose('http://server','thread',path,output.append),2)
  self.assertIn('graph-owned fields',output[0])
 def test_dashboard_shows_plan_only(self):
  text=render({"values":{"decomposition_program":{"program_id":"p","execution_mode":"PLAN_ONLY","capabilities":[{"classification":"MERGE"}],"migration_tasks":[{"status":"READY"}],"package_candidates":[],"target_dependency_graph":{"nodes":[],"edges":[],"cycles":[]}}}})
  self.assertIn("PLAN_ONLY",text)
  self.assertIn("RUNNING: 0",text)
 @patch("agent_hub.gateway.decomposition._call")
 def test_plan_creates_thread_when_not_supplied(self, call):
  call.side_effect=[{"thread_id":"t"},[{"assistant_id":"a","graph_id":"decomposition"}],{"run_id":"r"}]
  output=[]
  self.assertEqual(plan("http://server",None,output.append),0)
  self.assertIn("Thread ID: t",output[0]); self.assertIn("Run ID: r",output[0])
  self.assertEqual(call.call_args_list[2].args[1],"http://server/threads/t/runs")
 @patch("agent_hub.gateway.decomposition._call")
 def test_status_does_not_select_refactor_thread(self, call):
  call.return_value=[{"thread_id":"ref","metadata":{"program_id":"flutter-forge-refactor-program"}}]
  output=[]
  self.assertEqual(status("http://server",None,output.append),2)
  self.assertTrue(output[0].startswith("NO_DECOMPOSITION_PROGRAM"))
 @patch("agent_hub.gateway.decomposition._call")
 def test_explicit_refactor_thread_is_rejected(self, call):
  call.return_value={"thread_id":"ref","metadata":{"program_id":"flutter-forge-refactor-program"}}
  output=[]
  self.assertEqual(status("http://server","ref",output.append),2)
  self.assertEqual(output[0],"WRONG_PROGRAM_TYPE")
 @patch("agent_hub.gateway.decomposition._resolve_thread")
 def test_run_receives_server_and_thread_and_preserves_plan_only(self, resolve):
  resolve.return_value=("decomposition-thread",None)
  output=[]
  self.assertEqual(run("http://server","decomposition-thread",False,output.append),3)
  self.assertEqual(resolve.call_args.args[:2],("http://server","decomposition-thread"))
  self.assertIn("decomposition-thread",output[0])
 @patch("agent_hub.gateway.decomposition._submit")
 @patch("agent_hub.gateway.decomposition._reconcile_stale_dispatching", side_effect=lambda server, thread_id, state: state)
 @patch("agent_hub.gateway.decomposition._worker_ready", return_value=True)
 @patch("agent_hub.gateway.decomposition._resolve_thread")
 @patch("agent_hub.gateway.decomposition.fetch_state")
 def test_execute_submits_to_existing_thread(self, state, resolve, worker_ready, reconcile, submit):
  resolve.return_value=("decomposition-thread",None); submit.return_value={"run_id":"run"}
  state.return_value={"values":{"decomposition_program":{"program_id":"flutter-forge-decomposition-program"}}}
  output=[]
  self.assertEqual(run("http://server","decomposition-thread",True,output.append),0)
  payload=submit.call_args.args[2]
  self.assertTrue(payload["execute"]); self.assertEqual(payload["worker_endpoint"],"http://127.0.0.1:8766/execute")
  self.assertEqual(payload["project_context"]["project_id"],"flutter-forge")
  self.assertIn("Mode: EXECUTE",output[0])
  def test_package_task_maps_only_to_flutter_forge(self):
   self.assertEqual(_repositories_for({"source_units":["flutter_forge/packages/gcode_core"],"target_units":["packages/gcode_core"]}),["flutter_forge"])
  def test_file_picker_contract_derives_only_flutter_forge(self):
   roles=_mutation_repositories({"source_units":["flutter_forge/packages/file_picker_bridge"],"target_units":["packages/file_picker_bridge"],"allowed_operations":[]})
   self.assertEqual(roles,{"flutter_forge":"source_target"})
 def test_package_unit_task_resolves_to_primary_repository(self):
  task={"source_units":[],"target_units":["packages/gcode_core","packages/file_picker_bridge","packages/flutter_study_learning","packages/flutter_ioc_core"]}
  self.assertEqual(_repositories_for(task),["flutter_forge"])
  self.assertEqual(_mutation_repositories({**task,"allowed_operations":[]}),{"flutter_forge":"target"})
 def test_worker_scope_requires_declared_allowed_paths(self):
  from agent_hub.execution.decomposition_worker import DecompositionCodeExecutor
  scope,error=DecompositionCodeExecutor._writable_scope({"allowed_paths_by_repository":{"file_picker_bridge":["lib"]},"writable_repositories":[{"repository":"file_picker_bridge","role":"source","writable":True,"allowed_paths":["lib"]}]})
  self.assertEqual(error,""); self.assertEqual(scope,{"file_picker_bridge":["lib"]})
  def test_worker_diff_emits_applyable_binary_patch(self):
   import os, tempfile
   from pathlib import Path
   from agent_hub.execution.decomposition_worker import _snapshot
   with tempfile.TemporaryDirectory() as raw:
    root=Path(raw); os.system(f"git init -q {root}"); os.system(f"git -C {root} config user.email test@example.com"); os.system(f"git -C {root} config user.name test")
    (root/"icon.bin").write_bytes(b"\x00\x01\x02"); os.system(f"git -C {root} add icon.bin && git -C {root} commit -qm base")
    (root/"icon.bin").write_bytes(b"\x03\x04\x05")
    changed,diff=_snapshot(root)
    self.assertEqual(changed,["icon.bin"])
    self.assertIn("literal",diff)
 def test_frozen_allowed_paths_override_task_defaults(self):
  self.assertEqual(_allowed({"task_id":"merge-file-picker-bridge-owners","allowed_paths_by_repository":{"flutter_forge":["packages/file_picker_bridge","pubspec.yaml"]}},"flutter_forge"),["packages/file_picker_bridge","pubspec.yaml"])
 def test_app_relocation_contract_creates_a_scoped_app_target(self):
  contract=_app_relocation_contract()
  self.assertTrue(contract["target_creation_allowed"])
  self.assertIn("apps/flutter_forge",contract["allowed_paths_by_repository"]["flutter_forge"])
  self.assertEqual(_mutation_repositories(contract),{"flutter_forge":"source_target"})
 def test_app_relocation_decision_replaces_only_blocked_contract(self):
  program=build_decomposition_graph().invoke({"reconcile_only":True,"decision":{"decision_id":"retry:relocate-flutter-forge-app","choice":"CREATE_APPS_FLUTTER_STUDY"},"decomposition_program":{"status":"PROGRAM_BLOCKED","execution_blocker":{"status":"MIGRATION_NO_EFFECT","task_id":"relocate-flutter-forge-app"},"migration_tasks":[{"task_id":"relocate-flutter-forge-app","status":"BLOCKED_DECISION"}]}})["decomposition_program"]
  task=program["migration_tasks"][0]
  self.assertEqual(task["status"],"READY")
  self.assertTrue(task["target_creation_allowed"])
 @patch("agent_hub.graphs.decomposition._ensure_worktree")
 def test_app_guard_accepts_verified_isolated_target_diff_before_apply(self, ensure):
  from pathlib import Path
  from agent_hub.graphs.decomposition import _architecture_guard
  ensure.return_value=(Path("/missing"),"decomposition/flutter_forge")
  guard=_architecture_guard(_app_relocation_contract(),{"repositories":{"flutter_forge":{"changed_files":["apps/flutter_forge/pubspec.yaml","apps/flutter_forge/lib/main.dart","lib/main.dart","pubspec.yaml"]}}},{})
  self.assertEqual(guard["status"],"PASS")
  def test_retry_decision_returns_only_matching_blocked_task_to_ready(self):
   program=build_decomposition_graph().invoke({"reconcile_only":True,"decision":{"decision_id":"retry:merge-file-picker-bridge-owners","choice":"retry","reason":"fixed scope"},"worker_result":{"task_id":"merge-file-picker-bridge-owners","architecture_verdict":"REJECTED"},"decomposition_program":{"status":"PROGRAM_BLOCKED","current_migration_task":"merge-file-picker-bridge-owners","execution_blocker":{"status":"MIGRATION_NO_EFFECT","task_id":"merge-file-picker-bridge-owners"},"migration_tasks":[{"task_id":"merge-file-picker-bridge-owners","status":"BLOCKED_DECISION"}]}})["decomposition_program"]
   self.assertEqual(program["migration_tasks"][0]["status"],"READY")
   self.assertEqual(program["human_decisions"][-1]["status"],"APPLIED")
  def test_retry_consumes_codex_execution_failed_blocker_to_ready(self):
   program=build_decomposition_graph().invoke({"reconcile_only":True,"decision":{"decision_id":"retry:relocate-flutter-forge-app","choice":"retry","reason":"codex out of credits"},"worker_result":{"task_id":"relocate-flutter-forge-app","status":"CODEX_EXECUTION_FAILED"},"decomposition_program":{"status":"PROGRAM_BLOCKED","current_migration_task":None,"execution_blocker":{"status":"CODEX_EXECUTION_FAILED","task_id":"relocate-flutter-forge-app","reason":"codex"},"migration_tasks":[{"task_id":"relocate-flutter-forge-app","status":"BLOCKED_DECISION","worker_execution":{"worker_execution_id":"migration-old"}}]}})["decomposition_program"]
   task=program["migration_tasks"][0]
   self.assertEqual(task["status"],"READY")
   self.assertNotIn("worker_execution",task)
   self.assertIsNone(program.get("execution_blocker"))
   self.assertEqual(program["status"],"PLANNING_COMPLETE")
   self.assertEqual(program["current_migration_task"],"relocate-flutter-forge-app")
   self.assertEqual(program["human_decisions"][-1]["status"],"APPLIED")
  def test_retry_decision_is_idempotent_across_replays(self):
   base={"reconcile_only":True,"decision":{"decision_id":"retry:relocate-flutter-forge-app","choice":"retry"},"decomposition_program":{"status":"PROGRAM_BLOCKED","current_migration_task":None,"execution_blocker":{"status":"CODEX_EXECUTION_FAILED","task_id":"relocate-flutter-forge-app"},"human_decisions":[],"migration_tasks":[{"task_id":"relocate-flutter-forge-app","status":"BLOCKED_DECISION","worker_execution":{"worker_execution_id":"migration-old"}}]}}
   first=build_decomposition_graph().invoke(base)["decomposition_program"]
   self.assertEqual(first["migration_tasks"][0]["status"],"READY")
   self.assertEqual(len(first["human_decisions"]),1)
   replayed=build_decomposition_graph().invoke({**base,"decomposition_program":first})["decomposition_program"]
   self.assertEqual(replayed["migration_tasks"][0]["status"],"READY")
   self.assertEqual(len(replayed["human_decisions"]),1)
   self.assertIsNone(replayed.get("execution_blocker"))
  def test_codex_execution_failed_blocker_gets_retry_metadata(self):
   self.assertTrue(_needs_blocked_decision_metadata({"values":{"decomposition_program":{"execution_blocker":{"status":"CODEX_EXECUTION_FAILED","task_id":"relocate-flutter-forge-app"},"migration_tasks":[{"task_id":"relocate-flutter-forge-app","status":"BLOCKED_DECISION"}]}}}))
  def test_codex_execution_timeout_is_retryable(self):
   program=build_decomposition_graph().invoke({"reconcile_only":True,"decision":{"decision_id":"retry:relocate-flutter-forge-app","choice":"retry"},"decomposition_program":{"status":"PROGRAM_BLOCKED","current_migration_task":None,"execution_blocker":{"status":"CODEX_EXECUTION_TIMEOUT","task_id":"relocate-flutter-forge-app"},"migration_tasks":[{"task_id":"relocate-flutter-forge-app","status":"BLOCKED_DECISION"}]}})["decomposition_program"]
   self.assertEqual(program["migration_tasks"][0]["status"],"READY")
 def test_zero_change_migration_is_not_approved(self):
  self.assertTrue(_needs_done_reconciliation({"values":{"worker_result":{"task_id":"relocate-flutter-forge-app","status":"SUCCESS","scope_guard":"PASS","architecture_verdict":"APPROVED","repositories":{"flutter_forge":{"changed_files":[]}},"validation":{"architecture_guard":{"status":"PASS"}}},"decomposition_program":{"migration_tasks":[{"task_id":"relocate-flutter-forge-app","status":"DONE"}]}}}))
 def test_zero_change_running_task_requires_reconciliation(self):
  self.assertTrue(_needs_zero_change_reconciliation({"values":{"worker_result":{"task_id":"t","status":"SUCCESS","repositories":{"flutter_forge":{"changed_files":[]}}},"decomposition_program":{"migration_tasks":[{"task_id":"t","status":"RUNNING"}]}}}))
 def test_app_guard_rejection_is_reconciled_from_verified_diff(self):
  self.assertTrue(_needs_app_guard_reconciliation({"values":{"worker_result":{"task_id":"relocate-flutter-forge-app","architecture_verdict":"REJECTED","validation":{"architecture_guard":{"reason":"app_target_missing"}}},"decomposition_program":{"migration_tasks":[{"task_id":"relocate-flutter-forge-app","status":"BLOCKED_DECISION"}]}}}))
 @patch("agent_hub.gateway.decomposition.subprocess.check_output")
 @patch("agent_hub.gateway.decomposition.os.path.isdir",return_value=True)
 def test_ready_managed_dirty_requires_graph_reconciliation(self, isdir, output):
  output.side_effect=["lib/main.dart\n",""]
  state={"values":{"decomposition_program":{"current_migration_task":"relocate-flutter-forge-app","managed_worktrees":[{"repository":"flutter_forge","worktree":"/managed"}],"migration_tasks":[{"task_id":"relocate-flutter-forge-app","status":"READY","source_units":["flutter_forge/root_flutter_application"],"target_units":["apps/flutter_forge"]}]}}}
  self.assertTrue(_needs_ready_dirty_reconciliation(state))
 @patch("agent_hub.graphs.decomposition._ensure_worktree")
 def test_architecture_guard_rejects_source_deletion_without_target_owner(self, ensure):
  from pathlib import Path
  from agent_hub.graphs.decomposition import _architecture_guard
  ensure.return_value=(Path("/missing"),"decomposition/flutter_forge")
  diff="diff --git a/pubspec.yaml b/pubspec.yaml\ndeleted file mode 100644\n"
  guard=_architecture_guard({"source_units":["gcode_core"],"target_units":["packages/gcode_core"]},{"repositories":{"gcode_core":{"changed_files":["pubspec.yaml","lib/x.dart"],"diff":diff}}},{})
  self.assertEqual(guard["status"],"REJECT")
 @patch("agent_hub.graphs.decomposition._ensure_worktree")
 def test_architecture_guard_does_not_treat_modified_files_as_deletions(self, ensure):
  from pathlib import Path
  from agent_hub.graphs.decomposition import _architecture_guard
  ensure.return_value=(Path("/missing"),"decomposition/flutter_forge")
  diff="diff --git a/apps/flutter_forge/lib/app/navigation_policy.dart b/apps/flutter_forge/lib/app/navigation_policy.dart\n--- a/apps/flutter_forge/lib/app/navigation_policy.dart\n+++ b/apps/flutter_forge/lib/app/navigation_policy.dart\n@@ -1 +1 @@\n-old\n+new\n"
  guard=_architecture_guard({"source_units":["flutter_forge/apps/flutter_forge"],"target_units":["flutter_forge/apps/flutter_forge"]},{"repositories":{"flutter_forge":{"changed_files":["apps/flutter_forge/lib/app/navigation_policy.dart"],"diff":diff}}},{})
  self.assertEqual(guard["status"],"PASS")
 @patch("agent_hub.graphs.decomposition._ensure_worktree")
 def test_architecture_guard_accepts_repository_qualified_retained_target(self, ensure):
  import tempfile
  from pathlib import Path
  from agent_hub.graphs.decomposition import _architecture_guard
  with tempfile.TemporaryDirectory() as raw:
   root=Path(raw); target=root/"packages/file_picker_bridge"; (target/"lib").mkdir(parents=True); (target/"pubspec.yaml").write_text("name: file_picker_bridge\n")
   ensure.return_value=(root,"decomposition/flutter_forge")
   guard=_architecture_guard({"target_units":["flutter_forge/packages/file_picker_bridge"]},{"repositories":{"file_picker_bridge":{"changed_files":["lib/x.dart"]}}},{})
  self.assertEqual(guard["status"],"PASS")
 def test_done_without_changes_reconciles_to_blocked_decision(self):
  program=build_decomposition_graph().invoke({"reconcile_only":True,"worker_result":{"task_id":"merge-file-picker-bridge-owners","status":"SUCCESS","scope_guard":"PASS","repositories":{"file_picker_bridge":{"changed_files":[]},"flutter_forge":{"changed_files":[]}},"review":"APPROVED"},"decomposition_program":{"status":"PLANNING_COMPLETE","migration_tasks":[{"task_id":"merge-file-picker-bridge-owners","status":"DONE","source_units":[],"target_units":[]}]}})["decomposition_program"]
  self.assertEqual(program["migration_tasks"][0]["status"],"BLOCKED_DECISION")
 def test_architecture_rejection_blocks_instead_of_leaving_running(self):
  program=build_decomposition_graph().invoke({"reconcile_only":True,"worker_result":{"task_id":"merge-file-picker-bridge-owners","status":"SUCCESS","architecture_verdict":"REJECTED","validation":{"architecture_guard":{"reason":"MIGRATION_NO_EFFECT"}}},"decomposition_program":{"status":"RUNNING","current_migration_task":"merge-file-picker-bridge-owners","migration_tasks":[{"task_id":"merge-file-picker-bridge-owners","status":"RUNNING"}]}})["decomposition_program"]
  self.assertEqual(program["migration_tasks"][0]["status"],"BLOCKED_DECISION")
  self.assertEqual(program["execution_blocker"]["status"],"MIGRATION_NO_EFFECT")
 @patch("agent_hub.graphs.decomposition._ensure_worktree")
 @patch("agent_hub.graphs.decomposition._changes",return_value=[])
 @patch("agent_hub.graphs.decomposition._worker")
 def test_dispatch_evidence_precedes_running(self, worker, changes, ensure):
  from pathlib import Path
  ensure.side_effect=lambda repo,*_:(Path("/tmp") / repo,"decomposition/"+repo)
  with patch("agent_hub.graphs.decomposition.subprocess.check_output",return_value="base\n"):
   worker.return_value={"status":"WORKER_DISPATCH_FAILED","reason":"unreachable"}
   program=build_decomposition_graph().invoke({"cluster_root":"/tmp","execute":True,"decomposition_program":{"migration_tasks":[{"task_id":"merge-gcode-core-owners","source_units":["flutter_forge/packages/gcode_core"],"target_units":["packages/gcode_core"],"depends_on":[],"allowed_operations":[],"status":"READY"}]}})["decomposition_program"]
  self.assertEqual(program["migration_tasks"][0]["status"],"BLOCKED_DECISION")
  self.assertEqual(program["execution_blocker"]["status"],"WORKER_DISPATCH_FAILED")
 @patch("agent_hub.graphs.decomposition._ensure_worktree")
 @patch("agent_hub.graphs.decomposition._changes",return_value=[])
 @patch("agent_hub.graphs.decomposition._architecture_guard",return_value={"status":"PASS"})
 @patch("agent_hub.graphs.decomposition._worker")
 def test_zero_change_success_is_not_marked_done(self, worker, architecture_guard, changes, ensure):
  from pathlib import Path
  ensure.side_effect=lambda repo,*_:(Path("/tmp") / repo,"decomposition/"+repo)
  worker.return_value={"status":"SUCCESS","scope_guard":"PASS","worker_execution_id":"execution-1","worker_workspace":"/tmp/agent-hub-worker-1","dispatched_at":"now","repositories":{}}
  with patch("agent_hub.graphs.decomposition.subprocess.check_output",return_value="base\n"):
   program=build_decomposition_graph().invoke({"cluster_root":"/tmp","execute":True,"decomposition_program":{"migration_tasks":[{"task_id":"merge-gcode-core-owners","source_units":["flutter_forge/packages/gcode_core"],"target_units":["packages/gcode_core"],"depends_on":[],"allowed_operations":[],"status":"READY"}]}})["decomposition_program"]
  task=program["migration_tasks"][0]
  self.assertEqual(task["status"],"BLOCKED_DECISION")
  self.assertEqual(task["worker_execution"]["worker_execution_id"],"execution-1")
 @patch("agent_hub.graphs.decomposition._ensure_worktree")
 @patch("agent_hub.graphs.decomposition._changes",return_value=[])
 def test_stale_running_without_evidence_returns_to_ready(self, changes, ensure):
  from pathlib import Path
  ensure.side_effect=lambda repo,*_:(Path("/tmp") / repo,"decomposition/"+repo)
  program=build_decomposition_graph().invoke({"decomposition_program":{"status":"RUNNING","current_migration_task":"merge-gcode-core-owners","migration_tasks":[{"task_id":"merge-gcode-core-owners","source_units":["flutter_forge/packages/gcode_core"],"target_units":["packages/gcode_core"],"status":"RUNNING"}]}})["decomposition_program"]
  self.assertEqual(program["migration_tasks"][0]["status"],"READY")
 @patch("agent_hub.graphs.decomposition._ensure_worktree")
 @patch("agent_hub.graphs.decomposition._changes",return_value=[])
 def test_stale_dispatching_without_evidence_returns_to_ready(self, changes, ensure):
  from pathlib import Path
  ensure.side_effect=lambda repo,*_:(Path("/tmp") / repo,"decomposition/"+repo)
  program=build_decomposition_graph().invoke({"reconcile_only":True,"decomposition_program":{"status":"DISPATCHING","current_migration_task":"merge-gcode-core-owners","migration_tasks":[{"task_id":"merge-gcode-core-owners","source_units":["flutter_forge/packages/gcode_core"],"target_units":["packages/gcode_core"],"status":"DISPATCHING"}]}})["decomposition_program"]
  self.assertEqual(program["migration_tasks"][0]["status"],"READY")
  self.assertEqual(program["status"],"PLANNING_COMPLETE")
 @patch("agent_hub.graphs.decomposition._ensure_worktree")
 @patch("agent_hub.graphs.decomposition._changes",return_value=[])
 def test_dispatching_with_execution_evidence_is_blocked(self, changes, ensure):
  from pathlib import Path
  ensure.side_effect=lambda repo,*_:(Path("/tmp") / repo,"decomposition/"+repo)
  program=build_decomposition_graph().invoke({"reconcile_only":True,"decomposition_program":{"status":"DISPATCHING","current_migration_task":"merge-gcode-core-owners","migration_tasks":[{"task_id":"merge-gcode-core-owners","source_units":["flutter_forge/packages/gcode_core"],"target_units":["packages/gcode_core"],"status":"DISPATCHING","worker_execution":{"worker_execution_id":"live"}}]}})["decomposition_program"]
  self.assertEqual(program["migration_tasks"][0]["status"],"BLOCKED_DECISION")
  self.assertEqual(program["execution_blocker"]["status"],"STALE_DISPATCHING_CONFLICT")
 @patch("agent_hub.graphs.decomposition._ensure_worktree")
 @patch("agent_hub.graphs.decomposition._changes",return_value=[])
 def test_dispatching_with_persisted_worker_result_is_not_returned_to_ready(self, changes, ensure):
  from pathlib import Path
  ensure.side_effect=lambda repo,*_:(Path("/tmp") / repo,"decomposition/"+repo)
  program=build_decomposition_graph().invoke({"reconcile_only":True,"worker_result":{"task_id":"merge-gcode-core-owners","status":"CODEX_EXECUTION_FAILED"},"decomposition_program":{"status":"DISPATCHING","current_migration_task":"merge-gcode-core-owners","migration_tasks":[{"task_id":"merge-gcode-core-owners","source_units":["flutter_forge/packages/gcode_core"],"target_units":["packages/gcode_core"],"status":"DISPATCHING"}]}})["decomposition_program"]
  self.assertEqual(program["migration_tasks"][0]["status"],"BLOCKED_DECISION")
  self.assertEqual(program["execution_blocker"]["status"],"STALE_DISPATCHING_CONFLICT")
 @patch("agent_hub.graphs.decomposition._ensure_worktree")
 @patch("agent_hub.graphs.decomposition._changes",return_value=["lib/partial.dart"])
 def test_dispatching_with_unknown_dirty_is_blocked(self, changes, ensure):
  from pathlib import Path
  ensure.side_effect=lambda repo,*_:(Path("/tmp") / repo,"decomposition/"+repo)
  program=build_decomposition_graph().invoke({"reconcile_only":True,"decomposition_program":{"status":"DISPATCHING","current_migration_task":"merge-gcode-core-owners","migration_tasks":[{"task_id":"merge-gcode-core-owners","source_units":["flutter_forge/packages/gcode_core"],"target_units":["packages/gcode_core"],"status":"DISPATCHING"}]}})["decomposition_program"]
  self.assertEqual(program["execution_blocker"]["status"],"STALE_DISPATCHING_CONFLICT")
 @patch("agent_hub.graphs.decomposition._ensure_worktree")
 @patch("agent_hub.graphs.decomposition._changes",return_value=[])
 @patch("agent_hub.graphs.decomposition._worker",side_effect=RuntimeError("bridge boom"))
 def test_dispatch_bridge_exception_becomes_terminal_blocker(self, worker, changes, ensure):
  from pathlib import Path
  ensure.side_effect=lambda repo,*_:(Path("/tmp") / repo,"decomposition/"+repo)
  with patch("agent_hub.graphs.decomposition.subprocess.check_output",return_value="base\n"):
   program=build_decomposition_graph().invoke({"cluster_root":"/tmp","execute":True,"worker_endpoint":"http://worker/execute","decomposition_program":{"migration_tasks":[{"task_id":"merge-gcode-core-owners","source_units":["flutter_forge/packages/gcode_core"],"target_units":["packages/gcode_core"],"depends_on":[],"allowed_operations":[],"status":"READY"}]}})["decomposition_program"]
  self.assertEqual(program["migration_tasks"][0]["status"],"BLOCKED_DECISION")
  self.assertEqual(program["execution_blocker"]["status"],"WORKER_DISPATCH_FAILED")
 def test_staging_uses_actual_deleted_paths_not_fixed_flutter_paths(self):
  import os, tempfile
  from pathlib import Path
  with tempfile.TemporaryDirectory() as raw:
   root=Path(raw); os.system(f"git init -q {root}"); os.system(f"git -C {root} config user.email test@example.com"); os.system(f"git -C {root} config user.name test")
   (root/"lib").mkdir(); (root/"lib/value.dart").write_text("x\n"); os.system(f"git -C {root} add lib/value.dart && git -C {root} commit -qm base")
   (root/"lib/value.dart").unlink()
   result=_stage_validated_changes(root,["lib/value.dart"])
   self.assertEqual(result["status"],"STAGED")
   self.assertEqual(os.popen(f"git -C {root} diff --cached --name-status").read().strip(),"D\tlib/value.dart")
 def test_staging_no_changes_never_creates_empty_commit(self):
  from pathlib import Path
  import tempfile
  with tempfile.TemporaryDirectory() as raw:
   self.assertEqual(_stage_validated_changes(Path(raw),[])["status"],"INTEGRATION_NO_CHANGES")
 def test_worker_change_set_is_repository_scoped(self):
  from agent_hub.graphs.decomposition import _worker_change_set
  worker={"repositories":{"gcode_core":{"changed_files":["lib/a.dart"]},"flutter_forge":{"changed_files":[]}}}
  self.assertEqual(_worker_change_set(worker,"gcode_core"),["lib/a.dart"])
 def test_execute_without_checkpoint_never_invents_a_plan(self):
  program=build_decomposition_graph().invoke({"execute":True})["decomposition_program"]
  self.assertEqual(program["status"],"STATE_NOT_LOADED")
  self.assertEqual(program["migration_tasks"],[])
 def test_snapshot_round_trip_preserves_worker_and_program(self):
  import tempfile
  from pathlib import Path
  with tempfile.TemporaryDirectory() as raw, patch("agent_hub.gateway.decomposition_state.ROOT",Path(raw)):
   state={"values":{"decomposition_program":{"program_id":"flutter-forge-decomposition-program","migration_tasks":[{"task_id":"t"}]},"worker_result":{"task_id":"t","status":"SUCCESS"}}}
   save_snapshot("thread",state)
   self.assertEqual(load_snapshot("thread")["worker_result"]["task_id"],"t")
 def test_snapshot_validation_rejects_wrong_thread_and_missing_worktrees(self):
  snapshot={"schema_version":1,"thread_id":"a","decomposition_program":{"program_id":"flutter-forge-decomposition-program","cluster_root":"/Users/forest/code/langGraph","migration_tasks":[{"task_id":"t"}],"managed_worktrees":[]}}
  self.assertEqual(validate_snapshot(snapshot,"b","/Users/forest/code/langGraph"),"STATE_UNRECOVERABLE")
  self.assertIsNone(validate_snapshot(snapshot,"a","/Users/forest/code/langGraph"))
 def test_agent_owned_dirty_requires_managed_branch_base_and_scope(self):
  import os, tempfile
  from pathlib import Path
  with tempfile.TemporaryDirectory() as raw:
    root=Path(raw); os.system(f"git init -q {root}"); os.system(f"git -C {root} config user.email test@example.com"); os.system(f"git -C {root} config user.name test"); (root/'packages/gcode_core/lib').mkdir(parents=True); (root/'packages/gcode_core/lib/a.dart').write_text('a'); os.system(f"git -C {root} add . && git -C {root} commit -qm base && git -C {root} checkout -qb decomposition/flutter_forge")
    head=os.popen(f"git -C {root} rev-parse HEAD").read().strip(); (root/'packages/gcode_core/lib/a.dart').unlink()
    task={"task_id":"merge-gcode-core-owners"}
    self.assertEqual(_classify_managed_dirty(task,'flutter_forge',root,head)["classification"],"AGENT_STALE_DIRTY")
    self.assertEqual(_restore_agent_owned_dirty(root,head,['packages/gcode_core/lib/a.dart'])["status"],"RESTORED")
 def test_unknown_dirty_is_not_agent_owned(self):
  import os, tempfile
  from pathlib import Path
  with tempfile.TemporaryDirectory() as raw:
    root=Path(raw); os.system(f"git init -q {root}"); os.system(f"git -C {root} config user.email test@example.com"); os.system(f"git -C {root} config user.name test"); (root/'README.md').write_text('a'); os.system(f"git -C {root} add . && git -C {root} commit -qm base && git -C {root} checkout -qb decomposition/flutter_forge")
    head=os.popen(f"git -C {root} rev-parse HEAD").read().strip(); (root/'README.md').write_text('user')
    self.assertEqual(_classify_managed_dirty({"task_id":"merge-gcode-core-owners"},'flutter_forge',root,head)["classification"],"USER_UNKNOWN_DIRTY")
