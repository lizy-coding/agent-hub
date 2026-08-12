"""Evidence-driven ownership, coupling, overlap, and extraction assessment."""
import re
from pathlib import Path
from agent_hub.context.resolver import ContextResolver
from agent_hub.projects import api as registry_api
from agent_hub.schemas.models import CapabilityAnalysis, CapabilityNode, ContextPackage, CouplingProfile, ExtractionAssessment, WorkspaceCapabilityMatch
from agent_hub.tools.path_guard import is_allowed_business_path
from agent_hub.workspace.config import WorkspaceConfig

class CapabilityAnalyzer:
    def __init__(self, config: WorkspaceConfig): self.config=config; self.resolver=ContextResolver(config)
    def _text(self, context: ContextPackage) -> dict[str,str]:
        result={}
        for item in context.files:
            path=Path(item.absolute_path)
            if is_allowed_business_path(path,self.config):
                try: result[item.absolute_path]=path.read_text(encoding='utf-8')[:12000]
                except (OSError,UnicodeDecodeError): pass
        return result
    def analyze_coupling(self, text: str) -> CouplingProfile:
        low=text.lower()
        return CouplingProfile(ui="HIGH" if any(x in low for x in ('widget','build(','custompaint')) else "NONE", application_state="HIGH" if any(x in low for x in ('provider','riverpod','bloc','navigator','router','controller')) else "LOW" if 'state' in low else "NONE", platform="HIGH" if any(x in low for x in ('methodchannel','ffi','platform')) else "NONE", external_contract="MEDIUM" if any(x in low for x in ('abstract class','interface','service')) else "NONE")
    def classify_ownership(self, text: str, coupling: CouplingProfile, public_widget: bool = False) -> str:
        low=text.lower()
        if 'gorouter' in low or 'navigator' in low or ('controller' in low and sum(x in low for x in ('service','pipeline','repository')) >= 2): return 'application_orchestration'
        if 'controller' in low and 'service' in low and ('final ' in low or 'state' in low): return 'adapter'
        if coupling.platform == 'HIGH': return 'platform_plugin'
        # Export visibility proves consumption, not destination ownership. Rendering
        # surfaces remain UI-only unless a separate non-render contract is evidenced.
        if coupling.ui == 'HIGH':
            # Rendering alone is UI-only; a public scaffold-like contract with
            # non-render responsibility is a reusable capability.
            # A local `Widget content` inside build is rendering detail.  A
            # constructor/field-level Widget or section slot is a caller-facing
            # composition contract and can support reuse when publicly exported.
            composition = bool(re.search(r'final\s+(?:list<\s*widget\s*>|widget\??|voidcallback\??)', low))
            # A scaffold/root composition is a stronger reusable contract than a
            # visual leaf.  Treating a leaf canvas with optional visual settings
            # as reusable would turn its mere public export into a destination
            # decision, which remains intentionally unsupported.
            composition = composition and any(x in low for x in ('scaffold(', 'appbar:', 'floatingactionbutton', 'sections'))
            return 'reusable_capability' if public_widget and composition else 'ui_only'
        if any(x in low for x in ('parser','parse','algorithm','model','transform')) and coupling.ui in ('NONE','UNKNOWN'): return 'shared_core'
        return 'unknown'
    def _is_public_export(self, unit_id: str, source_path: str) -> bool:
        unit=registry_api.get_development_unit(self.config,unit_id); repo=registry_api.get_repository(self.config,unit.repo_id) if unit else None
        if not unit or not repo: return False
        source=Path(source_path).resolve()
        for entry in (repo.path/unit.relative_path/'lib').glob('*.dart'):
            exported=self._text_file(entry)
            # A unit-level barrel is not proof that every source file is public.
            # Match the actual exported source name to keep visibility evidence
            # specific and traceable.
            if source.name and re.search(rf"export\s+['\"][^'\"]*{re.escape(source.name)}['\"]", exported): return True
        return False
    def _text_file(self,path:Path)->str:
        try: return path.read_text(encoding='utf-8')[:12000] if is_allowed_business_path(path,self.config) else ''
        except (OSError,UnicodeDecodeError): return ''
    def match_workspace_capabilities(self, node: CapabilityNode, context: ContextPackage):
        matches=[]
        unit_id=node.development_units[0]
        unit=registry_api.get_development_unit(self.config,unit_id)
        # A public contract in a registered unit plus an incoming manifest path edge
        # is a strong existing-unit match, including workspace-member packages.
        incoming=[edge for repo in registry_api.list_repositories(self.config) for edge in registry_api.get_dependencies(self.config,repo.repo_id) if edge.target==unit_id]
        if unit and self._is_public_export(unit_id,node.files[0]) and incoming:
            edge=incoming[0]
            matches.append(WorkspaceCapabilityMatch(source_capability_id=node.capability_id,target_repo=unit.repo_id,target_unit=unit_id,match_type='existing_unit_strong_match',matched_contracts=node.files,matched_symbols=node.symbols,evidence_refs=[edge.evidence.path]+node.evidence_refs,confidence='HIGH'))
        for edge in node.dependencies:
            target=registry_api.get_development_unit(self.config, edge.target)
            if target and target.repo_id != node.target_repo:
                matches.append(WorkspaceCapabilityMatch(source_capability_id=node.capability_id,target_repo=target.repo_id,target_unit=target.unit_id,match_type='existing_unit_strong_match',matched_contracts=[],matched_symbols=[],evidence_refs=[edge.evidence.path],confidence='HIGH'))
            elif target:
                matches.append(WorkspaceCapabilityMatch(source_capability_id=node.capability_id,target_repo=target.repo_id,target_unit=target.unit_id,match_type='existing_unit_partial_overlap',matched_contracts=[],matched_symbols=[],evidence_refs=[edge.evidence.path],confidence='MEDIUM'))
        return matches
    def assess_extraction(self,node:CapabilityNode,matches):
        strong=next((m for m in matches if m.match_type=='existing_unit_strong_match'),None)
        if node.ownership=='application_orchestration': decision='KEEP_IN_APPLICATION'; target=None
        elif node.ownership=='adapter': decision='ADAPTER_ONLY'; target=None
        elif node.ownership=='unknown': decision='NOT_ENOUGH_EVIDENCE'; target=None
        elif node.ownership=='ui_only': decision='UNKNOWN'; target=None
        elif strong: decision='EXTEND_EXISTING_UNIT' if node.ownership=='reusable_capability' else 'MOVE_TO_EXISTING_UNIT'; target=strong
        elif node.ownership=='shared_core' and node.coupling.ui in ('NONE','LOW') and node.coupling.application_state in ('NONE','LOW'): decision='NEW_SHARED_CORE_CANDIDATE'; target=None
        elif node.ownership=='platform_plugin': decision='NEW_PLUGIN_CANDIDATE'; target=None
        else: decision='NOT_ENOUGH_EVIDENCE'; target=None
        return ExtractionAssessment(capability_id=node.capability_id,decision=decision,target_repo=target.target_repo if target else None,target_unit=target.target_unit if target else None,reasons=[f'ownership={node.ownership}'],blockers=node.unknowns,evidence_refs=node.evidence_refs,confidence=node.confidence)
    def analyze_capabilities(self, requirement:str, target_repository:str) -> CapabilityAnalysis:
        context=self.resolver.resolve_context(requirement,target_repository)
        nodes=[]
        # Seed one bounded capability per source-evidence file rather than per unit.
        for file in context.files:
            unit=registry_api.get_development_unit(self.config,file.unit_id)
            if not unit: continue
            unit_text=self._text_file(Path(file.absolute_path))
            if not unit_text: continue
            symbols=[s.name for s in context.symbols if s.file==file.absolute_path]
            coupling=self.analyze_coupling(unit_text); ownership=self.classify_ownership(unit_text,coupling,self._is_public_export(file.unit_id,file.absolute_path))
            unknowns=[] if ownership!='unknown' else ['Insufficient bounded source evidence for ownership.']
            deps=registry_api.get_dependencies(self.config,file.unit_id)+registry_api.get_dependents(self.config,file.unit_id)
            refs=list(dict.fromkeys(file.evidence_refs+[d.evidence.path for d in deps]))
            confidence='HIGH' if refs and ownership!='unknown' else 'MEDIUM' if refs else 'LOW'
            nodes.append(CapabilityNode(capability_id=f'capability:{file.unit_id}:{Path(file.absolute_path).name}',label='evidence_anchor',target_repo=target_repository,development_units=[file.unit_id],files=[file.relative_path],symbols=symbols,responsibilities=['source evidence anchor'],ownership=ownership,coupling=coupling,dependencies=deps,evidence_refs=refs,confidence=confidence,unknowns=unknowns))
        matches=[m for n in nodes for m in self.match_workspace_capabilities(n,context)]
        assessments=[self.assess_extraction(n,[m for m in matches if m.source_capability_id==n.capability_id]) for n in nodes]
        unknowns=list(context.unknowns[i].reason for i in range(len(context.unknowns)))+[u for n in nodes for u in n.unknowns]
        return CapabilityAnalysis(requirement=requirement,target_repository=target_repository,context_ref={'confidence':context.confidence,'metrics':context.metrics},capabilities=nodes,workspace_matches=matches,extraction_assessments=assessments,keep_in_application=[a.capability_id for a in assessments if a.decision=='KEEP_IN_APPLICATION'],extraction_candidates=[a.capability_id for a in assessments if a.decision not in ('KEEP_IN_APPLICATION','NOT_ENOUGH_EVIDENCE')],unknowns=unknowns,evidence_summary={'context_evidence':context.metrics.get('evidence_count',0),'capability_nodes':len(nodes)},metrics={'bounded_files_read':len(nodes),'capabilities':len(nodes),'matches':len(matches)})
    def explain_capability(self, node:CapabilityNode): return node.model_dump()
    def validate_capability_analysis(self, analysis:CapabilityAnalysis):
        errors=[]
        for node in analysis.capabilities:
            if not node.evidence_refs: errors.append(f'missing evidence: {node.capability_id}')
            if node.confidence=='HIGH' and node.ownership=='unknown': errors.append(f'untraceable high ownership: {node.capability_id}')
        return errors
