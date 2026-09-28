"""四进口双向航路交叉口教学仿真。单位为米、秒。"""
from dataclasses import asdict, dataclass
from decimal import Decimal
from math import isfinite
import random

APPROACHES = ("北", "东", "南", "西")
OPPOSITE = {"北": "南", "南": "北", "东": "西", "西": "东"}
MANEUVERS = ("左转", "直行", "右转")
PHASES = APPROACHES


@dataclass
class Flight:
    id: str
    approach: str
    maneuver: str
    position: float
    level: int
    deadline: float
    task_level: int = 1
    time_limit: float = 0
    lane: str = "直右"
    wait: float = 0
    arrival: float | None = None
    granted: float | None = None
    completed: float | None = None
    entered: float | None = None
    cleared: float | None = None
    moving: bool = False
    held: bool = False
    contraflow: bool = False

    @property
    def route(self):
        return self.approach


class Crossing:
    MODEL_VERSION = 11
    SPEED, GAP, STOP, CLEAR, END, ENTRY = 20, 70, -80, 80, 300, -300
    HEADWAY, PHASE_DURATION, DT = 2, 10, .1
    SPAWN_INTERVAL = 5
    MAX_FLIGHTS = 200
    TASK_LEVELS = (1, 2, 3, 4, 5)
    TASK_LEVEL_WEIGHTS = (40, 25, 18, 11, 6)
    TASK_TIME_MEAN_MINUTES = 20
    TASK_TIME_SIGMA_MINUTES = 10
    TASK_TIME_MIN_MINUTES = 3

    def __init__(self, strategy="动态优先", continuous=False, seed=None, spawn_batch_size=1):
        if strategy not in ("动态优先", "先到先行"):
            raise ValueError("未知策略")
        self.strategy = strategy
        self.model_version = self.MODEL_VERSION
        self.continuous = bool(continuous)
        self.spawn_batch_size = max(1, min(4, int(spawn_batch_size)))
        self._rng = random.Random(seed)
        self.tick = 0
        self.signal_tick = 0
        self._pending_time = Decimal("0")
        self.owners: list[str] = []
        self.last_exit = -self.HEADWAY
        self.logs: list[dict] = []
        self.flights: list[Flight] = []
        self.generated = 0
        self.total_completed = 0
        self.crossing_time_sum = {0: 0.0, 1: 0.0, 2: 0.0}
        self.crossing_time_count = {0: 0, 1: 0, 2: 0}
        n = 1
        # 初始场景也随机配置任务属性；固定的独立种子让教学场景和自动测试可复现。
        initial_rng = random.Random(20260927 if seed is None else seed)
        for ai, approach in enumerate(APPROACHES):
            for qi, maneuver in enumerate(MANEUVERS):
                task_level, time_limit = self._random_task_profile(initial_rng)
                self.flights.append(Flight(
                    f"D{n:02}", approach, maneuver, self.STOP-qi*self.GAP, 0,
                    time_limit, task_level=task_level, time_limit=time_limit,
                    lane="本向"))
                n += 1
                self.generated += 1
        self._refresh_priorities(log_changes=False)
        self._arrivals()

    @property
    def now(self):
        return round(self.tick*self.DT, 1)

    @property
    def owner(self):
        return self.owners[0] if self.owners else None

    @property
    def phase(self):
        return f"{self.phase_approach}进口放行"

    @property
    def phase_approach(self):
        signal_time = self.signal_tick*self.DT
        return PHASES[int(signal_time // self.PHASE_DURATION) % len(PHASES)]

    @property
    def finished(self):
        return not self.continuous and all(f.completed is not None for f in self.flights)

    @classmethod
    def emergency_thresholds(cls, task_level):
        """返回任务等级对应的（紧急、极端紧急）阈值，单位为秒。"""
        if task_level not in cls.TASK_LEVELS:
            raise ValueError("任务等级必须为 1 至 5")
        offset = task_level-1
        return (10+2*offset)*60, (5+offset)*60

    def _random_task_profile(self, rng):
        # 权重随任务等级严格递减；限时服从正态分布并执行 3 分钟下限截断。
        task_level = rng.choices(
            self.TASK_LEVELS, weights=self.TASK_LEVEL_WEIGHTS, k=1)[0]
        sampled = rng.gauss(self.TASK_TIME_MEAN_MINUTES, self.TASK_TIME_SIGMA_MINUTES)
        minutes = max(self.TASK_TIME_MIN_MINUTES, round(sampled, 1))
        return task_level, minutes*60

    def priority_for(self, f, at_time=None):
        remaining = f.deadline-(self.now if at_time is None else at_time)
        urgent, extreme = self.emergency_thresholds(f.task_level)
        if remaining < extreme:
            return 2
        if remaining < urgent:
            return 1
        return 0

    def _refresh_priorities(self, log_changes=True):
        names = {0: "常态", 1: "紧急", 2: "极端紧急"}
        for f in self.flights:
            if f.completed is not None:
                continue
            new_level = self.priority_for(f)
            if new_level == f.level:
                continue
            old_level = f.level
            f.level = new_level
            if log_changes:
                remaining = f.deadline-self.now
                urgent, extreme = self.emergency_thresholds(f.task_level)
                self.logs.append(dict(
                    时间=self.now, 事件="优先级变化", 对象=f.id,
                    说明=(f"T{f.task_level} 任务剩余 {remaining/60:.1f} 分钟，"
                          f"阈值为紧急 <{urgent/60:g} 分钟、极端紧急 <{extreme/60:g} 分钟；"
                          f"E{old_level} → E{new_level} {names[new_level]}")
                ))

    def _spawn(self):
        available = []
        for approach in APPROACHES:
            incoming = [f.position for f in self.flights if f.completed is None and
                        f.approach == approach and f.granted is None]
            if not incoming or min(incoming) >= self.ENTRY+self.GAP:
                available.append(approach)
        if not available:
            return None
        approach = self._rng.choice(available)
        maneuver = self._rng.choice(MANEUVERS)
        task_level, time_limit = self._random_task_profile(self._rng)
        self.generated += 1
        f = Flight(f"D{self.generated:02}", approach, maneuver, self.ENTRY, 0,
                   self.now+time_limit, task_level=task_level, time_limit=time_limit,
                   lane="本向")
        f.level = self.priority_for(f)
        self.flights.append(f)
        names = {0: "常态", 1: "紧急", 2: "极端紧急"}
        self.logs.append(dict(时间=self.now, 事件="生成", 对象=f.id,
                              说明=(f"随机生成 T{task_level} 任务，限时 {time_limit/60:g} 分钟，"
                                    f"当前 E{f.level} {names[f.level]}；{approach}进口 {maneuver}，"
                                    f"进入{f.lane}车道")))
        completed = [x for x in self.flights if x.completed is not None]
        if len(self.flights) > self.MAX_FLIGHTS and completed:
            remove = min(completed, key=lambda x: x.completed)
            self.flights.remove(remove)
        return f

    def _maybe_spawn(self):
        interval_ticks = round(self.SPAWN_INTERVAL/self.DT)
        if self.continuous and self.tick > 0 and self.tick % interval_ticks == 0:
            for _ in range(self.spawn_batch_size):
                if self._spawn() is None:
                    break

    def average_crossing_times(self):
        return {level: (self.crossing_time_sum[level]/self.crossing_time_count[level]
                        if self.crossing_time_count[level] else None)
                for level in (0, 1, 2)}

    @property
    def all_red(self):
        return (any(f.level == 2 and f.granted is None and not f.held and
                    f.completed is None for f in self.flights) or
                any(self.get(owner).level == 2 for owner in self.owners))

    @property
    def green_approaches(self):
        if self.all_red:
            return ()
        active = []
        for owner in self.owners:
            f = self.get(owner)
            if f and f.approach not in active:
                active.append(f.approach)
        return tuple(active) if active else (self.phase_approach,)

    @property
    def signal_status(self):
        if self.all_red:
            return "全红（极端紧急）"
        if self.owners and any(self.get(owner).level == 1 for owner in self.owners):
            return f"紧急连续放行：{'、'.join(self.green_approaches)}进口"
        if self.owners:
            return f"连续放行：{'、'.join(self.green_approaches)}进口"
        return self.phase

    def get(self, flight_id):
        return next((f for f in self.flights if f.id == flight_id), None)

    def score_parts(self, f):
        score_time = f.completed if f.completed is not None else self.now
        pressure = min(1, max(0, 1-(f.deadline-score_time)/60))
        aging = min(1, f.wait/60)
        return {"等级分": 40*f.level, "时间分": 20*pressure, "等待分": 15*aging}

    def score(self, f):
        return sum(self.score_parts(f).values())

    def _lane_load(self, approach, lane, excluding=None):
        return sum(f.granted is None and f.completed is None and not f.held and
                   f.approach == approach and f.lane == lane and f.id != excluding
                   for f in self.flights)

    def shortest_lane(self, f):
        return "本向"

    def adjust(self, flight_id, task_level, remaining, wait, held=False):
        f = self.get(flight_id)
        if f is None or f.granted is not None:
            raise ValueError("仅能修改尚未获准的无人机")
        if task_level not in self.TASK_LEVELS or not isfinite(remaining) or not isfinite(wait) or wait < 0:
            raise ValueError("等级、剩余时间或等待时间无效")
        before, old_lane = self.score(f), f.lane
        f.task_level, f.time_limit = task_level, remaining
        f.deadline, f.wait, f.held = self.now+remaining, wait, bool(held)
        f.level = self.priority_for(f)
        f.lane = "本向"
        if held:
            f.moving = False
        urgent, extreme = self.emergency_thresholds(task_level)
        detail = (f"状态调整：T{task_level}，剩余 {remaining/60:g} 分钟，自动判定 E{f.level}；"
                  f"紧急阈值 <{urgent/60:g} 分钟，极端紧急阈值 <{extreme/60:g} 分钟；等待 {wait:g}s，"
                  f"{'暂停申请' if held else '正常申请'}；分数 {before:.2f} → {self.score(f):.2f}；"
                  f"车道 {old_lane} → {f.lane}")
        self.logs.append(dict(时间=self.now, 事件="状态调整", 对象=f.id, 说明=detail))
        return detail

    def _queue_heads(self):
        heads = []
        for approach in APPROACHES:
            queue = self._lane_queue(approach)
            if queue and abs(queue[0].position-self.STOP) < 1e-6:
                heads.append(queue[0])
        return heads

    def _lane_queue(self, approach):
        return sorted((f for f in self.flights if f.granted is None and not f.held and
                       f.completed is None and f.approach == approach),
                      key=lambda f: -f.position)

    def candidates(self):
        return sorted(self._queue_heads(), key=lambda f:
                      ((-f.level, -self.score(f), f.deadline, f.id)
                       if self.strategy == "动态优先" else
                       (-f.level, f.arrival if f.arrival is not None else 1e9, f.id)))

    @staticmethod
    def movements_conflict(a, b):
        """保守冲突判定：同进口、对向直/右、分离右转可并行。"""
        if a.id == b.id:
            return False
        if a.level == 2 or b.level == 2 or a.contraflow or b.contraflow:
            return True
        if a.approach == b.approach:
            return False
        opposite = OPPOSITE[a.approach] == b.approach
        if a.maneuver == b.maneuver == "右转":
            return False
        if opposite and a.maneuver == b.maneuver == "左转":
            return False
        if opposite and a.maneuver in ("直行", "右转") and b.maneuver in ("直行", "右转"):
            return False
        return True

    @staticmethod
    def exit_approach(f):
        i = APPROACHES.index(f.approach)
        if f.maneuver == "直行":
            return APPROACHES[(i+2) % 4]
        return APPROACHES[(i-1) % 4] if f.maneuver == "左转" else APPROACHES[(i+1) % 4]

    def _opposing_lane_clear(self, f):
        return not any(x.granted is not None and x.completed is None and x.id not in self.owners and
                       self.exit_approach(x) == f.approach and x.position < self.CLEAR
                       for x in self.flights)

    def _grant(self, flights, reason):
        for f in flights:
            f.granted = self.now
            if abs(f.position-self.STOP) < 1e-6:
                f.entered = self.now
            self.owners.append(f.id)
        ids = "、".join(f.id for f in flights)
        self.logs.append(dict(时间=self.now, 事件="放行", 对象=ids,
                              说明=f"{reason}；放行 {ids}"))

    def _dispatch(self):
        # E2 无条件先于常态清空间隔和 E1 调度；已进入路口的对象只做安全清空。
        extreme = sorted((f for f in self.flights if f.level == 2 and
                          f.granted is None and f.completed is None and not f.held),
                         key=lambda f: (-self.score(f), f.deadline, f.id))
        if extreme:
            if self.owners:
                return
            leader = extreme[0]
            convoy = sorted((f for f in self.flights if f.granted is None and not f.held and
                             f.completed is None and f.level == 2 and f.approach == leader.approach),
                            key=lambda f: -f.position)
            convoy_ids = {f.id for f in convoy}
            blocked_ahead = any(f.completed is None and f.id not in convoy_ids and
                                f.approach == leader.approach and f.position > leader.position
                                for f in self.flights)
            if not blocked_ahead:
                self._grant(convoy, "极端应急车队：本向前方无无人机，无视清空间隔直接连续放行")
            elif self._opposing_lane_clear(leader):
                for f in convoy:
                    f.contraflow = True
                self._grant(convoy, "极端应急车队：路口持续全红、对向车道已清空，同方向连续借道逆行")
            return
        if self.owners:
            active_e1 = [self.get(owner) for owner in self.owners if self.get(owner).level == 1]
            if active_e1:
                approach = active_e1[0].approach
                queue = self._lane_queue(approach)
                urgents = [f for f in queue if f.level == 1]
                if urgents:
                    last_index = max(queue.index(f) for f in urgents)
                    self._grant(queue[:last_index+1],
                                "紧急连续放行追加：保持当前绿灯，继续放行至同方向最后一架紧急无人机")
            return
        if self.now-self.last_exit < self.HEADWAY-1e-6:
            return
        heads = self._queue_heads()
        if not heads:
            return
        urgent_groups = []
        # E1 不改变四向轮转相位，只在其本来所属的进口相位内延长绿灯。
        queue = self._lane_queue(self.phase_approach)
        if queue and abs(queue[0].position-self.STOP) < 1e-6:
            urgents = [f for f in queue if f.level == 1]
            if urgents:
                last_index = max(queue.index(f) for f in urgents)
                representative = max(urgents, key=lambda f: (self.score(f), -f.deadline, f.id))
                urgent_groups.append((representative, queue[:last_index+1]))
        if urgent_groups:
            batch = urgent_groups[0][1]
            self._grant(batch, "紧急协调：保持本相位，连续放行至同方向最后一架紧急无人机，冲突方向等待")
            return
        queue = self._lane_queue(self.phase_approach)
        batch = queue[:3] if queue and abs(queue[0].position-self.STOP) < 1e-6 else []
        if batch:
            self._grant(batch, f"常态灯控：{self.phase}，同进口车队连续通过")

    def gate(self):
        if self.finished:
            return "本轮已完成，全部无人机已抵达终点"
        if self.owners:
            if self.all_red:
                if any(self.get(owner).level == 2 for owner in self.owners):
                    mode = "连续借道" if any(self.get(owner).contraflow for owner in self.owners) else "本向连续直行"
                    return f"极端紧急车队 {'、'.join(self.owners)} {mode}；路口保持全红"
                return f"极端紧急已触发全红；等待已在路口内的 {'、'.join(self.owners)} 安全清空"
            if any(self.get(owner).level == 1 for owner in self.owners):
                return f"紧急车队 {'、'.join(self.owners)} 连续通过；绿灯保持，冲突方向让行"
            return f"{'、'.join(self.owners)} 正在连续通过；冲突方向让行"
        extreme = [f for f in self.flights if f.granted is None and not f.held and
                   f.completed is None and f.level == 2]
        if extreme:
            ahead = any(f.completed is None and f.approach == extreme[0].approach and
                        f.id != extreme[0].id and f.position > extreme[0].position
                        for f in self.flights)
            if not ahead:
                return "极端应急最高优先：路口全红，本向前方为空，立即直接放行"
            return ("极端应急最高优先：对向车道已清空，准备借道" if self._opposing_lane_clear(extreme[0])
                    else "极端应急最高优先：路口全红，等待对向车道清空")
        remaining = self.HEADWAY-(self.now-self.last_exit)
        if remaining > 1e-6:
            return f"安全清空间隔，剩余 {remaining:.1f} 秒"
        if any(f.level == 1 for f in self._queue_heads()):
            return "紧急协调待放行：短队列引导，互不冲突路径可同时通过"
        return f"常态灯控：{self.phase}，其他三个进口停止"

    def status(self, f):
        if f.completed is not None:
            return "已完成"
        if f.granted is not None:
            return "借道逆行" if f.contraflow and f.position < self.CLEAR else ("获准通行" if f.id in self.owners else "驶离路口")
        if f.held:
            return "人工暂停"
        if abs(f.position-self.STOP) < 1e-6:
            return {2: "极端应急等待", 1: "紧急等待"}.get(f.level, "信号等待")
        return "跟随排队" if not f.moving else "接近路口"

    def wait_reason(self, f):
        status = self.status(f)
        if status == "人工暂停":
            return "暂停移动与通行申请"
        if "等待" in status:
            return self.gate()
        if status == "跟随排队":
            return "同车道保持安全间隔，禁止超越"
        return "—"

    def _arrivals(self):
        for f in self.flights:
            if f.arrival is None and abs(f.position-self.STOP) < 1e-6:
                f.arrival = self.now

    def advance(self, seconds=1):
        if not isinstance(seconds, (int, float)) or not isfinite(seconds) or seconds < 0:
            raise ValueError("推进时间必须是非负有限秒数")
        if self.finished:
            return
        self._pending_time += Decimal(str(seconds))
        step = Decimal(str(self.DT))
        steps = int(self._pending_time // step)
        self._pending_time -= steps * step
        for _ in range(steps):
            if self.finished:
                break
            self._maybe_spawn()
            self._refresh_priorities()
            self._dispatch()
            signal_running = not self.all_red
            old = {f.id: f.position for f in self.flights}
            for approach in APPROACHES:
                leader = None
                queue = sorted((x for x in self.flights if x.completed is None and
                                x.approach == approach), key=lambda x: -x.position)
                for f in queue:
                    limit = self.END if f.granted is not None else self.STOP
                    if f.held and f.granted is None:
                        limit = f.position
                    if leader is not None and not f.contraflow:
                        limit = min(limit, leader.position-self.GAP)
                    f.position = min(f.position+self.SPEED*self.DT, limit)
                    f.moving = f.position-old[f.id] > 1e-6
                    if (f.granted is not None and f.entered is None and
                            old[f.id] <= self.STOP < f.position):
                        f.entered = self.now+self.DT
                    if f.granted is None and not f.moving:
                        f.wait = round(f.wait+self.DT, 1)
                    if not f.contraflow:
                        leader = f
            self.tick += 1
            if signal_running:
                self.signal_tick += 1
            cleared = []
            for owner in list(self.owners):
                f = self.get(owner)
                if f.position >= self.CLEAR:
                    self.owners.remove(owner)
                    if f.cleared is None:
                        f.cleared = self.now
                        if f.arrival is not None:
                            elapsed = max(0.0, f.cleared-f.arrival)
                            self.crossing_time_sum[f.level] += elapsed
                            self.crossing_time_count[f.level] += 1
                    cleared.append(owner)
            if cleared and not self.owners:
                self.last_exit = self.now
                self.logs.append(dict(时间=self.now, 事件="清空", 对象="、".join(cleared),
                                      说明="冲突区已清空，开始安全间隔"))
            for f in self.flights:
                if f.completed is None and f.position >= self.END:
                    f.completed, f.moving = self.now, False
                    self.total_completed += 1
            self._arrivals()
        if self.finished:
            self._pending_time = Decimal("0")

    def promote(self, flight_id):
        f = self.get(flight_id)
        if f is None:
            raise ValueError("无人机编号不存在")
        if f.granted is not None or f.level == 2:
            raise ValueError("只可提升尚未获准且非 E2 的任务")
        _, extreme = self.emergency_thresholds(f.task_level)
        self.adjust(flight_id, f.task_level, extreme-self.DT, f.wait, f.held)

    def ranking_rows(self):
        eligible = {f.id for f in self.candidates()}
        flights = sorted((f for f in self.flights if f.granted is None),
                         key=lambda f: (-f.level, -self.score(f), f.deadline, f.id))
        return [{"评分排名": i+1, "无人机": f.id, "任务等级": f"T{f.task_level}",
                 "紧急状态": f"E{f.level}",
                 **{k: round(v, 2) for k, v in self.score_parts(f).items()},
                 "总分": round(self.score(f), 2), "进口": f.approach,
                 "车道": f.lane, "通行资格": "车道队首" if f.id in eligible else "排队中"}
                for i, f in enumerate(flights)]

    def rows(self):
        ranks = {f.id: i+1 for i, f in enumerate(self.candidates())}
        return [{"无人机": f.id, "进口": f.approach, "转向": f.maneuver,
                 "车道": f.lane, "任务等级": f"T{f.task_level}", "紧急状态": f"E{f.level}",
                 "任务限时 min": round(f.time_limit/60, 1), "位置 m": round(f.position, 1),
                 "状态": self.status(f), "剩余时间 s": round(f.deadline-(f.completed if f.completed is not None else self.now), 1),
                 "累计等待 s": f.wait, "动态分": round(self.score(f), 2),
                 "候选排名": ranks.get(f.id), "等待原因": self.wait_reason(f)}
                for f in self.flights]

    def export(self):
        return dict(strategy=self.strategy, continuous=self.continuous,
                    spawn_batch_size=self.spawn_batch_size, time=self.now,
                    signal_time=round(self.signal_tick*self.DT, 1), phase=self.phase,
                    owners=list(self.owners), all_red=self.all_red,
                    generated=self.generated, total_completed=self.total_completed,
                    average_crossing_times=self.average_crossing_times(),
                    crossing_time_count=dict(self.crossing_time_count),
                    pending_seconds=float(self._pending_time),
                    parameters=dict(speed=self.SPEED, gap=self.GAP, stop=self.STOP,
                                    clear=self.CLEAR, headway=self.HEADWAY,
                                    phase_duration=self.PHASE_DURATION,
                                    spawn_interval=self.SPAWN_INTERVAL),
                    flights=[asdict(f) for f in self.flights], logs=[dict(log) for log in self.logs])
