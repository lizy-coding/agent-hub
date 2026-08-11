"""Persisted Workspace Registry and the stable API for later Context Resolver use."""

import json
from pathlib import Path

from agent_hub.projects.discovery import discover
from agent_hub.schemas.models import DevelopmentUnit, Repository, RuleFile, ValidationCommand, Workspace
from agent_hub.tools.path_guard import is_allowed_business_path
from agent_hub.workspace.config import WorkspaceConfig


class WorkspaceRegistry:
    def __init__(self, config: WorkspaceConfig):
        self.config = config
        self.storage_path = config.registry_storage_path or (Path(__file__).resolve().parents[4] / "workspace" / "registry.json")

    def get_workspace(self) -> Workspace:
        return Workspace.model_validate(json.loads(self.storage_path.read_text(encoding="utf-8")))

    def list_repositories(self) -> list[Repository]: return self.get_workspace().repositories
    def get_repository(self, repo_id: str) -> Repository | None: return next((r for r in self.list_repositories() if r.repo_id == repo_id), None)
    def list_development_units(self) -> list[DevelopmentUnit]: return [u for r in self.list_repositories() for u in r.development_units]
    def get_development_unit(self, unit_id: str) -> DevelopmentUnit | None: return next((u for u in self.list_development_units() if u.unit_id == unit_id), None)
    def find_unit_by_path(self, path: Path) -> DevelopmentUnit | None:
        resolved = path.resolve()
        if not is_allowed_business_path(resolved, self.config): return None
        candidates = [(Path(r.path) / u.relative_path, u) for r in self.list_repositories() for u in r.development_units]
        matched = [u for base, u in candidates if resolved == base.resolve() or base.resolve() in resolved.parents]
        return max(matched, key=lambda u: len(u.relative_path)) if matched else None
    def get_dependencies(self, identifier: str):
        unit = self.get_development_unit(identifier)
        if unit: return unit.dependencies
        repo = self.get_repository(identifier); return repo.dependencies if repo else []
    def get_dependents(self, identifier: str):
        unit = self.get_development_unit(identifier)
        if unit: return unit.dependents
        repo = self.get_repository(identifier); return repo.dependents if repo else []
    def get_rule_files(self, path_or_unit: str | Path):
        unit = self.get_development_unit(str(path_or_unit))
        if unit: return unit.rule_files
        found = self.find_unit_by_path(Path(path_or_unit))
        return found.rule_files if found else []
    def get_validation_commands(self, identifier: str):
        unit = self.get_development_unit(identifier)
        if unit: return unit.validation
        repo = self.get_repository(identifier); return repo.validation if repo else []
    def refresh(self) -> dict:
        previous = self.get_workspace() if self.storage_path.is_file() else None
        current = discover(self.config)
        if previous: current.manual_overrides = previous.manual_overrides
        diff = _diff(previous, current)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.storage_path.write_text(json.dumps(current.model_dump(mode="json"), indent=2, sort_keys=True), encoding="utf-8")
        return diff
    def validate_registry(self) -> list[str]:
        errors = []
        try: workspace = self.get_workspace()
        except (OSError, ValueError, json.JSONDecodeError) as error: return [f"registry unreadable: {error}"]
        for repo in workspace.repositories:
            if not is_allowed_business_path(repo.path, self.config): errors.append(f"repository outside boundary: {repo.repo_id}")
            for unit in repo.development_units:
                for edge in unit.dependencies:
                    if not edge.evidence.path: errors.append(f"dependency missing evidence: {edge.source}->{edge.target}")
        return errors


def _diff(previous: Workspace | None, current: Workspace) -> dict:
    def stable(value):
        if isinstance(value, dict): return {k: stable(v) for k, v in value.items() if k not in {"freshness", "discovered_at"}}
        if isinstance(value, list): return [stable(item) for item in value]
        return value
    old = {r.repo_id: stable(r.model_dump(mode="json")) for r in previous.repositories} if previous else {}
    new = {r.repo_id: stable(r.model_dump(mode="json")) for r in current.repositories}
    return {"added": sorted(set(new)-set(old)), "removed": sorted(set(old)-set(new)), "changed": sorted(k for k in set(old)&set(new) if old[k] != new[k]), "unchanged": sorted(k for k in set(old)&set(new) if old[k] == new[k]), "ambiguous": []}
