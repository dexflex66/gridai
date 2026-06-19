"""
Neutral voltage-physics constraint layer for GridAI.

Provides pure functions shared by oracle (feasibility bound) and strategies
(dispatch). Depends ONLY on sim.feeder and sim.profiles — NOT on sim.strategies.

Every function here is deterministic given its inputs. No random state, no
protocol parameters, no tuned constants.
"""

import numpy as np

from sim.feeder import (
    V_SOURCE_PU, V_MIN_PU, V_MAX_PU, FEEDER_IMPEDANCE_PU,
    N_HOMES_DEFAULT,
)
from sim.profiles import (
    N_STEPS, BATTERY_CAPACITY_KWH, BATTERY_MAX_RATE_KW,
    BATTERY_SOC_MIN, BATTERY_SOC_MAX,
)


# ---------------------------------------------------------------------------
# 0. Position extraction and validation
# ---------------------------------------------------------------------------

def _extract_positions(homes):
    """Extract and validate feeder positions from homes list.

    Returns (N,) int array of positions.
    Raises ValueError with clear message on:
      - missing "position" key
      - non-integer position (float, string, etc.)
      - negative position
      - position >= N (out of range)
      - duplicate positions

    Current convention: positions must be 0..N-1, one home per position,
    contiguous.  This helper makes that assumption EXPLICIT so callers
    cannot silently depend on list order.
    """
    N = len(homes)
    positions = np.zeros(N, dtype=int)

    for idx, h in enumerate(homes):
        if "position" not in h:
            raise ValueError(
                f"Home[{idx}] is missing required key 'position'. "
                f"Every home must have an integer position 0..{N-1}."
            )
        p = h["position"]
        if not isinstance(p, (int, np.integer)):
            raise ValueError(
                f"Home[{idx}] position={p!r} must be an integer "
                f"(got {type(p).__name__}). "
                f"Cannot safely map to feeder position."
            )
        if p < 0:
            raise ValueError(
                f"Home[{idx}] position={p} is negative. "
                f"Feeder positions must be >= 0."
            )
        if p >= N:
            raise ValueError(
                f"Home[{idx}] position={p} is out of range. "
                f"With {N} homes, position must be in [0, {N-1}]."
            )
        positions[idx] = p

    if len(np.unique(positions)) < N:
        # Find which positions are duplicated and which homes share them
        unique, counts = np.unique(positions, return_counts=True)
        dup_positions = unique[counts > 1]
        dup_details = []
        for dp in dup_positions:
            home_indices = [j for j in range(N) if positions[j] == dp]
            dup_details.append(f"position {dp} used by homes {home_indices}")
        raise ValueError(
            f"Duplicate feeder positions detected: "
            f"{'; '.join(dup_details)}. "
            f"Each position must be assigned to at most one home."
        )

    return positions


# ---------------------------------------------------------------------------
# 1. Base net power (no battery)
# ---------------------------------------------------------------------------

def compute_base_net_power(homes, step, positions=None):
    """Net power per home at *step* assuming zero battery action.

    Positive = export (PV > load), negative = import (load > PV).
    Returns shape (N,) array in kW, indexed by FEEDER POSITION,
    NOT by list index.  The prefix-sum voltage model requires
    position-ordered input.

    Parameters
    ----------
    positions : (N,) int array or None — pre-validated positions from
        _extract_positions.  If None, extracted and validated here.
    """
    if positions is None:
        positions = _extract_positions(homes)
    N = len(homes)
    net = np.zeros(N)
    for h, p in zip(homes, positions):
        net[p] = h["pv_gen"][step] - h["base_load"][step]
    return net


# ---------------------------------------------------------------------------
# 2. Voltage computation
# ---------------------------------------------------------------------------

