import math
import time
import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Dict

import numpy as np
import matplotlib.pyplot as plt

import streamlit as st

# ---------------------------------------------------------------------
# RAVEN 3 · Rivian Autonomy & Visual Energy Nexus
#
# Deterministic “brain-on-a-table” demo for off-road autonomy:
# - Synthetic terrain segments (grade / roughness / edge / traction)
# - Drift & stability scoring
# - Human-gated actions (CRUISE / CAUTIOUS / CRAWL / STOP_SAFE)
# - Lightweight audit log (NDJSON)
#
# No ML. No cloud. No black box.
# Just math, rules, and transparency.
#
# This work was never meant to stay in a laptop.
# Transparent, accountable autonomy will take a team—
# people who understand why determinism, auditability,
# and human oversight aren't optional features but foundations.
#
# If you're reading this because you're evaluating the system:
# I believe in building clear, inspectable tools that earn trust.
# I'm ready to work with the people who believe the same.
# ---------------------------------------------------------------------

# ---------------------------------------------------------------------
# Streamlit page config & simple theming
# ---------------------------------------------------------------------
st.set_page_config(
    page_title="RAVEN 3 · Rivian Autonomy Kernel Demo",
    layout="wide",
)

RIVIAN_GREEN = "#0b2520"
RIVIAN_ACCENT = "#00e0a4"
RIVIAN_ORANGE = "#ffb454"
TEXT_MUTED = "#9ca3af"
BG = "#020714"

st.markdown(
    f"""
<style>
.stApp {{
  background: radial-gradient(circle at top, #06141a 0, {BG} 45%, #000000 100%);
  color: white;
  font-family: system-ui, -apple-system, BlinkMacSystemFont, "SF Pro Text", sans-serif;
}}
.title-main {{
  font-size: 1.5rem;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: {RIVIAN_ACCENT};
}}
.subtitle {{
  color: {TEXT_MUTED};
  font-size: 0.9rem;
  margin-bottom: 0.5rem;
}}
.metric-label {{
  font-size: 0.7rem;
  color: {TEXT_MUTED};
  text-transform: uppercase;
  letter-spacing: 0.08em;
}}
.metric-value {{
  font-size: 1.4rem;
  font-weight: 600;
}}
.pill {{
  display: inline-block;
  padding: 0.15rem 0.5rem;
  border-radius: 999px;
  background-color: #0f172a;
  color: {TEXT_MUTED};
  font-size: 0.7rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}}
</style>
""",
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------


@dataclass
class TerrainSegment:
    x: float
    y: float
    slope_deg: float        # signed grade in degrees
    roughness: float        # 0–1 (rocks, ruts)
    edge_exposure: float    # 0–1 (drop-off / cliff risk)
    traction_coeff: float   # 0–1 (mud / snow / ice)


@dataclass
class VehicleState:
    x: float
    y: float
    heading_deg: float
    speed_mps: float
    stability_index: float  # 0–100 (higher = better)
    drift_score: float      # 0–100 (higher = worse)
    grade_deg: float
    mode: str               # HOLD, CRUISE, CAUTIOUS, CRAWL, STOP_SAFE


@dataclass
class DecisionEvent:
    tick: int
    action: str
    reason: str
    grade_deg: float
    drift_score: float
    stability_index: float
    human_required: bool
    human_override: str  # PENDING, APPROVED, DENIED, AUTO
    timestamp: float


# ---------------------------------------------------------------------
# Audit logging
# ---------------------------------------------------------------------
RUNS_DIR = Path("runs_raven3")
RUNS_DIR.mkdir(parents=True, exist_ok=True)


def current_run_id() -> str:
    if "raven_run_id" not in st.session_state:
        st.session_state.raven_run_id = time.strftime("%Y%m%dT%H%M%S")
    return st.session_state.raven_run_id


def append_audit_record(record: Dict) -> None:
    run_id = current_run_id()
    fpath = RUNS_DIR / f"{run_id}.ndjson"
    with fpath.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, sort_keys=True) + "\n")


