"""The scenario engine beside the frozen one (Interfaces/scenarios/scenarioEngine.py).

The frozen engine parses the two scenario files and fires each event into a live Python object; the bus engine
parses them the same way (proved here, file for file and quirk for quirk) and turns each event into the bus
command its injector amounts to (checked here against the injectors' defaults and parameter names). The frozen
engine's clock was wall time on a thread; the bus engine's is the bus frame, checked here with a fake client.
"""

import time
import unittest
from xml.etree import ElementTree as ET

from FMOFP.Interfaces.scenarios.scenarioEngine import ScenarioEngine as FrozenEngine

from fmofp_bus.avionics import key_text
from fmofp_bus.command_port import Acknowledgement
from fmofp_bus.icd import messages as m
from fmofp_bus.icd.enums import (AvionicsCommand, DefensiveCommand, IffIdentity, LruHealth, MissionCommand,
                                 MissionPhase, RwrBand, TargetClass, ThreatType, WaypointType, WeatherCategory)
from fmofp_bus.status import Status
from fmofp_scenario.engine import (FIRST_ANONYMOUS_CONTACT, FRAMES_PER_SECOND, Firing, ScenarioEngine, Translator,
                                   describe, name_words)
from fmofp_scenario.scenario import FAILURE, TRAINING, ScenarioEvent, load_scenario, parse_events, parse_value


def as_tuples(events):
    return [(e.event_id, e.event_type, e.trigger_s, e.params) for e in events]


def by_id(scenario):
    return {e.event_id: e for e in scenario.events}


class FakeClient:
    """Records what the engine sends and acknowledges everything as queued at frame 1234."""

    def __init__(self, status=Status.OK):
        self.sent = []
        self.status = status
        self.seq = 200

    def send(self, message, rt=None):
        self.sent.append(message)
        if hasattr(message, "cmd_seq") and message.cmd_seq == 0:
            self.seq += 1
            message.cmd_seq = self.seq
        return Acknowledgement(self.status, frame=1234, cmd_seq=getattr(message, "cmd_seq", 0))


class SteppingView:
    """A bus whose frame advances by `step` every time it is asked."""

    def __init__(self, frame, step=1):
        self.frame = frame
        self.step = step

    def current_frame(self):
        frame = self.frame
        self.frame += self.step
        return frame


class StuckView:
    def current_frame(self):
        return 500


class ParseOracleTest(unittest.TestCase):
    def test_both_files_parse_as_the_frozen_engine_parsed_them(self):
        for path in (TRAINING, FAILURE):
            frozen = FrozenEngine()
            self.assertTrue(frozen.load(path))
            mine = load_scenario(path)
            self.assertEqual(as_tuples(frozen._events), as_tuples(mine.events))
            self.assertEqual(frozen._name, mine.name)
            self.assertEqual(16, len(mine.events))
            self.assertEqual(sorted(e.trigger_s for e in mine.events), [e.trigger_s for e in mine.events])
        self.assertEqual("Basic Training Scenario", load_scenario(TRAINING).name)
        self.assertEqual("Systems Failure Training", load_scenario("failureScenario.xml").name)  # by name, as load did

    def test_the_parameter_conversion_quirks_are_the_frozen_ones(self):
        root = ET.fromstring(
            '<scenario name="Quirks">'
            '<event><text>no id, no type, no time</text></event>'
            '<event id="E2" type="radar_contact" time_s="1.5"><x>1e3</x><y></y><is_stealth>false</is_stealth>'
            '<n>007</n><f>2.50</f><neg>-3</neg></event>'
            '</scenario>')
        frozen = FrozenEngine()._parse(root)
        mine = parse_events(root)
        self.assertEqual(2, len(frozen))
        self.assertEqual(2, len(mine))
        for events in (frozen, mine):  # the first event's id is a random eight characters in both
            self.assertEqual(8, len(events[0].event_id))
            self.assertEqual(("message", 0.0, {"text": "no id, no type, no time"}),
                             (events[0].event_type, events[0].trigger_s, events[0].params))
        self.assertEqual(as_tuples(frozen[1:]), as_tuples(mine[1:]))
        # a number without a point is an int, with a point a float, anything else the text (so "1e3" and "false"
        # stay text, and an empty element is "")
        self.assertEqual({"x": "1e3", "y": "", "is_stealth": "false", "n": 7, "f": 2.5, "neg": -3}, mine[1].params)
        self.assertEqual((45, 35.6, "Ka", "", "SAM-SITE-1"),
                         (parse_value("045"), parse_value("35.60"), parse_value("Ka"), parse_value(None),
                          parse_value("SAM-SITE-1")))

    def test_a_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            load_scenario("noSuchScenario.xml")


