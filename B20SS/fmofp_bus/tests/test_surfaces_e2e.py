"""The flight surfaces terminal on the bus, end to end.

The plant (Python, in-process, its attitude held at 20 degrees of roll, 5 of pitch and 10 of angle of attack) and
the real fmofp_surfaces under the real fmofp_bc with a script of commands: the flaps to 15 degrees, the speedbrake
to 50 %, the rudder to 10 degrees, a pitch trim, the flaps to 10 (the 5 detent), and a command with nothing in
it, which is rejected. The monitor port shows the plant's flight state reaching the terminal by relay every frame,
the ailerons and elevators settling where the sensed attitude puts them, the slats coming out at 5 degrees a
second, and every commanded surface travelling at its slew rate.

Needs FMOFP_BC and FMOFP_SURFACES (CI sets them).
"""

import os
import subprocess
import tempfile
import threading
import time
import unittest

from fmofp_bus.icd import messages as m
from fmofp_bus.icd.enums import CmdStatus, SurfaceCommand, TerminalState, TrimAxis
from fmofp_bus.monitor import Monitor
from fmofp_bus.status import Status
from fmofp_bus.tests._support import binary_env, free_port_base, needs
from fmofp_plant.plant import PlantModel, PlantTerminal

PORT_BASE = free_port_base(52500)
FRAMES = 420
SYNC_MODE_CODE = 17
SURFACES_RT = m.FsfStatus.RT
PLANT_RT = m.PlantSensors.RT
LSB = 0.011  # the positions' and the trim's resolution, with a little slack

