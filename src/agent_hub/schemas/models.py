"""Stable, evidence-bearing contracts shared by Registry consumers."""

from pathlib import Path

from pydantic import AliasChoices, BaseModel, Field, model_validator


class Evidence(BaseModel):
    source: str
    path: str
    discovered_at: str
    detail: str | None = None


class Dependency(BaseModel):
    source: str
    target: str
    kind: str
    evidence: Evidence


class RuleFile(BaseModel):
    path: str
    scope: str
    provenance: str


class ValidationCommand(BaseModel):
    """A command candidate from a repository's declared validation metadata."""

    category: str
    command: str | None = None
    commands: list[str] = Field(default_factory=list)
    working_directory: str | None = None
    platform: str = "any"
    available: bool | None = None
    evidence: Evidence | None = None


class ProjectProfile(BaseModel):
    """A discovered project/package record from the bootstrap registry."""

    project_id: str
    relative_path: str
    classification: str
    build_descriptors: list[str] = Field(default_factory=list)
    runtime_build_system: list[str] = Field(default_factory=list)
    rule_entrypoints: list[str] = Field(default_factory=list)
    validation_candidates: dict[str, list[str]] = Field(default_factory=dict)


class DevelopmentUnit(BaseModel):
    unit_id: str
    repo_id: str
    relative_path: str
    unit_type: str
    manifests: list[str] = Field(default_factory=list)
    rule_files: list[RuleFile] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    dependencies: list[Dependency] = Field(default_factory=list)
    dependents: list[Dependency] = Field(default_factory=list)
    validation: list[ValidationCommand] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    freshness: str = "unknown"


class Repository(BaseModel):
    """Repository identity and contained projects from the bootstrap registry."""

    repo_id: str
    path: Path = Field(validation_alias=AliasChoices("path", "absolute_path"))
    git_root: Path | None = None
    repo_type: str = "unknown"
    runtime: list[str] = Field(default_factory=list)
    manifests: list[str] = Field(default_factory=list)
    rule_files: list[RuleFile] = Field(default_factory=list)
    validation: list[ValidationCommand] = Field(default_factory=list)
    development_units: list[DevelopmentUnit] = Field(default_factory=list)
    dependencies: list[Dependency] = Field(default_factory=list)
    dependents: list[Dependency] = Field(default_factory=list)
    platform_constraints: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    freshness: str = "unknown"

    @property
    def absolute_path(self) -> Path:
        """Compatibility with the P1 bootstrap reader."""
        return self.path


class Workspace(BaseModel):
    """Runtime workspace context injected into graphs."""

    workspace_root: Path
    allowed_paths: list[Path]
    excluded_paths: list[Path]
    registry_path: Path
    repositories: list[Repository] = Field(default_factory=list)
    refreshed_at: str = "unknown"
    schema_version: str = "workspace-registry.v2"
    manual_overrides: dict[str, object] = Field(default_factory=dict)
