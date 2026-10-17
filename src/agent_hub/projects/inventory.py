"""Project facts from explicit, frozen contracts; never grant execution scope."""
from __future__ import annotations

import hashlib
import json
import posixpath
import subprocess
from pathlib import Path

import yaml


def manifest_versions(texts: dict[str, str], primary_manifest: str = 'pubspec.yaml') -> dict:
    manifests, unknowns = [], []
    for path, text in sorted(texts.items()):
        if Path(path).name != 'pubspec.yaml':
            continue
        try:
            data = yaml.safe_load(text)
            if not isinstance(data, dict):
                raise ValueError('manifest must be a mapping')
            if data.get('name') is not None and not isinstance(data['name'], str):
                raise ValueError('manifest name must be text')
            manifests.append({'manifest': path, 'name': data.get('name'), 'version': str(data['version']) if data.get('version') is not None else None})
        except (yaml.YAMLError, ValueError) as error:
            unknowns.append(f'MANIFEST_INVALID: {path}: {error}')
    primary = next((item for item in manifests if item['manifest'] == primary_manifest), None)
    if primary is None or primary['version'] is None:
        unknowns.append(f'PRIMARY_VERSION_NOT_OBSERVED: {primary_manifest}')
    return {'version': primary['version'] if primary else None, 'version_source': primary_manifest if primary and primary['version'] is not None else None,
            'primary_manifest': primary_manifest, 'manifest_versions': manifests, 'unknowns': unknowns}


