"""The crew alerting terminal against the frozen eicas.py's alert rules, through fmofp_cas_tool.

The frozen EICASDisplay built its alert list in its 10 Hz poll: _compute_alerts (engine, fuel, hydraulic,
electrical, the maximum-thrust advisory), then a row per GCAS alert and per performance exceedance, then
_compute_defensive_alerts, _compute_sensor_alerts and _compute_weather_alerts. Here those methods run on a stand-in
`self` holding a generated state (the display's dictionaries and its field validity), the GCAS rows come from the
frozen GCAS._evaluate and the performance rows from the frozen PerformanceMonitor._check_envelope on the same state,
and the same state goes to the C++ rules through the tool. The C++ answers with the alerts it sets; their texts are
made the way the EICAS window makes them (a CAS_ALERTS payload, encoded and decoded, through
fmofp_bus.cas_alerts.alert_list), and the two lists must be equal, text for text and in order.

Needs FMOFP_CAS_TOOL (CI sets it).
"""

import os
import random
import subprocess
import sys
import unittest
from types import SimpleNamespace

from fmofp_bus import cas_alerts
from fmofp_bus.tests._support import binary_env, needs

B20SS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if B20SS not in sys.path:
    sys.path.insert(0, B20SS)

SHEAR = {"NONE": 0, "LOW": 1, "MODERATE": 2, "SEVERE": 3}
TURBULENCE = {"NONE": 0, "LIGHT": 1, "MODERATE": 2, "SEVERE": 3, "EXTREME": 4}
HEALTH = {"INITIALISING": 0, "UNKNOWN": 0, "NOMINAL": 1, "DEGRADED": 2, "FAULT": 3}
PERF_PARAMETERS = ("g_force", "angle_of_attack", "roll", "pitch", "vertical_speed")  # PerformanceMonitor.LIMITS
CASES = 400


class Validity:
    """FieldValidity as the rules ask it: is_valid(name)."""

    def __init__(self, valid):
        self.valid = set(valid)

    def is_valid(self, name, now=None):
        return name in self.valid


def pick(rng, *values):
    return rng.choice(values)


def generate(rng):
    """One state of the EICAS when its poll built the list, with values on and around every threshold."""
    fields = ("egt_c", "oil_psi", "oil_temp_c", "vib", "total_kg", "balance_kg", "sys_a_psi", "sys_b_psi", "sys_c_psi",
              "gen1_ok", "gen2_ok", "main_bus_v")
    valid = [f for f in fields if rng.random() < (0.97 if f == "egt_c" else 0.75)]
    contacts = [{"hostile": rng.random() < 0.6, "priority": pick(rng, 1, 2, 3, 4)} for _ in range(pick(rng, 0, 0, 1, 2, 5))]
    defensive = {} if rng.random() < 0.2 else {
        "chaff_remaining": pick(rng, 60, 30, 11, 10, 3, 1, 0), "flares_remaining": pick(rng, 30, 6, 5, 2, 0),
        "ecm_mode": pick(rng, "STANDBY", "ACTIVE", "PASSIVE"), "rwr_contacts": contacts}
    return {
        "thrust": pick(rng, 60.0, 0.6 * 100, 0.7 * 100, 0.9 * 100, 1.0 * 100, 95.0, 95.5, 88.88, 101.0),
        "valid": valid,
        "oil_psi": pick(rng, 60.0, 50.0, 49.99, 45.0, 40.0, 39.99, 10.0),
        "oil_temp_c": pick(rng, 95.0, 130.0, 130.01, 150.0),
        "vib": pick(rng, 0.3, 0.8, 0.801, 1.5),
        "total_kg": pick(rng, 39000.0, 1000.0, 999.9, 500.0, 499.9, 0.0),
        "balance_kg": pick(rng, 0.0, 200.0, -200.0, 200.1, -250.0, 1000.0),
        "hyd": [pick(rng, 3000.0, 2500.0, 2499.9, 2000.0, 1999.9, 0.0) for _ in range(3)],
        "gen1_ok": rng.random() < 0.7, "gen2_ok": rng.random() < 0.7,
        "main_bus_v": pick(rng, 115.0, 100.0, 99.9, 0.0),
        # The GCAS's state (ft, fpm) and the TFR clearance it was given; the performance monitor's state.
        "altitude": pick(rng, 25000.0, 1999.0, 1500.0, 999.0, 500.0, 0.0),
        "vertical_speed": pick(rng, 0.0, -1999.0, -2000.0, -3999.0, -4000.0, -6500.0, 7000.0),
        "clearance": pick(rng, None, None, 1500.0, 499.0, 100.0, -20.0),
        "perf_state": {p: pick(rng, 0.0, limit, limit + 0.5, -(limit + 1.0))
                       for p, limit in zip(PERF_PARAMETERS, (9.0, 25.0, 60.0, 45.0, 6000))},
        "defensive": defensive,
        "sensor_health": pick(rng, "UNKNOWN", "INITIALISING", "NOMINAL", "DEGRADED", "FAULT"),
        "fused_hostile": pick(rng, 0, 0, 1, 2, 3, 7),
        "windshear": pick(rng, "NONE", "LOW", "MODERATE", "SEVERE"),
        "turbulence": pick(rng, "NONE", "LIGHT", "MODERATE", "SEVERE", "EXTREME"),
        "microburst": rng.random() < 0.15,
    }


