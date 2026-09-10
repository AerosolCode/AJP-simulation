import contextlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import bo_loop


ROOT = Path(__file__).resolve().parents[1]


class ManualWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.workdir = Path(self.temporary.name) / "manual_campaign"
        self.config, _ = bo_loop.load_config(ROOT / "bo_config.json")
        self.config["bo"]["candidate_pool"] = 64
        self.config["objective"]["total_particles"] = 2
        self.config_path = Path(self.temporary.name) / "config.json"
        self.config_path.write_text(json.dumps(self.config))
        self.cli = [
            "--config", str(self.config_path),
            "--workdir", str(self.workdir),
            "--template-root", str(ROOT),
        ]

    def command(self, *arguments):
        with contextlib.redirect_stdout(io.StringIO()):
            return bo_loop.main(self.cli + list(arguments))

    def prepare(self):
        self.command("init", "--initial-batch", "2")
        return bo_loop.read_csv_rows(bo_loop.candidates_path(self.workdir))

    def mark_cfd_done(self, case):
        case_dir = self.workdir / case
        latest = case_dir / "250"
        latest.mkdir()
        for name in ("U", "p", "k", "epsilon", "omega", "nut"):
            (latest / name).write_text("// test field\n")
        (case_dir / "log.simpleFoam").write_text("Time = 250\nEnd\n")
        (case_dir / "CFD_DONE").touch()

    def mark_particles_done(self, case):
        particle_dir = self.workdir / case / "baseparticle"
        particle_dir.mkdir(exist_ok=True)
        (particle_dir / "particle_fates_all.csv").write_text(
            "patch,x,y,z\nwallSubstrate,0,0,0\noutlet,0,0,0\n"
        )
        (particle_dir / "particle_run_config.txt").write_text("total_particles=2\n")
        (particle_dir / "PARTICLE_DONE").touch()

    def test_offline_init_and_suggest_only_prepare_cases(self):
        with mock.patch.object(bo_loop, "run_sbatch") as submit:
            first = self.prepare()
            self.command("suggest", "--batch-size", "1")
            submit.assert_not_called()
        self.assertEqual([row["case"] for row in first], ["case_0000", "case_0001"])
        rows = bo_loop.read_csv_rows(bo_loop.candidates_path(self.workdir))
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[-1]["case"], "case_0002")
        self.assertTrue((self.workdir / "case_0002" / "params.dat").is_file())
        self.assertEqual(bo_loop.read_csv_rows(bo_loop.observations_path(self.workdir)), [])

    def test_cli_does_not_load_environment_files(self):
        unused_env = Path(self.temporary.name) / "unused.env"
        unused_env.write_text("this is not a valid environment setting\n")
        with mock.patch.dict(os.environ, {"AJP_SITE_ENV": str(unused_env)}):
            rows = self.prepare()
        self.assertEqual(len(rows), 2)

    def test_default_counts_and_explicit_128_then_32_generation(self):
        parser = bo_loop.build_parser()
        self.assertEqual(parser.parse_args(["init"]).initial_batch, 32)
        self.assertEqual(parser.parse_args(["suggest"]).batch_size, 8)
        self.config["bo"]["candidate_pool"] = 256
        self.config_path.write_text(json.dumps(self.config))
        with mock.patch.object(bo_loop, "run_sbatch") as submit:
            self.command("init", "--initial-batch", "128")
            self.command("suggest", "--batch-size", "32")
            submit.assert_not_called()
        rows = bo_loop.read_csv_rows(bo_loop.candidates_path(self.workdir))
        self.assertEqual(len(rows), 160)
        self.assertEqual([row["generation"] for row in rows[:128]], ["0"] * 128)
        self.assertEqual([row["generation"] for row in rows[128:]], ["1"] * 32)
        self.assertEqual(rows[0]["case"], "case_0000")
        self.assertEqual(rows[-1]["case"], "case_0159")
        # No observations were collected, so neither batch can use a fitted GP.
        self.assertTrue(all(row["method"] == "maximin_initial_mobo" for row in rows))

    def test_cli_rejects_automatic_execution_modes(self):
        parser = bo_loop.build_parser()
        for arguments in (["loop"], ["step"], ["init", "--submit"], ["suggest", "--submit"]):
            with self.subTest(arguments=arguments), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    parser.parse_args(arguments)
                self.assertNotEqual(raised.exception.code, 0)

    def test_selected_case_round_trip_and_idempotent_collection(self):
        particle_template = Path(self.temporary.name) / "particle-template"
        shutil.copytree(ROOT / "baseparticle", particle_template)
        library = particle_template / "custom/finiteRadiusDeposition/lib/libfiniteRadiusDeposition.so"
        library.parent.mkdir(parents=True, exist_ok=True)
        library.write_text("placeholder for mocked Slurm submission; not a real library\n")
        self.config["particle_template"] = str(particle_template)
        self.config_path.write_text(json.dumps(self.config))
        self.prepare()
        completed = subprocess.CompletedProcess(["sbatch"], 0, "Submitted batch job 123\n", "")
        with mock.patch.object(bo_loop, "queued_jobs", return_value=set()) as queue, \
                mock.patch.object(bo_loop.subprocess, "run", return_value=completed) as run:
            self.command("submit-cfd", "--cases", "case_0001")
            queue.assert_called_once_with(mock.ANY, strict=True)
            run.assert_called_once()
            self.assertEqual(Path(run.call_args.kwargs["cwd"]), self.workdir / "case_0001")
            self.assertEqual(run.call_args.args[0][-1], "run.sh")
        self.mark_cfd_done("case_0001")
        with mock.patch.object(bo_loop, "queued_jobs", return_value=set()), \
                mock.patch.object(bo_loop.subprocess, "run", return_value=completed) as run:
            self.command("submit-particles", "--cases", "case_0001")
            run.assert_called_once()
            self.assertEqual(
                Path(run.call_args.kwargs["cwd"]), self.workdir / "case_0001" / "baseparticle"
            )
            self.assertEqual(run.call_args.args[0][-1], "loopaerosolDynamics.sh")
        self.mark_particles_done("case_0000")
        self.mark_particles_done("case_0001")
        with mock.patch.object(bo_loop, "run_sbatch") as submit:
            self.command("collect", "--cases", "case_0001")
            self.command("collect", "--cases", "case_0001")
            rows = bo_loop.read_csv_rows(bo_loop.observations_path(self.workdir))
            self.assertEqual([row["case"] for row in rows], ["case_0001"])
            self.assertEqual(rows[0]["evaluation_status"], "complete")
            self.assertEqual(float(rows[0]["target_fraction"]), 0.5)
            self.assertEqual(float(rows[0]["target_precision"]), 1.0)
            self.assertEqual(float(rows[0]["resolved_ratio"]), 1.0)
            self.command("collect", "--cases", "case_0000")
            self.command("suggest", "--batch-size", "1")
            submit.assert_not_called()
        rows = bo_loop.read_csv_rows(bo_loop.observations_path(self.workdir))
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(bo_loop.read_csv_rows(bo_loop.candidates_path(self.workdir))), 3)

    def test_particle_submission_requires_finite_radius_library(self):
        self.prepare()
        self.mark_cfd_done("case_0000")
        particle_template = Path(self.temporary.name) / "unbuilt-particle-template"
        particle_template.mkdir()
        with mock.patch.object(bo_loop, "queued_jobs", return_value=set()), \
                mock.patch.object(bo_loop, "run_sbatch") as submit:
            with self.assertRaisesRegex(RuntimeError, "finiteRadiusDeposition"):
                bo_loop.submit_particles(self.config, self.workdir, particle_template)
            submit.assert_not_called()

    def test_real_submission_aborts_when_queue_cannot_be_checked(self):
        self.prepare()
        for failure in (
            FileNotFoundError("squeue is unavailable"),
            subprocess.CompletedProcess(["squeue"], 1, "", "scheduler unavailable"),
        ):
            with self.subTest(failure=failure):
                kwargs = {"side_effect": failure} if isinstance(failure, Exception) else {"return_value": failure}
                with mock.patch.object(bo_loop.subprocess, "run", **kwargs), \
                        mock.patch.object(bo_loop, "run_sbatch") as submit:
                    with self.assertRaises(RuntimeError):
                        bo_loop.submit_cfd(self.config, self.workdir)
                    submit.assert_not_called()
        with mock.patch.object(bo_loop.subprocess, "run", side_effect=FileNotFoundError):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(bo_loop.submit_cfd(self.config, self.workdir, dry_run=True), 2)

    def test_failed_cases_are_visible_and_are_not_resubmitted(self):
        self.prepare()
        (self.workdir / "case_0000" / "CFD_FAILED").touch()
        self.mark_cfd_done("case_0001")
        particle_dir = self.workdir / "case_0001" / "baseparticle"
        particle_dir.mkdir()
        (particle_dir / "PARTICLE_FAILED").touch()
        self.mark_particles_done("case_0001")
        with mock.patch.object(bo_loop, "queued_jobs", return_value=set()), \
                mock.patch.object(bo_loop, "run_sbatch") as submit:
            bo_loop.submit_cfd(self.config, self.workdir)
            bo_loop.submit_particles(self.config, self.workdir, ROOT / "baseparticle")
            submit.assert_not_called()
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                bo_loop.print_status(self.config, self.workdir)
        self.assertIn("cfd_failed: 1", output.getvalue())
        self.assertIn("particle_failed: 1", output.getvalue())
        self.assertIn("ready_collect: 0", output.getvalue())

    def test_queued_jobs_are_scoped_to_campaign_and_stage(self):
        self.prepare()
        cfd_name = bo_loop.job_name(self.config, self.workdir, "case_0000")
        particle_name = bo_loop.job_name(self.config, self.workdir, "case_0000", particle=True)
        other_name = bo_loop.job_name(self.config, self.workdir.parent / "other_campaign", "case_0000")
        self.assertEqual(len({cfd_name, particle_name, other_name}), 3)
        with mock.patch.object(bo_loop, "queued_jobs", return_value={cfd_name}), \
                mock.patch.object(bo_loop, "run_sbatch", return_value=True) as submit:
            self.assertEqual(bo_loop.submit_cfd(self.config, self.workdir), 1)
            self.assertEqual(submit.call_args.args[0], self.workdir / "case_0001")

    def test_site_nodelist_overrides_shared_config_on_submit(self):
        self.config["slurm"]["nodelist"] = "shared-node"
        completed = subprocess.CompletedProcess(["sbatch"], 0, "Submitted batch job 123\n", "")
        with mock.patch.dict(os.environ, {"AJP_SLURM_NODELIST": "student-node"}), \
                mock.patch.object(bo_loop.subprocess, "run", return_value=completed) as run:
            bo_loop.run_sbatch(self.workdir, "test-job", "run.sh", self.config)
        command = run.call_args.args[0]
        self.assertEqual(command[command.index("--nodelist") + 1], "student-node")


if __name__ == "__main__":
    unittest.main()
