"""Unit 34: the themes and the holographic PFD and MFD fed from the bus.

The builders (`pfd_picture`, `mfd_picture`) are checked without Qt on a fake terminal; the rewrite of the frozen MFD's
panel methods is checked against the frozen source (every fixed value it replaces is still there, and nothing else
changed); the windows are painted offscreen under each theme, with and without bus data.
"""
import ast
import inspect
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication
    HAVE_QT = True
except ImportError:  # pragma: no cover - depends on the machine
    HAVE_QT = False

from fmofp_bus.icd import blocks as b
from fmofp_bus.icd import messages as m
from fmofp_bus.icd.enums import (FmsFlightMode, MasterArm, Ssm, StoreKind, StoreState, TargetingMode, TerminalState,
                                 WeaponsState)
from fmofp_bus.tests.test_display_feeds import (FakeTerminal, flight_payload, sample_aewc, sample_elevation, sample_link,
                                                sample_mission_status, sample_plan, sample_rwr_contacts, sample_tracks)
from fmofp_display import holographic as h
from fmofp_display.flight_feed import FlightDataFeed
from fmofp_display.radar_feed import RadarFeed
from fmofp_display.systems_feed import SystemsFeed


class NullCoordinator:
    def store_data(self, data_type, items, request_id):
        return len(items)

    def reset_data(self, data_type=None):
        pass


def stores_payload(**overrides):
    p = m.SmsStatus(state=TerminalState.NORMAL, master_arm=MasterArm.ARMED, selected_station=1, armed_count=2,
                    total_weight=4321.0, stores_released=1,
                    station_1_kind=StoreKind.MK_82, station_1_state=StoreState.ARMED, station_1_qty=3,
                    station_2_kind=StoreKind.MK_82, station_2_state=StoreState.SAFE, station_2_qty=2,
                    station_3_kind=StoreKind.JDAM, station_3_state=StoreState.EXPENDED, station_3_qty=0,
                    station_4_kind=StoreKind.AN_ALQ, station_4_state=StoreState.READY, station_4_qty=1)
    for key, value in overrides.items():
        setattr(p, key, value)
    return p


def engine_payload():
    return m.EngEngineStatus(engine_1_ssm=Ssm.NORMAL, thrust_1=81.4, n1_1=88.0, n2_1=93.0, egt_1=700.2,
                             fuel_flow_1=2400.0, oil_pressure_1=41.6)


def fuel_payload(**overrides):
    p = m.EngFuelStatus(main_left=8000.0, main_right=8000.0, center=10000.0, total=26000.0, burn_rate=5200.0)
    for key, value in overrides.items():
        setattr(p, key, value)
    return p


def full_mfd_terminal():
    t = FakeTerminal()
    t.put(m.BcastFmsFlightData(payload=flight_payload(latitude=0.0, longitude=0.0, altitude=10000.0)))
    t.put(m.BcastFmsStatus(payload=m.FmsStatus(state=TerminalState.NORMAL, flight_mode=FmsFlightMode.COMBAT,
                                               weapons=WeaponsState.ARMED, stealth_mode=True)))
    t.put(m.BcastRdrTgtStatus(payload=m.RdrTgtStatus(state=TerminalState.NORMAL, mode=TargetingMode.TARGET_SEARCH)))
    t.put_block(b.MfdRdrTgtTracks, sample_tracks(), 3)
    t.put_block(b.MfdRdrAewcTracks, sample_aewc(), 2)
    t.put(sample_mission_status())
    t.put_block(b.BcastMsnPlan, sample_plan(), 5)
    t.put(m.BcastEngEngineStatus(payload=engine_payload()))
    t.put(m.BcastEngFuelStatus(payload=fuel_payload()))
    t.put(sample_link())
    t.put(m.MfdSmsStores(payload=stores_payload()))
    t.put_block(b.BcastRdrTfrElevation, sample_elevation(), 4)
    return t


