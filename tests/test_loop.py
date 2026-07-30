import unittest
from atlas_core.controller import AtlasController

class TestLoop(unittest.TestCase):
    def test_loop_runs(self):
        c = AtlasController(max_iterations=2)
        result = c.run("jämför tre alternativ och rekommendera väg")
        self.assertTrue("Recommendation" in result or "recommendation" in result.lower())
        self.assertIn("Atlas route:", result)

    def test_write_requires_approval(self):
        c = AtlasController(max_iterations=2)
        result = c.run("skapa issue och pusha ändringen")
        self.assertIn("Write approval required", result)

if __name__ == "__main__":
    unittest.main()
