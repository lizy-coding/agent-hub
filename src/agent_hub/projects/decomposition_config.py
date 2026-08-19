"""Project identity and runtime paths for decomposition control-plane calls."""
from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import BaseModel, Field, model_validator

from agent_hub.workspace.config import WorkspaceConfig
from agent_hub.workspace.runtime import RuntimeWorkspaceProvider


AGENT_HUB_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REGISTRY = AGENT_HUB_ROOT / "workspace" / "projects.json"


class DecompositionProjectConfig(BaseModel):
    project_id: str
    program_id: str
    refactor_program_id: str
    adapter: str
    cluster_root: Path
    primary_repository_id: str
    repository_paths: dict[str, Path] = Field(default_factory=dict)
    snapshot_namespace: str

    @model_validator(mode="after")
    def normalize(self) -> "DecompositionProjectConfig":
        self.cluster_root = self.cluster_root.expanduser().resolve()
        self.repository_paths = {
            repository_id: path.expanduser().resolve()
            for repository_id, path in self.repository_paths.items()
        }
        if self.primary_repository_id not in self.repository_paths:
            raise ValueError(
                f"primary repository is not configured: {self.primary_repository_id}"
            )
        if self.adapter == "flutter_study" and self.primary_repository_id != "flutter_study":
            raise ValueError(
                "flutter_study adapter requires primary_repository_id=flutter_study"
            )
        return self

    def graph_input(self) -> dict[str, object]:
        return {
            "project_id": self.project_id,
            "program_id": self.program_id,
            "refactor_program_id": self.refactor_program_id,
            "adapter": self.adapter,
            "cluster_root": str(self.cluster_root),
            "primary_repository_id": self.primary_repository_id,
            "repository_paths": {
                key: str(value) for key, value in self.repository_paths.items()
            },
            "snapshot_namespace": self.snapshot_namespace,
        }


def load_decomposition_project(
    project_id: str | None = None,
    *,
    registry_path: Path | None = None,
) -> DecompositionProjectConfig:
    """Resolve stable project identity through a checked-in registry entry."""

    configured_registry = os.environ.get("AGENT_HUB_PROJECT_REGISTRY")
    path = Path(configured_registry) if configured_registry else registry_path or DEFAULT_REGISTRY
    path = path.expanduser().resolve()
    payload = json.loads(path.read_text(encoding="utf-8"))
    selected = project_id or os.environ.get("AGENT_HUB_PROJECT") or payload.get("default_project")
    projects = payload.get("projects")
    if not selected or not isinstance(projects, dict) or selected not in projects:
        raise KeyError(f"unknown decomposition project: {selected or '<unset>'}")
    entry = projects[selected]
    if not isinstance(entry, dict):
        raise ValueError(f"invalid decomposition project entry: {selected}")
    workspace_path = Path(str(entry.get("workspace_config", "")))
    if not workspace_path.is_absolute():
        workspace_path = AGENT_HUB_ROOT / workspace_path
    workspace_config = WorkspaceConfig.from_file(workspace_path.resolve())
    runtime = RuntimeWorkspaceProvider.from_config(workspace_config).workspace
    return DecompositionProjectConfig(
        project_id=str(selected),
        program_id=str(entry.get("program_id") or f"{selected}-decomposition-program"),
        refactor_program_id=str(entry.get("refactor_program_id") or f"{selected}-refactor-program"),
        adapter=str(entry.get("adapter") or selected),
        cluster_root=runtime.runtime_root,
        primary_repository_id=runtime.primary_repository_id,
        repository_paths={
            repository.repository_id: repository.runtime_path
            for repository in runtime.repositories
        },
        snapshot_namespace=str(entry.get("snapshot_namespace") or selected),
    )