def compute_voltages_from_net(net_power, feeder_impedance=None):
    """Voltage at every node given per-home net power (kW).

    Uses the prefix-sum model defined in sim.feeder:
      V[i] = V_source + Z * sum(net[0..i])

    This is the same model used by sim.simulator.simulate().
    Returns shape (N,) array in pu.
    """
    if feeder_impedance is None:
        feeder_impedance = FEEDER_IMPEDANCE_PU
    prefix = np.cumsum(net_power)
    return V_SOURCE_PU + feeder_impedance * prefix


# ---------------------------------------------------------------------------
# 3. Baseline voltage forecast (no battery)
# ---------------------------------------------------------------------------

def baseline_voltage_forecast(homes):
    """Full 288-step voltage forecast assuming NO battery action.

    Returns (N, N_STEPS) array of voltages in pu.
    Forecast rows are in feeder-position order (row i = voltage at node i).
    """
    positions = _extract_positions(homes)
    N = len(homes)
    forecast = np.zeros((N, N_STEPS))
    for t in range(N_STEPS):
        net = compute_base_net_power(homes, t, positions)
        forecast[:, t] = compute_voltages_from_net(net)
    return forecast


# ---------------------------------------------------------------------------
# 4. Risk window detection
# ---------------------------------------------------------------------------

def voltage_risk_windows(forecast, v_min=None, v_max=None):
    """Dynamically detect voltage-risk windows from a forecast.

    Parameters
    ----------
    forecast : (N, N_STEPS) array — per-home voltage series (pu).
    v_min, v_max : float — voltage limits (default from feeder).

    Returns
    -------
    dict with keys:
      undervolt_risk : list of (start, end) step ranges where
                       V[N-1] < v_min (no battery).
      overvolt_risk  : list of (start, end) step ranges where
                       V[N-1] > v_max (no battery).
      critical_node  : int — node index with worst voltage (typically N-1).
      risk_window    : (start, end) — union of all risk steps.
      undervolt_window : (start, end) — combined undervoltage-only window.
                         This is the window where battery discharge helps.
                         (Battery discharge during overvoltage makes it worse,
                         so the dispatch window should be undervoltage-only.)

    Each range is [inclusive, exclusive), matching step indexing convention.
    """
    if v_min is None:
        v_min = V_MIN_PU
    if v_max is None:
        v_max = V_MAX_PU

    N = forecast.shape[0]
    critical = N - 1  # far-end node has max cumulative swing
    v_critical = forecast[critical, :]

    # Detect contiguous intervals below V_MIN or above V_MAX
    uv = (v_critical < v_min).astype(int)
    ov = (v_critical > v_max).astype(int)

    def _intervals(bitmask):
        """Convert binary mask to list of (start, end) intervals."""
        if np.sum(bitmask) == 0:
            return []
        padded = np.concatenate([[0], bitmask, [0]])
        diffs = np.diff(padded)
        starts = np.where(diffs == 1)[0]
        ends = np.where(diffs == -1)[0]
        return [(int(s), int(e)) for s, e in zip(starts, ends)]

    uv_ranges = _intervals(uv)
    ov_ranges = _intervals(ov)

    # Union of all risk steps
    any_risk = (uv | ov).astype(int)
    combined = _intervals(any_risk)
    if combined:
        risk_start = min(r[0] for r in combined)
        risk_end = max(r[1] for r in combined)
    else:
        risk_start = 0
        risk_end = 0

    # Undervoltage-only window (where battery discharge helps)
    if uv_ranges:
        uv_start = min(r[0] for r in uv_ranges)
        uv_end = max(r[1] for r in uv_ranges)
    else:
        uv_start = 0
        uv_end = 0

    return {
        "undervolt_risk": uv_ranges,
        "overvolt_risk": ov_ranges,
        "critical_node": int(critical),
        "risk_window": (int(risk_start), int(risk_end)),
        "undervolt_window": (int(uv_start), int(uv_end)),
    }


# ---------------------------------------------------------------------------
# 5. Per-home available discharge steps (from SOC)
# ---------------------------------------------------------------------------

