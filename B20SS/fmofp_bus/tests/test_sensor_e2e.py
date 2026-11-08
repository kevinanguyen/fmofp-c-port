"""The sensor management terminal on the bus, end to end.

The plant (Python, in-process, with its sensor scans and ESM intercepts) and the real fmofp_sensor under the real
fmofp_bc with a script of commands: the LIDAR is switched off (DEGRADED), then the forward-looking infrared (FAULT),
then both back on (DEGRADED, NOMINAL), then a command with nothing in it (REJECTED_INVALID). The EICAS's bus half
(no Qt) receives the status by relay. The monitor port shows the plant's scans block and intercepts reaching the
terminal by relay, and SNS_STATUS with its contact count and id counter growing.

Needs FMOFP_BC and FMOFP_SENSOR (CI sets them).
"""

import os
import subprocess
import tempfile
import threading
import time
import unittest

from fmofp_bus.icd import blocks as b
from fmofp_bus.icd import messages as m
from fmofp_bus.icd.enums import CmdStatus, SensorCommand, SensorHealth, SensorId, TerminalState
from fmofp_bus.monitor import Monitor
from fmofp_bus.status import Status
from fmofp_bus.tests._support import binary_env, needs
from fmofp_display.systems_feed import SystemsFeed
from fmofp_display.terminal import DisplayTerminal
from fmofp_plant.plant import PlantModel, PlantTerminal

PORT_BASE = 53500
FRAMES = 420
SYNC_MODE_CODE = 17
SENSOR_RT = m.SnsStatus.RT
PLANT_RT = m.PlantSensors.RT
EICAS_RT = m.DspEicasStatus.RT