class TranslationTest(unittest.TestCase):
    def assert_encodes(self, message):
        status, words = message.encode()
        self.assertIn(status, (Status.OK, Status.CLAMPED), message)
        self.assertEqual(message.WORDS, len(words))

    def test_the_training_scenario_becomes_bus_commands(self):
        events = by_id(load_scenario(TRAINING))
        t = Translator()
        message, note = t.translate(events["MSG-001"])
        self.assertIsNone(message)
        self.assertEqual("INSTRUCTOR: Training scenario started. Proceed to first waypoint.", note)

        message, note = t.translate(events["WP-001"])
        self.assertIsInstance(message, m.MsnCmd)
        self.assertEqual((MissionCommand.ADD_WAYPOINT, WaypointType.NAV, True, 35.6, -97.2, 15000.0),
                         (message.command, message.waypoint_type, message.fly_over, message.latitude,
                          message.longitude, message.altitude))
        self.assertEqual(name_words("INGRESS"), [message.name_0, message.name_1, message.name_2, message.name_3])
        self.assertEqual("MSN_CMD ADD_WAYPOINT INGRESS 35.6000 -97.2000 15000 ft", note)
        self.assert_encodes(message)

        message, note = t.translate(events["PH-001"])
        self.assertEqual((MissionCommand.SET_PHASE, MissionPhase.INGRESS), (message.command, message.phase))
        self.assertEqual(MissionPhase.COMPLETE, t.translate(events["PH-004"])[0].phase)

        message, note = t.translate(events["WX-001"])
        self.assertIsInstance(message, m.PlantInjectWeather)
        self.assertEqual((WeatherCategory.MODERATE, 20.0, 30.0, 8.0, 0.6, 42.0),
                         (message.category, message.x_km, message.y_km, message.size, message.intensity,
                          message.reflectivity))
        self.assertEqual("PLANT_INJECT_WEATHER 20 km E 30 km N, 8 km, 42 dBZ, MODERATE", note)
        self.assert_encodes(message)
        self.assertEqual(WeatherCategory.SEVERE, t.translate(events["WX-002"])[0].category)

        message, note = t.translate(events["RC-001"])
        self.assertIsInstance(message, m.PlantInjectContact)
        self.assertEqual((1, TargetClass.UNKNOWN, IffIdentity.UNKNOWN, False, 80.0, 60.0, 25000.0, -5.0, -3.0, 0.0, 5.0),
                         (message.contact_id, message.classification, message.identity, message.is_stealth,
                          message.x_km, message.y_km, message.alt_ft, message.velocity_east, message.velocity_north,
                          message.velocity_up, message.rcs))
        self.assertEqual("PLANT_INJECT_CONTACT T01 as id 1: 80 km E 60 km N 25000 ft, UNKNOWN/UNKNOWN", note)
        self.assert_encodes(message)
        message, note = t.translate(events["RC-002"])  # the same track, now classified: the same contact id
        self.assertEqual((1, TargetClass.FIGHTER, IffIdentity.HOSTILE, 65.0, 50.0, 24000.0),
                         (message.contact_id, message.classification, message.identity, message.x_km, message.y_km,
                          message.alt_ft))

        message, note = t.translate(events["TH-001"])
        self.assertIsInstance(message, m.DefCmd)
        self.assertEqual((DefensiveCommand.INJECT_THREAT, 1, 125.0, 35.0, RwrBand.X, ThreatType.SAM, 1),
                         (message.command, message.threat_id, message.bearing, message.range, message.band,
                          message.threat_type, message.priority))
        self.assertEqual("DEF_CMD INJECT_THREAT SCEN-1 (SAM-SITE-1) 125 deg 35 nm X SAM priority 1", note)
        self.assert_encodes(message)

        self.assertEqual(name_words("OBJECTIVE"), [getattr(t.translate(events["WP-002"])[0], f"name_{i}") for i in range(4)])
        self.assertEqual(name_words("OBJECTIVE"), name_words("OBJECTIV"))  # eight characters, as MSN_CMD carries

    def test_the_failure_scenario_becomes_bus_commands(self):
        events = by_id(load_scenario(FAILURE))
        t = Translator()
        message, note = t.translate(events["FAIL-001"])
        self.assertIsInstance(message, m.AvnCmd)
        self.assertEqual((AvionicsCommand.FORCE_FAULT, LruHealth.FAULT), (message.command, message.health))
        self.assertEqual("hydraulic_system_a", key_text(message))
        self.assertTrue(note.startswith("AVN_CMD FORCE_FAULT FAULT hydraulic_system_a: HYD SYS A"), note)
        self.assert_encodes(message)
        self.assertEqual("flight_control_computer", key_text(t.translate(events["FAIL-003"])[0]))
        self.assertEqual("fuel_transfer", key_text(t.translate(events["FAIL-004"])[0]))

        message, note = t.translate(events["RC-001"])
        self.assertEqual((99, TargetClass.FIGHTER, IffIdentity.HOSTILE, 15.0, 10.0, 28000.0, 8.0, 5.0),
                         (message.contact_id, message.classification, message.identity, message.x_km, message.y_km,
                          message.alt_ft, message.velocity_east, message.velocity_north))

        message, note = t.translate(events["TH-001"])
        self.assertEqual((1, 45.0, 12.0, RwrBand.KA, ThreatType.AIR, 1),
                         (message.threat_id, message.bearing, message.range, message.band, message.threat_type,
                          message.priority))
        self.assertIn("(AAM-LAUNCH)", note)

        message, note = t.translate(events["WX-001"])
        self.assertEqual((WeatherCategory.SEVERE, 5.0, 0.0, 15.0, 0.9, 62.0),
                         (message.category, message.x_km, message.y_km, message.size, message.intensity,
                          message.reflectivity))
        message, note = t.translate(events["WP-001"])
        self.assertEqual((35.25, -98.1, 8000.0), (message.latitude, message.longitude, message.altitude))
        self.assertEqual(name_words("DIVERT"), [message.name_0, message.name_1, message.name_2, message.name_3])
        self.assertEqual(MissionPhase.EGRESS, t.translate(events["PH-001"])[0].phase)

    def test_the_injectors_defaults_and_quirks(self):
        t = Translator()
        # Each injector's defaults for a missing parameter are the frozen injector's.
        waypoint = t.translate(ScenarioEvent("W", "waypoint", 0.0, {}))[0]
        self.assertEqual((35.0, -97.0, 10000.0, name_words("WP")),
                         (waypoint.latitude, waypoint.longitude, waypoint.altitude,
                          [waypoint.name_0, waypoint.name_1, waypoint.name_2, waypoint.name_3]))
        self.assertEqual(MissionPhase.INGRESS, t.translate(ScenarioEvent("P", "phase_change", 0.0, {}))[0].phase)
        cell = t.translate(ScenarioEvent("X", "weather_cell", 0.0, {}))[0]
        self.assertEqual((WeatherCategory.MODERATE, 0.0, 0.0, 5.0, 0.7, 45.0),
                         (cell.category, cell.x_km, cell.y_km, cell.size, cell.intensity, cell.reflectivity))
        contact = t.translate(ScenarioEvent("C", "radar_contact", 0.0, {}))[0]
        self.assertEqual((FIRST_ANONYMOUS_CONTACT, TargetClass.UNKNOWN, IffIdentity.UNKNOWN, False, 50.0, 50.0, 20000.0,
                          0.0, 0.0, 0.0, 5.0),
                         (contact.contact_id, contact.classification, contact.identity, contact.is_stealth,
                          contact.x_km, contact.y_km, contact.alt_ft, contact.velocity_east, contact.velocity_north,
                          contact.velocity_up, contact.rcs))
        self.assertEqual(FIRST_ANONYMOUS_CONTACT + 1,
                         t.translate(ScenarioEvent("C", "radar_contact", 0.0, {"track_id": "ABC"}))[0].contact_id)
        threat = t.translate(ScenarioEvent("T", "threat_launch", 0.0, {}))[0]
        self.assertEqual((1, 0.0, 30.0, RwrBand.X, ThreatType.SAM, 1),
                         (threat.threat_id, threat.bearing, threat.range, threat.band, threat.threat_type,
                          threat.priority))
        self.assertEqual(2, t.translate(ScenarioEvent("T", "threat_launch", 0.0, {}))[0].threat_id)
        failure = t.translate(ScenarioEvent("F", "system_failure", 0.0, {}))[0]
        self.assertEqual((AvionicsCommand.FORCE_FAULT, LruHealth.FAULT, "unknown"),
                         (failure.command, failure.health, key_text(failure)))
        # The frozen injector's bool() of the parsed text: "false" is a non-empty string, so it is stealth.
        self.assertTrue(t.translate(ScenarioEvent("C", "radar_contact", 0.0, {"is_stealth": "false"}))[0].is_stealth)
        self.assertFalse(t.translate(ScenarioEvent("C", "radar_contact", 0.0, {"is_stealth": 0}))[0].is_stealth)
        # Names are matched whatever the case; an unknown one takes the enum's unknown value.
        self.assertEqual(RwrBand.KA, t.translate(ScenarioEvent("T", "threat_launch", 0.0, {"band": "ka"}))[0].band)
        self.assertEqual(RwrBand.UNKNOWN, t.translate(ScenarioEvent("T", "threat_launch", 0.0, {"band": "W"}))[0].band)
        self.assertEqual(ThreatType.UNK,
                         t.translate(ScenarioEvent("T", "threat_launch", 0.0, {"threat_type": "SHIP"}))[0].threat_type)
        self.assertEqual(TargetClass.UNKNOWN,
                         t.translate(ScenarioEvent("C", "radar_contact", 0.0, {"classification": "UFO"}))[0].classification)
        # The failure's state and actions.
        degraded = t.translate(ScenarioEvent("F", "system_failure", 0.0, {"system": "FCC-1", "state": "degraded"}))[0]
        self.assertEqual((LruHealth.DEGRADED, "FCC-1"), (degraded.health, key_text(degraded)))
        self.assertEqual(LruHealth.FAULT, t.translate(ScenarioEvent("F", "system_failure", 0.0, {"state": "BROKEN"}))[0].health)
        clear = t.translate(ScenarioEvent("F", "system_failure", 0.0, {"system": "FCC-1", "action": " Clear "}))[0]
        self.assertEqual((AvionicsCommand.CLEAR_FAULT, "FCC-1"), (clear.command, key_text(clear)))
        self.assertEqual(AvionicsCommand.CLEAR_ALL_FAULTS,
                         t.translate(ScenarioEvent("F", "system_failure", 0.0, {"action": "clear_all"}))[0].command)
        # A phase the ICD does not name and an event type nobody knows are skipped, with a note.
        message, note = t.translate(ScenarioEvent("P", "phase_change", 0.0, {"phase": "LOITER"}))
        self.assertIsNone(message)
        self.assertEqual("skipped: unknown mission phase 'LOITER'", note)
        message, note = t.translate(ScenarioEvent("Z", "earthquake", 0.0, {}))
        self.assertIsNone(message)
        self.assertEqual("skipped: unknown event type 'earthquake'", note)
        # A track id's digits are the contact id, kept within 1-255.
        self.assertEqual(255, t.translate(ScenarioEvent("C", "radar_contact", 0.0, {"track_id": "T0"}))[0].contact_id)
        self.assertEqual(45, t.translate(ScenarioEvent("C", "radar_contact", 0.0, {"track_id": "T300"}))[0].contact_id)


