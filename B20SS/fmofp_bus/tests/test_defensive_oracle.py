"""The defensive systems terminal against the frozen defensiveService.py, through fmofp_defensive_tool.

DefensiveService runs in this process beside the C++ on the same inputs: fused threat tracks (objects answering
what _update_rwr asks of a track: track_id, classification, bearing_deg(), range_nm(), is_hostile()), the same
ESM detection sets, and a clock the test moves (the service reads time.time() for its contacts' ages and its
cooldown; the C++ counts frames, fifty a second). The service's own random range for a new ESM contact is
replaced by the plant's range for that signal, which is what PLANT_ESM carries. Neither its database nor its
sensors are constructed: the imports that make them are blocked, which the service tolerates.

A second test records the frozen Python's behaviour with a real FusedTrack: its bearing_deg and range_nm are
properties, the service calls them, the TypeError is swallowed and no fused contact was ever made (the port
departs there; ICD README section 2).

Needs FMOFP_DEFENSIVE_TOOL for the oracle (CI sets it).
"""

import math
import os
import subprocess
import sys
import unittest
from unittest import mock

from fmofp_bus.tests._support import binary_env, needs

B20SS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if B20SS not in sys.path:
    sys.path.insert(0, B20SS)

CLASS_NUMBER = {"UNKNOWN": 0, "FIGHTER": 1, "BOMBER": 2, "HIGH_ALT": 3, "MISSILE": 4, "HELICOPTER": 5, "DRONE": 6,
                "STEALTH": 7}  # target_class
BAND_NUMBER = {"?": 0, "L": 1, "S": 2, "C": 3, "X": 4, "Ku": 5, "K": 6, "Ka": 7}  # rwr_band, by the Python's letters
BAND_LETTERS = {"UNKNOWN": "?", "L": "L", "S": "S", "C": "C", "X": "X", "KU": "Ku", "K": "K", "KA": "Ka"}  # by its names
TYPE_NUMBER = {"UNK": 0, "SAM": 1, "AIR": 2}  # threat_type
ECM_NUMBER = {"STANDBY": 0, "ACTIVE": 1, "PASSIVE": 2}  # ecm_mode
SOURCE_PREFIX = {"FUSION": "FUS", "ESM": "ESM", "SCENARIO": "SCEN"}
BLOCKED_IMPORTS = {"FMOFP.storage.DBM": None,
                   "FMOFP.Systems.sensorManagement.passiveSensors.passiveSensors": None,
                   "FMOFP.Systems.radarManagement.radar_data_fusion": None}


class DefensiveTool:
    """One fmofp_defensive_tool run; answers read back in the order asked."""

    def __init__(self):
        self.lines = []
        self.out = []
        self.pos = 0

    def send(self, *commands):
        self.lines += commands

    def run(self):
        result = subprocess.run([os.environ["FMOFP_DEFENSIVE_TOOL"]], input="\n".join(self.lines) + "\n",
                                capture_output=True, text=True, timeout=120, env=binary_env())
        assert result.returncode == 0, result.stderr
        self.out = result.stdout.splitlines()
        self.pos = 0
        return self

    def line(self):
        self.pos += 1
        return self.out[self.pos - 1].split()

    def block(self):
        rows = []
        while True:
            row = self.line()
            if row == ["end"]:
                return rows
            rows.append(row)


class FakeTrack:
    """What _update_rwr asks of a fused threat track, answering as FusedTrack's properties compute."""

    def __init__(self, track_id, classification, hostile, x, y, z):
        self.track_id = track_id
        self.classification = classification
        self.hostile = hostile
        self.x, self.y, self.z = x, y, z

    def bearing_deg(self):
        return math.degrees(math.atan2(self.x, self.y)) % 360

    def range_nm(self):
        return math.sqrt(self.x * self.x + self.y * self.y + self.z * self.z) / 1852.0

    def is_hostile(self):
        return self.hostile

    def tool_command(self):
        return (f"track {self.track_id} {CLASS_NUMBER[self.classification]} {1 if self.hostile else 0} "
                f"{self.x!r} {self.y!r} {self.z!r}")


class FakeFusion:
    def __init__(self):
        self.tracks = []

    def get_threat_tracks(self):
        return [t for t in self.tracks if t.is_hostile()]


class FakeEsm:
    def __init__(self):
        self.signals = []

    def get_sensor_data(self, sensor_name):
        return [dict(s) for s in self.signals]


def signal(frequency_hz, strength_dbm, bearing_deg, range_nm):
    """One ESM intercept as the sensor reported it, plus the range the plant draws for it."""
    return {"frequency": frequency_hz, "signal_strength": strength_dbm, "bearing": bearing_deg, "range_nm": range_nm}


def make_service(module):
    """A DefensiveService with no database and no sensors (their imports blocked), its inputs the fakes."""
    with mock.patch.dict(sys.modules, BLOCKED_IMPORTS):
        service = module.DefensiveService()
    assert service._db is None and service._esm is None and service._fusion is None
    service._esm = FakeEsm()
    service._fusion = FakeFusion()
    return service