def project_inventory(texts: dict[str, str], repository_id: str, primary_manifest: str = 'pubspec.yaml') -> dict:
    """Keep declared ownership distinct from architecture policy and acceptance."""
    versions = manifest_versions(texts, primary_manifest)
    unknowns = list(versions['unknowns'])
    manifests = {}
    for item in versions['manifest_versions']:
        data = yaml.safe_load(texts[item['manifest']])
        manifests[item['manifest']] = data
    names = {}
    for path, data in manifests.items():
        name = data.get('name')
        if name in names:
            unknowns.append(f'DUPLICATE_PACKAGE_NAME: {name}')
        if name:
            names[name] = str(Path(path).parent)
        members = data.get('workspace', [])
        if isinstance(members, list):
            for member in members:
                if not isinstance(member, str):
                    unknowns.append(f'WORKSPACE_MEMBER_INVALID: {path}')
                elif posixpath.normpath(posixpath.join(str(Path(path).parent), member, 'pubspec.yaml')) not in manifests:
                    unknowns.append(f'WORKSPACE_MEMBER_NOT_OBSERVED: {member}')
    candidates, capabilities, edges = [], [], []
    for path, data in sorted(manifests.items()):
        owner = str(Path(path).parent)
        deps = data.get('dependencies') or {}
        if not isinstance(deps, dict) or any(not isinstance(key, str) for key in deps):
            unknowns.append(f'DEPENDENCIES_INVALID: {path}')
            deps = {}
        candidates.append({'package_id': owner, 'target_path': owner, 'package_type': 'APP_ONLY' if path == primary_manifest and owner.startswith('apps/') else 'MANIFEST_DECLARED',
                           'package_name': data.get('name'), 'version': str(data['version']) if data.get('version') is not None else None,
                           'dependencies': sorted(deps), 'dependency_specs': deps, 'owned_capabilities': [], 'evidence': [path]})
        for name, spec in sorted(deps.items()):
            if isinstance(spec, dict) and isinstance(spec.get('path'), str):
                target = posixpath.normpath(posixpath.join(owner, spec['path']))
                if target == names.get(name):
                    edges.append([owner, target])
                else:
                    unknowns.append(f'LOCAL_DEPENDENCY_NOT_OBSERVED: {path}: {name}: {target}')
    ids = set()
    for path, text in sorted(texts.items()):
        if Path(path).name != 'AI_ANALYSIS.md':
            continue
        try:
            data = json.loads(text)
            if not isinstance(data, dict):
                raise ValueError('contract must be a mapping')
            mode = data.get('mode')
            if mode not in {'module_contract', 'package_contract'}:
                continue
            node = data.get('node')
            if not isinstance(node, dict) or not isinstance(node.get('id'), str) or not node['id']:
                raise ValueError('contract node.id required')
            if node['id'] in ids:
                raise ValueError('duplicate contract node.id')
            ids.add(node['id'])
            for field in ('owns', 'depends'):
                if not isinstance(data.get(field, []), list) or any(not isinstance(v, str) for v in data.get(field, [])):
                    raise ValueError(f'{field} must be a string list')
            source = str(Path(path).parent)
            owners = [str(Path(p).parent) for p in manifests if Path(p).parent == Path(source) or Path(p).parent in Path(source).parents]
            owner = max(owners, key=lambda p: len(Path(p).parts)) if owners else None
            support = data.get('platform_support')
            platforms = None
            if support is not None and not isinstance(support, dict):
                raise ValueError('platform_support must be a mapping')
            if isinstance(support, dict):
                for field in ('target_platforms', 'excluded_platforms'):
                    if not isinstance(support.get(field, []), list) or any(not isinstance(v, str) for v in support.get(field, [])):
                        raise ValueError(f'{field} must be a string list')
                platforms = [p for p in support.get('target_platforms', []) if p not in support.get('excluded_platforms', [])]
            elif isinstance(data.get('supported_platforms'), list):
                platforms = data['supported_platforms']
            if mode == 'module_contract' and platforms is None:
                unknowns.append(f'PLATFORM_DECLARATION_NOT_OBSERVED: {path}')
            capability = {'capability_id': node['id'], 'contract_id': node['id'], 'current_owners': [f'{repository_id}/{source}'],
                          'source_paths': [f'{repository_id}/{source}'], 'target_package': owner,
                          'declared_responsibilities': data.get('owns', []), 'dependencies': data.get('depends', []),
                          'route': data.get('route'), 'declared_status': node.get('status'), 'supported_platforms': platforms,
                          'classification': 'KEEP_PACKAGE' if mode == 'package_contract' else 'KEEP_APP_ONLY',
                          'evidence': [path], 'acceptance': False}
            if owner is None:
                unknowns.append(f'OWNER_MANIFEST_NOT_OBSERVED: {path}')
            capabilities.append(capability)
            for candidate in candidates:
                if candidate['package_id'] == owner:
                    candidate['owned_capabilities'].append(node['id'])
        except (ValueError, TypeError) as error:
            unknowns.append(f'CONTRACT_INVALID: {path}: {error}')
    nodes = sorted(item['package_id'] for item in candidates)
    # Detect cycles only within the observed local dependency graph.
    adjacency = {node: [b for a, b in edges if a == node] for node in nodes}
    cycles, visiting, visited = [], [], set()
    def visit(node):
        if node in visiting:
            cycle = visiting[visiting.index(node):] + [node]
            if cycle not in cycles:
                cycles.append(cycle)
            return
        if node in visited:
            return
        visiting.append(node)
        for target in adjacency.get(node, []):
            visit(target)
        visiting.pop()
        visited.add(node)
    for node in nodes:
        visit(node)
    return {'schema_version': 'project-inventory.v1', **versions, 'capabilities': capabilities, 'package_candidates': candidates,
            'target_dependency_graph': {'nodes': nodes, 'edges': edges, 'cycles': cycles}, 'unknowns': list(dict.fromkeys(unknowns)),
            'acceptance': False, 'allowed_paths_by_repository': {}, 'execution_authority': 'FROZEN_PROPOSAL_REQUIRED',
            'files': [{'path': p, 'sha256': hashlib.sha256(t.encode()).hexdigest()} for p, t in sorted(texts.items())]}