# ---------------------------------------------------------------------
# Terrain generator (synthetic but physically consistent grade)
# ---------------------------------------------------------------------
def generate_terrain(preset: str) -> List[TerrainSegment]:
    """
    Synthetic 2D trail generator.
    Each segment holds slope (grade), roughness, edge exposure, traction.
    """
    if preset == "Mountain ridge":
        seed = 42
    elif preset == "Forest trail":
        seed = 17
    else:
        seed = 9

    rng = np.random.default_rng(seed)

    segments: List[TerrainSegment] = []
    n = 140
    x = 0.0
    y = 0.0
    elev = 0.0  # synthetic height dimension for grade

    # max grades in degrees for different presets (approximate envelopes)
    if preset == "Mountain ridge":
        max_grade = 16.0
    elif preset == "Forest trail":
        max_grade = 10.0
    else:  # Desert wash
        max_grade = 8.0

    step = 1.0

    for i in range(n):
        t = i / n

        if preset == "Mountain ridge":
            curvature = math.sin(t * 6 * math.pi) * 0.6
            slope_pattern = math.sin(t * 2 * math.pi)
            rough = 0.3 + 0.4 * rng.random()
            edge = 0.4 + 0.5 * abs(curvature)
            traction = 0.6 - 0.2 * rng.random()
        elif preset == "Forest trail":
            curvature = math.sin(t * 3 * math.pi) * 0.4
            slope_pattern = math.sin(t * 1.2 * math.pi)
            rough = 0.2 + 0.3 * rng.random()
            edge = 0.1 + 0.3 * rng.random()
            traction = 0.7 + 0.2 * rng.random()
        else:  # Desert wash
            curvature = math.sin(t * 4 * math.pi) * 0.5
            slope_pattern = math.sin(t * 0.9 * math.pi)
            rough = 0.4 + 0.4 * rng.random()
            edge = 0.2 + 0.4 * rng.random()
            traction = 0.4 + 0.2 * rng.random()

        # Target slope for this segment (signed grade in degrees)
        slope_deg = slope_pattern * max_grade
        slope_rad = math.radians(slope_deg)

        # Update trail geometry
        heading_delta = curvature * 0.12
        x += math.cos(heading_delta) * step
        y += math.sin(heading_delta) * step
        elev += math.tan(slope_rad) * step  # height change given grade

        seg = TerrainSegment(
            x=x,
            y=y + elev * 0.02,  # height hint baked into y for visualization
            slope_deg=float(slope_deg),
            roughness=float(rough),
            edge_exposure=float(edge),
            traction_coeff=float(traction),
        )
        segments.append(seg)

    return segments


# ---------------------------------------------------------------------
# Deterministic “brain” – scoring & decisions
# ---------------------------------------------------------------------
def evaluate_segment(
    seg: TerrainSegment,
    vehicle: VehicleState,
    weather_factor: float,
) -> Dict[str, float]:
    """
    Squeezes terrain + state into scores.
    All purely mathematical, no learning.

    Risk appetite is *not* baked into physics here – it only
    affects gating / thresholds in the decision layer.
    """

    # Grade penalty: above ~8–10° starts to get interesting
    grade = seg.slope_deg
    # Normalize grade to a [0, 1] risk scale around a 8–22° envelope
    grade_risk = max(0.0, (abs(grade) - 8.0) / 14.0)  # 0–1-ish

    # Drift risk from grade, roughness, traction, speed
    speed_factor = min(1.0, vehicle.speed_mps / 16.0)

    traction_risk = (1.0 - seg.traction_coeff) * (0.4 + 0.6 * speed_factor)
    rough_risk = seg.roughness * (0.3 + 0.7 * speed_factor)
    edge_risk = seg.edge_exposure * (0.4 + 0.6 * speed_factor)

    drift_risk = (
        0.35 * grade_risk
        + 0.30 * traction_risk
        + 0.25 * rough_risk
        + 0.10 * edge_risk
    )

    # Instability / “stability window” score from physical terms + weather
    instab_raw = (
        0.4 * drift_risk
        + 0.3 * rough_risk
        + 0.2 * grade_risk
        + 0.1 * weather_factor
    )

    drift_score = float(max(0.0, min(100.0, drift_risk * 100.0)))
    stability_index = float(max(0.0, min(100.0, 100.0 - instab_raw * 100.0)))

    return {
        "grade_deg": float(grade),
        "drift_score": drift_score,
        "stability_index": stability_index,
    }


