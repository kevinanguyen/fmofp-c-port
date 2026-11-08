"""The defensive systems terminal on the bus, end to end.

The plant (Python, in-process, with its air traffic and its ESM intercepts), the real fmofp_radar (its targeting
radar switched to TARGET_SEARCH, so the fusion broadcasts the hostile tracks its rule finds) and the real
fmofp_defensive under the real fmofp_bc with a script of commands: a priority-1 SAM is injected on the radar
warning receiver (the automatic salvo follows at the next update, and again once the cooldown has passed), the
jammer goes active, chaff is dispensed, a flare request fails inside the cooldown and another succeeds after it.
Two display terminals of this process (the EICAS's and the TSD's bus halves, no Qt) receive what the windows
would: DEF_STATUS relayed to the EICAS alone, the contacts block broadcast to both. The monitor port shows the
plant's PLANT_ESM reaching the terminal by relay, DEF_STATUS and the DEF_RWR_CONTACTS block.

Needs FMOFP_BC, FMOFP_RADAR and FMOFP_DEFENSIVE (CI sets them).
"""

import os
import subprocess
import tempfile
import threading
import time
import unittest

from fmofp_bus.block import blocks_from_records
from fmofp_bus.command_word import BROADCAST_RT
from fmofp_bus.icd import blocks as b
from fmofp_bus.icd import messages as m
from fmofp_bus.icd.enums import (CmdStatus, DefensiveCommand, EcmMode, RwrBand, RwrSource, TargetingMode, TerminalState,
                                 Threat, ThreatType, TrackFilter)
from fmofp_bus.monitor import Monitor
from fmofp_bus.status import Status
from fmofp_bus.tests._support import binary_env, needs
from fmofp_display.systems_feed import SystemsFeed
from fmofp_display.terminal import DisplayTerminal
from fmofp_plant.plant import PlantModel, PlantTerminal

PORT_BASE = 53000
FRAMES = 450
SYNC_MODE_CODE = 17
DEFENSIVE_RT = m.DefStatus.RT
RADAR_RT = m.RdrTgtStatus.RT
PLANT_RT = m.PlantSensors.RT
EICAS_RT = m.DspEicasStatus.RT
TSD_RT = m.DspTsdStatus.RT

