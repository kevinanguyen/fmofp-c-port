"""The four small utility terminals against the frozen ecsControl.py, hydrControl.py, airframeControl.py and
fdmControl.py, through fmofp_utilities_tool.

Each Python class runs in this process beside the C++: the ECS with readings supplied through set_sensor_readings
(its logger captured, since its three checks only logged), the hydraulics controller's config and backup switch,
the airframe manager's gear state machine and sensor table, the recorder's config tables and card ejection. The
quirk tests record what the Python did that the port keeps or departs from (ICD README section 2): the ECS never
read ecsConfig.xml's limits, the hydraulics monitor compared a constant 2800 psi for equality with its thresholds,
the airframe config has no limits and its loop no longer commands the gear, and the recorder logged the number 123
for every parameter.

Needs FMOFP_UTILITIES_TOOL for the oracle (CI sets it).
"""

import inspect
import os
import subprocess
import sys
import unittest
from unittest import mock

from fmofp_bus.tests._support import binary_env, needs

B20SS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if B20SS not in sys.path:
    sys.path.insert(0, B20SS)

PLACES = 12


class UtilitiesTool:
    """One fmofp_utilities_tool run; answers read back in the order asked."""

    def __init__(self):
        self.lines = []
        self.out = []
        self.pos = 0

    def send(self, *commands):
        self.lines += commands

    def run(self):
        result = subprocess.run([os.environ["FMOFP_UTILITIES_TOOL"]], input="\n".join(self.lines) + "\n",
                                capture_output=True, text=True, timeout=120, env=binary_env())
        assert result.returncode == 0, result.stderr
        self.out = result.stdout.splitlines()
        self.pos = 0
        return self

    def line(self):
        self.pos += 1
        return self.out[self.pos - 1].split()

    def raw(self):
        self.pos += 1
        return self.out[self.pos - 1]


def logged(logger, level="info"):
    """The messages a patched logger's level received, as strings."""
    return [str(call.args[0]) for call in getattr(logger, level).call_args_list]


@needs("FMOFP_UTILITIES_TOOL")
class EcsOracleTest(unittest.TestCase):
    def test_the_checks_the_oxygen_and_the_climate_follow_the_python_pass_for_pass(self):
        import FMOFP.Systems.enviornmentalControlSystem.ecsControl as ecs_module
        tool = UtilitiesTool()
        expected = []  # (kind, value) per tool answer

        def snapshot(ecs, flags):
            status = ecs.get_status()
            expected.append(("data", (status["temperature_c"], status["pressure_kpa"], status["air_quality_pct"],
                                      status["climate"]["temperature"], status["climate"]["humidity"],
                                      status["oxygen"]["oxygen_level"], status["oxygen"]["generation_rate"], flags)))
            tool.send("ecs data")

        with mock.patch.object(ecs_module, "logger") as logger:
            ecs = ecs_module.ECSControl()
            # Without sensor data monitor_ecs returns early: nothing moves, the oxygen stays at 21.
            ecs.monitor_ecs()
            self.assertEqual(21.0, ecs.oxygen.oxygen_level)
            self.assertTrue(any("No sensor source" in msg for msg in logged(logger, "warning")))
            # Readings around the thresholds, 25 passes: the checks (read from the log), the oxygen's climb and cap,
            # the climate's copy of each reading.
            readings = [(22.4, 101.7, 95.0), (22.6, 100.7, 94.9), (21.4, 101.3, 98.0), (22.0, 101.81, 96.0),
                        (22.51, 100.79, 95.0)] + [(22.0 + 0.1 * i, 101.3, 98.0 - 0.2 * i) for i in range(20)]
            for temperature, pressure, quality in readings:
                logger.info.reset_mock()
                ecs.set_sensor_readings(temperature_c=temperature, pressure_kpa=pressure, air_quality_pct=quality)
                ecs.monitor_ecs()
                messages = logged(logger)
                flags = (any(msg.startswith("Adjusting temperature") for msg in messages),
                         any(msg.startswith("Adjusting pressure") for msg in messages),
                         any("Activating air purification" in msg for msg in messages))
                tool.send(f"ecs monitor {temperature!r} {pressure!r} {quality!r}")
                expected.append(("ok", None))
                snapshot(ecs, flags)
            self.assertEqual(23.0, ecs.oxygen.oxygen_level, "capped after the twentieth pass")
            self.assertEqual(readings[-1][0], ecs.climate.current_temperature)
            # The sub-components' manual controls, which nothing in the Python called.
            ecs.oxygen.adjust_generation_rate(1.5)
            tool.send("ecs oxygen_rate 1.5")
            expected.append(("ok", None))
            ecs.climate.adjust_humidity(45.0)
            tool.send("ecs humidity 45.0")
            expected.append(("ok", None))
            ecs.climate.adjust_temperature(30.0)
            tool.send("ecs climate_temp 30.0")
            expected.append(("ok", None))
            snapshot(ecs, flags)
            # The next pass overwrites the climate temperature with the reading.
            logger.info.reset_mock()
            ecs.set_sensor_readings(temperature_c=22.2, pressure_kpa=101.3, air_quality_pct=97.0)
            ecs.monitor_ecs()
            tool.send("ecs monitor 22.2 101.3 97.0")
            expected.append(("ok", None))
            snapshot(ecs, (False, False, False))
            self.assertEqual(22.2, ecs.climate.current_temperature)
            self.assertEqual(45.0, ecs.climate.current_humidity)

        tool.run()
        for kind, want in expected:
            row = tool.line()
            if kind == "ok":
                self.assertEqual(["ok"], row)
                continue
            values = [float(x) for x in row[:7]]
            for name, w, got in zip(("temperature", "pressure", "air_quality", "climate_temperature", "humidity",
                                     "oxygen_level", "oxygen_rate"), want[:7], values):
                self.assertAlmostEqual(w, got, places=PLACES, msg=name)
            self.assertEqual(want[7], tuple(bool(int(x)) for x in row[7:10]), row)


