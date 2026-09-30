"""Read the independently maintained G-code package's current build facts."""
from pathlib import Path
import subprocess

import yaml


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(
        ['git', *args], cwd=root, text=True, stderr=subprocess.DEVNULL
    ).strip()


def _android_contract(root: Path) -> dict[str, object]:
    gradle = root / 'example/android/app/build.gradle.kts'
    text = gradle.read_text(encoding='utf-8') if gradle.is_file() else ''
    return {
        'status': 'BUILD_READY_RUNTIME_PENDING' if gradle.is_file() else 'UNSUPPORTED',
        'minimum_api': 29 if 'minSdk = 29' in text else None,
        'abis': ['arm64-v8a'] if 'abiFilters += "arm64-v8a"' in text else [],
        'build_command': 'flutter build apk --debug --target-platform android-arm64',
        'runtime_acceptance': 'PENDING_NATIVE_GPU_DEVICE_EVIDENCE',
    }


def enrich_program(program: dict, root: Path, primary: str) -> dict:
    manifest = root / 'pubspec.yaml'
    if not manifest.is_file():
        program['status'] = 'PROGRAM_BLOCKED'
        program['execution_blocker'] = {'status': 'MANIFEST_MISSING', 'reason': str(manifest)}
        return program

    data = yaml.safe_load(manifest.read_text(encoding='utf-8'))
    dependencies = list((data.get('dependencies') or {}).keys())
    program['repositories'][0]['role'] = 'PACKAGE'
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
    macos_evidence = root / 'docs/evidence/macos-gpu-only/report.json'
    program['platform_contract'] = {
        'macos': {
            'status': 'RUNTIME_VALIDATED' if macos_evidence.is_file() else 'BUILD_READY_RUNTIME_PENDING',
            'evidence': ['docs/evidence/macos-gpu-only/report.json'] if macos_evidence.is_file() else [],
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
            'source_paths': [f'{primary}/lib/src/parser', f'{primary}/lib/src/core', f'{primary}/lib/src/services'],
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
            'evidence': ['lib/src/rendering', 'shaders/toolpath.shaderbundle', 'docs/evidence/macos-gpu-only/report.json'],
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
    ]
    program['package_candidates'] = [{
        'package_id': '.', 'package_type': 'FLUTTER_PACKAGE', 'target_path': '.',
        'owned_capabilities': ['gcode-parsing-and-toolpath-modeling', 'flutter-gpu-toolpath-rendering'],
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
            'title': 'Preserve the validated macOS Flutter GPU baseline',
            'source_units': [primary], 'target_units': [primary], 'depends_on': [],
            'allowed_operations': [], 'allowed_paths_by_repository': {},
            'status': 'DONE' if macos_evidence.is_file() else 'PARTIAL',
            'evidence': ['docs/evidence/macos-gpu-only/report.json'] if macos_evidence.is_file() else [],
        },
        {
            'task_id': 'gcode_android_arm64_runtime_acceptance',
            'title': 'Complete Android API 29+ ARM64 Flutter GPU device acceptance',
            'source_units': [f'{primary}/example'], 'target_units': [f'{primary}/example'],
            'depends_on': ['gcode_macos_gpu_runtime_baseline'],
            'allowed_operations': [], 'allowed_paths_by_repository': {},
            'acceptance': ['api_29_and_api_35_arm64_device_runs', 'picker_cancel_and_sample_load', 'gpu_first_frame', 'frame_and_memory_measurements'],
            'status': 'PARTIAL' if android['status'] == 'BUILD_READY_RUNTIME_PENDING' else 'BLOCKED',
            'evidence': ['example/android', '.github/workflows/ci.yml', 'AGENTS.md'],
        },
    ]
    program['execution_mode'] = 'PLAN_ONLY'
    return program
