"""应急智航：四进口双向航路交叉口演示。"""
import json
from html import escape
from math import ceil

import streamlit as st

from crossing import APPROACHES, Crossing

COLORS = ["#38bdf8", "#fbbf24", "#fb7185"]


_SCENE = st.components.v2.component(
    "clickable_traffic_scene",
    html="""<div id="scene" aria-live="polite"></div>""",
    css="""
#scene svg { width:100%; height:auto; display:block; border-radius:16px; }
[data-flight] { cursor:pointer; transition:filter .15s ease, opacity .15s ease; }
[data-flight]:hover { filter:drop-shadow(0 0 8px var(--st-primary-color)); }
[data-flight]:focus { outline:none; filter:drop-shadow(0 0 10px #fff); }
""",
    js="""
export default function(component) {
  const {data, parentElement, setTriggerValue} = component
  const root = parentElement.querySelector('#scene')
  if (!root) return
  if (root.innerHTML !== data.svg) root.innerHTML = data.svg
  root.querySelectorAll('[data-flight]').forEach(node => {
    node.onclick = () => setTriggerValue('selected', `${node.dataset.flight}|${Date.now()}`)
    node.onkeydown = e => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault(); setTriggerValue('selected', `${node.dataset.flight}|${Date.now()}`)
      }
    }
  })
}
""",
)


def _position(f):
    """把一维进度映射到真实车道中心线和路口转弯曲线。"""
    cx, cy, scale = 500, 390, 1.05
    vectors = {"北": (0, -1), "东": (1, 0), "南": (0, 1), "西": (-1, 0)}

    def inbound_point(approach, distance, lane, merge=False):
        ox, oy = vectors[approach]
        # 全程双向两车道：每个行驶方向只有一条连续车道。
        lane_offset = 20
        left_x, left_y = oy, -ox
        return (cx+ox*distance+left_x*lane_offset,
                cy+oy*distance+left_y*lane_offset)

    def outbound_point(approach, distance):
        ox, oy = vectors[approach]
        right_x, right_y = -oy, ox
        return cx+ox*distance+right_x*22, cy+oy*distance+right_y*22

    if f.contraflow:
        # 极端应急在进口段切入对向（出口）车道，再穿越路口回到目标出口。
        if f.position < -80:
            return outbound_point(f.approach, -f.position*scale)
        borrowed = outbound_point(f.approach, 80*scale)
        exit_lane = outbound_point(Crossing.exit_approach(f), 80*scale)
        if f.position <= 80:
            t = (f.position+80)/160
            return (borrowed[0]+(exit_lane[0]-borrowed[0])*t,
                    borrowed[1]+(exit_lane[1]-borrowed[1])*t)
        return outbound_point(Crossing.exit_approach(f), f.position*scale)

    if f.position < -80:
        distance = -f.position*scale
        return inbound_point(f.approach, distance, f.lane)
    if f.position > 80:
        return outbound_point(Crossing.exit_approach(f), f.position*scale)

    start = inbound_point(f.approach, 80*scale, f.lane)
    end = outbound_point(Crossing.exit_approach(f), 80*scale)
    t = (f.position+80)/160
    if f.maneuver == "直行":
        return start[0]+(end[0]-start[0])*t, start[1]+(end[1]-start[1])*t
    # 三次贝塞尔让无人机沿右转小弯或左转大弯连续通过，不再切回路口中心线。
    aox, aoy = vectors[f.approach]
    eox, eoy = vectors[Crossing.exit_approach(f)]
    reach = 28 if f.maneuver == "右转" else 64
    c1 = (start[0]-aox*reach, start[1]-aoy*reach)
    c2 = (end[0]-eox*reach, end[1]-eoy*reach)
    u = 1-t
    return (u**3*start[0]+3*u*u*t*c1[0]+3*u*t*t*c2[0]+t**3*end[0],
            u**3*start[1]+3*u*u*t*c1[1]+3*u*t*t*c2[1]+t**3*end[1])


def _signal_heads(sim):
    positions = {"北": (585, 255), "东": (625, 485), "南": (335, 500), "西": (310, 270)}
    parts = []
    for approach, (x, y) in positions.items():
        active = approach in sim.green_approaches
        left = straight = right = "#22c55e" if active else "#ef4444"
        parts.append(f'''<g transform="translate({x},{y})">
<rect x="-38" y="-23" width="76" height="46" rx="8" fill="#09111f" stroke="#64748b"/>
<text x="0" y="-30" fill="#dbeafe" font-size="12" text-anchor="middle">{approach}进口信号</text>
<circle cx="-24" cy="-5" r="7" fill="{left}"/><circle cx="0" cy="-5" r="7" fill="{straight}"/><circle cx="24" cy="-5" r="7" fill="{right}"/>
<text x="-24" y="17" fill="#cbd5e1" font-size="10" text-anchor="middle">左</text><text x="0" y="17" fill="#cbd5e1" font-size="10" text-anchor="middle">直</text><text x="24" y="17" fill="#cbd5e1" font-size="10" text-anchor="middle">右</text></g>''')
    return "".join(parts)


