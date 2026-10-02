"""Read the independently maintained G-code package's current build facts."""
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET

import yaml


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(
        ['git', *args], cwd=root, text=True, stderr=subprocess.DEVNULL
    ).strip()


def _android_contract(root: Path) -> dict[str, object]:
    gradle = root / 'example/android/app/build.gradle.kts'
    text = gradle.read_text(encoding='utf-8') if gradle.is_file() else ''
    manifest = root / 'example/android/app/src/main/AndroidManifest.xml'
    gpu_enabled = False
    if manifest.is_file():
        try:
            application = ET.fromstring(manifest.read_text(encoding='utf-8')).find('application')
            if application is not None:
                namespace = '{http://schemas.android.com/apk/res/android}'
                gpu_enabled = any(
                    item.get(f'{namespace}name') == 'io.flutter.embedding.android.EnableFlutterGPU'
                    and item.get(f'{namespace}value') == 'true'
                    for item in application.findall('meta-data')
                )
        except ET.ParseError:
            pass
    return {
        'status': 'BUILD_READY_RUNTIME_PENDING' if gradle.is_file() else 'UNSUPPORTED',
        'minimum_api': 29 if 'minSdk = 29' in text else None,
        'abis': ['arm64-v8a'] if 'abiFilters += "arm64-v8a"' in text else [],
        'flutter_gpu_enabled': gpu_enabled,
        'host_configuration': 'GPU_ENABLED' if gpu_enabled else 'GPU_METADATA_MISSING_OR_INVALID',
        'evidence': [str(path.relative_to(root)) for path in (gradle, manifest) if path.is_file()],
        'build_command': 'flutter build apk --debug --target-platform android-arm64',
        'runtime_acceptance': 'PENDING_NATIVE_GPU_DEVICE_EVIDENCE',
        'detailed_acceptance': 'PENDING',
    }


def _maintainer_acceptance(root: Path, version: str) -> dict[str, object]:
    acceptance = {
        'status': 'UNKNOWN', 'version': version, 'platforms': [], 'evidence': [],
        'detailed_acceptance': 'PENDING',
    }
    if not re.fullmatch(r'\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.+-]+)?', version):
        return acceptance
    path = root / f'docs/evidence/{version}-maintainer-acceptance.md'
    if not path.is_file():
        return acceptance
    acceptance['evidence'] = [str(path.relative_to(root))]
    content = ' '.join(path.read_text(encoding='utf-8').split())
    confirmation = (
        'The maintainer explicitly confirmed that macOS and Android manual acceptance '
        f'passed and authorized publication as {version}.'
    )
    date = re.search(r'Date: (\d{4}-\d{2}-\d{2})\.', content)
    baseline = re.search(r'Source baseline: ([0-9a-f]{7,40})\.', content)
    if confirmation in content and date and baseline:
        acceptance.update({
            'status': 'MAINTAINER_CONFIRMED', 'platforms': ['macos', 'android'],
            'date': date.group(1), 'source_baseline': baseline.group(1),
            'scope': 'MANUAL_ACCEPTANCE_ONLY',
        })
    return acceptance


