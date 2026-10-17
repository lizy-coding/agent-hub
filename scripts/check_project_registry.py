#!/usr/bin/env python3
"""Check project identity, runtime boundaries, and explicit evidence policies."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from agent_hub.projects.decomposition_config import DEFAULT_REGISTRY
from agent_hub.projects.registry_check import check_project_registry


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--registry', type=Path, default=DEFAULT_REGISTRY)
    args = parser.parse_args()
    result = check_project_registry(args.registry)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['ok'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
