"""Validate declared project metadata without discovering business source."""
from __future__ import annotations

import json
import re
from pathlib import Path

from agent_hub.projects.adapters import get_adapter
from agent_hub.projects.decomposition_config import AGENT_HUB_ROOT, DEFAULT_REGISTRY
from agent_hub.tools.path_guard import is_allowed_business_path
from agent_hub.workspace.config import WorkspaceConfig


def check_project_registry(registry_path: Path = DEFAULT_REGISTRY) -> dict:
    errors, warnings, resolved, identities = [], [], [], {}
    def error(project, message):
        errors.append({'project_id': project, 'reason': message})
    try:
        payload = json.loads(registry_path.read_text(encoding='utf-8'))
        if not isinstance(payload, dict) or not isinstance(payload.get('projects'), dict):
            raise ValueError('projects must be a mapping')
    except (OSError, ValueError) as exc:
        return {'ok': False, 'errors': [{'project_id': None, 'reason': str(exc)}], 'warnings': [], 'projects': []}
    projects = payload['projects']
    if payload.get('default_project') not in projects:
        error(None, 'default_project is not registered')
    aliases = payload.get('aliases', {})
    if not isinstance(aliases, dict):
        error(None, 'aliases must be a mapping')
        aliases = {}
    for alias, target in aliases.items():
        if not isinstance(target, str) or target not in projects or alias in projects:
            error(None, f'invalid alias: {alias}')
    for project_id, entry in projects.items():
        try:
            if not isinstance(entry, dict):
                raise ValueError('project entry must be a mapping')
            get_adapter(entry.get('adapter') or project_id)
            for field, default in [('program_id', f'{project_id}-decomposition-program'), ('refactor_program_id', f'{project_id}-refactor-program'), ('snapshot_namespace', project_id)]:
                value = entry.get(field, default)
                if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', value):
                    raise ValueError(f'{field} must be nonempty text')
                key = (field, value)
                if key in identities:
                    error(project_id, f'duplicate {field}: {value} ({identities[key]})')
                identities[key] = project_id
            raw_path = entry.get('workspace_config')
            if not isinstance(raw_path, str) or not raw_path:
                raise ValueError('workspace_config is required')
            path = Path(raw_path)
            path = path if path.is_absolute() else AGENT_HUB_ROOT / path
            config = WorkspaceConfig.from_file(path)
            runtime = config.runtime
            primary = runtime.get('primary_repository_id')
            repositories = runtime.get('repositories')
            if not isinstance(repositories, dict) or primary not in repositories:
                raise ValueError('explicit primary runtime repository is required')
            if entry.get('adapter') == 'flutter_forge' and primary != 'flutter_forge':
                error(project_id, 'flutter_forge adapter requires primary_repository_id=flutter_forge')
            for repository_id, repository in repositories.items():
                if not isinstance(repository, dict) or not repository.get('runtime_path'):
                    raise ValueError(f'runtime_path required: {repository_id}')
                for flag in ('managed', 'writable'):
                    if not isinstance(repository.get(flag, False), bool):
                        error(project_id, f'{flag} must be boolean: {repository_id}')
                if repository_id == primary and repository.get('role', 'PRIMARY') != 'PRIMARY':
                    error(project_id, 'primary repository role must be PRIMARY')
                root = Path(repository['runtime_path'])
                if not is_allowed_business_path(root, config):
                    error(project_id, f'runtime path outside configured boundary: {repository_id}')
                if repository.get('writable') and not repository.get('managed'):
                    error(project_id, f'writable repository is not managed: {repository_id}')
            if 'sync_profiles' in entry:
                from agent_hub.projects.sync_plan import resolve_profile
                profiles = entry['sync_profiles']
                if not isinstance(profiles, dict) or 'maintenance' not in profiles:
                    raise ValueError('maintenance sync profile is required')
                for name in profiles:
                    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', name):
                        raise ValueError('invalid sync profile name')
                    resolve_profile(entry, name)
            context = entry.get('agent_context') or {}
            primary_manifest = context.get('primary_manifest', 'pubspec.yaml')
            policy = entry.get('project_inventory') or {}
            limit = policy.get('max_files', 24)
            if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 64:
                error(project_id, 'inventory max_files must be between 1 and 64')
            for field, values in [('seed_files', context.get('seed_files', [])), ('change_prefixes', context.get('change_prefixes', [])), ('candidate_paths', policy.get('candidate_paths', [])), ('primary_manifest', [primary_manifest])]:
                if not isinstance(values, list):
                    error(project_id, f'{field} must be a list')
                    continue
                for value in values:
                    if not isinstance(value, str) or not value or Path(value).is_absolute() or '..' in Path(value).parts:
                        error(project_id, f'unsafe {field}: {value}')
            if len(context.get('seed_files', [])) > 24:
                warnings.append({'project_id': project_id, 'reason': 'seed list exceeds default context budget; ancestor guides also consume budget'})
            resolved.append({'project_id': project_id, 'adapter': entry.get('adapter'), 'primary_repository_id': primary,
                             'repository_path': repositories[primary]['runtime_path'], 'writable': repositories[primary].get('writable', False)})
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            error(project_id, str(exc))
    return {'ok': not errors, 'errors': errors, 'warnings': warnings, 'projects': resolved, 'source_discovery_performed': False}
