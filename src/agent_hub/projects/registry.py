"""Read the external bootstrap registry without inspecting business source files."""

import json
from pathlib import Path

from agent_hub.schemas.models import Repository, Workspace
from agent_hub.workspace.config import WorkspaceConfig


def load_workspace_registry(config: WorkspaceConfig) -> Workspace:
    """Load only the declared registry and map its repository facts to public schema."""

    registry_path = config.registry_path
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    repositories = [Repository.model_validate(item) for item in payload.get("repositories", [])]
    return Workspace(
        workspace_root=config.workspace_root,
        allowed_paths=config.allowed_paths,
        excluded_paths=config.excluded_paths,
        registry_path=registry_path,
        repositories=repositories,
    )
