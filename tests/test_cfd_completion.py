import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import bo_loop
from baseparticle.cfd_fields import latest_cfd_time


ROOT = Path(__file__).resolve().parents[1]


class CfdCompletionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.case_dir = Path(self.temporary.name)
        (self.case_dir / "CFD_DONE").touch()
        (self.case_dir / "log.simpleFoam").write_text("Time = 250\nEnd\n")

    def add_time(self, name, field="U"):
        time_dir = self.case_dir / name
        time_dir.mkdir()
        if field:
            (time_dir / field).touch()
        return time_dir

    def test_early_converged_times_replace_fixed_end_time(self):
        for name in ("0", "-1", "nan", "inf", "constant"):
            self.add_time(name)
        self.add_time("250")
        self.assertEqual(latest_cfd_time(self.case_dir), "250")
        self.assertTrue(bo_loop.cfd_completed(self.case_dir))
        self.add_time("750")
        self.assertEqual(latest_cfd_time(self.case_dir), "750")
        self.assertTrue(bo_loop.cfd_completed(self.case_dir))

    def test_missing_latest_velocity_does_not_fall_back_to_stale_time(self):
        self.add_time("250")
        self.add_time("750", field=None)
        with self.assertRaisesRegex(ValueError, "latest CFD time has no U"):
            latest_cfd_time(self.case_dir)
        self.assertFalse(bo_loop.cfd_completed(self.case_dir))

    def test_failed_or_unfinished_cfd_is_not_a_particle_input(self):
        self.add_time("250")
        (self.case_dir / "CFD_FAILED").touch()
        with self.assertRaises(ValueError):
            latest_cfd_time(self.case_dir)
        self.assertFalse(bo_loop.cfd_completed(self.case_dir))
        (self.case_dir / "CFD_FAILED").unlink()
        (self.case_dir / "CFD_DONE").unlink()
        with self.assertRaises(ValueError):
            latest_cfd_time(self.case_dir)
        self.assertFalse(bo_loop.cfd_completed(self.case_dir))

    def test_compressed_velocity_is_recognized_by_both_stages(self):
        self.add_time("250", field="U.gz")
        self.assertEqual(latest_cfd_time(self.case_dir), "250")
        self.assertTrue(bo_loop.cfd_completed(self.case_dir))

    def test_missing_inherited_python_marks_stage_failed_without_loading_environment_files(self):
        for script, stage in (
            (ROOT / "base/run.sh", "CFD"),
            (ROOT / "baseparticle/loopaerosolDynamics.sh", "PARTICLE"),
        ):
            with self.subTest(stage=stage):
                case_dir = self.case_dir / stage.lower()
                case_dir.mkdir()
                done = case_dir / (stage + "_DONE")
                failed = case_dir / (stage + "_FAILED")
                done.touch()
                environment = dict(os.environ)
                environment.pop("HOME", None)
                ignored_file = case_dir / "unused-environment.sh"
                ignored_file.write_text("touch sourced-environment\n")
                environment.update({
                    "AJP_PYTHON_BIN": str(case_dir / "missing-python"),
                    "AJP_OPENFOAM_BASHRC": str(ignored_file),
                    "AJP_WORKER_ENV": str(ignored_file),
                })
                result = subprocess.run(
                    ["bash", str(script)], cwd=case_dir, env=environment,
                    capture_output=True, text=True, timeout=5,
                )
                self.assertEqual(result.returncode, 127, result.stdout + result.stderr)
                self.assertIn("required command unavailable", result.stderr)
                self.assertTrue(failed.is_file(), result.stdout + result.stderr)
                self.assertFalse(done.exists(), result.stdout + result.stderr)
                self.assertFalse((case_dir / "sourced-environment").exists())


if __name__ == "__main__":
    unittest.main()
