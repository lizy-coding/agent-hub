"""Validator caches stay outside the frozen output tree in the default environment."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_hub.execution.validation import run_checks


class ValidationCacheTest(unittest.TestCase):
    def test_default_python_validator_does_not_create_bytecode_in_tree(self):
        with tempfile.TemporaryDirectory() as raw:
            root=Path(raw)
            (root/'test_suite.py').write_text('import unittest\nclass TestOK(unittest.TestCase):\n def test_ok(self): self.assertTrue(True)\n')
            with patch.dict(os.environ,{'PYTHONDONTWRITEBYTECODE':'','PYTHONPYCACHEPREFIX':str(root/'bad-cache')}):
                receipts=run_checks(root,[{'check_id':'python_unittest:test_suite','cwd':'.','timeout_seconds':30}],'a'*40)
            self.assertEqual(receipts[0]['status'],'PASS',receipts)
            self.assertFalse((root/'__pycache__').exists())
            self.assertFalse((root/'bad-cache').exists())
            self.assertEqual(receipts[0]['environment']['cache_scope'],'OUTSIDE_OUTPUT_TREE')

    def test_actual_source_mutation_is_still_visible(self):
        with tempfile.TemporaryDirectory() as raw:
            root=Path(raw)
            (root/'model.txt').write_text('before')
            (root/'test_suite.py').write_text("from pathlib import Path\nPath('model.txt').write_text('changed')\n")
            run_checks(root,[{'check_id':'python_unittest:test_suite','cwd':'.','timeout_seconds':30}],'b'*40)
            self.assertEqual((root/'model.txt').read_text(),'changed')
            # The executor's validation_changed_output gate remains enabled;
            # tests.test_execution_control verifies that it rejects this mutation.
