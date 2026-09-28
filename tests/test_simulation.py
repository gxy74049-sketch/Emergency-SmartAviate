import unittest
from dataclasses import replace
from priority import PriorityTask, score_task
from simulation import Simulation, make_scenario, compare, SCENARIOS


def task(tid='A', **kwargs):
    values = dict(task_id=tid, cargo_type='食品', release_s=0, deadline_s=300,
                  expiry_s=None, level=0, severity=3, quantity_kg=5, people=100,
                  estimated_service_s=20)
    values.update(kwargs)
    return PriorityTask(**values)


class SimulationTests(unittest.TestCase):
    def test_emergency_reorders_without_preempting(self):
        s = Simulation([task('A'), task('B')], drone_count=1)
        s.inject('ADD', payload=__import__('dataclasses').asdict(task('E', level=2)))
        self.assertEqual(s.drones[0].task_id, 'A')
        self.assertEqual(s.queue[0], 'E')
        s.advance(40)
        self.assertEqual(s.drones[0].task_id, 'E')

    def test_partial_delivery_and_no_duplicate(self):
        s = Simulation([task(quantity_kg=8)], drone_count=3)
        self.assertEqual(sum(d.task_id == 'A' for d in s.drones), 1)
        s.advance(20)
        self.assertEqual(s.tasks['A'].spec.delivered_kg, 5)
        self.assertEqual(s.in_transit('A'), 3)
        s.advance(20)
        self.assertEqual(s.tasks['A'].spec.delivered_kg, 8)
        self.assertEqual(s.tasks['A'].status, 'COMPLETED')

    def test_cancel_at_delivery_prevents_delivery(self):
        s = Simulation([task()], [dict(time=20, kind='CANCEL', task_id='A')], drone_count=1)
        s.advance(40)
        self.assertEqual(s.tasks['A'].spec.delivered_kg, 0)
        self.assertEqual(s.tasks['A'].status, 'CANCELLED')
        self.assertIsNone(s.drones[0].task_id)

    def test_expiry_boundary_blocks_dispatch(self):
        s = Simulation([task(deadline_s=15, expiry_s=20)], drone_count=1)
        self.assertIsNone(s.drones[0].task_id)
        s.advance(20)
        self.assertEqual(s.tasks['A'].status, 'EXPIRED')
        self.assertNotIn('A', s.queue)

    def test_waiting_only_when_queued(self):
        s = Simulation([task('A'), task('B')], drone_count=1)
        s.advance(10)
        self.assertEqual(s.tasks['A'].spec.wait_s, 0)
        self.assertEqual(s.tasks['B'].spec.wait_s, 10)

    def test_future_task_does_not_wait(self):
        s = Simulation([task(release_s=10)], drone_count=1)
        s.advance(10)
        self.assertEqual(s.tasks['A'].spec.wait_s, 0)
        self.assertEqual(s.tasks['A'].first_dispatch, 10)

    def test_deadline_and_wait_can_reverse_same_level(self):
        a = task('A', deadline_s=800, severity=4, estimated_service_s=200)
        b = task('B', deadline_s=400, severity=2, estimated_service_s=200)
        # 占用唯一无人机，留下 A/B；B 的时间压力增长可超过 A 的严重度优势。
        s = Simulation([task('X', level=2, estimated_service_s=500), a, b], drone_count=1)
        self.assertEqual(s.queue, ['A', 'B'])
        s.advance(100)
        self.assertEqual(s.queue, ['B', 'A'])
        self.assertTrue(any(e['kind'] == '队列重排' for e in s.logs))

    def test_demand_and_level_events(self):
        s = Simulation([task('A'), task('B', quantity_kg=10, delivered_kg=5)], drone_count=1)
        before = score_task(s.tasks['B'].spec, 0).shortage
        s.inject('DEMAND', task_id='B', amount=5)
        self.assertGreater(score_task(s.tasks['B'].spec, 0).shortage, before)
        s.inject('ESCALATE', task_id='B', level=2, severity=5)
        self.assertGreaterEqual(score_task(s.tasks['B'].spec, 0).priority, 70)

    def test_soft_deadline_does_not_expire(self):
        s = Simulation([task(deadline_s=1)], drone_count=1)
        s.advance(20)
        self.assertEqual(s.tasks['A'].status, 'COMPLETED')
        self.assertEqual(s.metrics()['准时完成率'], 0)

    def test_end_no_new_dispatch(self):
        s = Simulation([task('A'), task('B')], drone_count=1, t_end=40)
        s.advance(100)
        self.assertEqual(s.now, 40)
        self.assertIsNone(s.tasks['B'].first_dispatch)
        with self.assertRaises(ValueError):
            s.inject('CANCEL', task_id='B')

    def test_reproducible_all_scenarios_and_conservation(self):
        for name in SCENARIOS:
            runs = []
            for _ in range(2):
                tasks, events = make_scenario(name, 42, 12)
                s = Simulation(tasks, events)
                s.advance(900)
                for state in s.tasks.values():
                    self.assertLessEqual(state.spec.delivered_kg, state.spec.quantity_kg)
                runs.append(s.export())
            self.assertEqual(*runs)

    def test_comparison_has_identical_task_denominators(self):
        rows = compare('中途新增急救', 42, 12, 2, 900)
        self.assertEqual([r['已发布任务'] for r in rows], [13, 13, 13])
        self.assertEqual([r['策略'] for r in rows], ['G0', 'G1', 'G2'])

    def test_lateness_no_longer_reduces_score(self):
        a = task(deadline_s=0, estimated_service_s=20, wait_s=300)
        self.assertEqual(score_task(a, 0).priority, score_task(a, 300).priority)


if __name__ == '__main__':
    unittest.main()