def mfd_feeds(terminal):
    systems = SystemsFeed(terminal)
    systems.stores_message = m.MfdSmsStores
    return systems, RadarFeed(terminal, NullCoordinator())


class PfdPictureTest(unittest.TestCase):
    def feeds(self, terminal):
        return FlightDataFeed(terminal), SystemsFeed(terminal)

    def test_silent_bus_is_invalid_with_no_invented_value(self):
        picture = h.pfd_picture(*self.feeds(FakeTerminal()))
        self.assertFalse(picture["valid"])
        self.assertEqual("--", str(picture["tactical"]["fuel_state"]))
        self.assertEqual("--", f"{picture['energy_state']}%"[:2])
        self.assertEqual("NO DATA", picture["tactical"]["weapon_status"])
        self.assertEqual(0, picture["tactical"]["threat_level"])
        self.assertEqual("NO FMS DATA", picture["flight_mode"])

    def test_the_flight_data_fuel_weapons_and_the_most_urgent_contact(self):
        t = FakeTerminal()
        t.put(m.BcastFmsFlightData(payload=flight_payload()))
        t.put(m.BcastFmsStatus(payload=m.FmsStatus(state=TerminalState.NORMAL, flight_mode=FmsFlightMode.COMBAT,
                                                   weapons=WeaponsState.ARMED)))
        t.put(m.BcastEngFuelStatus(payload=fuel_payload(total=12000.0)))
        t.put_block(b.BcastDefRwrContacts, sample_rwr_contacts(), 4)
        flight, systems = self.feeds(t)
        picture = h.pfd_picture(flight, systems)
        self.assertTrue(picture["valid"])
        self.assertEqual((5000.0, 420.0, 275.0, 3.5, -12.0), tuple(picture[k] for k in
                                                                    ("altitude", "airspeed", "heading", "pitch",
                                                                     "roll")))
        self.assertEqual(61, picture["energy_state"])
        self.assertEqual("NORMAL", picture["flight_mode"])
        tactical = picture["tactical"]
        self.assertEqual("ARMED", tactical["weapon_status"])
        self.assertEqual(30, tactical["fuel_state"])
        hostile = [c for c in systems.rwr_contacts() if c["hostile"]]
        first = min(hostile, key=lambda c: c["priority"])
        self.assertEqual(h.PRIORITY_LEVEL[first["priority"]], tactical["threat_level"])
        self.assertAlmostEqual((first["bearing_deg"] - 275.0) % 360.0, tactical["threat_direction"])
        self.assertEqual(len(hostile), tactical["threat_count"])

    def test_a_stale_heading_invalidates_the_picture(self):
        t = FakeTerminal()
        t.put(m.BcastFmsFlightData(payload=flight_payload(heading_ssm=Ssm.NO_COMPUTED_DATA)))
        self.assertFalse(h.pfd_picture(*self.feeds(t))["valid"])
        t.put(m.BcastFmsFlightData(payload=flight_payload()), age=5.0)
        self.assertFalse(h.pfd_picture(*self.feeds(t))["valid"], "flight data older than the staleness window")