def _remaining_label(seconds):
    """把任务剩余时间格式化为适合场景标牌的 ±MM:SS。"""
    sign = "-" if seconds < 0 else ""
    whole = ceil(abs(seconds))
    minutes, secs = divmod(whole, 60)
    return f"{sign}{minutes:02}:{secs:02}"


def scene(sim, selected=None):
    phase_color = "#ef4444" if sim.all_red else "#22c55e"
    parts = [f'''<svg viewBox="0 0 1000 780" role="img" aria-label="四进口双向航路与无人机实时位置" xmlns="http://www.w3.org/2000/svg" style="background:#0b1426;font-family:Microsoft YaHei,sans-serif">
<defs><pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse"><path d="M40 0H0V40" fill="none" stroke="#18263c"/></pattern></defs>
<rect width="1000" height="780" fill="url(#grid)"/>
<!-- 路段双向、每方向一车道 -->
<path d="M65 390H935 M500 55V725" stroke="#263c56" stroke-width="78"/>
<path d="M65 390H935 M500 55V725" stroke="#9ab0cb" stroke-width="2" stroke-dasharray="13 10"/>
<rect x="461" y="351" width="78" height="78" fill="#1c3048" stroke="#f59e0b" stroke-dasharray="6 5"/>
<!-- 停止线 -->
<g stroke="#f8fafc" stroke-width="5"><path d="M461 306H500 M500 474H539 M584 351V390 M416 390V429"/></g>
<g fill="#a9bbd6" font-size="15">
  <text x="28" y="34">全程双向两车道：每个方向 1 条连续车道，路口不展宽</text>
  <text x="475" y="75">北进口</text><text x="475" y="715">南进口</text>
  <text x="78" y="375">西进口</text><text x="855" y="375">东进口</text>
</g>
{_signal_heads(sim)}
<circle cx="500" cy="390" r="9" fill="{phase_color}"/><text x="516" y="396" fill="{phase_color}" font-size="14">{escape(sim.signal_status)}</text>''']
    for f in sim.flights:
        if f.completed is not None:
            continue
        x, y = _position(f)
        color = COLORS[f.level]
        status_name = ("常态", "紧急", "极端")[f.level]
        remaining = _remaining_label(f.deadline-sim.now)
        active = f.id in sim.owners
        ring = "#c084fc" if f.contraflow and active else "#4ade80" if active else "#ffffff" if f.id == selected else "none"
        label = escape(f"{f.id} T{f.task_level} E{f.level} {f.approach}进口 {f.maneuver} {sim.status(f)}")
        # 靠近右边界时把信息牌放到左侧，避免文字被 SVG 裁切。
        badge_x = -140 if x > 820 else 28
        parts.append(f'''<g data-flight="{f.id}" tabindex="0" role="button" aria-label="选择 {label}" transform="translate({x:.1f},{y:.1f})">
<title>{label}，点击调整状态</title><circle r="22" fill="#0b1426" fill-opacity=".65" stroke="{ring}" stroke-width="3"/>
<path d="M-9-9L9 9M-9 9L9-9" stroke="{color}" stroke-width="3"/><circle r="6" fill="{color}"/>
<g fill="{color}" stroke="{color}"><circle cx="-9" cy="-9" r="3"/><circle cx="9" cy="9" r="3"/><circle cx="-9" cy="9" r="3"/><circle cx="9" cy="-9" r="3"/></g>
<rect x="{badge_x}" y="-25" width="112" height="50" rx="7" fill="#07101f" fill-opacity=".9" stroke="{color}" stroke-width="1.5"/>
<text x="{badge_x+7}" y="-7" fill="#f8fafc" font-size="12">{f.id} · T{f.task_level} · E{f.level} {status_name}</text>
<text x="{badge_x+7}" y="13" fill="{color}" font-size="13" font-weight="700">剩余 {remaining}</text></g>''')
    parts.append('''<g font-size="14"><text x="25" y="754" fill="#38bdf8">● E0 常态</text><text x="145" y="754" fill="#fbbf24">● E1 紧急</text><text x="265" y="754" fill="#fb7185">● E2 极端紧急</text><text x="430" y="754" fill="#4ade80">◎ 正在放行</text><text x="565" y="754" fill="#c084fc">◎ 借道逆行</text><text x="700" y="754" fill="#f8fafc">白环：当前选中</text></g></svg>''')
    return "".join(parts)


