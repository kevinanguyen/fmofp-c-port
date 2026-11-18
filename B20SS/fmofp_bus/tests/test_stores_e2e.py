"""The stores management terminal on the bus, end to end.

The plant (Python, in-process), the real fmofp_fms and fmofp_stores under the real fmofp_bc with a script: a release
refused while the master arm is SAFE, the FMS to COMBAT (its weapons state ARMED: the master arm follows), one MK-82
released from station 1, the release mode to SALVO, station 5's MK-82s released together, and a jettison. The SMS
display's bus half (no Qt) receives the status by its own relay and the window's feed builds the station table the
frozen display draws.

Needs FMOFP_BC, FMOFP_FMS and FMOFP_STORES (CI sets them).
"""

import os
import subprocess
import tempfile
import threading
import time
import unittest

from fmofp_bus.icd import messages as m
from fmofp_bus.icd.enums import CmdStatus, FmsFlightMode, MasterArm, ReleaseMode, SmsCommand, StoreState, TerminalState
from fmofp_bus.monitor import Monitor
from fmofp_bus.status import Status
from fmofp_bus.tests._support import binary_env, free_port_base, needs
from fmofp_display.systems_feed import SystemsFeed
from fmofp_display.terminal import DisplayTerminal
from fmofp_plant.plant import PlantModel, PlantTerminal

PORT_BASE = free_port_base(51500)
FRAMES = 360
SYNC_MODE_CODE = 17
PLANT_RT = m.PlantSensors.RT
SMS_DISPLAY_RT = m.DspSmsStatus.RT
STORES_RT = m.SmsStatus.RT
BINARIES = ("FMOFP_FMS", "FMOFP_STORES")
TERMINALS = (PLANT_RT, m.FmsStatus.RT, STORES_RT, SMS_DISPLAY_RT)

SCRIPT = [
    (60, m.SmsCmd(cmd_seq=1, command=SmsCommand.RELEASE, station=1)),
    (100, m.FmsFlightModeCmd(cmd_seq=1, flight_mode=FmsFlightMode.COMBAT)),
    (150, m.SmsCmd(cmd_seq=2, command=SmsCommand.RELEASE, station=1)),
    (200, m.SmsCmd(cmd_seq=3, command=SmsCommand.SET_RELEASE_MODE, release_mode=ReleaseMode.SALVO)),
    (250, m.SmsCmd(cmd_seq=4, command=SmsCommand.RELEASE, station=5)),
    (300, m.SmsCmd(cmd_seq=5, command=SmsCommand.JETTISON)),
]


def write_script(path):
    with open(path, "w", encoding="utf-8") as f:
        f.write("# frame rt sa words (hex)\n")
        for frame, msg in SCRIPT:
            status, words = msg.encode()
            assert status == Status.OK, (msg, status)
            f.write(f"{frame} {msg.RT} {msg.SUBADDRESS} " + " ".join(f"{w:04X}" for w in words) + "\n")


class PlantThread(threading.Thread):
    def __init__(self, plant):
        super().__init__(daemon=True)
        self.plant = plant
        self.stop = threading.Event()

    def run(self):
        while not self.stop.is_set():
            self.plant.poll(0.005)