def frozen_list(state):
    """eicas.py's list for the state: its own methods, and the GCAS and performance rows as _poll_data made them."""
    from FMOFP.Interfaces.userInterface.displays.eicas import EICASDisplay
    from FMOFP.Systems.flightControlSys.groundCollisionAvoidanceSys.groundCollisionAvoidanceSys import GCAS
    from FMOFP.Systems.flightControlSys.performaneMonitoring.performaneMonitoring import PerformanceMonitor
    fake = SimpleNamespace(
        _validity=Validity(state["valid"]),
        _engine={"egt_c": 350 + state["thrust"] * 4.5, "oil_psi": state["oil_psi"], "oil_temp_c": state["oil_temp_c"],
                 "vib": state["vib"]},
        _fuel={"total_kg": state["total_kg"], "balance_kg": state["balance_kg"]},
        _hydraulic={"sys_a_psi": state["hyd"][0], "sys_b_psi": state["hyd"][1], "sys_c_psi": state["hyd"][2]},
        _electrical={"main_bus_v": state["main_bus_v"], "gen1_ok": state["gen1_ok"], "gen2_ok": state["gen2_ok"]},
        _defensive=state["defensive"], _sensor_health=state["sensor_health"],
        _fused_hostile_count=state["fused_hostile"], _wx_windshear=state["windshear"],
        _wx_turbulence=state["turbulence"], _wx_microburst=state["microburst"])
    alerts = EICASDisplay._compute_alerts(fake, state["thrust"])
    gcas = GCAS._evaluate(None, {"altitude_ft": state["altitude"], "vertical_speed_fpm": state["vertical_speed"]},
                          state["clearance"])
    for a in gcas:
        alerts.append({"text": f"FCS  {a['message']}", "severity": "WARNING" if a["severity"] == 1 else "CAUTION"})
    monitor = PerformanceMonitor()
    monitor._check_envelope(state["perf_state"])
    for exc in monitor.get_exceedances():
        alerts.append({"text": f"PERF {exc['parameter'].upper()[:8]} EXCEED", "severity": "WARNING"})
    alerts += EICASDisplay._compute_defensive_alerts(fake)
    alerts += EICASDisplay._compute_sensor_alerts(fake)
    alerts += EICASDisplay._compute_weather_alerts(fake)
    return [(a["text"], a["severity"]) for a in alerts], [a["code"] for a in gcas], monitor.get_exceedances()


