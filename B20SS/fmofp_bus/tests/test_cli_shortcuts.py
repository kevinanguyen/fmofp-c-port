"""Unit 35: the prompt's shortcuts (upstream's canned messages by name), its display modes and its test suites.

The first classes run on a fake bus; the last runs the real radar computer and a display terminal under the real
controller and drives them from the prompt (needs FMOFP_BC and FMOFP_RADAR).
"""

import ast
import os
import subprocess
import time
import unittest

from fmofp_bus.bus_view import BusView
from fmofp_bus.command_port import CommandClient
from fmofp_bus.icd import messages as m
from fmofp_bus.icd.enums import (ControlSurface, DisplayMode, FmsFlightMode, Maneuver, TargetingMode, TerminalState,
                                 TrackFilter, WeatherMode)
from fmofp_bus.status import Status
from fmofp_bus.tests._support import binary_env, free_port_base, needs
from fmofp_bus.tests.test_cli import FakeClient, FakeView
from fmofp_cli import shortcuts, suites
from fmofp_cli.cli import DebugCli, parse_field
from fmofp_demo import demo
from fmofp_display.terminal import DisplayTerminal

PORT_BASE = free_port_base(63750)
TESTS_DIR = os.path.join(suites.B20SS, "fmofp_bus", "tests")
# The canned builders of upstream's Interfaces/predefinedMessages, as git shows them at the cut (unit 29).
UPSTREAM_BUILDERS = {
    "WeatherRadarMessages": ("create_weather_radar_mode_change_request", "create_precipitation_request",
                             "create_vil_request", "create_echo_top_request"),
    "TFRRadarMessages": ("create_tfr_elevation_data_request",),
    "TargetingRadarMessages": ("create_targeting_radar_track_request", "create_targeting_radar_lock_request"),
    "AEWCRadarMessages": ("create_aewc_radar_track_request", "create_aewc_radar_sector_scan_request"),
    "SARRadarMessages": ("create_sar_imagery_request",),
    "FMSMessages": ("create_attitude_update_request", "create_navigation_update_request", "create_maneuver_request"),
    "FCSMessages": ("create_control_surface_request", "create_flight_mode_request", "create_autopilot_request"),
}


def build(name, *args):
    return shortcuts.build(shortcuts.BY_NAME[name], list(args), parse_field)


class ShortcutTest(unittest.TestCase):
    def test_every_upstream_builder_has_a_shortcut_or_a_reading(self):
        named = {s.origin.split(" ")[0] for s in shortcuts.SHORTCUTS} | {r.origin.split(" ")[0]
                                                                          for r in shortcuts.READINGS}
        for cls, builders in UPSTREAM_BUILDERS.items():
            for builder in builders:
                self.assertIn(f"{cls}.{builder}", named)

    def test_the_radar_shortcuts(self):
        self.assertEqual(200.0, build("wx", "MAPPING").range_km, "the radar window's default range")
        wx = build("wx", "surveillance", "150", "tilt=2")
        self.assertEqual((TerminalState.NORMAL, WeatherMode.SURVEILLANCE, 150.0, 2.0, 0),
                         (wx.requested_state, wx.requested_mode, wx.range_km, wx.tilt, wx.cmd_seq))
        self.assertEqual(TerminalState.STANDBY, build("wx", "NONE").requested_state, "mode NONE stands the radar by")
        lock = build("tgt-lock", "3")
        self.assertEqual((TargetingMode.TARGET_TRACK, 3), (lock.requested_mode, lock.lock_track_id))
        self.assertEqual(TrackFilter.HOSTILE, build("tgt", "TARGET_SEARCH", "HOSTILE").track_filter)
        sector = build("aewc-sector", "10", "80")
        self.assertEqual(("SECTOR_SCAN", 10.0, 80.0), (sector.requested_mode.name, sector.azimuth_start,
                                                       sector.azimuth_end))
        self.assertEqual(500.0, build("tfr", "TERRAIN_FOLLOWING", "500").set_clearance)
        self.assertEqual(3.0, build("sar", "STRIPMAP", "3").resolution)

    def test_the_fms_and_fcs_shortcuts_set_the_present_bits(self):
        att = build("attitude", "roll=10", "pitch_rate=2")
        self.assertEqual((True, False, False, True, 10.0, 2.0),
                         (att.roll_present, att.pitch_present, att.yaw_present, att.pitch_rate_present, att.roll,
                          att.pitch_rate))
        for name in ("nav", "autopilot"):
            nav = build(name, "altitude=12000", "heading=90")
            self.assertIsInstance(nav, m.FmsNavUpdateCmd)
            self.assertEqual((True, False, True, False, 12000.0, 90.0),
                             (nav.altitude_present, nav.airspeed_present, nav.heading_present,
                              nav.vertical_speed_present, nav.altitude, nav.heading))
        self.assertEqual((Maneuver.DIVE, 30.0), (build("maneuver", "dive", "30").maneuver,
                                                 build("maneuver", "dive", "30").dive_angle))
        surface = build("surface", "AILERONS", "5")
        self.assertEqual((ControlSurface.AILERONS, 5.0), (surface.surface, surface.position))
        self.assertEqual(FmsFlightMode.COMBAT, build("flight-mode", "combat").flight_mode)

    def test_wrong_arguments_say_what_is_wanted(self):
        for args, text in ((("wx",), "missing REQUESTED_MODE"), (("wx", "SURVEILLANCE", "1", "2", "3"), "too many"),
                           (("attitude",), "at least one of roll="), (("wx", "SURVEILLANCE", "bogus=1"), "no field"),
                           (("wx", "SIDEWAYS"), "is not one of")):
            with self.assertRaises(ValueError) as caught:
                build(*args)
            self.assertIn(text, str(caught.exception))

    def test_every_shortcut_encodes(self):
        examples = {"wx": ("SURVEILLANCE",), "tfr": ("TFR_SEARCH",), "sar": ("STRIPMAP",), "tgt": ("TARGET_SEARCH",),
                    "tgt-lock": ("1",), "aewc": ("AEWC_SEARCH",), "aewc-sector": ("0", "90"),
                    "attitude": ("roll=5",), "nav": ("airspeed=400",), "autopilot": ("altitude=9000",),
                    "maneuver": ("BREAK_LEFT",), "surface": ("ELEVATOR", "-3"), "flight-mode": ("STEALTH",)}
        self.assertEqual(set(shortcuts.BY_NAME), set(examples))
        for name, args in examples.items():
            status, _ = build(name, *args).encode()
            self.assertEqual(Status.OK, status, name)


