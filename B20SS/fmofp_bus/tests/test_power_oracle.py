"""The power management terminal against the frozen powerManagementSystem.py and its component classes, through
fmofp_power_tool.

PowerManagementSystem runs in this process beside the C++ on the same readings: its random.uniform answers the
staged reading (the generator output, the consumption, then the snapshot's four bus readings, each matched by
its range), its database is a stand-in. Each second both do adjust_power_parameters() and monitor(); the
batteries' charges and loads, the coolant and cabin temperatures, the fan and the snapshot are compared to the
last bit, since both sides do the same arithmetic in the same order. The manual controls nothing in the Python
called (emergency power, the APU, an engine start, the HVAC, the dissipation unit, a mission equipment battery)
are exercised on both too.

A second test records the frozen Python's set_generator_output: the next second's draw overwrote it (the port
holds the plant's generator instead; ICD README section 2).

Needs FMOFP_POWER_TOOL for the oracle (CI sets it).
"""

import os
import subprocess
import sys
import unittest
from unittest import mock

from fmofp_bus.tests._support import binary_env, needs

B20SS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if B20SS not in sys.path:
    sys.path.insert(0, B20SS)

# random.uniform's arguments in powerManagementSystem.py, by what they draw.
RANGES = {"gen": (200, 250), "cons": (180, 220), "main_v": (110, 120), "aux_v": (25, 28), "freq": (398, 402),
          "pf": (0.95, 1)}
EQUIPMENT = ("Radar", "Comms", "Mission Computer")  # PowerManagementSystem.__init__'s add_equipment calls, in order
PLACES = 9


class PowerTool:
    """One fmofp_power_tool run; answers read back in the order asked."""

    def __init__(self):
        self.lines = []
        self.out = []
        self.pos = 0

    def send(self, *commands):
        self.lines += commands

    def run(self):
        result = subprocess.run([os.environ["FMOFP_POWER_TOOL"]], input="\n".join(self.lines) + "\n",
                                capture_output=True, text=True, timeout=120, env=binary_env())
        assert result.returncode == 0, result.stderr
        self.out = result.stdout.splitlines()
        self.pos = 0
        return self

    def line(self):
        self.pos += 1
        return self.out[self.pos - 1].split()


class FakeRandom:
    """random, as powerManagementSystem.py uses it: uniform(low, high) answers the staged reading by its range."""

    def __init__(self):
        self.staged = {}

    def uniform(self, low, high):
        return self.staged[(low, high)]


def make_pms(pms_module):
    """The frozen PowerManagementSystem with a stand-in for the SQLite database it wrote its snapshots to."""
    with mock.patch.object(pms_module, "DatabaseManager"):
        return pms_module.PowerManagementSystem()


def snapshot_of(pms):
    """What to compare after a step: the raw numbers the Python holds (monitor() rounds some of them)."""
    main, emergency, apu = pms.main_battery, pms.emergency_battery, pms.apu_battery
    cooling, unit, hvac = pms.cooling, pms.cooling.dissipation_unit, pms.hvac
    return {
        "data": (main.charge_pct, emergency.charge_pct, apu.charge_pct, pms.generator_output,
                 pms.total_power_consumption, pms.generator_output - pms.total_power_consumption,
                 pms.pms_data.get("main_bus_voltage", 0.0), pms.pms_data.get("aux_bus_voltage", 0.0),
                 pms.pms_data.get("generator_frequency", 0.0), pms.pms_data.get("power_factor", 0.0),
                 cooling.coolant_temp_c, hvac.cabin_temp_c),
        "batteries": ((main.charge_pct, main.load_amps, main.online),
                      (emergency.charge_pct, emergency.load_amps, emergency.online, emergency.emergency_mode_active,
                       emergency.estimated_endurance_minutes()),
                      (apu.charge_pct, apu.load_amps, apu.online, apu.apu_running),
                      tuple((b.charge_pct, b.load_amps, b.online, b.powering_equipment)
                            for b in (pms.mission_equipment.get(name) for name in EQUIPMENT))),
        "thermal": ((cooling.coolant_temp_c, cooling.target_temp_c, cooling.ambient_temp_c,
                     cooling.total_heat_load_watts(), unit.fan_pct, unit.last_rejected_watts, unit.active,
                     cooling.get_status()["status"]),
                    (hvac.cabin_temp_c, hvac.setpoint_c, hvac.airflow_pct, hvac.powered, hvac.get_status()["at_setpoint"])),
        "rounded": dict(pms.pms_data),
    }