class EngineClockTest(unittest.TestCase):
    def test_events_fire_by_the_bus_frame_at_the_speed_asked(self):
        client = FakeClient()
        engine = ScenarioEngine(client, speed=1.0)
        self.assertFalse(engine.start(100))  # nothing loaded
        engine.load(TRAINING)
        self.assertTrue(engine.start(100))
        fired = engine.step(100)
        self.assertEqual(["MSG-001"], [f.event.event_id for f in fired])
        self.assertIsNone(fired[0].message)
        self.assertEqual([], engine.step(599))  # WP-001 is at T+10 s: frame 100 + 500
        fired = engine.step(600)
        self.assertEqual(["WP-001"], [f.event.event_id for f in fired])
        self.assertIsInstance(fired[0].message, m.MsnCmd)
        self.assertTrue(fired[0].queued)
        self.assertEqual(201, fired[0].ack.cmd_seq)
        self.assertEqual(1, len(client.sent))
        status = engine.status()
        self.assertEqual((True, "Basic Training Scenario", 16, 2, 10.0, 1.0, 1, 0),
                         (status["running"], status["scenario_name"], status["events_total"], status["events_fired"],
                          status["elapsed_s"], status["speed"], status["commands_queued"], status["commands_failed"]))
        self.assertEqual("WP-001", status["log"][1]["event_id"])
        self.assertEqual("OK", status["log"][1]["status"])
        # the rest at once: a late step fires everything due, in time order
        fired = engine.step(100 + 510 * FRAMES_PER_SECOND)
        self.assertEqual(14, len(fired))
        self.assertEqual("PH-004", fired[-1].event.event_id)
        self.assertTrue(engine.complete)
        self.assertFalse(engine.running)
        self.assertEqual([], engine.step(100000))
        self.assertEqual(12, len(client.sent))

        # ten times faster: WP-001 at frame 100 + 50
        engine = ScenarioEngine(FakeClient(), speed=10.0)
        engine.load(TRAINING)
        engine.start(100)
        engine.step(100)
        self.assertEqual([], engine.step(149))
        self.assertEqual(["WP-001"], [f.event.event_id for f in engine.step(150)])
        self.assertEqual(10.0, engine.status()["elapsed_s"])
        engine.stop()
        self.assertFalse(engine.running)
        self.assertEqual([], engine.step(200))

    def test_two_events_at_one_time_fire_in_file_order_and_a_failed_command_is_counted(self):
        client = FakeClient(status=Status.TIMEOUT)
        engine = ScenarioEngine(client, speed=50.0)
        engine.load(FAILURE)
        engine.start(0)
        engine.step(0)
        fired = engine.step(15)
        self.assertEqual(["FAIL-001", "MSG-002"], [f.event.event_id for f in fired])
        self.assertFalse(fired[0].queued)
        self.assertEqual(1, engine.status()["commands_failed"])
        self.assertTrue(describe(fired[0]).endswith("-> TIMEOUT"))

    def test_run_follows_a_view_and_stops_when_the_bus_stalls(self):
        engine = ScenarioEngine(FakeClient(), speed=100.0)
        engine.load(TRAINING)
        firings = engine.run(SteppingView(frame=40, step=7))
        self.assertEqual(16, len(firings))
        self.assertTrue(engine.complete)
        self.assertEqual(40, engine.start_frame)
        self.assertEqual("MSG-001", firings[0].event.event_id)
        self.assertEqual(40, firings[0].frame)
        self.assertGreaterEqual(firings[1].frame, 45)  # WP-001 at T+10 s is 5 frames in at this speed

        stuck = ScenarioEngine(FakeClient(), speed=1.0)
        stuck.load(TRAINING)
        started = time.monotonic()
        firings = stuck.run(StuckView(), stall_s=0.05, poll_s=0.001)
        self.assertLess(time.monotonic() - started, 2.0)
        self.assertEqual(["MSG-001"], [f.event.event_id for f in firings])
        self.assertTrue(stuck.stopped)
        self.assertFalse(stuck.running)
        self.assertFalse(stuck.complete)

    def test_describe_and_the_log_entry(self):
        event = ScenarioEvent("MSG-001", "message", 0.0, {"text": "hi"})
        self.assertEqual("T+0s  [message]  id=MSG-001  INSTRUCTOR: hi", describe(Firing(event, 10, None, "INSTRUCTOR: hi")))
        event = ScenarioEvent("PH-001", "phase_change", 30.0, {"phase": "INGRESS"})
        firing = Firing(event, 12, m.MsnCmd(), "MSN_CMD SET_PHASE INGRESS", Acknowledgement(Status.OK, 13, 0, 201))
        self.assertEqual("T+30s  [phase_change]  id=PH-001  MSN_CMD SET_PHASE INGRESS  -> queued at frame 13 (cmd_seq 201)",
                         describe(firing))
        self.assertEqual("T+30s  [phase_change]  id=PH-001  MSN_CMD SET_PHASE INGRESS  -> not sent",
                         describe(Firing(event, 12, m.MsnCmd(), "MSN_CMD SET_PHASE INGRESS")))
        entry = firing.as_dict()
        self.assertEqual(("PH-001", "phase_change", {"phase": "INGRESS"}, 12, "OK", 201),
                         (entry["event_id"], entry["event_type"], entry["params"], entry["frame"], entry["status"],
                          entry["cmd_seq"]))


if __name__ == "__main__":
    unittest.main()