def _adjust_threshold(base: float, risk_appetite: float, span: float) -> float:
    """
    Shift threshold based on driver risk appetite.
    risk_appetite: 0.0 = ultra conservative, 1.0 = more aggressive.
    span: how far (±) we allow the threshold to move.
    """
    # appetite 0→ -span, 0.5 → 0, 1→ +span
    return base + (risk_appetite - 0.5) * 2.0 * span


def choose_action(
    metrics: Dict[str, float],
    vehicle: VehicleState,
    clarity_floor: float,
    risk_appetite: float,
) -> Dict[str, object]:
    """
    Deterministic decision layer.
    No “AI vibe” – just thresholds + explicit rules.

    Risk appetite adjusts thresholds, not the underlying physics.
    """

    drift = metrics["drift_score"]
    stab = metrics["stability_index"]
    grade = metrics["grade_deg"]

    prev_mode = vehicle.mode or "HOLD"
    if prev_mode == "HOLD":
        prev_mode = "CRUISE"

    reason_chunks = []
    human_required = False

    # Base thresholds
    base = {
        "drift": {
            "CAUTIOUS": 40.0,
            "CRAWL": 60.0,
            "STOP_SAFE": 80.0,
        },
        "stab": {
            "CAUTIOUS": 65.0,
            "CRAWL": 50.0,
            "STOP_SAFE": 35.0,
        },
        "grade": {
            "CAUTIOUS": 10.0,
            "CRAWL": 14.0,
            "STOP_SAFE": 18.0,
        },
    }

    # Appetite-adjusted thresholds
    drift_th = {
        k: _adjust_threshold(v, risk_appetite, span=8.0)
        for k, v in base["drift"].items()
    }
    # Lower stability thresholds for conservative drivers
    stab_th = {
        "CAUTIOUS": _adjust_threshold(base["stab"]["CAUTIOUS"], 1.0 - risk_appetite, span=8.0),
        "CRAWL": _adjust_threshold(base["stab"]["CRAWL"], 1.0 - risk_appetite, span=8.0),
        "STOP_SAFE": _adjust_threshold(base["stab"]["STOP_SAFE"], 1.0 - risk_appetite, span=8.0),
    }
    grade_th = {
        k: _adjust_threshold(v, risk_appetite, span=3.0)
        for k, v in base["grade"].items()
    }

    # Hysteresis margins (to avoid thrash between modes)
    H_DRIFT = 5.0
    H_STAB = 5.0

    # First, compute a "raw" mode based on thresholds
    if drift > drift_th["STOP_SAFE"] or stab < stab_th["STOP_SAFE"] or abs(grade) > grade_th["STOP_SAFE"]:
        raw_mode = "STOP_SAFE"
        reason_chunks.append("drift / stability / grade beyond hard safety envelope")
    elif drift > drift_th["CRAWL"] or stab < stab_th["CRAWL"] or abs(grade) > grade_th["CRAWL"]:
        raw_mode = "CRAWL"
        reason_chunks.append("high slope / exposure / low stability")
    elif drift > drift_th["CAUTIOUS"] or stab < stab_th["CAUTIOUS"] or abs(grade) > grade_th["CAUTIOUS"]:
        raw_mode = "CAUTIOUS"
        reason_chunks.append("moderate terrain risk")
    else:
        raw_mode = "CRUISE"
        reason_chunks.append("within stable window")

    # Apply hysteresis when de-escalating (e.g., STOP_SAFE -> CRAWL -> CAUTIOUS -> CRUISE)
    action = raw_mode

    if prev_mode == "STOP_SAFE" and raw_mode in ("CRAWL", "CAUTIOUS", "CRUISE"):
        if not (drift < drift_th["STOP_SAFE"] - H_DRIFT and stab > stab_th["STOP_SAFE"] + H_STAB):
            action = "STOP_SAFE"
            reason_chunks.append("held in STOP_SAFE until conditions clearly improve")
    elif prev_mode == "CRAWL" and raw_mode in ("CAUTIOUS", "CRUISE"):
        if not (drift < drift_th["CRAWL"] - H_DRIFT and stab > stab_th["CRAWL"] + H_STAB):
            action = "CRAWL"
            reason_chunks.append("held in CRAWL until conditions clearly improve")
    elif prev_mode == "CAUTIOUS" and raw_mode == "CRUISE":
        if not (drift < drift_th["CAUTIOUS"] - H_DRIFT and stab > stab_th["CAUTIOUS"] + H_STAB):
            action = "CAUTIOUS"
            reason_chunks.append("held in CAUTIOUS until conditions clearly improve")

    # Human attention floor
    if stab < clarity_floor:
        human_required = True
        reason_chunks.append("stability below configured floor (driver attention requested)")

    # Conservative envelope always human-gates STOP_SAFE and CRAWL
    if action in ("STOP_SAFE", "CRAWL"):
        human_required = True

    reason = ", ".join(reason_chunks)

    # Speed targets (m/s)
    if action == "STOP_SAFE":
        target_speed = 0.0
    elif action == "CRAWL":
        target_speed = 2.0
    elif action == "CAUTIOUS":
        target_speed = 6.0
    else:  # CRUISE
        target_speed = 12.0

    # First-order lag toward target speed
    alpha = 0.25
    new_speed = vehicle.speed_mps + alpha * (target_speed - vehicle.speed_mps)

    return {
        "action": action,
        "reason": reason,
        "speed_mps": float(new_speed),
        "human_required": human_required,
    }