def available_discharge_steps(home, dt_h=None, safety_cap=None):
    """Maximum consecutive discharge steps a home can sustain from SOC.

    Derivation:
      usable_energy = (soc_initial - soc_min) * battery_capacity_kwh
      energy_per_step = battery_max_rate_kw * dt_h
      max_steps = floor(usable_energy / energy_per_step)

    Parameters
    ----------
    home : dict — must have soc_initial, soc_min, battery_capacity_kwh,
                  battery_max_rate_kw.
    dt_h : float — timestep in hours (default 5/60 = 5 minutes).
    safety_cap : int or None — optional hard cap (e.g. battery-health
                 limit). If provided, result = min(floor(...), safety_cap).
                 The caller must justify the cap; this function does not
                 hardcode one.

    Returns
    -------
    int — number of 5-min discharge steps available.
    """
    if dt_h is None:
        dt_h = 5.0 / 60.0
    usable = (home["soc_initial"] - home["soc_min"]) * home["battery_capacity_kwh"]
    energy_per_step = home["battery_max_rate_kw"] * dt_h
    if energy_per_step <= 0:
        return 0
    steps = int(np.floor(usable / energy_per_step))
    if safety_cap is not None:
        steps = min(steps, safety_cap)
    return max(steps, 0)


# ---------------------------------------------------------------------------
# 6. Home voltage sensitivity
# ---------------------------------------------------------------------------

def home_voltage_sensitivity(homes, feeder_impedance=None):
    """Voltage sensitivity coefficient per home.

    In the prefix-sum model, V[N-1] (the critical far node) is:
      V[N-1] = V_source + Z * sum(net[0..N-1])

    Each discharging home adds Z * battery_rate_kW to V[N-1].
    So dV[N-1]/d(discharge) = Z * battery_rate for ALL homes — equal.

    However, the NUMBER of nodes each home affects varies:
    - Home i affects V[i], V[i+1], ..., V[N-1] = (N - i) nodes.
    - Near-transformer homes affect more nodes.

    We define sensitivity as how many downstream nodes a home's discharge
    supports — homes nearer the transformer have wider coverage.

    Returns (N,) array of normalised sensitivity [0, 1].
    """
    if feeder_impedance is None:
        feeder_impedance = FEEDER_IMPEDANCE_PU
    N = len(homes)
    if N == 0:
        return np.array([])
    # For prefix-sum: home i contributes to nodes i..N-1
    # Count = N - i
    counts = np.array([N - h["position"] for h in homes], dtype=float)
    max_count = float(np.max(counts)) if np.max(counts) > 0 else 1.0
    sensitivity = counts / max_count  # [0, 1], near-transformer = 1.0
    return sensitivity


# ---------------------------------------------------------------------------
# 7. Per-slot support bounds
# ---------------------------------------------------------------------------