class MfdPictureTest(unittest.TestCase):
    def test_silent_bus_draws_no_contact_and_says_no_data(self):
        picture = h.mfd_picture(*mfd_feeds(FakeTerminal()))
        tactical = picture["tactical"]
        self.assertEqual([], tactical["targets"] + tactical["friendlies"] + tactical["threats"] + tactical["waypoints"])
        status = picture["system_status"]
        self.assertEqual(("NO DATA", "NO DATA", "NO DATA", "NO FIX", "NO DATA", "NO DATA"),
                         (status["radar"], status["comms"], status["weapons"], status["navigation"], status["engine"],
                          status["stealth"]))
        self.assertEqual("--", str(status["fuel"]))
        rows = picture["rows"]
        for key in ("engine", "fuel", "weapons"):
            self.assertEqual("NO DATA", rows[key][0]["name"], key)
        self.assertEqual([], rows["inventory"])
        self.assertEqual([], rows["channels"])
        self.assertEqual("NO DATA", rows["comm_status"][0]["status"])
        self.assertEqual("SELECTED: NO DATA", picture["texts"]["selected"])
        self.assertEqual("INS: NOT CARRIED", picture["texts"]["ins"])
        self.assertEqual(0.0, picture["numbers"]["signal"])
        self.assertIsNone(picture["terrain"])

    def test_the_tracks_placed_in_the_picture(self):
        picture = h.mfd_picture(*mfd_feeds(full_mfd_terminal()))
        tactical = picture["tactical"]
        by_id = {t["id"]: t for t in tactical["targets"]}
        # The targeting radar's fighter 10 nm east, 1000 m above; its friendly helicopter 20 nm south.
        fighter = by_id["T1"]
        self.assertAlmostEqual(10.0, fighter["x"])
        self.assertAlmostEqual(0.0, fighter["y"])
        self.assertAlmostEqual(10000.0 + 1000.0 * h.FT_PER_M, fighter["altitude"])
        self.assertAlmostEqual(0.0, fighter["heading"])
        self.assertAlmostEqual(250.0 * h.KT_PER_MPS, fighter["speed"])
        self.assertEqual(("FIGHTER", 8), (fighter["type"], fighter["threat_level"]))
        self.assertEqual(["T2"], [f["id"] for f in tactical["friendlies"]])
        self.assertAlmostEqual(20.0, tactical["friendlies"][0]["y"], msg="20 nm south: down the picture")
        # The AEWC's fighter 100 nm north-east is beyond the picture's 100 nm; its stealth track 10 nm east is in.
        self.assertNotIn("A1", by_id)
        self.assertEqual("STEALTH", by_id["A2"]["type"])
        self.assertEqual({"T1", "A2"}, {t["id"] for t in tactical["threats"]})
        self.assertEqual(["IP", "TURN"], [w["id"] for w in tactical["waypoints"]])
        self.assertAlmostEqual(-0.0719 * 60.0, tactical["waypoints"][0]["y"], msg="4.3 nm north: up the picture")
        for w in tactical["waypoints"]:
            self.assertLessEqual((w["x"] ** 2 + w["y"] ** 2) ** 0.5, h.PICTURE_RADIUS_NM)

    def test_without_the_aircraft_altitude_no_track_is_drawn(self):
        t = full_mfd_terminal()
        t.put(m.BcastFmsFlightData(payload=flight_payload(altitude_ssm=Ssm.NO_COMPUTED_DATA)))
        self.assertEqual([], h.mfd_picture(*mfd_feeds(t))["tactical"]["targets"])

    def test_the_panels_from_the_engine_fuel_stores_and_comms(self):
        picture = h.mfd_picture(*mfd_feeds(full_mfd_terminal()))
        status = picture["system_status"]
        self.assertEqual(("TARGET_SEARCH", "ACTIVE", "ARMED", "NOMINAL", 65, "NOMINAL", "ACTIVE"),
                         tuple(status[k] for k in ("radar", "comms", "weapons", "navigation", "fuel", "engine",
                                                   "stealth")))
        rows = picture["rows"]
        self.assertEqual(["81%", "700°C", "88%", "42 PSI"], [r["value"] for r in rows["engine"]])
        self.assertEqual(["65%", "50%", "5200 KG/H", "5:00"], [r["value"] for r in rows["fuel"]])
        self.assertEqual("TARGETS", rows["radar"][2]["name"])
        self.assertEqual(["ARMED", "2", "4321 KG", "1"], [r["value"] for r in rows["weapons"]])
        self.assertEqual([{"name": "MK-82", "count": "5", "type": "WEAPON"},
                          {"name": "AN/ALQ", "count": "1", "type": "POD"}], rows["inventory"])
        self.assertEqual(["RADIO", "SATCOM", "DATALINK"], [c["name"] for c in rows["channels"]])
        self.assertEqual(["RADIO", "SATCOM", "DATALINK"], [c["name"] for c in rows["comm_status"]])
        self.assertEqual("SELECTED: STA 1 MK-82", picture["texts"]["selected"])
        self.assertEqual("WEAPON: MK-82", picture["texts"]["weapon"])
        self.assertTrue(picture["texts"]["messages"].startswith("DATALINK RX: "))
        self.assertGreater(picture["numbers"]["signal"], 0.0)
        self.assertEqual(20, len(picture["terrain"]))
        self.assertTrue(all(0.1 <= v <= 0.9 for row in picture["terrain"] for v in row))

    def test_a_selected_station_with_its_stores_gone_is_empty(self):
        t = full_mfd_terminal()
        t.put(m.MfdSmsStores(payload=stores_payload(selected_station=3)))
        self.assertEqual("SELECTED: STA 3 EMPTY", h.mfd_picture(*mfd_feeds(t))["texts"]["selected"])

    def test_the_fuel_colours_follow_the_engine_computer(self):
        t = full_mfd_terminal()
        t.put(m.BcastEngFuelStatus(payload=fuel_payload(total=6000.0, critical_left=True, leak_suspected=True)))
        rows = h.mfd_picture(*mfd_feeds(t))["rows"]["fuel"]
        self.assertEqual("critical", rows[0]["color"])
        self.assertEqual(("LEAK", "critical"), (rows[-1]["name"], rows[-1]["color"]))