@needs("FMOFP_UTILITIES_TOOL")
class HydraulicsOracleTest(unittest.TestCase):
    def test_the_config_the_backup_switch_and_the_thresholds(self):
        import FMOFP.Systems.hydraulics.hydrControl as hyd_module
        with mock.patch.object(hyd_module, "logger"):
            hyd = hyd_module.HydraulicSystemController()
            self.assertEqual("Main hydraulic system", hyd.active_system["description"])
            hyd.activate_backup()
            self.assertEqual("Backup hydraulic system", hyd.get_status()["active_system"])
        tool = UtilitiesTool()
        tool.send("hyd config", "hyd data", "hyd monitor 2800.0 2950.0", "hyd data", "hyd monitor 2500.0 2950.0",
                  "hyd data", "hyd monitor 2000.0 2950.0", "hyd data", "hyd monitor 3000.0 2400.0", "hyd data",
                  "hyd reset", "hyd backup", "hyd data")
        tool.run()
        thresholds = hyd.pressure_thresholds
        self.assertEqual([float(thresholds["nominal"]), float(thresholds["warning"]), float(thresholds["critical"])],
                         [float(x) for x in tool.line()], "hydrConfig.xml's thresholds")
        self.assertEqual(["PRIMARY", "OK", "0", "0"], tool.line())
        self.assertEqual(["ok"], tool.line())
        self.assertEqual(["PRIMARY", "OK", "2800", "2950"], tool.line(), "the Python's constant: OK, as it logged")
        self.assertEqual(["ok"], tool.line())
        self.assertEqual(["PRIMARY", "WARNING", "2500", "2950"], tool.line(), "at the warning threshold")
        self.assertEqual(["ok"], tool.line())
        self.assertEqual(["BACKUP", "CRITICAL", "2000", "2950"], tool.line(), "critical: the backup takes over")
        self.assertEqual(["ok"], tool.line())
        self.assertEqual(["BACKUP", "WARNING", "3000", "2400"], tool.line(), "the backup's pressure is judged now")
        self.assertEqual(["ok"], tool.line())
        self.assertEqual(["ok"], tool.line())
        self.assertEqual("BACKUP", tool.line()[0], "activate_backup by hand")