class Oracle:
    """Runs each step on the Python and queues it for the tool, recording what to compare afterwards."""

    def __init__(self, pms, fake_random):
        self.pms = pms
        self.random = fake_random
        self.tool = PowerTool()
        self.script = []  # (command, kind, expected)

    def send(self, command, kind="ok", expected=None):
        self.tool.send(command)
        self.script.append((command, kind, expected))

    def snapshot(self, monitored=False):
        """What to compare now; pms_data (get_data()'s dictionary) only right after a monitor(), since a manual
        control changes the components and the dictionary waits for the next second."""
        expected = snapshot_of(self.pms)
        if not monitored:
            expected["rounded"] = {}
        self.send("data", "data", expected)
        self.send("batteries", "batteries", expected["batteries"])
        self.send("thermal", "thermal", expected["thermal"])

    def second(self, gen, cons, main_v=115.0, aux_v=27.0, freq=400.0, pf=0.98):
        """One second of the loop on this reading: adjust_power_parameters() then monitor(), on both."""
        self.random.staged = {RANGES["gen"]: gen, RANGES["cons"]: cons, RANGES["main_v"]: main_v,
                              RANGES["aux_v"]: aux_v, RANGES["freq"]: freq, RANGES["pf"]: pf}
        self.pms.adjust_power_parameters()
        self.pms.monitor()
        self.send(f"electrical {gen!r} {cons!r} {main_v!r} {aux_v!r} {freq!r} {pf!r}")
        self.snapshot(monitored=True)

    def control(self, command, kind="ok", expected=None):
        """A manual control already applied to the Python; the tool's answer and a snapshot are compared."""
        self.send(command, kind, expected)
        self.snapshot()