SCRIPT = [
    (100, m.FsfCmd(cmd_seq=1, command=SurfaceCommand.SET_FLAPS, value=15.0)),
    (150, m.FsfCmd(cmd_seq=2, command=SurfaceCommand.SET_SPEEDBRAKE, value=50.0)),
    (200, m.FsfCmd(cmd_seq=3, command=SurfaceCommand.SET_RUDDER, value=10.0)),
    (250, m.FsfCmd(cmd_seq=4, command=SurfaceCommand.SET_TRIM, axis=TrimAxis.PITCH, value=3.5)),
    (300, m.FsfCmd(cmd_seq=5, command=SurfaceCommand.SET_FLAPS, value=10.0)),
    (350, m.FsfCmd(cmd_seq=6, command=SurfaceCommand.NONE)),
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


@needs("FMOFP_BC", "FMOFP_SURFACES")
class SurfacesEndToEndTest(unittest.TestCase):
    processes = []
    plant_thread = None
    plant = None
    monitor = None

    @classmethod
    def setUpClass(cls):
        cls.script = os.path.join(tempfile.mkdtemp(prefix="fmofp_surfaces_"), "commands.txt")
        write_script(cls.script)
        try:
            model = PlantModel(seed=5, traffic=False, weather=False, ground=False)
            model.hold = dict(speed=450.0, heading=0.0, altitude=5000.0, vertical_speed=0.0, roll=20.0, pitch=5.0,
                              angle_of_attack=10.0)
            cls.plant = PlantTerminal(model, PORT_BASE)
            assert cls.plant.init() == Status.OK, "plant port in use?"
            cls.plant_thread = PlantThread(cls.plant)
            cls.plant_thread.start()
            cls.monitor = Monitor(PORT_BASE)
            assert cls.monitor.open() == Status.OK, "monitor port in use?"
            cls.processes.append(subprocess.Popen(
                [os.environ["FMOFP_SURFACES"], "--port-base", str(PORT_BASE), "--quiet"], stdout=subprocess.PIPE,
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
        if cls.plant_thread is not None:
            cls.plant_thread.stop.set()
            cls.plant_thread.join(timeout=2)
        if cls.plant is not None:
            cls.plant.shutdown()
        if cls.monitor is not None:
            cls.monitor.close()

    def run_bus(self):
        bc = subprocess.Popen(
            [os.environ["FMOFP_BC"], "--rt", str(PLANT_RT), "--rt", str(SURFACES_RT), "--port-base", str(PORT_BASE),
             "--frames", str(FRAMES), "--free-run", "--strict", "--timeout-ms", "40", "--script", self.script],
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

    def test_the_surfaces_follow_the_attitude_and_the_commands(self):
        self.monitor.drain()
        records, output = self.run_bus()
        framed = self.by_frame(records)
        self.assertGreaterEqual(framed[-1][0], FRAMES - 2)
        self.assertIn("script: 6 commands sent of 6", output)

        # The plant's flight state reaches the terminal by relay every frame.
        self.assertGreaterEqual(len(self.writes_into(framed, SURFACES_RT, m.FsfSensors.SUBADDRESS)), FRAMES - 40)

        # Frames 20-60: the flight state is in and the terminal is NORMAL; no command yet. The ailerons oppose the
        # 20 degree roll (+-10, reached within nine frames at 60 deg/s), the elevators the 5 degree pitch (-4), the
        # slats are on their way out at 5 deg/s; the rudder, flaps and speedbrake rest at zero.
        status = self.last_in_window(framed, m.FsfStatus, 20, 60)
        self.assertEqual(TerminalState.NORMAL, status.state)
        self.assertTrue(status.sensors_valid)
        self.assertTrue(status.slats_extended)
        self.assertEqual(CmdStatus.NONE, status.surface_cmd_status)
        self.assertEqual(0.0, status.flap_cmd)
        self.assertEqual((0.0, 0.0, 0.0), (status.trim_pitch, status.trim_roll, status.trim_yaw))
        positions = self.last_in_window(framed, m.FsfPositions, 20, 60)
        self.assertAlmostEqual(10.0, positions.aileron_l, delta=LSB)
        self.assertAlmostEqual(-10.0, positions.aileron_r, delta=LSB)
        self.assertAlmostEqual(-4.0, positions.elevator_l, delta=LSB)
        self.assertAlmostEqual(-4.0, positions.elevator_r, delta=LSB)
        self.assertTrue(1.5 <= positions.slat_l <= 6.5, positions.slat_l)
        self.assertEqual(positions.slat_l, positions.slat_r)
        self.assertEqual((0.0, 0.0, 0.0, 0.0), (positions.rudder, positions.flap_l, positions.flap_r,
                                                positions.speedbrake))
        # Frames 260-300: the flaps commanded to 15 at frame 100 arrived (5 deg/s: 150 frames), the speedbrake
        # commanded to 50 % at 150 stands at 30 degrees (reached in 50 frames), the rudder commanded at 200 at
        # 10 degrees (13 frames), the pitch trim set at 250, the slats fully out (200 frames).
        status = self.last_in_window(framed, m.FsfStatus, 260, 300)
        self.assertEqual(CmdStatus.ACCEPTED, status.surface_cmd_status)
        self.assertEqual(15.0, status.flap_cmd)
        self.assertAlmostEqual(3.5, status.trim_pitch, delta=LSB)
        self.assertEqual((0.0, 0.0), (status.trim_roll, status.trim_yaw))
        positions = self.last_in_window(framed, m.FsfPositions, 260, 300)
        self.assertAlmostEqual(15.0, positions.flap_l, delta=LSB)
        self.assertAlmostEqual(15.0, positions.flap_r, delta=LSB)
        self.assertAlmostEqual(30.0, positions.speedbrake, delta=LSB)
        self.assertAlmostEqual(10.0, positions.rudder, delta=LSB)
        self.assertAlmostEqual(20.0, positions.slat_l, delta=LSB)
        self.assertAlmostEqual(20.0, positions.slat_r, delta=LSB)
        self.assertAlmostEqual(10.0, positions.aileron_l, delta=LSB)
        # Frames 405-420: the flaps commanded to 10 at frame 300 went to the 5 detent (a tie, the lower) and got
        # there at 5 deg/s (100 frames); the empty command at 350 was rejected; nothing else moved.
        status = self.last_in_window(framed, m.FsfStatus, 405, FRAMES)
        self.assertEqual(CmdStatus.REJECTED_INVALID, status.surface_cmd_status)
        self.assertEqual(5.0, status.flap_cmd)
        self.assertAlmostEqual(3.5, status.trim_pitch, delta=LSB)
        self.assertTrue(status.sensors_valid and status.healthy)
        positions = self.last_in_window(framed, m.FsfPositions, 405, FRAMES)
        self.assertAlmostEqual(5.0, positions.flap_l, delta=LSB)
        self.assertAlmostEqual(5.0, positions.flap_r, delta=LSB)
        self.assertAlmostEqual(30.0, positions.speedbrake, delta=LSB)
        self.assertAlmostEqual(10.0, positions.rudder, delta=LSB)
        self.assertAlmostEqual(-4.0, positions.elevator_r, delta=LSB)
        term = self.last_in_window(framed, m.TermStatus, 300, FRAMES, rt=SURFACES_RT)
        self.assertEqual(TerminalState.NORMAL, term.state)
        self.assertTrue(term.healthy)
        self.assertIn("overruns=0", output)


if __name__ == "__main__":
    unittest.main()