def tool_commands(state, gcas_codes, exceedances):
    """The same state as AlertInputs for the C++ rules."""
    valid = set(state["valid"])
    d = state["defensive"]
    hostile = [c for c in d.get("rwr_contacts", []) if c.get("hostile")]
    values = {
        "thrust_pct": state["thrust"], "egt_valid": "egt_c" in valid,
        "oil_press_valid": "oil_psi" in valid, "oil_psi": state["oil_psi"],
        "oil_temp_valid": "oil_temp_c" in valid, "oil_temp_c": state["oil_temp_c"],
        "vib_valid": "vib" in valid, "vib": state["vib"],
        "fuel_total_valid": "total_kg" in valid, "fuel_total_kg": state["total_kg"],
        "fuel_balance_valid": "balance_kg" in valid, "fuel_balance_kg": state["balance_kg"],
        "hyd_valid_a": "sys_a_psi" in valid, "hyd_valid_b": "sys_b_psi" in valid, "hyd_valid_c": "sys_c_psi" in valid,
        "hyd_psi_a": state["hyd"][0], "hyd_psi_b": state["hyd"][1], "hyd_psi_c": state["hyd"][2],
        "gen_1_valid": "gen1_ok" in valid, "gen_1_ok": state["gen1_ok"],
        "gen_2_valid": "gen2_ok" in valid, "gen_2_ok": state["gen2_ok"],
        "main_bus_valid": "main_bus_v" in valid, "main_bus_v": state["main_bus_v"],
        "gcas_pullup": "PULLUP" in gcas_codes, "gcas_sink_rate": "SINK RATE" in gcas_codes,
        "gcas_terrain": "TERRAIN" in gcas_codes, "gcas_alt_low": "ALT LOW" in gcas_codes,
        "gcas_vertical_speed": state["vertical_speed"], "gcas_altitude": state["altitude"],
        "gcas_terrain_clearance": state["clearance"] if state["clearance"] is not None else 0.0,
        "rwr_hostile": len(hostile), "rwr_high_priority": sum(1 for c in hostile if c.get("priority", 99) == 1),
        "chaff_remaining": d.get("chaff_remaining", 60), "flares_remaining": d.get("flares_remaining", 30),
        "ecm_active": d.get("ecm_mode") == "ACTIVE",
        "sensor_health": HEALTH[state["sensor_health"]], "fused_hostile": state["fused_hostile"],
        "wx_microburst": state["microburst"], "wx_windshear": SHEAR[state["windshear"]],
        "wx_turbulence": TURBULENCE[state["turbulence"]],
    }
    exceeded = {e["parameter"] for e in exceedances}
    for i, parameter in enumerate(PERF_PARAMETERS):
        values[f"perf_{i}"] = parameter in exceeded
    lines = ["reset"]
    for name, value in values.items():
        lines.append(f"set {name} {float(value):.17g}")
    lines.append("eval")
    return lines


def port_list(names, values):
    """The EICAS window's list from the alerts the C++ set: a CAS_ALERTS payload through the bus encoding."""
    from fmofp_bus.icd import messages as m
    from fmofp_bus.icd.enums import TerminalState
    fields = {name: True for name in names}
    payload = m.CasAlerts(state=TerminalState.NORMAL, computed=True,
                          chaff_remaining=int(values["chaff_remaining"]), flares_remaining=int(values["flares_remaining"]),
                          rwr_high_priority=int(values["rwr_high_priority"]), rwr_hostile=int(values["rwr_hostile"]),
                          fused_hostile=int(values["fused_hostile"]), gcas_vertical_speed=values["gcas_vertical_speed"],
                          gcas_altitude=values["gcas_altitude"],
                          gcas_terrain_clearance=values["gcas_terrain_clearance"], **fields)
    _, words = payload.encode()
    _, back = m.CasAlerts.decode(words)
    return [(a["text"], a["severity"]) for a in cas_alerts.alert_list(back, 0.0)]


