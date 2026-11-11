"""The debug CLI: its parsing and output on a fake bus, then its commands against the real controller and the
plant (the second class needs FMOFP_BC)."""

import math
import os
import subprocess
import tempfile
import threading
import time
import unittest

from fmofp_bus.bus_view import BusView
from fmofp_bus.command_port import Acknowledgement, CommandClient
from fmofp_bus.icd import messages as m
from fmofp_bus.icd.enums import IffIdentity, MissionCommand, MissionPhase, TargetClass, TerminalState, WeatherCategory
from fmofp_bus.status import Status
from fmofp_bus.tests._support import binary_env, free_port_base
from fmofp_cli.cli import DebugCli, parse_field
from fmofp_plant.plant import PlantModel, PlantTerminal
from fmofp_scenario.scenario import TRAINING

PORT_BASE = free_port_base(59500)
PLANT_RT = m.PlantSensors.RT
FRAMES = 300

TINY_SCENARIO = """<?xml version="1.0" encoding="UTF-8"?>
<scenario name="CLI check" version="1.0">
  <event id="M" type="message" time_s="0"><text>hello</text></event>
  <event id="W" type="weather_cell" time_s="0.5"><x>5.0</x><y>5.0</y><reflectivity>50</reflectivity></event>
  <event id="C" type="radar_contact" time_s="1"><track_id>T07</track_id><x>10.0</x><y>10.0</y></event>
</scenario>
"""


class FakeView:
    def __init__(self):
        self.frame = 1234
        self.latest = {}
        self.term_status = {}
        self.last_answer = {}
        self.last_poll = {}

    def current_frame(self):
        return self.frame

    def snapshot(self):
        return dict(frame=self.frame, records=0, latest=dict(self.latest), term_status=dict(self.term_status),
                    last_answer=dict(self.last_answer), last_poll=dict(self.last_poll))


class FakeClient:
    def __init__(self):
        self.sent = []

    def send(self, message, rt=None):
        self.sent.append((message.RT if rt is None else rt, message))
        if hasattr(message, "cmd_seq") and message.cmd_seq == 0:
            message.cmd_seq = 201
        return Acknowledgement(Status.OK, frame=1300, cmd_seq=getattr(message, "cmd_seq", 0))


