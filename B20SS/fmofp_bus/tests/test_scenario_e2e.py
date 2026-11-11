"""The two frozen scenario files run end to end over the bus.

The plant (Python, in-process, with its traffic and weather), the real fmofp_mission, fmofp_defensive and
fmofp_avionics, and the EICAS's and TSD's bus halves (the consumers of MSN_STATUS, DEF_STATUS and AVN_STATUS) under
the real fmofp_bc. The scenario engine runs each file through the controller's command port at a time factor (the
training scenario's 510 s in 255 frames), reading its clock from the monitor; the test then reads what the
terminals made of it: the mission computer's route and phase, the radar warning receiver's contact and the salvo it
earned, the avionics' forced faults, the plant's injected aircraft and storm cells. The partitions start afresh for
each scenario: a terminal kept alive while the controller's frame count restarts at 0 sees its frame-based
cooldowns and expiries go wrong.

Needs FMOFP_BC, FMOFP_MISSION, FMOFP_DEFENSIVE and FMOFP_AVIONICS (CI sets them).
"""

import os
import subprocess
import threading
import time
import unittest

from fmofp_bus.bus_view import BusView
from fmofp_bus.command_port import CommandClient
from fmofp_bus.icd import messages as m
from fmofp_bus.icd.enums import CmdStatus, MissionPhase
from fmofp_bus.status import Status
from fmofp_bus.tests._support import binary_env, needs
from fmofp_display.terminal import DisplayTerminal
from fmofp_plant.plant import PlantModel, PlantTerminal
from fmofp_scenario.engine import ScenarioEngine, describe
from fmofp_scenario.scenario import FAILURE, TRAINING

PORT_BASE = 58500
PLANT_RT = m.PlantSensors.RT
EICAS_RT = m.DspEicasStatus.RT
TSD_RT = m.DspTsdStatus.RT
BINARIES = ("FMOFP_MISSION", "FMOFP_DEFENSIVE", "FMOFP_AVIONICS")
TERMINALS = (PLANT_RT, m.MsnStatus.RT, m.DefStatus.RT, m.AvnStatus.RT, EICAS_RT, TSD_RT)
WARM_UP_FRAME = 125  # every terminal NORMAL, the avionics' first bus-health report in (root CLAUDE.md section 6)


class PlantThread(threading.Thread):
    def __init__(self, plant):
        super().__init__(daemon=True)
        self.plant = plant
        self.stop = threading.Event()

    def run(self):
        while not self.stop.is_set():
            self.plant.poll(0.005)