# The terminal counts its frames from its first sync, so a command at bus frame f is applied at its frame f + 1
# or f + 2; its RWR updates fall on its frames 25, 50, 75... (bus frames 24, 49, 74...).
SCRIPT = [
    (5, m.RdrTgtModeCmd(cmd_seq=1, requested_state=TerminalState.NORMAL, requested_mode=TargetingMode.TARGET_SEARCH,
                        track_filter=TrackFilter.ALL)),
    (60, m.DefCmd(cmd_seq=1, command=DefensiveCommand.INJECT_THREAT, threat_id=7, bearing=30.0, range=25.0,
                  band=RwrBand.X, threat_type=ThreatType.SAM, priority=1)),   # the salvo at the update of frame 75
    (80, m.DefCmd(cmd_seq=2, command=DefensiveCommand.SET_ECM_MODE, ecm_mode=EcmMode.ACTIVE)),
    (90, m.DefCmd(cmd_seq=3, command=DefensiveCommand.DISPENSE_CHAFF, count=4)),
    (100, m.DefCmd(cmd_seq=4, command=DefensiveCommand.DISPENSE_FLARES, count=1)),  # 25 frames after the salvo: FAILED
    (240, m.DefCmd(cmd_seq=5, command=DefensiveCommand.DISPENSE_FLARES, count=1)),  # 165 after it: one flare
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


@needs("FMOFP_BC", "FMOFP_RADAR", "FMOFP_DEFENSIVE")
class DefensiveEndToEndTest(unittest.TestCase):
    processes = []
    plant_thread = None
    plant = None
    monitor = None
    eicas = None
    tsd = None

    @classmethod
    def setUpClass(cls):
        cls.script = os.path.join(tempfile.mkdtemp(prefix="fmofp_defensive_"), "commands.txt")
        write_script(cls.script)
        try:
            model = PlantModel(seed=5, weather=False, ground=False)
            model.hold = dict(speed=450.0, heading=0.0, altitude=5000.0, vertical_speed=0.0)
            cls.plant = PlantTerminal(model, PORT_BASE)
            assert cls.plant.init() == Status.OK, "plant port in use?"
            cls.plant_thread = PlantThread(cls.plant)
            cls.plant_thread.start()
            cls.monitor = Monitor(PORT_BASE)
            assert cls.monitor.open() == Status.OK, "monitor port in use?"
            # The displays' bus halves: what eicas_terminal() and tsd_terminal() subscribe to for this terminal.
            cls.eicas = DisplayTerminal(EICAS_RT, PORT_BASE, m.DspEicasStatus, m.DspEicasModeCmd,
                                        receives=(m.EicasDefStatus,), blocks=(b.BcastDefRwrContacts,))
            assert cls.eicas.start() == Status.OK, "EICAS port in use?"
            cls.tsd = DisplayTerminal(TSD_RT, PORT_BASE, m.DspTsdStatus, m.DspTsdModeCmd,
                                      blocks=(b.BcastDefRwrContacts,))
            assert cls.tsd.start() == Status.OK, "TSD port in use?"
            for binary in ("FMOFP_RADAR", "FMOFP_DEFENSIVE"):
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
        for terminal in (cls.eicas, cls.tsd):
            if terminal is not None:
                terminal.stop()
        if cls.plant_thread is not None:
            cls.plant_thread.stop.set()
            cls.plant_thread.join(timeout=2)
        if cls.plant is not None:
            cls.plant.shutdown()
        if cls.monitor is not None:
            cls.monitor.close()

    def run_bus(self):
        bc = subprocess.Popen(
            [os.environ["FMOFP_BC"], "--rt", str(PLANT_RT), "--rt", str(RADAR_RT), "--rt", str(DEFENSIVE_RT),
             "--rt", str(EICAS_RT), "--rt", str(TSD_RT), "--port-base", str(PORT_BASE), "--frames", str(FRAMES),
             "--free-run", "--strict", "--timeout-ms", "40", "--script", self.script],
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

    def decoded_blocks(self, records, rt, cls):
        out = []
        for _, version, payload in blocks_from_records(records, rt, cls.DESCRIPTOR_SUBADDRESS, cls.SEGMENT_SUBADDRESS):
            status, block = cls.decode(payload)
            self.assertEqual(Status.OK, status, version)
            out.append(block)
        return out

    @staticmethod
    def writes_into(framed, rt, subaddress):
        return [r for _, r in framed if not r.command.transmit and not r.command.is_mode_code
                and r.command.rt == rt and r.command.subaddress == subaddress]

    def test_the_receiver_the_dispensers_and_the_displays_follow_the_bus(self):
        self.monitor.drain()
        records, output = self.run_bus()
        framed = self.by_frame(records)
        self.assertGreaterEqual(framed[-1][0], FRAMES - 2)
        self.assertIn("script: 6 commands sent of 6", output)

        # The plant's intercepts reach the terminal by relay (PLANT_ESM polled, written into DEF_ESM, 5 Hz).
        self.assertGreaterEqual(len(self.writes_into(framed, DEFENSIVE_RT, m.DefEsm.SUBADDRESS)), 40)
        # The status reaches the EICAS alone (its own relay), the contacts both displays (broadcast).
        self.assertGreaterEqual(len(self.writes_into(framed, EICAS_RT, m.EicasDefStatus.SUBADDRESS)), 40)
        self.assertEqual([], self.writes_into(framed, TSD_RT, m.EicasDefStatus.SUBADDRESS), "one consumer")
        broadcast = {r.command.subaddress for _, r in framed if not r.command.transmit and not r.command.is_mode_code
                     and r.command.rt == BROADCAST_RT}
        self.assertTrue({b.BcastDefRwrContacts.DESCRIPTOR_SUBADDRESS, b.BcastDefRwrContacts.SEGMENT_SUBADDRESS} <= broadcast,
                        broadcast)

        # Frames 110-200: the salvo of frame 75 (two flares), the jammer, four chaff; the flare request of frame 100
        # failed inside the cooldown, which runs to frame 225.
        status = self.last_in_window(framed, m.DefStatus, 110, 200)
        self.assertEqual((56, 28, EcmMode.ACTIVE, True, 1, 1, 4, 2, CmdStatus.FAILED),
                         (status.chaff_remaining, status.flares_remaining, status.ecm_mode, status.jamming_active,
                          status.high_priority_count, status.auto_salvos, status.chaff_released, status.flares_released,
                          status.defensive_cmd_status))
        self.assertTrue(status.esm_valid, "the plant's intercepts arrive")
        self.assertGreater(status.cooldown_frames, 0)
        # Frames 420-450: the flare of frame 240 (accepted), then the second salvo at the update of frame 400.
        status = self.last_in_window(framed, m.DefStatus, 420, FRAMES)
        self.assertEqual((56, 25, 2, 5, CmdStatus.ACCEPTED, TerminalState.NORMAL),
                         (status.chaff_remaining, status.flares_remaining, status.auto_salvos, status.flares_released,
                          status.defensive_cmd_status, status.state))
        self.assertGreaterEqual(status.contact_count, 1)
        term = self.last_in_window(framed, m.TermStatus, 390, FRAMES, rt=DEFENSIVE_RT)  # polled once a second
        self.assertEqual(TerminalState.NORMAL, term.state)

        # The contacts block: the injection, the plant's intercepts, and the fusion's hostile tracks if any.
        blocks = self.decoded_blocks(records, DEFENSIVE_RT, b.DefRwrContacts)
        self.assertGreaterEqual(len(blocks), 10, "an update every 25 frames, nine segments in eighteen")
        self.assertEqual(sorted(blk.update for blk in blocks), [blk.update for blk in blocks])
        last = blocks[-1]
        scen = [c for c in last.contact if c.source == RwrSource.SCENARIO]
        self.assertEqual(1, len(scen))
        self.assertEqual((7, RwrBand.X, ThreatType.SAM, 1, True), (scen[0].id, scen[0].band, scen[0].threat_type,
                                                                  scen[0].priority, scen[0].hostile))
        self.assertAlmostEqual(30.0, scen[0].bearing, delta=0.01)
        self.assertAlmostEqual(25.0, scen[0].range, delta=0.06)
        self.assertEqual(1, last.high_priority_count)
        self.assertEqual(scen[0], last.contact[0], "the priority-1 contact sorts first")
        esm = [c for c in last.contact if c.source == RwrSource.ESM]
        self.assertGreater(len(esm), 0, "eighteen sets of up to five intercepts, each alive for ten seconds")
        for contact in esm:
            self.assertEqual((ThreatType.UNK, 3, True), (contact.threat_type, contact.priority, contact.hostile))
            self.assertTrue(5.0 <= contact.range <= 60.0, contact.range)
            self.assertEqual(int(contact.bearing), contact.id, "named by the whole degrees of the bearing")
        fused = self.decoded_blocks(records, RADAR_RT, b.RdrFusedTracks)
        hostile_ids = {tr.track_id for blk in fused for tr in blk.track if tr.threat == Threat.HOSTILE}
        fusion_contacts = [c for blk in blocks for c in blk.contact if c.source == RwrSource.FUSION]
        for contact in fusion_contacts:
            self.assertIn(contact.id, hostile_ids, "a fused contact is a track the fusion called hostile")
            self.assertEqual(ThreatType.AIR if contact.band in (RwrBand.X, RwrBand.S) else ThreatType.UNK,
                             contact.threat_type, "THREAT_DB: FIGHTER X/AIR/2, BOMBER S/AIR/3, else ?/UNK/4")
        if hostile_ids:
            self.assertTrue(fusion_contacts, "the hostile tracks became contacts")
        self.assertLessEqual(len(last.contact), 64)
        self.assertEqual(0, last.dropped)

        # What the windows would draw, from the display terminals' own data.
        relayed = self.eicas.fresh(m.EicasDefStatus, stale_after_s=60.0)
        self.assertIsNotNone(relayed, "DEF_STATUS reached the EICAS by relay")
        self.assertEqual((56, 25, EcmMode.ACTIVE), (relayed.payload.chaff_remaining, relayed.payload.flares_remaining,
                                                    relayed.payload.ecm_mode))
        self.assertIsNone(self.tsd.fresh(m.EicasDefStatus, stale_after_s=60.0), "not written into the TSD")
        self.assertIsNotNone(self.eicas.latest_block(b.BcastDefRwrContacts)[0], "the contacts block at the EICAS")
        self.assertIsNotNone(self.tsd.latest_block(b.BcastDefRwrContacts)[0], "the contacts block at the TSD")
        eicas = SystemsFeed(self.eicas, stale_after_s=60.0)
        data = eicas.defensive.get_data()
        self.assertEqual((56, 25, "ACTIVE", True), (data["chaff_remaining"], data["flares_remaining"], data["ecm_mode"],
                                                    data["jamming_active"]))
        self.assertGreaterEqual(data["threat_count"], 1)
        self.assertIn("DEF chaff 56 flares 25 ECM ACTIVE", eicas.status_text())
        tsd = SystemsFeed(self.tsd, stale_after_s=60.0)
        contacts = tsd.defensive.get_rwr_contacts()
        self.assertEqual({}, tsd.defensive.get_data(), "the TSD reads the contacts only")
        self.assertGreaterEqual(len(contacts), 1)
        sam = [c for c in contacts if c["contact_id"] == "SCEN-7"]
        self.assertEqual([{"contact_id": "SCEN-7", "bearing_deg": 30.0, "range_nm": 25.0, "band": "X", "threat_type": "SAM",
                           "priority": 1, "hostile": True}], sam)
        for contact in contacts:
            self.assertIn(contact["band"], ("?", "L", "S", "C", "X", "Ku", "K", "Ka"))
            self.assertTrue(contact["contact_id"].startswith(("FUS-", "ESM-", "SCEN-")), contact)
        self.assertIn("overruns=0", output)


if __name__ == "__main__":
    unittest.main()