def _scene_selection_changed():
    state = st.session_state.get("traffic_scene")
    selected = getattr(state, "selected", None)
    if selected is None and isinstance(state, dict):
        selected = state.get("selected")
    if selected:
        selected = str(selected).split("|", 1)[0]
    sim = st.session_state.get("crossing")
    if sim and selected and (flight := sim.get(selected)) and flight.completed is None:
        st.session_state.edit_flight = selected
        st.session_state.playing = False
        st.rerun(scope="app")


def main():
    st.set_page_config(page_title="应急智航 · 双向路口", page_icon="🚁", layout="wide")
    st.title("应急智航 · 双向交叉口优先通行")
    st.caption("全程双向两车道 · 四进口依次放行 · 紧急协调与极端应急借道")
    if ("crossing" not in st.session_state or
            getattr(st.session_state.crossing, "model_version", 0) != Crossing.MODEL_VERSION or
            not getattr(st.session_state.crossing, "continuous", False)):
        st.session_state.crossing = Crossing(continuous=True)
    st.session_state.setdefault("playing", False)
    sim = st.session_state.crossing

    st.sidebar.title("演示控制")
    st.sidebar.caption("持续流量：每 5 秒生成一批；T1–T5 概率递减，限时服从 μ=20、σ=10 分钟的正态分布且不低于 3 分钟")
    strategy = st.sidebar.selectbox("通行策略", ["动态优先", "先到先行"], key="cross_strategy")
    speed = st.sidebar.select_slider("播放倍速", [1, 2, 5], value=1)
    spawn_batch_size = st.sidebar.slider("每批生成数量", 1, 4,
                                          value=getattr(sim, "spawn_batch_size", 1),
                                          key="spawn_batch_size")
    sim.spawn_batch_size = max(1, min(4, int(spawn_batch_size)))
    pending = strategy != sim.strategy
    if pending:
        st.session_state.playing = False
        st.sidebar.warning("策略已修改，重置后应用。")
    if st.sidebar.button("重置场景", key="cross_reset", width="stretch"):
        st.session_state.crossing = Crossing(strategy, continuous=True,
                                             spawn_batch_size=spawn_batch_size)
        st.session_state.playing = False
        st.session_state.pop("adjustment", None)
        st.session_state.edit_flight = "D01"
        st.rerun()
    a, b = st.sidebar.columns(2)
    if a.button("开始", key="cross_start", disabled=pending or sim.finished or st.session_state.playing):
        st.session_state.playing = True
        st.rerun()
    if b.button("暂停", key="cross_pause", disabled=not st.session_state.playing):
        st.session_state.playing = False
        st.rerun()
    if a.button("单步 1 秒", key="cross_step", disabled=pending or sim.finished or st.session_state.playing):
        sim.advance(1)
        st.rerun()
    if b.button("推进 10 秒", key="cross_jump", disabled=pending or sim.finished or st.session_state.playing):
        sim.advance(10)
        st.rerun()

    st.sidebar.divider()
    st.sidebar.subheader("调整无人机状态")
    st.sidebar.caption("可直接点击场景中的无人机选定；点击会自动暂停播放。")
    selectable = [f for f in sim.flights if f.completed is None]
    if selectable:
        options = [f.id for f in selectable]
        if st.session_state.get("edit_flight") not in options:
            st.session_state.edit_flight = options[0]
        target_id = st.sidebar.selectbox("选择无人机", options, key="edit_flight",
                                         disabled=st.session_state.playing)
        flight = sim.get(target_id)
        version = f"{target_id}_{sim.now}_{len(sim.logs)}"
        with st.sidebar.form(f"edit_{version}"):
            task_level = st.selectbox("任务等级", list(Crossing.TASK_LEVELS),
                                      index=flight.task_level-1,
                                      format_func=lambda x: f"T{x}",
                                      key=f"task_level_{version}")
            remaining_minutes = st.number_input("剩余限时（分钟，可为负）",
                                        value=float((flight.deadline-sim.now)/60), step=1.0,
                                        key=f"remaining_{version}")
            waiting = st.number_input("累计等待（秒）", min_value=0.0, value=float(flight.wait), step=5.0,
                                      key=f"wait_{version}")
            held = st.checkbox("暂停该机", value=flight.held, key=f"held_{version}")
            if st.form_submit_button("应用状态并重新评分", disabled=pending or st.session_state.playing or flight.granted is not None):
                st.session_state.adjustment = sim.adjust(
                    target_id, task_level, remaining_minutes*60, waiting, held)
                st.rerun()
        urgent, extreme = sim.emergency_thresholds(flight.task_level)
        st.sidebar.caption(
            f"当前：T{flight.task_level} · E{flight.level} · 剩余 {(flight.deadline-sim.now)/60:.1f} 分钟 · "
            f"紧急 <{urgent/60:g} 分钟 · 极端紧急 <{extreme/60:g} 分钟")
        st.sidebar.caption(f"航路：{flight.approach}进口 · {flight.maneuver} · 单一进口车道")
        if flight.granted is not None:
            st.sidebar.info("该机已经放行，可选中查看，但不能再修改任务状态。")
    if "adjustment" in st.session_state:
        st.sidebar.success(st.session_state.adjustment)

    with st.expander("放行规则", expanded=False):
        st.markdown("""
1. **无紧急任务**：北、东、南、西四个进口依次获得绿灯；每个方向只有一条进口车道，同一批最多连续放行 3 架。
2. **E1 紧急**：不改变北、东、南、西轮转相位；轮到该进口时从队首连续放行，直至同方向最后一架紧急无人机通过，期间延长本相位且不插入清空间隔。
3. **E2 极端紧急**：无条件最高优先并立即触发全红。本向前方为空时直接沿本向放行；前方受阻时清空对向车道后连续借道，最后一架清空后恢复正常灯控。
4. **多架紧急**：无冲突路径组成同一放行批次；有冲突时按等级、动态分、截止时间和编号依次放行。
5. **动态紧急度**：每架无人机随机获得 T1–T5 任务等级和任务限时。T1 在剩余限时小于 10 分钟时变为 E1、小于 5 分钟时变为 E2；Tn 的两个阈值分别为 `10 + 2×(n−1)` 分钟和 `5 + (n−1)` 分钟。
6. **随机生成**：任务等级概率依次为 T1 40%、T2 25%、T3 18%、T4 11%、T5 6%；初始剩余时间服从均值 20 分钟、标准差 10 分钟的正态分布，小于 3 分钟时按 3 分钟计。
7. **持续流量**：每 5 秒在入口空间允许时随机生成无人机；系统持续按剩余限时自动更新 E0/E1/E2，并立即采用相应放行规则。
""")

    @st.fragment(run_every=.2 if st.session_state.playing else None)
    def dashboard():
        if st.session_state.playing:
            sim.advance(.2*speed)
        if sim.finished and st.session_state.playing:
            st.session_state.playing = False
            st.rerun()
        cols = st.columns(5)
        cols[0].metric("仿真时间", f"{sim.now:.1f} s")
        cols[1].metric("信号状态", sim.signal_status)
        cols[2].metric("正在放行", "、".join(sim.owners) or "暂无")
        cols[3].metric("等待通行", f"{sum(f.granted is None for f in sim.flights)} 架")
        cols[4].metric("生成 / 完成", f"{sim.generated} / {sim.total_completed}")
        averages = sim.average_crossing_times()
        st.caption("分优先级平均通过路口耗时（从到达等待线到清空路口，包含信号等待）")
        average_cols = st.columns(3)
        for level, col in enumerate(average_cols):
            value = "暂无" if averages[level] is None else f"{averages[level]:.1f} s"
            col.metric(f"E{level} 平均耗时", value,
                       help=f"已完成穿越样本 {sim.crossing_time_count[level]} 架")
        left, right = st.columns([1.7, 1])
        with left:
            _SCENE(data={"svg": scene(sim, st.session_state.get("edit_flight"))}, key="traffic_scene",
                   on_selected_change=_scene_selection_changed, height=640)
        with right:
            st.subheader("当前通行决策")
            st.info(sim.gate())
            candidates = sim.candidates()
            if candidates:
                st.dataframe([{"候选": f.id, "进口": f.approach, "转向": f.maneuver,
                               "车道": f.lane, "任务等级": f"T{f.task_level}",
                               "紧急状态": f"E{f.level}",
                               "剩余 min": round((f.deadline-sim.now)/60, 1),
                               "分数": round(sim.score(f), 1)}
                              for f in candidates], hide_index=True, width="stretch")
            st.subheader("最近事件")
            for log in sim.logs[-5:][::-1]:
                st.markdown(f"**{log['时间']:.1f}s · {log['对象']} · {log['事件']}**")
                st.caption(log["说明"])
        st.subheader("实时评分与车辆状态")
        tabs = st.tabs(["评分排行", "全部状态", "决策日志"])
        with tabs[0]:
            st.dataframe(sim.ranking_rows(), hide_index=True, width="stretch")
        with tabs[1]:
            st.dataframe(sim.rows(), hide_index=True, width="stretch")
        with tabs[2]:
            st.dataframe(sim.logs, hide_index=True, width="stretch")
        st.download_button("下载本次运行 JSON", json.dumps(sim.export(), ensure_ascii=False, indent=2),
                           "crossing_run.json", "application/json", on_click="ignore")
    dashboard()


if __name__ == "__main__":
    main()
