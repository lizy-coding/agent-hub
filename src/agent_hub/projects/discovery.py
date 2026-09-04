"""Bounded, read-only manifest and Git discovery for a configured workspace."""

import json
import os
import shutil
import subprocess
import tomllib
import hashlib
from datetime import UTC, datetime
from pathlib import Path

import yaml

from agent_hub.schemas.models import Dependency, DevelopmentUnit, Evidence, Repository, RuleFile, ValidationCommand, Workspace
from agent_hub.tools.path_guard import is_allowed_business_path, is_within
from agent_hub.workspace.config import WorkspaceConfig

MANIFEST_NAMES = {"pubspec.yaml": "dart_flutter", "pyproject.toml": "python", "Cargo.toml": "rust", "package.json": "node", "CMakeLists.txt": "cmake"}
CONTROL_DOCUMENT_NAMES = {"AGENTS.md", "AGENTS.override.md", "CONTEXT.md", "AI_PROJECT_CONTEXT.md", "AI_ANALYSIS_SCHEMA.json", "REFACTOR_PLAN.md"}
SKIP_DIRS = {".git", ".dart_tool", ".venv", "build", "node_modules", ".langgraph_api"}


def now() -> str:
    return datetime.now(UTC).isoformat()


def relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix() or "."


def evidence(path: Path, root: Path, detail: str | None = None) -> Evidence:
    if path.is_file():
        digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
        detail = f"{detail or 'file'};sha256={digest}"
    return Evidence(source="filesystem", path=relative(path, root), discovered_at=now(), detail=detail)


def walk(root: Path, config: WorkspaceConfig):
    """Yield safe paths only; symlink directories are never traversed."""
    for current, dirs, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and is_allowed_business_path(current_path / d, config) and not (current_path / d).is_symlink()]
        yield current_path, files


def git_roots(root: Path, config: WorkspaceConfig) -> list[Path]:
    roots = []
    for current, dirs, _ in os.walk(root, followlinks=False):
        current_path = Path(current)
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS - {".git"} and is_allowed_business_path(current_path / d, config) and not (current_path / d).is_symlink()]
        if ".git" in dirs:
            roots.append(current_path.resolve())
            dirs.remove(".git")
    return sorted(set(roots))


def rule_files(base: Path, root: Path, config: WorkspaceConfig) -> list[RuleFile]:
    found: list[RuleFile] = []
    for current, files in walk(base, config):
        names = [name for name in files if name in CONTROL_DOCUMENT_NAMES or (current.name == "adr" and name.endswith(".md"))]
        for name in names:
            path = current / name
            found.append(RuleFile(path=relative(path, root), scope=relative(current, root), provenance="filesystem_control_contract"))
    return found


def manifest_data(path: Path) -> dict:
    try:
        if path.name == "pubspec.yaml":
            return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if path.name == "pyproject.toml" or path.name == "Cargo.toml":
            return tomllib.loads(path.read_text(encoding="utf-8"))
        if path.name == "package.json":
            return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, tomllib.TOMLDecodeError, yaml.YAMLError):
        return {}
    return {}


def unit_type(manifest: Path, data: dict) -> tuple[str, list[str], list[str]]:
    if manifest.name == "pubspec.yaml":
        dependencies = data.get("dependencies", {}) if isinstance(data.get("dependencies"), dict) else {}
        runtime = ["dart", "flutter", "pub"] if "flutter" in dependencies else ["dart", "pub"]
        return ("application" if manifest.parent.joinpath("lib/main.dart").is_file() else "library/package", runtime, list(data.get("workspace", []) or []))
    if manifest.name == "pyproject.toml": return "library/package", ["python"], []
    if manifest.name == "Cargo.toml": return "native component", ["rust"], []
    if manifest.name == "package.json": return "application", ["node"], []
    return "native component", ["cmake"], []


