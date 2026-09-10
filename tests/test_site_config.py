import importlib.util
import os
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "bo_multihost.py"
SPEC = importlib.util.spec_from_file_location("portable_bo_multihost", SCRIPT)
bo_multihost = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bo_multihost)


class SiteConfigTests(unittest.TestCase):
    def test_user_environment_expands_remote_paths_and_ssh_targets(self):
        environment = {
            "AJP_SITE_ENV": "/path/that/does/not/exist",
            "AJP_MASTER_PYTHON": "python3",
            "AJP_SSH_USER_XEON1": "student-x1",
            "AJP_SSH_USER_XEON4": "student-x4",
            "AJP_SSH_USER_XEON5": "student-x5",
            "AJP_WORKER_ROOT_XEON6": "/srv/x6/AJP-worker",
            "AJP_WORKER_ROOT_XEON1": "/srv/x1/AJP-worker",
            "AJP_WORKER_ROOT_XEON4": "/srv/x4/AJP-worker",
            "AJP_WORKER_ROOT_XEON5": "/srv/x5/AJP-worker",
        }
        with mock.patch.dict(os.environ, environment, clear=False):
            config = bo_multihost.load_dispatch_config(
                ROOT / "bo_multihost_config.json"
            )

        hosts = {host["name"]: host for host in config["hosts"]}
        self.assertEqual(hosts["xeon6"]["worker_root"], "/srv/x6/AJP-worker")
        remote_hosts = [host for host in config["hosts"] if host["mode"] == "ssh"]
        self.assertEqual(
            [host["ssh_target"] for host in remote_hosts],
            [
                "student-x1@133.28.174.91",
                "student-x4@133.28.174.94",
                "student-x5@133.28.126.54",
            ],
        )
        self.assertEqual(
            hosts["xeon4"]["campaign_root"],
            "/srv/x4/AJP-worker/campaigns/%s" % config["campaign"],
        )

    def test_site_template_is_tracked_while_local_file_is_ignored(self):
        template = (ROOT / "site.env.example").read_text()
        ignore = (ROOT / ".gitignore").read_text().splitlines()
        for name in (
            "AJP_MASTER_PYTHON",
            "AJP_SSH_USER_XEON1",
            "AJP_SSH_USER_XEON4",
            "AJP_SSH_USER_XEON5",
            "AJP_WORKER_ROOT_XEON6",
            "AJP_WORKER_ROOT_XEON1",
            "AJP_WORKER_ROOT_XEON4",
            "AJP_WORKER_ROOT_XEON5",
        ):
            self.assertIn(name, template)
        self.assertIn("site.env", ignore)

    def test_active_sources_do_not_fix_an_operator_home_directory(self):
        forbidden = (
            "/home/" + "tamadate",
            "/home/" + "tama4thgen",
        )
        skipped_directories = {".git", "archive", "campaigns", "test_cases", "vendor"}
        text_suffixes = {".json", ".md", ".py", ".sh", ".tex"}

        for path in ROOT.rglob("*"):
            if not path.is_file() or path.name == "site.env":
                continue
            if skipped_directories.intersection(path.relative_to(ROOT).parts):
                continue
            if path.suffix not in text_suffixes and path.name != ".gitignore":
                continue
            content = path.read_text(errors="replace")
            for value in forbidden:
                self.assertNotIn(value, content, str(path.relative_to(ROOT)))


if __name__ == "__main__":
    unittest.main()
