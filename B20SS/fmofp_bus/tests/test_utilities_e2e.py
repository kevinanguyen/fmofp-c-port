"""The four small utility terminals on the bus, end to end.

The plant (Python, in-process, its primary hydraulic pressure held at 2450 psi, its cabin at 24 C, 90 kPa and 93 %
clean air), the real fmofp_ecs, fmofp_hydraulics, fmofp_airframe and fmofp_fdm, with the real fmofp_fcs and
fmofp_fms (the FMS's gear command and flight data feed the airframe and the recorder) under the real fmofp_bc with a
script of commands: the oxygen generation rate, the humidity, the gear down through the FMS, the backup hydraulic
system by hand, the gear up by hand, a storage card ejected (twice: the second fails). The EICAS's bus half (no Qt)
receives the hydraulics and ECS statuses by its own relays. The monitor port shows the plant's readings reaching
the terminals by relay and the statuses following.

Needs FMOFP_BC, FMOFP_FCS, FMOFP_FMS, FMOFP_ECS, FMOFP_HYDRAULICS, FMOFP_AIRFRAME and FMOFP_FDM (CI sets them).
"""

import os
import subprocess
import tempfile
import threading
import time
import unittest

from fmofp_bus.icd import messages as m
from fmofp_bus.icd.enums import (AirframeCommand, CmdStatus, EcsCommand, FdmCommand, GearPosition, GearState,
                                 HydraulicCommand, HydraulicSystem, PressureStatus, TerminalState)
from fmofp_bus.monitor import Monitor
from fmofp_bus.status import Status
from fmofp_bus.tests._support import binary_env, needs
from fmofp_display.systems_feed import SystemsFeed
from fmofp_display.terminal import DisplayTerminal
from fmofp_plant.plant import PlantModel, PlantTerminal

PORT_BASE = 56500
FRAMES = 450
SYNC_MODE_CODE = 17
PLANT_RT = m.PlantSensors.RT
EICAS_RT = m.DspEicasStatus.RT
BINARIES = ("FMOFP_FCS", "FMOFP_FMS", "FMOFP_ECS", "FMOFP_HYDRAULICS", "FMOFP_AIRFRAME", "FMOFP_FDM")
TERMINALS = (PLANT_RT, m.FcsStatus.RT, m.FmsStatus.RT, m.EcsStatus.RT, m.HydStatus.RT, m.AfrStatus.RT, m.FdmStatus.RT,
             EICAS_RT)

