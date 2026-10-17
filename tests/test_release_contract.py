"""Workflow drift and frozen producer provenance without network or publication."""
import hashlib
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import yaml
from agent_hub.projects.release_contract import inspect_release_contract, freeze_release_provenance
from agent_hub.graphs.release_hosting import build_release_hosting_graph
from agent_hub.policies.safety import validate_release_command


class ReleaseContractTest(unittest.TestCase):
    def fixture(self):
        labels={'macos-x64':'macos','windows-x64':'windows','android-arm64':'android','web':'web'}
        ext={'macos-x64':'dmg','windows-x64':'exe','android-arm64':'apk','web':'zip'}
        matrix={p:{'runner':'fixture-runner','architecture':'x64' if p!='web' else 'not applicable',
                   'signing':'unsigned' if p!='web' else 'not applicable','artifacts':[f'verified/Forge-<version>-{p}.{ext[p]}']} for p in labels}
        policy={'platforms':list(labels),'build_matrix':matrix,
                'workflow_contract':{'path':'release.yml','platform_labels':labels,'staging_step':'Stage','environment':{'FLUTTER_VERSION':'3.47.2'}},
                'provenance_policy':{'schema':'flutter_forge.release_manifest.v1','toolchain':{'flutter':'3.47.2'},'workflow_name':'Release installers','ci_artifact_name_template':'forge-{platform}-{source_sha}'}}
        workflow={'env':{'FLUTTER_VERSION':'3.47.2'},'jobs':{'build':{'needs':'quality','strategy':{'matrix':{'include':[{'platform':label,'os':'fixture-runner'} for label in labels.values()]}},
            'steps':[{'uses':'actions/checkout@v7','with':{'ref':'${{ needs.quality.outputs.source-sha }}'}},
                     {'name':'Stage','run':'\n'.join(v['artifacts'][0].replace('<version>','${APP_VERSION}') for v in matrix.values())}]}}}
        return policy,workflow

    def test_workflow_drift_reports_platform_runner_asset_and_source(self):
        policy,w=self.fixture()
        self.assertEqual(inspect_release_contract({'release.yml':yaml.safe_dump(w)},policy)['status'],'MATCH')
        w['jobs']['build']['strategy']['matrix']['include'].pop()
        w['jobs']['build']['strategy']['matrix']['include'][0]['os']='other'
        w['jobs']['build']['steps'][0]['with']['ref']='main'
        w['jobs']['build']['steps'][1]['run']='directory-only'
        gaps=inspect_release_contract({'release.yml':yaml.safe_dump(w)},policy)['unknowns']
        for name in ['RELEASE_PLATFORM_MISSING','RELEASE_RUNNER_DRIFT','RELEASE_SOURCE_SHA_BINDING_MISSING','RELEASE_ARTIFACT_FORMAT_DRIFT']:
            self.assertIn(name,str(gaps))

    def producer_fixture(self,root):
        policy,_=self.fixture(); artifacts=[]; manifests=[]
        for platform in policy['platforms']:
            expected=policy['build_matrix'][platform]
            name=Path(expected['artifacts'][0].replace('<version>','1.0.0')).name
            file=root/name;file.write_bytes(platform.encode())
            checksum=hashlib.sha256(file.read_bytes()).hexdigest()
            artifacts.append({'path':name,'asset_name':name,'sha256':'','status':'PENDING'})
            data={'schema':'flutter_forge.release_manifest.v1','source_sha':'a'*40,'version':'1.0.0+1','tag':'v1.0.0',
                  'platform':policy['workflow_contract']['platform_labels'][platform],'run_id':'123','run_attempt':'1',
                  'architecture':expected['architecture'],'toolchain':{'flutter':'3.47.2'},'build_mode':'release','signing':expected['signing'],
                  'artifacts':[{'name':name,'size':file.stat().st_size,'sha256':checksum}]}
            manifest=root/f'{platform}.json';manifest.write_text(json.dumps(data));manifests.append(manifest.name)
        spec={'source_sha':'a'*40,'provenance_manifests':manifests}
        return policy,artifacts,spec

    def test_freeze_requires_every_platform_and_toolchain_architecture_signing(self):
        with tempfile.TemporaryDirectory() as raw:
            root=Path(raw);policy,assets,spec=self.producer_fixture(root)
            proof=freeze_release_provenance(root,policy,'1.0.0','v1.0.0',assets,spec)
            self.assertEqual(proof['status'],'FROZEN',proof)
            for field in ['source_sha','architecture','toolchain','signing','run_id']:
                file=root/spec['provenance_manifests'][0];before=file.read_text();data=json.loads(before);data.pop(field);file.write_text(json.dumps(data))
                self.assertEqual(freeze_release_provenance(root,policy,'1.0.0','v1.0.0',assets,spec)['status'],'BLOCKED',field)
                file.write_text(before)
            self.assertEqual(freeze_release_provenance(root,policy,'1.0.0','v1.0.0',assets,{**spec,'provenance_manifests':spec['provenance_manifests'][:-1]})['status'],'BLOCKED')

    def program(self,root):
        policy,assets,spec=self.producer_fixture(root)
        proof=freeze_release_provenance(root,policy,'1.0.0','v1.0.0',assets,spec)
        return {'project_id':'fixture','github_repo':'org/product','cluster_root':str(root.parent),
                'repositories':[{'repository_id':'fixture','path':str(root)}],'primary_repository_id':root.name,
                'execution_mode':'PLAN_ONLY','status':'READY','provenance_policy':policy['provenance_policy'],
                'release':{'tag':'v1.0.0','version':'1.0.0','artifacts':proof['artifacts'],
                           'provenance':{k:v for k,v in proof.items() if k!='artifacts'}}}

    def test_manifest_change_or_missing_platform_blocks_without_network(self):
        with tempfile.TemporaryDirectory() as raw:
            root=Path(raw);program=self.program(root)
            file=root/program['release']['provenance']['manifests'][0]['path'];file.write_text(file.read_text()+'\n')
            with patch('agent_hub.graphs.release_hosting._run',side_effect=AssertionError('no network')):
                result=build_release_hosting_graph(root/'control').invoke({'release_program':program,'execute':False})
            self.assertEqual(result['release_program']['execution_blocker']['status'],'RELEASE_PROVENANCE_CHANGED')
            program=self.program(root);program['release']['artifacts'].pop()
            with patch('agent_hub.graphs.release_hosting._run',side_effect=AssertionError('no network')):
                result=build_release_hosting_graph(root/'control').invoke({'release_program':program,'execute':False})
            self.assertEqual(result['release_program']['execution_blocker']['status'],'RELEASE_PLATFORMS_INCOMPLETE')

    def test_ci_sha_mismatch_blocks_before_publication_and_lane_is_read_only(self):
        with tempfile.TemporaryDirectory() as raw:
            root=Path(raw);program=self.program(root);commands=[]
            def runner(argv):
                commands.append(argv)
                if argv[1:3]==['run','view']:
                    return {'returncode':0,'stdout':json.dumps({'headSha':'b'*40,'attempt':1,'status':'completed','conclusion':'success','workflowName':'Release installers'}),'stderr':''}
                return {'returncode':0,'stdout':'{}','stderr':''}
            with patch('agent_hub.graphs.release_hosting._run',side_effect=runner):
                result=build_release_hosting_graph(root/'control').invoke({'release_program':program,'execute':True})
            self.assertEqual(result['release_program']['execution_blocker']['status'],'RELEASE_CI_SOURCE_UNVERIFIED')
            self.assertFalse(any(argv[1:3] in [['release','create'],['release','upload']] for argv in commands))
            read=['gh','run','view','123','--attempt','1','--repo','org/product','--json','attempt,headSha,status,conclusion,workflowName']
            self.assertEqual(validate_release_command(read,'org/product')['status'],'PASS')
            self.assertEqual(validate_release_command(read,'org/other')['status'],'REJECT')
            self.assertEqual(validate_release_command(['gh','run','rerun','123','--repo','org/product'],'org/product')['status'],'REJECT')

    def test_successful_ci_run_without_matching_producer_manifest_still_blocks(self):
        with tempfile.TemporaryDirectory() as raw:
            root=Path(raw);program=self.program(root);commands=[]
            def runner(argv):
                commands.append(argv)
                if argv[1:3]==['run','view']:
                    return {'returncode':0,'stdout':json.dumps({'headSha':'a'*40,'attempt':1,'status':'completed','conclusion':'success','workflowName':'Release installers'}),'stderr':''}
                return {'returncode':0,'stdout':'{}','stderr':''}
            with patch('agent_hub.graphs.release_hosting._run',side_effect=runner):
                result=build_release_hosting_graph(root/'control').invoke({'release_program':program,'execute':True})
            self.assertEqual(result['release_program']['execution_blocker']['status'],'RELEASE_CI_ARTIFACT_UNVERIFIED')
            self.assertFalse(any(argv[1:3] in [['release','create'],['release','upload']] for argv in commands))

    def test_complete_ci_proof_publishes_and_rechecks_before_any_publication(self):
        for mutate in [False, True]:
            with self.subTest(mutate=mutate), tempfile.TemporaryDirectory() as raw:
                root=Path(raw);program=self.program(root);commands=[];created=False
                release=program['release']
                by_label={m['producer_platform']:m for m in release['provenance']['manifests']}
                by_name={a['asset_name']:a for a in release['artifacts']}
                def runner(argv):
                    nonlocal created
                    commands.append(argv)
                    data='{}';code=0
                    if argv[1:3]==['run','view']:
                        data=json.dumps({'headSha':'a'*40,'attempt':1,'status':'completed','conclusion':'success','workflowName':'Release installers'})
                    elif argv[1:3]==['run','download']:
                        name=argv[argv.index('--name')+1]
                        label=name[len('forge-'):-(len('a'*40)+1)]
                        dest=Path(argv[argv.index('--dir')+1])
                        (dest/f'RELEASE_MANIFEST-{label}.json').write_bytes((root/by_label[label]['path']).read_bytes())
                        if mutate:
                            (root/release['artifacts'][0]['path']).write_bytes(b'changed after remote check')
                    elif argv[1:3]==['release','view']:
                        if not created:code=1
                        else:data=json.dumps({'url':'https://example.invalid/release','assets':[{'name':n,'size':a['size']} for n,a in by_name.items()]})
                    elif argv[1:3]==['release','create']:
                        created=True
                    elif argv[1:3]==['release','download']:
                        name=argv[argv.index('--pattern')+1]
                        dest=Path(argv[argv.index('--dir')+1]);(dest/name).write_bytes((root/by_name[name]['path']).read_bytes())
                    return {'returncode':code,'stdout':data,'stderr':''}
                with patch('agent_hub.graphs.release_hosting._run',side_effect=runner):
                    result=build_release_hosting_graph(root/'control').invoke({'release_program':program,'execute':True})
                if mutate:
                    self.assertEqual(result['release_program']['status'],'PROGRAM_BLOCKED')
                    self.assertFalse(any(argv[1:3] in [['release','create'],['release','upload']] for argv in commands))
                else:
                    self.assertEqual(result['release_program']['status'],'PUBLISHED',result)
                    self.assertTrue(any(argv[1:3]==['release','download'] for argv in commands))

    def test_release_version_never_uses_workspace_package_as_application(self):
        from agent_hub.projects.flutter_forge_adapter import _app_version
        with tempfile.TemporaryDirectory() as raw:
            root=Path(raw);(root/'pubspec.yaml').write_text('name: workspace\nversion: 9.9.9\n')
            self.assertEqual(_app_version(root),'')