@needs("FMOFP_POWER_TOOL")
class PowerOracleTest(unittest.TestCase):
    def test_the_batteries_the_coolant_loop_and_the_cabin_match_the_python_second_for_second(self):
        import FMOFP.Systems.powerManagement.elec.powerManagementSystem as pms_module
        fake_random = FakeRandom()
        with mock.patch.object(pms_module, "random", fake_random):
            pms = make_pms(pms_module)
            oracle = Oracle(pms, fake_random)
            oracle.snapshot()
            # Three surplus seconds: both batteries full, nothing accepted; the coolant warms under the avionics load.
            for gen, cons in ((240.0, 190.0), (231.4, 205.2), (249.9, 180.1)):
                oracle.second(gen, cons, main_v=112.5, aux_v=26.9, freq=399.7, pf=0.955)
            self.assertEqual((100.0, 100.0), (pms.main_battery.charge_pct, pms.apu_battery.charge_pct))
            self.assertGreater(pms.cooling.coolant_temp_c, 20.0)
            # Two deficit seconds discharge the main battery; a surplus second takes it back to full.
            oracle.second(200.0, 220.0)
            oracle.second(201.5, 219.5)
            self.assertLess(pms.main_battery.charge_pct, 99.0)
            self.assertGreater(pms.main_battery.load_amps, 700.0)
            oracle.second(250.0, 180.0)
            self.assertEqual(100.0, pms.main_battery.charge_pct, "70 kW for a second refills two deficit seconds")
            # Emergency power: the emergency battery carries 8 A a second while on; off, its load reads 0.
            pms.emergency_battery.activate_emergency_power()
            oracle.control("emergency 1")
            oracle.second(230.0, 200.0)
            self.assertLess(pms.emergency_battery.charge_pct, 100.0)
            pms.emergency_battery.deactivate_emergency_power()
            oracle.control("emergency 0")
            # The APU lights off its battery, which the next surplus second charges at a quarter of the current; a
            # running APU is not started again.
            oracle.control("apu start", "number", int(pms.apu_battery.start_apu()))
            self.assertTrue(pms.apu_battery.apu_running)
            oracle.second(245.0, 185.0)
            self.assertGreater(pms.apu_battery.charge_pct, 97.8)
            oracle.control("apu start", "number", int(pms.apu_battery.start_apu()))
            pms.apu_battery.stop_apu()
            oracle.control("apu stop")
            # An engine start off the main battery.
            oracle.control("engine_start", "number", int(pms.main_battery.start_engine("Engine 1")))
            self.assertLess(pms.main_battery.charge_pct, 99.0)
            # The cabin: a new setpoint and airflow, two seconds toward it, a second unpowered (drift), power back.
            pms.hvac.set_temperature(26.0)
            oracle.control("hvac_setpoint 26.0")
            pms.hvac.set_airflow(80.0)
            oracle.control("hvac_airflow 80.0")
            oracle.second(238.0, 199.0)
            oracle.second(236.0, 201.0)
            self.assertGreater(pms.hvac.cabin_temp_c, 22.0)
            pms.hvac.power_off()
            oracle.control("hvac_power 0")
            oracle.second(236.0, 201.0)
            pms.hvac.power_on()
            oracle.control("hvac_power 1")
            # The dissipation unit off: nothing rejected, the coolant climbs by the whole load; on again: fan at minimum.
            pms.cooling.dissipation_unit.deactivate()
            oracle.control("dissipation 0")
            oracle.second(240.0, 210.0)
            pms.cooling.dissipation_unit.activate()
            oracle.control("dissipation 1")
            oracle.second(240.0, 210.0)
            # A mission equipment battery powers its equipment; a zero draw powers nothing.
            oracle.control("equipment 0 10.0", "number",
                           int(pms.mission_equipment.get("Radar").power_equipment(10.0, 1.0 / 3600.0)))
            oracle.control("equipment 1 0.0", "number",
                           int(pms.mission_equipment.get("Comms").power_equipment(0.0, 1.0 / 3600.0)))
            # The generator gone: the whole consumption off the main battery, 5-6 % a second.
            for _ in range(3):
                oracle.second(0.0, 200.0)
            self.assertLess(pms.main_battery.charge_pct, 85.0)
            # A 600 kW deficit empties it (depleted mid-draw: the load reads 0); an engine start then fails.
            for _ in range(7):
                oracle.second(0.0, 600.0)
            self.assertTrue(pms.main_battery.is_depleted())
            self.assertEqual(0.0, pms.main_battery.load_amps)
            oracle.control("engine_start", "number", int(pms.main_battery.start_engine("Engine 2")))
            # A surplus charges it again.
            oracle.second(250.0, 180.0)
            self.assertGreater(pms.main_battery.charge_pct, 0.0)

            oracle.tool.run()
            for command, kind, expected in oracle.script:
                if kind == "ok":
                    self.assertEqual(["ok"], oracle.tool.line(), command)
                elif kind == "number":
                    self.assertEqual(expected, int(oracle.tool.line()[0]), command)
                elif kind == "data":
                    self.compare_data(expected, oracle.tool.line())
                elif kind == "batteries":
                    self.compare_batteries(expected, oracle.tool.line())
                else:
                    self.compare_thermal(expected, oracle.tool.line())

    def compare_data(self, expected, row):
        values = [float(x) for x in row]
        self.assertEqual(12, len(values))
        for name, want, got in zip(("main", "emergency", "apu", "gen", "cons", "balance", "main_v", "aux_v", "freq",
                                    "pf", "coolant", "cabin"), expected["data"], values):
            self.assertAlmostEqual(want, got, places=PLACES, msg=name)
        rounded = expected["rounded"]
        if rounded:
            # monitor()'s dictionary rounds the generator, the consumption and the balance to two places and
            # hands the batteries' charges out raw.
            self.assertEqual((rounded["generator_output"], rounded["total_power_consumption"], rounded["power_balance"]),
                             (round(values[3], 2), round(values[4], 2), round(values[5], 2)))
            self.assertAlmostEqual(rounded["main_battery_charge"], values[0], places=PLACES)
            self.assertAlmostEqual(rounded["coolant_temp_c"], values[10], places=PLACES)
            self.assertAlmostEqual(rounded["cabin_temp_c"], values[11], places=PLACES)

    def compare_batteries(self, expected, row):
        groups = " ".join(row).split("|")
        self.assertEqual(4, len(groups), row)
        main, emergency, apu, equipment = (g.split() for g in groups)
        py_main, py_emergency, py_apu, py_equipment = expected
        self.assertAlmostEqual(py_main[0], float(main[0]), places=PLACES)
        self.assertAlmostEqual(py_main[1], float(main[1]), places=PLACES)
        self.assertEqual(py_main[2], bool(int(main[2])))
        self.assertAlmostEqual(py_emergency[0], float(emergency[0]), places=PLACES)
        self.assertAlmostEqual(py_emergency[1], float(emergency[1]), places=PLACES)
        self.assertEqual((py_emergency[2], py_emergency[3]), (bool(int(emergency[2])), bool(int(emergency[3]))))
        self.assertAlmostEqual(py_emergency[4], float(emergency[4]), places=PLACES - 2)
        self.assertAlmostEqual(py_apu[0], float(apu[0]), places=PLACES)
        self.assertAlmostEqual(py_apu[1], float(apu[1]), places=PLACES)
        self.assertEqual((py_apu[2], py_apu[3]), (bool(int(apu[2])), bool(int(apu[3]))))
        self.assertEqual(12, len(equipment))
        for i, (charge, load, online, powering) in enumerate(py_equipment):
            self.assertAlmostEqual(charge, float(equipment[4 * i]), places=PLACES)
            self.assertAlmostEqual(load, float(equipment[4 * i + 1]), places=PLACES)
            self.assertEqual((online, powering), (bool(int(equipment[4 * i + 2])), bool(int(equipment[4 * i + 3]))))

    def compare_thermal(self, expected, row):
        cooling, hvac = (g.split() for g in " ".join(row).split("|"))
        py_cooling, py_hvac = expected
        for want, got in zip(py_cooling[:6], cooling[:6]):
            self.assertAlmostEqual(want, float(got), places=PLACES)
        self.assertEqual((py_cooling[6], py_cooling[7]), (bool(int(cooling[6])), cooling[7]))
        for want, got in zip(py_hvac[:3], hvac[:3]):
            self.assertAlmostEqual(want, float(got), places=PLACES)
        self.assertEqual((py_hvac[3], py_hvac[4]), (bool(int(hvac[3])), bool(int(hvac[4]))))

    def test_the_generator_hold_is_reported_for_the_plant(self):
        tool = PowerTool()
        tool.send("gencmd", "gen -5.0", "gencmd", "gen 150.0", "gencmd", "gen_auto", "gencmd", "status")
        tool.run()
        self.assertEqual(["0", "0", "0"], tool.line(), "no hold until a command")
        self.assertEqual(["ok"], tool.line())
        self.assertEqual(["1", "0", "1"], tool.line(), "max(0, output), as set_generator_output had it")
        self.assertEqual(["ok"], tool.line())
        self.assertEqual(["1", "150", "2"], tool.line())
        self.assertEqual(["ok"], tool.line())
        self.assertEqual(["0", "0", "3"], tool.line(), "released")
        self.assertEqual("INITIALIZING", tool.line()[0], "no reading yet")