class DebugCliParsingTest(unittest.TestCase):
    def setUp(self):
        self.view = FakeView()
        self.client = FakeClient()
        self.lines = []
        self.cli = DebugCli(self.view, self.client, out=self.lines.append)

    def tearDown(self):
        self.cli.close()

    def text(self):
        return "\n".join(self.lines)

    def test_send_builds_a_message_from_fields(self):
        self.assertTrue(self.cli.execute("send PLANT_INJECT_WEATHER x_km=10 y_km=-20.5 size=5 reflectivity=50 category=severe"))
        self.assertEqual(1, len(self.client.sent))
        rt, message = self.client.sent[0]
        self.assertEqual(PLANT_RT, rt)
        self.assertIsInstance(message, m.PlantInjectWeather)
        self.assertEqual((10.0, -20.5, 5.0, 50.0, WeatherCategory.SEVERE, 201),
                         (message.x_km, message.y_km, message.size, message.reflectivity, message.category, message.cmd_seq))
        self.assertEqual("PLANT_INJECT_WEATHER -> RT 27 SA 22: OK, queued at frame 1300 (cmd_seq 201)", self.lines[-1])
        self.cli.execute("send PlantInjectContact contact_id=0x07 is_stealth=true classification=FIGHTER identity=2")
        _, contact = self.client.sent[-1]
        self.assertEqual((7, True, TargetClass.FIGHTER, IffIdentity.HOSTILE),
                         (contact.contact_id, contact.is_stealth, contact.classification, contact.identity))
        self.cli.execute("send MSN_CMD command=SET_PHASE phase=INGRESS")
        _, msn = self.client.sent[-1]
        self.assertEqual((MissionCommand.SET_PHASE, MissionPhase.INGRESS), (msn.command, msn.phase))

    def test_send_refuses_what_it_cannot_build(self):
        self.cli.execute("send")
        self.assertIn("error: send ID", self.lines[-1])
        self.cli.execute("send NOPE x=1")
        self.assertIn("unknown message 'NOPE'", self.lines[-1])
        self.cli.execute("send PLANT_GPS epoch=1")
        self.assertIn("transmit message", self.lines[-1])
        self.cli.execute("send PLANT_INJECT_WEATHER bogus=1")
        self.assertIn("no field 'bogus'", self.lines[-1])
        self.assertIn("x_km", self.lines[-1])
        self.cli.execute("send PLANT_INJECT_WEATHER x_km=abc")
        self.assertIn("not a number", self.lines[-1])
        self.cli.execute("send PLANT_INJECT_WEATHER category=FOO")
        self.assertIn("not one of UNKNOWN, LIGHT, MODERATE, SEVERE, EXTREME", self.lines[-1])
        self.cli.execute("send PLANT_INJECT_CONTACT is_stealth=maybe")
        self.assertIn("not a boolean", self.lines[-1])
        self.cli.execute("send PLANT_INJECT_CONTACT contact_id")
        self.assertIn("name=value", self.lines[-1])
        self.cli.execute("send TERM_CMD requested_state=NORMAL")
        self.assertIn("rt=N", self.lines[-1])
        self.assertEqual([], self.client.sent)
        self.cli.execute("send TERM_CMD rt=plant requested_state=NORMAL")
        rt, message = self.client.sent[-1]
        self.assertEqual((PLANT_RT, TerminalState.NORMAL, 201), (rt, message.requested_state, message.cmd_seq))

    def test_parse_field_types(self):
        self.assertEqual(7, parse_field(m.PlantInjectContact, "contact_id", "7"))
        self.assertEqual(255, parse_field(m.PlantInjectContact, "contact_id", "0xff"))
        self.assertEqual(-3.5, parse_field(m.PlantInjectContact, "x_km", "-3.5"))
        self.assertIs(False, parse_field(m.PlantInjectContact, "is_stealth", "off"))
        self.assertEqual(TargetClass.DRONE, parse_field(m.PlantInjectContact, "classification", "drone"))
        self.assertEqual(TargetClass.DRONE, parse_field(m.PlantInjectContact, "classification", "6"))
        with self.assertRaises(ValueError):
            parse_field(m.PlantInjectContact, "contact_id", "seven")

    def test_status_and_messages_from_the_view(self):
        self.cli.execute("frame")
        self.assertEqual("frame 1234 (24.7 s on the bus)", self.lines[-1])
        self.cli.execute("terminals")
        self.assertIn("no terminal seen yet", self.lines[-1])
        self.cli.execute("msgs")
        self.assertIn("no message seen yet", self.lines[-1])
        self.view.term_status[PLANT_RT] = m.TermStatus(state=TerminalState.NORMAL, healthy=True, icd_major=1, icd_minor=23)
        self.view.last_answer[PLANT_RT] = self.view.last_poll[PLANT_RT] = time.monotonic()
        self.view.last_poll[9] = time.monotonic()
        self.view.latest[m.PlantGps] = m.PlantGps(epoch=3)
        self.view.latest[(m.TermStatus, PLANT_RT)] = self.view.term_status[PLANT_RT]
        self.lines.clear()
        self.cli.execute("terminals")
        self.assertIn("frame 1234: 2 terminals", self.lines[0])
        self.assertIn("RT  9 radar          (no TERM_STATUS yet)", self.lines[1])
        self.assertIn("never answered", self.lines[1])
        self.assertIn("RT 27 plant          NORMAL       healthy=1 faults=0 icd=1.23", self.lines[2])
        self.assertIn("answered 0.0 s ago", self.lines[2])
        self.lines.clear()
        self.cli.execute("status plant")
        self.assertIn("RT 27 (plant) TERM_STATUS: state=NORMAL", self.lines[0])
        self.assertIn("PLANT_GPS: epoch=3", self.lines[1])
        self.lines.clear()
        self.cli.execute("status 9")
        self.assertIn("RT 9 (radar): no TERM_STATUS seen; it has not answered a poll", self.lines[0])
        self.assertIn("no message of its own seen", self.lines[1])
        self.cli.execute("status nowhere")
        self.assertIn("no terminal 'nowhere'", self.lines[-1])
        self.lines.clear()
        self.cli.execute("msgs")
        self.assertEqual(["TERM_STATUS from RT 27", "PLANT_GPS"], self.lines)
        self.lines.clear()
        self.cli.execute("msg PLANT_GPS")
        self.assertEqual("PLANT_GPS:", self.lines[0])
        self.assertIn("  epoch = 3", self.lines)
        self.cli.execute("msg MSN_STATUS")
        self.assertEqual("no MSN_STATUS seen yet", self.lines[-1])
        self.cli.execute("msg MSN_CMD")
        self.assertIn("a receive message", self.lines[-1])
        self.cli.execute("msg TERM_STATUS")
        self.assertIn("every terminal has one", self.lines[-1])
        self.cli.execute("msg TERM_STATUS 27")
        self.assertIn("  healthy = 1", self.lines)
        self.cli.execute("msg NOPE")
        self.assertIn("unknown message 'NOPE'", self.lines[-1])

    def test_help_quit_and_unknown_commands(self):
        self.assertTrue(self.cli.execute(""))
        self.assertTrue(self.cli.execute("help"))
        self.assertIn("send ID [field=value ...]", self.text())
        self.assertTrue(self.cli.execute("dance"))
        self.assertIn("unknown command 'dance'", self.lines[-1])
        self.assertFalse(self.cli.execute("quit"))
        self.assertFalse(self.cli.execute("exit"))

    def test_scenario_commands(self):
        self.cli.execute("scenario events")
        self.assertIn("no scenario loaded", self.lines[-1])
        self.cli.execute("scenario status")
        self.assertEqual("no scenario loaded", self.lines[-1])
        self.cli.execute("scenario load noSuchScenario.xml")
        self.assertIn("cannot load", self.lines[-1])
        self.cli.execute(f"scenario load {TRAINING}")
        self.assertEqual("loaded 'Basic Training Scenario': 16 events over 510 s", self.lines[-1])
        self.lines.clear()
        self.cli.execute("scenario events")
        self.assertEqual(16, len(self.lines))
        self.assertIn("T+10s  [waypoint]  WP-001", self.lines[1])
        self.cli.execute("scenario status")
        self.assertIn("not started, 0/16 events fired", self.lines[-1])
        self.cli.execute("scenario start fast")
        self.assertIn("not a number", self.lines[-1])
        self.cli.execute("scenario bogus")
        self.assertIn("scenario load FILE", self.lines[-1])
        # started against a bus whose frame never moves: the T+0 event fires at the start, nothing else
        self.lines.clear()
        self.cli.execute("scenario start 100")
        self.assertEqual("started 'Basic Training Scenario' at frame 1234, speed x100", self.lines[0])
        deadline = time.monotonic() + 2.0
        while len(self.lines) < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertIn("T+0s  [message]  id=MSG-001  INSTRUCTOR: Training scenario started", self.lines[1])
        self.cli.execute("scenario start")
        self.assertIn("already running", self.lines[-1])
        self.cli.execute("scenario status")
        self.assertIn("running, 1/16 events fired", self.lines[-1])
        self.cli.execute("scenario stop")
        self.assertEqual("stopped", self.lines[-1])
        self.cli.execute("scenario status")
        self.assertIn("stopped, 1/16 events fired", self.lines[-1])
        self.cli.execute("scenario stop")
        self.assertEqual("nothing was running", self.lines[-1])
        self.lines.clear()
        self.cli.execute("scenario events")
        self.assertTrue(self.lines[0].startswith("  fired T+0s"))
        self.assertTrue(self.lines[1].startswith("        T+10s"))


