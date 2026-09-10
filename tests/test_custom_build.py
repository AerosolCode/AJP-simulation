import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CustomBuildTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.particle = self.root / "baseparticle"
        self.particle.mkdir()
        self.script = self.particle / "build_custom.sh"
        shutil.copy2(ROOT / "baseparticle/build_custom.sh", self.script)
        self.source = self.root / "external-solver"
        self.source.mkdir()

    def test_external_source_requires_generated_solver_headers(self):
        result = subprocess.run(
            ["bash", str(self.script), str(self.source)],
            text=True, capture_output=True, timeout=5,
        )
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("Missing solver header", result.stderr)
        self.assertIn("lnInclude", result.stderr)
        self.assertFalse((self.particle / "custom").exists())

    def test_build_uses_external_headers_and_library_but_keeps_plugin_local(self):
        headers = self.source / "lagrangian/intermediate/lnInclude"
        headers.mkdir(parents=True)
        for header in ("basicKinematicCloud.H", "CloudFunctionObject.H", "cloudFunctionObjectTools.H"):
            (headers / header).touch()
        external_lib = self.root / "external-lib"
        external_lib.mkdir()
        (external_lib / "liboneWayIntermediate.so").write_text("external library placeholder\n")
        binaries = self.root / "bin"
        binaries.mkdir()
        (binaries / "wclean").write_text("#!/bin/sh\nexit 0\n")
        (binaries / "wmake").write_text(
            '#!/bin/sh\n'
            'printf "%s\\n" "$AJP_AEROSOL_SOURCE_DIR" "$AJP_AEROSOL_LIBBIN" "$FOAM_USER_LIBBIN" > "$AJP_TEST_BUILD_CAPTURE"\n'
            'printf "fake plugin\\n" > "$FOAM_USER_LIBBIN/libfiniteRadiusDeposition.so"\n'
        )
        for binary in binaries.iterdir():
            binary.chmod(0o755)
        capture = self.root / "build-environment.txt"
        environment = dict(os.environ)
        environment.pop("AJP_AEROSOL_LIBBIN", None)
        environment.update({
            "PATH": str(binaries) + os.pathsep + environment.get("PATH", "/usr/bin:/bin"),
            "FOAM_USER_LIBBIN": str(external_lib),
            "AJP_TEST_BUILD_CAPTURE": str(capture),
        })
        result = subprocess.run(
            ["bash", str(self.script), str(self.source)],
            env=environment, text=True, capture_output=True, timeout=5,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        plugin_lib = self.particle / "custom/finiteRadiusDeposition/lib"
        self.assertEqual(capture.read_text().splitlines(), [str(self.source), str(external_lib), str(plugin_lib)])
        self.assertTrue((plugin_lib / "libfiniteRadiusDeposition.so").is_file())
        self.assertFalse((external_lib / "libfiniteRadiusDeposition.so").exists())


if __name__ == "__main__":
    unittest.main()
