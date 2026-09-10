import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class CfdTemplatePolicyTest(unittest.TestCase):
    def test_structured_mesh_is_the_only_production_generator(self):
        production = (REPO_ROOT / "base" / "meshGen2.py").read_text()
        self.assertIn("Production structured/swept mesh generator", production)
        self.assertFalse((REPO_ROOT / "base" / "meshGen2_structured.py").exists())

        archived = REPO_ROOT / "archive" / "mesh" / "meshGen2_unstructured.py"
        self.assertTrue(archived.is_file())
        self.assertIn("Archived unstructured mesh generator", archived.read_text())

    def test_potential_foam_initialises_flow_rate_boundaries_and_is_required(self):
        run_script = (REPO_ROOT / "base" / "run.sh").read_text()
        self.assertIn("potentialFoam -initialiseUBCs -writep", run_script)
        self.assertNotIn("potentialFoam failed, continuing", run_script)

    def test_simple_foam_has_conservative_residual_control(self):
        solution = (REPO_ROOT / "base" / "system" / "fvSolution").read_text()
        self.assertIn("residualControl", solution)
        self.assertRegex(solution, r"p\s+1e-5;")
        self.assertRegex(solution, r"U\s+1e-4;")
        self.assertRegex(solution, r'"\(k\|epsilon\|omega\)"\s+1e-5;')


if __name__ == "__main__":
    unittest.main()