def slot_support_bounds(homes, forecast=None, v_min=None, v_max=None,
                        feeder_impedance=None):
    """Compute per-slot K_min and K_max from voltage physics.

    NOTE: This function returns COUNT-based bounds using a WORST-CASE
    battery rate across homes.  With heterogeneous battery rates the
    true physical constraint is kW-based — see
    overvoltage_kw_capacity_per_node.  This count-based scalar is kept
    for backward compatibility only.

    K_min[t] : minimum discharging homes needed at step t to prevent
               V[N-1] from dropping below v_min.
               Uses the minimum battery rate among homes (most
               conservative: more homes needed for same lift).

    K_max[t] : CONSERVATIVE SCALAR count bound on discharging homes.
               Uses the maximum battery rate among homes (most
               conservative: fewer homes for same headroom).
               The TRUE constraint is kW-position based —
               see validate_schedule_invariants (check 4) and
               overvoltage_kw_capacity_per_node.

    These are PURELY PHYSICAL bounds — no protocol caps applied.
    The caller may optionally apply a protocol cap on K_max.

    Parameters
    ----------
    homes : list of home dicts.
    forecast : (N, N_STEPS) or None — precomputed baseline voltage forecast.
               Computed if None.
    v_min, v_max : float — voltage limits (defaults from feeder).
    feeder_impedance : float — line impedance per kW (default from feeder).

    Returns
    -------
    k_min : (N_STEPS,) int array.
    k_max : (N_STEPS,) int array.
    """
    if v_min is None:
        v_min = V_MIN_PU
    if v_max is None:
        v_max = V_MAX_PU
    if feeder_impedance is None:
        feeder_impedance = FEEDER_IMPEDANCE_PU
    if forecast is None:
        forecast = baseline_voltage_forecast(homes)

    # Use per-home rates for conservative count bounds
    rates = np.array([h["battery_max_rate_kw"] for h in homes], dtype=float)
    rate_min = float(np.min(rates))   # conservative for K_min: minimum lift per home
    rate_max = float(np.max(rates))   # conservative for K_max: maximum headroom per home
    dV_min = feeder_impedance * rate_min
    dV_max = feeder_impedance * rate_max

    N = len(homes)
    N_steps = forecast.shape[1]

    k_min = np.zeros(N_steps, dtype=int)
    k_max = np.full(N_steps, N, dtype=int)

    for t in range(N_steps):
        v_all = forecast[:, t]  # (N,) — baseline V at ALL nodes

        # --- K_min: undervoltage bound ---
        v_N1 = v_all[-1]
        if v_N1 < v_min:
            gap = v_min - v_N1
            k_min[t] = min(int(np.ceil(gap / dV_min)), N)
        else:
            k_min[t] = 0

        # --- K_max: overvoltage bound (conservative count approx) ---
        k_max_t = N
        for i in range(N):
            v_i = v_all[i]
            if v_i >= v_max:
                k_max_t = 0
                break
            headroom = v_max - v_i
            max_affecting_i = int(np.floor(headroom / dV_max))
            capped_affecting = min(max_affecting_i, i + 1)
            K_max_i = capped_affecting + (N - i - 1)
            if K_max_i < k_max_t:
                k_max_t = K_max_i
        k_max[t] = k_max_t

    return k_min, k_max


# ---------------------------------------------------------------------------
# 8. kW-based overvoltage capacity (the true physical constraint)
# ---------------------------------------------------------------------------

def overvoltage_kw_capacity_per_node(homes, forecast=None, v_max=None,
                                     feeder_impedance=None):
    """Per-node cumulative kW capacity for overvoltage prevention.

    cap_kw[i,t] = max(0, (V_MAX - V_base[i,t]) / Z)

    This is the TRUE physical constraint: cumulative upstream battery
    discharge kW at step t must not exceed cap_kw[i,t] for any node i.

    In the prefix-sum model:
      V[i,t] = V_base[i,t] + Z * sum(discharge_kw[j,t] for j <= i)
      Constraint: V[i,t] <= V_MAX
      => sum(discharge_kw[j,t] for j <= i) <= (V_MAX - V_base[i,t]) / Z

    Returns (N, N_STEPS) float array of kW capacities.
    """
    if v_max is None:
        v_max = V_MAX_PU
    if feeder_impedance is None:
        feeder_impedance = FEEDER_IMPEDANCE_PU
    if forecast is None:
        forecast = baseline_voltage_forecast(homes)

    if feeder_impedance <= 0:
        raise ValueError(
            f"feeder_impedance must be positive, got {feeder_impedance}"
        )

    N, N_steps = forecast.shape
    cap_kw = np.zeros((N, N_steps), dtype=float)

    for i in range(N):
        headroom = v_max - forecast[i, :]  # (N_STEPS,) pu
        cap_kw[i, :] = np.maximum(headroom / feeder_impedance, 0.0)

    return cap_kw


# ---------------------------------------------------------------------------
# 8b. Legacy count-based overvoltage capacity (deprecated)
# ---------------------------------------------------------------------------

