import unittest

import numpy as np

import bo_loop


class CentralTargetObjectiveTest(unittest.TestCase):
    def setUp(self):
        self.config = bo_loop.deep_merge(
            bo_loop.DEFAULT_CONFIG,
            {
                "objective": {
                    "total_particles": 10,
                    "version": "central_target_d10um_v1",
                    "mode": "weighted_sum",
                    "target": {
                        "center_m": [0.0, 0.0],
                        "diameter_um": 10.0,
                    },
                    "weights": {
                        "target_fraction": 1.0,
                        "deposition_compactness": 0.3,
                        "substrate_overspray_fraction": -1.0,
                        "wall_deposition_fraction": -1.0,
                        "outlet_fraction": -0.2,
                        "unresolved_fraction": -0.5,
                    },
                }
            },
        )
        self.config["objective"]["weights"] = {
            "target_fraction": 1.0,
            "deposition_compactness": 0.3,
            "substrate_overspray_fraction": -1.0,
            "wall_deposition_fraction": -1.0,
            "outlet_fraction": -0.2,
            "unresolved_fraction": -0.5,
        }
        self.candidate = {"R_mm": 1.0}

    def test_target_overspray_and_wall_are_separate(self):
        counts = {
            "wallSubstrate": 3,
            "wallUpper": 1,
            "wallDown": 1,
            "wallCavity": 0,
            "outlet": 1,
        }
        substrate_points = np.asarray(
            [
                [0.0, 0.0],
                [4.0e-6, 0.0],
                [6.0e-6, 0.0],
            ]
        )

        metrics = bo_loop.compute_metrics(
            counts,
            substrate_points,
            self.candidate,
            self.config,
        )

        self.assertEqual(metrics["objective_version"], "central_target_d10um_v1")
        self.assertEqual(metrics["n_target"], 2)
        self.assertEqual(metrics["n_substrate_overspray"], 1)
        self.assertEqual(metrics["n_wall_deposition"], 2)
        self.assertAlmostEqual(metrics["target_fraction"], 0.2)
        self.assertAlmostEqual(metrics["substrate_overspray_fraction"], 0.1)
        self.assertAlmostEqual(metrics["wall_deposition_fraction"], 0.2)
        self.assertAlmostEqual(metrics["outlet_fraction"], 0.1)
        self.assertAlmostEqual(metrics["unresolved_fraction"], 0.4)

        expected = (
            metrics["target_fraction"]
            + 0.3 * metrics["deposition_compactness"]
            - metrics["substrate_overspray_fraction"]
            - metrics["wall_deposition_fraction"]
            - 0.2 * metrics["outlet_fraction"]
            - 0.5 * metrics["unresolved_fraction"]
        )
        self.assertAlmostEqual(metrics["score"], expected)

    def test_lexicographic_target_always_prefers_one_more_target_particle(self):
        self.config["objective"].update(
            {
                "version": "central_target_d10um_v2_lexicographic",
                "mode": "target_lexicographic",
                "tie_break_particles": 0.25,
                "secondary_clip": 1.0,
                "target_compactness": {"min_particles": 2},
                "weights": {
                    "targeted_deposition_compactness": 0.3,
                    "substrate_overspray_fraction": -1.0,
                    "wall_deposition_fraction": -1.0,
                    "outlet_fraction": -0.2,
                    "unresolved_fraction": -0.5,
                },
            }
        )
        no_target = bo_loop.compute_metrics(
            {
                "wallSubstrate": 0,
                "wallUpper": 0,
                "wallDown": 0,
                "wallCavity": 0,
                "outlet": 10,
            },
            np.empty((0, 2)),
            self.candidate,
            self.config,
        )
        one_target = bo_loop.compute_metrics(
            {
                "wallSubstrate": 10,
                "wallUpper": 0,
                "wallDown": 0,
                "wallCavity": 0,
                "outlet": 0,
            },
            np.asarray(
                [[0.0, 0.0]]
                + [[1.0e-3, 0.0] for _ in range(9)]
            ),
            self.candidate,
            self.config,
        )

        self.assertEqual(no_target["n_target"], 0)
        self.assertEqual(one_target["n_target"], 1)
        self.assertGreater(one_target["score"], no_target["score"])

    def test_compactness_has_no_credit_without_target_particles(self):
        self.config["objective"].update(
            {
                "version": "central_target_d10um_v2_lexicographic",
                "mode": "target_lexicographic",
                "target_compactness": {"min_particles": 2},
                "weights": {
                    "targeted_deposition_compactness": 0.3,
                },
            }
        )
        metrics = bo_loop.compute_metrics(
            {
                "wallSubstrate": 3,
                "wallUpper": 0,
                "wallDown": 0,
                "wallCavity": 0,
                "outlet": 0,
            },
            np.asarray(
                [
                    [1.0e-3, 0.0],
                    [1.001e-3, 0.0],
                    [1.002e-3, 0.0],
                ]
            ),
            self.candidate,
            self.config,
        )

        self.assertGreater(metrics["deposition_compactness"], 0.0)
        self.assertEqual(metrics["target_particle_support"], 0.0)
        self.assertEqual(metrics["targeted_deposition_compactness"], 0.0)

    def test_multi_objective_metrics_use_prescribed_target_center(self):
        self.config["objective"].update(
            {
                "version": "central_target_mobo_v1",
                "mode": "multi_objective",
                "target_centered_compactness": {
                    "radius_quantile": 0.9,
                    "min_particles": 2,
                },
                "constraints": {
                    "resolved_ratio_min": 0.9,
                    "wall_deposition_fraction_max": 0.05,
                },
            }
        )
        substrate_points = np.asarray(
            [
                [0.0, 0.0],
                [4.0e-6, 0.0],
                [100.0e-6, 0.0],
            ]
        )
        metrics = bo_loop.compute_metrics(
            {
                "wallSubstrate": 3,
                "wallUpper": 0,
                "wallDown": 0,
                "wallCavity": 0,
                "outlet": 7,
            },
            substrate_points,
            self.candidate,
            self.config,
        )

        self.assertAlmostEqual(metrics["target_fraction"], 0.2)
        self.assertAlmostEqual(metrics["target_precision"], 2.0 / 3.0)
        self.assertGreater(metrics["target_r90_radius_um"], 4.0)
        self.assertLess(metrics["target_centered_compactness"], 1.0)
        self.assertAlmostEqual(metrics["target_centered_particle_support"], 1.0)
        self.assertAlmostEqual(metrics["resolved_constraint"], -0.1)
        self.assertAlmostEqual(metrics["wall_constraint"], -0.05)
        self.assertAlmostEqual(metrics["score"], metrics["target_fraction"])

    def test_target_centered_compactness_is_zero_without_target_hits(self):
        self.config["objective"].update(
            {
                "mode": "multi_objective",
                "target_centered_compactness": {
                    "radius_quantile": 0.9,
                    "min_particles": 2,
                },
            }
        )
        metrics = bo_loop.compute_metrics(
            {
                "wallSubstrate": 3,
                "wallUpper": 0,
                "wallDown": 0,
                "wallCavity": 0,
                "outlet": 7,
            },
            np.asarray(
                [
                    [100.0e-6, 0.0],
                    [101.0e-6, 0.0],
                    [102.0e-6, 0.0],
                ]
            ),
            self.candidate,
            self.config,
        )

        self.assertEqual(metrics["n_target"], 0)
        self.assertEqual(metrics["target_centered_particle_support"], 0.0)
        self.assertEqual(metrics["target_centered_compactness"], 0.0)

    def test_missing_substrate_coordinate_is_overspray(self):
        counts = {
            "wallSubstrate": 2,
            "wallUpper": 0,
            "wallDown": 0,
            "wallCavity": 0,
            "outlet": 0,
        }
        substrate_points = np.asarray([[0.0, 0.0]])

        metrics = bo_loop.compute_metrics(
            counts,
            substrate_points,
            self.candidate,
            self.config,
        )

        self.assertEqual(metrics["n_target"], 1)
        self.assertEqual(metrics["n_substrate_overspray"], 1)

    def test_gp_ignores_other_objective_versions(self):
        rows = [
            {
                **{key: np.mean(value) for key, value in self.config["parameters"].items()},
                "score": "0.5",
                "objective_version": "legacy",
            }
        ]
        x_train, y_train = bo_loop.load_observation_xy(rows, self.config)
        self.assertEqual(x_train.shape[0], 0)
        self.assertEqual(y_train.shape[0], 0)

    def test_initial_mobo_design_uses_maximin_without_torch(self):
        config = bo_loop.deep_merge(
            bo_loop.DEFAULT_CONFIG,
            {
                "objective": {
                    "version": "fresh_mobo",
                    "mode": "multi_objective",
                },
                "bo": {
                    "strategy": "qlognehvi",
                    "gp_min_points": 32,
                    "min_distance": 0.001,
                },
            },
        )
        pool = np.asarray(
            [
                [0.0] * 11,
                [1.0] * 11,
                [0.5] * 11,
            ]
        )

        selected, method = bo_loop.select_candidates(
            pool,
            np.empty((0, 11)),
            np.empty((0, 11)),
            [],
            2,
            config,
        )

        self.assertEqual(selected.shape, (2, 11))
        self.assertEqual(method, "maximin_initial_mobo")


if __name__ == "__main__":
    unittest.main()
