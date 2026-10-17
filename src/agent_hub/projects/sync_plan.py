"""One bounded fact-capture round; no execution or checkpoint mutation."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from agent_hub.projects.agent_context import _refresh_project, _validate_output, _write_snapshot, _workspace_config
from agent_hub.projects.decomposition_config import AGENT_HUB_ROOT, DEFAULT_REGISTRY, load_decomposition_project
from agent_hub.projects.registry_check import check_project_registry

DEFAULT_OUTPUT = AGENT_HUB_ROOT / 'workspace' / 'sync-plan.json'


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def resolve_profile(entry: dict, name: str = 'maintenance') -> dict:
    profiles = entry.get('sync_profiles')
    if profiles is not None:
        if not isinstance(profiles, dict) or name not in profiles:
            raise ValueError(f'unknown sync profile: {name}')
        policy = profiles[name]
    else:
        if name != 'maintenance':
            raise ValueError(f'unknown sync profile: {name}')
        # Registry fixtures and external registries may supply the old fields.
        # They are input data only, never independent capture phases.
        policy = {'required_files': [], 'candidate_paths': list(dict.fromkeys([
            *((entry.get('project_inventory') or {}).get('candidate_paths', [])),
            *((entry.get('agent_context') or {}).get('seed_files', []))]))}
    if not isinstance(policy, dict):
        raise ValueError('sync profile must be a mapping')
    for field in ('required_files', 'candidate_paths'):
        values = policy.get(field, [])
        if not isinstance(values, list) or any(not isinstance(p, str) or not p or Path(p).is_absolute() or '..' in Path(p).parts or '\\' in p or any(c in p for c in '\0\n\r') for p in values):
            raise ValueError(f'unsafe sync profile {field}')
    return {'required_files': list(dict.fromkeys(policy.get('required_files', []))),
            'candidate_paths': list(dict.fromkeys(policy.get('candidate_paths', [])))}


def project_queue(texts: dict[str, str]) -> dict:
    if 'REFACTOR_PLAN.md' not in texts:
        return {'status': 'NOT_OBSERVED', 'tasks': [], 'unknowns': []}
    try:
        payload = json.loads(texts['REFACTOR_PLAN.md'])
        entries = payload.get('work_queue', [])
        if not isinstance(entries, list):
            raise ValueError('work_queue must be a list')
        tasks, ids = [], set()
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get('id'), str) or not entry['id'] or entry['id'] in ids:
                raise ValueError('task ids must be nonempty and unique')
            ids.add(entry['id'])
            task = {'task_id': entry['id'], 'priority': entry.get('priority'), 'project_status': entry.get('status', 'unknown')}
            for key in ('depends_on', 'targets', 'acceptance', 'evidence'):
                values = entry.get(key, [])
                if not isinstance(values, list):
                    raise ValueError(f'task {key} must be a list')
                task[key] = values
            task.update(allowed_operations=[], allowed_paths_by_repository={}, execution_authority='FROZEN_PROPOSAL_REQUIRED')
            tasks.append(task)
        gaps = [f'QUEUE_DEPENDENCY_NOT_OBSERVED: {task["task_id"]}: {dependency}' for task in tasks for dependency in task['depends_on'] if dependency not in ids]
        return {'status': 'PARTIAL' if gaps else 'OBSERVED', 'tasks': tasks, 'unknowns': gaps,
                'source': 'REFACTOR_PLAN.md', 'contract_sha256': hashlib.sha256(texts['REFACTOR_PLAN.md'].encode()).hexdigest()}
    except (ValueError, AttributeError, TypeError) as error:
        return {'status': 'INVALID', 'tasks': [], 'unknowns': [f'QUEUE_INVALID: {error}']}


def queue_delta(current: list[dict], previous: list[dict] | None) -> dict:
    if previous is None:
        return {'status': 'NO_PREVIOUS_OBSERVATION', 'added': [], 'removed': [], 'changed': []}
    old, new = {x['task_id']: x for x in previous}, {x['task_id']: x for x in current}
    return {'status': 'COMPARED', 'added': sorted(new.keys() - old.keys()), 'removed': sorted(old.keys() - new.keys()),
            'changed': [{'task_id': key, 'before': old[key], 'after': new[key]} for key in sorted(old.keys() & new.keys()) if old[key] != new[key]]}


def _facts(texts: dict[str, str], entry: dict) -> dict:
    from agent_hub.projects.release_contract import inspect_release_contract
    return {'project_work_queue': project_queue(texts), 'release_contract': inspect_release_contract(texts, entry.get('release') or {})}


def classify(project: dict) -> dict:
    selected = {x['path'] for x in project.get('selected_files', [])}
    required = project.get('required_files', [])
    blockers = [f'REQUIRED_INPUT_NOT_OBSERVED: {p}' for p in required if p not in selected]
    if not selected.intersection({'AGENTS.md', 'AGENTS.override.md'}):
        blockers.append('REQUIRED_ROOT_GUIDE_NOT_OBSERVED')
    if project.get('version') is None:
        blockers.append('PRIMARY_VERSION_NOT_OBSERVED')
    warnings, partial = [], []
    for gap in project.get('unknowns', []):
        if any(gap.startswith(prefix + ': ' + path + ':') for prefix in ('MANIFEST_INVALID', 'MANIFEST_UNREADABLE', 'MANIFEST_NOT_A_MAPPING') for path in required):
            blockers.append(gap)
        elif gap.startswith(('DIRTY_WORKSPACE:', 'UNTRACKED_EXPLICIT_FILE:')):
            warnings.append(gap)
        elif gap.startswith(('SOURCE_CHANGED_DURING_CAPTURE', 'CONFIG_CHANGED_DURING_CAPTURE', 'GIT_SOURCE_SHA_UNAVAILABLE', 'REQUIRED_AGENT_GUIDE_UNAVAILABLE', 'REQUIRED_ROOT_GUIDE', 'REQUIRED_LOCAL_MANIFEST_UNSAFE')):
            blockers.append(gap)
        else:
            partial.append(gap)
    facts = project.get('project_facts', {})
    queue = facts.get('project_work_queue', {})
    if queue.get('status') == 'INVALID' and 'REFACTOR_PLAN.md' in required:
        blockers.extend(queue['unknowns'])
    else:
        partial.extend(queue.get('unknowns', []))
    contract = facts.get('release_contract', {})
    if contract.get('status') == 'INVALID' and contract.get('source') in required:
        blockers.extend(contract.get('unknowns', []))
    else:
        partial.extend(contract.get('unknowns', []))
    return {'status': 'BLOCKED' if blockers else 'PARTIAL' if partial else 'SUCCESS',
            'blockers': sorted(set(blockers)), 'gaps': sorted(set(partial)), 'warnings': sorted(set(warnings))}


def exit_code(plan: dict) -> int:
    statuses = [x.get('status') for x in plan.get('projects', [])]
    if plan.get('errors') or 'BLOCKED' in statuses or not statuses:
        return 2
    return 1 if 'PARTIAL' in statuses else 0


def build_sync_plan(project_ids: list[str] | None = None, *, registry_path: Path | None = None,
                    max_files: int = 64, profile: str = 'maintenance', requirement: str | None = None,
                    output_path: Path | None = None, previous: dict | None = None, checkpoint_paths: dict[str, Path] | None = None) -> dict:
    if type(max_files) is not int or not 1 <= max_files <= 64:
        raise ValueError('max_files must be an integer between 1 and 64')
    if requirement is not None and (not isinstance(requirement, str) or not requirement.strip()):
        raise ValueError('requirement must be nonempty text')
    path = Path(os.environ.get('AGENT_HUB_PROJECT_REGISTRY') or registry_path or DEFAULT_REGISTRY).expanduser().resolve()
    registry_bytes = path.read_bytes()
    payload = json.loads(registry_bytes)
    check = check_project_registry(path)
    entries = payload.get('projects', {})
    aliases = payload.get('aliases', {})
    if not isinstance(entries, dict) or not isinstance(aliases, dict):
        raise ValueError('projects and aliases must be mappings')
    ids = list(dict.fromkeys(aliases.get(p, p) if isinstance(aliases.get(p, p), str) else p for p in (project_ids if project_ids is not None else entries)))
    errors = [e for e in check['errors'] if e['project_id'] is None]
    project_errors = {p: [e['reason'] for e in check['errors'] if e['project_id'] == p] for p in ids}
    if output_path is not None:
        output_path = Path(output_path).expanduser().resolve()
        if any(output_path == Path(file).expanduser().resolve() for file in (checkpoint_paths or {}).values()):
            raise ValueError('sync output must not overwrite an execution checkpoint')
        # Protect every readable config/runtime, including unselected projects.
        _validate_output(output_path, path, payload)
    if previous is not None and (not isinstance(previous, dict) or previous.get('schema_version') != 'sync-plan.v1' or not isinstance(previous.get('projects'), list)):
        raise ValueError('previous must be a sync-plan.v1 observation')
    results = []
    prior_projects = {p['project_id']:p for p in (previous or {}).get('projects', []) if isinstance(p, dict) and 'project_id' in p}
    for project_id in ids:
        entry = entries.get(project_id)
        if errors or project_errors[project_id] or not isinstance(entry, dict):
            results.append({'project_id': project_id, 'status': 'BLOCKED', 'blockers': project_errors[project_id] or ['INVALID_REGISTRY' if errors else 'UNKNOWN_PROJECT'], 'gaps': [], 'warnings': [], 'acceptance': False})
            continue
        try:
            policy = resolve_profile(entry, profile)
            config_path = Path(entry['workspace_config'])
            config_path = config_path if config_path.is_absolute() else AGENT_HUB_ROOT / config_path
            config_bytes = config_path.read_bytes()
            config = _workspace_config(entry)
            project_config = load_decomposition_project(project_id, registry_path=path)
            if registry_bytes != path.read_bytes() or config_bytes != config_path.read_bytes():
                raise ValueError('CONFIG_CHANGED_BEFORE_CAPTURE')
            observation = _refresh_project(project_id, entry, path, max_files, {path}, requirement,
                                           intake_profile=policy, project_facts=lambda texts: _facts(texts, entry),
                                           project_config=project_config, workspace_config=config)
            if registry_bytes != path.read_bytes() or config_bytes != config_path.read_bytes():
                observation['unknowns'].append('CONFIG_CHANGED_DURING_CAPTURE')
            outcome = classify(observation)
            result = {**observation, 'capture_status': observation['status'], **outcome, 'profile': profile,
                      'allowed_operations': [], 'allowed_paths_by_repository': {}, 'execution_authority': 'FROZEN_PROPOSAL_REQUIRED',
                      'runtime_checkpoint': {'status': 'NOT_INSPECTED', 'reason': 'local_fact_capture_only'}}
            facts = result.get('project_facts', {})
            old = prior_projects.get(project_id)
            old_queue = ((old.get('project_facts') or {}).get('project_work_queue') or {}).get('tasks') if old else None
            result['queue_delta'] = queue_delta(facts.get('project_work_queue', {}).get('tasks', []), old_queue)
            checkpoint = (checkpoint_paths or {}).get(project_id)
            if checkpoint is not None:
                result['runtime_checkpoint'] = inspect_checkpoint(checkpoint, project_id, entry)
                if result['runtime_checkpoint']['status'] == 'INVALID':
                    result['status'] = 'BLOCKED'
                    result['blockers'].append('CHECKPOINT_IDENTITY_MISMATCH')
            binding = {'runtime': project_config.graph_input(), 'checkpoint_sha256': result['runtime_checkpoint'].get('sha256'),
                       'previous_queue_sha256': digest(old_queue) if old_queue is not None else None,
                       'registry_sha256': hashlib.sha256(registry_bytes).hexdigest(),
                       'workspace_config_sha256': hashlib.sha256(config_bytes).hexdigest(),
                       'profile': policy, 'profile_name': profile, 'max_files': max_files, 'requirement': requirement,
                       'source_snapshot_id': result['source_snapshot_id']}
            result['plan_id'] = digest(binding)
            result['capture_binding'] = binding
            results.append(result)
        except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as error:
            results.append({'project_id': project_id, 'status': 'BLOCKED', 'blockers': [str(error)], 'gaps': [], 'warnings': [], 'acceptance': False})
    plan = {'schema_version': 'sync-plan.v1', 'generated_at': datetime.now(UTC).isoformat(), 'mode': 'PLAN_ONLY',
            'acceptance': False, 'allowed_operations': [], 'allowed_paths_by_repository': {},
            'execution_authority': 'FROZEN_PROPOSAL_REQUIRED', 'read_only_business_repositories': True,
            'no_walk': True, 'registry_check': check, 'errors': errors, 'projects': results,
            'budget': {'max_files_per_project_per_round': max_files, 'shared_by_all_projections': True},
            'summary': {kind.lower():sum(p['status'] == kind for p in results) for kind in ('SUCCESS', 'PARTIAL', 'BLOCKED')}}
    plan['exit_code'] = exit_code(plan)
    plan['plan_id'] = digest({'registry_sha256': hashlib.sha256(registry_bytes).hexdigest(),
                              'profile':profile, 'max_files':max_files, 'requirement':requirement,
                              'projects':[p.get('plan_id') or {'project_id':p['project_id'], 'blockers':p['blockers']} for p in results]})
    if output_path is not None:
        _write_snapshot(output_path, plan)
    return plan


def inspect_checkpoint(file: Path, project_id: str, entry: dict) -> dict:
    """Observe one explicit local file; never call status/rehydrate/reconcile."""
    try:
        file = Path(file)
        if file.stat().st_size > 16 * 1024 * 1024:
            raise ValueError('checkpoint too large')
        raw = file.read_bytes()
        state = json.loads(raw)
        if state.get('schema_version') not in {1, 2}:
            raise ValueError('unsupported checkpoint schema')
        program = state['decomposition_program']
        expected_program = entry.get('program_id', f'{project_id}-decomposition-program')
        if program.get('project_id') != project_id or program.get('program_id') != expected_program:
            raise ValueError('checkpoint project or program mismatch')
        namespace = entry.get('snapshot_namespace', project_id)
        if state.get('schema_version') == 2 and state.get('project_id') != namespace:
            raise ValueError('checkpoint namespace mismatch')
        return {'status':'OBSERVED_LOCAL_FILE', 'path':str(file), 'sha256':hashlib.sha256(raw).hexdigest(),
                'latest_state':'UNVERIFIED', 'project_id':project_id, 'program_id':expected_program,
                'integration_head':program.get('integration_head'), 'orchestration_sync':program.get('orchestration_sync'),
                'execution_status':program.get('status'), 'effect':'READ_ONLY_NO_RECONCILIATION'}
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        return {'status':'INVALID', 'reason':str(error)}
