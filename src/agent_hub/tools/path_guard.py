"""Containment checks for all workspace business-path access."""

from pathlib import Path

from agent_hub.workspace.config import WorkspaceConfig


def is_within(path: Path, parent: Path) -> bool:
    """Return whether path resolves inside parent, including parent itself."""

    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def is_allowed_business_path(path: Path, config: WorkspaceConfig) -> bool:
    """Allow only configured paths within the workspace and outside exclusions."""

    resolved = path.resolve()
    if not is_within(resolved, config.workspace_root):
        return False
    if any(is_within(resolved, excluded) for excluded in config.excluded_paths):
        return False
    return any(is_within(resolved, allowed) for allowed in config.allowed_paths)
