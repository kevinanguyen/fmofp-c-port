"""The avionics terminal on the bus, end to end.

The plant (Python, in-process), the real fmofp_fcs and the real fmofp_avionics under the real fmofp_bc, with the
EICAS's bus half (no Qt) receiving the avionics status by relay.

First run, with a script of commands: the bus controller's own AVN_BUS_HEALTH report reaches RT 1 once a second
from the second major frame on; the power-on self test and the first periodic tests run on the first report (the
flight control terminal answers; navigation, the mission computer and communications are not on this bus, so
their LRUs read OFFLINE and their probes FAIL); the scenario engine's failure injection forces a fault on the
flight control computer and on a system that is no LRU, clears the first, runs the initiated test, applies a
data load, clears everything, and an empty command is rejected.

Second run, without the plant: the flight control computer loses its sensors and reports DEGRADED in its
TERM_STATUS; the bus controller's report carries it and the three LRUs of that terminal turn DEGRADED with it.

Needs FMOFP_BC, FMOFP_FCS and FMOFP_AVIONICS (CI sets them).
"""

import os
import subprocess
import tempfile
import threading
import time
import unittest

from fmofp_bus.avionics import key_fields
from fmofp_bus.icd import messages as m
from fmofp_bus.icd.enums import AvionicsCommand, BitStatus, CmdStatus, FitnessStatus, LruHealth, TerminalState
from fmofp_bus.monitor import Monitor
from fmofp_bus.status import Status
from fmofp_bus.tests._support import binary_env, free_port_base, needs
from fmofp_display.systems_feed import SystemsFeed
from fmofp_display.terminal import DisplayTerminal
from fmofp_plant.plant import PlantModel, PlantTerminal

PORT_BASE = free_port_base(55500)
FRAMES = 460
SYNC_MODE_CODE = 17
AVIONICS_RT = m.AvnStatus.RT
FCS_RT = m.FcsStatus.RT
PLANT_RT = m.PlantSensors.RT
EICAS_RT = m.DspEicasStatus.RT
FCS_SLOTS = 0x0601  # FCC-1, GCAS-1 and PERF-1: table slots 0, 9 and 10

