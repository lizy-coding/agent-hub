import tempfile,unittest
from pathlib import Path
from agent_hub.execution.migration_executor import WorktreeManager
from agent_hub.execution.path_dependencies import RelativePathDependencyAvailabilityGuard
class MigrationExecutorTest(unittest.TestCase):
 def test_canonical_relative_path_guard(self):
  with tempfile.TemporaryDirectory() as raw:
   root=Path(raw);(root/'flutter_forge').mkdir();(root/'gcode_core').mkdir()
   self.assertTrue(WorktreeManager(root/'flutter_forge',root/'gcode_core').canonical_relative_ok())
 def test_missing_path_dependency_is_detected(self):
  with tempfile.TemporaryDirectory() as raw:
   root=Path(raw);(root/'pubspec.yaml').write_text('dependencies:\n  a:\n    path: ../a\n')
   item=RelativePathDependencyAvailabilityGuard().inspect(root)[0]
   self.assertFalse(item['exists'])
 def test_dependency_guard_reports_identity(self):
  with tempfile.TemporaryDirectory() as raw:
   root=Path(raw);(root/'provider').mkdir();(root/'provider'/'pubspec.yaml').write_text('name: provider\n');(root/'app').mkdir();(root/'app'/'pubspec.yaml').write_text('dependencies:\n  provider:\n    path: ../provider\n')
   item=RelativePathDependencyAvailabilityGuard().inspect(root/'app')[0]
   self.assertEqual(item['package_identity'],'provider')
