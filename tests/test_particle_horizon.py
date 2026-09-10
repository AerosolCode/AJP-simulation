import importlib.util
import math
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "baseparticle"
    / "particle_horizon.py"
)
SPEC = importlib.util.spec_from_file_location("particle_horizon", SCRIPT)
particle_horizon = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(particle_horizon)


class ParticleHorizonTest(unittest.TestCase):
    def test_low_flow_case_uses_upper_bound(self):
        params = {
            "Rin_mm": 5.873,
            "Qaerosol_lpm": 0.1333,
            "t_mm": 4.0,
            "L0_mm": 5.0,
            "L1_mm": 20.0,
            "L2_mm": 21.5,
            "L4_mm": 29.4,
        }
        horizon, velocity, axial, transit = particle_horizon.estimate_horizon(
            params
        )
        expected_velocity = (
            params["Qaerosol_lpm"]
            * 1.0e-3
            / 60.0
            / (math.pi * (params["Rin_mm"] * 1.0e-3) ** 2)
        )
        self.assertAlmostEqual(velocity, expected_velocity)
        self.assertAlmostEqual(axial, 0.0799)
        self.assertAlmostEqual(transit, axial / velocity)
        self.assertEqual(horizon, 5.0)

    def test_fast_case_uses_lower_bound(self):
        params = {
            "Rin_mm": 1.0,
            "Qaerosol_lpm": 5.0,
            "t_mm": 2.0,
            "L0_mm": 2.0,
            "L1_mm": 2.0,
            "L2_mm": 2.0,
            "L4_mm": 2.0,
        }
        horizon, _, _, _ = particle_horizon.estimate_horizon(params)
        self.assertEqual(horizon, 0.5)

    def test_load_params_ignores_comments(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "params.dat"
            path.write_text("# test\nRin_mm=2.0\nQaerosol_lpm=1.5\n")
            loaded = particle_horizon.load_params(path)
        self.assertEqual(
            loaded,
            {"Rin_mm": 2.0, "Qaerosol_lpm": 1.5},
        )

    def test_invalid_flow_is_rejected(self):
        params = {
            "Rin_mm": 1.0,
            "Qaerosol_lpm": 0.0,
            "t_mm": 1.0,
            "L0_mm": 1.0,
            "L1_mm": 1.0,
            "L2_mm": 1.0,
            "L4_mm": 1.0,
        }
        with self.assertRaises(ValueError):
            particle_horizon.estimate_horizon(params)

    def test_slurm_submit_directory_selects_helper(self):
        loop_script = SCRIPT.parent / "loopaerosolDynamics.sh"
        command = (
            "set -u; "
            'CASE_DIR=${SLURM_SUBMIT_DIR:-$PWD}; '
            'HORIZON_TOOL=${AJP_PARTICLE_HORIZON_TOOL:-$CASE_DIR/particle_horizon.py}; '
            'printf "%s\\n" "$HORIZON_TOOL"'
        )
        environment = dict(os.environ)
        environment["SLURM_SUBMIT_DIR"] = str(loop_script.parent)
        result = subprocess.run(
            ["bash", "-c", command],
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        )
        self.assertEqual(result.stdout.strip(), str(SCRIPT))