@needs("FMOFP_BC", *BINARIES)
class ScenarioEndToEndTest(unittest.TestCase):
    plant_thread = None
    plant = None

    @classmethod
    def setUpClass(cls):
        cls.plant = PlantTerminal(PlantModel(seed=7, ground=False), PORT_BASE)
        assert cls.plant.init() == Status.OK, "plant port in use?"
        cls.plant_thread = PlantThread(cls.plant)
        cls.plant_thread.start()

    @classmethod
    def tearDownClass(cls):
        if cls.plant_thread is not None:
            cls.plant_thread.stop.set()
            cls.plant_thread.join(timeout=2)
        if cls.plant is not None:
            cls.plant.shutdown()

    def setUp(self):
        self.processes = []
        self.eicas = DisplayTerminal(EICAS_RT, PORT_BASE, m.DspEicasStatus, m.DspEicasModeCmd,
                                     receives=(m.EicasDefStatus, m.EicasAvnStatus))
        self.assertEqual(Status.OK, self.eicas.start(), "EICAS port in use?")
        self.tsd = DisplayTerminal(TSD_RT, PORT_BASE, m.DspTsdStatus, m.DspTsdModeCmd, receives=(m.BcastMsnStatus,))
        self.assertEqual(Status.OK, self.tsd.start(), "TSD port in use?")
        for binary in BINARIES:
            self.processes.append(subprocess.Popen(
                [os.environ[binary], "--port-base", str(PORT_BASE), "--quiet"], stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, env=binary_env()))
        time.sleep(0.3)

    def tearDown(self):
        for p in self.processes:
            p.kill()
            p.wait(timeout=10)
            p.stdout.close()
        self.eicas.stop()
        self.tsd.stop()

    def run_scenario(self, path, speed, frames):
        """The controller for `frames` free-running frames with the scenario fired from the warm-up frame on.
        Returns the engine, the bus picture at the end, the controller's output and how many injections the plant
        took."""
        view = BusView(PORT_BASE)
        self.assertEqual(Status.OK, view.open(), "monitor port in use?")
        view.start()
        client = CommandClient(PORT_BASE, timeout_s=2.0)
        self.assertEqual(Status.OK, client.open())
        args = [os.environ["FMOFP_BC"]]
        for rt in TERMINALS:
            args += ["--rt", str(rt)]
        args += ["--port-base", str(PORT_BASE), "--frames", str(frames), "--free-run", "--strict", "--timeout-ms", "40"]
        bc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=binary_env())
        try:
            engine = ScenarioEngine(client, speed=speed)
            engine.load(path)
            self.assertTrue(view.wait_for_frame(WARM_UP_FRAME, 30.0), "the bus did not reach the warm-up frame")
            injections_before = self.plant.injections
            engine.run(view, stall_s=15.0)
            output = bc.stdout.read()
            bc.stdout.close()
            code = bc.wait(timeout=60)
            time.sleep(0.05)  # the monitor's last records
            after = view.snapshot()
        finally:
            if bc.poll() is None:
                bc.kill()
                bc.wait(timeout=10)
            client.close()
            view.close()
        self.assertEqual(0, code, output)
        return engine, after, output, self.plant.injections - injections_before

    def check_commands(self, engine, output, expected):
        self.assertTrue(engine.complete, engine.status())
        firings = list(engine.log)
        self.assertEqual(16, len(firings))
        commands = [f for f in firings if f.message is not None]
        self.assertEqual(expected, len(commands))
        for firing in commands:
            self.assertTrue(firing.queued, describe(firing))
            self.assertLessEqual(abs(firing.ack.frame - firing.frame), 5, describe(firing))
        self.assertIn(f"bc: command port: received={expected} queued={expected} refused=0 malformed=0", output)

    def latest(self, snapshot, cls):
        message = snapshot["latest"].get(cls)
        self.assertIsNotNone(message, f"no {cls.__name__} on the monitor")
        return message

    def test_the_training_scenario_runs_end_to_end(self):
        engine, after, output, injections = self.run_scenario(TRAINING, speed=100.0, frames=600)
        self.check_commands(engine, output, 12)
        # The mission computer: three waypoints added, the phase through INGRESS, OBJECTIVE and EGRESS to COMPLETE.
        msn = self.latest(after, m.MsnStatus)
        self.assertEqual((MissionPhase.COMPLETE, 3, CmdStatus.ACCEPTED),
                         (msn.phase, msn.waypoint_count, msn.mission_cmd_status))
        # The radar warning receiver: the SAM site injected at T+180 s and the automatic salvo a priority-1
        # hostile contact earns (the 10 s expiry is 500 frames: it is still there at the end).
        defensive = self.latest(after, m.DefStatus)
        self.assertGreaterEqual(defensive.contact_count, 1)
        self.assertGreaterEqual(defensive.high_priority_count, 1)
        self.assertGreaterEqual(defensive.auto_salvos, 1)
        self.assertGreaterEqual(defensive.flares_released, 2)
        self.assertIsNotNone(self.eicas.latest(m.EicasDefStatus))  # and the EICAS's half got it by relay
        # The plant: two contacts (one aircraft, classified and moved by the second) and two storm cells.
        self.assertEqual(4, injections)
        injected = [t for t in self.plant.model.traffic.targets if t.injected_id == 1]
        self.assertEqual(1, len(injected))
        self.assertEqual((5.0, False), (injected[0].rcs, injected[0].stealth))
        self.assertGreaterEqual(len([c for c in self.plant.model.weather.cells if getattr(c, "injected", False)]), 2)
        # No failure in this scenario.
        avionics = self.latest(after, m.AvnStatus)
        self.assertEqual(0, avionics.forced_count)

    def test_the_failure_scenario_runs_end_to_end(self):
        engine, after, output, injections = self.run_scenario(FAILURE, speed=50.0, frames=450)
        self.check_commands(engine, output, 10)
        # The avionics: four forced faults, three of them on systems that are no LRU of the catalogue (declared
        # entries, so eleven LRUs become fourteen), one on the flight control computer.
        avionics = self.latest(after, m.AvnStatus)
        self.assertEqual((4, 14, CmdStatus.ACCEPTED), (avionics.forced_count, avionics.lru_count, avionics.avionics_cmd_status))
        self.assertGreaterEqual(avionics.fault_count, 4)
        self.assertNotEqual(0, avionics.lru_forced_mask)
        self.assertIsNotNone(self.eicas.latest(m.EicasAvnStatus))
        # The missile launch warning on the receiver, with its salvo.
        defensive = self.latest(after, m.DefStatus)
        self.assertGreaterEqual(defensive.contact_count, 1)
        self.assertGreaterEqual(defensive.high_priority_count, 1)
        self.assertGreaterEqual(defensive.auto_salvos, 1)
        # The divert waypoint and the phases.
        msn = self.latest(after, m.MsnStatus)
        self.assertEqual((MissionPhase.COMPLETE, 1), (msn.phase, msn.waypoint_count))
        # The plant: the close hostile contact and the severe cell on the route.
        self.assertEqual(2, injections)
        self.assertEqual(1, len([t for t in self.plant.model.traffic.targets if t.injected_id == 99]))


if __name__ == "__main__":
    unittest.main()