@needs("FMOFP_UTILITIES_TOOL")
class AirframeOracleTest(unittest.TestCase):
    def test_the_sensor_table_and_the_gear_state_machine(self):
        import FMOFP.Systems.airframeSystemManagement.airframeControl as afr_module
        with mock.patch.object(afr_module, "logger") as logger:
            afr = afr_module.AirframeSystemManager()
            self.assertEqual("UNKNOWN", afr.gear_state)
            states = [afr.control_landing_gear("deploy"), afr.control_landing_gear("deploy"),
                      afr.control_landing_gear("retract"), afr.control_landing_gear("bogus")]
            self.assertEqual(["DEPLOYED", "DEPLOYED", "RETRACTED", "RETRACTED"], states)
            self.assertTrue(any("Ignoring unknown gear command" in msg for msg in logged(logger, "warning")))
            # Readings: logged, never judged (asmConfig.xml has no limits).
            afr.monitor_airframe()
            self.assertTrue(any("No sensor source" in msg for msg in logged(logger, "warning")))
            for sensor_id, value in ((1, 185.0), (2, 112.0), (3, -5.25)):
                afr.set_sensor_reading(sensor_id, value)
            logger.info.reset_mock()
            afr.monitor_airframe()
            self.assertEqual(3, logger.info.call_count)
        tool = UtilitiesTool()
        tool.send("afr config", "afr data", "afr gear deploy", "afr gear deploy", "afr gear retract", "afr gear bogus",
                  "afr sensors 185.0 112.0 -5.25", "afr data")
        tool.run()
        sensors = [tuple(s.split("|")) for s in tool.raw().split(";")]
        self.assertEqual([(str(s["id"]), s["type"], s["location"]) for s in afr.sensors], sensors)
        self.assertEqual(["UNKNOWN", "0", "0", "0", "0"], tool.line())
        self.assertEqual(["DEPLOYED"], tool.line())
        self.assertEqual(["DEPLOYED"], tool.line())
        self.assertEqual(["RETRACTED"], tool.line())
        self.assertEqual(["error", "deploy|retract"], tool.line())
        self.assertEqual(["ok"], tool.line())
        row = tool.line()
        self.assertEqual("RETRACTED", row[0])
        self.assertEqual([185.0, 112.0, -5.25, 1.0], [float(x) for x in row[1:]])


@needs("FMOFP_UTILITIES_TOOL")
class FdmOracleTest(unittest.TestCase):
    def test_the_config_tables_and_the_card_ejection(self):
        import FMOFP.Systems.flightDataMonitoring.fdmControl as fdm_module
        with mock.patch.object(fdm_module, "logger") as logger:
            fdm = fdm_module.FlightDataMonitoring()
            fdm.eject_storage(1)
            fdm.eject_storage(3)
            self.assertTrue(any("Ejecting FDR PCMCIA Card" in msg for msg in logged(logger)))
            self.assertTrue(any("No storage card in slot 3" in msg for msg in logged(logger, "warning")))
        tool = UtilitiesTool()
        tool.send("fdm config", "fdm data", "fdm eject 1", "fdm eject 1", "fdm eject 3", "fdm eject 2",
                  "fdm record 50 12345.0 420.5", "fdm record 75 12350.0 421.0", "fdm data")
        tool.run()
        recorders_text, cards_text = tool.raw().split("#")
        recorders = []
        for item in recorders_text.split(";"):
            rec_id, description, rec_type, *params = item.split("|")
            recorders.append({"id": int(rec_id), "description": description, "type": rec_type,
                              "parameters": [{"name": p.rsplit(" ", 1)[0], "units": p.rsplit(" ", 1)[1]} for p in params]})
        self.assertEqual(fdm.recorders, recorders, "fdmsConfig.xml's recorders and parameters")
        cards = []
        for item in cards_text.split(";"):
            slot, description, capacity, contents = item.split("|")
            cards.append({"slot": int(slot), "description": description, "capacity": int(capacity), "contents": contents})
        self.assertEqual(fdm.storage, cards, "fdmsConfig.xml's storage cards")
        self.assertEqual(["0", "0", "1", "1", "0", "0", "0"], tool.line(), "no records, both cards in")
        self.assertEqual(["1"], tool.line(), "the FDR card ejected")
        self.assertEqual(["0"], tool.line(), "no card in slot 1 any more (the Python would have logged Ejecting again)")
        self.assertEqual(["0"], tool.line(), "no slot 3")
        self.assertEqual(["1"], tool.line())
        self.assertEqual(["ok"], tool.line())
        self.assertEqual(["ok"], tool.line())
        row = tool.line()
        self.assertEqual(["2", "2", "0", "0", "75"], row[:5], "recording goes on with both cards out")
        self.assertEqual([12350.0, 421.0], [float(x) for x in row[5:]])


