import importlib.util
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "bo_multihost.py"
SPEC = importlib.util.spec_from_file_location("bo_multihost", SCRIPT)
bo_multihost = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bo_multihost)


class MultiHostAssignmentTest(unittest.TestCase):
    def setUp(self):
        self.config = {
            "hosts": [
                {"name": "xeon6", "mode": "local", "slots": 2},
                {"name": "xeon1", "mode": "ssh", "slots": 2},
                {"name": "xeon4", "mode": "ssh", "slots": 2},
                {"name": "xeon5", "mode": "ssh", "slots": 2},
            ]
        }

    def test_empty_state_starts_with_master(self):
        state = {"cases": {}}
        selected = bo_multihost.choose_host(self.config, state)
        self.assertEqual(selected["name"], "xeon6")

    def test_assignment_uses_all_four_hosts(self):
        state = {
            "cases": {
                "case_0000": {"host": "xeon6", "stage": "cfd_submitted"},
                "case_0001": {"host": "xeon1", "stage": "cfd_submitted"},
                "case_0002": {"host": "xeon4", "stage": "cfd_submitted"},
            }
        }
        selected = bo_multihost.choose_host(self.config, state)
        self.assertEqual(selected["name"], "xeon5")

    def test_full_hosts_return_none(self):
        cases = {}
        index = 0
        for host in self.config["hosts"]:
            for _ in range(host["slots"]):
                cases["case_%04d" % index] = {
                    "host": host["name"],
                    "stage": "particle_submitted",
                }
                index += 1
        selected = bo_multihost.choose_host(self.config, {"cases": cases})
        self.assertIsNone(selected)

    def test_local_particle_markers_are_cleared_before_resubmit(self):
        with tempfile.TemporaryDirectory() as temporary:
            particle_dir = Path(temporary) / "case_0004" / "baseparticle"
            particle_dir.mkdir(parents=True)
            (particle_dir / "PARTICLE_DONE").touch()
            (particle_dir / "PARTICLE_FAILED").touch()
            dispatch_config = {}
            host = {"name": "xeon6", "mode": "local"}
            bo_multihost.clear_particle_completion_markers(
                dispatch_config,
                host,
                temporary,
                "case_0004",
            )
            self.assertFalse((particle_dir / "PARTICLE_DONE").exists())
            self.assertFalse((particle_dir / "PARTICLE_FAILED").exists())

    def test_submit_injects_the_selected_hosts_worker_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            dispatch_config = {
                "campaign": "portable_test",
                "cfd_env": {"AJP_CFD_MAX_U_MAG": "10000"},
            }
            host = {
                "name": "xeon6",
                "mode": "local",
                "worker_root": "/srv/xeon6-user/AJP-worker",
            }
            result = mock.Mock(returncode=0, stdout="12345\n", stderr="")
            with mock.patch.object(
                bo_multihost,
                "run_command",
                return_value=result,
            ) as run_command:
                job_id = bo_multihost.submit_job(
                    dispatch_config,
                    host,
                    temporary,
                    "case_0001",
                    "cfd",
                )

            command = run_command.call_args.args[0]
            exported = command[command.index("--export") + 1]
            self.assertEqual(job_id, "12345")
            self.assertIn("AJP_WORKER_ROOT=/srv/xeon6-user/AJP-worker", exported)
            self.assertIn(
                "AJP_WORKER_ENV=/srv/xeon6-user/AJP-worker/worker-env.sh",
                exported,
            )

    def test_stop_progress_enforces_new_observation_budget(self):
        config = {
            "loop": {
                "stop": {
                    "baseline_observations": 2,
                    "max_new_observations": 3,
                    "min_new_observations": 2,
                    "patience": 2,
                    "min_improvement": 0.01,
                }
            }
        }
        observations = [
            {"score": "0.1"},
            {"score": "0.2"},
            {"score": "0.21"},
            {"score": "0.20"},
            {"score": "0.19"},
        ]

        progress = bo_multihost.stop_progress(config, observations)

        self.assertEqual(progress["new_observations"], 3)
        self.assertEqual(progress["remaining_budget"], 0)
        self.assertEqual(progress["reason"], "max_new_observations")

    def test_stop_progress_detects_stagnation_after_minimum(self):
        config = {
            "loop": {
                "stop": {
                    "baseline_observations": 1,
                    "max_new_observations": 10,
                    "min_new_observations": 3,
                    "patience": 3,
                    "min_improvement": 0.01,
                }
            }
        }
        observations = [
            {"score": "0.5"},
            {"score": "0.505"},
            {"score": "0.49"},
            {"score": "0.48"},
        ]

        progress = bo_multihost.stop_progress(config, observations)

        self.assertEqual(progress["no_improvement_count"], 3)
        self.assertEqual(progress["remaining_budget"], 7)
        self.assertEqual(progress["reason"], "stagnation")

    def test_loop_command_reads_run_once_stop_result(self):
        dispatch_config = {"loop": {"sleep_seconds": 0}}
        lock = io.StringIO()
        with (
            mock.patch.object(
                bo_multihost,
                "load_dispatch_config",
                return_value=dispatch_config,
            ),
            mock.patch.object(
                bo_multihost,
                "load_bo_context",
                return_value=(
                    {"objective": {"version": "test"}},
                    Path("/tmp/work"),
                    Path("/tmp/base"),
                    Path("/tmp/particle"),
                ),
            ),
            mock.patch.object(bo_multihost, "acquire_lock", return_value=lock),
            mock.patch.object(bo_multihost, "load_state", return_value={}),
            mock.patch.object(bo_multihost, "run_once", return_value=False) as run_once,
        ):
            bo_multihost.main(["--config", "unused", "loop", "--iterations", "1"])

        run_once.assert_called_once()

    def test_prepare_only_initialization_does_not_dispatch(self):
        with tempfile.TemporaryDirectory() as temporary:
            workdir = Path(temporary) / "campaign"
            bo_config = {"objective": {"version": "fresh_test"}}
            dispatch_config = {"bo_config": "bo_config.json"}
            state = {"cases": {}}
            with (
                mock.patch.object(
                    bo_multihost,
                    "load_bo_context",
                    return_value=(
                        bo_config,
                        workdir,
                        Path("/tmp/base"),
                        Path("/tmp/particle"),
                    ),
                ),
                mock.patch.object(bo_multihost.bo_loop, "init_workdir"),
                mock.patch.object(bo_multihost.bo_loop, "suggest"),
                mock.patch.object(bo_multihost, "load_state", return_value=state),
                mock.patch.object(bo_multihost, "dispatch_candidates") as dispatch,
                mock.patch.object(bo_multihost, "save_state") as save,
            ):
                bo_multihost.initialize(
                    dispatch_config,
                    initial_batch=32,
                    submit_jobs=False,
                )

            dispatch.assert_not_called()
            save.assert_called_once_with(workdir, state)


if __name__ == "__main__":
    unittest.main()
