"""Project-scoped release configuration for the hosting graph."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class ReleaseProjectConfig:
    project_id: str
    program_id: str
    cluster_root: Path
    primary_repository_id: str
    repository_path: Path
    release: dict[str, object]

    def graph_input(self) -> dict[str, object]:
        return {
            "project_id": self.project_id,
            "program_id": self.program_id,
            "adapter": "flutter_forge" if self.project_id == "flutter-forge" else "generic",
            "cluster_root": str(self.cluster_root),
            "primary_repository_id": self.primary_repository_id,
            "repository_paths": {self.primary_repository_id: str(self.repository_path)},
            "release": dict(self.release),
        }


def load_release_project(project_id: str | None = None) -> ReleaseProjectConfig:
    payload = json.loads((_ROOT / "workspace" / "projects.json").read_text(encoding="utf-8"))
    selected = project_id or str(payload.get("default_project") or "flutter-forge")
    project = (payload.get("projects") or {}).get(selected)
    if not isinstance(project, dict):
        raise ValueError(f"unknown project: {selected}")
    repository_id = str(project.get("adapter") or selected.replace("-", "_"))
    repository_path = (_ROOT / ".." / "langGraph" / repository_id).resolve()
    return ReleaseProjectConfig(selected, f"{selected}-release-program", _ROOT / ".." / "langGraph", repository_id, repository_path, dict(project.get("release") or {}))
