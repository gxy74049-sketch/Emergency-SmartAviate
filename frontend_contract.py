"""前后端边界：请求描述选择意图，不冒充 materialize 后的完整 Scenario。"""
from copy import deepcopy
from typing import Protocol
from uuid import uuid4
from scenario_catalog import SCENARIOS, STRATEGIES


class ScenarioBackend(Protocol):
    def load_preset(self, scenario_id: str) -> dict: ...
    def materialize(self, config: dict, seed: int) -> dict: ...
    def validate(self, scenario: dict) -> None: ...
    # 实现方先校验并创建新引擎，成功后原子替换旧 run；失败保留旧状态。
    def dispatch(self, command: dict) -> None: ...
    def get_snapshot(self) -> dict: ...


def validate_selection(selection):
    base = selection['base_scenario_id']
    if base not in SCENARIOS or selection['strategy'] not in STRATEGIES:
        raise ValueError('未知场景或策略')
    if selection['scenario_id'] not in (base, 'CUSTOM'):
        raise ValueError('场景与来源不匹配')
    p = selection['parameters']
    for key, low, high in (('drone_count', 1, None), ('seed', 0, 999), ('t_end', 300, 3600), ('background_tasks', 0, 30)):
        if type(p[key]) is not int or p[key] < low or (high is not None and p[key] > high):
            raise ValueError(f'{key} 必须为不小于 {low} 的整数' if high is None else f'{key} 超出范围 {low}～{high}')
    item = SCENARIOS[base]
    total = p['background_tasks'] + item.fixed
    if not 1 <= total <= 30:
        if not (base == 'S09' and selection['scenario_id'] == 'S09' and p['background_tasks'] == 30 and p['drone_count'] == 6):
            raise ValueError('自定义总任务数必须为 1～30；S09 锁定预设例外')
    if base in ('S08', 'S09') and selection['scenario_id'] != 'CUSTOM':
        if p['background_tasks'] != item.background or p['drone_count'] != item.drones:
            raise ValueError('此预设任务与机队参数锁定，请复制为自定义')


def build_load_request(selection):
    validate_selection(selection)
    return {'command_id': str(uuid4()), 'command_type': 'LOAD_SCENARIO',
            'payload': {'run_id': str(uuid4()), 'selection': deepcopy(selection)}}