# ---------------------------------------------------------------------
# Session state & step function
# ---------------------------------------------------------------------
def init_state():
    terrain = generate_terrain("Mountain ridge")
    vehicle = VehicleState(
        x=0.0,
        y=0.0,
        heading_deg=0.0,
        speed_mps=0.0,
        stability_index=100.0,
        drift_score=0.0,
        grade_deg=0.0,
        mode="HOLD",
    )
    st.session_state.raven = {
        "tick": 0,
        "terrain": terrain,
        "vehicle": vehicle,
        "path_history": [],  # list[(x, y)]
        "decisions": [],     # list[DecisionEvent]
        "human_lock_index": None,  # index into decisions needing input
        "human_lock_active": False,
    }


if "raven" not in st.session_state:
    init_state()


def step_raven(params: Dict[str, float]) -> None:
    """
    Advance simulation by one tick and log decision.
    """
    state = st.session_state.raven
    state["tick"] += 1
    tick = state["tick"]

    terrain: List[TerrainSegment] = state["terrain"]
    vehicle: VehicleState = state["vehicle"]

    # Clamp index to last segment
    idx = min(len(terrain) - 1, tick)
    seg = terrain[idx]

    metrics = evaluate_segment(
        seg=seg,
        vehicle=vehicle,
        weather_factor=params["weather_factor"],
    )

    decision = choose_action(
        metrics=metrics,
        vehicle=vehicle,
        clarity_floor=params["clarity_floor"],
        risk_appetite=params["risk_appetite"],
    )

    # Update vehicle state
    vehicle.grade_deg = metrics["grade_deg"]
    vehicle.stability_index = metrics["stability_index"]
    vehicle.drift_score = metrics["drift_score"]
    vehicle.speed_mps = decision["speed_mps"]
    vehicle.mode = decision["action"]
    vehicle.x = seg.x
    vehicle.y = seg.y
    state["vehicle"] = vehicle
    state["path_history"].append((vehicle.x, vehicle.y))

    # Decision event
    ev = DecisionEvent(
        tick=tick,
        action=decision["action"],
        reason=decision["reason"],
        grade_deg=vehicle.grade_deg,
        drift_score=vehicle.drift_score,
        stability_index=vehicle.stability_index,
        human_required=decision["human_required"],
        human_override="PENDING" if decision["human_required"] else "AUTO",
        timestamp=time.time(),
    )
    state["decisions"].append(ev)

    # Lock on first human-required decision if not already active
    if decision["human_required"] and not state["human_lock_active"]:
        state["human_lock_index"] = len(state["decisions"]) - 1
        state["human_lock_active"] = True

    # Audit record
    audit_record = {
        "run_id": current_run_id(),
        "tick": tick,
        "terrain_segment": asdict(seg),
        "vehicle_state": asdict(vehicle),
        "metrics": metrics,
        "decision": {
            "action": ev.action,
            "reason": ev.reason,
            "human_required": ev.human_required,
            "human_override": ev.human_override,
        },
        "params": params,
        "ts": ev.timestamp,
    }
    append_audit_record(audit_record)

    st.session_state.raven = state