def validation_for(manifest: Path, root: Path, config: WorkspaceConfig) -> list[ValidationCommand]:
    directory, commands = manifest.parent, []
    def add(category: str, command: str, executable: str, working_directory: Path = directory):
        commands.append(ValidationCommand(category=category, command=command, commands=[command], working_directory=relative(working_directory, root), available=shutil.which(executable) is not None, evidence=evidence(manifest, root, f"{manifest.name} runtime")))
    if manifest.name == "pubspec.yaml":
        add("format", "dart format .", "dart")
        add("analyze", "flutter analyze" if (manifest.parent / "lib").exists() else "dart analyze", "flutter" if (manifest.parent / "lib").exists() else "dart")
        if (directory / "test").is_dir(): add("test", "flutter test", "flutter")
    elif manifest.name == "pyproject.toml":
        if (directory / "tests").is_dir(): add("test", "pytest", "pytest")
    elif manifest.name == "Cargo.toml": add("test", "cargo test", "cargo")
    project_root = next((parent for parent in (directory, *directory.parents) if (parent / ".git").exists()), None)
    if project_root and (project_root / "tool" / "quality_gate.sh").is_file():
        add("quality_gate", "bash tool/quality_gate.sh", "bash", project_root)
    return commands


def discover(config: WorkspaceConfig) -> Workspace:
    root = config.workspace_root
    if not root.is_dir() or not is_allowed_business_path(root, config):
        raise ValueError("workspace root is inaccessible or outside configured boundary")
    timestamp = now()
    roots = git_roots(root, config)
    manifests = [(current / name) for current, files in walk(root, config) for name in files if name in MANIFEST_NAMES]
    standalone = [path.parent.resolve() for path in manifests if not any(is_within(path, git_root) for git_root in roots)]
    containers = roots + sorted(set(standalone))
    repositories: list[Repository] = []
    for base in containers:
        contained = [p for p in manifests if is_within(p, base)]
        if not contained: continue
        is_git = base in roots
        repo_id = base.name
        if any(repo.repo_id == repo_id for repo in repositories): repo_id = f"{repo_id}-{abs(hash(str(base))) % 100000:05d}"
        units: list[DevelopmentUnit] = []
        for manifest in sorted(contained):
            data = manifest_data(manifest)
            type_name, runtime, _ = unit_type(manifest, data)
            rel = relative(manifest.parent, base)
            name = data.get("name") if isinstance(data, dict) else None
            unit_id = f"{repo_id}:{rel}"
            units.append(DevelopmentUnit(unit_id=unit_id, repo_id=repo_id, relative_path=rel, unit_type=type_name, manifests=[relative(manifest, root)], rule_files=rule_files(manifest.parent, root, config), capabilities=[str(name)] if name else ["unknown"], validation=validation_for(manifest, root, config), evidence=[evidence(manifest, root, MANIFEST_NAMES[manifest.name])], freshness=timestamp))
        runtimes = sorted({MANIFEST_NAMES[path.name] for path in contained})
        repositories.append(Repository(repo_id=repo_id, path=base, git_root=base if is_git else None, repo_type="git_repository" if is_git else "standalone_project", runtime=runtimes, manifests=[relative(p, root) for p in contained], rule_files=rule_files(base, root, config), validation=[command for unit in units for command in unit.validation], development_units=units, evidence=[evidence(base, root, "git metadata" if is_git else "manifest outside git repository")], freshness=timestamp))
    _link_dependencies(repositories, root)
    return Workspace(workspace_root=root, allowed_paths=config.allowed_paths, excluded_paths=config.excluded_paths, registry_path=config.registry_path, repositories=repositories, refreshed_at=timestamp)


def _link_dependencies(repositories: list[Repository], root: Path) -> None:
    units = [unit for repo in repositories for unit in repo.development_units]
    by_path = {(repo.path / unit.relative_path).resolve(): unit for repo in repositories for unit in repo.development_units}
    for repo in repositories:
        for unit in repo.development_units:
            manifest = (repo.path / unit.relative_path / Path(unit.manifests[0]).name)
            data = manifest_data(manifest)
            dependencies = data.get("dependencies", {}) if manifest.name == "pubspec.yaml" else {}
            if not isinstance(dependencies, dict): continue
            for name, spec in dependencies.items():
                if isinstance(spec, dict) and isinstance(spec.get("path"), str):
                    target_path = (manifest.parent / spec["path"]).resolve()
                    target = by_path.get(target_path)
                    if target:
                        edge = Dependency(source=unit.unit_id, target=target.unit_id, kind="path_dependency", evidence=evidence(manifest, root, f"dependencies.{name}.path"))
                        unit.dependencies.append(edge)
                        target.dependents.append(edge)
                        repo.dependencies.append(edge)
    for repo in repositories:
        repo.dependents = [edge for unit in repo.development_units for edge in unit.dependents]
