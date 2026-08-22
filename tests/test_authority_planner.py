import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from agent_hub.planning.authority_planner import AuthorityPlanner
from agent_hub.projects.discovery import discover
from agent_hub.schemas.models import MigrationPlan
from agent_hub.workspace.config import WorkspaceConfig

class AuthorityPlannerTest(unittest.TestCase):
 def test_authority_file_is_persisted_and_declares_canonical_targets(self):
  data=json.loads((Path(__file__).parents[1]/'architecture/flutter-study-plugin-authority.json').read_text())
  self.assertEqual(data['provenance'],'HUMAN_REVIEW_P6_3')
  self.assertEqual(len(data['canonical_targets']),2)
 def test_build_with_authority_emits_only_adoption_and_host_validation(self):
  # P6.3 task generation is restricted to dependency adoption plus host
  # validation. The archived p6-3 plan held this invariant; guard it directly
  # on the AuthorityPlanner so a future planner change cannot reintroduce a
  # source-move (MOVE_*) task into the adoption path.
  with tempfile.TemporaryDirectory() as raw:
   root=Path(raw)
   canonical=root/'flutter_study_learning'; (canonical/'lib').mkdir(parents=True)
   (canonical/'lib/widgets.dart').write_text('class A {}\n'); (canonical/'pubspec.yaml').write_text('name: flutter_study_learning\n')
   host=root/'flutter_forge'; (host/'lib').mkdir(parents=True); (host/'packages/flutter_study_learning/lib').mkdir(parents=True)
   (host/'pubspec.yaml').write_text('name: flutter_forge_app\ndependencies:\n  flutter_study_learning:\n    path: packages/flutter_study_learning\n')
   (host/'packages/flutter_study_learning/pubspec.yaml').write_text('name: flutter_study_learning\n')
   (host/'packages/flutter_study_learning/lib/widgets.dart').write_text('class A {}\n')
   (host/'lib/main.dart').write_text("import 'package:flutter_study_learning/widgets.dart';\nvoid main() { A a; }\n")
   for repo in (canonical,host):
    subprocess.run(['git','init','-q'],cwd=repo,check=True); subprocess.run(['git','-C',repo,'config','user.email','t@e.c'],check=True); subprocess.run(['git','-C',repo,'config','user.name','t'],check=True)
    subprocess.run(['git','-C',repo,'add','.'],check=True); subprocess.run(['git','-C',repo,'commit','-qm','base'],check=True)
   config=WorkspaceConfig(workspace_root=root,allowed_paths=[root],registry_path=root/'bootstrap.json',registry_storage_path=root/'registry.json')
   (root/'registry.json').write_text(json.dumps(discover(config).model_dump(mode='json')))
   authority=root/'authority.json'; authority.write_text(json.dumps({'canonical_targets':[{'source_candidate':'flutter_forge:packages/flutter_study_learning','canonical_repository':'flutter_study_learning'}]}))
   base=MigrationPlan(plan_id='p',requirement='adopt',target_repository='flutter_forge',source_analysis_ref={},status='PLANNED')
   plan=AuthorityPlanner(config).build_with_authority('adopt','flutter_forge',base,str(authority))
  self.assertTrue(plan.migration_tasks)
  self.assertTrue(all(x.action_type in ('UPDATE_DEPENDENCY','VALIDATE_INTEGRATION') for x in plan.migration_tasks))
  self.assertTrue(all(x.migration_delta.status=='ADOPTION_ONLY' for x in plan.migration_tasks))