def enrich_program(program: dict, root: Path, primary: str) -> dict:
    manifest = root / 'pubspec.yaml'
    if not manifest.is_file():
        program['status'] = 'PROGRAM_BLOCKED'
        program['execution_blocker'] = {'status': 'MANIFEST_MISSING', 'reason': str(manifest)}
        return program

    data = yaml.safe_load(manifest.read_text(encoding='utf-8'))
    dependencies = list((data.get('dependencies') or {}).keys())
    program['repositories'][0]['role'] = 'PACKAGE'
    program['package_version'] = str(data.get('version', ''))
    program['source_revision'] = _git(root, 'rev-parse', 'HEAD')
    try:
        status = subprocess.check_output(
            ['git', 'status', '--short'], cwd=root, text=True,
            stderr=subprocess.DEVNULL,
        )
        dirty_paths = [line[3:] for line in status.splitlines() if len(line) > 3]
    except subprocess.CalledProcessError:
        dirty_paths = []
    program['observed_worktree'] = {
        'status': 'DIRTY' if dirty_paths else 'CLEAN',
        'changed_paths': dirty_paths,
        'inventory_only': True,
    }

    android = _android_contract(root)
    acceptance = _maintainer_acceptance(root, program['package_version'])
    program['maintainer_acceptance'] = acceptance
    latest_evidence = acceptance['evidence']
    android['manual_acceptance'] = acceptance
    macos_evidence = root / 'docs/evidence/macos-gpu-only/report.json'
    program['platform_contract'] = {
        'macos': {
            'status': 'BUILD_READY_RUNTIME_PENDING',
            'evidence': latest_evidence,
            'manual_acceptance': acceptance,
            'detailed_acceptance': 'PENDING',
            'historical_runtime_evidence': {
                'status': 'RECORDED' if macos_evidence.is_file() else 'MISSING',
                'evidence': ['docs/evidence/macos-gpu-only/report.json'] if macos_evidence.is_file() else [],
                'current_revision_binding': 'UNVERIFIED',
            },
            'build_command': 'python3 tool/macos_run.py --mode release --build-only',
        },
        'android': android,
        'ios': {'status': 'UNSUPPORTED'},
        'linux': {'status': 'UNSUPPORTED'},
        'windows': {'status': 'UNSUPPORTED'},
        'web': {'status': 'UNSUPPORTED', 'blockers': ['dart:io reader', 'GPU-only renderer']},
    }
    program['build_requirements'] = {
        'environment': data.get('environment', {}),
        'assets': (data.get('flutter') or {}).get('assets', []),
        'validation': ['flutter analyze', 'flutter test', '(cd example && flutter test)'],
        'platform_validation': {
            'macos': 'cd example && python3 tool/macos_run.py --mode release --build-only',
            'android': f"cd example && {android['build_command']}",
        },
        'native_acceptance': 'PLATFORM_SPECIFIC_EVIDENCE_REQUIRED',
    }
    program['capabilities'] = [
        {
            'capability_id': 'gcode-parsing-and-toolpath-modeling',
            'current_owners': [primary],
            'source_paths': [f'{primary}/lib/src/parser', f'{primary}/lib/src/core', f'{primary}/lib/src/models', f'{primary}/lib/src/services'],
            'consumers': [f'{primary}:rendering', f'{primary}:example', 'flutter_forge:gcode_visualizer'],
            'dependencies': dependencies, 'flutter_dependency': True,
            'platform_dependency': False, 'native_dependency': False, 'state_dependency': False,
            'reuse_scope': 'cluster', 'classification': 'KEEP_PACKAGE', 'target_package': '.',
            'evidence': ['pubspec.yaml', 'lib/gcode_core.dart', 'AGENTS.md'],
        },
        {
            'capability_id': 'flutter-gpu-toolpath-rendering',
            'current_owners': [primary],
            'source_paths': [f'{primary}/lib/src/rendering', f'{primary}/lib/src/widgets', f'{primary}/shaders'],
            'consumers': [f'{primary}:example', 'flutter_forge:gcode_visualizer'],
            'dependencies': ['flutter_gpu', 'flutter'], 'supported_platforms': ['macos', 'android'],
            'platform_dependency': True, 'native_dependency': True, 'state_dependency': True,
            'reuse_scope': 'cluster', 'classification': 'KEEP_PACKAGE', 'target_package': '.',
            'evidence': ['lib/src/rendering', 'shaders/toolpath.shaderbundle', 'docs/evidence/macos-gpu-only/report.json', *latest_evidence],
        },
        {
            'capability_id': 'gcode-example-session-playback',
            'current_owners': [f'{primary}/example'], 'source_paths': [f'{primary}/example/lib/src'],
            'consumers': [f'{primary}:example'], 'dependencies': ['gcode_core'],
            'supported_platforms': ['macos', 'android'],
            'platform_dependency': True, 'native_dependency': True, 'state_dependency': True,
            'reuse_scope': 'example', 'classification': 'KEEP_APP_ONLY', 'target_package': 'example',
            'evidence': ['example/lib/src/gcode_session_controller.dart', 'example/lib/src/gcode_example_page.dart'],
        },
        {
            'capability_id': 'native-gcode-file-reading',
            'current_owners': [primary], 'source_paths': [f'{primary}/lib/src/data/readers'],
            'consumers': [f'{primary}:example', 'flutter_forge:gcode_visualizer'],
            'dependencies': ['dart:io'], 'supported_platforms': ['macos', 'android'],
            'flutter_dependency': False, 'platform_dependency': True,
            'native_dependency': True, 'state_dependency': False,
            'reuse_scope': 'cluster', 'classification': 'KEEP_PACKAGE', 'target_package': '.',
            'public_api_intent': 'Native line reading; file picking and playback state remain app owned',
            'evidence': ['lib/src/data/readers', 'AGENTS.md'],
        },
    ]
    program['package_candidates'] = [{
        'package_id': '.', 'package_type': 'FLUTTER_PACKAGE', 'target_path': '.',
        'owned_capabilities': ['gcode-parsing-and-toolpath-modeling', 'flutter-gpu-toolpath-rendering', 'native-gcode-file-reading'],
        'dependencies': dependencies,
        'public_api_intent': 'G-code parsing, toolpath modeling, and GPU-only visualization',
        'migration_priority': 1,
    }]
    nodes, edges = ['.'], []
    if (root / 'example/pubspec.yaml').is_file():
        program['package_candidates'].append({
            'package_id': 'example', 'package_type': 'APP_ONLY', 'target_path': 'example',
            'owned_capabilities': ['gcode-example-session-playback'], 'dependencies': ['.'],
            'public_api_intent': 'Package demonstration and platform-specific native acceptance',
            'migration_priority': 2,
        })
        nodes.append('example')
        edges.append(['example', '.'])
    program['target_dependency_graph'] = {'nodes': nodes, 'edges': edges, 'cycles': []}
    program['migration_tasks'] = [
        {
            'task_id': 'gcode_macos_gpu_runtime_baseline',
            'title': 'Preserve the historical macOS Flutter GPU report',
            'source_units': [primary], 'target_units': [primary], 'depends_on': [],
            'allowed_operations': [], 'allowed_paths_by_repository': {},
            'status': 'DONE' if macos_evidence.is_file() else 'PARTIAL',
            'evidence': ['docs/evidence/macos-gpu-only/report.json'] if macos_evidence.is_file() else [],
            'evidence_scope': 'HISTORICAL_REPORT_ONLY',
            'current_detailed_acceptance': 'PENDING',
        },
        {
            'task_id': 'gcode_android_arm64_runtime_acceptance',
            'title': 'Complete Android API 29+ ARM64 Flutter GPU device acceptance',
            'source_units': [f'{primary}/example'], 'target_units': [f'{primary}/example'],
            'depends_on': ['gcode_macos_gpu_runtime_baseline'],
            'allowed_operations': [], 'allowed_paths_by_repository': {},
            'acceptance': ['api_29_and_api_35_arm64_device_runs', 'picker_cancel_and_sample_load', 'gpu_first_frame', 'frame_and_memory_measurements'],
            'status': 'PARTIAL' if android['status'] == 'BUILD_READY_RUNTIME_PENDING' else 'BLOCKED',
            'evidence': ['example/android', '.github/workflows/ci.yml', 'AGENTS.md', *latest_evidence],
        },
    ]
    program['execution_mode'] = 'PLAN_ONLY'
    return program