@unittest.skipUnless(os.environ.get("FMOFP_BC"), "set FMOFP_BC to the fmofp_bc binary to run")
class DebugCliOnTheBusTest(unittest.TestCase):
    def test_status_send_and_a_scenario_against_the_plant(self):
        model = PlantModel(seed=11, ground=False)
        plant = PlantTerminal(model, PORT_BASE)
        self.assertEqual(Status.OK, plant.init(), "plant port in use?")
        stop = threading.Event()

        def pump():
            while not stop.is_set():
                plant.poll(0.005)

        thread = threading.Thread(target=pump, daemon=True)
        thread.start()
        view = BusView(PORT_BASE)
        self.assertEqual(Status.OK, view.open(), "monitor port in use?")
        view.start()
        client = CommandClient(PORT_BASE, timeout_s=2.0)
        self.assertEqual(Status.OK, client.open())
        lines = []
        cli = DebugCli(view, client, out=lines.append)
        scenario_dir = tempfile.mkdtemp(prefix="fmofp_cli_")
        scenario_path = os.path.join(scenario_dir, "tiny.xml")
        with open(scenario_path, "w", encoding="utf-8") as f:
            f.write(TINY_SCENARIO)
        bc = subprocess.Popen([os.environ["FMOFP_BC"], "--rt", str(PLANT_RT), "--port-base", str(PORT_BASE), "--frames",
                               str(FRAMES), "--timeout-ms", "20"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, env=binary_env())
        try:
            self.assertTrue(view.wait_for_frame(60, 10.0), "the bus did not start")
            cli.execute("frame")
            self.assertRegex(lines[-1], r"^frame \d+ \(\d+\.\d s on the bus\)$")
            lines.clear()
            cli.execute("terminals")
            text = "\n".join(lines)
            # the plant is test equipment and fills no TERM_STATUS: the controller shows its zeros
            self.assertIn("RT 27 plant          STANDBY      healthy=0 faults=0 icd=0.0", text)
            self.assertIn("answered 0.", text)
            lines.clear()
            cli.execute("status plant")
            self.assertIn("RT 27 (plant) TERM_STATUS: state=STANDBY", lines[0])
            text = "\n".join(lines)
            self.assertIn("  PLANT_SENSORS: altitude_ssm=", text)  # the controller polls the plant's messages for the relays
            self.assertIn("  PLANT_GPS: epoch=", text)
            lines.clear()
            cli.execute("msg PLANT_GPS")
            self.assertEqual("PLANT_GPS:", lines[0])
            self.assertTrue(any(line.startswith("  epoch = ") for line in lines))
            lines.clear()
            cli.execute("msg TERM_STATUS plant")
            self.assertIn("  healthy = 0", lines)
            self.assertIn("  last_sync = 0", lines)
            lines.clear()
            cli.execute("send PLANT_INJECT_WEATHER x_km=10 y_km=20 size=5 reflectivity=50 category=SEVERE")
            self.assertIn("PLANT_INJECT_WEATHER -> RT 27 SA 22: OK, queued at frame", lines[-1])
            time.sleep(0.1)
            self.assertEqual(1, plant.injections)
            cell = next(c for c in model.weather.cells if getattr(c, "injected", False))
            # the cell drifts with the wind from the moment it is injected: within a tenth of a degree and a km
            self.assertAlmostEqual(math.degrees(math.atan2(10.0, 20.0)), cell.position[0], delta=0.1)
            self.assertAlmostEqual(math.hypot(10.0, 20.0), cell.position[1], delta=0.1)
            lines.clear()
            cli.execute(f'scenario load "{scenario_path}"')
            self.assertEqual("loaded 'CLI check': 3 events over 1 s", lines[-1])
            cli.execute("scenario start")
            self.assertIn("started 'CLI check' at frame", "\n".join(lines))  # the T+0 event may already follow it
            deadline = time.monotonic() + 5.0
            while not cli.engine.complete and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(cli.engine.complete, cli.engine.status())
            time.sleep(0.1)
            self.assertEqual(3, plant.injections)
            self.assertEqual(1, len([t for t in model.traffic.targets if t.injected_id == 7]))
            lines.clear()
            cli.execute("scenario status")
            self.assertIn("complete, 3/3 events fired", lines[-1])
            self.assertIn("2 commands queued, 0 not acknowledged", lines[-1])
            self.assertFalse(cli.execute("quit"))
        finally:
            output = bc.stdout.read()
            bc.stdout.close()
            code = bc.wait(timeout=60)
            cli.close()
            client.close()
            view.close()
            stop.set()
            thread.join(timeout=2)
            plant.shutdown()
        self.assertEqual(0, code, output)
        self.assertIn("bc: command port: received=3 queued=3 refused=0 malformed=0", output)


if __name__ == "__main__":
    unittest.main()
