"""仅生成前端待加载配置与命令，不访问文件包或引擎。"""
from copy import deepcopy
import streamlit as st
from scenario_catalog import SCENARIOS, STRATEGIES, STRATEGY_EXPLANATIONS, default_parameters
from frontend_contract import build_load_request


def _init_session_state():
    for key, value in {'scenario_choice': 'S01', 'custom_base': 'S01', 'last_preset': 'S01',
                       'draft': None, 'request_preview': None, 'last_error': None}.items():
        st.session_state.setdefault(key, value)


def _scenario_changed():
    choice = st.session_state['scenario_choice']
    if choice == 'CUSTOM':
        st.session_state['custom_base'] = st.session_state['last_preset']
        draft = st.session_state.get('draft')
        if draft:
            for key, value in draft['parameters'].items():
                st.session_state[f'edit_{key}'] = value
    else:
        st.session_state['last_preset'] = choice
        for key, value in default_parameters(choice).items():
            st.session_state[f'edit_{key}'] = value
    st.session_state['request_preview'] = None
    st.session_state['last_error'] = None


def render_scenario_sidebar():
    """返回本次点击产生的待接入命令；渲染或切换选择不创建 run_id。"""
    _init_session_state()
    st.sidebar.title('仿真场景配置')
    st.sidebar.caption('前端配置预览 · 预设包暂未接入')
    choice = st.sidebar.selectbox('场景', [*SCENARIOS, 'CUSTOM'], key='scenario_choice',
        format_func=lambda k: '自定义（复制当前场景）' if k == 'CUSTOM' else f'{k} {SCENARIOS[k].name}',
        on_change=_scenario_changed)
    base = st.session_state['custom_base'] if choice == 'CUSTOM' else choice
    item = SCENARIOS[base]
    if choice == 'CUSTOM':
        st.sidebar.caption(f'复制来源：{base} {item.name}')
    strategy = st.sidebar.selectbox(
        '算法策略组', STRATEGIES, index=4, key='strategy_choice',
        format_func=lambda code: f'{code} · {STRATEGY_EXPLANATIONS[code].split("：", 1)[0]}',
        help='策略独立于场景；切换策略不修改任务、事件或地图。',
    )
    st.sidebar.caption(f'已选 {strategy}：{STRATEGY_EXPLANATIONS[strategy]}')
    st.sidebar.subheader('基础设置')
    defaults = default_parameters(base)
    for key, value in defaults.items():
        st.session_state.setdefault(f'edit_{key}', value)
    locked = choice in ('S08', 'S09')
    if locked:
        st.sidebar.caption('任务与机队参数已锁定；需要修改时选择“自定义”。')
    p = {}
    for key, label, low, high in (
        ('background_tasks', '背景任务数量', 0, 30), ('drone_count', '无人机数量', 1, None),
        ('seed', '随机种子', 0, 999), ('t_end', '模拟时长（秒）', 300, 3600)):
        p[key] = int(st.sidebar.number_input(label, min_value=low, max_value=high, step=1,
                    key=f'edit_{key}', disabled=locked and key in ('background_tasks', 'drone_count')))
    st.sidebar.caption(f"背景 {p['background_tasks']} + 固定 {item.fixed} = 总计 {p['background_tasks'] + item.fixed} 项")
    selection = dict(schema_version=1, scenario_id=choice, base_scenario_id=base,
                     strategy=strategy, parameters=p)
    if selection != st.session_state.get('draft'):
        st.session_state['request_preview'] = None
        st.session_state['last_error'] = None
    st.session_state['draft'] = deepcopy(selection)
    modified = p != defaults
    st.sidebar.info(f"{item.name}{' · 自定义' if choice == 'CUSTOM' else ' · 已修改' if modified else ''} · 待加载")
    commands = []
    if st.sidebar.button('生成加载请求', type='primary', use_container_width=True,
                         help='仅预览“加载并重置”请求，不加载预设包或创建引擎。'):
        try:
            commands.append(build_load_request(selection))
        except ValueError as exc:
            st.session_state['last_error'] = str(exc)
    if st.session_state['last_error']:
        st.sidebar.error(st.session_state['last_error'])
    st.sidebar.caption('接入后启用运行控制')
    cols = st.sidebar.columns(2)
    cols[0].button('开始', disabled=True, use_container_width=True)
    cols[1].button('暂停', disabled=True, use_container_width=True)
    cols[0].button('单步', disabled=True, use_container_width=True)
    cols[1].button('重置', disabled=True, use_container_width=True)
    return commands