def overvoltage_capacity_per_node(homes, forecast=None, v_max=None,
                                  feeder_impedance=None):
    """DEPRECATED — count-based approximation.

    Use overvoltage_kw_capacity_per_node for the true kW-based constraint.
    This wrapper returns floor(cap_kw / BATTERY_MAX_RATE_KW), i.e.
    the number of homes that could discharge at the global rate without
    exceeding V_MAX.

    Returns (N, N_STEPS) int array.
    """
    cap_kw = overvoltage_kw_capacity_per_node(
        homes, forecast, v_max, feeder_impedance
    )
    raw = np.floor(cap_kw / BATTERY_MAX_RATE_KW).astype(int)
    return np.maximum(raw, 0)


# ---------------------------------------------------------------------------
# 9. Active interval counts
# ---------------------------------------------------------------------------

def active_interval_counts(starts, durations, t_min=0, t_max=None):
    """Count homes actively discharging at each step.

    Unlike counting start-slot occupancy, this counts every home across
    its full discharge interval [start, start + duration).

    Parameters
    ----------
    starts : (N,) int array — start step per home.
    durations : (N,) int array — discharge duration per home.
    t_min, t_max : int — time range to evaluate (defaults to 0..N_STEPS-1).

    Returns
    -------
    counts : (T,) int array — active homes per step in [t_min, t_max).
    """
    if t_max is None:
        t_max = N_STEPS
    T = t_max - t_min
    counts = np.zeros(T, dtype=int)
    for s, d in zip(starts, durations):
        if d <= 0:
            continue
        start_idx = max(0, s - t_min)
        end_idx = min(T, s + d - t_min)
        if start_idx < end_idx:
            counts[start_idx:end_idx] += 1
    return counts


# ---------------------------------------------------------------------------
# 9. Schedule invariant validation
# ---------------------------------------------------------------------------

