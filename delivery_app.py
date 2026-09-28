"""应急智航动态优先级交互入口。"""
import json
from dataclasses import asdict
import pandas as pd
import streamlit as st
from priority import PriorityTask
from simulation import SCENARIOS, STRATEGIES, Simulation, compare, make_scenario


def create_run(config):
    tasks, events = make_scenario(config['scenario'], config['seed'], config['count'])
    return Simulation(tasks, events, config['strategy'], config['drones'], config['t_end'])


def main():
    st.set_page_config(page_title='应急智航 · 动态优先级', page_icon='🚁', layout='wide')
    st.title('应急智航 · 动态优先级调整')
    st.caption('观察任务为何升分、队列如何重排，以及调整对配送顺序的影响。')
    st.sidebar.title('实验配置')
    scenario = st.sidebar.selectbox('场景', list(SCENARIOS), index=1, key='scenario')
    st.sidebar.caption(SCENARIOS[scenario])
    strategy = st.sidebar.selectbox('排序策略', list(STRATEGIES), index=2,
                                    format_func=lambda s: f'{s} · {STRATEGIES[s]}', key='strategy')
    drones = st.sidebar.number_input('无人机数量', 1, 20, 2, key='drones')
    count = st.sidebar.number_input('背景任务数', 4, 30, 12, key='count')
    seed = st.sidebar.number_input('随机种子', 0, 999, 42, key='seed')
    t_end = st.sidebar.number_input('结束时间（秒）', 300, 3600, 900, step=60, key='t_end')
    config = dict(scenario=scenario, strategy=strategy, drones=drones, count=count, seed=seed, t_end=t_end)
    if 'sim' not in st.session_state:
        st.session_state.sim = create_run(config)
        st.session_state.loaded = config.copy()
        st.session_state.running = False
    pending = config != st.session_state.loaded
    if pending:
        st.session_state.running = False
        st.sidebar.warning('参数已修改。点击加载并重置后生效，当前结果仍属于原配置。')
    if st.sidebar.button('加载并重置', key='reset', type='primary', width='stretch'):
        st.session_state.sim = create_run(config)
        st.session_state.loaded = config.copy()
        st.session_state.running = False
        st.session_state.pop('comparison', None)
        st.rerun()
    sim = st.session_state.sim
    controls = st.sidebar.columns(2)
    if controls[0].button('开始', key='start', disabled=pending or sim.finished or st.session_state.running):
        st.session_state.running = True
        st.rerun()
    if controls[1].button('暂停', key='pause', disabled=not st.session_state.running):
        st.session_state.running = False
        st.rerun()
    if controls[0].button('单步 5 秒', key='step', disabled=pending or sim.finished or st.session_state.running):
        sim.advance(5)
    if controls[1].button('推进 60 秒', key='jump', disabled=pending or sim.finished or st.session_state.running):
        sim.advance(60)
    st.sidebar.caption('自动运行每秒推进 5 个仿真秒；每 5 秒及事件发生时重新评分。')
    st.sidebar.info('每批最多运 5 kg；配送后按相同耗时返仓。未模拟航路冲突、电量或真实飞控。')
    with st.expander('动态评分规则'):
        st.latex(r'B=clip(0.30U+0.25T+0.20S+0.15N+0.10A),\quad P=35E+30B')
        st.write('E：紧急等级；U：严重度；T：截止时间压力；S：未满足比例；N：受影响人数；A：等待补偿。分项均归一化至 0～1。')
        st.caption('E0：0～30；E1：35～65；E2：70～100。迟到单独统计，不再扣分。G0/G1 中 P 仅作参考。执行中的批次不抢占。')
    loaded = st.session_state.loaded
    st.write(f"当前运行：{loaded['scenario']} · {STRATEGIES[sim.strategy]} · seed={loaded['seed']}")

    @st.fragment(run_every=1.0 if st.session_state.running else None)
    def dashboard():
        if st.session_state.running and not sim.finished:
            sim.advance(5)
        if sim.finished and st.session_state.running:
            st.session_state.running = False
            st.rerun()
        cols = st.columns(4)
        m = sim.metrics()
        cols[0].metric('仿真时间', f'{sim.now} / {sim.t_end} 秒')
        cols[1].metric('已完成任务', f"{m['完成任务']} / {m['已发布任务']}")
        cols[2].metric('等待任务', len(sim.queue))
        cols[3].metric('准时完成率', f"{m['准时完成率']:.1%}")
        if sim.finished:
            st.success('本次运行已到结束时间。可下载记录或重置，未完成任务已保留。')
        st.subheader('实时任务与等待队列')
        st.dataframe(sim.rows(), hide_index=True, width='stretch')
        st.caption('排名仅针对等待队列；上次评分排名为上一次参与评分的名次。P参考分按当前状态显示，派机使用最近一次评分队列。')
        st.subheader('无人机执行状态')
        st.dataframe([{'无人机': d.drone_id, '状态': '空闲' if not d.task_id else '返仓中' if d.delivered else '配送中',
                       '任务': d.task_id or '—', '批次kg': d.amount,
                       '预计交付秒': d.arrival if d.task_id else None,
                       '预计返仓秒': d.available if d.task_id else None} for d in sim.drones], hide_index=True)
        st.subheader('等待任务优先级变化')
        if sim.history:
            frame = pd.DataFrame(sim.history)
            chart = frame.pivot_table(index='time', columns='task_id', values='priority', aggfunc='last')
            st.line_chart(chart, x_label='仿真时间（秒）', y_label='动态参考分 P')
            with st.expander('评分分项与排名记录'):
                st.dataframe(frame.tail(300), hide_index=True)
        st.subheader('事件与调整记录')
        st.dataframe(pd.DataFrame(sim.logs[-100:][::-1]), hide_index=True, width='stretch')
        st.download_button('下载完整运行记录 JSON', json.dumps(sim.export(), ensure_ascii=False, indent=2),
                           'priority_run.json', 'application/json', key='download_run')
        if sim.history:
            st.download_button('下载评分历史 CSV', pd.DataFrame(sim.history).to_csv(index=False).encode('utf-8-sig'),
                               'priority_history.csv', 'text/csv', key='download_history')
    dashboard()

    st.subheader('人工突发事件')
    st.caption('先暂停再操作；事件在当前仿真时刻生效并立即触发重排。')
    disabled = pending or sim.finished or st.session_state.running
    with st.form('new_task'):
        st.write('新增急救任务')
        c = st.columns(3)
        amount = c[0].number_input('急救需求 kg', 1, 20, 2)
        deadline = c[1].number_input('距软截止秒数', 30, 600, 180)
        people = c[2].number_input('受影响人数', 0, 5000, 80)
        if st.form_submit_button('新增急救', disabled=disabled):
            index = 1
            while f'MAN{index:03}' in sim.tasks:
                index += 1
            task = PriorityTask(f'MAN{index:03}', '急救药品', sim.now, sim.now+deadline,
                                sim.now+deadline+240, 2, 5, amount, people, estimated_service_s=50)
            sim.inject('ADD', payload=asdict(task))
            st.rerun()
    available = [tid for tid, s in sim.tasks.items() if s.status in ('WAITING', 'ACTIVE')]
    if available:
        with st.form('change_task'):
            tid = st.selectbox('目标任务', available)
            kind = st.selectbox('操作', ['追加需求', '提升为急救', '取消任务'])
            extra = st.number_input('追加数量 kg', 1, 20, 5)
            if st.form_submit_button('应用事件', disabled=disabled):
                if kind == '追加需求':
                    sim.inject('DEMAND', task_id=tid, amount=extra)
                elif kind == '提升为急救':
                    sim.inject('ESCALATE', task_id=tid, level=2, severity=5)
                else:
                    sim.inject('CANCEL', task_id=tid)
                st.rerun()
    st.subheader('同输入策略对照')
    st.caption('从已加载预设重新运行 G0/G1/G2，任务、种子、机队和时长相同；不包含人工注入事件。单次结果不能证明策略普遍更优。')
    if st.button('运行三策略对照', disabled=st.session_state.running or pending, key='compare'):
        with st.spinner('计算三组完整运行结果…'):
            st.session_state.comparison = compare(loaded['scenario'], loaded['seed'], loaded['count'], loaded['drones'], loaded['t_end'])
    if 'comparison' in st.session_state:
        frame = pd.DataFrame(st.session_state.comparison)
        st.dataframe(frame, hide_index=True)
        st.download_button('下载对照结果 CSV', frame.to_csv(index=False).encode('utf-8-sig'), 'comparison.csv', 'text/csv')


if __name__ == '__main__':
    main()

