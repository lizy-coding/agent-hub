"""Evidence-driven, bounded Context Resolver built on the Registry public API."""

import re
from dataclasses import dataclass
from pathlib import Path

from agent_hub.projects import api as registry_api
from agent_hub.schemas.models import ContextCandidate, ContextFile, ContextPackage, ContextRule, ContextSymbol, ContextUnknown, DevelopmentUnit
from agent_hub.tools.path_guard import is_allowed_business_path, is_within
from agent_hub.workspace.config import WorkspaceConfig

EXCLUDED = {".git", "build", ".dart_tool", "node_modules", "generated", ".venv", ".langgraph_api"}
SOURCE_SUFFIXES = {".dart", ".py", ".c", ".cc", ".cpp", ".h", ".hpp"}


@dataclass(frozen=True)
class ContextLimits:
    max_candidate_repositories: int = 6
    max_files: int = 40
    max_symbols: int = 80
    max_dependency_depth: int = 2


STOP_TERMS = {"workspace", "current", "analysis", "capability", "package", "plugin", "existing", "related", "between", "with", "native", "flutter", "application"}
SEMANTIC_QUERY_TERMS = {"controller", "service", "adapter", "router", "route", "parser", "model", "render", "widget", "channel", "ffi", "pipeline", "state"}
def terms(requirement: str) -> list[str]:
    return [term for term in dict.fromkeys(term.lower() for term in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", requirement)) if term not in STOP_TERMS]


class RepositorySearcher:
    def __init__(self, config: WorkspaceConfig): self.config = config
    def _owns_path(self, unit: DevelopmentUnit, path: Path) -> bool:
        """Keep parent repository scans from attributing nested units to itself."""
        repo = registry_api.get_repository(self.config, unit.repo_id)
        if not repo: return False
        base = (repo.path / unit.relative_path).resolve()
        for other in registry_api.list_development_units(self.config):
            if other.repo_id != unit.repo_id or other.unit_id == unit.unit_id or other.relative_path == ".":
                continue
            nested = (repo.path / other.relative_path).resolve()
            if is_within(nested, base) and is_within(path, nested):
                return False
        return True
    def search_symbols(self, unit: DevelopmentUnit, term_list: list[str], max_results: int):
        return self._search(unit, term_list, max_results, "symbol")
    def search_callsites(self, unit: DevelopmentUnit, term_list: list[str], max_results: int):
        return self._search(unit, term_list, max_results, "callsite")
    def _search(self, unit, term_list, max_results, kind):
        repo = registry_api.get_repository(self.config, unit.repo_id)
        if not repo: return []
        base = (repo.path / unit.relative_path).resolve()
        matches = []
        for path in base.rglob("*"):
            if not path.is_file() or path.is_symlink() or any(part in EXCLUDED for part in path.parts) or not is_allowed_business_path(path, self.config) or not self._owns_path(unit, path): continue
            try: lines = path.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError): continue
            for line_number, line in enumerate(lines, 1):
                for term in term_list:
                    exact = re.search(rf"\b{re.escape(term)}\b", line, re.IGNORECASE)
                    if not exact: continue
                    if kind == "callsite" and not ("import " in line or "package:" in line or re.search(rf"\b{re.escape(term)}\s*\(", line, re.I)): continue
                    matches.append((path, line_number, term, kind))
                    break
                if len(matches) >= max_results: break
        # Source evidence is a more direct implementation signal than mentions in
        # documentation, generated metadata, or tests.  This is ordering only:
        # every selected result still has an exact textual evidence reference.
        return sorted(matches, key=lambda item: (item[0].suffix not in SOURCE_SUFFIXES, str(item[0]), item[1]))[:max_results]
    def semantic_anchors(self, unit: DevelopmentUnit, max_results: int, preferred_terms: list[str]):
        """Return bounded source anchors independent of a requirement's wording."""
        repo=registry_api.get_repository(self.config,unit.repo_id)
        if not repo: return []
        patterns=(r'abstract class ',r'implements ',r'class \w+Controller',r'GoRouter\s*\(',r'MethodChannel',r'class \w*(Parser|Model)',r'(StatelessWidget|StatefulWidget)')
        found=[]
        for path in (repo.path/unit.relative_path).rglob('*.dart'):
            if path.is_symlink() or any(part in EXCLUDED for part in path.parts) or not is_allowed_business_path(path,self.config) or not self._owns_path(unit,path): continue
            try: text=path.read_text(encoding='utf-8')
            except (OSError,UnicodeDecodeError): continue
            for number,line in enumerate(text.splitlines(),1):
                if any(re.search(pattern,line) for pattern in patterns):
                    score=sum(term in line.lower() or term in path.name.lower() for term in preferred_terms)
                    found.append((score,path,number,'semantic_anchor','anchor')); break
        return [(path,number,term,kind) for _,path,number,term,kind in sorted(found,key=lambda item:(-item[0],str(item[1])))[:max_results]]


class RuleResolver:
    def __init__(self, config: WorkspaceConfig): self.config = config
    def resolve_rules_for_path(self, path_or_unit: str) -> list[ContextRule]:
        unit = registry_api.get_development_unit(self.config, path_or_unit)
        rules = registry_api.get_rule_files(self.config, path_or_unit)
        return [ContextRule(path=rule.path, scope=rule.scope, applies_to=unit.unit_id if unit else str(path_or_unit)) for rule in rules]


class EvidenceScorer:
    def score(self, *, dependency_count: int, symbol_count: int, callsite_count: int, rule_count: int, file_count: int, name_only: bool, unknown: bool) -> str:
        points = dependency_count * 2 + (2 if symbol_count or callsite_count else 0) + (1 if rule_count else 0) + (1 if file_count else 0) - (2 if unknown else 0)
        if name_only: return "LOW"
        return "HIGH" if points >= 5 else "MEDIUM" if points >= 2 else "LOW" if points >= 0 else "BLOCKED"


class ContextResolver:
    def __init__(self, config: WorkspaceConfig):
        self.config, self.searcher, self.rules, self.scorer = config, RepositorySearcher(config), RuleResolver(config), EvidenceScorer()
    def search_symbols(self, unit_id: str, query: str):
        unit = registry_api.get_development_unit(self.config, unit_id)
        return [] if not unit else self.searcher.search_symbols(unit, terms(query), 80)
    def search_callsites(self, unit_id: str, query: str):
        unit = registry_api.get_development_unit(self.config, unit_id)
        return [] if not unit else self.searcher.search_callsites(unit, terms(query), 80)
    def resolve_rules_for_path(self, path_or_unit: str): return self.rules.resolve_rules_for_path(path_or_unit)
    def explain_candidate(self, candidate: ContextCandidate) -> dict: return candidate.model_dump()
    def resolve_context(self, requirement: str, target_repository: str | None = None, limits: ContextLimits | None = None) -> ContextPackage:
        limits = limits or ContextLimits(); term_list = terms(requirement); repositories = registry_api.list_repositories(self.config)
        if target_repository:
            selected_repos = [repo for repo in repositories if repo.repo_id == target_repository]
        else:
            selected_repos = repositories[:limits.max_candidate_repositories]
        units = [unit for repo in selected_repos for unit in repo.development_units]
        # Root application units are composition boundaries; process them before
        # nested packages so the bounded file budget cannot hide their anchors.
        units.sort(key=lambda unit: (unit.relative_path != ".", len(unit.relative_path)))
        # Registry-backed neighborhood expansion never turns a neighbor into a required change.
        seen = {unit.unit_id for unit in units}
        frontier = list(units)
        for _ in range(limits.max_dependency_depth):
            next_frontier = []
            for unit in frontier:
                for edge in registry_api.get_dependencies(self.config, unit.unit_id) + registry_api.get_dependents(self.config, unit.unit_id):
                    neighbor_id = edge.target if edge.source == unit.unit_id else edge.source
                    neighbor = registry_api.get_development_unit(self.config, neighbor_id)
                    if neighbor and neighbor.unit_id not in seen:
                        seen.add(neighbor.unit_id); units.append(neighbor); next_frontier.append(neighbor)
            frontier = next_frontier
        candidates, files, symbols, rules, dependencies, unknowns = [], [], [], [], [], []
        searched_files = 0
        # Reserve a small, per-unit share of the file budget for direct semantic
        # definitions.  Broad lexical matches elsewhere must not hide a controller,
        # router root, contract implementation, or widget composition anchor.
        reserved_anchors = {}
        for unit in units:
            probe_symbols = self.searcher.search_symbols(unit, term_list, 1)
            probe_calls = self.searcher.search_callsites(unit, term_list, 1)
            hits = self.searcher.semantic_anchors(unit, 4, term_list) if (probe_symbols or probe_calls or set(term_list) & SEMANTIC_QUERY_TERMS) else []
            reserved_anchors[unit.unit_id] = hits
            for path, line, term, kind in hits:
                if len(files) >= limits.max_files: break
                if str(path) in {item.absolute_path for item in files}: continue
                symbols.append(ContextSymbol(name=term, kind=kind, file=str(path), line=line, evidence_refs=[f"{path.relative_to(self.config.workspace_root)}:{line}"]))
                files.append(ContextFile(absolute_path=str(path), relative_path=str(path.relative_to(self.config.workspace_root)), repo_id=unit.repo_id, unit_id=unit.unit_id, relevance=kind, evidence_refs=[f"{path.relative_to(self.config.workspace_root)}:{line}"]))
        for unit in units:
            deps = registry_api.get_dependencies(self.config, unit.unit_id) + registry_api.get_dependents(self.config, unit.unit_id)
            symbol_hits = self.searcher.search_symbols(unit, term_list, limits.max_symbols - len(symbols))
            call_hits = self.searcher.search_callsites(unit, term_list, limits.max_symbols - len(symbols))
            anchor_hits = reserved_anchors[unit.unit_id]
            name_only = not symbol_hits and not call_hits and not deps
            unit_rules = self.rules.resolve_rules_for_path(unit.unit_id)
            classification = "required" if symbol_hits or call_hits else "context_only" if deps else "unknown"
            confidence = self.scorer.score(dependency_count=len(deps), symbol_count=len(symbol_hits), callsite_count=len(call_hits), rule_count=len(unit_rules), file_count=len(symbol_hits)+len(call_hits), name_only=name_only, unknown=classification == "unknown")
            refs = [f"{path.relative_to(self.config.workspace_root)}:{line}" for path, line, _, _ in symbol_hits + call_hits]
            candidates.append(ContextCandidate(id=unit.unit_id, classification=classification, confidence=confidence, reasons=["exact lexical evidence" if refs else "registry dependency evidence" if deps else "no supported evidence"], evidence_refs=refs + [edge.evidence.path for edge in deps]))
            for path, line, term, kind in anchor_hits + symbol_hits + call_hits:
                if len(symbols) < limits.max_symbols: symbols.append(ContextSymbol(name=term, kind=kind, file=str(path), line=line, evidence_refs=[f"{path.relative_to(self.config.workspace_root)}:{line}"]))
                if len(files) < limits.max_files and str(path) not in {item.absolute_path for item in files}:
                    repo = registry_api.get_repository(self.config, unit.repo_id); files.append(ContextFile(absolute_path=str(path), relative_path=str(path.relative_to(self.config.workspace_root)), repo_id=unit.repo_id, unit_id=unit.unit_id, relevance=kind, evidence_refs=[f"{path.relative_to(self.config.workspace_root)}:{line}"]))
            for manifest in unit.manifests:
                manifest_path = self.config.workspace_root / manifest
                if len(files) < limits.max_files and any(term in manifest.lower() for term in term_list) and str(manifest_path) not in {item.absolute_path for item in files}:
                    files.append(ContextFile(absolute_path=str(manifest_path), relative_path=manifest, repo_id=unit.repo_id, unit_id=unit.unit_id, relevance="file_path_match", evidence_refs=[manifest]))
            rules.extend(unit_rules); dependencies.extend(deps)
            if classification == "unknown": unknowns.append(ContextUnknown(subject=unit.unit_id, reason="No exact symbol, callsite, or registry dependency evidence matched the requirement.", required_evidence="Exact source/import/callsite or manifest dependency evidence."))
            searched_files += len(unit.manifests)
        candidates = sorted(candidates, key=lambda item: ({"required": 0, "context_only": 1, "unknown": 2}[item.classification], {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "BLOCKED": 3}[item.confidence]))
        candidates = candidates[:limits.max_candidate_repositories * 10]
        unique_deps = {f"{edge.source}>{edge.target}>{edge.kind}": edge for edge in dependencies}
        unique_rules = {f"{rule.path}:{rule.applies_to}": rule for rule in rules}
        unique_symbols = {(item.file, item.line, item.name, item.kind): item for item in symbols}
        package = ContextPackage(request={"requirement": requirement, "optional_target_repository": target_repository}, scope={"repositories": sorted({registry_api.get_development_unit(self.config, unit.unit_id).repo_id for unit in units}), "development_units": [unit.unit_id for unit in units]}, candidates=candidates, files=files[:limits.max_files], symbols=list(unique_symbols.values())[:limits.max_symbols], rules=list(unique_rules.values()), dependencies=list(unique_deps.values()), unknowns=unknowns, confidence="HIGH" if any(item.confidence == "HIGH" for item in candidates) else "MEDIUM" if any(item.confidence == "MEDIUM" for item in candidates) else "LOW", metrics={"searched_repositories": len(selected_repos), "searched_files": searched_files, "selected_files": len(files[:limits.max_files]), "evidence_count": len(unique_symbols)+len(unique_deps), "context_size_estimate": len(files)+len(unique_symbols)+len(unique_deps)+len(unique_rules)})
        return package
    def validate_context_package(self, package: ContextPackage) -> list[str]:
        errors=[]
        for file in package.files:
            if not is_allowed_business_path(Path(file.absolute_path), self.config): errors.append(f"out-of-bound file: {file.absolute_path}")
        for dependency in package.dependencies:
            if not dependency.evidence.path: errors.append(f"dependency lacks evidence: {dependency.source}")
        return errors