class PowerManagementQuirkTest(unittest.TestCase):
    """The frozen Python's behaviour the port departs from (ICD README section 2)."""

    def test_set_generator_output_is_overwritten_by_the_next_seconds_draw(self):
        import FMOFP.Systems.powerManagement.elec.powerManagementSystem as pms_module
        fake_random = FakeRandom()
        fake_random.staged = {RANGES["gen"]: 240.0, RANGES["cons"]: 190.0, RANGES["main_v"]: 115.0,
                              RANGES["aux_v"]: 27.0, RANGES["freq"]: 400.0, RANGES["pf"]: 0.98}
        with mock.patch.object(pms_module, "random", fake_random):
            pms = make_pms(pms_module)
            pms.set_generator_output(500.0)
            self.assertEqual(500.0, pms.generator_output)
            pms.adjust_power_parameters()
            self.assertEqual(240.0, pms.generator_output, "the draw replaced the command within the second")
            pms.set_generator_output(-7.0)
            self.assertEqual(0, pms.generator_output, "max(0, output)")
            # The mission equipment batteries: one each for the radar, the comms and the mission computer, which
            # the loop never draws from.
            pms.adjust_power_parameters()
            pms.monitor()
            statuses = pms.mission_equipment.get_all_status()
            self.assertEqual(set(EQUIPMENT), set(statuses))
            self.assertTrue(all(s["charge_pct"] == 100.0 and not s["powering_equipment"] for s in statuses.values()))
            # The coolant loop's one heat source, and the constant step of one second.
            self.assertEqual({"avionics_bus"}, set(pms.cooling.get_status()["heat_sources"]))
            self.assertEqual(190.0 * 6.0, pms.cooling.total_heat_load_watts())
            self.assertEqual(1.0 / 3600.0, pms.adjust_power_parameters.__defaults__[0])


if __name__ == "__main__":
    unittest.main()