SCRIPT = [
    (150, m.AvnCmd(cmd_seq=1, command=AvionicsCommand.FORCE_FAULT, health=LruHealth.FAULT,
                   **key_fields("flight_control_computer"))),
    (200, m.AvnCmd(cmd_seq=2, command=AvionicsCommand.FORCE_FAULT, health=LruHealth.DEGRADED,
                   **key_fields("engine_vibration"))),
    (250, m.AvnCmd(cmd_seq=3, command=AvionicsCommand.CLEAR_FAULT, **key_fields("flight_control_computer"))),
    (300, m.AvnCmd(cmd_seq=4, command=AvionicsCommand.RUN_INITIATED_BIT)),
    (350, m.AvnCmd(cmd_seq=5, command=AvionicsCommand.APPLY_DATA_LOAD, data_load=20190601.0)),
    (400, m.AvnCmd(cmd_seq=6, command=AvionicsCommand.CLEAR_ALL_FAULTS)),
    (430, m.AvnCmd(cmd_seq=7, command=AvionicsCommand.NONE)),
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


@needs("FMOFP_BC", "FMOFP_FCS", "FMOFP_AVIONICS")
class AvionicsEndToEndTest(unittest.TestCase):
    processes = []
    plant_thread = None
    plant = None
    monitor = None
    eicas = None

    @classmethod
    def setUpClass(cls):
        cls.script = os.path.join(tempfile.mkdtemp(prefix="fmofp_avionics_"), "commands.txt")
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
                                        receives=(m.EicasAvnStatus,))
            assert cls.eicas.start() == Status.OK, "EICAS port in use?"
            for name in ("FMOFP_FCS", "FMOFP_AVIONICS"):
                cls.processes.append(subprocess.Popen(
                    [os.environ[name], "--port-base", str(PORT_BASE), "--quiet"], stdout=subprocess.PIPE,
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

    def run_bus(self, terminals, frames, script=None):
        command = [os.environ["FMOFP_BC"]]
        for rt in terminals:
            command += ["--rt", str(rt)]
        command += ["--port-base", str(PORT_BASE), "--frames", str(frames), "--free-run", "--strict",
                    "--timeout-ms", "40"]
        if script is not None:
            command += ["--script", script]
        bc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=binary_env())
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
        return [(frame, r) for frame, r in framed if not r.command.transmit and not r.command.is_mode_code
                and r.command.rt == rt and r.command.subaddress == subaddress]

    def test_1_reports_tests_and_forced_faults_follow_the_script(self):
        self.monitor.drain()
        records, output = self.run_bus((PLANT_RT, FCS_RT, AVIONICS_RT, EICAS_RT), FRAMES, self.script)
        framed = self.by_frame(records)
        self.assertGreaterEqual(framed[-1][0], FRAMES - 2)
        self.assertIn("script: 7 commands sent of 7", output)

        # The controller writes its report into RT 1 once a second: nothing (epoch 0) during the first major
        # frame, then a new epoch each second, with the terminals of this bus listed and answering.
        reports = []
        for frame, record in self.writes_into(framed, AVIONICS_RT, m.AvnBusHealth.SUBADDRESS):
            status, report = m.AvnBusHealth.decode(record.sent)
            self.assertEqual(Status.OK, status)
            reports.append((frame, report))
        self.assertGreaterEqual(len(reports), 8)
        self.assertEqual(0, reports[0][1].epoch, "the first major frame has nothing to report")
        epochs = [report.epoch for _, report in reports[1:]]
        self.assertEqual(list(range(1, len(epochs) + 1)), epochs)
        last = reports[-1][1]
        on_bus = sum(1 << rt for rt in (PLANT_RT, FCS_RT, AVIONICS_RT, EICAS_RT))
        for name in ("listed", "responded", "answering", "status"):
            mask = (getattr(last, f"{name}_mask_hi") << 16) | getattr(last, f"{name}_mask_lo")
            self.assertEqual(on_bus, mask, name)
        # The plant is test equipment and leaves TERM_STATUS.healthy at 0; the aircraft's terminals set it.
        healthy = (last.healthy_mask_hi << 16) | last.healthy_mask_lo
        self.assertEqual(on_bus & ~(1 << PLANT_RT), healthy)
        normal = (last.normal_mask_hi << 16) | last.normal_mask_lo
        self.assertTrue(normal & (1 << FCS_RT), "the flight control computer has its sensors: NORMAL")
        self.assertEqual((0, 0), (last.failure_mask_hi, last.failure_mask_lo))
        # The status reaches the EICAS alone, five times a second.
        self.assertGreaterEqual(len(self.writes_into(framed, EICAS_RT, m.EicasAvnStatus.SUBADDRESS)), 40)

        # Frames 20-50: answering, no report yet: nothing is known.
        status = self.last_in_window(framed, m.AvnStatus, 20, 50)
        self.assertEqual(TerminalState.INITIALIZING, status.state)
        self.assertFalse(status.bus_health_valid or status.post_complete)
        self.assertEqual((LruHealth.UNKNOWN, 11, 0), (status.overall_health, status.lru_count, status.fault_count))
        self.assertEqual(BitStatus.PENDING, status.post_fcc_cpu)

        # Frames 110-150: the first report is in. The power-on self test: the flight control computer answers,
        # navigation is not on this bus. The periodic tests were all due. The LRUs of the terminals that are not
        # here read OFFLINE, which is DEGRADED overall and no fault.
        status = self.last_in_window(framed, m.AvnStatus, 110, 150)
        self.assertEqual(TerminalState.NORMAL, status.state)
        self.assertTrue(status.bus_health_valid and status.post_complete and status.healthy)
        self.assertEqual((BitStatus.PASS,) * 3, (status.post_fcc_cpu, status.post_fcc_memory, status.post_fcc_databus))
        self.assertEqual((BitStatus.FAIL,) * 3,
                         (status.post_nav_cpu, status.post_nav_sensors, status.post_nav_gps_receiver))
        self.assertEqual((BitStatus.PASS, BitStatus.FAIL, BitStatus.FAIL, BitStatus.FAIL, BitStatus.FAIL),
                         (status.pbit_flight_control, status.pbit_mission, status.pbit_datalink, status.pbit_satcom,
                          status.pbit_radios))
        self.assertEqual((2, 5), (status.pbit_avionics_stored, status.pbit_comm_stored),
                         "BIT-COMM holds BIT-AVIONICS's two results with its own three")
        self.assertEqual((LruHealth.DEGRADED, 11, 0, 0),
                         (status.overall_health, status.lru_count, status.fault_count, status.forced_count))
        self.assertEqual((0, 0, 0), (status.lru_fault_mask, status.lru_degraded_mask, status.lru_forced_mask))
        self.assertEqual((FitnessStatus.OK,) * 3,
                         (status.fitness_flight_control, status.fitness_navigation, status.fitness_avionics))
        self.assertEqual((5, 2, 1, True), (status.sw_flight_control_major, status.sw_flight_control_minor,
                                           status.sw_flight_control_patch, status.sw_flight_control_has_patch))
        self.assertEqual((3, 8, False, 2, 5, False),
                         (status.sw_mission_major, status.sw_mission_minor, status.sw_mission_has_patch,
                          status.sw_comms_major, status.sw_comms_minor, status.sw_comms_has_patch))
        self.assertEqual(CmdStatus.NONE, status.avionics_cmd_status)

        # Frames 160-200: the scenario's failure on the flight control computer, at once and through the reports.
        status = self.last_in_window(framed, m.AvnStatus, 160, 200)
        self.assertEqual((LruHealth.FAULT, 1, 1), (status.overall_health, status.fault_count, status.forced_count))
        self.assertEqual((0x0001, 0x0001), (status.lru_fault_mask, status.lru_forced_mask))
        self.assertEqual(CmdStatus.ACCEPTED, status.avionics_cmd_status)
        # Frames 210-250: a system that is no LRU is declared, in the first free slot.
        status = self.last_in_window(framed, m.AvnStatus, 210, 250)
        self.assertEqual((12, 2, 2), (status.lru_count, status.fault_count, status.forced_count))
        self.assertEqual((0x0001, 0x0800, 0x0801),
                         (status.lru_fault_mask, status.lru_degraded_mask, status.lru_forced_mask))
        # Frames 310-350: the first fault cleared at 250 and a report since: the computer is NOMINAL again, the
        # declared entry still DEGRADED. The initiated test of frame 300: fifteen probes, seven on what answers
        # (the flight control computer five times, the two systems without a terminal).
        status = self.last_in_window(framed, m.AvnStatus, 310, 350)
        self.assertEqual((LruHealth.DEGRADED, 12, 1, 1),
                         (status.overall_health, status.lru_count, status.fault_count, status.forced_count))
        self.assertEqual((0, 0x0800, 0x0800), (status.lru_fault_mask, status.lru_degraded_mask, status.lru_forced_mask))
        self.assertEqual((1, 7, 8, 0), (status.ibit_runs, status.ibit_pass, status.ibit_fail, status.ibit_abort))
        self.assertEqual((2, 5), (status.pbit_avionics_stored, status.pbit_comm_stored),
                         "neither the initiated run nor the later reports run a periodic test again")
        # Frames 360-400: data load 20190601 takes the flight control software to 5.2.
        status = self.last_in_window(framed, m.AvnStatus, 360, 400)
        self.assertEqual((5, 2, False), (status.sw_flight_control_major, status.sw_flight_control_minor,
                                         status.sw_flight_control_has_patch))
        self.assertEqual((20190601.0, 1), (status.last_data_load, status.data_loads_applied))
        # Frames 405-430: everything cleared; the declared entry is gone.
        status = self.last_in_window(framed, m.AvnStatus, 405, 430)
        self.assertEqual((11, 0, 0, 0), (status.lru_count, status.fault_count, status.forced_count,
                                         status.lru_forced_mask))
        self.assertEqual(CmdStatus.ACCEPTED, status.avionics_cmd_status)
        # The empty command at 430.
        status = self.last_in_window(framed, m.AvnStatus, 435, FRAMES)
        self.assertEqual(CmdStatus.REJECTED_INVALID, status.avionics_cmd_status)
        self.assertEqual(BitStatus.PASS, status.post_fcc_cpu, "the power-on results stand")
        term = self.last_in_window(framed, m.TermStatus, 360, FRAMES, rt=AVIONICS_RT)
        self.assertEqual(TerminalState.NORMAL, term.state)
        self.assertEqual((m.ICD_MAJOR, m.ICD_MINOR), (term.icd_major, term.icd_minor))

        # What the EICAS would show, from its own terminal: one BITS row per self test.
        self.assertIsNotNone(self.eicas.fresh(m.EicasAvnStatus, stale_after_s=60.0), "AVN_STATUS reached the EICAS")
        feed = SystemsFeed(self.eicas, stale_after_s=60.0)
        self.assertEqual(["POST-FCC: PASS", "POST-NAV: FAIL"], feed.bit_results())
        data = feed.avionics_data()
        self.assertEqual(("DEGRADED", 11, 0, 0, True), (data["overall_health"], data["lru_count"], data["fault_count"],
                                                         data["forced_count"], data["post_complete"]))
        self.assertIn("AVN DEGRADED 0/11 faults", feed.status_text())
        self.assertIn("overruns=0", output)

    def test_2_a_degraded_terminal_degrades_its_lrus(self):
        """Without the plant the flight control computer's sensors go stale: it reports DEGRADED in TERM_STATUS,
        the controller's report says so, and FCC-1, GCAS-1 and PERF-1 follow."""
        self.monitor.drain()
        records, output = self.run_bus((FCS_RT, AVIONICS_RT, EICAS_RT), 210)
        framed = self.by_frame(records)
        term = self.last_in_window(framed, m.TermStatus, 100, 210, rt=FCS_RT)
        self.assertEqual(TerminalState.DEGRADED, term.state)
        status = self.last_in_window(framed, m.AvnStatus, 160, 210)
        self.assertEqual(TerminalState.NORMAL, status.state, "the avionics computer itself is fine")
        self.assertEqual(FCS_SLOTS, status.lru_degraded_mask)
        self.assertEqual((LruHealth.DEGRADED, 3, 0), (status.overall_health, status.fault_count, status.forced_count))
        self.assertEqual(BitStatus.PASS, status.post_fcc_cpu, "the power-on self test is not run again")
        self.assertIn("overruns=0", output)


if __name__ == "__main__":
    unittest.main()
