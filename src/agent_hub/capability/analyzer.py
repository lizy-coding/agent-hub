"""Evidence-driven ownership, coupling, overlap, and extraction assessment."""

import re
from pathlib import Path

from agent_hub.capability.decisions import ACTIONABLE_DECISIONS, ExtractionDecision
from agent_hub.context.resolver import ContextLimits, ContextResolver, terms, first_matching_term
from agent_hub.projects import api as registry_api
from agent_hub.schemas.models import CapabilityAnalysis, CapabilityNode, ContextPackage, CouplingProfile, ExtractionAssessment, WorkspaceCapabilityMatch
from agent_hub.tools.path_guard import is_allowed_business_path
from agent_hub.workspace.config import WorkspaceConfig


SOURCE_SUFFIXES = {".dart", ".py", ".js", ".ts", ".jsx", ".tsx", ".c", ".cc", ".cpp", ".h", ".hpp", ".m", ".mm", ".swift", ".kt", ".java", ".rs", ".go", ".cs"}
SCRIPT_SUFFIXES = {".sh", ".bash", ".zsh", ".bat", ".cmd", ".ps1"}
CONFIG_SUFFIXES = {".yaml", ".yml", ".json", ".json5", ".toml", ".xml", ".ini", ".cfg", ".lock", ".gradle", ".kts", ".properties"}
_STRINGS_AND_COMMENTS = re.compile(r'''"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`|//[^\n]*|/\*.*?\*/''', re.DOTALL)


def _without_comments(text: str) -> str:
    return _STRINGS_AND_COMMENTS.sub(lambda match: " " * len(match[0]) if match[0].startswith(("//", "/*")) else match[0], text)


def _source_code(text: str) -> str:
    """Keep identifier evidence separate from claims inside comments/strings."""
    return _STRINGS_AND_COMMENTS.sub(lambda match: " " * len(match[0]), text)


def _identifier_parts(text: str) -> set[str]:
    parts = set()
    for identifier in re.findall(r"[A-Za-z_$][A-Za-z0-9_$]*", text):
        parts.add(identifier.lower())
        split = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", identifier)
        split = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", split)
        parts.update(part.lower() for part in re.split(r"[_$\s]+", split) if part)
    return parts


def _imports_ffi(text: str) -> bool:
    comments_removed = _without_comments(text)
    code = _source_code(text)
    for match in re.finditer(r"\bimport\s+['\"]dart:ffi['\"]", comments_removed):
        # An import-shaped string is documentation, not an actual directive.
        if code[match.start():match.start() + len("import")] == "import":
            return True
    return False


def evidence_kind(path: Path, text: str) -> str:
    if path.suffix.lower() in {".md", ".mdx", ".rst", ".txt"}:
        return "guidance"
    if path.suffix.lower() in CONFIG_SUFFIXES:
        return "configuration"
    if path.suffix.lower() in SCRIPT_SUFFIXES:
        return "script"
    if path.suffix.lower() in SOURCE_SUFFIXES:
        if text.startswith("#!") or re.search(r"\b(?:require\.main\s*===?\s*module|__name__\s*==\s*['\"]__main__['\"])", text):
            return "script"
        return "source"
    return "unsupported"