# ---------------------------------------------------------------------
# Visualization helpers
# ---------------------------------------------------------------------
def draw_topdown_map() -> plt.Figure:
    state = st.session_state.raven
    terrain: List[TerrainSegment] = state["terrain"]
    vehicle: VehicleState = state["vehicle"]
    path = state["path_history"]

    xs = [t.x for t in terrain]
    ys = [t.y for t in terrain]

    fig, ax = plt.subplots(figsize=(6, 6))
    fig.patch.set_facecolor(BG)
    ax.set_facecolor("#020617")

    # Terrain backbone
    ax.plot(xs, ys, linewidth=2, alpha=0.4)

    # Color segments by approximate risk (roughness + edge + grade)
    for i in range(1, len(terrain)):
        prev = terrain[i - 1]
        seg = terrain[i]
        risk = (
            0.35 * seg.roughness
            + 0.40 * seg.edge_exposure
            + 0.25 * (abs(seg.slope_deg) / 18.0)
        )
        risk = max(0.0, min(1.0, risk))
        # simple green → orange → red
        if risk < 0.4:
            color = (0.0, 0.8, 0.6)
        elif risk < 0.75:
            color = (1.0, 0.7, 0.2)
        else:
            color = (1.0, 0.25, 0.25)

        ax.plot([prev.x, seg.x], [prev.y, seg.y], linewidth=2.5, alpha=0.9, color=color)

    # Driven path
    if len(path) >= 2:
        px, py = zip(*path)
        ax.plot(px, py, linewidth=3, alpha=0.9)

    # Vehicle marker
    ax.scatter([vehicle.x], [vehicle.y], s=120, linewidths=1.5)

    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_title(
        "Trail Visualization · Synthetic Rivian Scenario",
        fontsize=9,
    )
    ax.set_aspect("equal", "box")
    return fig


def draw_metric_gauge(
    label: str,
    value: float,
    vmin: float,
    vmax: float,
    good_high: bool = True,
) -> plt.Figure:
    """Tiny horizontal gauge using matplotlib."""
    fig, ax = plt.subplots(figsize=(3.4, 0.6))
    fig.patch.set_facecolor(BG)
    ax.set_facecolor("#020617")
    ax.set_xlim(vmin, vmax)
    ax.set_ylim(0, 1)
    ax.axis("off")

    t = (value - vmin) / (vmax - vmin)
    t = max(0.0, min(1.0, t))

    # basic color logic: green / yellow / red
    if good_high:
        if t < 0.33:
            color = (1.0, 0.25, 0.25)
        elif t < 0.66:
            color = (1.0, 0.8, 0.4)
        else:
            color = (0.0, 0.9, 0.6)
    else:
        if t < 0.33:
            color = (0.0, 0.9, 0.6)
        elif t < 0.66:
            color = (1.0, 0.8, 0.4)
        else:
            color = (1.0, 0.25, 0.25)

    # base bar
    ax.barh(0.5, vmax - vmin, left=vmin, height=0.4)
    # filled bar
    ax.barh(0.5, value - vmin, left=vmin, height=0.4, color=color)
    ax.text(vmin, 0.9, label, fontsize=7, ha="left", va="bottom")
    ax.text(vmax, 0.9, f"{value:.1f}", fontsize=7, ha="right", va="bottom")
    return fig


