"""The crew alerts of the crew alerting terminal (RT 26, ICD v1.25), in the order the frozen EICAS built its list.

eicas.py decided its alert list itself (`_compute_alerts`, the GCAS and performance rows `_poll_data` appended,
`_compute_defensive_alerts`, `_compute_sensor_alerts`, `_compute_weather_alerts`). Since v1.25 the decision is the
C++ crew alerting terminal's (`ofp/partitions/cas`), which sets one bit of `CAS_ALERTS` per alert, in this order; the
EICAS window builds the list back from the bits with these texts and severities. A text with a `{...}` takes the
number `CAS_ALERTS` carries beside the bits (`ALERT_NUMBERS`). The C++ enumerates the same alerts in the same order
(`fmofp::cas::Alert`); `test_cas_oracle` holds the two tables together.
"""

WARNING = "WARNING"
CAUTION = "CAUTION"
ADVISORY = "ADVISORY"

# (CAS_ALERTS field, the frozen EICAS's text, severity), in the frozen list's order.
ALERTS = (
    ("eng_egt_high", "ENG  EGT HIGH", WARNING),
    ("eng_egt_caution", "ENG  EGT CAUTION", CAUTION),
    ("eng_egt_unknown", "ENG  EGT UNKNOWN", CAUTION),
    ("eng_oil_press_lo", "ENG  OIL PRESSURE LO", WARNING),
    ("eng_oil_press_low", "ENG  OIL PRESS LOW", CAUTION),
    ("eng_oil_press_unknown", "ENG  OIL PRESS UNKNOWN", CAUTION),
    ("eng_oil_temp_high", "ENG  OIL TEMP HIGH", WARNING),
    ("eng_oil_temp_unknown", "ENG  OIL TEMP UNKNOWN", CAUTION),
    ("eng_vibration_high", "ENG  VIBRATION HIGH", CAUTION),
    ("eng_vib_unknown", "ENG  VIB UNKNOWN", CAUTION),
    ("fuel_qty_unknown", "FUEL QTY UNKNOWN", CAUTION),
    ("fuel_quantity_low", "FUEL  QUANTITY LOW", WARNING),
    ("fuel_quantity_caution", "FUEL  QUANTITY CAUTION", CAUTION),
    ("fuel_balance_unknown", "FUEL  BALANCE UNKNOWN", CAUTION),
    ("fuel_imbalance", "FUEL  IMBALANCE", CAUTION),
    ("hyd_a_unknown", "HYD A  PRESSURE UNKNOWN", CAUTION),
    ("hyd_a_low", "HYD A  PRESSURE LOW", WARNING),
    ("hyd_a_reduced", "HYD A  PRESS REDUCED", CAUTION),
    ("hyd_b_unknown", "HYD B  PRESSURE UNKNOWN", CAUTION),
    ("hyd_b_low", "HYD B  PRESSURE LOW", WARNING),
    ("hyd_b_reduced", "HYD B  PRESS REDUCED", CAUTION),
    ("hyd_c_unknown", "HYD C  PRESSURE UNKNOWN", CAUTION),
    ("hyd_c_low", "HYD C  PRESSURE LOW", WARNING),
    ("hyd_c_reduced", "HYD C  PRESS REDUCED", CAUTION),
    ("elec_gen_1_unknown", "ELEC  GEN 1 UNKNOWN", CAUTION),
    ("elec_gen_1_fault", "ELEC  GEN 1 FAULT", WARNING),
    ("elec_gen_2_unknown", "ELEC  GEN 2 UNKNOWN", CAUTION),
    ("elec_gen_2_fault", "ELEC  GEN 2 FAULT", WARNING),
    ("elec_bus_volts_unknown", "ELEC  BUS VOLTS UNKNOWN", CAUTION),
    ("elec_main_bus_lo", "ELEC  MAIN BUS LO", CAUTION),
    ("eng_max_continuous_thrust", "ENG  MAX CONTINUOUS THRUST", ADVISORY),
    ("fcs_pull_up", "FCS  PULL UP  VS {gcas_vertical_speed:.0f} fpm", WARNING),
    ("fcs_sink_rate", "FCS  SINK RATE  {gcas_vertical_speed:.0f} fpm", WARNING),
    ("fcs_terrain", "FCS  TERRAIN  {gcas_terrain_clearance:.0f} ft clearance", WARNING),
    ("fcs_alt_low", "FCS  ALT LOW  {gcas_altitude:.0f} ft", CAUTION),
    ("perf_g_force", "PERF G_FORCE EXCEED", WARNING),
    ("perf_angle_of_attack", "PERF ANGLE_OF EXCEED", WARNING),
    ("perf_roll", "PERF ROLL EXCEED", WARNING),
    ("perf_pitch", "PERF PITCH EXCEED", WARNING),
    ("perf_vertical_speed", "PERF VERTICAL EXCEED", WARNING),
    ("rwr_high_pri_threats", "RWR  {rwr_high_priority} HIGH-PRI THREAT(S)", WARNING),
    ("rwr_threat_contacts", "RWR  {rwr_hostile} THREAT CONTACT(S)", CAUTION),
    ("cmds_chaff_depleted", "CMDS  CHAFF DEPLETED", WARNING),
    ("cmds_chaff_low", "CMDS  CHAFF LOW ({chaff_remaining})", CAUTION),
    ("cmds_flares_depleted", "CMDS  FLARES DEPLETED", WARNING),
    ("cmds_flares_low", "CMDS  FLARES LOW ({flares_remaining})", CAUTION),
    ("ew_ecm_active", "EW   ECM ACTIVE", ADVISORY),
    ("sensor_system_fault", "SENSOR  SYSTEM FAULT", WARNING),
    ("sensor_degraded_mode", "SENSOR  DEGRADED MODE", CAUTION),
    ("fusion_hostile_tracks", "FUSION  {fused_hostile} HOSTILE TRACKS", WARNING),
    ("fusion_hostile_track", "FUSION  {fused_hostile} HOSTILE TRACK(S)", CAUTION),
    ("wx_microburst", "WX   MICROBURST ALERT", WARNING),
    ("wx_severe_windshear", "WX   SEVERE WINDSHEAR", WARNING),
    ("wx_moderate_windshear", "WX   MODERATE WINDSHEAR", CAUTION),
    ("wx_windshear_ahead", "WX   WINDSHEAR AHEAD", ADVISORY),
    ("wx_extreme_turbulence", "WX   EXTREME TURBULENCE", WARNING),
    ("wx_severe_turbulence", "WX   SEVERE TURBULENCE", WARNING),
    ("wx_moderate_turbulence", "WX   MODERATE TURBULENCE", CAUTION),
    ("wx_light_turbulence", "WX   LIGHT TURBULENCE", ADVISORY),
)

# The numbers CAS_ALERTS carries for the texts above.
ALERT_NUMBERS = ("gcas_vertical_speed", "gcas_terrain_clearance", "gcas_altitude", "rwr_high_priority", "rwr_hostile",
                 "chaff_remaining", "flares_remaining", "fused_hostile")

# Shown, as a caution, while the crew alerting terminal is not heard: an empty list would read as "no alerts",
# which is the fabricated nominal state the frozen EICAS's own comments warn against (ICD README section 2).
SILENT_TEXT = "CAS  ALERTS UNKNOWN"


def alert_list(payload, now):
    """The frozen EICAS's alert dictionaries ({'text', 'severity', 'ts'}) from a CAS_ALERTS payload, in its order."""
    numbers = {name: getattr(payload, name) for name in ALERT_NUMBERS}
    return [{"text": text.format(**numbers), "severity": severity, "ts": now}
            for field, text, severity in ALERTS if getattr(payload, field)]


def silent_list(now):
    return [{"text": SILENT_TEXT, "severity": CAUTION, "ts": now}]