def validate_schedule_invariants(schedule, homes, feeder_impedance=None,
                                 v_min=None, v_max=None, verbose=False,
                                 dispatch_window=None):
    """Check all voltage and energy invariants for a dispatch schedule.

    Checks:
      1. SOC limits respected (no home discharged below soc_min).
      2. Voltage violations in the dispatch window (battery-caused).
      3. Active-interval overlap vs physical K_max (scalar bound).
      4. Active-interval position vs per-node capacity (vector bound).
      5. Discharge coverage vs physical K_min.

    Parameters
    ----------
    dispatch_window : (start, end) or None — scopes voltage violation
        reporting to this window. If None, checks all steps (will include
        PV-caused overvoltage unrelated to battery dispatch).

    Returns
    -------
    dict with keys:
      soc_ok : bool
      overvolt_steps : int (steps where any home > v_max in dispatch window)
      undervolt_steps : int (steps where any home < v_min in dispatch window)
      overvolt_events : int (home-step OV violations in dispatch window)
      undervolt_events : int (home-step UV violations in dispatch window)
      voltage_feasible : bool (dispatch-window violations == 0)
      k_max_violations : list of (step, active_count, k_max) or empty
      k_max_position_violations : list of (step, node, cum_active, capacity)
          or empty — position-aware violation: node i has cum_active[i]
          discharging homes at positions <= i, but per-node capacity cap[i]
          allows at most capacity.
      k_min_shortfall : list of (step, active_count, k_min) or empty
      invariants_ok : bool (soc_ok and voltage_feasible and zero kw_position_violations)
      kw_position_ok : bool (zero kw_position_violations)
    """
    if feeder_impedance is None:
        feeder_impedance = FEEDER_IMPEDANCE_PU
    if v_min is None:
        v_min = V_MIN_PU
    if v_max is None:
        v_max = V_MAX_PU

    N = len(homes)
    if not isinstance(schedule, np.ndarray) or schedule.ndim != 2:
        raise ValueError(
            f"schedule must be a 2D ndarray, got {type(schedule).__name__} "
            f"with ndim={getattr(schedule, 'ndim', '?')}"
        )
    if schedule.shape[0] != N:
        raise ValueError(
            f"schedule rows ({schedule.shape[0]}) != len(homes) ({N}). "
            f"Each home must have exactly one row in the schedule."
        )
    if schedule.shape[1] != N_STEPS:
        raise ValueError(
            f"schedule columns ({schedule.shape[1]}) != N_STEPS ({N_STEPS}). "
            f"Schedule horizon must match the simulation time steps."
        )
    N_steps = schedule.shape[1]

    # --- Position-safety: sort by position for voltage simulation ---
    #
    # NOTE: sim.simulator.simulate builds net_power by iterating the homes
    # list in order, then computes voltages via prefix-sum (which depends
    # on array order).  For correct physical voltages, the homes list AND
    # schedule rows must both be in feeder-position order.
    #
    # We sort by explicit home["position"] here, run simulation on the
    # position-ordered data, then map SOC results back to the original
    # (caller-provided) home order.
    positions = _extract_positions(homes)
    sort_idx = np.argsort(positions)
    homes_sorted = [homes[i] for i in sort_idx]
    schedule_sorted = schedule[sort_idx, :]

    # --- Simulate to get actual voltages and SOC (position-ordered) ---
    from sim.simulator import simulate
    result = simulate(homes_sorted, schedule_sorted)
    soc_pos_order = result["soc_series"]
    vs = result["voltage_series"]  # already in position order (row i = position i)

    # 1. SOC check — map back to original home order
    soc = np.empty_like(soc_pos_order)
    for new_idx, orig_idx in enumerate(sort_idx):
        soc[orig_idx] = soc_pos_order[new_idx]
    soc_min_vals = np.array([h["soc_min"] for h in homes])
    soc_min_2d = soc_min_vals.reshape(-1, 1)
    soc_ok = bool(np.all(soc >= soc_min_2d - 0.01))

    # 2. Voltage violation counts scoped to dispatch window
    dw_start, dw_end = dispatch_window if dispatch_window else (0, N_steps)
    dw_end = min(dw_end, N_steps)
    v_dw = vs[:, dw_start:dw_end]
    overvolt_steps = int(np.sum(np.any(v_dw > v_max, axis=0)))
    undervolt_steps = int(np.sum(np.any(v_dw < v_min, axis=0)))
    overvolt_events = int(np.sum(v_dw > v_max))
    undervolt_events = int(np.sum(v_dw < v_min))

    # Step-node indices for repair targeting
    overvolt_step_indices = [
        (dw_start + int(t), int(i))
        for t in range(v_dw.shape[1])
        for i in range(v_dw.shape[0])
        if v_dw[i, t] > v_max
    ]
    undervolt_step_indices = [
        (dw_start + int(t), int(i))
        for t in range(v_dw.shape[1])
        for i in range(v_dw.shape[0])
        if v_dw[i, t] < v_min
    ]

    # 3. Extract intervals from original (unsorted) homes/schedule
    starts = np.zeros(N, dtype=int)
    durations = np.zeros(N, dtype=int)
    for i in range(N):
        d = schedule[i, :]
        nonzero = np.where(d == 1)[0]
        if len(nonzero) > 0:
            starts[i] = nonzero[0]
            durations[i] = len(nonzero)
        else:
            starts[i] = -1
            durations[i] = 0

    #     # Forecast and bounds always computed in position order
    forecast = baseline_voltage_forecast(homes_sorted)
    k_min_phys, k_max_phys = slot_support_bounds(
        homes_sorted, forecast, v_min, v_max, feeder_impedance
    )
    cap_kw_per_node = overvoltage_kw_capacity_per_node(
        homes_sorted, forecast, v_max, feeder_impedance
    )

    # --- Window selection ---
    # K_min shortfall: meaningful only where undervoltage occurs
    #   → undervoltage risk window
    # K_max violations: upper-bound safety — check across full dispatch window
    #   → dispatch_window
    risks = voltage_risk_windows(forecast, v_min, v_max)
    kmin_rs, kmin_re = risks["undervolt_window"]
    if kmin_rs >= kmin_re:
        kmin_rs, kmin_re = risks["risk_window"]
    if kmin_rs >= kmin_re:
        kmin_rs, kmin_re = dw_start, dw_end
    kmax_rs, kmax_re = dw_start, dw_end

    # --- K_min shortfall check (risk window) ---
    active_kmin = active_interval_counts(
        starts[starts >= 0], durations[starts >= 0], kmin_rs, kmin_re
    )
    k_min_shortfall = []
    for idx, t in enumerate(range(kmin_rs, kmin_re)):
        if t >= N_steps:
            break
        act = int(active_kmin[idx])
        kmin = int(k_min_phys[t])
        if kmin > 0 and act < kmin:
            k_min_shortfall.append((t, act, kmin))

    # --- K_max checks (full dispatch window, kW-based) ---
    active_kmax = active_interval_counts(
        starts[starts >= 0], durations[starts >= 0], kmax_rs, kmax_re
    )

    # Build per-step active-kW-by-position using each home's actual rate
    kmax_len = kmax_re - kmax_rs
    active_kw_by_position = np.zeros((N, kmax_len), dtype=float)
    for i in range(N):
        if starts[i] < 0:
            continue
        pos = int(positions[i])
        rate = float(homes[i]["battery_max_rate_kw"])
        d = durations[i]
        s = starts[i]
        i_start = max(s - kmax_rs, 0)
        i_end = min(s + d - kmax_rs, kmax_len)
        if i_start < i_end:
            active_kw_by_position[pos, i_start:i_end] += rate

    k_max_violations = []
    kw_position_violations = []
    KW_TOLERANCE = 1e-4

    for idx, t in enumerate(range(kmax_rs, kmax_re)):
        if t >= N_steps:
            break
        act = int(active_kmax[idx])
        kmax = int(k_max_phys[t])

        # Scalar K_max check (count-based approximation)
        if act > kmax:
            k_max_violations.append((t, act, kmax))

        # Per-node kW-based capacity check
        # Node index i = physical feeder position
        cum_kw = 0.0
        for i in range(N):
            cum_kw += float(active_kw_by_position[i, idx])
            cap_kw = float(cap_kw_per_node[i, t])
            if cum_kw > cap_kw + KW_TOLERANCE:
                kw_position_violations.append((t, i, cum_kw, cap_kw))

    voltage_feasible = (
        overvolt_steps == 0
        and undervolt_steps == 0
    )

    # NOTE: k_max_violations and k_min_shortfall are count-based
    # conservative approximations (use worst-case battery rate).
    # With heterogeneous rates these are informational only.
    # The TRUE constraints are:
    #   - Overvoltage: kw_position_violations (kW-based position check)
    #   - Undervoltage: full voltage simulation (voltage_feasible)
    #   - Both: voltage_feasible (via simulate) is the final authority
    # NOTE: k_min_shortfall is excluded from invariants_ok for the same
    # reason — it is a conservative count-based approximation.
    kw_position_ok = len(kw_position_violations) == 0
    invariants_ok = bool(soc_ok and voltage_feasible and kw_position_ok)

    return {
        "soc_ok": soc_ok,
        "overvolt_steps": overvolt_steps,
        "undervolt_steps": undervolt_steps,
        "overvolt_events": overvolt_events,
        "undervolt_events": undervolt_events,
        "voltage_feasible": voltage_feasible,
        "overvolt_step_indices": overvolt_step_indices,
        "undervolt_step_indices": undervolt_step_indices,
        "k_max_violations": k_max_violations,
        "k_max_position_violations": kw_position_violations,
        "kw_position_violations": kw_position_violations,
        "kw_position_ok": kw_position_ok,
        "k_min_shortfall": k_min_shortfall,
        "invariants_ok": invariants_ok,
    }
