import tempfile
import unittest
from pathlib import Path
from atlas_core.adapters.model import ModelResult
from atlas_core.controller import AtlasController
from atlas_core.finalizer import render_run_text

class FailSecond:
    def __init__(self): self.n=0
    def execute(self, **kwargs):
        self.n+=1
        if self.n==2: raise RuntimeError('provider unavailable')
        return ModelResult(output='incomplete ' * 50,provider='test',model='fixture')

class TerminalRegressions(unittest.TestCase):
    def test_missing_sources_not_repaired_by_formatting_retry(self):
        run=AtlasController(max_iterations=1).run('granska repo och hitta P0 P1 P2',json_mode=True)
        self.assertEqual(run['stop_reason'],'insufficient_evidence')
        self.assertEqual(run['iteration'],1)
    def test_failure_does_not_promote_previous_grade_to_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            run=AtlasController(max_iterations=2,model_adapter=FailSecond(),memory_dir=tmp).run('hej',json_mode=True)
            self.assertEqual(run['stop_reason'],'tool_error')
            self.assertEqual(len(run['evaluations']),1)
            self.assertEqual(run['memory_candidates'],[])
            self.assertEqual(list(Path(tmp).iterdir()),[])
            text=render_run_text(run)
            self.assertIn('failed iteration was not graded',text)
            self.assertNotIn('Nothing was graded',text)