SCRIPT = [
    (100, m.EcsCmd(cmd_seq=1, command=EcsCommand.SET_OXYGEN_RATE, value=1.5)),
    (150, m.FmsControlCmd(cmd_seq=1, gear_present=True, gear=GearPosition.DOWN)),
    (200, m.HydCmd(cmd_seq=1, command=HydraulicCommand.ACTIVATE_BACKUP)),
    (250, m.EcsCmd(cmd_seq=2, command=EcsCommand.SET_HUMIDITY, value=45.0)),
    (300, m.AfrCmd(cmd_seq=1, command=AirframeCommand.GEAR_RETRACT)),
    (350, m.FdmCmd(cmd_seq=1, command=FdmCommand.EJECT_STORAGE, slot=2)),
    (400, m.FdmCmd(cmd_seq=2, command=FdmCommand.EJECT_STORAGE, slot=2)),
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
class UtilitiesEndToEndTest(unittest.TestCase):
    processes = []
    plant_thread = None
    plant = None
    monitor = None
    eicas = None

    @classmethod
    def setUpClass(cls):
        cls.script = os.path.join(tempfile.mkdtemp(prefix="fmofp_utilities_"), "commands.txt")
        write_script(cls.script)
        try:
            model = PlantModel(seed=5, traffic=False, weather=False, ground=False)
            model.hold = dict(speed=450.0, heading=0.0, altitude=5000.0, vertical_speed=0.0, g_force=1.0,
                              primary_psi=2450.0, cabin_temperature=24.0, cabin_pressure=90.0, cabin_air_quality=93.0)
            cls.plant = PlantTerminal(model, PORT_BASE)
            assert cls.plant.init() == Status.OK, "plant port in use?"
            cls.plant_thread = PlantThread(cls.plant)
            cls.plant_thread.start()
            cls.monitor = Monitor(PORT_BASE)
            assert cls.monitor.open() == Status.OK, "monitor port in use?"
            cls.eicas = DisplayTerminal(EICAS_RT, PORT_BASE, m.DspEicasStatus, m.DspEicasModeCmd,
                                        receives=(m.EicasHydStatus, m.EicasEcsStatus))
            assert cls.eicas.start() == Status.OK, "EICAS port in use?"
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

    def test_the_four_terminals_follow_the_plant_the_fms_and_the_commands(self):
        self.monitor.drain()
        records, output = self.run_bus()
        framed = self.by_frame(records)
        self.assertGreaterEqual(framed[-1][0], FRAMES - 2)
        self.assertIn("script: 7 commands sent of 7", output)

        # The plant's readings reach the terminals by relay (the cabin at 5 Hz polls, the others once a second), the
        # FMS's control status reaches the airframe terminal, and the two statuses reach the EICAS alone.
        self.assertGreaterEqual(len(self.writes_into(framed, m.EcsStatus.RT, m.EcsCabin.SUBADDRESS)), 35)
        self.assertGreaterEqual(len(self.writes_into(framed, m.HydStatus.RT, m.HydPressures.SUBADDRESS)), 7)
        self.assertGreaterEqual(len(self.writes_into(framed, m.AfrStatus.RT, m.AfrSensors.SUBADDRESS)), 7)
        self.assertGreaterEqual(len(self.writes_into(framed, m.AfrStatus.RT, m.AfrFmsControl.SUBADDRESS)), 35)
        self.assertGreaterEqual(len(self.writes_into(framed, EICAS_RT, m.EicasHydStatus.SUBADDRESS)), 35)
        self.assertGreaterEqual(len(self.writes_into(framed, EICAS_RT, m.EicasEcsStatus.SUBADDRESS)), 35)

        # Frames 60-100: the readings are in. The cabin at 24 C, 90 kPa and 93 %: all three checks fire; the oxygen
        # climbs from 21 by 0.1 a reading (2 Hz); the climate copies the temperature.
        ecs = self.last_in_window(framed, m.EcsStatus, 60, 100)
        self.assertEqual(TerminalState.NORMAL, ecs.state)
        self.assertTrue(ecs.sensors_valid)
        self.assertEqual((24.0, 90.0, 93.0), (ecs.temperature, ecs.pressure, ecs.air_quality))
        self.assertTrue(ecs.temperature_adjusting and ecs.pressure_adjusting and ecs.purification_active)
        self.assertEqual(24.0, ecs.climate_temperature)
        self.assertEqual(50.0, ecs.humidity)
        self.assertTrue(21.0 < ecs.oxygen_level <= 21.5, ecs.oxygen_level)
        self.assertEqual(CmdStatus.NONE, ecs.ecs_cmd_status)
        # Frames 110-150: the 1 Hz readings are in (the plant's first at frame 50, relayed within the second), and the
        # oxygen rate was set at 100. The hydraulics: the primary held at 2450 psi (WARNING, at or under 2500), the
        # backup free, PRIMARY active.
        ecs = self.last_in_window(framed, m.EcsStatus, 110, 150)
        self.assertEqual((1.5, CmdStatus.ACCEPTED), (ecs.oxygen_rate, ecs.ecs_cmd_status))
        hyd = self.last_in_window(framed, m.HydStatus, 110, 150)
        self.assertEqual(TerminalState.NORMAL, hyd.state)
        self.assertTrue(hyd.pressures_valid)
        self.assertEqual((2450.0, HydraulicSystem.PRIMARY, PressureStatus.WARNING),
                         (hyd.primary_psi, hyd.active_system, hyd.pressure_status))
        self.assertTrue(2700.0 <= hyd.backup_psi <= 3100.0, hyd.backup_psi)
        # The airframe: the gauges follow the 1 g hold, the leading edge the 5000 ft, the gear RETRACTED (the FMS
        # reports UP before any command).
        afr = self.last_in_window(framed, m.AfrStatus, 110, 150)
        self.assertEqual(TerminalState.NORMAL, afr.state)
        self.assertTrue(afr.sensors_valid)
        self.assertAlmostEqual(180.0, afr.wing_root_strain, delta=5.0)
        self.assertAlmostEqual(110.0, afr.fuselage_strain, delta=5.0)
        self.assertAlmostEqual(5.0, afr.leading_edge_temp, delta=0.5)
        self.assertEqual(GearState.RETRACTED, afr.gear_state)
        # The recorder: the FMS flight data by broadcast, a record every 25 frames, both cards in.
        fdm = self.last_in_window(framed, m.FdmStatus, 110, 150)
        self.assertEqual(TerminalState.NORMAL, fdm.state)
        self.assertTrue(fdm.flight_data_valid and fdm.slot_1_present and fdm.slot_2_present)
        self.assertGreaterEqual(fdm.records, 1)

        # Frames 260-300: the oxygen rate set at 100, the gear down through the FMS at 150, the backup system by
        # hand at 200 (its pressure is judged now: OK), the humidity at 250.
        ecs = self.last_in_window(framed, m.EcsStatus, 260, 300)
        self.assertEqual((1.5, 45.0, CmdStatus.ACCEPTED), (ecs.oxygen_rate, ecs.humidity, ecs.ecs_cmd_status))
        self.assertGreater(ecs.oxygen_level, 21.5)
        hyd = self.last_in_window(framed, m.HydStatus, 260, 300)
        self.assertEqual((HydraulicSystem.BACKUP, PressureStatus.OK, CmdStatus.ACCEPTED),
                         (hyd.active_system, hyd.pressure_status, hyd.hyd_cmd_status))
        self.assertEqual(2450.0, hyd.primary_psi, "still reported")
        afr = self.last_in_window(framed, m.AfrStatus, 260, 300)
        self.assertEqual(GearState.DEPLOYED, afr.gear_state)
        # Frames 405-450: the gear up by hand at 300 (and the FMS still saying DOWN leaves it alone), the CVR card
        # ejected at 350, the second ejection at 400 failed; records keep coming.
        afr = self.last_in_window(framed, m.AfrStatus, 405, FRAMES)
        self.assertEqual((GearState.RETRACTED, CmdStatus.ACCEPTED), (afr.gear_state, afr.afr_cmd_status))
        fdm = self.last_in_window(framed, m.FdmStatus, 405, FRAMES)
        self.assertEqual((True, False, CmdStatus.FAILED), (fdm.slot_1_present, fdm.slot_2_present, fdm.fdm_cmd_status))
        self.assertGreaterEqual(fdm.records, 12)
        self.assertEqual(fdm.records, fdm.held)
        self.assertAlmostEqual(5000.0, fdm.last_altitude, delta=1.0)
        self.assertAlmostEqual(450.0, fdm.last_airspeed, delta=0.2)
        for rt in (m.EcsStatus.RT, m.HydStatus.RT, m.AfrStatus.RT, m.FdmStatus.RT):
            term = self.last_in_window(framed, m.TermStatus, 360, FRAMES, rt=rt)
            self.assertEqual(TerminalState.NORMAL, term.state, rt)
            self.assertTrue(term.healthy)

        # What the EICAS would show, from its own terminal: SYS A the primary (2450, reduced), SYS B the backup,
        # CAB TEMP 24 C, CAB ALT the pressure altitude of 90 kPa.
        feed = SystemsFeed(self.eicas, stale_after_s=60.0)
        readings = feed.system_readings()
        self.assertEqual({"sys_a_psi", "sys_b_psi", "cabin_temp_c", "cabin_alt_ft"}, set(readings),
                         "no power terminal here: the electrical keys are absent")
        self.assertEqual((2450.0, 24.0), (readings["sys_a_psi"], readings["cabin_temp_c"]))
        self.assertTrue(2700.0 <= readings["sys_b_psi"] <= 3100.0, readings)
        self.assertAlmostEqual(3243.0, readings["cabin_alt_ft"], delta=15.0)
        self.assertEqual("Backup hydraulic system", feed.hydraulics.get_status()["active_system"])
        self.assertEqual(45.0, feed.ecs.get_status()["climate"]["humidity"])
        self.assertIn("HYD 2450/", feed.status_text())
        self.assertIn("ECS 24.0C", feed.status_text())
        self.assertIn("overruns=0", output)


if __name__ == "__main__":
    unittest.main()
