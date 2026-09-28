import unittest

from priority import PriorityTask, build_preview_tasks, rank_tasks, score_task


def task(**changes):
    values = dict(task_id='T01', cargo_type='急救药品', release_s=0, deadline_s=500,
                  expiry_s=800, level=2, severity=5, quantity_kg=10, people=99,
                  estimated_service_s=200)
    values.update(changes)
    return PriorityTask(**values)


class PriorityTests(unittest.TestCase):
    def test_hand_calculation_example(self):
        result = score_task(task(deadline_s=80, estimated_service_s=20, quantity_kg=10,
                                 delivered_kg=2, people=62, wait_s=60), 0)
        self.assertAlmostEqual(result.benefit, 0.77, places=2)
        self.assertAlmostEqual(result.priority, 93.10, places=2)

    def test_expired_task_is_not_scored(self):
        self.assertIsNone(score_task(task(deadline_s=20, expiry_s=20), 20))

    def test_unreleased_task_is_not_scored(self):
        self.assertIsNone(score_task(task(release_s=10), 9))

    def test_waiting_and_lateness_are_clipped(self):
        result = score_task(task(deadline_s=0, expiry_s=None, wait_s=3000), 3000)
        self.assertEqual(result.waiting, 1)
        self.assertEqual(result.lateness, 1)

    def test_level_isolation(self):
        normal = score_task(task(level=0, severity=5, people=1000, wait_s=300,
                                 deadline_s=0, expiry_s=None, estimated_service_s=0), 0)
        emergency = score_task(task(level=2, severity=0, people=0, quantity_kg=1,
                                    deadline_s=1000, expiry_s=None), 0)
        self.assertLessEqual(normal.priority, 30)
        self.assertGreaterEqual(emergency.priority, 70)

    def test_g0_uses_release_then_id(self):
        ranked = rank_tasks([task(task_id='B', release_s=0), task(task_id='A', release_s=0)], 'G0', 0)
        self.assertEqual([item[0].task_id for item in ranked], ['A', 'B'])

    def test_g1_uses_fixed_severity(self):
        ranked = rank_tasks([task(task_id='low', severity=2), task(task_id='high', severity=5)], 'G1', 0)
        self.assertEqual(ranked[0][0].task_id, 'high')

    def test_dynamic_groups_share_priority_rule(self):
        tasks = [task(task_id='A'), task(task_id='B', severity=4)]
        expected = [item[0].task_id for item in rank_tasks(tasks, 'G2', 0)]
        for strategy in ('G3', 'G4', 'G5'):
            self.assertEqual([item[0].task_id for item in rank_tasks(tasks, strategy, 0)], expected)

    def test_preview_generation_is_deterministic(self):
        parameters = dict(background_tasks=3, drone_count=4, seed=42, t_end=1800)
        self.assertEqual(build_preview_tasks('S02', parameters), build_preview_tasks('S02', parameters))
        self.assertEqual(len(build_preview_tasks('S02', parameters)), 4)


if __name__ == '__main__':
    unittest.main()
