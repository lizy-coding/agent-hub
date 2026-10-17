"""Project-scoped release configuration for the hosting graph."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from agent_hub.projects.decomposition_config import DEFAULT_REGISTRY, load_decomposition_project


@dataclass(frozen=True)
class ReleaseProjectConfig:
    project_id: str
    program_id: str
    cluster_root: Path
    primary_repository_id: str
    repository_path: Path
    release: dict[str, object]
    adapter: str = "generic"

    def graph_input(self) -> dict[str, object]:
        return {
            "project_id": self.project_id,
            "program_id": self.program_id,
            "adapter": self.adapter,
            "cluster_root": str(self.cluster_root),
            "primary_repository_id": self.primary_repository_id,
            "repository_paths": {self.primary_repository_id: str(self.repository_path)},
            "release": dict(self.release),
        }


def load_release_project(project_id: str | None = None, *, registry_path: Path | None = None) -> ReleaseProjectConfig:
    path = Path(os.environ.get("AGENT_HUB_PROJECT_REGISTRY") or registry_path or DEFAULT_REGISTRY)
    payload = json.loads(path.read_text(encoding="utf-8"))
    try:
        config = load_decomposition_project(project_id, registry_path=path)
    except KeyError as error:
        raise ValueError(str(error)) from error
    project = payload["projects"][config.project_id]
    return ReleaseProjectConfig(
        project_id=config.project_id,
        program_id=f"{config.project_id}-release-program",
        cluster_root=config.cluster_root,
        primary_repository_id=config.primary_repository_id,
        repository_path=config.repository_paths[config.primary_repository_id],
        release=dict(project.get("release") or {}),
        adapter=config.adapter,
    )
