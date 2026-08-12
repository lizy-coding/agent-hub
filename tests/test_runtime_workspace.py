import json,tempfile,unittest
from pathlib import Path
from agent_hub.workspace.config import WorkspaceConfig
from agent_hub.workspace.runtime import RuntimeWorkspaceProvider

class RuntimeWorkspaceTest(unittest.TestCase):
 def config(self,root):
  (root/'flutter_study').mkdir();return WorkspaceConfig(workspace_root=root,allowed_paths=[root],registry_path=root/'bootstrap.json',runtime={'environment':'HOSTED','runtime_root':str(root),'checkout_root':str(root),'primary_repository_id':'flutter_study','repositories':{'flutter_study':{'runtime_path':str(root/'flutter_study'),'role':'PRIMARY','managed':True,'writable':True},'ref':{'runtime_path':str(root/'flutter_study'),'role':'REFERENCE','managed':False,'writable':False}}})
 def test_identity_is_independent_of_runtime_root_and_permissions_apply(self):
  with tempfile.TemporaryDirectory() as raw:
   provider=RuntimeWorkspaceProvider.from_config(self.config(Path(raw)));self.assertEqual(provider.get_primary_repository().repository_id,'flutter_study');self.assertEqual(provider.resolve_path('flutter_study','lib/x.dart'),(Path(raw)/'flutter_study/lib/x.dart').resolve());self.assertRaises(PermissionError,provider.assert_writable,'ref','x');self.assertRaises(ValueError,provider.resolve_path,'flutter_study','../escape')
