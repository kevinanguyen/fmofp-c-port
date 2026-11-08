"""The power management terminal on the bus, end to end.

The plant (Python, in-process, with its electrical readings) and the real fmofp_power under the real fmofp_bc with
a script of commands: the generator is held at zero (the main battery carries the whole consumption and both
generator rows read FAIL at the EICAS), then released (the surplus charges it again), the emergency power is
switched on (the emergency battery takes its load), the cabin setpoint is moved, and a command with nothing in it
is rejected. The EICAS's bus half (no Qt) receives the status by relay. The monitor port shows the plant's
readings reaching the terminal by relay, the terminal's generator command reaching the plant by relay, and
PWR_STATUS following.

Needs FMOFP_BC and FMOFP_POWER (CI sets them).
"""

import os
import subprocess
import tempfile
import threading
import time
import unittest

from fmofp_bus.icd import messages as m
from fmofp_bus.icd.enums import CmdStatus, PowerCommand, TerminalState, ThermalStatus
from fmofp_bus.monitor import Monitor
from fmofp_bus.status import Status
from fmofp_bus.tests._support import binary_env, needs
from fmofp_display.systems_feed import SystemsFeed
from fmofp_display.terminal import DisplayTerminal
from fmofp_plant.plant import PlantModel, PlantTerminal

PORT_BASE = 54500
FRAMES = 450
SYNC_MODE_CODE = 17
POWER_RT = m.PwrStatus.RT
PLANT_RT = m.PlantSensors.RT
EICAS_RT = m.DspEicasStatus.RT

