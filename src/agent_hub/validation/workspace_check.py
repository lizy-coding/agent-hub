"""Checks used by the bootstrap graph; no repository mutation or shell execution."""

import importlib.util
import json
from pathlib import Path

from pydantic import BaseModel, Field

from agent_hub.projects.registry import load_workspace_registry
from agent_hub.tools.path_guard import is_allowed_business_path
from agent_hub.workspace.config import WorkspaceConfig


class WorkspaceCheckResult(BaseModel):
    """Machine-readable outcome for the only bootstrap graph node."""

    ok: bool
    checks: dict[str, bool]
    repository_count: int = 0
    errors: list[str] = Field(default_factory=list)


def check_workspace(config: WorkspaceConfig) -> WorkspaceCheckResult:
    """Verify accessibility, registry structure, repository containment, and host import."""

    checks = {
        "workspace_accessible": config.workspace_root.is_dir(),
        "registry_readable": config.registry_path.is_file(),
        "agent_hub_environment_normal": importlib.util.find_spec("langgraph") is not None,
        "repository_paths_valid": False,
    }
    errors: list[str] = []
    repository_count = 0

    if not checks["workspace_accessible"]:
        errors.append("workspace_root is not an accessible directory")
    if not checks["registry_readable"]:
        errors.append("registry_path is not a readable file")

    if checks["registry_readable"]:
        try:
            # Parse first to distinguish malformed data from a missing registry.
            json.loads(config.registry_path.read_text(encoding="utf-8"))
            workspace = load_workspace_registry(config)
            repository_count = len(workspace.repositories)
            invalid = [
                repository.repo_id
                for repository in workspace.repositories
                if not repository.absolute_path.is_dir()
                or not is_allowed_business_path(repository.absolute_path, config)
            ]
            checks["repository_paths_valid"] = not invalid
            if invalid:
                errors.append("invalid or out-of-bound repository paths: " + ", ".join(invalid))
        except (OSError, ValueError, json.JSONDecodeError) as error:
            errors.append(f"registry cannot be read: {error}")

    if not checks["agent_hub_environment_normal"]:
        errors.append("langgraph is not importable in the Agent Hub environment")
    return WorkspaceCheckResult(
        ok=all(checks.values()),
        checks=checks,
        repository_count=repository_count,
        errors=errors,
    )