@needs("FMOFP_CAS_TOOL")
class CasOracleTest(unittest.TestCase):
    def run_tool(self, lines):
        result = subprocess.run([os.environ["FMOFP_CAS_TOOL"]], input="\n".join(lines) + "\n", capture_output=True,
                                text=True, timeout=120, env=binary_env())
        self.assertEqual(0, result.returncode, result.stderr)
        return result.stdout.splitlines()

    def test_the_rules_give_eicas_py_s_list(self):
        rng = random.Random(2611)
        states = [generate(rng) for _ in range(CASES)]
        frozen = [frozen_list(s) for s in states]
        lines = []
        commands = []
        for state, (_, codes, exceedances) in zip(states, frozen):
            cmds = tool_commands(state, codes, exceedances)
            commands.append(cmds)
            lines += cmds
        out = self.run_tool(lines)
        self.assertFalse([line for line in out if line.startswith("error")], "every input name is known")
        answers = [line for line in out if line != "ok"]
        self.assertEqual(CASES, len(answers))
        seen = set()
        for i, (state, (expected, _, _), answer) in enumerate(zip(states, frozen, answers)):
            names = [] if answer == "none" else answer.split()
            seen.update(names)
            values = dict(cmd.split(" ", 2)[1:] for cmd in commands[i] if cmd.startswith("set "))
            values = {k: float(v) for k, v in values.items()}
            self.assertEqual(expected, port_list(names, values), f"case {i}: {state}")
        # The generated states reach every alert but the EGT's UNKNOWN on the bus's thrust and the impossible ones.
        missing = [field for field, _, _ in cas_alerts.ALERTS if field not in seen]
        self.assertEqual([], missing, "every alert met at least once")

    def test_the_profile_power_is_the_feed_s(self):
        from fmofp_bus.icd.enums import FmsFlightMode
        from fmofp_display.flight_feed import DEFAULT_LIMITS, PROFILE_LIMITS
        modes = list(FmsFlightMode)
        out = self.run_tool([f"power {int(mode)}" for mode in modes] + ["power none"])
        self.assertEqual([PROFILE_LIMITS[mode][2] for mode in modes] + [DEFAULT_LIMITS[2]], [float(x) for x in out])


class FrozenRulesTest(unittest.TestCase):
    """What the frozen rules do that the port keeps or departs from (ICD README section 2)."""

    def test_without_a_thrust_the_frozen_rules_stop(self):
        """_compute_alerts compares the thrust unconditionally: None raised, and the poll's except swallowed the
        whole pass. The bus always gives the profile's power, as the EICAS's feed did."""
        from FMOFP.Interfaces.userInterface.displays.eicas import EICASDisplay
        fake = SimpleNamespace(_validity=Validity([]), _engine={}, _fuel={}, _hydraulic={}, _electrical={})
        with self.assertRaises(TypeError):
            EICASDisplay._compute_alerts(fake, None)

    def test_the_table_is_the_frozen_texts(self):
        """Every text of fmofp_bus.cas_alerts appears in eicas.py (or the GCAS's and the performance monitor's
        message formats it prefixed), with its severity."""
        import inspect
        from FMOFP.Interfaces.userInterface.displays import eicas
        source = inspect.getsource(eicas)
        for field, text, severity in cas_alerts.ALERTS:
            if field.startswith(("fcs_", "perf_")):
                continue
            stem = text.split("{")[0].split("(")[0].rstrip()
            if field.startswith("hyd_"):
                stem = "{name}" + text[len("HYD A"):]  # f"{name}  PRESSURE LOW" over ("HYD A", ...)
            self.assertIn(stem, source, field)
            self.assertIn(f'"{severity[:4]}', source.replace("_WARN", '"WARN').replace("_CAUT", '"CAUT')
                          .replace("_ADV", '"ADVI'), field)


if __name__ == "__main__":
    unittest.main()
