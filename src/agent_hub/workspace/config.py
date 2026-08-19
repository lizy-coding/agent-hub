"""Load runtime context without embedding repository identities in graph source."""

import json
import os
from pathlib import Path

from pydantic import BaseModel, Field, model_validator


class WorkspaceConfig(BaseModel):
    """The minimal runtime context accepted by the bootstrap graph."""

    workspace_root: Path
    allowed_paths: list[Path] = Field(default_factory=list)
    excluded_paths: list[Path] = Field(default_factory=list)
    registry_path: Path
    registry_storage_path: Path | None = None
    runtime: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def normalize_and_validate_paths(self) -> "WorkspaceConfig":
        self.workspace_root = self.workspace_root.expanduser().resolve()
        self.allowed_paths = [path.expanduser().resolve() for path in self.allowed_paths]
        self.excluded_paths = [path.expanduser().resolve() for path in self.excluded_paths]
        self.registry_path = self.registry_path.expanduser().resolve()
        if self.registry_storage_path is not None:
            self.registry_storage_path = self.registry_storage_path.expanduser().resolve()
        if not self.allowed_paths:
            self.allowed_paths = [self.workspace_root]
        return self

    @classmethod
    def from_file(
        cls,
        config_path: Path,
        *,
        workspace_root: Path | None = None,
        registry_path: Path | None = None,
    ) -> "WorkspaceConfig":
        """Load config and permit explicit runtime injection without source edits."""

        config_path = config_path.expanduser().resolve()
        base = config_path.parent
        payload = json.loads(config_path.read_text(encoding="utf-8"))

        def configured_path(value: object) -> str:
            expanded = Path(os.path.expandvars(str(value))).expanduser()
            return str(expanded if expanded.is_absolute() else (base / expanded).resolve())

        for key in ("workspace_root", "registry_path", "registry_storage_path"):
            if payload.get(key):
                payload[key] = configured_path(payload[key])
        payload["allowed_paths"] = [configured_path(path) for path in payload.get("allowed_paths", [])]
        payload["excluded_paths"] = [configured_path(path) for path in payload.get("excluded_paths", [])]
        runtime = payload.get("runtime")
        if isinstance(runtime, dict):
            for key in ("runtime_root", "checkout_root"):
                if runtime.get(key):
                    runtime[key] = configured_path(runtime[key])
            repositories = runtime.get("repositories")
            if isinstance(repositories, dict):
                for entry in repositories.values():
                    if isinstance(entry, dict) and entry.get("runtime_path"):
                        entry["runtime_path"] = configured_path(entry["runtime_path"])
        if workspace_root is not None:
            payload["workspace_root"] = str(workspace_root.expanduser().resolve())
            payload["allowed_paths"] = [str(workspace_root.expanduser().resolve())]
        if registry_path is not None:
            payload["registry_path"] = str(registry_path.expanduser().resolve())
        return cls.model_validate(payload)
