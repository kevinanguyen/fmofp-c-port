"""The crew alerting terminal on the bus, end to end.

The plant (Python, in-process, its primary hydraulic pressure held at 2450 psi), the real fmofp_fcs, fmofp_fms,
fmofp_engine, fmofp_hydraulics, fmofp_power, fmofp_defensive and fmofp_cas under the real fmofp_bc with a script of
commands: the FMS to COMBAT (its engine power 1.0: the EGT model at 800 C and the maximum-thrust advisory), the
generator held at zero (both GEN rows FAULT), 55 chaff cartridges released (CHAFF LOW) and a priority-1 threat
injected (RWR HIGH-PRI). The crew alerting terminal hears the broadcasts and its four relays; the EICAS's bus half
(no Qt) receives its list by relay and the window's feed builds the texts. The monitor port shows CAS_ALERTS
following each command.

Needs FMOFP_BC, FMOFP_FCS, FMOFP_FMS, FMOFP_ENGINE, FMOFP_HYDRAULICS, FMOFP_POWER, FMOFP_DEFENSIVE and FMOFP_CAS
(CI sets them).
"""

import os
import subprocess
import tempfile
import threading
import time
import unittest

from fmofp_bus.icd import messages as m
from fmofp_bus.icd.enums import (DefensiveCommand, FmsFlightMode, PowerCommand, RwrBand, TerminalState, ThreatType)
from fmofp_bus.monitor import Monitor
from fmofp_bus.status import Status
from fmofp_bus.tests._support import binary_env, free_port_base, needs
from fmofp_display.systems_feed import SystemsFeed
from fmofp_display.terminal import DisplayTerminal
from fmofp_plant.plant import PlantModel, PlantTerminal

PORT_BASE = free_port_base(62500)
FRAMES = 420
SYNC_MODE_CODE = 17
PLANT_RT = m.PlantSensors.RT
EICAS_RT = m.DspEicasStatus.RT
CAS_RT = m.CasAlerts.RT
BINARIES = ("FMOFP_FCS", "FMOFP_FMS", "FMOFP_ENGINE", "FMOFP_HYDRAULICS", "FMOFP_POWER", "FMOFP_DEFENSIVE", "FMOFP_CAS")
TERMINALS = (PLANT_RT, m.FcsStatus.RT, m.FmsStatus.RT, m.EngStatus.RT, m.HydStatus.RT, m.PwrStatus.RT,
             m.DefStatus.RT, CAS_RT, EICAS_RT)

