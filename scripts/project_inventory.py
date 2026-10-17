#!/usr/bin/env python3
"""Print bounded project facts from the registered explicit contract intake."""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from agent_hub.projects.decomposition_config import DEFAULT_REGISTRY
from agent_hub.projects.sync_plan import build_sync_plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True)
    parser.add_argument('--registry', type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument('--max-files', type=int, default=64)
    parser.add_argument('--profile', default='maintenance')
    args = parser.parse_args()
    try:
        plan = build_sync_plan([args.project], registry_path=args.registry,
                               max_files=args.max_files, profile=args.profile)
        project = plan['projects'][0]
        print(json.dumps({'project_id': project['project_id'], 'status': project['status'],
                          'plan_id': project.get('plan_id'), 'blockers': project.get('blockers', []),
                          'gaps': project.get('gaps', []), 'inventory': project.get('project_inventory')},
                         ensure_ascii=False, indent=2))
        return plan['exit_code']
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
