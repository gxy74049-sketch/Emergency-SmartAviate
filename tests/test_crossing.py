import unittest
from collections import Counter
from pathlib import Path
import random
import statistics

from streamlit.testing.v1 import AppTest

from app import _remaining_label, scene
from crossing import APPROACHES, Crossing


class CrossingTests(unittest.TestCase):
    def isolate(self, sim, *ids):
        keep = set(ids)
        for f in sim.flights:
            if f.id not in keep:
                f.completed = 0
                f.position = sim.END
            else:
                f.task_level = 1
                f.time_limit = 20*60
                f.deadline = sim.now+f.time_limit
                f.level = sim.priority_for(f)
        return [sim.get(i) for i in ids]

    def set_priority(self, sim, flight, level, task_level=1):
        remaining = {0: 20*60, 1: 7*60, 2: 4*60}[level]
        flight.task_level = task_level
        flight.deadline = sim.now+remaining
        flight.time_limit = remaining
        flight.level = sim.priority_for(flight)
        self.assertEqual(flight.level, level)

    def test_four_bidirectional_approaches_and_lane_assignment(self):
        sim = Crossing()
        self.assertEqual(set(f.approach for f in sim.flights), set(APPROACHES))
        self.assertEqual(len(sim.flights), 12)
        for f in sim.flights:
            self.assertEqual(f.lane, "本向")
            self.assertIn(f.task_level, Crossing.TASK_LEVELS)
            self.assertGreater(f.time_limit, 0)
        self.assertEqual({Crossing.exit_approach(f) for f in sim.flights}, set(APPROACHES))

    def test_task_level_deadline_thresholds_are_strict_and_scaled(self):
        sim = Crossing()
        flight = sim.get("D01")
        flight.task_level = 1
        flight.deadline = sim.now+10*60
        self.assertEqual(sim.priority_for(flight), 0)
        flight.deadline = sim.now+10*60-.1
        self.assertEqual(sim.priority_for(flight), 1)
        flight.deadline = sim.now+5*60
        self.assertEqual(sim.priority_for(flight), 1)
        flight.deadline = sim.now+5*60-.1
        self.assertEqual(sim.priority_for(flight), 2)

        self.assertEqual(sim.emergency_thresholds(3), (14*60, 7*60))
        flight.task_level = 3
        flight.deadline = sim.now+13*60
        self.assertEqual(sim.priority_for(flight), 1)
        flight.deadline = sim.now+6*60
        self.assertEqual(sim.priority_for(flight), 2)

    def test_random_task_profile_has_descending_levels_and_truncated_normal_time(self):
        sim = Crossing(seed=7)
        rng = random.Random(2026)
        profiles = [sim._random_task_profile(rng) for _ in range(50000)]
        counts = Counter(level for level, _ in profiles)
        self.assertTrue(all(counts[level] > counts[level+1] for level in range(1, 5)))

        minutes = [seconds/60 for _, seconds in profiles]
        self.assertGreaterEqual(min(minutes), 3)
        self.assertAlmostEqual(statistics.mean(minutes), 20, delta=.5)
        self.assertAlmostEqual(statistics.pstdev(minutes), 10, delta=1)

    def test_generated_flights_have_random_task_profile_and_derived_priority(self):
        sim = Crossing(continuous=True, seed=7, spawn_batch_size=4)
        sim.advance(5.1)
        generated = [f for f in sim.flights if int(f.id[1:]) > 12]
        self.assertEqual(len(generated), 4)
        self.assertTrue(all(f.task_level in Crossing.TASK_LEVELS for f in generated))
        self.assertTrue(all(f.time_limit >= 3*60 for f in generated))
        self.assertTrue(all(f.level == sim.priority_for(f) for f in generated))

    def test_scene_badge_shows_live_remaining_time_task_level_and_priority(self):
        sim = Crossing()
        flight, = self.isolate(sim, "D01")
        flight.task_level = 1
        flight.deadline = sim.now+599.1
        flight.level = sim.priority_for(flight)
        first = scene(sim)
        self.assertIn("D01 · T1 · E1 紧急", first)
        self.assertIn("剩余 10:00", first)

        sim.advance(.2)
        second = scene(sim)
        self.assertIn("剩余 09:59", second)
        self.assertEqual(_remaining_label(-1.2), "-00:02")

    def test_normal_four_protected_phases_and_right_turn_yield(self):
        sim = Crossing()
        north_left, south_left, east_left = self.isolate(sim, "D01", "D07", "D04")
        sim.advance(.1)
        self.assertIn(north_left.id, sim.owners)
        self.assertNotIn(south_left.id, sim.owners)
        self.assertNotIn(east_left.id, sim.owners)
        self.assertIn("北进口放行", sim.logs[0]["说明"])

        phase_sim = Crossing()
        self.assertEqual(phase_sim.phase, "北进口放行")
        phase_sim.signal_tick = 100
        self.assertEqual(phase_sim.phase, "东进口放行")
        phase_sim.signal_tick = 200
        self.assertEqual(phase_sim.phase, "南进口放行")
        phase_sim.signal_tick = 300
        self.assertEqual(phase_sim.phase, "西进口放行")

        sim = Crossing()
        right_a, right_b = self.isolate(sim, "D03", "D06")
        right_a.position = right_b.position = sim.STOP
        sim._arrivals()
        sim.advance(.1)
        self.assertEqual(set(sim.owners), {"D03"})
        self.assertFalse(Crossing.movements_conflict(right_a, right_b))

    def test_normal_release_can_take_three_vehicle_platoon(self):
        sim = Crossing()
        left, straight, right = self.isolate(sim, "D01", "D02", "D03")
        sim.advance(.1)
        self.assertEqual(set(sim.owners), {"D01", "D02", "D03"})

    def test_single_direction_lane_spacing_and_lane_invariant(self):
        sim = Crossing(continuous=True, seed=0)
        for _ in range(800):
            sim.advance(.1)
            for f in sim.flights:
                self.assertEqual(f.lane, "本向")
            for approach in APPROACHES:
                waiting = [f for f in sim.flights if f.completed is None and f.granted is None and
                           not f.held and f.approach == approach and f.position <= sim.STOP]
                positions = sorted(f.position for f in waiting)
                self.assertTrue(all(b-a >= sim.GAP-1e-6 for a, b in zip(positions, positions[1:])))

    def test_emergency_keeps_turn_lane_and_releases_prefix_through_emergency(self):
        sim = Crossing()
        leader, urgent = sim.get("D02"), sim.get("D03")
        self.isolate(sim, "D02", "D03")
        leader.position, urgent.position = sim.STOP, sim.STOP-sim.GAP
        sim.adjust("D03", 1, 7*60, 0)
        self.assertEqual(urgent.lane, "本向")
        sim.advance(.1)
        self.assertEqual(set(sim.owners), {"D02", "D03"})
        self.assertIn("最后一架紧急无人机", sim.logs[-1]["说明"])

    def test_emergency_does_not_change_current_signal_phase(self):
        sim = Crossing()
        north, south = self.isolate(sim, "D02", "D08")
        for f in (north, south):
            f.position = sim.STOP
            self.set_priority(sim, f, 1)
        sim._arrivals()
        sim.advance(.1)
        self.assertEqual(set(sim.owners), {"D02"})
        self.assertIsNone(south.granted)
        self.assertEqual(sim.green_approaches, ("北",))

    def test_conflicting_emergencies_release_by_priority(self):
        sim = Crossing()
        north, east = self.isolate(sim, "D02", "D05")
        for f in (north, east):
            f.position = sim.STOP
            self.set_priority(sim, f, 1)
        north.deadline, east.deadline = sim.now+8*60, sim.now+6*60
        sim._arrivals()
        sim.advance(.1)
        self.assertEqual(sim.owners, ["D02"])
        self.assertIsNone(east.granted)
        sim.advance(20)
        self.assertIsNotNone(east.granted)
        self.assertGreater(east.granted, north.granted)

    def test_extreme_emergency_all_red_and_contraflow(self):
        sim = Crossing()
        extreme, normal = self.isolate(sim, "D01", "D04")
        self.set_priority(sim, extreme, 2)
        self.assertTrue(sim.all_red)
        self.assertIn("全红", sim.gate())
        sim.advance(.1)
        self.assertEqual(sim.owners, ["D01"])
        self.assertFalse(extreme.contraflow)
        self.assertIsNone(normal.granted)
        self.assertIn("前方无无人机", sim.logs[0]["说明"])

        blocked = Crossing()
        normal, extreme = self.isolate(blocked, "D01", "D02")
        self.set_priority(blocked, extreme, 2)
        blocked.advance(.1)
        self.assertEqual(blocked.owners, ["D02"])
        self.assertTrue(extreme.contraflow)
        self.assertIsNone(normal.granted)
        self.assertIn("借道逆行", blocked.logs[0]["说明"])

    def test_same_direction_emergency_convoys_have_no_internal_headway(self):
        urgent_sim = Crossing()
        first, second, normal = self.isolate(urgent_sim, "D01", "D02", "D03")
        self.set_priority(urgent_sim, first, 1)
        self.set_priority(urgent_sim, second, 1)
        urgent_sim.advance(.1)
        self.assertEqual(set(urgent_sim.owners), {"D01", "D02"})
        self.assertEqual(first.granted, second.granted)
        self.assertIsNone(normal.granted)
        self.assertEqual(urgent_sim.green_approaches, ("北",))
        self.assertIn("紧急连续放行", urgent_sim.signal_status)

        extreme_sim = Crossing()
        first, second = self.isolate(extreme_sim, "D01", "D02")
        self.set_priority(extreme_sim, first, 2)
        self.set_priority(extreme_sim, second, 2)
        extreme_sim.advance(.1)
        self.assertEqual(set(extreme_sim.owners), {"D01", "D02"})
        self.assertEqual(first.granted, second.granted)
        self.assertFalse(first.contraflow or second.contraflow)
        self.assertTrue(extreme_sim.all_red)
        self.assertEqual(extreme_sim.green_approaches, ())
        self.assertIn("直接连续放行", extreme_sim.logs[0]["说明"])

    def test_urgent_convoy_extends_to_new_last_urgent(self):
        sim = Crossing()
        first, second = self.isolate(sim, "D01", "D02")
        self.set_priority(sim, first, 1)
        sim.advance(.1)
        self.assertEqual(sim.owners, ["D01"])
        sim.adjust("D02", 1, 7*60, 0)
        sim.advance(.1)
        self.assertEqual(set(sim.owners), {"D01", "D02"})
        self.assertIn("最后一架紧急无人机", sim.logs[-1]["说明"])

    def test_extreme_emergency_pauses_and_resumes_signal_cycle(self):
        sim = Crossing()
        self.isolate(sim, "D01")
        self.set_priority(sim, sim.get("D01"), 2)
        sim.tick = sim.signal_tick = 90
        self.assertEqual(sim.phase, "北进口放行")
        sim.advance(8.1)
        self.assertEqual(sim.phase, "北进口放行")
        self.assertEqual(sim.signal_tick, 91)
        sim.advance(1.1)
        self.assertEqual(sim.phase, "东进口放行")

    def test_fractional_steps_and_complete_run_are_repeatable(self):
        whole, split = Crossing(), Crossing()
        whole.advance(.3)
        for _ in range(6):
            split.advance(.05)
        self.assertEqual(whole.export(), split.export())
        first, second = Crossing(), Crossing()
        first.advance(200)
        second.advance(200)
        self.assertTrue(first.finished)
        self.assertEqual(first.export(), second.export())

    def test_continuous_generation_includes_emergencies_and_never_finishes(self):
        sim = Crossing(continuous=True, seed=0)
        sim.advance(180)
        self.assertGreater(sim.generated, 12)
        self.assertGreater(sim.total_completed, 0)
        self.assertTrue(any(e["事件"] == "生成" and "E1" in e["说明"] for e in sim.logs))
        self.assertTrue(any(e["事件"] == "放行" and "极端应急" in e["说明"] for e in sim.logs))
        self.assertFalse(sim.finished)

    def test_generation_batch_size_and_average_crossing_time_by_level(self):
        stream = Crossing(continuous=True, seed=0, spawn_batch_size=4)
        stream.advance(5.1)
        self.assertEqual(stream.generated, 16)

        for level in (0, 1, 2):
            sim = Crossing()
            self.isolate(sim, "D01")
            self.set_priority(sim, sim.get("D01"), level)
            sim.advance(9)
            averages = sim.average_crossing_times()
            self.assertEqual(sim.crossing_time_count[level], 1)
            self.assertAlmostEqual(averages[level], 8.0, places=1)
            self.assertTrue(all(averages[other] is None for other in (0, 1, 2) if other != level))

    def test_continuous_seed_reproduces_export(self):
        first = Crossing(continuous=True, seed=42, spawn_batch_size=3)
        second = Crossing(continuous=True, seed=42, spawn_batch_size=3)
        first.advance(120)
        second.advance(120)
        self.assertEqual(first.export(), second.export())
        self.assertEqual(first.export()["seed"], 42)
        self.assertEqual(first.export()["model_version"], Crossing.MODEL_VERSION)
        self.assertNotEqual(Crossing(seed=42).rows(), Crossing(seed=43).rows())

    def test_ui_seed_requires_reset_and_replays(self):
        page = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py")).run(timeout=30)
        page.number_input(key="cross_seed").set_value(42).run()
        self.assertTrue(page.button(key="cross_start").disabled)
        self.assertTrue(page.button(key="cross_step").disabled)
        page.button(key="cross_reset").click().run()
        self.assertEqual(page.session_state["crossing"].seed, 42)
        page.button(key="cross_jump").click().run()
        snapshot = page.session_state["crossing"].export()
        page.button(key="cross_reset").click().run()
        page.button(key="cross_jump").click().run()
        self.assertEqual(page.session_state["crossing"].export(), snapshot)
        self.assertFalse(page.exception)

    def test_invalid_inputs_and_snapshot(self):
        sim = Crossing()
        snapshot = sim.export()
        for invalid in (-1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                sim.advance(invalid)
        with self.assertRaises(ValueError):
            sim.adjust("missing", 1, 1, 0)
        self.assertEqual(sim.export(), snapshot)

    def test_ui_adjustment_controls_and_scene_component(self):
        page = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py")).run(timeout=30)
        self.assertFalse(page.exception)
        self.assertEqual(page.selectbox(key="edit_flight").value, "D01")
        next(s for s in page.selectbox if s.label == "任务等级").select(5)
        next(n for n in page.number_input if n.label == "剩余限时（分钟，可为负）").set_value(8.0)
        next(b for b in page.button if b.label == "应用状态并重新评分").click().run()
        self.assertEqual(page.session_state["crossing"].get("D01").task_level, 5)
        self.assertEqual(page.session_state["crossing"].get("D01").level, 2)
        self.assertTrue(page.session_state["crossing"].all_red)
        self.assertFalse(page.exception)

    def test_ui_play_reset_and_strategy(self):
        page = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py")).run(timeout=30)
        page.slider(key="spawn_batch_size").set_value(3).run()
        self.assertEqual(page.session_state["crossing"].spawn_batch_size, 3)
        page.button(key="cross_step").click().run()
        self.assertEqual(page.session_state["crossing"].now, 1)
        page.selectbox(key="cross_strategy").select("先到先行").run()
        self.assertTrue(page.button(key="cross_step").disabled)
        page.button(key="cross_reset").click().run()
        self.assertEqual(page.session_state["crossing"].strategy, "先到先行")
        page.button(key="cross_start").click().run()
        self.assertTrue(page.session_state["playing"])
        page.button(key="cross_pause").click().run()
        self.assertFalse(page.session_state["playing"])
        self.assertFalse(page.exception)


if __name__ == "__main__":
    unittest.main()
