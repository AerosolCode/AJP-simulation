import unittest
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "baseparticle"
    / "loopaerosolDynamics.sh"
)


class ParticleScriptTest(unittest.TestCase):
    def test_wedge_is_preserved_and_checked(self):
        content = SCRIPT.read_text()
        self.assertNotIn(
            "s/type[[:space:]]*wedge/type            symmetry/g",
            content,
        )
        self.assertIn(
            "Mesh has 2 geometric (non-empty/wedge) directions",
            content,
        )

    def test_carrier_velocity_uses_continuous_interpolation(self):
        properties = (
            SCRIPT.parent / "constant" / "kinematicCloudProperties"
        ).read_text()
        self.assertIn("U               cellPoint;", properties)
        self.assertNotIn("U               cell;", properties)

    def test_finite_radius_wall_capture_remains_enabled(self):
        properties = (SCRIPT.parent / "constant/kinematicCloudProperties").read_text()
        self.assertRegex(properties, r"type\s+finiteRadiusDeposition;")
        self.assertRegex(properties, r"radiusFactor\s+0\.5;")
        self.assertRegex(properties, r"action\s+remove;")
        self.assertIn("(wallSubstrate wallUpper wallDown wallCavity)", properties)
        control = (SCRIPT.parent / "system/controlDict").read_text()
        self.assertIn("$FOAM_CASE/custom/finiteRadiusDeposition/lib/libfiniteRadiusDeposition.so", control)