class CapabilityAnalyzer:
    def __init__(self, config: WorkspaceConfig):
        self.config = config
        self.resolver = ContextResolver(config)

    def _text(self, context: ContextPackage) -> dict[str, str]:
        return {item.absolute_path: self._text_file(Path(item.absolute_path)) for item in context.files}

    @staticmethod
    def _platform_bridge(text: str) -> bool:
        code = _source_code(text)
        return bool(
            re.search(r"\b(?:MethodChannel|EventChannel|BasicMessageChannel|FlutterPlugin|NativeFunction|DynamicLibrary)\b", code)
            or _imports_ffi(text)
        )

    @staticmethod
    def _adapter(text: str) -> bool:
        code = _source_code(text)
        cli = bool(re.search(r"\b(?:ArgParser|ArgResults|CommandRunner|stdout|stderr)\b|\bextends\s+Command\s*(?:<|\{)", code))
        ide = bool(re.search(r"\bimport\s+(?:com\.intellij|org\.eclipse)\.", code))
        return cli or ide

    def analyze_coupling(self, text: str) -> CouplingProfile:
        code = _source_code(text)
        identifiers = _identifier_parts(code)
        ui = bool(identifiers & {"widget", "statelesswidget", "statefulwidget", "custompaint"})
        state = bool(identifiers & {"provider", "riverpod", "bloc", "navigator", "router", "controller"})
        platform = self._platform_bridge(text) or bool(re.search(r"\bPlatform\.(?:is[A-Z]\w*|operatingSystem|environment)\b|\bkIsWeb\b", code))
        contract = bool(identifiers & {"interface", "service"}) or bool(re.search(r"\babstract\s+class\b", code))
        return CouplingProfile(ui="HIGH" if ui else "NONE", application_state="HIGH" if state else "LOW" if "state" in identifiers else "NONE", platform="HIGH" if platform else "NONE", external_contract="MEDIUM" if contract else "NONE")

    def classify_ownership(self, text: str, coupling: CouplingProfile, public_widget: bool = False) -> str:
        code = _source_code(text)
        identifiers = _identifier_parts(code)
        if identifiers & {"gorouter", "navigator"} or ("controller" in identifiers and len(identifiers & {"service", "pipeline", "repository"}) >= 2):
            return "application_orchestration"
        if self._adapter(text) or ("controller" in identifiers and "service" in identifiers and ("final" in identifiers or "state" in identifiers)):
            return "adapter"
        if coupling.ui == "HIGH":
            composition = bool(re.search(r"\bfinal\s+(?:List\s*<\s*Widget\s*>|Widget\??|VoidCallback\??)\b", code))
            composition = composition and bool(re.search(r"\b(?:Scaffold\s*\(|appBar\s*:|floatingActionButton\s*:|sections\b)", code))
            return "reusable_capability" if public_widget and composition else "ui_only"
        if self._platform_bridge(text):
            return "platform_plugin"
        if coupling.platform == "HIGH":
            return "adapter"
        if identifiers & {"parser", "parse", "algorithm", "model", "transform"}:
            return "shared_core"
        return "unknown"

    def _is_public_export(self, unit_id: str, source_path: str, export_paths: list[Path] | None = None, *, texts: dict[Path, str] | None = None) -> bool:
        unit = registry_api.get_development_unit(self.config, unit_id)
        repo = registry_api.get_repository(self.config, unit.repo_id) if unit else None
        if not unit or not repo:
            return False
        source = Path(source_path)
        if not source.is_absolute():
            source = self.config.workspace_root / source
        source = source.resolve()
        lib_root = (repo.path / unit.relative_path / "lib").resolve()
        entries = lib_root.glob("*.dart") if export_paths is None else [path for path in export_paths if path.parent == lib_root and path.suffix == ".dart"]
        for entry in entries:
            exported = texts.get(entry, "") if texts is not None else self._text_file(entry)
            code = _source_code(exported)
            for match in re.finditer(r"\bexport\s+['\"]([^'\"]+)['\"]", _without_comments(exported)):
                if code[match.start():match.start() + len("export")] != "export":
                    continue
                relative = match[1]
                # Exporting a same-named file in another directory is not public
                # visibility evidence for this file.
                if not re.match(r"[A-Za-z][\w+.-]*:", relative) and (entry.parent / relative).resolve() == source:
                    return True
        return False

    def _text_file(self, path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8") if is_allowed_business_path(path, self.config) else ""
        except (OSError, UnicodeDecodeError):
            return ""

    def match_workspace_capabilities(self, node: CapabilityNode, context: ContextPackage, *, export_paths: list[Path] | None = None, texts: dict[Path, str] | None = None):
        matches = []
        unit_id = node.development_units[0]
        unit = registry_api.get_development_unit(self.config, unit_id)
        incoming = [edge for repo in registry_api.list_repositories(self.config) for edge in registry_api.get_dependencies(self.config, repo.repo_id) if edge.target == unit_id]
        if unit and self._is_public_export(unit_id, node.files[0], export_paths, texts=texts) and incoming:
            edge = incoming[0]
            matches.append(WorkspaceCapabilityMatch(source_capability_id=node.capability_id, target_repo=unit.repo_id, target_unit=unit_id, match_type="existing_unit_strong_match", matched_contracts=node.files, matched_symbols=node.symbols, evidence_refs=[edge.evidence.path] + node.evidence_refs, confidence="HIGH"))
        for edge in node.dependencies:
            target = registry_api.get_development_unit(self.config, edge.target)
            if target:
                # Manifest adjacency gives a context relationship, without
                # proving that this source duplicates the target's contract.
                matches.append(WorkspaceCapabilityMatch(source_capability_id=node.capability_id, target_repo=target.repo_id, target_unit=target.unit_id, match_type="existing_unit_partial_overlap", matched_contracts=[], matched_symbols=[], evidence_refs=[edge.evidence.path], confidence="MEDIUM"))
        return matches

    def assess_extraction(self, node: CapabilityNode, matches, *, query_matched: bool = True):
        strong = next((match for match in matches if match.match_type == "existing_unit_strong_match"), None)
        target = None
        reasons = [f"ownership={node.ownership}"]
        blockers = list(node.unknowns)
        if node.ownership == "application_orchestration":
            decision = ExtractionDecision.KEEP_IN_APPLICATION
        elif node.ownership == "adapter":
            decision = ExtractionDecision.ADAPTER_ONLY
        elif not query_matched:
            decision = ExtractionDecision.NOT_ENOUGH_EVIDENCE
            reasons.append("No source evidence matches the current query.")
        elif node.ownership == "unknown":
            decision = ExtractionDecision.NOT_ENOUGH_EVIDENCE
        elif node.ownership == "ui_only":
            decision = ExtractionDecision.UNKNOWN
        elif strong:
            decision = ExtractionDecision.EXTEND_EXISTING_UNIT if node.ownership == "reusable_capability" else ExtractionDecision.MOVE_TO_EXISTING_UNIT
            target = strong
        elif node.ownership == "shared_core" and node.coupling.ui in ("NONE", "LOW") and node.coupling.application_state in ("NONE", "LOW"):
            decision = ExtractionDecision.NEW_SHARED_CORE_CANDIDATE
        elif node.ownership == "platform_plugin":
            decision = ExtractionDecision.NEW_PLUGIN_CANDIDATE
        else:
            decision = ExtractionDecision.NOT_ENOUGH_EVIDENCE
        return ExtractionAssessment(capability_id=node.capability_id, decision=decision.value, target_repo=target.target_repo if target else None, target_unit=target.target_unit if target else None, reasons=reasons, blockers=blockers, evidence_refs=node.evidence_refs, confidence=node.confidence)

    def analyze_capabilities(self, requirement: str, target_repository: str, *, candidate_paths: list[str] | None = None, limits: ContextLimits | None = None, source_texts: dict[str, str] | None = None) -> CapabilityAnalysis:
        # Preserve one mapping across resolver, ownership, and export analysis.
        # Resolver validates unsupported types before any evidence is consumed.
        if isinstance(source_texts, dict):
            source_texts = dict(source_texts)
        context = self.resolver.resolve_context(requirement, target_repository, limits, candidate_paths=candidate_paths, source_texts=source_texts)
        texts: dict[Path, str] = {}
        evidence_kinds, query_relevance = {}, {}
        nodes = []
        query_terms = terms(requirement)

        def evidence_path(file):
            repository = registry_api.get_repository(self.config, file.repo_id)
            relative = Path(file.absolute_path).relative_to(repository.path).as_posix()
            # Legacy discovery can project neighboring repository evidence.
            # Bounded/frozen intakes keep the requested repo-relative protocol.
            key = relative if file.repo_id == target_repository else f"{file.repo_id}:{relative}"
            return relative, key

        for file in context.files:
            path = Path(file.absolute_path)
            repo_relative, key = evidence_path(file)
            text = source_texts[repo_relative] if source_texts is not None else self._text_file(path)
            texts[path] = text
            evidence_kinds[key] = evidence_kind(path, text)
            # Task-specific relevance is independent of source ownership and of
            # the bounded symbol projection (which can have a zero budget).
            query_refs = [f"{file.relative_path}:{number}" for number, line in enumerate(text.splitlines(), 1) if first_matching_term(line, query_terms)]
            query_relevance[key] = {"matched": bool(query_refs), "status": "matched" if query_refs else "no_match" if text else "unreadable", "evidence_refs": query_refs}
        export_paths = list(texts) if candidate_paths is not None else None
        matched_by_id = {}
        for file in context.files:
            unit = registry_api.get_development_unit(self.config, file.unit_id)
            if not unit:
                continue
            path = Path(file.absolute_path)
            repo_relative, key = evidence_path(file)
            kind = evidence_kinds[key]
            if kind not in {"source", "script"}:
                continue
            unit_text = texts[path]
            if not unit_text:
                continue
            symbols = [symbol.name for symbol in context.symbols if symbol.file == file.absolute_path]
            coupling = self.analyze_coupling(unit_text)
            public = self._is_public_export(file.unit_id, file.absolute_path, export_paths, texts=texts if candidate_paths is not None else None)
            ownership = self.classify_ownership(unit_text, coupling, public)
            unknowns = [] if ownership != "unknown" else ["Insufficient bounded source evidence for ownership."]
            query_matched = bool(query_relevance[key]["matched"])
            if not query_matched:
                unknowns.append("No source evidence matches the current query; extraction requires relevant evidence.")
            deps = registry_api.get_dependencies(self.config, file.unit_id) + registry_api.get_dependents(self.config, file.unit_id)
            refs = list(dict.fromkeys(file.evidence_refs + [dependency.evidence.path for dependency in deps]))
            confidence = "HIGH" if refs and ownership != "unknown" else "MEDIUM" if refs else "LOW"
            identity = f"capability:{file.repo_id}:{repo_relative}"
            matched_by_id[identity] = query_matched
            nodes.append(CapabilityNode(capability_id=identity, label=f"{kind}_evidence", target_repo=file.repo_id, development_units=[file.unit_id], files=[file.relative_path], symbols=symbols, responsibilities=[f"{kind} evidence anchor"], ownership=ownership, coupling=coupling, dependencies=deps, evidence_refs=refs, confidence=confidence, unknowns=unknowns))
        matches = [match for node in nodes for match in self.match_workspace_capabilities(node, context, export_paths=export_paths, texts=texts if candidate_paths is not None else None)]
        assessments = [self.assess_extraction(node, [match for match in matches if match.source_capability_id == node.capability_id], query_matched=matched_by_id[node.capability_id]) for node in nodes]
        unknowns = [unknown.reason for unknown in context.unknowns] + [unknown for node in nodes for unknown in node.unknowns]
        controls = sum(kind in {"guidance", "configuration", "unsupported"} for kind in evidence_kinds.values())
        return CapabilityAnalysis(
            requirement=requirement, target_repository=target_repository,
            context_ref={"confidence": context.confidence, "metrics": context.metrics, "evidence_kinds": evidence_kinds, "query_relevance": query_relevance},
            capabilities=nodes, workspace_matches=matches, extraction_assessments=assessments,
            keep_in_application=[item.capability_id for item in assessments if item.decision == ExtractionDecision.KEEP_IN_APPLICATION.value],
            extraction_candidates=[item.capability_id for item in assessments if item.decision in ACTIONABLE_DECISIONS],
            unknowns=unknowns, evidence_summary={"context_evidence": context.metrics.get("evidence_count", 0), "capability_nodes": len(nodes)},
            metrics={"bounded_files_read": context.metrics.get("searched_files", len(context.files)), "capabilities": len(nodes), "matches": len(matches), "control_evidence_files": controls, "source_evidence_files": sum(kind == "source" for kind in evidence_kinds.values()), "script_evidence_files": sum(kind == "script" for kind in evidence_kinds.values()), "query_matched_capabilities": sum(matched_by_id.values()), "query_unmatched_capabilities": len(nodes) - sum(matched_by_id.values()), "query_actionable_decisions": sum(item.decision in ACTIONABLE_DECISIONS for item in assessments), "abstained_extraction_decisions": sum(item.decision == ExtractionDecision.NOT_ENOUGH_EVIDENCE.value for item in assessments)},
        )

    def explain_capability(self, node: CapabilityNode):
        return node.model_dump()

    def validate_capability_analysis(self, analysis: CapabilityAnalysis):
        errors = []
        identities = set()
        for node in analysis.capabilities:
            if node.capability_id in identities:
                errors.append(f"duplicate capability identity: {node.capability_id}")
            identities.add(node.capability_id)
            if not node.evidence_refs:
                errors.append(f"missing evidence: {node.capability_id}")
            if node.confidence == "HIGH" and node.ownership == "unknown":
                errors.append(f"untraceable high ownership: {node.capability_id}")
        return errors