def read_project_inventory(root: Path, repository_id: str, policy: dict, primary_manifest: str) -> dict:
    """Read only listed files and their active ancestor guides within one budget."""
    from agent_hub.context.resolver import ancestor_agent_rules
    root = root.resolve()
    def observation():
        try:
            revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True, stderr=subprocess.DEVNULL).strip()
            status = subprocess.check_output(['git', 'status', '--short'], cwd=root, text=True, stderr=subprocess.DEVNULL)
            return {'revision': revision, 'worktree_status': 'DIRTY' if status else 'CLEAN', 'changed_paths': [line[3:] for line in status.splitlines()]}
        except (OSError, subprocess.CalledProcessError):
            return {'revision': None, 'worktree_status': 'UNKNOWN', 'changed_paths': []}
    source_before = observation()
    limit = policy.get('max_files', 24)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 64:
        raise ValueError('inventory max_files must be between 1 and 64')
    paths = policy.get('candidate_paths', [])
    if not isinstance(paths, list) or any(not isinstance(p, str) for p in paths):
        raise ValueError('inventory candidate_paths must be a string list')
    texts, unknowns, attempted = {}, [], set()
    def capture(relative):
        if relative in attempted:
            return relative in texts
        if len(attempted) >= limit:
            unknowns.append(f'BUDGET_EXHAUSTED: {relative}')
            return False
        attempted.add(relative)
        path = root / relative
        try:
            if Path(relative).is_absolute() or '..' in Path(relative).parts or path.resolve() != path or not path.is_file():
                raise ValueError('missing or unsafe explicit file')
            texts[relative] = path.read_text(encoding='utf-8')
            return True
        except (OSError, UnicodeError, ValueError) as error:
            unknowns.append(f'FILE_UNAVAILABLE: {relative}: {error}')
            return False
    for relative in dict.fromkeys(paths):
        path = root / relative
        if Path(relative).is_absolute() or '..' in Path(relative).parts:
            unknowns.append(f'UNSAFE_CANDIDATE: {relative}')
            continue
        guides = ancestor_agent_rules(root, path)
        if not any(g.parent == root for g in guides):
            unknowns.append('GUIDE_MISSING: AGENTS.md or AGENTS.override.md')
        if all([capture(g.relative_to(root).as_posix()) for g in guides]):
            capture(relative)
    result = project_inventory(texts, repository_id, primary_manifest)
    result['unknowns'] = list(dict.fromkeys(unknowns + result['unknowns']))
    for relative, text in texts.items():
        try:
            if hashlib.sha256((root / relative).read_bytes()).hexdigest() != hashlib.sha256(text.encode()).hexdigest():
                result['unknowns'].append(f'SOURCE_CHANGED_DURING_INTAKE: {relative}')
        except OSError:
            result['unknowns'].append(f'SOURCE_CHANGED_DURING_INTAKE: {relative}')
    result['source_observation'] = observation()
    if source_before['revision'] is None or result['source_observation']['revision'] is None:
        result['unknowns'].append('SOURCE_REVISION_UNAVAILABLE')
    elif source_before != result['source_observation']:
        result['unknowns'].append('SOURCE_CHANGED_DURING_INTAKE: git metadata')
    result['metrics'] = {'max_files': limit, 'inspected_files': len(attempted), 'no_walk': True}
    return result


def merge_inventory(program: dict, inventory: dict) -> dict:
    """Overlay observed facts, preserving legacy capability IDs and policy fields."""
    program['project_inventory'] = inventory
    capability_ids = {}
    for observed in inventory['capabilities']:
        matches = [c for c in program['capabilities'] if c.get('source_paths') == observed['source_paths']]
        if matches:
            capability_ids[observed['capability_id']] = [c['capability_id'] for c in matches]
            for existing in matches:
                existing.update({k: v for k, v in observed.items() if k not in {'capability_id', 'classification', 'target_package', 'evidence'} and v is not None})
                existing['evidence'] = sorted(set(existing.get('evidence', []) + observed['evidence']))
        else:
            capability_ids[observed['capability_id']] = [observed['capability_id']]
            program['capabilities'].append(observed)
    for raw in inventory['package_candidates']:
        observed = {**raw, 'owned_capabilities': sorted({value for key in raw['owned_capabilities'] for value in capability_ids.get(key, [key])})}
        existing = next((c for c in program['package_candidates'] if c['package_id'] == observed['package_id']), None)
        if existing:
            existing.update({k: v for k, v in observed.items() if k not in {'package_type', 'owned_capabilities'}})
            existing['owned_capabilities'] = sorted(set(existing.get('owned_capabilities', []) + observed['owned_capabilities']))
        elif observed['package_id'] != '.':
            program['package_candidates'].append(observed)
    program['observed_dependency_graph'] = inventory['target_dependency_graph']
    return program
