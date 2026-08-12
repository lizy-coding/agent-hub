import unittest
from agent_hub.capability.analyzer import CapabilityAnalyzer
from agent_hub.schemas.models import CouplingProfile

class CalibrationFixturesTest(unittest.TestCase):
 def test_generic_ownership_order(self):
  analyzer=object.__new__(CapabilityAnalyzer)
  self.assertEqual(analyzer.classify_ownership('class ParseThing {}',CouplingProfile()),'shared_core')
  self.assertEqual(analyzer.classify_ownership('class View extends StatelessWidget {}',CouplingProfile(ui='HIGH'),False),'ui_only')
  self.assertEqual(analyzer.classify_ownership('class Surface extends StatelessWidget {}',CouplingProfile(ui='HIGH'),True),'ui_only')
  self.assertEqual(analyzer.classify_ownership('class Native { MethodChannel c; }',CouplingProfile(platform='HIGH')),'platform_plugin')
  self.assertEqual(analyzer.classify_ownership('class BridgeController { final Service s; }',CouplingProfile()),'adapter')
  self.assertEqual(analyzer.classify_ownership('GoRouter router; class C {}',CouplingProfile()),'application_orchestration')
 def test_cmake_name_only_stays_unknown(self):
  analyzer=object.__new__(CapabilityAnalyzer)
  self.assertEqual(analyzer.classify_ownership('cmake_minimum_required(VERSION 3.0)',CouplingProfile()),'unknown')
 def test_generic_adapter_router_and_reusable_contracts(self):
  analyzer=object.__new__(CapabilityAnalyzer)
  self.assertEqual(analyzer.classify_ownership('class SessionController { final SessionService service; State state; }',CouplingProfile()),'adapter')
  self.assertEqual(analyzer.classify_ownership('final GoRouter root = GoRouter(routes: table);',CouplingProfile()),'application_orchestration')
  self.assertEqual(analyzer.classify_ownership('class TeachingSurface extends StatelessWidget { final Widget content; final VoidCallback? callback; Widget build() => Scaffold(body: content); }',CouplingProfile(ui='HIGH'),True),'reusable_capability')
  self.assertEqual(analyzer.classify_ownership('class PaintedLeaf extends StatelessWidget {}',CouplingProfile(ui='HIGH'),True),'ui_only')
