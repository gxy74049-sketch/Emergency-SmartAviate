"""动态优先级教学仿真：单一时钟、非抢占批次配送、可重放事件。"""
from dataclasses import asdict, dataclass, replace
from math import isfinite
from random import Random
from priority import PriorityTask, rank_tasks, score_task

SCENARIOS = {
    '常规配送': '任务分批发布，观察时间压力与等待补偿。',
    '中途新增急救': '120 秒新增一项 E2 急救任务，立即重排等待队列。',
    '需求变化': '90 秒 T03 追加 5 kg；150 秒 T04 升为 E2。',
    '长期等待': '任务集中发布且运输耗时较长，观察等待补偿及队列变化。',
    '取消与失效': '60 秒取消 T03；T04 在 100 秒硬失效。',
}
STRATEGIES = {'G0': '先到先服务', 'G1': '固定严重度', 'G2': '动态优先级'}


@dataclass
class TaskState:
    spec: PriorityTask
    status: str = 'PENDING'
    first_dispatch: int | None = None
    completed_at: int | None = None


@dataclass
class Drone:
    drone_id: str
    task_id: str | None = None
    amount: float = 0
    arrival: int = 0
    available: int = 0
    delivered: bool = False


def make_scenario(name='中途新增急救', seed=42, count=12):
    if name not in SCENARIOS or not 4 <= count <= 30:
        raise ValueError('未知场景或任务数不在 4～30 范围内')
    rng = Random(seed)
    tasks = []
    for i in range(count):
        release = 0 if name == '长期等待' else (i // 4) * 30
        level = 0 if i % 3 else 1
        tasks.append(PriorityTask(
            f'T{i+1:02}', '紧迫饮水' if level else '食品', release,
            release + rng.randint(180, 600), None, level,
            4.0 if level else 3.0, rng.randint(2, 10), rng.randint(20, 500),
            estimated_service_s=rng.randint(100, 160) if name == '长期等待' else rng.randint(40, 90)))
    events = []
    if name == '中途新增急救':
        emergency = PriorityTask('EM01', '急救药品', 120, 300, 540, 2, 5, 2, 80, estimated_service_s=50)
        events.append(dict(time=120, kind='ADD', payload=asdict(emergency)))
    elif name == '需求变化':
        events = [dict(time=90, kind='DEMAND', task_id='T03', amount=5),
                  dict(time=150, kind='ESCALATE', task_id='T04', level=2, severity=5)]
    elif name == '取消与失效':
        tasks[3] = replace(tasks[3], deadline_s=70, expiry_s=100, estimated_service_s=60)
        events = [dict(time=60, kind='CANCEL', task_id='T03')]
    return tasks, events


class Simulation:
    def __init__(self, tasks, events=(), strategy='G2', drone_count=2, t_end=900):
        if strategy not in STRATEGIES or type(drone_count) is not int or not 1 <= drone_count <= 20 or t_end <= 0:
            raise ValueError('策略、无人机数量或结束时间无效')
        self.now = 0
        self.t_end = t_end
        self.strategy = strategy
        self.tasks = {}
        for task in tasks:
            self._insert(task)
        self.initial_tasks = [asdict(t.spec) for t in self.tasks.values()]
        self.events = [dict(e, event_id=f'PRE{i:03}') for i, e in enumerate(events)]
        self.processed = set()
        self.manual_events = []
        self.drones = [Drone(f'D{i+1:02}') for i in range(drone_count)]
        self.logs = []
        self.history = []
        self.previous = {}
        self.queue = []
        self._cycle('初始化')

    def _insert(self, task):
        score_task(task, task.release_s)
        if task.task_id in self.tasks:
            raise ValueError('任务编号重复')
        if not 0 <= task.severity <= 5 or task.release_s < 0 or task.estimated_service_s <= 0:
            raise ValueError('严重度、发布时间或配送耗时无效')
        if not 0 <= task.delivered_kg <= task.quantity_kg:
            raise ValueError('已送达数量无效')
        self.tasks[task.task_id] = TaskState(task)

    @property
    def finished(self):
        return self.now >= self.t_end

    def _log(self, kind, task_id, detail):
        self.logs.append(dict(time=self.now, kind=kind, task_id=task_id, detail=detail))

    def in_transit(self, task_id):
        return sum(d.amount for d in self.drones if d.task_id == task_id and not d.delivered)

    def _eligible(self):
        result = []
        for state in self.tasks.values():
            t = state.spec
            if state.status in ('CANCELLED', 'EXPIRED', 'COMPLETED') or t.release_s > self.now:
                continue
            # 同一父任务同时只执行一个批次；最多载重 5 kg。
            if self.in_transit(t.task_id) > 0:
                continue
            if t.quantity_kg > t.delivered_kg:
                result.append(t)
        return result

    def _apply(self, event):
        kind = event['kind']
        if kind == 'ADD':
            task = PriorityTask(**event['payload'])
            self._insert(task)
            self._log('新增任务', task.task_id, f'新增 E{task.level} {task.cargo_type}，{task.quantity_kg:g} kg')
            return
        tid = event['task_id']
        if tid not in self.tasks:
            raise ValueError('任务不存在')
        state = self.tasks[tid]
        if state.status in ('CANCELLED', 'EXPIRED', 'COMPLETED'):
            self._log('事件跳过', tid, '任务已终止，原事件保留在重放记录中')
            return
        if kind == 'DEMAND':
            amount = event['amount']
            if not isfinite(amount) or amount <= 0:
                raise ValueError('追加数量必须大于 0')
            state.spec = replace(state.spec, quantity_kg=state.spec.quantity_kg + amount)
            self._log('需求追加', tid, f'追加 {amount:g} kg，总需求 {state.spec.quantity_kg:g} kg')
        elif kind == 'ESCALATE':
            if event['level'] not in (0, 1, 2) or not 0 <= event['severity'] <= 5:
                raise ValueError('等级或严重度无效')
            state.spec = replace(state.spec, level=event['level'], severity=event['severity'])
            self._log('灾情变更', tid, f'等级 E{state.spec.level}，严重度 {state.spec.severity:g}')
        elif kind == 'CANCEL':
            state.status = 'CANCELLED'
            self._log('取消任务', tid, '停止新发运；在途批次按原返回时刻返仓，不再交付')
        else:
            raise ValueError('未知事件类型')

    def inject(self, kind, **payload):
        if self.finished:
            raise ValueError('本次运行已结束，请重置后操作')
        event = dict(time=self.now, kind=kind, **payload)
        self._apply(event)
        self.manual_events.append(event)
        self._cycle('人工事件')

    def _cycle(self, reason):
        # 同刻事件先于交付；取消或恰好硬失效的货物不计送达。
        changed = False
        for event in self.events:
            if event['time'] <= self.now and event['event_id'] not in self.processed:
                self._apply(event)
                self.processed.add(event['event_id'])
                changed = True
        for state in self.tasks.values():
            t = state.spec
            if state.status in ('CANCELLED', 'EXPIRED', 'COMPLETED'):
                continue
            if t.expiry_s is not None and self.now >= t.expiry_s:
                state.status = 'EXPIRED'
                self._log('硬失效', t.task_id, '退出等待队列；在途批次返仓')
                changed = True
            elif self.now >= t.release_s and state.status == 'PENDING':
                state.status = 'WAITING'
                self._log('任务发布', t.task_id, '进入可调度集合')
                changed = True
        for d in self.drones:
            if d.task_id and not d.delivered and self.now >= d.arrival:
                state = self.tasks[d.task_id]
                if state.status not in ('CANCELLED', 'EXPIRED'):
                    state.spec = replace(state.spec, delivered_kg=state.spec.delivered_kg + d.amount)
                    state.status = 'COMPLETED' if state.spec.delivered_kg >= state.spec.quantity_kg else 'WAITING'
                    if state.status == 'COMPLETED':
                        state.completed_at = self.now
                    self._log('交付', d.task_id, f'{d.drone_id} 交付 {d.amount:g} kg，累计 {state.spec.delivered_kg:g} kg')
                else:
                    self._log('停止交付', d.task_id, f'{d.drone_id} 保留 {d.amount:g} kg 返仓')
                d.delivered = True
                changed = True
            if d.task_id and self.now >= d.available:
                self._log('返仓', d.task_id, f'{d.drone_id} 已返回，可领取新批次')
                d.task_id, d.amount = None, 0
                changed = True
        if self.now % 5 == 0 or changed or reason != '时钟推进':
            self._rank('事件触发' if changed else reason)
            if not self.finished:
                self._dispatch()

    def _rank(self, reason):
        ranked = rank_tasks(self._eligible(), self.strategy, self.now)
        self.queue = [t.task_id for t, _ in ranked]
        current = {}
        for rank, (t, s) in enumerate(ranked, 1):
            old = self.previous.get(t.task_id)
            current[t.task_id] = (rank, s.priority)
            self.history.append(dict(time=self.now, task_id=t.task_id, priority=s.priority,
                                     rank=rank, urgency=s.urgency, time_pressure=s.time_pressure,
                                     shortage=s.shortage, people_impact=s.people_impact, waiting=s.waiting,
                                     previous_rank=old[0] if old else None, reason=reason))
            if old and rank != old[0]:
                self._log('队列重排', t.task_id, f'第 {old[0]} → {rank}；P {old[1]:.2f} → {s.priority:.2f}；{reason}')
        self.previous = current

    def _dispatch(self):
        for d in self.drones:
            if d.task_id:
                continue
            for tid in list(self.queue):
                state = self.tasks[tid]
                t = state.spec
                arrival = self.now + t.estimated_service_s
                if t.expiry_s is not None and arrival >= t.expiry_s:
                    continue
                d.task_id, d.amount = tid, min(5, t.quantity_kg - t.delivered_kg)
                d.arrival, d.available = arrival, arrival + t.estimated_service_s
                d.delivered = False
                state.status = 'ACTIVE'
                if state.first_dispatch is None:
                    state.first_dispatch = self.now
                self.queue.remove(tid)
                self._log('派送', tid, f'{d.drone_id} 装载 {d.amount:g} kg；预计 {arrival} 秒交付、{d.available} 秒返仓')
                break

    def advance(self, seconds=5):
        if type(seconds) is not int or seconds < 0:
            raise ValueError('推进秒数必须为非负整数')
        for _ in range(min(seconds, self.t_end - self.now)):
            for t in self._eligible():
                state = self.tasks[t.task_id]
                state.spec = replace(t, wait_s=t.wait_s + 1)
            self.now += 1
            self._cycle('时钟推进')

    def rows(self):
        rows = []
        ranks = {tid: i for i, tid in enumerate(self.queue, 1)}
        labels = {'PENDING': '未发布', 'WAITING': '等待', 'ACTIVE': '配送中',
                  'COMPLETED': '已完成', 'CANCELLED': '已取消', 'EXPIRED': '已失效'}
        for state in self.tasks.values():
            t = state.spec
            s = score_task(t, self.now) if state.status not in ('CANCELLED', 'EXPIRED', 'COMPLETED') else None
            latest = next((h for h in reversed(self.history) if h['task_id'] == t.task_id), None)
            rows.append({'任务': t.task_id, '物资': t.cargo_type, '状态': labels[state.status],
                         '等级': f'E{t.level}', '当前排名': ranks.get(t.task_id),
                         '上次评分排名': latest['previous_rank'] if latest else None,
                         'P参考分': round(s.priority, 2) if s else None,
                         '等待秒数': t.wait_s, '需求kg': t.quantity_kg, '已送达kg': t.delivered_kg,
                         '在途kg': self.in_transit(t.task_id), '软截止秒': t.deadline_s,
                         '硬失效秒': t.expiry_s,
                         '说明': '预计交付不早于硬失效，暂缓' if t.task_id in ranks and t.expiry_s is not None and self.now+t.estimated_service_s >= t.expiry_s else ''})
        return sorted(rows, key=lambda r: (r['当前排名'] is None, r['当前排名'] or 0, r['任务']))

    def metrics(self):
        released = [s for s in self.tasks.values() if s.spec.release_s <= self.now]
        completed = [s for s in released if s.status == 'COMPLETED']
        emergency = [s.first_dispatch-s.spec.release_s for s in released if s.spec.level == 2 and s.first_dispatch is not None]
        return {'策略': self.strategy, '已发布任务': len(released), '完成任务': len(completed),
                '完成率': len(completed)/len(released) if released else 0,
                '准时完成率': sum(s.completed_at <= s.spec.deadline_s for s in completed)/len(released) if released else 0,
                '急救平均首次派送等待秒': sum(emergency)/len(emergency) if emergency else None,
                '急救未派送数': sum(s.spec.level == 2 and s.first_dispatch is None for s in released),
                '普通任务最长累计等待秒': max((s.spec.wait_s for s in released if s.spec.level == 0), default=0),
                '未满足需求kg': sum(s.spec.quantity_kg-s.spec.delivered_kg for s in released if s.status != 'CANCELLED'),
                '失效任务': sum(s.status == 'EXPIRED' for s in released)}

    def export(self):
        return dict(schema_version=2, strategy=self.strategy, now=self.now, t_end=self.t_end,
                    drone_count=len(self.drones), initial_tasks=self.initial_tasks,
                    preset_events=self.events, manual_events=self.manual_events,
                    tasks=[dict(**asdict(s)) for s in self.tasks.values()],
                    drones=[asdict(d) for d in self.drones], history=self.history,
                    logs=self.logs, metrics=self.metrics())


def compare(name, seed, count, drones, t_end):
    rows = []
    for strategy in STRATEGIES:
        tasks, events = make_scenario(name, seed, count)
        sim = Simulation(tasks, events, strategy, drones, t_end)
        sim.advance(t_end)
        rows.append(sim.metrics())
    return rows