class PromptTest(unittest.TestCase):
    def setUp(self):
        self.view = FakeView()
        self.client = FakeClient()
        self.lines = []
        self.runs = []
        self.cli = DebugCli(self.view, self.client, out=self.lines.append, build_dir="BUILD",
                            run_tests=lambda modules, build_dir, out: self.runs.append((modules, build_dir)) or 0)

    def tearDown(self):
        self.cli.close()

    def test_do_lists_sends_and_reads(self):
        self.cli.execute("do")
        text = "\n".join(self.lines)
        for name in list(shortcuts.BY_NAME) + list(shortcuts.READING_BY_NAME):
            self.assertIn(f"  do {name}", text)
        self.lines.clear()
        self.cli.execute("do wx MAPPING 100")
        rt, message = self.client.sent[-1]
        self.assertEqual((9, WeatherMode.MAPPING, 100.0), (rt, message.requested_mode, message.range_km))
        self.assertEqual("RDR_WX_MODE_CMD -> RT 9 SA 1: OK, queued at frame 1300 (cmd_seq 101)", self.lines[-1])
        self.lines.clear()
        self.cli.execute("do vil")
        self.assertIn("VIL", self.lines[0])
        self.assertEqual("no RDR_WX_SCAN seen yet", self.lines[-1])
        self.cli.execute("do nothing-such")
        self.assertIn("no shortcut 'nothing-such'", self.lines[-1])

    def test_mode_sends_every_display_its_mode(self):
        self.cli.execute("mode night")
        sent = {rt: message for rt, message in self.client.sent}
        self.assertEqual({15, 11, 13, 14, 16, 17}, set(sent))
        for message in sent.values():
            self.assertEqual((TerminalState.NORMAL, DisplayMode.NIGHT), (message.requested_state,
                                                                           message.requested_mode))
        self.client.sent.clear()
        self.cli.execute("mode NVG pfd mfd")
        self.assertEqual([11, 13], [rt for rt, _ in self.client.sent])
        for line in ("mode", "mode DUSK", "mode NOT_SET", "mode DAY hud"):
            self.lines.clear()
            self.cli.execute(line)
            self.assertTrue(self.lines[-1].startswith("error: "), line)

    def test_test_lists_and_runs_suites(self):
        self.cli.execute("test list")
        text = "\n".join(self.lines)
        self.assertIn("1)  precip-vil", text)
        self.assertIn("9)  aewc", text)
        self.lines.clear()
        self.cli.execute("test 2 fcs test_word")
        self.assertEqual([(["test_fms_e2e", "test_fcs_e2e", "test_word"], "BUILD")], self.runs)
        self.assertEqual("test: OK", self.lines[-1])
        self.cli.execute("test weather-ish")
        self.assertIn("no suite 'weather-ish'", self.lines[-1])