@needs("FMOFP_BC", *BINARIES)
class StoresEndToEndTest(unittest.TestCase):
    processes = []
    plant_thread = None
    plant = None
    monitor = None
    display = None

    @classmethod
    def setUpClass(cls):
        cls.script = os.path.join(tempfile.mkdtemp(prefix="fmofp_stores_"), "commands.txt")
        write_script(cls.script)
        try:
            model = PlantModel(seed=4, traffic=False, weather=False, ground=False)
            model.hold = dict(speed=450.0, heading=0.0, altitude=5000.0, vertical_speed=0.0)
            cls.plant = PlantTerminal(model, PORT_BASE)
            assert cls.plant.init() == Status.OK, "plant port in use?"
            cls.plant_thread = PlantThread(cls.plant)
            cls.plant_thread.start()
            cls.monitor = Monitor(PORT_BASE)
            assert cls.monitor.open() == Status.OK, "monitor port in use?"
            cls.display = DisplayTerminal(SMS_DISPLAY_RT, PORT_BASE, m.DspSmsStatus, m.DspSmsModeCmd,
                                          receives=(m.BcastFmsStatus, m.DspSmsStores))
            assert cls.display.start() == Status.OK, "SMS display port in use?"
            for binary in BINARIES:
                cls.processes.append(subprocess.Popen(
                    [os.environ[binary], "--port-base", str(PORT_BASE), "--quiet"], stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, text=True, env=binary_env()))
            time.sleep(0.3)
        except BaseException:
            cls.tearDownClass()
            raise

    @classmethod
    def tearDownClass(cls):
        for p in cls.processes:
            p.kill()
            p.wait(timeout=10)
            p.stdout.close()
        cls.processes = []
        if cls.display is not None:
            cls.display.stop()
        if cls.plant_thread is not None:
            cls.plant_thread.stop.set()
            cls.plant_thread.join(timeout=2)
        if cls.plant is not None:
            cls.plant.shutdown()
        if cls.monitor is not None:
            cls.monitor.close()

    def run_bus(self):
        args = [os.environ["FMOFP_BC"]]
        for rt in TERMINALS:
            args += ["--rt", str(rt)]
        args += ["--port-base", str(PORT_BASE), "--frames", str(FRAMES), "--free-run", "--strict", "--timeout-ms", "40",
                 "--script", self.script]
        bc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=binary_env())
        records = self.monitor.read_until(lambda: bc.poll() is not None)
        output = bc.stdout.read()
        bc.stdout.close()
        self.assertEqual(0, bc.wait(timeout=60), output)
        return records, output

    def statuses(self, records, first, last):
        frame = -1
        out = []
        for record in records:
            cw = record.command
            if cw.is_mode_code and cw.count_or_mode == SYNC_MODE_CODE:
                frame += 1
                continue
            if (first <= frame < last and cw.transmit and not cw.is_mode_code and cw.rt == STORES_RT
                    and cw.subaddress == m.SmsStatus.SUBADDRESS and record.answered):
                status, msg = m.SmsStatus.decode(record.received)
                self.assertEqual(Status.OK, status)
                out.append(msg)
        self.assertTrue(out, f"no SMS_STATUS in frames {first}..{last - 1}")
        return out

    def test_the_stores_follow_the_fms_and_the_commands(self):
        self.monitor.drain()
        records, output = self.run_bus()
        self.assertIn("script: 6 commands sent of 6", output)

        start = self.statuses(records, 40, 60)[-1]
        self.assertEqual((TerminalState.NORMAL, MasterArm.SAFE, 2, 7806.0, 1),
                         (start.state, start.master_arm, start.armed_count, start.total_weight, start.selected_station))
        refused = self.statuses(records, 70, 100)[-1]
        self.assertEqual((CmdStatus.REJECTED_STATE, 4, 0),
                         (refused.sms_cmd_status, refused.station_1_qty, refused.stores_released),
                         "no release with the master arm SAFE")
        combat = self.statuses(records, 120, 150)[-1]
        self.assertEqual(MasterArm.ARMED, combat.master_arm, "COMBAT arms the FMS's weapons")
        one = self.statuses(records, 160, 200)[-1]
        self.assertEqual((CmdStatus.COMPLETED, 3, 1, 7806.0 - 227.0),
                         (one.sms_cmd_status, one.station_1_qty, one.stores_released, one.total_weight))
        salvo = self.statuses(records, 260, 300)[-1]
        self.assertEqual((ReleaseMode.SALVO, 0, StoreState.EXPENDED, 5, 1),
                         (salvo.release_mode, salvo.station_5_qty, salvo.station_5_state, salvo.stores_released,
                          salvo.armed_count))
        gone = self.statuses(records, 310, FRAMES)[-1]
        self.assertTrue(gone.jettisoned)
        self.assertEqual((0.0, 0, StoreState.JETTISONED, StoreState.EMPTY),
                         (gone.total_weight, gone.armed_count, gone.station_2_state, gone.station_4_state))

        # The SMS display hears the status by its own relay; the window's feed gives the frozen display its table.
        feed = SystemsFeed(self.display, stale_after_s=60.0)
        status = feed.stores_status()
        self.assertIsNotNone(status, "the SMS display's own relay")
        stations = feed.stores_stations()
        self.assertEqual(11, len(stations))
        self.assertEqual(("MK-82", 227, 0, "JETTISONED", "WEAPON"), stations[0], "three left, then jettisoned")
        self.assertEqual(("MK-82", 227, 0, "EXPENDED", "WEAPON"), stations[4], "released by the salvo")
        self.assertEqual(("AN/ALQ", 180, 0, "JETTISONED", "POD"), stations[10])


if __name__ == "__main__":
    unittest.main()
