"""Load runtime context without embedding repository identities in graph source."""

import json
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

        payload = json.loads(config_path.read_text(encoding="utf-8"))
        if workspace_root is not None:
            payload["workspace_root"] = str(workspace_root)
            payload["allowed_paths"] = [str(workspace_root)]
        if registry_path is not None:
            payload["registry_path"] = str(registry_path)
        return cls.model_validate(payload)
