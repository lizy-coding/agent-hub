"""Stable, evidence-bearing contracts shared by Registry consumers."""

from pathlib import Path

from pydantic import AliasChoices, BaseModel, Field, model_validator


class Evidence(BaseModel):
    source: str
    path: str
    discovered_at: str
    detail: str | None = None


class ProjectIdentity(BaseModel):
    project_id: str
    repository_id: str
    role: str
    source_type: str


class ProjectSource(BaseModel):
    repository_id: str
    source_type: str
    source_locator: str
    revision: str | None = None
    checkout_policy: str = "PRECHECKED_OUT"
    managed: bool = False


class RuntimeRepository(BaseModel):
    repository_id: str
    runtime_path: Path
    source: ProjectSource
    revision: str | None = None
    role: str = "REFERENCE"
    managed: bool = False
    writable: bool = False
    development_units: list[str] = Field(default_factory=list)


class RuntimeWorkspace(BaseModel):
    runtime_id: str
    runtime_root: Path
    checkout_root: Path
    repositories: list[RuntimeRepository] = Field(default_factory=list)
    primary_repository_id: str
    environment: str = "LOCAL"
    created_at: str


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


class ContextCandidate(BaseModel):
    id: str
    classification: str
    confidence: str
    reasons: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


class ContextFile(BaseModel):
    absolute_path: str
    relative_path: str
    repo_id: str
    unit_id: str
    relevance: str
    evidence_refs: list[str] = Field(default_factory=list)


class ContextSymbol(BaseModel):
    name: str
    kind: str
    file: str
    line: int
    evidence_refs: list[str] = Field(default_factory=list)


class ContextRule(BaseModel):
    path: str
    scope: str
    applies_to: str
    provenance: str | None = None


class ContextUnknown(BaseModel):
    subject: str
    reason: str
    required_evidence: str


class ContextPackage(BaseModel):
    request: dict[str, object]
    scope: dict[str, list[str]]
    candidates: list[ContextCandidate] = Field(default_factory=list)
    files: list[ContextFile] = Field(default_factory=list)
    symbols: list[ContextSymbol] = Field(default_factory=list)
    rules: list[ContextRule] = Field(default_factory=list)
    dependencies: list[Dependency] = Field(default_factory=list)
    unknowns: list[ContextUnknown] = Field(default_factory=list)
    confidence: str = "LOW"
    metrics: dict[str, int] = Field(default_factory=dict)
    planned_capabilities: list[dict[str, object]] = Field(default_factory=list)


class CouplingProfile(BaseModel):
    ui: str = "UNKNOWN"
    application_state: str = "UNKNOWN"
    platform: str = "UNKNOWN"
    external_contract: str = "UNKNOWN"


class CapabilityNode(BaseModel):
    capability_id: str
    label: str
    target_repo: str
    development_units: list[str]
    files: list[str] = Field(default_factory=list)
    symbols: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    ownership: str = "unknown"
    coupling: CouplingProfile = Field(default_factory=CouplingProfile)
    dependencies: list[Dependency] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: str = "LOW"
    unknowns: list[str] = Field(default_factory=list)


class WorkspaceCapabilityMatch(BaseModel):
    source_capability_id: str
    target_repo: str
    target_unit: str
    match_type: str
    matched_contracts: list[str] = Field(default_factory=list)
    matched_symbols: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: str = "LOW"


class ExtractionAssessment(BaseModel):
    capability_id: str
    decision: str
    target_repo: str | None = None
    target_unit: str | None = None
    reasons: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: str = "LOW"


class CapabilityAnalysis(BaseModel):
    requirement: str
    target_repository: str
    context_ref: dict[str, object]
    capabilities: list[CapabilityNode] = Field(default_factory=list)
    workspace_matches: list[WorkspaceCapabilityMatch] = Field(default_factory=list)
    extraction_assessments: list[ExtractionAssessment] = Field(default_factory=list)
    keep_in_application: list[str] = Field(default_factory=list)
    extraction_candidates: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    evidence_summary: dict[str, int] = Field(default_factory=dict)
    metrics: dict[str, int] = Field(default_factory=dict)


class BlockedItem(BaseModel):
    capability_id: str
    reason: str
    missing_evidence: list[str] = Field(default_factory=list)
    prohibited_decisions: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


class MigrationTask(BaseModel):
    task_id: str
    title: str
    action_type: str
    source_repo: str
    target_repo: str | None = None
    source_units: list[str] = Field(default_factory=list)
    target_units: list[str] = Field(default_factory=list)
    allowed_paths: list[str] = Field(default_factory=list)
    context_refs: list[str] = Field(default_factory=list)
    applicable_rules: list[ContextRule] = Field(default_factory=list)
    dependency_tasks: list[str] = Field(default_factory=list)
    preconditions: list[str] = Field(default_factory=list)
    expected_changes: list[str] = Field(default_factory=list)
    invariants: list[str] = Field(default_factory=list)
    acceptance: list[str] = Field(default_factory=list)
    validation: list[ValidationCommand] = Field(default_factory=list)
    rollback_boundary: str
    risk: str
    status: str = "PLANNED"
    migration_delta: "MigrationDelta | None" = None


class MigrationDelta(BaseModel):
    capability_id: str
    current_owner_repo: str
    current_owner_unit: str | None = None
    current_paths: list[str] = Field(default_factory=list)
    intended_owner_repo: str | None = None
    intended_owner_unit: str | None = None
    destination_paths: list[str] = Field(default_factory=list)
    consumer_paths: list[str] = Field(default_factory=list)
    contract_delta: list[str] = Field(default_factory=list)
    implementation_delta: list[str] = Field(default_factory=list)
    dependency_delta: list[str] = Field(default_factory=list)
    cleanup_delta: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    status: str


class MigrationPlan(BaseModel):
    plan_id: str
    requirement: str
    target_repository: str
    source_analysis_ref: dict[str, object]
    architecture_invariants: list[str] = Field(default_factory=list)
    migration_tasks: list[MigrationTask] = Field(default_factory=list)
    dependency_dag: dict[str, list[str]] = Field(default_factory=dict)
    blocked_items: list[BlockedItem] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    validation_strategy: list[ValidationCommand] = Field(default_factory=list)
    risk_summary: dict[str, int] = Field(default_factory=dict)
    metrics: dict[str, int] = Field(default_factory=dict)
    status: str
    evidence_resolutions: list["CapabilityResolution"] = Field(default_factory=list)


class CapabilityResolution(BaseModel):
    capability_id: str
    prior_block_reason: str
    terminal_state: str
    current_owner_repo: str | None = None
    current_owner_unit: str | None = None
    intended_owner_repo: str | None = None
    intended_owner_unit: str | None = None
    source_paths: list[str] = Field(default_factory=list)
    destination_paths: list[str] = Field(default_factory=list)
    consumer_paths: list[str] = Field(default_factory=list)
    public_contract_paths: list[str] = Field(default_factory=list)
    dependency_evidence: list[str] = Field(default_factory=list)
    callsite_evidence: list[str] = Field(default_factory=list)
    applicable_rules: list[ContextRule] = Field(default_factory=list)
    validation_evidence: list[ValidationCommand] = Field(default_factory=list)
    migration_delta: MigrationDelta | None = None
    missing_evidence: list[str] = Field(default_factory=list)
    confidence: str = "LOW"
    evidence_refs: list[str] = Field(default_factory=list)
