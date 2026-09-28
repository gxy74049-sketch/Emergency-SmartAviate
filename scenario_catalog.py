"""前端展示目录：仅摘录方案元数据，不读取或替代预设配置包。"""
from dataclasses import dataclass


@dataclass(frozen=True)
class ScenarioOption:
    name: str
    drones: int
    background: int
    fixed: int
    description: str
    events: tuple[str, ...] = ()
    map_note: str = '标准 8 节点、12 航段，物理高度 L1 / L2 / L3'
    initial: str = '仓库待命，初始电量 100'
    focus: str = '任务排序与完整运输'


SCENARIOS = {
    'S01': ScenarioOption('常规物资配送', 4, 20, 0, '任务每 30 秒发布，无突发事件。'),
    'S02': ScenarioOption('中途新增急救', 4, 20, 1, '20 个非急救背景任务与 1 个固定急救任务。', ('300 秒：发布 EM01，W→F，2 kg，E=2，截止 480 秒、失效 660 秒',), focus='急救重排与未装载改派'),
    'S03': ScenarioOption('交叉口集中通行', 6, 18, 0, '任务按 0 / 10 / 20 秒三批发布，目的地 D 或 F。', map_note='关闭 B-D、C-E，X 为必经点；物理高度 L1 / L2 / L3', focus='预约排队及有利条件下换层'),
    'S04': ScenarioOption('航路临时中断', 4, 20, 0, '航路关闭允许在途飞机驶离。', ('400 秒：关闭 A-X', '700 秒：恢复 A-X'), focus='撤销未来预约、绕行或安全等待'),
    'S05': ScenarioOption('无人机失联', 4, 20, 0, '保留失联占用，确认移除后才能补发。', ('450 秒：D02 失联', '600 秒：确认移除，所载货物确认丢失'), focus='失联封锁与货物守恒'),
    'S06': ScenarioOption('上层临时禁用', 6, 18, 0, '18 项集中任务，地图同 S03。', ('80 秒：X 关联航段仅保留 L1', '200 秒：恢复三层'), map_note='关闭 B-D、C-E；X 关联航段有临时层限制', focus='算法可用层与物理允许层取交集'),
    'S07': ScenarioOption('低电量派机筛选', 4, 12, 0, '换电位独立于装卸位。', initial='D01 电量 20，其他无人机电量 100，均位于仓库', focus='配送与返航储备筛选、120 秒换电'),
    'S08': ScenarioOption('部分送达与取消失效', 4, 0, 4, '固定状态测试；任务与机队参数锁定。', ('30 秒：取消 PART01 未交付部分；SOFT01 软截止', '40 秒：EXP01 硬失效（截止 20 秒）'), initial='4 架；PART01 需求 8 kg，初始已交付 5 kg', focus='剩余 3 kg、取消返仓、软截止与硬失效'),
    'S09': ScenarioOption('高负载综合压力', 6, 30, 1, '背景任务每 5 秒发布，31 项压力预设保持锁定。', ('120 秒：新增急救', '180 秒：关闭 A-X', '240 秒：D03 失联', '420 秒：确认移除', '480 秒：恢复航路'), focus='急救时延、普通长等待与未完成量'),
}
STRATEGIES = ('G0', 'G1', 'G2', 'G3', 'G4', 'G5')
STRATEGY_EXPLANATIONS = {
    'G0': '先到先服务：按发布时间与任务编号排序。',
    'G1': '固定严重度优先：发布后不随等待时间改变。',
    'G2': '动态评分：单层飞行，仅等待冲突。',
    'G3': '动态评分：三层飞行，可等待或换层。',
    'G4': '完整动态策略：三层、等待、换层与绕行。',
    'G5': '动态评分：单层飞行，可等待或绕行。',
}


def default_parameters(scenario_id):
    item = SCENARIOS[scenario_id]
    return dict(background_tasks=item.background, drone_count=item.drones, seed=42, t_end=1800)
