import unittest

import numpy as np

import mobo


class MultiObjectiveUtilitiesTest(unittest.TestCase):
    def setUp(self):
        self.config = {
            "parameters": {
                "x": [0.0, 1.0],
                "y": [0.0, 1.0],
            },
            "objective": {
                "version": "mobo_v1",
                "multi_objective": {
                    "objectives": [
                        "target_fraction",
                        "target_precision",
                        "target_centered_compactness",
                    ],
                    "constraints": [
                        "resolved_constraint",
                        "wall_constraint",
                    ],
                    "reference_point": [-0.001, -0.001, -0.001],
                },
            },
            "bo": {
                "max_training_points": 3,
                "recent_training_points": 0,
            },
        }

    def row(self, case, x, objectives, constraints=(0.0, 0.0)):
        return {
            "case": case,
            "x": str(x),
            "y": str(1.0 - x),
            "objective_version": "mobo_v1",
            "evaluation_status": "complete",
            "target_fraction": str(objectives[0]),
            "target_precision": str(objectives[1]),
            "target_centered_compactness": str(objectives[2]),
            "resolved_constraint": str(constraints[0]),
            "wall_constraint": str(constraints[1]),
        }

    def test_nondominated_mask_keeps_tradeoff_points(self):
        values = np.asarray(
            [
                [0.5, 0.2, 0.2],
                [0.2, 0.5, 0.2],
                [0.1, 0.1, 0.1],
            ]
        )

        mask = mobo.nondominated_mask(values)

        self.assertEqual(mask.tolist(), [True, True, False])

    def test_pareto_rows_exclude_constraint_violations(self):
        rows = [
            self.row("a", 0.1, (0.5, 0.2, 0.2)),
            self.row("b", 0.2, (0.2, 0.5, 0.2)),
            self.row("c", 0.3, (0.9, 0.9, 0.9), constraints=(0.1, 0.0)),
            self.row("d", 0.4, (0.1, 0.1, 0.1)),
        ]

        pareto = mobo.pareto_rows(rows, self.config)

        self.assertEqual({row["case"] for row in pareto}, {"a", "b"})

    def test_training_subset_keeps_target_positive_rows(self):
        rows = [
            self.row("zero_a", 0.0, (0.0, 0.1, 0.1)),
            self.row("positive", 0.2, (0.01, 0.2, 0.2)),
            self.row("zero_b", 0.4, (0.0, 0.4, 0.4)),
            self.row("zero_c", 0.6, (0.0, 0.6, 0.6)),
            self.row("zero_d", 1.0, (0.0, 0.8, 0.8)),
        ]

        selected = mobo.select_training_rows(rows, self.config)

        self.assertEqual(len(selected), 3)
        self.assertIn("positive", {row["case"] for row in selected})


if __name__ == "__main__":
    unittest.main()
