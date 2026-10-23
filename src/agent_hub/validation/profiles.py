"""Explicit fixture menus; never discover business sources or start a benchmark."""
from pathlib import Path
import os
import subprocess
import sys

PROFILES = {
    'workflow': ['tests.test_learning_workflows'],
    'maintenance': ['tests.test_sync_plan', 'tests.test_project_maintenance', 'tests.test_agent_context',
                    'tests.test_agent_context_integrity', 'tests.test_bounded_context'],
    'execution': ['tests.test_validation_cache', 'tests.test_execution_control', 'tests.test_completion_evidence'],
    'release': ['tests.test_release_contract', 'tests.test_release_program', 'tests.test_release_integrity'],
}


def run_profile(name: str) -> int:
    if name not in PROFILES:
        print(f'Unknown test profile: {name}; choose {", ".join(PROFILES)}', file=sys.stderr)
        return 2
    env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'}
    return subprocess.run([sys.executable, '-m', 'unittest', *PROFILES[name]],
                          cwd=Path(__file__).resolve().parents[3], env=env).returncode