SCRIPT = [
    (100, m.SnsCmd(cmd_seq=1, command=SensorCommand.DEACTIVATE, sensor=SensorId.LIDAR)),
    (200, m.SnsCmd(cmd_seq=2, command=SensorCommand.DEACTIVATE, sensor=SensorId.FLIR)),
    (300, m.SnsCmd(cmd_seq=3, command=SensorCommand.ACTIVATE, sensor=SensorId.LIDAR)),
    (350, m.SnsCmd(cmd_seq=4, command=SensorCommand.ACTIVATE, sensor=SensorId.FLIR)),
    (380, m.SnsCmd(cmd_seq=5, command=SensorCommand.NONE, sensor=SensorId.MAIN_RADAR)),
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


@needs("FMOFP_BC", "FMOFP_SENSOR")
class SensorEndToEndTest(unittest.TestCase):
    processes = []
    plant_thread = None
    plant = None
    monitor = None
    eicas = None

    @classmethod
    def setUpClass(cls):
        cls.script = os.path.join(tempfile.mkdtemp(prefix="fmofp_sensor_"), "commands.txt")
        write_script(cls.script)
        try:
            model = PlantModel(seed=5, traffic=False, weather=False, ground=False)
            model.hold = dict(speed=450.0, heading=0.0, altitude=5000.0, vertical_speed=0.0)
            cls.plant = PlantTerminal(model, PORT_BASE)
            assert cls.plant.init() == Status.OK, "plant port in use?"
            cls.plant_thread = PlantThread(cls.plant)
            cls.plant_thread.start()
            cls.monitor = Monitor(PORT_BASE)
            assert cls.monitor.open() == Status.OK, "monitor port in use?"
            cls.eicas = DisplayTerminal(EICAS_RT, PORT_BASE, m.DspEicasStatus, m.DspEicasModeCmd,
                                        receives=(m.EicasSnsStatus,), blocks=(b.BcastRdrFusedTracks,))
            assert cls.eicas.start() == Status.OK, "EICAS port in use?"
            cls.processes.append(subprocess.Popen(
                [os.environ["FMOFP_SENSOR"], "--port-base", str(PORT_BASE), "--quiet"], stdout=subprocess.PIPE,
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
        if cls.eicas is not None:
            cls.eicas.stop()
        if cls.plant_thread is not None:
            cls.plant_thread.stop.set()
            cls.plant_thread.join(timeout=2)
        if cls.plant is not None:
            cls.plant.shutdown()
        if cls.monitor is not None:
            cls.monitor.close()

    def run_bus(self):
        bc = subprocess.Popen(
            [os.environ["FMOFP_BC"], "--rt", str(PLANT_RT), "--rt", str(SENSOR_RT), "--rt", str(EICAS_RT),
             "--port-base", str(PORT_BASE), "--frames", str(FRAMES), "--free-run", "--strict", "--timeout-ms", "40",
             "--script", self.script],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=binary_env())
        records = self.monitor.read_until(lambda: bc.poll() is not None)
        output = bc.stdout.read()
        bc.stdout.close()
        self.assertEqual(0, bc.wait(timeout=60), output)
        return records, output

    @staticmethod
    def by_frame(records):
        frame = -1
        out = []
        for record in records:
            cw = record.command
            if cw.is_mode_code and cw.count_or_mode == SYNC_MODE_CODE:
                frame += 1
                continue
            out.append((frame, record))
        return out

    def last_in_window(self, framed, cls, first, last, rt=None):
        rt = cls.RT if rt is None else rt
        for frame, record in reversed(framed):
            cw = record.command
            if (first <= frame < last and cw.transmit and not cw.is_mode_code and cw.rt == rt
                    and cw.subaddress == cls.SUBADDRESS and record.answered):
                status, msg = cls.decode(record.received)
                self.assertEqual(Status.OK, status)
                return msg
        self.fail(f"no {cls.__name__} from RT {rt} in frames {first}..{last - 1}")

    @staticmethod
    def writes_into(framed, rt, subaddress):
        return [r for _, r in framed if not r.command.transmit and not r.command.is_mode_code
                and r.command.rt == rt and r.command.subaddress == subaddress]

    def test_the_health_follows_the_commands_and_the_fusion_fills_from_the_plant(self):
        self.monitor.drain()
        records, output = self.run_bus()
        framed = self.by_frame(records)
        self.assertGreaterEqual(framed[-1][0], FRAMES - 2)
        self.assertIn("script: 5 commands sent of 5", output)

        # The plant's scans block and intercepts reach the terminal by relay; the status reaches the EICAS alone.
        self.assertGreaterEqual(len(self.writes_into(framed, SENSOR_RT, b.SnsScan.DESCRIPTOR_SUBADDRESS)), 100)
        self.assertGreaterEqual(len(self.writes_into(framed, SENSOR_RT, b.SnsScan.SEGMENT_SUBADDRESS)), 100)
        self.assertGreaterEqual(len(self.writes_into(framed, SENSOR_RT, m.SnsEsm.SUBADDRESS)), 30)
        self.assertGreaterEqual(len(self.writes_into(framed, EICAS_RT, m.EicasSnsStatus.SUBADDRESS)), 30)

        # Frames 50-100: every sensor on, NOMINAL, the fusion filling from the plant's sets.
        status = self.last_in_window(framed, m.SnsStatus, 50, 100)
        self.assertEqual(SensorHealth.NOMINAL, status.health)
        self.assertTrue(status.main_radar_active and status.tfr_radar_active and status.lidar_active and
                        status.flir_active and status.maws_active and status.esm_active)
        self.assertTrue(status.scan_valid and status.esm_valid, "the world's sets arrive")
        self.assertGreater(status.contact_count, 0)
        self.assertGreater(status.sequence, 0)
        self.assertEqual(CmdStatus.NONE, status.sensor_cmd_status)
        early = status
        # Frames 110-200: the LIDAR off, DEGRADED; 210-300: the FLIR off too, FAULT; 310-350: the LIDAR back, DEGRADED;
        # 360-380: everything on, NOMINAL; 385-420: an empty command rejected.
        status = self.last_in_window(framed, m.SnsStatus, 110, 200)
        self.assertEqual((SensorHealth.DEGRADED, False, True, CmdStatus.ACCEPTED),
                         (status.health, status.lidar_active, status.flir_active, status.sensor_cmd_status))
        status = self.last_in_window(framed, m.SnsStatus, 210, 300)
        self.assertEqual((SensorHealth.FAULT, False, False), (status.health, status.lidar_active, status.flir_active))
        status = self.last_in_window(framed, m.SnsStatus, 310, 350)
        self.assertEqual((SensorHealth.DEGRADED, True, False), (status.health, status.lidar_active, status.flir_active))
        status = self.last_in_window(framed, m.SnsStatus, 360, 380)
        self.assertEqual((SensorHealth.NOMINAL, True, True, CmdStatus.ACCEPTED),
                         (status.health, status.lidar_active, status.flir_active, status.sensor_cmd_status))
        status = self.last_in_window(framed, m.SnsStatus, 385, FRAMES)
        self.assertEqual((SensorHealth.NOMINAL, CmdStatus.REJECTED_INVALID), (status.health, status.sensor_cmd_status))
        self.assertGreater(status.sequence, early.sequence, "every detection takes a number")
        self.assertLessEqual(status.contact_count, 192)
        self.assertEqual(0, status.dropped)
        term = self.last_in_window(framed, m.TermStatus, 360, FRAMES, rt=SENSOR_RT)
        self.assertEqual(TerminalState.NORMAL, term.state)

        # What the EICAS would read, from its own terminal: the health and the six states, the contact count, and
        # the fused track count it takes from the fused tracks block (none here: no radar computer on this bus).
        relayed = self.eicas.fresh(m.EicasSnsStatus, stale_after_s=60.0)
        self.assertIsNotNone(relayed, "SNS_STATUS reached the EICAS by relay")
        feed = SystemsFeed(self.eicas, stale_after_s=60.0)
        data = feed.sensors.get_data()
        self.assertEqual("NOMINAL", data["health"])
        self.assertEqual(0, data["fused_track_count"])
        self.assertGreaterEqual(data["sensor_contact_count"], 1)
        self.assertEqual({"main_radar", "terrain_following_radar", "lidar"}, set(data["active_sensors"]))
        self.assertTrue(all(s["is_active"] for s in data["active_sensors"].values()))
        self.assertTrue(all(s["is_active"] for s in data["passive_sensors"].values()))
        self.assertIn("SNS NOMINAL 0 fused", feed.status_text())
        self.assertIn("overruns=0", output)


if __name__ == "__main__":
    unittest.main()
