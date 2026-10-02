"""Refresh managed agent context through explicit LangGraph file intakes."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import yaml

from agent_hub.context.resolver import AGENT_RULE_NAMES, ancestor_agent_rules
from agent_hub.graphs.capability_analysis import build_capability_analysis_graph
from agent_hub.graphs.context_analysis import build_context_analysis_graph
from agent_hub.projects.decomposition_config import AGENT_HUB_ROOT, DEFAULT_REGISTRY, load_decomposition_project
from agent_hub.schemas.models import DevelopmentUnit, Repository, Workspace
from agent_hub.workspace.config import WorkspaceConfig

DEFAULT_OUTPUT = AGENT_HUB_ROOT / "workspace" / "agent-context.json"
TEXT_SUFFIXES = {".dart", ".md", ".yaml", ".yml", ".json", ".js", ".ts", ".toml", ".py", ".sh", ".kts", ".gradle", ".xml", ".kt", ".java", ".cpp", ".cc", ".c", ".h", ".hpp", ".mm", ".m", ".swift", ".cmake", ".txt", ".ini", ".properties", ".iss", ".html", ".css", ".svg", ".lock", ".sql", ".bat", ".ps1", ".rst"}
TEXT_NAMES = {"LICENSE", "NOTICE", "Makefile", ".gitignore", ".gitattributes", ".metadata"}


def _git(root: Path, *args: str) -> tuple[str, str | None]:
    result = subprocess.run(["git", "--literal-pathspecs", "-C", str(root), *args], capture_output=True, text=True, timeout=20, check=False)
    return result.stdout, None if result.returncode == 0 else result.stderr.strip() or f"git exited {result.returncode}"


def _names(output: str) -> list[str]:
    return list(dict.fromkeys(value.strip("\n") for value in output.split("\0") if value.strip("\n")))


def _candidate_reason(root: Path, value: str) -> str | None:
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts or any(character in value for character in ("\n", "\r", "\0")):
        return "OUTSIDE_REPOSITORY_OR_INVALID_PATH"
    path = root / relative
    try:
        if path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent == root or root in parent.parents):
            return "SYMLINK"
        resolved = path.resolve()
        if root not in resolved.parents:
            return "OUTSIDE_REPOSITORY"
        if not resolved.exists():
            return "MISSING_OR_DELETED"
        if not resolved.is_file():
            return "DIRECTORY_OR_NONREGULAR_FILE"
    except OSError:
        return "PATH_METADATA_UNREADABLE"
    if resolved.suffix.lower() not in TEXT_SUFFIXES and resolved.name not in TEXT_NAMES:
        return "UNSUPPORTED_TEXT_FORMAT"
    return None


def _workspace_config(entry: dict) -> WorkspaceConfig:
    path = Path(str(entry.get("workspace_config", "")))
    if not path.is_absolute():
        path = AGENT_HUB_ROOT / path
    return WorkspaceConfig.from_file(path)


def _manifest_facts(texts: dict[str, str]) -> tuple[str | None, str | None, list[dict], list[str]]:
    """Bind consumer declarations to selected lockfiles, never sibling HEADs."""
    version, version_path = None, None
    manifests, lockfiles, gaps = {}, {}, []
    for value, text in texts.items():
        name = Path(value).name
        if name not in {"pubspec.yaml", "pubspec.lock"}:
            continue
        try:
            payload = yaml.safe_load(text)
        except yaml.YAMLError:
            gaps.append(f"MANIFEST_UNREADABLE: {value}")
            continue
        if not isinstance(payload, dict):
            gaps.append(f"MANIFEST_NOT_A_MAPPING: {value}")
            continue
        if name == "pubspec.lock":
            if not isinstance(payload.get("packages", {}), dict):
                gaps.append(f"LOCK_PACKAGES_NOT_A_MAPPING: {value}")
                continue
            lockfiles[value] = payload
        else:
            manifests[value] = payload
            if version is None and payload.get("version") is not None:
                version, version_path = str(payload["version"]), value
    pins = []
    for manifest_path, manifest in manifests.items():
        for section in ("dependencies", "dev_dependencies", "dependency_overrides"):
            dependencies = manifest.get(section)
            if not isinstance(dependencies, dict):
                continue
            for package, spec in dependencies.items():
                if not isinstance(spec, dict) or "git" not in spec:
                    continue
                git = spec["git"]
                git = git if isinstance(git, dict) else {"url": git}
                requested = git.get("ref")
                matching_locks = []
                for lock_path, lock in lockfiles.items():
                    # A package uses its own lockfile or a selected workspace
                    # ancestor lockfile. An unrelated app lock is not evidence.
                    parent = Path(lock_path).parent
                    consumer_parent = Path(manifest_path).parent
                    if parent != consumer_parent and parent not in consumer_parent.parents:
                        continue
                    locked = (lock.get("packages") or {}).get(package)
                    if isinstance(locked, dict) and locked.get("source") == "git":
                        matching_locks.append((len(parent.parts), lock_path, locked))
                selected_lock = max(matching_locks, key=lambda item: item[0]) if matching_locks else None
                lock_path = selected_lock[1] if selected_lock else None
                locked = selected_lock[2] if selected_lock else {}
                description = locked.get("description") or {}
                description = description if isinstance(description, dict) else {}
                resolved = description.get("resolved-ref")
                lock_matches = description.get("url") in (None, git.get("url")) and description.get("ref") in (None, requested)
                state = "DECLARED_AND_LOCKED" if resolved and lock_matches else "MANIFEST_LOCK_REF_MISMATCH" if selected_lock and not lock_matches else "DECLARED_ONLY"
                if state != "DECLARED_AND_LOCKED":
                    gaps.append(f"{state}: {package} in {manifest_path}")
                pins.append({"package": str(package), "consumer_manifest": manifest_path, "section": section, "url": git.get("url"), "requested_ref": requested, "git_path": git.get("path"), "resolved_ref": resolved, "lockfile": lock_path, "locked_version": locked.get("version"), "binding_state": state})
    return version, version_path, pins, gaps


def _target_repository(config: WorkspaceConfig, root: Path, repo_id: str) -> tuple[Repository, str, list[str]]:
    """Load one cached identity; the fallback checks a fixed pubspec only."""
    gaps = []
    storage = config.registry_storage_path
    repository = None
    if storage and storage.is_file():
        try:
            payload = json.loads(storage.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or not isinstance(payload.get("repositories", []), list):
                raise ValueError("registry cache must contain a repositories list")
            raw = next((item for item in payload.get("repositories", []) if isinstance(item, dict) and item.get("repo_id") == repo_id), None)
            if raw is not None:
                repository = Repository.model_validate(raw)
        except (OSError, ValueError, TypeError) as error:
            gaps.append(f"REGISTRY_CACHE_UNREADABLE: {error}")
    if repository is None:
        gaps.append("TARGET_REGISTRY_METADATA_MISSING: using one explicit root unit")
        manifest = root / "pubspec.yaml"
        has_manifest = manifest.is_file() and not manifest.is_symlink()
        if not has_manifest:
            gaps.append("ROOT_PUBSPEC_MISSING: fallback unit has no manifest evidence")
        unit = DevelopmentUnit(unit_id=f"{repo_id}:.", repo_id=repo_id, relative_path=".", unit_type="library/package" if has_manifest else "unknown", manifests=["pubspec.yaml"] if has_manifest else [], freshness="bounded_fallback")
        return Repository(repo_id=repo_id, path=root, git_root=root, development_units=[unit], freshness="bounded_fallback"), "EXPLICIT_ROOT_FALLBACK", gaps
    old_root = repository.path.resolve()

    def local(value: str) -> str:
        path = (config.workspace_root / value).resolve()
        return path.relative_to(old_root).as_posix() if path == old_root or old_root in path.parents else value

    repository.path = root
    repository.git_root = root
    for item in [repository, *repository.development_units]:
        item.manifests = [local(value) for value in item.manifests]
        for rule in item.rule_files:
            rule.path, rule.scope = local(rule.path), local(rule.scope)
        for validation in item.validation:
            if validation.working_directory:
                validation.working_directory = local(validation.working_directory)
        for evidence in item.evidence:
            evidence.path = local(evidence.path)
        for edge in item.dependencies + item.dependents:
            edge.evidence.path = local(edge.evidence.path)
    if not repository.development_units:
        repository.development_units = [DevelopmentUnit(unit_id=f"{repo_id}:.", repo_id=repo_id, relative_path=".", unit_type="unknown", freshness="bounded_fallback")]
        gaps.append("TARGET_UNITS_MISSING: using one explicit root unit")
    return repository, "CACHED_TARGET_METADATA", gaps


def _refresh_project(project_id: str, entry: dict, registry_path: Path, max_files: int, protected_outputs: set[Path]) -> dict:
    project = load_decomposition_project(project_id, registry_path=registry_path)
    root = project.repository_paths[project.primary_repository_id].resolve()
    config = _workspace_config(entry)
    protected_outputs.update(path.resolve() for path in (config.registry_path, config.registry_storage_path) if path is not None)
    spec = entry.get("agent_context") or {}
    seeds = list(dict.fromkeys(str(value) for value in spec.get("seed_files", [])))
    prefixes = [str(value).rstrip("/") for value in spec.get("change_prefixes", [])]
    unknowns = []
    git_results = {}
    commands = {
        "source_sha": ("rev-parse", "HEAD"),
        "branch": ("rev-parse", "--abbrev-ref", "HEAD"),
        "recent_paths": ("log", "-6", "--format=", "--name-only", "-z", "--no-renames"),
        "worktree_paths": ("diff", "--name-only", "-z", "--no-renames"),
        "index_paths": ("diff", "--cached", "--name-only", "-z", "--no-renames"),
    }
    for key, args in commands.items():
        try:
            output, error = _git(root, *args)
        except (OSError, subprocess.TimeoutExpired) as error:
            output, error = "", str(error)
        git_results[key] = output
        if error:
            unknowns.append(f"GIT_{key.upper()}_UNAVAILABLE: {error}")
    recent = _names(git_results["recent_paths"])
    worktree = _names(git_results["worktree_paths"])
    index = _names(git_results["index_paths"])
    dirty = sorted(set(worktree + index))
    origins: dict[str, list[str]] = {value: ["seed"] for value in seeds}
    ignored = []
    for origin, values in (("dirty_worktree", worktree), ("dirty_index", index), ("recent_commit", recent)):
        for value in values:
            if value not in origins and not any(value == prefix or value.startswith(prefix + "/") for prefix in prefixes):
                ignored.append({"path": value, "reason": "OUTSIDE_MONITORED_CHANGE_PREFIXES", "origin": origin})
                continue
            sources = origins.setdefault(value, [])
            if origin not in sources:
                sources.append(origin)
    # Applicable guides are part of the evidence budget. Resolve only exact
    # ancestor names for the explicit intake; cached unit roots are incomplete
    # for repositories admitted through a root-only fallback.
    required_rules: dict[str, list[str]] = {}
    rule_origins: dict[str, list[str]] = {}
    candidates: dict[str, list[str]] = {}
    for value, origin in origins.items():
        reason = _candidate_reason(root, value)
        if reason:
            ignored.append({"path": value, "reason": reason, "origins": origin})
            if reason != "UNSUPPORTED_TEXT_FORMAT":
                unknowns.append(f"{reason}: {value}")
            continue
        path = root / value
        rules = ancestor_agent_rules(root, path)
        if path.name == "AGENTS.md" and any(rule.parent == path.parent and rule.name == "AGENTS.override.md" for rule in rules):
            ignored.append({"path": value, "reason": "AGENT_GUIDE_OVERRIDDEN", "origins": origin})
            for rule in rules:
                rule_origins.setdefault(rule.relative_to(root).as_posix(), ["ancestor_rule"])
            continue
        required_rules[value] = [rule.relative_to(root).as_posix() for rule in rules if rule != path]
        for rule in rules:
            rule_origins.setdefault(rule.relative_to(root).as_posix(), ["ancestor_rule"])
        candidates[value] = origin
    for value, origin in candidates.items():
        if Path(value).name in AGENT_RULE_NAMES:
            rule_origins[value] = list(dict.fromkeys(rule_origins.get(value, []) + origin))
    intake = {**rule_origins, **{value: origin for value, origin in candidates.items() if value not in rule_origins}}
    selected, inspected = [], 0
    texts = {}
    for value, origin in intake.items():
        reason = _candidate_reason(root, value)
        if reason:
            ignored.append({"path": value, "reason": reason, "origins": origin})
            if reason != "UNSUPPORTED_TEXT_FORMAT":
                unknowns.append(f"{reason}: {value}")
            continue
        if inspected >= max_files:
            ignored.append({"path": value, "reason": "FILE_BUDGET_EXHAUSTED", "origins": origin})
            unknowns.append(f"FILE_BUDGET_EXHAUSTED: {value}")
            continue
        missing_rules = [rule for rule in required_rules.get(value, []) if rule not in texts]
        if missing_rules:
            ignored.append({"path": value, "reason": "REQUIRED_AGENT_GUIDE_UNAVAILABLE", "origins": origin, "required_guides": missing_rules})
            unknowns.append(f"REQUIRED_AGENT_GUIDE_UNAVAILABLE: {value}: {', '.join(missing_rules)}")
            continue
        inspected += 1
        try:
            data = (root / value).read_bytes()
            text = data.decode("utf-8")
            if b"\0" in data:
                raise UnicodeError("NUL bytes")
        except (OSError, UnicodeError) as error:
            ignored.append({"path": value, "reason": "BINARY_OR_UNREADABLE_FILE", "origins": origin})
            unknowns.append(f"BINARY_OR_UNREADABLE_FILE: {value}: {error}")
            continue
        texts[value] = text
        selected.append({"path": value, "sha256": hashlib.sha256(data).hexdigest(), "origins": origin, "content_state": "CURRENT_WORKTREE", "dirty_tracked": value in dirty})
    selected_paths = [item["path"] for item in selected]
    if selected_paths:
        tracked, error = _git(root, "ls-files", "-z", "--", *selected_paths)
        tracked_paths = set(_names(tracked)) if not error else None
        if error:
            unknowns.append(f"GIT_TRACKED_STATE_UNAVAILABLE: {error}")
        for item in selected:
            item["tracked"] = item["path"] in tracked_paths if tracked_paths is not None else None
            if item["tracked"] is False:
                item["content_state"] = "UNTRACKED_EXPLICIT_FILE"
                unknowns.append(f"UNTRACKED_EXPLICIT_FILE: {item['path']}")
    if dirty:
        unknowns.append("DIRTY_WORKSPACE: observations include current worktree content beyond source SHA")
    version, version_path, dependency_pins, manifest_gaps = _manifest_facts(texts)
    unknowns.extend(manifest_gaps)
    if version is None:
        unknowns.append("VERSION_NOT_OBSERVED_IN_SELECTED_MANIFESTS")
    repository, metadata_mode, metadata_gaps = _target_repository(config, root, project.primary_repository_id)
    unknowns.extend(metadata_gaps)
    with tempfile.TemporaryDirectory(prefix="agent-hub-context-", dir="/private/tmp") as temporary:
        temporary_registry = Path(temporary) / "registry.json"
        temporary_registry.write_text(Workspace(workspace_root=root, allowed_paths=[root], excluded_paths=[], registry_path=temporary_registry, repositories=[repository]).model_dump_json(), encoding="utf-8")
        bounded_config = WorkspaceConfig(workspace_root=root, allowed_paths=[root], registry_path=temporary_registry, registry_storage_path=temporary_registry)
        state = {"requirement": f"{project_id} agent contracts {spec.get('ownership', '')} public interface release parser controller widget", "target_repository": project.primary_repository_id, "candidate_paths": selected_paths, "limits": {"max_files": max_files, "max_symbols": 80, "max_dependency_depth": 0}}
        context = build_context_analysis_graph(bounded_config).invoke(state)["context_package"]
        capabilities = build_capability_analysis_graph(bounded_config).invoke(state)["capability_analysis"]
    return {
        "project_id": project_id, "repository_id": project.primary_repository_id, "repository_root": str(root), "adapter": project.adapter,
        "status": "REFRESHED_WITH_GAPS" if unknowns else "REFRESHED", "source_sha": git_results["source_sha"].strip() or None, "branch": git_results["branch"].strip() or None,
        "version": version, "version_source": version_path, "dependency_pins": dependency_pins, "content_state": "CURRENT_WORKTREE", "acceptance": False,
        "workspace_dirty_paths": dirty, "worktree_dirty_paths": worktree, "index_dirty_paths": index,
        "untracked_inventory": "NOT_SCANNED_ONLY_EXPLICIT_FILES_CLASSIFIED", "recent_commit_limit": 6, "recent_changed_paths": recent,
        "selected_files": selected, "ignored_candidates": ignored, "unknowns": list(dict.fromkeys(unknowns)), "registry_metadata_mode": metadata_mode, "registry_metadata_freshness": repository.freshness,
        "scope": context["scope"], "metrics": {"candidate_files": len(set(origins) | set(rule_origins)), "rule_candidates": len(rule_origins), "inspected_files": inspected, "selected_files": len(selected), "max_files": max_files, "no_walk": True, "source_discovery_performed": False},
        "context_package": context, "capability_analysis": capabilities,
    }


def refresh_agent_contexts(project_ids: list[str] | None = None, output_path: Path = DEFAULT_OUTPUT, max_files: int = 24, registry_path: Path | None = None) -> dict:
    """Save bounded source observations; this grants no execution or acceptance.

    The registry argument identifies projects.json. Workspace registries are
    loaded as cached metadata and never overwritten or refreshed.
    """
    if isinstance(max_files, bool) or not isinstance(max_files, int) or not 1 <= max_files <= 64:
        raise ValueError("max_files must be an integer between 1 and 64")
    registry_path = Path(os.environ.get("AGENT_HUB_PROJECT_REGISTRY") or registry_path or DEFAULT_REGISTRY).expanduser().resolve()
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    entries = payload.get("projects", {})
    aliases = payload.get("aliases", {})
    selected_ids = project_ids if project_ids is not None else [key for key, entry in entries.items() if isinstance(entry, dict) and isinstance(entry.get("agent_context"), dict)]
    selected_ids = list(dict.fromkeys(aliases.get(key, key) for key in selected_ids))
    protected_outputs = {registry_path}
    projects = []
    for project_id in selected_ids:
        entry = entries.get(project_id)
        if not isinstance(entry, dict) or not isinstance(entry.get("agent_context"), dict):
            projects.append({"project_id": project_id, "status": "UNKNOWN_PROJECT_OR_CONTEXT_POLICY", "acceptance": False, "unknowns": ["No registered agent_context policy"]})
            continue
        try:
            projects.append(_refresh_project(project_id, entry, registry_path, max_files, protected_outputs))
        except (OSError, ValueError, KeyError, subprocess.TimeoutExpired) as error:
            projects.append({"project_id": project_id, "status": "CONTEXT_REFRESH_FAILED", "acceptance": False, "unknowns": [str(error)]})
    output = Path(output_path).expanduser().resolve()
    if output in protected_outputs:
        raise ValueError("agent context output must not overwrite a project or workspace registry")
    snapshot = {
        "schema_version": "managed-agent-context.v1", "generated_at": datetime.now(UTC).isoformat(),
        "read_only_business_repositories": True, "acceptance": False, "evidence_authority": "SOURCE_OBSERVATION_ONLY",
        "snapshot_scope": "scoped_snapshot_not_full_registry", "no_walk": True,
        "budget": {"max_files_per_project": max_files, "recent_commits_per_project": 6}, "projects": projects,
        "summary": {"projects": len(projects), "refreshed": sum(item["status"].startswith("REFRESHED") for item in projects), "selected_files": sum(len(item.get("selected_files", [])) for item in projects), "unknowns": sum(len(item.get("unknowns", [])) for item in projects)},
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return snapshot