def queue_ranges(module, service, signals, ranges):
    """The ranges the service's random.uniform(5, 60) must return: the plant's, for the signals it has not seen."""
    seen = set(service._contacts)
    for s in signals:
        cid = f"ESM-{module._classify_freq(s['frequency'])}-{int(s['bearing'])}"
        if cid not in seen:
            ranges.append(s["range_nm"])
            seen.add(cid)


CLOCK_BASE = 1000.0  # the service's _last_dispense starts at 0.0, the epoch: the clock must not start near it


class Oracle:
    """Runs each step on the service and queues it for the tool, recording what to compare afterwards. The
    Python's clock is CLOCK_BASE plus the frame in seconds (fifty frames a second)."""

    def __init__(self, module, service, clock, ranges):
        self.module = module
        self.service = service
        self.clock = clock
        self.ranges = ranges
        self.tool = DefensiveTool()
        self.script = []  # (command, kind, expected)

    def _send(self, command, kind="ok", expected=None):
        self.tool.send(command)
        self.script.append((command, kind, expected))

    def snapshot(self):
        self._send("contacts", "contacts", self.service.get_rwr_contacts())
        self._send("data", "data", self.service.get_data())

    def update(self, frame, tracks, signals, epoch):
        """The loop body at this frame: the fusion's threat tracks and the ESM's set, as the Python read them."""
        self.clock[0] = CLOCK_BASE + frame / 50.0
        self.service._fusion.tracks = list(tracks)
        self.service._esm.signals = list(signals)
        queue_ranges(self.module, self.service, signals, self.ranges)
        self.service._update_rwr()
        self.service._auto_dispense()
        assert not self.ranges, "every queued range was drawn"
        self._send("fused_begin")
        for t in tracks:
            self._send(t.tool_command())
        self._send(f"esm_begin {epoch}")
        for s in signals:
            self._send(f"signal {s['frequency'] / 1e6!r} {s['signal_strength']!r} {s['bearing']!r} {s['range_nm']!r}")
        self._send(f"update {frame}")
        self.snapshot()

    def inject(self, frame, threat_id, bearing, range_nm, band, threat_type, priority):
        """scenarioEngine._inject_threat: a contact written into the table under the lock."""
        self.clock[0] = CLOCK_BASE + frame / 50.0
        cid = f"SCEN-{threat_id}"
        with self.service._lock:
            self.service._contacts[cid] = self.module.RWRContact(cid, bearing, range_nm, band, threat_type, priority,
                                                                 True, last_seen=self.clock[0])
        self._send(f"inject {frame} {threat_id} {bearing!r} {range_nm!r} {BAND_NUMBER[band]} {TYPE_NUMBER[threat_type]} "
                   f"{priority}", "number", 1)
        self.snapshot()

    def chaff(self, count):
        self._send(f"chaff {count}", "number", self.service.dispense_chaff(count))

    def flares(self, frame, count):
        self.clock[0] = CLOCK_BASE + frame / 50.0
        self._send(f"flares {frame} {count}", "number", self.service.dispense_flares(count))

    def ecm(self, mode):
        self.service.set_ecm_mode(mode)
        self._send(f"ecm {ECM_NUMBER.get(mode, 3)}", "number", 1 if mode in ECM_NUMBER else 0)


