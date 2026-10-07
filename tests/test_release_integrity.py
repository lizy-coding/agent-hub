import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_hub.execution.control import digest, file_lock
from agent_hub.graphs.release_hosting import _remote_checksum, build_release_hosting_graph
from agent_hub.policies.safety import validate_release_command


class ReleaseIntegrityTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='release-integrity-fixture-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / 'installer.zip').write_bytes(b'good')
        self.artifact = {'path': 'installer.zip', 'asset_name': 'installer.zip',
                         'size': 4, 'sha256': hashlib.sha256(b'good').hexdigest()}
        self.program = {'primary_repository_id': 'product', 'github_repo': 'fixture/product',
                        'release': {'tag': 'v1.0.0', 'name': 'fixture', 'artifacts': [self.artifact]}}
        self.context = {'repository_paths': {'product': str(self.root)}}
        self.download = b'good'
        self.commands = []

    def runner(self, argv):
        self.commands.append(argv)
        stdout = ''
        if argv[1:3] == ['release', 'view']:
            stdout = json.dumps({'url': 'https://example.invalid/release',
                                 'assets': [{'name': 'installer.zip', 'size': 4}]})
        if argv[1:3] == ['release', 'download']:
            directory = Path(argv[argv.index('--dir')+1])
            (directory / 'installer.zip').write_bytes(self.download)
        return {'returncode': 0, 'stdout': stdout, 'stderr': ''}

    def execute(self):
        with patch('agent_hub.graphs.release_hosting._run', side_effect=self.runner):
            return build_release_hosting_graph().invoke({'release_program': self.program,
                                                        'project_context': self.context, 'execute': True})

    def test_remote_size_and_sha256_are_both_required(self):
        result = self.execute()
        self.assertEqual(result['release_program']['status'], 'PUBLISHED')
        artifact = result['release_program']['release']['artifacts'][0]
        self.assertEqual(artifact['remote_sha256'], self.artifact['sha256'])
        self.assertTrue(any(argv[1:3] == ['release', 'download'] for argv in self.commands))

    def test_equal_size_different_remote_content_is_not_published(self):
        self.download = b'evil'
        result = self.execute()
        self.assertEqual(result['release_program']['status'], 'PROGRAM_BLOCKED')
        self.assertEqual(result['verify_result']['status'], 'CHECKSUM_MISMATCH')

    def test_download_failure_or_missing_file_preserves_unverified_status(self):
        with patch('agent_hub.graphs.release_hosting._gh', return_value={'ok': False}):
            self.assertEqual(_remote_checksum('fixture/product', 'v1.0.0', self.artifact)['status'], 'FAIL')
        with patch('agent_hub.graphs.release_hosting._gh', return_value={'ok': True}):
            self.assertEqual(_remote_checksum('fixture/product', 'v1.0.0', self.artifact)['status'], 'FAIL')

    def test_artifact_changed_after_preflight_is_not_uploaded(self):
        original = self.runner
        def mutate(argv):
            value = original(argv)
            if argv[1:3] == ['repo', 'view']:
                (self.root / 'installer.zip').write_bytes(b'evil')
            return value
        with patch('agent_hub.graphs.release_hosting._run', side_effect=mutate):
            result = build_release_hosting_graph().invoke({'release_program': self.program,
                                                          'project_context': self.context, 'execute': True})
        self.assertEqual(result['release_program']['execution_blocker']['status'], 'ARTIFACT_CHECKSUM_MISMATCH')
        self.assertFalse(any(argv[1:3] == ['release', 'upload'] for argv in self.commands))

    def test_plan_only_does_not_access_remote_or_publish(self):
        with patch('agent_hub.graphs.release_hosting._run', side_effect=AssertionError('network forbidden')):
            result = build_release_hosting_graph().invoke({'release_program': self.program,
                                                          'project_context': self.context, 'execute': False})
        self.assertEqual(result['release_program']['execution_mode'], 'PLAN_ONLY')
        self.assertNotEqual(result['release_program'].get('status'), 'PUBLISHED')

    def test_release_writer_lock_blocks_publication(self):
        control=self.root/'control'
        lock=control/'release-locks'/f"{digest(['fixture/product','v1.0.0'])}.lock"
        with file_lock(lock), patch('agent_hub.graphs.release_hosting._run',side_effect=self.runner):
            result=build_release_hosting_graph(control).invoke({'release_program':self.program,
                                                               'project_context':self.context,'execute':True})
        self.assertEqual(result['release_program']['execution_blocker']['status'],'RELEASE_BUSY')
        self.assertFalse(any(argv[1:3]==['release','upload'] for argv in self.commands))

    def test_download_cannot_escape_asset_or_change_repository(self):
        for name in ('../escape', '*.zip', 'dir/name', ''):
            with self.subTest(name=name):
                self.assertEqual(_remote_checksum('fixture/product', 'v1.0.0', {**self.artifact, 'asset_name': name})['status'], 'FAIL')
        self.assertEqual(validate_release_command(['gh','release','download','v1.0.0','--repo','fixture/other'], 'fixture/product')['status'], 'REJECT')
        self.assertEqual(validate_release_command(['gh','release','view','v1.0.0'], 'fixture/product')['status'], 'REJECT')
        self.assertEqual(validate_release_command(['gh','release','delete','v1.0.0','--repo','fixture/product'], 'fixture/product')['status'], 'REJECT')


if __name__ == '__main__': unittest.main()