# ---------------------------------------------------------------------
# UI layout
# ---------------------------------------------------------------------
st.markdown(
    "<div class='title-main'>RAVEN 3 · RIVIAN AUTONOMY KERNEL (DEMO)</div>",
    unsafe_allow_html=True,
)
st.markdown(
    "<div class='subtitle'>Deterministic, human-gated autonomy layer. "
    "Synthetic trail. No learning. Everything logged.</div>",
    unsafe_allow_html=True,
)

left_col, mid_col, right_col = st.columns([1.4, 1.2, 1.1])

# ----------------- Right: controls -----------------
with right_col:
    st.markdown("### Environment & Envelope")

    scenario = st.selectbox(
        "Scenario",
        ["Mountain ridge", "Forest trail", "Desert wash"],
        index=0,
    )

    if st.button("Reset scenario / regen terrain"):
        st.session_state.raven["terrain"] = generate_terrain(scenario)
        st.session_state.raven["tick"] = 0
        st.session_state.raven["path_history"] = []
        st.session_state.raven["decisions"] = []
        st.session_state.raven["human_lock_index"] = None
        st.session_state.raven["human_lock_active"] = False

        v = VehicleState(
            x=0.0,
            y=0.0,
            heading_deg=0.0,
            speed_mps=0.0,
            stability_index=100.0,
            drift_score=0.0,
            grade_deg=0.0,
            mode="HOLD",
        )
        st.session_state.raven["vehicle"] = v
        # new run id for audit
        st.session_state.raven_run_id = time.strftime("%Y%m%dT%H%M%S")

    risk_appetite = st.slider(
        "Driver risk appetite",
        0.0,
        1.0,
        0.4,
        help="0.0 = ultra conservative, 1.0 = more aggressive envelope.",
    )

    weather = st.selectbox(
        "Weather / traction",
        ["Dry", "Wet", "Snow / ice", "Dusty"],
        index=0,
    )

    clarity_floor = st.slider(
        "Stability index floor (trip for human attention)",
        20.0,
        80.0,
        45.0,
        help="Below this, RAVEN always asks for human attention.",
    )

    weather_factor = {
        "Dry": 0.1,
        "Wet": 0.25,
        "Snow / ice": 0.45,
        "Dusty": 0.2,
    }[weather]

    params = {
        "risk_appetite": float(risk_appetite),
        "weather_factor": float(weather_factor),
        "clarity_floor": float(clarity_floor),
    }

    st.markdown("---")
    st.markdown("### Simulation control")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("▶ Pulse 1 tick"):
            step_raven(params)
    with c2:
        if st.button("⟳ Pulse 10 ticks"):
            for _ in range(10):
                step_raven(params)

    st.caption(
        "Each tick ≈ 1–2 seconds of trail time. "
        "Pulse to see how RAVEN reacts as terrain tightens."
    )

# ----------------- Left: map & vehicle state -----------------
with left_col:
    state = st.session_state.raven
    vehicle: VehicleState = state["vehicle"]

    map_placeholder = st.empty()
    map_fig = draw_topdown_map()
    map_placeholder.pyplot(map_fig, clear_figure=True)

    st.markdown("### R1 vehicle state")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(
            "<div class='metric-label'>Mode</div>",
            unsafe_allow_html=True,
        )
        st.markdown(
            f"<div class='metric-value'>{vehicle.mode}</div>",
            unsafe_allow_html=True,
        )
    with c2:
        st.markdown(
            "<div class='metric-label'>Speed</div>",
            unsafe_allow_html=True,
        )
        st.markdown(
            f"<div class='metric-value'>{vehicle.speed_mps * 3.6:.1f} km/h</div>",
            unsafe_allow_html=True,
        )
    with c3:
        st.markdown(
            "<div class='metric-label'>Trail segment</div>",
            unsafe_allow_html=True,
        )
        st.markdown(
            f"<div class='metric-value'>{state['tick']}</div>",
            unsafe_allow_html=True,
        )

    g1, g2 = st.columns(2)
    with g1:
        fig_stab = draw_metric_gauge(
            "Stability index",
            vehicle.stability_index,
            0,
            100,
            good_high=True,
        )
        st.pyplot(fig_stab, clear_figure=True)

        fig_grade = draw_metric_gauge(
            "Grade (abs°)",
            abs(vehicle.grade_deg),
            0,
            25,
            good_high=False,
        )
        st.pyplot(fig_grade, clear_figure=True)

    with g2:
        fig_drift = draw_metric_gauge(
            "Drift score",
            vehicle.drift_score,
            0,
            100,
            good_high=False,
        )
        st.pyplot(fig_drift, clear_figure=True)

    st.markdown(
        "<div class='subtitle'>RAVEN treats grade, roughness, traction "
        "and edge exposure as telemetry channels – not 'errors'. "
        "No learning, just math you can inspect.</div>",
        unsafe_allow_html=True,
    )