class SuitesTest(unittest.TestCase):
    def test_every_suite_module_exists_and_all_is_in_order_once(self):
        for suite in suites.SUITES:
            for module in suite.modules:
                self.assertTrue(os.path.isfile(os.path.join(TESTS_DIR, f"{module}.py")), module)
        every = suites.resolve(["all"])
        self.assertEqual(len(every), len(set(every)))
        self.assertEqual(["test_weather_oracle", "test_radar_e2e"], suites.resolve(["1"]))

    def test_the_nine_upstream_suites_in_its_order(self):
        upstream = ("Combined Precipitation & VIL Flow Test", "FMS System Test", "Flight Control System Test",
                    "Predefined Messages Test", "Weather Radar Test (All Modes)", "TFR Radar Test (All Modes)",
                    "SAR Radar Test (All Modes)", "Targeting Radar Test (All Modes)", "AEWC Radar Test (All Modes)")
        self.assertEqual(upstream, tuple(s.title for s in suites.SUITES[:9]))

    def test_the_binary_environment(self):
        root = os.path.join(suites.B20SS, "fmofp_bus", "tests", "_no_such_build")
        env = suites.binary_env(root, env={"PATH": "x"})
        self.assertNotIn("FMOFP_BC", env)
        self.assertEqual("offscreen", env["QT_QPA_PLATFORM"])

    def test_a_suite_runs_in_a_child_process(self):
        lines = []
        code = suites.run(["test_word"], os.path.join(suites.B20SS, "ofp", "build", "none"), lines.append)
        self.assertEqual(0, code, "\n".join(lines))
        self.assertTrue(any(line.startswith("Ran ") for line in lines))


class DemoModeTest(unittest.TestCase):
    def test_the_demo_sends_the_mode_to_every_display(self):
        events = demo.mode_events("nvg")
        self.assertEqual(6, len(events))
        for event in events:
            self.assertEqual((0.5, DisplayMode.NVG, 201), (event.seconds, event.message.requested_mode,
                                                           event.message.cmd_seq))
        with open(demo.__file__, encoding="utf-8") as f:
            source = f.read()
        self.assertIn('"--mode"', source)
        tree = ast.parse(source)
        self.assertTrue(any(isinstance(n, ast.FunctionDef) and n.name == "mode_events" for n in tree.body))


@needs("FMOFP_BC", "FMOFP_RADAR")
class PromptOnTheBusTest(unittest.TestCase):
    def test_a_shortcut_moves_the_radar_and_mode_the_display(self):
        display = DisplayTerminal(m.DspPfdStatus.RT, PORT_BASE, m.DspPfdStatus, m.DspPfdModeCmd)
        self.assertEqual(Status.OK, display.start(), "display port in use?")
        radar = subprocess.Popen([os.environ["FMOFP_RADAR"], "--port-base", str(PORT_BASE), "--quiet"],
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=binary_env())
        view = BusView(PORT_BASE)
        self.assertEqual(Status.OK, view.open(), "monitor port in use?")
        view.start()
        client = CommandClient(PORT_BASE, timeout_s=2.0)
        self.assertEqual(Status.OK, client.open())
        lines = []
        cli = DebugCli(view, client, out=lines.append)
        time.sleep(0.3)
        bc = subprocess.Popen([os.environ["FMOFP_BC"], "--rt", "9", "--rt", "11", "--port-base", str(PORT_BASE),
                               "--frames", "400", "--timeout-ms", "20"], stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True, env=binary_env())
        try:
            self.assertTrue(view.wait_for_frame(60, 10.0), "the bus did not start")
            cli.execute("do wx SURVEILLANCE 150")
            self.assertIn("RDR_WX_MODE_CMD -> RT 9 SA 1: OK, queued", lines[-1])
            cli.execute("mode NIGHT pfd")
            self.assertIn("DSP_PFD_MODE_CMD -> RT 11 SA 11: OK, queued", lines[-1])
            deadline = time.monotonic() + 5.0
            status = None
            while time.monotonic() < deadline:
                status = view.snapshot()["latest"].get(m.RdrWxStatus)
                if (status is not None and status.mode == WeatherMode.SURVEILLANCE
                        and display.display_mode == DisplayMode.NIGHT):
                    break
                time.sleep(0.05)
            self.assertEqual(WeatherMode.SURVEILLANCE, status.mode if status else None)
            self.assertEqual(DisplayMode.NIGHT, display.display_mode)
            lines.clear()
            cli.execute("do precipitation")
            self.assertTrue(any(line.startswith("RDR_WX_SCAN:") for line in lines), lines)
        finally:
            output = bc.stdout.read()
            bc.stdout.close()
            code = bc.wait(timeout=60)
            cli.close()
            client.close()
            view.close()
            radar.kill()
            radar.wait(timeout=10)
            radar.stdout.close()
            display.stop()
        self.assertEqual(0, code, output)


if __name__ == "__main__":
    unittest.main()
