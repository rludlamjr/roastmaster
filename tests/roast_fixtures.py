"""Synthetic roast data shaped like a light roast on a Kaleido M1 (170 g)."""

from __future__ import annotations

from roastmaster.display.units import c_to_f
from roastmaster.profiles.schema import ProfileEvent, ProfileSample, RoastProfile

PREHEAT_S = 30  # samples recorded before CHARGE (session clock offset)


def _ror_c(t: float, *, fc_s: float, crash: bool) -> float:
    """Rate of rise in C/min at roast time t (after the turning point)."""
    if t < 110:
        return (t - 65) / 45 * 22.0
    if t < fc_s:
        return 22.0 + (10.0 - 22.0) * (t - 110) / (fc_s - 110)
    if not crash:
        return max(4.0, 10.0 - (t - fc_s) * 0.05)
    # crash: collapses right after FC, then flicks back up
    if t < fc_s + 40:
        return 10.0 - (t - fc_s) * 0.2          # 10 -> 2
    if t < fc_s + 80:
        return 2.0 + (t - fc_s - 40) * 0.12     # 2 -> 6.8
    return 6.8


def make_roast(
    *,
    fc_s: float = 410.0,
    drop_s: float | None = 510.0,
    crash: bool = False,
    until_s: float | None = None,
    charge_bt_c: float = 190.0,
) -> RoastProfile:
    """Build a roast profile. ``drop_s=None`` gives an in-progress roast."""
    end = drop_s if drop_s is not None else (until_s or fc_s + 30)
    samples: list[ProfileSample] = []
    for i in range(PREHEAT_S):
        samples.append(ProfileSample(elapsed=float(i), bt=c_to_f(charge_bt_c),
                                     et=c_to_f(charge_bt_c + 5), burner=60))
    bt_c = charge_bt_c
    t = 0
    events = [ProfileEvent("CHARGE", float(PREHEAT_S), c_to_f(charge_bt_c))]
    fc_bt = None
    while t <= end + (60 if drop_s is not None else 0):
        if t <= 65:
            bt_c = 95.0 + (charge_bt_c - 95.0) * (1 - t / 65) ** 2
        elif drop_s is not None and t > drop_s:
            bt_c -= 1.5  # cooling tray
        else:
            bt_c += _ror_c(t, fc_s=fc_s, crash=crash) / 60.0
        if t == int(fc_s):
            fc_bt = bt_c
        burner = 90 if t < 240 else (70 if t < fc_s else 50)
        samples.append(ProfileSample(elapsed=float(PREHEAT_S + t), bt=c_to_f(bt_c),
                                     et=c_to_f(bt_c + 30), burner=burner))
        if drop_s is not None and t == int(drop_s):
            events.append(ProfileEvent("DROP", float(PREHEAT_S + t), c_to_f(bt_c)))
        t += 1
    if fc_bt is not None:
        events.append(ProfileEvent("FIRST_CRACK", float(PREHEAT_S + fc_s), c_to_f(fc_bt)))
    return RoastProfile(roast_id="2026-09-28_143200", roast_date="2026-09-28 14:32",
                        coffee="Reserva del Patron", weight_g=170.0,
                        samples=samples, events=events)