SCRIPT = [
    (150, m.FmsFlightModeCmd(cmd_seq=1, flight_mode=FmsFlightMode.COMBAT)),
    (200, m.PwrCmd(cmd_seq=1, command=PowerCommand.SET_GENERATOR_OUTPUT, value=0.0)),
    (250, m.DefCmd(cmd_seq=1, command=DefensiveCommand.DISPENSE_CHAFF, count=55)),
    (300, m.DefCmd(cmd_seq=2, command=DefensiveCommand.INJECT_THREAT, threat_id=3, bearing=45.0, range=20.0,
                   band=RwrBand.X, threat_type=ThreatType.SAM, priority=1)),
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
class CasEndToEndTest(unittest.TestCase):
    processes = []
    plant_thread = None
    plant = None
    monitor = None
    eicas = None

    @classmethod
    def setUpClass(cls):
        cls.script = os.path.join(tempfile.mkdtemp(prefix="fmofp_cas_"), "commands.txt")
        write_script(cls.script)
        try:
            model = PlantModel(seed=9, traffic=False, weather=False, ground=False)
            model.hold = dict(speed=450.0, heading=0.0, altitude=5000.0, vertical_speed=0.0, g_force=1.0,
                              primary_psi=2450.0)
            cls.plant = PlantTerminal(model, PORT_BASE)
            assert cls.plant.init() == Status.OK, "plant port in use?"
            cls.plant_thread = PlantThread(cls.plant)
            cls.plant_thread.start()
            cls.monitor = Monitor(PORT_BASE)
            assert cls.monitor.open() == Status.OK, "monitor port in use?"
            cls.eicas = DisplayTerminal(EICAS_RT, PORT_BASE, m.DspEicasStatus, m.DspEicasModeCmd,
                                        receives=(m.EicasCasAlerts,))
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

    def all_in_window(self, framed, cls, first, last):
        out = []
        for frame, record in framed:
            cw = record.command
            if (first <= frame < last and cw.transmit and not cw.is_mode_code and cw.rt == cls.RT
                    and cw.subaddress == cls.SUBADDRESS and record.answered):
                status, msg = cls.decode(record.received)
                self.assertEqual(Status.OK, status)
                out.append(msg)
        self.assertTrue(out, f"no {cls.__name__} in frames {first}..{last - 1}")
        return out

    def test_the_alerts_follow_the_bus_and_reach_the_eicas(self):
        self.monitor.drain()
        records, output = self.run_bus()
        framed = self.by_frame(records)
        self.assertGreaterEqual(framed[-1][0], FRAMES - 2)
        self.assertIn("script: 4 commands sent of 4", output)

        # Before the commands: the held primary pressure (2450 psi) is HYD A's caution, SYS C has no system behind
        # it, and every other input is heard and in limits (NORMAL's power: the EGT model at 665 C).
        before = self.all_in_window(framed, m.CasAlerts, 120, 150)
        for alerts in before:
            self.assertEqual(TerminalState.NORMAL, alerts.state)
            self.assertTrue(alerts.computed)
            self.assertTrue(alerts.hyd_a_reduced, alerts)
            self.assertTrue(alerts.hyd_c_unknown)
            for quiet in ("hyd_b_reduced", "hyd_b_unknown", "eng_egt_caution", "eng_max_continuous_thrust",
                          "eng_oil_press_unknown", "fuel_qty_unknown", "fuel_balance_unknown", "elec_gen_1_unknown",
                          "elec_gen_1_fault", "elec_bus_volts_unknown", "cmds_chaff_low", "rwr_high_pri_threats"):
                self.assertFalse(getattr(alerts, quiet), quiet)
            self.assertEqual((60, 30), (alerts.chaff_remaining, alerts.flares_remaining))

        # COMBAT: the profile's power 1.0, the EGT model at 800 C (a caution, not above 800) and the advisory.
        combat = self.all_in_window(framed, m.CasAlerts, 180, 200)
        self.assertTrue(all(a.eng_egt_caution and a.eng_max_continuous_thrust and not a.eng_egt_high for a in combat))

        # The generator held at zero: both GEN rows FAULT once the next reading reaches the power terminal.
        held = self.all_in_window(framed, m.CasAlerts, 360, FRAMES)
        self.assertTrue(all(a.elec_gen_1_fault and a.elec_gen_2_fault for a in held), held[0])

        # 55 chaff released: 5 left, a caution with the number in its text.
        def_status = [msg for msg in self.all_in_window(framed, m.DefStatus, 360, FRAMES)][-1]
        last = held[-1]
        self.assertEqual(def_status.chaff_remaining, last.chaff_remaining)
        self.assertTrue(0 < last.chaff_remaining <= 10, last.chaff_remaining)
        self.assertTrue(last.cmds_chaff_low)

        # The injected priority-1 threat: a hostile contact of the receiver's block, the warning with its count.
        self.assertTrue(last.rwr_high_pri_threats, last)
        self.assertEqual(1, last.rwr_high_priority)
        self.assertGreaterEqual(last.rwr_hostile, 1)
        self.assertEqual(last.warning_count, sum(1 for name in ("elec_gen_1_fault", "elec_gen_2_fault",
                                                                  "rwr_high_pri_threats") if getattr(last, name)))

        # The EICAS hears the list by its own relay, and the window's feed builds the texts in eicas.py's order.
        texts = [a["text"] for a in SystemsFeed(self.eicas).cas_alerts()]
        for text in ("ENG  EGT CAUTION", "HYD A  PRESS REDUCED", "HYD C  PRESSURE UNKNOWN", "ELEC  GEN 1 FAULT",
                     "ELEC  GEN 2 FAULT", "ENG  MAX CONTINUOUS THRUST", "RWR  1 HIGH-PRI THREAT(S)",
                     f"CMDS  CHAFF LOW ({last.chaff_remaining})"):
            self.assertIn(text, texts)
        self.assertLess(texts.index("ENG  EGT CAUTION"), texts.index("HYD A  PRESS REDUCED"))
        self.assertLess(texts.index("ENG  MAX CONTINUOUS THRUST"), texts.index("RWR  1 HIGH-PRI THREAT(S)"))
        relayed = [r for _, r in framed if not r.command.transmit and not r.command.is_mode_code
                   and r.command.rt == EICAS_RT and r.command.subaddress == m.EicasCasAlerts.SUBADDRESS]
        self.assertGreaterEqual(len(relayed), (FRAMES - 60) // 10, "CAS_ALERTS relayed at 5 Hz")


if __name__ == "__main__":
    unittest.main()
