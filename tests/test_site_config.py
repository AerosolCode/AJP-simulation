import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.site_config import load_site_env


ROOT = Path(__file__).resolve().parents[1]


class SiteConfigTests(unittest.TestCase):
    def test_user_paths_expand_and_explicit_environment_takes_priority(self):
        with tempfile.TemporaryDirectory() as temporary:
            site = Path(temporary) / "site.env"
            site.write_text(
                '# Student settings\n'
                'export AJP_PYTHON_BIN="$HOME/my env/bin/python" # quoted path\n'
                'AJP_OPENFOAM_BASHRC="$HOME/OpenFOAM/etc/bashrc"\n'
                'export AJP_SLURM_NODELIST=xeon4\n'
                'export AJP_PARTICLE_SOLVER=\n'
            )
            with mock.patch.dict(
                os.environ,
                {"HOME": "/home/student", "AJP_SLURM_NODELIST": "xeon5"},
                clear=True,
            ):
                load_site_env(site)
                self.assertEqual(
                    os.environ["AJP_PYTHON_BIN"], "/home/student/my env/bin/python"
                )
                self.assertEqual(
                    os.environ["AJP_OPENFOAM_BASHRC"],
                    "/home/student/OpenFOAM/etc/bashrc",
                )
                self.assertEqual(os.environ["AJP_SLURM_NODELIST"], "xeon5")
                self.assertEqual(os.environ["AJP_PARTICLE_SOLVER"], "")

    def test_missing_site_file_is_allowed_for_offline_work(self):
        with tempfile.TemporaryDirectory() as temporary:
            with mock.patch.dict(os.environ, {"HOME": temporary}, clear=True):
                load_site_env(Path(temporary) / "missing.env")

    def test_local_settings_are_ignored_by_git(self):
        self.assertIn("site.env", (ROOT / ".gitignore").read_text().splitlines())
        template = (ROOT / "site.env.example").read_text()
        for name in (
            "AJP_PYTHON_BIN",
            "AJP_OPENFOAM_BASHRC",
            "AJP_PARTICLE_SOLVER",
            "AJP_SLURM_NODELIST",
            "AJP_WORKER_ENV",
        ):
            self.assertIn(name, template)


if __name__ == "__main__":
    unittest.main()