class UnknownTest(unittest.TestCase):
    def test_prints_as_dashes_and_compares_as_normal(self):
        u = h.Unknown()
        self.assertEqual("--%", f"{u}%")
        self.assertFalse(u < 40)


@unittest.skipUnless(HAVE_QT, "PyQt6 not installed")
class RewriteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fmofp_display import app
        app.bootstrap()
        cls.base = h._holographic_mfd_class()
        cls.rebuilt = h.rewrite_methods(cls.base, h.MFD_REWRITES)

    def test_every_fixed_value_replaced_and_nothing_else(self):
        source = inspect.getsource(inspect.getmodule(self.base))
        for name, spec in h.MFD_REWRITES.items():
            frozen = getattr(self.base, name)
            node = ast.parse(inspect.cleandoc("\n" + inspect.getsource(frozen))).body[0]
            texts = [n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
            for text in spec.get("texts", {}):
                self.assertEqual(1, texts.count(text), f"{name}: {text!r}")
            code = self.rebuilt[name].__code__
            names = set(code.co_names)
            for method, key in (("_bus_rows", "lists"), ("_bus_text", "texts"), ("_bus_number", "numbers")):
                if spec.get(key):
                    self.assertIn(method, names, name)
            for text in spec.get("texts", {}):
                self.assertNotIn(text, code.co_consts, name)
        self.assertIn("MESSAGES: 2 NEW", source, "the frozen file is untouched")

    def test_a_missing_value_fails_loudly(self):
        with self.assertRaises(h.RewriteError):
            h.rewrite_methods(self.base, {"draw_navigation_data_panel": {"texts": {"INS: SOMETHING ELSE": "ins"}}})
        with self.assertRaises(h.RewriteError):
            h.rewrite_methods(self.base, {"no_such_method": {}})


def lit_pixels(image, step=3):
    return sum(1 for y in range(0, image.height(), step) for x in range(0, image.width(), step)
               if image.pixel(x, y) & 0xFFFFFF)


class StubTerminal(FakeTerminal):
    rt = 11
    state = TerminalState.NORMAL
    syncs = 0

    def take_mode_request(self):
        return None


@unittest.skipUnless(HAVE_QT, "PyQt6 not installed")
class ThemedWindowsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fmofp_display import app
        app.bootstrap()
        cls.qt = QApplication.instance() or QApplication([])
        cls.app = app

    def tearDown(self):
        self.app.apply_theme("classic")

    def test_the_themes_choose_the_classes(self):
        for theme, expected in (("classic", False), ("night", False), ("modern", True)):
            self.assertEqual(theme, self.app.apply_theme(theme))
            self.assertEqual(expected, self.app.holographic("pfd"), theme)
            self.assertEqual(expected, self.app.holographic("mfd"), theme)

    def test_the_standard_pfd_paints_under_every_theme(self):
        for theme in self.app.THEMES:
            self.app.apply_theme(theme)
            terminal = StubTerminal()
            terminal.put(m.BcastFmsFlightData(payload=flight_payload()))
            window = self.app.PfdWindow(terminal, holographic_pfd=False)
            window.resize(700, 500)
            window.show()
            window.pfd.update_flight_data()
            window.tick()
            self.qt.processEvents()
            self.assertGreater(lit_pixels(window.pfd.grab().toImage()), 0, theme)
            self.assertFalse(window.pfd._paint_error, theme)
            window.timer.stop()
            window.close()

    def test_the_holographic_pfd_crosses_out_a_silent_bus_and_draws_the_fms(self):
        self.app.apply_theme("modern")
        terminal = StubTerminal()
        window = self.app.PfdWindow(terminal)
        self.assertTrue(window.holographic)
        self.assertTrue(type(window.pfd).PROVIDES_FLIGHT_DATA)
        window.resize(700, 500)
        window.show()
        window.tick()
        self.qt.processEvents()
        silent = window.pfd.grab().toImage()
        self.assertFalse(window.pfd.picture_valid)
        terminal.put(m.BcastFmsFlightData(payload=flight_payload()))
        terminal.put(m.BcastEngFuelStatus(payload=fuel_payload()))
        terminal.put_block(b.BcastDefRwrContacts, sample_rwr_contacts(), 4)
        window.tick()
        self.qt.processEvents()
        live = window.pfd.grab().toImage()
        self.assertTrue(window.pfd.picture_valid)
        self.assertEqual((5000.0, 420.0, 275.0), (window.pfd.altitude, window.pfd.airspeed, window.pfd.heading))
        self.assertEqual(window.pfd.altitude, window.pfd.target_altitude, "no autopilot bug at a fixed 30000 ft")
        self.assertEqual(65, window.pfd.tactical_data["fuel_state"])
        self.assertFalse(window.pfd._paint_error)
        self.assertNotEqual(silent, live)
        window.timer.stop()
        window.close()

    def test_the_holographic_mfd_paints_every_page_from_the_bus(self):
        self.app.apply_theme("modern")
        terminal = full_mfd_terminal()
        terminal.rt, terminal.state, terminal.syncs = 13, TerminalState.NORMAL, 0
        terminal.take_mode_request = lambda: None
        window = self.app.HolographicMfdWindow(terminal)
        window.resize(900, 700)
        window.show()
        window.tick()
        mfd = window.mfd
        self.assertEqual({"T1", "A2"}, {t["id"] for t in mfd.tactical_data["threats"]})
        self.assertEqual(65, mfd.system_status["fuel"])
        for page in mfd.available_modes:
            mfd.display_mode = page
            window.tick()
            self.qt.processEvents()
            self.assertGreater(lit_pixels(mfd.grab().toImage()), 0, page)
            self.assertFalse(mfd._paint_error, page)
        window.timer.stop()
        window.close()

    def test_the_holographic_mfd_paints_a_silent_bus(self):
        self.app.apply_theme("modern")
        terminal = StubTerminal()
        terminal.rt = 13
        window = self.app.HolographicMfdWindow(terminal)
        window.resize(900, 700)
        window.show()
        for page in window.mfd.available_modes:
            window.mfd.display_mode = page
            window.tick()
            self.qt.processEvents()
            window.mfd.grab()
            self.assertFalse(window.mfd._paint_error, page)
        self.assertEqual([], window.mfd.tactical_data["targets"])
        window.timer.stop()
        window.close()


if __name__ == "__main__":
    unittest.main()
