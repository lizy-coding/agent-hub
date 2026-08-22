import json,tempfile,unittest
from pathlib import Path
from agent_hub.workspace.config import WorkspaceConfig
from agent_hub.workspace.runtime import RuntimeWorkspaceProvider

class RuntimeWorkspaceTest(unittest.TestCase):
 def config(self,root):
  (root/'flutter_forge').mkdir();return WorkspaceConfig(workspace_root=root,allowed_paths=[root],registry_path=root/'bootstrap.json',runtime={'environment':'HOSTED','runtime_root':str(root),'checkout_root':str(root),'primary_repository_id':'flutter_forge','repositories':{'flutter_forge':{'runtime_path':str(root/'flutter_forge'),'role':'PRIMARY','managed':True,'writable':True},'ref':{'runtime_path':str(root/'flutter_forge'),'role':'REFERENCE','managed':False,'writable':False}}})
 def test_identity_is_independent_of_runtime_root_and_permissions_apply(self):
  with tempfile.TemporaryDirectory() as raw:
   provider=RuntimeWorkspaceProvider.from_config(self.config(Path(raw)));self.assertEqual(provider.get_primary_repository().repository_id,'flutter_forge');self.assertEqual(provider.resolve_path('flutter_forge','lib/x.dart'),(Path(raw)/'flutter_forge/lib/x.dart').resolve());self.assertRaises(PermissionError,provider.assert_writable,'ref','x');self.assertRaises(ValueError,provider.resolve_path,'flutter_forge','../escape')
 def test_file_paths_resolve_relative_to_config_location(self):
  with tempfile.TemporaryDirectory() as raw:
   base=Path(raw); (base/'workspace').mkdir(); (base/'repo').mkdir(); config_path=base/'workspace/config.json'
   config_path.write_text(json.dumps({'workspace_root':'..','registry_path':'registry.json','registry_storage_path':'generated.json','runtime':{'primary_repository_id':'repo','repositories':{'repo':{'runtime_path':'../repo','managed':True,'writable':True}}}}))
   config=WorkspaceConfig.from_file(config_path); provider=RuntimeWorkspaceProvider.from_config(config)
   self.assertEqual(config.workspace_root,base.resolve()); self.assertEqual(config.registry_path,(base/'workspace/registry.json').resolve()); self.assertEqual(provider.get_primary_repository().runtime_path,(base/'repo').resolve())
