"""The data recorder on the bus, end to end.

The plant (Python, in-process) and the real fmofp_fcs, fmofp_fms, fmofp_engine, fmofp_comms, fmofp_power,
fmofp_defensive, fmofp_mission and fmofp_surfaces under the real fmofp_bc in real time, with four chaff cartridges
released at frame 150 and the ECM set ACTIVE at frame 200 by script. The recorder joins as a client of the
controller (a copy of the monitor stream through the command port, as it does beside the demo) and writes its
tables while the bus runs; the test then reads them back, as the prompt's `tables` and `table` do.

Needs FMOFP_BC, FMOFP_FCS, FMOFP_FMS, FMOFP_ENGINE, FMOFP_COMMS, FMOFP_POWER, FMOFP_DEFENSIVE, FMOFP_MISSION and
FMOFP_SURFACES (CI sets them).
"""

import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import unittest

from fmofp_bus.icd import messages as m
from fmofp_bus.icd.enums import DefensiveCommand, EcmMode
from fmofp_bus.status import Status
from fmofp_bus.tests._support import binary_env, free_port_base, needs
from fmofp_plant.plant import PlantModel, PlantTerminal
from fmofp_recorder import recorder as r
from fmofp_recorder.view import RecordingView

PORT_BASE = free_port_base(52250)
FRAMES = 400
PLANT_RT = m.PlantSensors.RT
BINARIES = ("FMOFP_FCS", "FMOFP_FMS", "FMOFP_ENGINE", "FMOFP_COMMS", "FMOFP_POWER", "FMOFP_DEFENSIVE",
            "FMOFP_MISSION", "FMOFP_SURFACES")
TERMINALS = (PLANT_RT, m.FcsStatus.RT, m.FmsStatus.RT, m.EngStatus.RT, m.ComStatus.RT, m.PwrStatus.RT,
             m.DefStatus.RT, m.MsnStatus.RT, m.FsfStatus.RT)

SCRIPT = [
    (150, m.DefCmd(cmd_seq=1, command=DefensiveCommand.DISPENSE_CHAFF, count=4)),
    (200, m.DefCmd(cmd_seq=2, command=DefensiveCommand.SET_ECM_MODE, ecm_mode=EcmMode.ACTIVE)),
]


def write_script(path):
    with open(path, "w", encoding="utf-8") as f:
        f.write("# frame rt sa words (hex)\n")
        for frame, msg in SCRIPT:
            status, words = msg.encode()
            assert status == Status.OK, (msg, status)
            f.write(f"{frame} {msg.RT} {msg.SUBADDRESS} " + " ".join(f"{w:04X}" for w in words) + "\n")


class Loop(threading.Thread):
    def __init__(self, step, period_s):
        super().__init__(daemon=True)
        self.step = step
        self.period_s = period_s
        self.halt = threading.Event()

    def run(self):
        while not self.halt.is_set():
            self.step()
            time.sleep(self.period_s)


@needs("FMOFP_BC", *BINARIES)
class RecorderEndToEndTest(unittest.TestCase):
    def setUp(self):
        self.out = tempfile.mkdtemp(prefix="fmofp_recorder_e2e_")
        self.script = os.path.join(self.out, "commands.txt")
        write_script(self.script)
        self.processes = []
        self.loops = []
        self.view = None
        self.plant = None
        self.recorder = None
        model = PlantModel(seed=3, traffic=False, weather=False, ground=False)
        model.hold = dict(speed=450.0, heading=0.0, altitude=5000.0, vertical_speed=0.0)
        self.plant = PlantTerminal(model, PORT_BASE)
        self.assertEqual(Status.OK, self.plant.init(), "plant port in use?")
        self.loops.append(Loop(lambda: self.plant.poll(0.002), 0.0))
        for binary in BINARIES:
            self.processes.append(subprocess.Popen(
                [os.environ[binary], "--port-base", str(PORT_BASE), "--quiet"], stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, env=binary_env()))
        self.view = RecordingView(PORT_BASE)
        self.assertEqual(Status.OK, self.view.open())
        self.view.start()
        self.recorder = r.Recorder(self.view, self.out)
        self.recorder.open()
        self.loops.append(Loop(lambda: self.recorder.step(self.view.current_frame()), 0.003))
        for loop in self.loops:
            loop.start()
        time.sleep(0.3)

    def tearDown(self):
        for loop in self.loops:
            loop.halt.set()
            loop.join(timeout=2)
        if self.view is not None:
            self.view.close()
        if self.recorder is not None:
            self.recorder.close()
        for p in self.processes:
            p.kill()
            p.wait(timeout=10)
        if self.plant is not None:
            self.plant.shutdown()
        shutil.rmtree(self.out, ignore_errors=True)

    def rows(self, table):
        result = r.read_table(table, 100000, self.out)
        self.assertIsNotNone(result, table)
        return result[1]

    def test_the_tables_fill_from_the_bus(self):
        args = [os.environ["FMOFP_BC"]]
        for rt in TERMINALS:
            args += ["--rt", str(rt)]
        args += ["--port-base", str(PORT_BASE), "--frames", str(FRAMES), "--timeout-ms", "40", "--script", self.script]
        bc = subprocess.run(args, capture_output=True, text=True, timeout=120, env=binary_env())
        self.assertEqual(0, bc.returncode, bc.stdout + bc.stderr)
        time.sleep(0.2)
        self.assertGreater(self.view.current_frame(), FRAMES - 20, "the recorder watched the run")

        counts = {table: n for _, table, n in r.list_tables(self.out)}
        # Eight seconds of bus, the first second or two before a terminal's first answer: rates, not exact counts.
        self.assertGreaterEqual(counts["fcs_data"], 60, counts)       # 10 Hz
        self.assertGreaterEqual(counts["surface_data"], 50, counts)   # 10 Hz
        self.assertGreaterEqual(counts["ecu_data"], 10, counts)       # 2 Hz
        self.assertGreaterEqual(counts["pms_data"], 4, counts)        # 1 Hz, from the first electrical reading
        self.assertGreaterEqual(counts["mission_data"], 5, counts)    # 1 Hz
        self.assertEqual(0, counts["comms_data"] % 3, counts)
        self.assertGreaterEqual(counts["comms_data"], 15, counts)
        self.assertEqual((3, 2, 4), (counts["fuel_tanks"], counts["engines"], counts["fuel_lines"]), counts)

        fcs = json.loads(self.rows("fcs_data")[-1][2])
        self.assertAlmostEqual(5000.0, fcs["altitude"], delta=1.0)
        self.assertAlmostEqual(450.0, fcs["speed"], delta=1.0)
        self.assertEqual("up", fcs["landing_gear"])
        self.assertEqual("PLANNING", self.rows("mission_data")[-1][2])
        events = [(row[2], json.loads(row[3])) for row in self.rows("defensive_events")]
        self.assertIn(("manual_chaff", {"released": 4}), events)
        self.assertIn(("ecm_mode_change", {"mode": "ACTIVE"}), events)
        levels = {row[0]: row[2] for row in self.rows("fuel_tanks")}
        self.assertTrue(all(0 < level <= 20000 for level in levels.values()), levels)
        self.assertEqual({"radio", "satcom", "datalink"}, {row[2] for row in self.rows("comms_data")})


if __name__ == "__main__":
    unittest.main()
