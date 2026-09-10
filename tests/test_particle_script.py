import unittest
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "baseparticle"
    / "loopaerosolDynamics.sh"
)
KINEMATIC_PARCEL = (
    Path(__file__).resolve().parents[1]
    / "vendor"
    / "aerosolDynamicsFoam"
    / "lagrangian"
    / "intermediate"
    / "parcels"
    / "Templates"
    / "KinematicParcel"
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

    def test_wedge_drift_uses_symmetry_reflection(self):
        header = (KINEMATIC_PARCEL / "KinematicParcel.H").read_text()
        source = (KINEMATIC_PARCEL / "KinematicParcel.C").read_text()
        self.assertIn("void hitWedgePatch", header)
        self.assertIn(
            "KinematicParcel<ParcelType>::hitWedgePatch",
            source,
        )
        self.assertIn("transformProperties(I - 2.0*nf*nf);", source)
        self.assertIn("if (isA<wedgePolyPatch>(pp))", source)
        self.assertIn("p.transformProperties(I - 2.0*nf*nf);", source)
