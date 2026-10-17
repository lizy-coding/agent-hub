"""Compare the captured release workflow with declared Hub publication policy."""
from __future__ import annotations

import re

import yaml


def inspect_release_contract(texts: dict[str, str], policy: dict) -> dict:
    binding = policy.get('workflow_contract')
    if not binding:
        return {'status': 'NOT_CONFIGURED', 'unknowns': []}
    file = binding.get('path', '.github/workflows/release.yml')
    if file not in texts:
        return {'status': 'NOT_OBSERVED', 'unknowns': [f'RELEASE_WORKFLOW_NOT_OBSERVED: {file}']}
    gaps, observations = [], {}
    try:
        workflow = yaml.safe_load(texts[file])
        build = workflow['jobs'][binding.get('build_job', 'build')]
        quality = binding.get('quality_job', 'quality')
        needs = build.get('needs', [])
        needs = [needs] if isinstance(needs, str) else needs
        if quality not in needs:
            gaps.append('RELEASE_QUALITY_DEPENDENCY_MISSING')
        steps = build.get('steps', [])
        ref = next((step.get('with', {}).get('ref') for step in steps if 'actions/checkout@' in str(step.get('uses', ''))), None)
        if ref != '${{ needs.' + quality + '.outputs.source-sha }}':
            gaps.append('RELEASE_SOURCE_SHA_BINDING_MISSING')
        rows = build.get('strategy', {}).get('matrix', {}).get('include', [])
        labels = binding.get('platform_labels', {})
        for platform in policy.get('platforms', []):
            row = next((row for row in rows if row.get('platform') == labels.get(platform)), None)
            expected = policy.get('build_matrix', {}).get(platform, {})
            if row is None:
                gaps.append(f'RELEASE_PLATFORM_MISSING: {platform}')
                continue
            if row.get('os') != expected.get('runner'):
                gaps.append(f'RELEASE_RUNNER_DRIFT: {platform}')
            observations[platform] = {'runner': row.get('os'), 'label': row.get('platform')}
        for key, expected in binding.get('environment', {}).items():
            if str((workflow.get('env') or {}).get(key)) != str(expected):
                gaps.append(f'RELEASE_TOOLCHAIN_DRIFT: {key}')
        stage = next((step.get('run') for step in steps if step.get('name') == binding.get('staging_step')), None)
        if not isinstance(stage, str):
            gaps.append('RELEASE_STAGING_CONTRACT_MISSING')
            stage = ''
        normalized = re.sub(r'\$\{?APP_VERSION\}?', '<version>', stage)
        for platform in policy.get('platforms', []):
            for filename in policy.get('build_matrix', {}).get(platform, {}).get('artifacts', []):
                if filename.rsplit('/', 1)[-1] not in normalized:
                    gaps.append(f'RELEASE_ARTIFACT_FORMAT_DRIFT: {platform}: {filename}')
        return {'status': 'DRIFT' if gaps else 'MATCH', 'unknowns': gaps, 'observed_platforms': observations,
                'source': file, 'evidence_scope': 'WORKFLOW_DECLARATION_ONLY', 'remote_acceptance': False}
    except (KeyError, TypeError, AttributeError, yaml.YAMLError) as error:
        return {'status': 'INVALID', 'source': file, 'unknowns': [f'RELEASE_WORKFLOW_INVALID: {error}']}


