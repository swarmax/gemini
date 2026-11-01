"""One day of the shipped doublet plant: its flow, pump frequency and injection setpoint."""

import gemini as gm


def doublet_day(frequency=55):
    """Return ``(clock, plan)`` of one day at 150 m3/h, ``frequency`` Hz and 51.5 bar injection."""
    clock = gm.engine.Clock.days(2027, 1, 1, days=1)
    profiles = {
        "doublet.reservoir.production_rate": gm.types.Profile.constant(
            150, unit="m3/h", clock=clock
        ),
        "doublet.esp.frequency": gm.types.Profile.constant(frequency, unit="Hz", clock=clock),
        "injection_pump.pressure_setpoint": gm.types.Profile.constant(
            51.5, unit="bar", clock=clock
        ),
    }
    return clock, gm.Dataset.from_profiles(profiles)