@needs("FMOFP_DEFENSIVE_TOOL")
class DefensiveOracleTest(unittest.TestCase):
    def test_the_contact_table_the_dispensers_and_the_ecm_match_defensive_service(self):
        import FMOFP.Systems.defensiveSys.defensiveService as module
        clock = [CLOCK_BASE]
        fake_time = mock.Mock()
        fake_time.time = lambda: clock[0]
        ranges = []
        # The service also draws uniform(0, 360) once per signal: the default of sig.get('bearing', ...), evaluated
        # whether or not the signal has a bearing (it always has); only the uniform(5, 60) range draws matter.
        with mock.patch.object(module, "time", fake_time), \
                mock.patch.object(module.random, "uniform",
                                  lambda low, high: ranges.pop(0) if (low, high) == (5, 60) else 0.0):
            service = make_service(module)
            oracle = Oracle(module, service, clock, ranges)
            tracks = [FakeTrack(7, "FIGHTER", True, 18520.0, 18520.0, 0.0),
                      FakeTrack(3, "BOMBER", True, 0.0, -9260.0, 300.0),
                      FakeTrack(9, "HIGH_ALT", True, -5000.0, 2000.0, 1000.0),
                      FakeTrack(4, "FIGHTER", False, 500.0, 500.0, 0.0)]
            moved = [FakeTrack(7, "FIGHTER", True, 20000.0, 17000.0, 100.0),
                     FakeTrack(3, "BOMBER", True, -18520.0, 0.0, 0.0),
                     FakeTrack(9, "HIGH_ALT", True, -5000.0, 2000.0, 1000.0)]
            set_one = [signal(9.5e9, -60.0, 123.7, 42.0), signal(9.6e9, -70.0, 123.2, 17.0),
                       signal(2.0e9, -50.0, 10.5, 30.0), signal(39.9999e9, -50.0, 350.2, 55.0),
                       signal(0.4e9, -50.0, 1.0, 20.0)]
            set_two = [signal(9.0e9, -60.0, 123.1, 5.0), signal(12.0e9, -60.0, 200.0, 33.0)]

            oracle.update(25, tracks, set_one, 1)
            self.assertEqual(7, len(service.get_rwr_contacts()), "three hostile tracks, four distinct intercepts")
            oracle.inject(30, 1, 30.0, 25.0, "X", "SAM", 1)
            oracle.update(50, moved, set_two, 2)
            self.assertEqual(28, service.get_data()["flares_remaining"], "the salvo on the priority-1 contact")
            oracle.flares(60, 2)
            oracle.chaff(5)
            oracle.snapshot()
            oracle.update(75, [], [], 3)
            oracle.update(200, [], [], 4)
            self.assertEqual(28, service.get_data()["flares_remaining"], "exactly the cooldown is not over it")
            oracle.update(225, [], [], 5)
            self.assertEqual(26, service.get_data()["flares_remaining"])
            oracle.ecm("ACTIVE")
            oracle.ecm("FOO")
            oracle.flares(400, 30)
            oracle.snapshot()
            oracle.flares(410, 1)
            oracle.update(525, [], [], 6)
            self.assertEqual(9, len(service.get_rwr_contacts()), "nothing has aged out yet: 10.0 s is not over the TTL")
            oracle.update(550, [], [], 7)
            self.assertEqual(5, len(service.get_rwr_contacts()),
                             "the first set's unrefreshed intercepts and the injection are gone; the tracks and the "
                             "intercepts seen at the second update have 10.0 s on them, not over the TTL")
            oracle.update(575, [], [], 8)
            self.assertEqual([], service.get_rwr_contacts())
            oracle.flares(600, 1)
            oracle.ecm("PASSIVE")
            oracle.snapshot()

            oracle.tool.run()
            for command, kind, expected in oracle.script:
                if kind == "ok":
                    self.assertEqual(["ok"], oracle.tool.line(), command)
                elif kind == "number":
                    self.assertEqual(float(expected), float(oracle.tool.line()[0]), command)
                elif kind == "contacts":
                    self.compare_contacts(expected, oracle.tool.block())
                else:
                    self.compare_data(expected, oracle.tool.line())

    def compare_contacts(self, py_contacts, rows):
        self.assertEqual(len(py_contacts), len(rows), (py_contacts, rows))
        for contact, row in zip(py_contacts, rows):
            source, cid, bearing, range_nm, band, threat_type, priority, hostile = row
            letters = BAND_LETTERS[band]
            expected_id = f"ESM-{letters}-{cid}" if source == "ESM" else f"{SOURCE_PREFIX[source]}-{cid}"
            self.assertEqual(contact["contact_id"], expected_id)
            self.assertEqual(contact["bearing_deg"], round(float(bearing), 1), contact)
            self.assertEqual(contact["range_nm"], round(float(range_nm), 1), contact)
            self.assertEqual((contact["band"], contact["threat_type"]), (letters, threat_type), contact)
            self.assertEqual((contact["priority"], contact["hostile"]), (int(priority), bool(int(hostile))), contact)

    def compare_data(self, py_data, row):
        chaff, flares, ecm, jamming, count = row[:5]
        self.assertEqual((py_data["chaff_remaining"], py_data["flares_remaining"], py_data["ecm_mode"],
                          py_data["jamming_active"], py_data["threat_count"]),
                         (int(chaff), int(flares), ecm, bool(int(jamming)), int(count)))
        self.assertEqual(len(py_data["rwr_contacts"]), int(count))


class DefensiveServiceQuirkTest(unittest.TestCase):
    """The frozen Python's fusion branch, as evidence for the departure recorded in the ICD README (section 2)."""

    def test_a_real_fused_track_raises_inside_update_rwr_and_no_contact_is_made(self):
        import FMOFP.Systems.defensiveSys.defensiveService as module
        from FMOFP.Systems.radarManagement.radar_data_fusion import FusedTrack
        service = make_service(module)
        track = FusedTrack(track_id="t1", position_m=(18520.0, 18520.0, 0.0), velocity_ms=(0.0, 0.0, 0.0),
                           confidence=0.8, classification="FIGHTER", identity="UNKNOWN", threat="HOSTILE",
                           sources=["targeting_radar"], last_seen=0.0)
        self.assertIsInstance(track.bearing_deg, float, "a property, where the service calls a method")
        service._fusion.tracks = [track]
        service._update_rwr()
        self.assertEqual([], service.get_rwr_contacts(),
                         "the TypeError is swallowed: the Python's RWR never showed a fused track")
        # The call the service makes, on an object answering it, is what the port computes.
        service._fusion.tracks = [FakeTrack("t1", "FIGHTER", True, 18520.0, 18520.0, 0.0)]
        service._update_rwr()
        self.assertEqual([{"contact_id": "FUS-t1", "bearing_deg": 45.0, "range_nm": 14.1, "band": "X",
                           "threat_type": "AIR", "priority": 2, "hostile": True}], service.get_rwr_contacts())


if __name__ == "__main__":
    unittest.main()
