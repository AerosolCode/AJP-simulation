import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ActiveConfigTests(unittest.TestCase):
    def test_active_campaign_is_fresh_structured_finite_radius_run(self):
        bo = json.loads((ROOT / "bo_config.json").read_text())
        dispatch = json.loads((ROOT / "bo_multihost_config.json").read_text())

        version = bo["objective"]["version"]
        campaign = dispatch["campaign"]
        self.assertIn("structured", version)
        self.assertIn("finite_radius", version)
        self.assertIn("structured", campaign)
        self.assertIn("finite_radius", campaign)
        self.assertEqual(dispatch["loop"]["stop"]["baseline_observations"], 0)
        self.assertEqual(dispatch["workdir"], f"campaigns/{campaign}")
        self.assertNotIn("remote_root", dispatch)
        for host in dispatch["hosts"]:
            self.assertIn("worker_root", host)
            if host["mode"] == "ssh":
                self.assertIn("ssh_user", host)

        for script_name in ("start_bo_multihost.sh", "stop_bo_multihost.sh"):
            script = (ROOT / "tools" / script_name).read_text()
            self.assertNotIn("mobo_target10um_v1", script)
            self.assertIn("config_workdir", script)

    def test_legacy_manual_pipeline_is_not_in_active_tree(self):
        active_legacy_paths = (
            "paramSet.py",
            "paramRun.py",
            "selectrun.sh",
            "particlerunall.sh",
            "delete.sh",
            "export.sh",
            "base/meshGen.py",
            "base/restartrun.sh",
            "baseparticle/loopparticle.sh",
            "baseparticle/particlerun.sh",
            "tools/analyze_cfd_failures.py",
            "tools/plot_cfd_failure_analysis.py",
            "tools/run_cfd_diagnostic_variant.sh",
            "tools/rescore_bo_campaign.py",
        )
        for relative_path in active_legacy_paths:
            self.assertFalse((ROOT / relative_path).exists(), relative_path)

        archive = ROOT / "archive" / "legacy_manual_pipeline_202607"
        self.assertTrue((archive / "README.md").is_file())
        self.assertTrue((archive / "root" / "paramSet.py").is_file())
        self.assertTrue((archive / "base" / "meshGen.py").is_file())
        self.assertTrue((archive / "baseparticle" / "loopparticle.sh").is_file())


if __name__ == "__main__":
    unittest.main()