# ----------------- Mid: decisions & human gate -----------------
with mid_col:
    st.markdown("### Decision feed · RAVEN audit")

    decisions: List[DecisionEvent] = st.session_state.raven["decisions"]
    human_lock_index = st.session_state.raven["human_lock_index"]
    human_lock_active = st.session_state.raven["human_lock_active"]

    if not decisions:
        st.caption("No decisions yet. Pulse the simulation to see RAVEN think.")
    else:
        # Human gate card
        if human_lock_active and human_lock_index is not None and 0 <= human_lock_index < len(decisions):
            ev = decisions[human_lock_index]
            st.markdown(
                "<span class='pill'>Human gate · required</span>",
                unsafe_allow_html=True,
            )
            st.markdown(
                f"**Tick {ev.tick} · {ev.action}** \n"
                f"Reason: {ev.reason} \n"
                f"Grade: `{ev.grade_deg:.1f}°` · "
                f"Drift: `{ev.drift_score:.1f}` · "
                f"Stability: `{ev.stability_index:.1f}`",
            )
            c_ha, c_hb, c_hc = st.columns(3)
            with c_ha:
                if st.button("Approve", key="approve_gate"):
                    decisions[human_lock_index].human_override = "APPROVED"
                    st.session_state.raven["human_lock_index"] = None
                    st.session_state.raven["human_lock_active"] = False
            with c_hb:
                if st.button("Deny", key="deny_gate"):
                    decisions[human_lock_index].human_override = "DENIED"
                    v = st.session_state.raven["vehicle"]
                    v.mode = "STOP_SAFE"
                    v.speed_mps = 0.0
                    st.session_state.raven["vehicle"] = v
                    st.session_state.raven["human_lock_index"] = None
                    st.session_state.raven["human_lock_active"] = False
            with c_hc:
                if st.button("Hold", key="hold_gate"):
                    st.caption(
                        "Hold: vehicle maintains current mode until human resolves.",
                    )

        st.markdown("---")
        # Recent events (newest first)
        for ev in decisions[-12:][::-1]:
            badge = ""
            if ev.human_required:
                if ev.human_override == "PENDING":
                    badge = " · `pending`"
                elif ev.human_override == "APPROVED":
                    badge = " · `approved`"
                elif ev.human_override == "DENIED":
                    badge = " · `denied`"

            st.markdown(
                f"**Tick {ev.tick} · {ev.action}{badge}** \n"
                f"<span style='color:{TEXT_MUTED};font-size:0.8rem'>"
                f"{ev.reason}<br>"
                f"Grade: {ev.grade_deg:.1f}° · "
                f"Drift: {ev.drift_score:.1f} · "
                f"Stability: {ev.stability_index:.1f}</span>",
                unsafe_allow_html=True,
            )
            st.markdown(
                "<hr style='border:0;border-top:1px solid #111827;margin:0.35rem 0'/>",
                unsafe_allow_html=True,
            )

    st.markdown(
        "<div class='subtitle'>Every decision is explainable and overrideable. "
        "If something feels wrong on the trail, you can see exactly what RAVEN saw "
        "and why it chose that action.</div>",
        unsafe_allow_html=True,
    )
    st.markdown("---")
    st.markdown(
        "<div class='subtitle'>Under the hood: RAVEN uses no ML at all. It fuses "
        "grade, roughness, traction and edge exposure into drift and stability metrics, "
        "then runs a deterministic rules engine. Plug this into real Rivian telemetry and "
        "you get a transparent safety layer that always defers to the driver.</div>",
        unsafe_allow_html=True,
    )
