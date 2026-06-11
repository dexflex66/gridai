"""
Load and PV profiles for residential homes.

Profiles are synthetic but physically plausible for Australian residential:
- Base load: peaks in morning (7-8am) and evening (6-9pm), low overnight
- PV: solar bell curve peaking at solar noon (~12:30pm)
- Battery: 10 kWh capacity, 5 kW max discharge rate

Battery discharge rate is 5 kW (aggressive home battery, e.g. Tesla Powerwall 2).
This creates a clear overvoltage signal when many batteries discharge simultaneously.

Physics check with FEEDER_IMPEDANCE_PU = 0.001 and N=60 homes (prefix-sum voltage model):
  Evening: battery 5kW, base 2.0kW, PV ~0.2kW -> net_export = 3.2 kW/home
  All 60 discharge: cumulative at home 59 = 60 * 3.2 = 192 kW
    V[59] = 1.02 + 0.001 * 192 = 1.212 pu -> OVERVOLTAGE ✓
  Gossip (15 homes discharge): 15*3.2 + 45*(-2.0) = 48 - 90 = -42 kW
    V[59] = 1.02 + 0.001 * (-42) = 0.978 pu -> IN BAND ✓

Profiles indexed by 5-minute steps: step 0 = midnight 00:00.
Step 84 = 07:00, step 96 = 08:00, step 168 = 14:00, step 228 = 19:00.
"""

import numpy as np

# Time axis
TIMESTEP_MINUTES = 5
N_STEPS = 288
HOURS = np.linspace(0, 24, N_STEPS, endpoint=False)

# Battery defaults
BATTERY_CAPACITY_KWH = 10.0
BATTERY_MAX_RATE_KW = 5.0      # 5 kW discharge: creates clear overvoltage when herding
BATTERY_EFFICIENCY = 0.95       # round-trip efficiency (applied on charge)
BATTERY_SOC_MIN = 0.10          # don't discharge below 10%
BATTERY_SOC_MAX = 0.95          # don't charge above 95%

# Price signal: evening peak period 17:00-20:00 (steps 204-240)
PRICE_PEAK_START_STEP = 204     # 17:00
PRICE_PEAK_END_STEP = 240       # 20:00
PRICE_THRESHOLD_DEFAULT = 0.5   # shared threshold for naive strategy (normalised 0-1)


def base_load_profile(seed: int = 0) -> np.ndarray:
    """
    Synthetic residential base load in kW over 288 steps (24h, 5-min).
    Morning peak ~1.5kW at 7:30am, evening peak ~2.5kW at 7pm.
    With per-home random variation.
    """
    rng = np.random.RandomState(seed)
    profile = np.zeros(N_STEPS)

    for i, h in enumerate(HOURS):
        # Morning peak: Gaussian centred at 7:30am
        morning = 1.0 * np.exp(-0.5 * ((h - 7.5) / 1.0) ** 2)
        # Evening peak: Gaussian centred at 19:00 (2.0 kW peak for calibration)
        evening = 2.0 * np.exp(-0.5 * ((h - 19.0) / 1.5) ** 2)
        # Overnight base: always-on appliances
        base = 0.20
        profile[i] = base + morning + evening

    # Add per-home variation: +/- 20%
    variation = rng.uniform(0.8, 1.2)
    profile *= variation

    # Add small random noise per step
    profile += rng.uniform(-0.05, 0.05, N_STEPS)
    profile = np.clip(profile, 0.1, 5.0)

    return profile


def pv_profile(seed: int = 0, has_pv: bool = True) -> np.ndarray:
    """
    Synthetic rooftop PV generation in kW. Bell curve around solar noon.
    Only active in daylight (6am-7pm). Returns zeros if no PV.
    """
    if not has_pv:
        return np.zeros(N_STEPS)

    rng = np.random.RandomState(seed + 1000)
    # Capacity varies by home: 3-6 kW systems
    peak_kw = rng.uniform(3.0, 6.0)

    profile = np.zeros(N_STEPS)
    for i, h in enumerate(HOURS):
        if 6.0 <= h <= 19.0:
            # Solar noon ~12:30, width ~3h
            solar = peak_kw * np.exp(-0.5 * ((h - 12.5) / 2.5) ** 2)
            # Cloud variation
            cloud = rng.uniform(0.85, 1.0)
            profile[i] = solar * cloud

    return profile


def price_signal() -> np.ndarray:
    """
    Normalised price signal (0-1) over 288 steps.
    Ramps up during the evening peak window 17:00-20:00.
    This is the signal that naive batteries respond to.
    """
    signal = np.zeros(N_STEPS)
    for i in range(N_STEPS):
        h = HOURS[i]
        if 17.0 <= h < 20.0:
            # Ramp up at 17:00, ramp down at 20:00
            if h < 18.5:
                signal[i] = (h - 17.0) / 1.5 * 0.8 + 0.2
            else:
                signal[i] = 1.0 - (h - 18.5) / 1.5 * 0.8
        elif 7.0 <= h < 9.0:
            # Small morning peak
            signal[i] = 0.3
    return signal


def make_homes(n_homes: int, heterogeneous: bool, rng_seed: int = 42,
               aemo_profile: np.ndarray = None) -> list:
    """
    Create a list of home parameter dicts.

    heterogeneous=True: willingness_threshold varies uniformly across fleet
    heterogeneous=False: all homes use PRICE_THRESHOLD_DEFAULT

    Each home dict contains:
      id, position (0=closest to transformer), has_pv,
      base_load (array), pv_gen (array),
      battery_capacity_kwh, battery_max_rate_kw,
      soc_initial, willingness_threshold,
      soc_min, soc_max, efficiency

    aemo_profile: optional 288-element array of mean per-home base load kW.
      When provided, replaces the synthetic base_load_profile() for each home
      (with per-home scaling noise applied on top).
    """
    rng = np.random.RandomState(rng_seed)
    homes = []

    for i in range(n_homes):
        has_pv = rng.random() > 0.35  # ~65% penetration

        if heterogeneous:
            # Spread thresholds: some owners very willing (0.2), some reluctant (0.85)
            threshold = rng.uniform(0.20, 0.85)
            # SOC also varied: some batteries full, some half-charged
            soc_init = rng.uniform(0.45, 0.92)
        else:
            # Homogeneous: everyone identical
            threshold = PRICE_THRESHOLD_DEFAULT
            soc_init = 0.70

        if aemo_profile is not None:
            # Use real AEMO shape with per-home scaling (+/-20%) and small noise.
            # This preserves the real evening-peak shape while giving each home
            # its own character, just as the synthetic profiles do.
            scale = rng.uniform(0.8, 1.2)
            noise = rng.uniform(-0.05, 0.05, N_STEPS)
            bl = np.clip(aemo_profile * scale + noise, 0.1, 5.0)
        else:
            bl = base_load_profile(seed=i)

        home = {
            "id": i,
            "position": i,  # 0 = nearest to transformer
            "has_pv": has_pv,
            "base_load": bl,
            "pv_gen": pv_profile(seed=i, has_pv=has_pv),
            "battery_capacity_kwh": BATTERY_CAPACITY_KWH,
            "battery_max_rate_kw": BATTERY_MAX_RATE_KW,
            "soc_initial": soc_init,
            "willingness_threshold": threshold,
            "soc_min": BATTERY_SOC_MIN,
            "soc_max": BATTERY_SOC_MAX,
            "efficiency": BATTERY_EFFICIENCY,
        }
        homes.append(home)

    return homes