SCRIPT = [
    (100, m.PwrCmd(cmd_seq=1, command=PowerCommand.SET_GENERATOR_OUTPUT, value=0.0)),
    (250, m.PwrCmd(cmd_seq=2, command=PowerCommand.GENERATOR_AUTO)),
    (300, m.PwrCmd(cmd_seq=3, command=PowerCommand.EMERGENCY_POWER_ON)),
    (350, m.PwrCmd(cmd_seq=4, command=PowerCommand.HVAC_SETPOINT, value=26.0)),
    (400, m.PwrCmd(cmd_seq=5, command=PowerCommand.NONE)),
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


@needs("FMOFP_BC", "FMOFP_POWER")
class PowerEndToEndTest(unittest.TestCase):
    processes = []
    plant_thread = None
    plant = None
    monitor = None
    eicas = None

    @classmethod
    def setUpClass(cls):
        cls.script = os.path.join(tempfile.mkdtemp(prefix="fmofp_power_"), "commands.txt")
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
                                        receives=(m.EicasPwrStatus,))
            assert cls.eicas.start() == Status.OK, "EICAS port in use?"
            cls.processes.append(subprocess.Popen(
                [os.environ["FMOFP_POWER"], "--port-base", str(PORT_BASE), "--quiet"], stdout=subprocess.PIPE,
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
            [os.environ["FMOFP_BC"], "--rt", str(PLANT_RT), "--rt", str(POWER_RT), "--rt", str(EICAS_RT),
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

    def all_in_window(self, framed, cls, first, last):
        out = []
        for frame, record in framed:
            cw = record.command
            if (first <= frame < last and cw.transmit and not cw.is_mode_code and cw.rt == cls.RT
                    and cw.subaddress == cls.SUBADDRESS and record.answered):
                status, msg = cls.decode(record.received)
                self.assertEqual(Status.OK, status)
                out.append(msg)
        return out

    @staticmethod
    def writes_into(framed, rt, subaddress):
        return [r for _, r in framed if not r.command.transmit and not r.command.is_mode_code
                and r.command.rt == rt and r.command.subaddress == subaddress]

    def test_the_generator_hold_the_batteries_and_the_commands_follow_the_script(self):
        self.monitor.drain()
        records, output = self.run_bus()
        framed = self.by_frame(records)
        self.assertGreaterEqual(framed[-1][0], FRAMES - 2)
        self.assertIn("script: 5 commands sent of 5", output)

        # The plant's readings reach the terminal by relay once a second, the terminal's generator command reaches
        # the plant by relay five times a second, and the status reaches the EICAS alone.
        self.assertGreaterEqual(len(self.writes_into(framed, POWER_RT, m.PwrElectrical.SUBADDRESS)), 7)
        self.assertGreaterEqual(len(self.writes_into(framed, PLANT_RT, m.PlantGenCmd.SUBADDRESS)), 30)
        self.assertGreaterEqual(len(self.writes_into(framed, EICAS_RT, m.EicasPwrStatus.SUBADDRESS)), 30)

        # Frames 20-60: the terminal answers from the start, no command yet, the first reading maybe not yet either.
        status = self.last_in_window(framed, m.PwrStatus, 20, 60)
        self.assertIn(status.state, (TerminalState.INITIALIZING, TerminalState.NORMAL))
        self.assertEqual(CmdStatus.NONE, status.power_cmd_status)
        self.assertEqual((100.0, 100.0, 100.0), (status.main_battery_charge, status.emergency_battery_charge,
                                                 status.apu_battery_charge))
        # Frames 110-150: the first readings are in, the generator runs (the hold commanded at 100 reaches the plant
        # for its reading at 150), the batteries are all but full.
        status = self.last_in_window(framed, m.PwrStatus, 110, 150)
        self.assertEqual(TerminalState.NORMAL, status.state)
        self.assertTrue(status.electrical_valid and status.generator_online)
        self.assertTrue(200.0 <= status.generator_output <= 250.0, status.generator_output)
        self.assertTrue(180.0 <= status.total_power_consumption <= 220.0, status.total_power_consumption)
        self.assertTrue(110.0 <= status.main_bus_voltage <= 120.0, status.main_bus_voltage)
        self.assertGreaterEqual(status.main_battery_charge, 99.0, "a deficit second costs under 0.6 %")
        self.assertEqual((100.0, 100.0), (status.emergency_battery_charge, status.apu_battery_charge))
        self.assertEqual(ThermalStatus.OK, status.thermal_status)
        self.assertTrue(status.hvac_at_setpoint and status.hvac_powered and status.dissipation_active)
        self.assertEqual(CmdStatus.ACCEPTED, status.power_cmd_status, "the hold commanded at frame 100")
        # Frames 210-260: the generator held at zero since frame 100 (the plant's next reading at 150, relayed within
        # the second): the whole consumption off the main battery, 5-6 % a second.
        status = self.last_in_window(framed, m.PwrStatus, 210, 260)
        self.assertEqual((False, 0.0, CmdStatus.ACCEPTED), (status.generator_online, status.generator_output,
                                                             status.power_cmd_status))
        self.assertLess(status.power_balance, -150.0)
        self.assertLess(status.main_battery_charge, 97.0)
        # The hold lasts three readings (150, 200, 250: the release at 250 misses the plant's step at 250), each
        # costing 5-6 %; the trough comes with the third, relayed before 300.
        charges = [msg.main_battery_charge for msg in self.all_in_window(framed, m.PwrStatus, 260, FRAMES)]
        low = min(charges)
        self.assertLess(low, 88.0, charges)
        # Frames 360-450: released at 250, the generator runs again from the plant's reading at 300 and the surplus
        # charges the battery; the emergency mode is on from 300 (its battery drains 8 A a second); the cabin
        # setpoint moved at 350; the empty command at 400 is rejected.
        status = self.last_in_window(framed, m.PwrStatus, 360, FRAMES)
        self.assertTrue(status.generator_online)
        self.assertTrue(200.0 <= status.generator_output <= 250.0, status.generator_output)
        self.assertLess(status.main_battery_charge, 100.0, "not refilled yet")
        self.assertTrue(status.emergency_mode_active)
        status = self.last_in_window(framed, m.PwrStatus, 405, FRAMES)
        self.assertEqual(CmdStatus.REJECTED_INVALID, status.power_cmd_status)
        self.assertLess(status.emergency_battery_charge, 100.0, "the critical load since frame 300")
        self.assertFalse(status.hvac_at_setpoint, "22 C against a 26 C setpoint")
        self.assertGreater(status.main_battery_charge, low, "charging again from the trough")
        term = self.last_in_window(framed, m.TermStatus, 360, FRAMES, rt=POWER_RT)
        self.assertEqual(TerminalState.NORMAL, term.state)
        self.assertGreaterEqual(self.plant.generator_commands, 2, "the hold and its release reached the plant")

        # What the EICAS would show, from its own terminal: the bus voltages, both generator rows from the one
        # generator (online again), and the snapshot for the status line.
        relayed = self.eicas.fresh(m.EicasPwrStatus, stale_after_s=60.0)
        self.assertIsNotNone(relayed, "PWR_STATUS reached the EICAS by relay")
        feed = SystemsFeed(self.eicas, stale_after_s=60.0)
        electrical = feed.system_readings()
        self.assertEqual({"main_bus_v", "ess_bus_v", "gen1_ok", "gen2_ok"}, set(electrical))
        self.assertTrue(110.0 <= electrical["main_bus_v"] <= 120.0, electrical)
        self.assertTrue(25.0 <= electrical["ess_bus_v"] <= 28.0, electrical)
        self.assertTrue(electrical["gen1_ok"] and electrical["gen2_ok"])
        power = feed.power.get_data()
        self.assertTrue(200.0 <= power["generator_output"] <= 250.0, power)
        self.assertTrue(power["emergency_mode_active"])
        self.assertIn("PWR gen ", feed.status_text())
        self.assertIn(" EMERG", feed.status_text())
        self.assertIn("overruns=0", output)


if __name__ == "__main__":
    unittest.main()
