"""任务优先级：实现《完整修订方案》5.1～5.4 的纯函数预览。"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, log
from random import Random
from typing import Optional


HORIZON_S = 300
PEOPLE_REFERENCE = 1000
DYNAMIC_STRATEGIES = frozenset(('G2', 'G3', 'G4', 'G5'))


@dataclass(frozen=True)
class PriorityTask:
    task_id: str
    cargo_type: str
    release_s: int
    deadline_s: int
    expiry_s: Optional[int]
    level: int
    severity: float
    quantity_kg: float
    people: int
    delivered_kg: float = 0
    wait_s: int = 0
    estimated_service_s: int = 120


@dataclass(frozen=True)
class PriorityScore:
    urgency: float
    time_pressure: float
    shortage: float
    people_impact: float
    waiting: float
    lateness: float
    benefit: float
    priority: float


def clip(value: float) -> float:
    return min(1.0, max(0.0, value))


def _validate_task(task: PriorityTask) -> None:
    if task.level not in (0, 1, 2):
        raise ValueError('level 必须为 0、1 或 2')
    if not isfinite(task.quantity_kg) or task.quantity_kg <= 0:
        raise ValueError('quantity_kg 必须为正的有限数')
    if task.people < 0:
        raise ValueError('people 不能为负数')
    if not isfinite(task.severity) or task.severity < 0:
        raise ValueError('severity 必须为非负有限数')
    if task.release_s > task.deadline_s:
        raise ValueError('release_s 不能晚于 deadline_s')
    if task.expiry_s is not None and task.deadline_s > task.expiry_s:
        raise ValueError('deadline_s 不能晚于 expiry_s')


def score_task(task: PriorityTask, now_s: int) -> Optional[PriorityScore]:
    """计算已发布且有效任务的 E/U/T/S/N/A/L、B 与 P；否则返回 None。"""
    _validate_task(task)
    if now_s < task.release_s or task.delivered_kg >= task.quantity_kg:
        return None
    if task.expiry_s is not None and now_s >= task.expiry_s:
        return None
    urgency = clip(task.severity / 5)
    slack = task.deadline_s - now_s - task.estimated_service_s
    time_pressure = clip(1 - slack / HORIZON_S)
    shortage = clip((task.quantity_kg - task.delivered_kg) / task.quantity_kg)
    people_impact = clip(log(1 + task.people) / log(1 + PEOPLE_REFERENCE))
    waiting = clip(task.wait_s / HORIZON_S)
    lateness = clip(max(0, now_s - task.deadline_s) / HORIZON_S)
    benefit = clip(
        0.30 * urgency + 0.25 * time_pressure + 0.20 * shortage
        + 0.15 * people_impact + 0.10 * waiting
    )
    return PriorityScore(
        urgency, time_pressure, shortage, people_impact, waiting, lateness,
        benefit, 35 * task.level + 30 * benefit,
    )


def rank_tasks(tasks: list[PriorityTask], strategy: str, now_s: int) -> list[tuple[PriorityTask, Optional[PriorityScore]]]:
    """按 G0～G5 的任务选择规则稳定排序，未发布或已失效任务不进入结果。"""
    if strategy not in ('G0', 'G1', 'G2', 'G3', 'G4', 'G5'):
        raise ValueError('未知策略')
    eligible = [(task, score_task(task, now_s)) for task in tasks]
    eligible = [(task, score) for task, score in eligible if score is not None]
    if strategy == 'G0':
        return sorted(eligible, key=lambda item: (item[0].release_s, item[0].task_id))
    if strategy == 'G1':
        return sorted(eligible, key=lambda item: (-item[0].severity, item[0].release_s, item[0].task_id))
    return sorted(eligible, key=lambda item: (-item[1].priority, item[0].deadline_s,
                                                item[0].release_s, item[0].task_id))


def rank_initial_tasks(tasks: list[PriorityTask], strategy: str) -> list[tuple[PriorityTask, PriorityScore]]:
    """按每个任务的发布时间计算初始分数，再套用对应策略的排序规则。"""
    if strategy not in ('G0', 'G1', 'G2', 'G3', 'G4', 'G5'):
        raise ValueError('未知策略')
    scored = [(task, score_task(task, task.release_s)) for task in tasks]
    eligible = [(task, score) for task, score in scored if score is not None]
    if strategy == 'G0':
        return sorted(eligible, key=lambda item: (item[0].release_s, item[0].task_id))
    if strategy == 'G1':
        return sorted(eligible, key=lambda item: (-item[0].severity, item[0].release_s, item[0].task_id))
    return sorted(eligible, key=lambda item: (-item[1].priority, item[0].deadline_s,
                                                item[0].release_s, item[0].task_id))


def _scenario_profile(scenario_id: str) -> tuple[int, tuple[int, ...], int]:
    """返回发布间隔、可选等级和截止缓冲；取自页面展示的场景设定。"""
    profiles = {
        'S01': (30, (0, 0, 1), 300), 'S02': (30, (0,), 300),
        'S03': (10, (0, 1), 220), 'S04': (30, (0, 1), 240),
        'S05': (30, (0, 1), 240), 'S06': (10, (0, 1), 220),
        'S07': (30, (0, 1), 260), 'S08': (30, (0, 1, 2), 180),
        'S09': (5, (0, 1, 2), 140),
    }
    return profiles[scenario_id]


def _severity_for_level(level: int, random: Random) -> tuple[str, float]:
    options = {
        0: (('普通食品', 3.0), ('帐篷', 2.0)),
        1: (('紧迫饮水', 4.0), ('常规药品', 3.5)),
        2: (('急救药品', 4.5), ('血液急救', 5.0)),
    }
    return random.choice(options[level])


def build_preview_tasks(scenario_id: str, parameters: dict) -> list[PriorityTask]:
    """由当前选择生成确定性输入任务，供前端在无仿真引擎时预览。"""
    interval, levels, deadline_buffer = _scenario_profile(scenario_id)
    random = Random(parameters['seed'])
    drones = parameters['drone_count']
    tasks: list[PriorityTask] = []
    for number in range(parameters['background_tasks']):
        level = random.choice(levels)
        cargo_type, severity = _severity_for_level(level, random)
        quantity = random.randint(1, 8)
        release_s = number * interval
        service_s = 90 + quantity * 8 + max(0, 6 - drones) * 20
        deadline_s = release_s + service_s + random.randint(deadline_buffer // 2, deadline_buffer)
        tasks.append(PriorityTask(
            f'BG{number + 1:02d}', cargo_type, release_s, deadline_s,
            deadline_s + 300 if cargo_type != '普通食品' else None, level, severity,
            quantity, random.randint(0, 600), estimated_service_s=service_s,
        ))
    fixed = {
        'S02': (('EM01', '急救药品', 300, 480, 660, 2, 4.5, 2, 80),),
        'S08': (
            ('PART01', '紧迫饮水', 0, 180, None, 1, 4.0, 8, 120),
            ('SOFT01', '普通食品', 0, 30, None, 0, 3.0, 3, 50),
            ('EXP01', '急救药品', 0, 20, 40, 2, 4.5, 2, 30),
            ('MED01', '常规药品', 0, 240, 540, 1, 3.5, 2, 70),
        ),
        'S09': (('EM01', '急救药品', 120, 480, 660, 2, 4.5, 2, 80),),
    }.get(scenario_id, ())
    for task_id, cargo, release, deadline, expiry, level, severity, quantity, people in fixed:
        service_s = 90 + quantity * 8 + max(0, 6 - drones) * 20
        delivered = 5 if scenario_id == 'S08' and task_id == 'PART01' else 0
        tasks.append(PriorityTask(task_id, cargo, release, deadline, expiry, level, severity,
                                  quantity, people, delivered_kg=delivered,
                                  estimated_service_s=service_s))
    return tasks
