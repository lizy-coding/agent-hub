import unittest
from pathlib import Path

from agent_hub.capability.analyzer import CapabilityAnalyzer
from agent_hub.workspace.config import WorkspaceConfig


class CapabilityAnalyzerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.analyzer = CapabilityAnalyzer(WorkspaceConfig.from_file(Path(__file__).parents[1] / 'workspace/config.json'))

    def test_context_consumption_evidence_and_unknowns(self):
        analysis = self.analyzer.analyze_capabilities('GCode import callsite and plugin adapter', 'flutter_forge')
        self.assertTrue(analysis.capabilities)
        self.assertTrue(analysis.unknowns)
        self.assertTrue(all(node.evidence_refs for node in analysis.capabilities))
        self.assertEqual(self.analyzer.validate_capability_analysis(analysis), [])

    def test_ownership_coupling_and_structured_extraction(self):
        coupling = self.analyzer.analyze_coupling('Riverpod controller Navigator Widget')
        self.assertEqual(self.analyzer.classify_ownership('Riverpod controller Navigator Widget', coupling), 'application_orchestration')
        analysis = self.analyzer.analyze_capabilities('riverpod platform controller widget parser', 'flutter_forge')
        self.assertTrue(all(item.decision for item in analysis.extraction_assessments))
        self.assertTrue(all(match.evidence_refs for match in analysis.workspace_matches))


if __name__ == '__main__':
    unittest.main()
