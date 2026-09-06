"""Read the independently maintained G-code package's current build facts."""
from pathlib import Path
import subprocess
import yaml


def enrich_program(program: dict, root: Path, primary: str) -> dict:
    manifest = root / 'pubspec.yaml'
    if not manifest.is_file():
        program['status'] = 'PROGRAM_BLOCKED'
        program['execution_blocker'] = {'status': 'MANIFEST_MISSING', 'reason': str(manifest)}
        return program
    data = yaml.safe_load(manifest.read_text())
    dependencies = list((data.get('dependencies') or {}).keys())
    program['repositories'][0]['role'] = 'PACKAGE'
    program['source_revision'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    program['build_requirements'] = {
        'environment': data.get('environment', {}),
        'assets': (data.get('flutter') or {}).get('assets', []),
        'validation': ['flutter pub get', 'flutter analyze', 'flutter test'],
        'native_acceptance': 'NOT_VERIFIED_BY_INVENTORY',
    }
    program['capabilities'] = [{
        'capability_id': 'gcode-toolpath-preview',
        'current_owners': [primary], 'source_paths': [f'{primary}/lib'],
        'consumers': [f'{primary}:example', 'flutter_forge:gcode_visualizer'],
        'dependencies': dependencies, 'flutter_dependency': True,
        'platform_dependency': 'flutter_gpu' in dependencies,
        'native_dependency': 'flutter_gpu' in dependencies,
        'state_dependency': True, 'reuse_scope': 'cluster',
        'classification': 'KEEP_PACKAGE', 'target_package': '.',
        'evidence': ['pubspec.yaml', 'lib/gcode_core.dart', 'CONTEXT.md'],
    }]
    program['package_candidates'] = [{
        'package_id': '.', 'package_type': 'FLUTTER_PACKAGE', 'target_path': '.',
        'owned_capabilities': ['gcode-toolpath-preview'], 'dependencies': dependencies,
        'public_api_intent': 'G-code parsing and trajectory preview; not machining simulation',
        'migration_priority': 1,
    }]
    nodes, edges = ['.'], []
    if (root / 'example/pubspec.yaml').is_file():
        program['package_candidates'].append({
            'package_id': 'example', 'package_type': 'APP_ONLY', 'target_path': 'example',
            'owned_capabilities': [], 'dependencies': ['.'],
            'public_api_intent': 'Package demonstration and native acceptance', 'migration_priority': 2,
        })
        nodes.append('example')
        edges.append(['example', '.'])
    program['target_dependency_graph'] = {'nodes': nodes, 'edges': edges, 'cycles': []}
    return program