class UtilitiesQuirkTest(unittest.TestCase):
    """The frozen Python's behaviour the port keeps or departs from (ICD README section 2)."""

    def test_the_ecs_never_read_its_config_and_its_rate_changes_nothing(self):
        import FMOFP.Systems.enviornmentalControlSystem.ecsControl as ecs_module
        source = inspect.getsource(ecs_module)
        self.assertNotIn("ecsConfig", source, "the limits of ecsConfig.xml are never read")
        self.assertIn("target_temp = 22.0", source)
        self.assertIn("target_pressure = 101.3", source)
        self.assertIn("current_quality < 95", source)
        with mock.patch.object(ecs_module, "logger"):
            ecs = ecs_module.ECSControl()
            ecs.oxygen.adjust_generation_rate(5.0)
            ecs.oxygen.generate_oxygen()
            self.assertAlmostEqual(21.1, ecs.oxygen.oxygen_level, msg="+0.1 whatever the rate")

    def test_the_hydraulics_monitor_compared_a_constant_for_equality(self):
        import FMOFP.Systems.hydraulics.hydrControl as hyd_module
        source = inspect.getsource(hyd_module.HydraulicSystemController.monitor_pressure)
        self.assertIn("current_pressure = 2800", source)
        self.assertIn('current_pressure == self.pressure_thresholds["critical"]', source)
        self.assertIn('current_pressure == self.pressure_thresholds["warning"]', source)
        with mock.patch.object(hyd_module, "logger") as logger:
            hyd = hyd_module.HydraulicSystemController()
            hyd.monitor_pressure()
            self.assertIn("Hydraulic pressure: 2800 psi, Status: OK", logged(logger))
            self.assertEqual("Main hydraulic system", hyd.active_system["description"], "never switched")

    def test_the_airframe_config_has_no_limits_and_the_loop_commands_no_gear(self):
        import FMOFP.Systems.airframeSystemManagement.airframeControl as afr_module
        with mock.patch.object(afr_module, "logger"):
            afr = afr_module.AirframeSystemManager()
        self.assertEqual(3, len(afr.sensors))
        self.assertEqual({"id", "type", "location"}, set(afr.sensors[0]), "no limits in the sensor table")
        code = [line for line in inspect.getsource(afr_module.AirframeSystemManager.run).splitlines()
                if not line.strip().startswith("#")]
        self.assertNotIn("control_landing_gear", "\n".join(code), "the loop no longer commands the gear (a comment says so)")

    def test_the_recorder_logged_the_number_123(self):
        import FMOFP.Systems.flightDataMonitoring.fdmControl as fdm_module
        with mock.patch.object(fdm_module, "logger") as logger:
            fdm = fdm_module.FlightDataMonitoring()
            fdm.collect_data()
        messages = logged(logger)
        self.assertIn("  UTC Time: 123 sec", messages)
        self.assertIn("  Altitude: 123 ft", messages)
        self.assertIn("  Airspeed: 123 kts", messages)
        self.assertIn("  Audio: 123 PCM", messages)
        self.assertEqual([1, 2], fdm.get_status()["storage_slots"])


if __name__ == "__main__":
    unittest.main()