def freeze_release_provenance(root, config: dict, version: str, tag: str, artifacts: list[dict], spec: dict) -> dict:
    """Freeze four exact producer manifests; missing evidence blocks publication."""
    import hashlib
    import json
    import subprocess
    from pathlib import Path
    root = Path(root).resolve()
    policy = config.get('provenance_policy')
    if not policy:
        return {'status': 'NOT_REQUIRED', 'artifacts': artifacts}
    try:
        source = str(spec.get('source_sha') or subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True, stderr=subprocess.DEVNULL).strip())
        if not re.fullmatch(r'[0-9a-f]{40}', source):
            raise ValueError('full source SHA is required')
        platforms = config['platforms']
        labels = config['workflow_contract']['platform_labels']
        supplied = spec.get('provenance_manifests')
        paths = supplied if supplied is not None else [f'{config.get("artifact_root", "release")}/{version}/RELEASE_MANIFEST-{labels[p]}.json' for p in platforms]
        if not isinstance(paths, list) or len(paths) != len(platforms) or len(set(paths)) != len(paths):
            raise ValueError('one exact provenance manifest per required platform is required')
        by_name = {a['asset_name']:a for a in artifacts}
        if len(by_name) != len(artifacts):
            raise ValueError('duplicate artifact names')
        frozen, assigned, observed = [], {}, set()
        for value in paths:
            if not isinstance(value, str):
                raise ValueError('manifest paths must be strings')
            relative = Path(value)
            file = root / relative
            if relative.is_absolute() or '..' in relative.parts or file.resolve() != file or file.suffix != '.json' or file.stat().st_size > 1024*1024:
                raise ValueError('unsafe provenance manifest path')
            raw = file.read_bytes(); manifest = json.loads(raw)
            label = manifest.get('platform')
            platform = next((p for p in platforms if labels[p] == label), None)
            if platform is None or platform in observed:
                raise ValueError('unexpected or duplicate platform manifest')
            observed.add(platform)
            expected = config['build_matrix'][platform]
            if manifest.get('schema') != policy['schema'] or manifest.get('source_sha') != source:
                raise ValueError('producer schema or source SHA mismatch')
            if str(manifest.get('version', '')).split('+')[0] != version or manifest.get('tag') not in (None, tag):
                raise ValueError('producer version or tag mismatch')
            if not str(manifest.get('run_id', '')).isdigit() or int(manifest['run_id']) < 1 or not str(manifest.get('run_attempt', '')).isdigit() or int(manifest['run_attempt']) < 1:
                raise ValueError('CI run and attempt required')
            if manifest.get('architecture') != expected['architecture']:
                raise ValueError('architecture evidence missing or mismatched')
            if manifest.get('toolchain') != policy['toolchain']:
                raise ValueError('toolchain evidence missing or mismatched')
            if manifest.get('build_mode') != expected.get('build_mode', 'release') or manifest.get('signing') != expected['signing']:
                raise ValueError('build mode or signing evidence mismatch')
            producer_artifacts = manifest.get('artifacts')
            if not isinstance(producer_artifacts, list) or not producer_artifacts:
                raise ValueError('producer artifacts required')
            expected_name = Path(expected['artifacts'][0].replace('<version>', version)).name
            if expected_name not in [a.get('name') for a in producer_artifacts if isinstance(a, dict)]:
                raise ValueError('expected platform artifact missing')
            for asset in producer_artifacts:
                name = asset.get('name')
                if name not in by_name or name in assigned or not re.fullmatch(r'[0-9a-f]{64}', str(asset.get('sha256'))) or type(asset.get('size')) is not int or asset['size'] < 1:
                    raise ValueError('artifact identity, size or checksum mismatch')
                old = by_name[name]
                if old.get('sha256') and old['sha256'] != asset['sha256']:
                    raise ValueError('spec checksum differs from producer manifest')
                assigned[name] = {**old, 'sha256':asset['sha256'], 'size':asset['size'], 'platform':platform}
            frozen.append({'path':value, 'sha256':hashlib.sha256(raw).hexdigest(), 'platform':platform,
                           'producer_platform':label, 'run_id':str(manifest['run_id']), 'run_attempt':int(manifest['run_attempt']),
                           'source_sha':source, 'architecture':manifest['architecture'], 'toolchain':manifest['toolchain'],
                           'build_mode':manifest['build_mode'], 'signing':manifest['signing']})
        if observed != set(platforms) or assigned.keys() != by_name.keys():
            raise ValueError('required platform set or artifact set incomplete')
        return {'status':'FROZEN', 'source_sha':source, 'required_platforms':platforms,
                'workflow_name':policy['workflow_name'], 'manifests':frozen,
                'artifacts':[assigned[a['asset_name']] for a in artifacts]}
    except (OSError, ValueError, TypeError, KeyError, AttributeError, subprocess.CalledProcessError) as error:
        return {'status':'BLOCKED', 'reason':str(error)}
