"""The sensor management terminal against the frozen sensorService.py and sensorDataFusion.py, through
fmofp_sensor_tool.

SensorService and SensorDataFusion run in this process beside the C++ on the same detections: the fusion's
sensor managers are stand-ins returning the staged scans, and the service reads the sensors' on/off states from
the same stand-ins, switched as the tool's are. The fusion's clock is a clock the test moves (its contacts' ages
read time.time(); the C++ counts frames, fifty a second), and its SensorContact is replaced by a subclass whose
first_seen and last_seen default to that clock, since the dataclass captured the real time.time at import. The
radar data fusion the service counted tracks from is a stand-in with no tracks: on the bus the EICAS counts them.

Needs FMOFP_SENSOR_TOOL (CI sets it).
"""

import copy
import os
import subprocess
import sys
import unittest
from dataclasses import dataclass, field
from unittest import mock

from fmofp_bus.tests._support import binary_env, needs

B20SS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if B20SS not in sys.path:
    sys.path.insert(0, B20SS)

CLOCK_BASE = 1000.0
SENSOR_NUMBER = {"main_radar": 0, "terrain_following_radar": 1, "lidar": 2, "forward_looking_infrared": 3,
                 "missile_approach_warning": 4, "electronic_support_measures": 5}  # sensor_id
ID_PREFIX = {"RADAR": "RAD", "LIDAR": "LID", "IR": "IR", "ESM": "ESM"}  # SensorSource.value[:3], and "ESM"/"IR"
BAND_LETTERS = {"UNKNOWN": "?", "L": "L", "S": "S", "C": "C", "X": "X", "KU": "Ku", "K": "K", "KA": "Ka"}


class SensorTool:
    """One fmofp_sensor_tool run; answers read back in the order asked."""

    def __init__(self):
        self.lines = []
        self.out = []
        self.pos = 0

    def send(self, *commands):
        self.lines += commands

    def run(self):
        result = subprocess.run([os.environ["FMOFP_SENSOR_TOOL"]], input="\n".join(self.lines) + "\n",
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


class FakeSensor:
    """What SensorDataFusion and SensorService ask of a sensor: is_active, accuracy, scan()/detect(), get_status()."""

    def __init__(self, accuracy=None):
        self.is_active = True
        self.accuracy = accuracy
        self.staged = []

    def scan(self):
        return [dict(d) for d in self.staged] if self.is_active else None

    detect = scan

    def get_status(self):
        return {"is_active": self.is_active, "accuracy": self.accuracy}


class FakeManager:
    def __init__(self, sensors):
        self.sensors = sensors


class FakeRadarFusion:
    def get_fused_tracks(self):
        return []


def make_pair(fusion_module, service_module):
    """The frozen fusion and service on the fake managers, sharing the sensors' states."""
    active = FakeManager({"main_radar": FakeSensor(0.95), "terrain_following_radar": FakeSensor(0.99),
                          "lidar": FakeSensor(0.99)})
    passive = FakeManager({"forward_looking_infrared": FakeSensor(), "missile_approach_warning": FakeSensor(),
                           "electronic_support_measures": FakeSensor()})
    fusion = fusion_module.SensorDataFusion()
    fusion._active = active
    fusion._passive = passive
    service = service_module.SensorService()
    service._active._mgr = active
    service._passive._mgr = passive
    service._fusion = FakeRadarFusion()
    service._sdf = fusion
    return fusion, service, {**active.sensors, **passive.sensors}


class Oracle:
    """Runs each step on the service and queues it for the tool, recording what to compare afterwards. The
    Python's clock is CLOCK_BASE plus the frame in seconds (fifty frames a second)."""

    def __init__(self, fusion, service, sensors, clock):
        self.fusion = fusion
        self.service = service
        self.sensors = sensors
        self.clock = clock
        self.tool = SensorTool()
        self.script = []  # (command, kind, expected)

    def _send(self, command, kind="ok", expected=None):
        self.tool.send(command)
        self.script.append((command, kind, expected))

    def snapshot(self):
        # to_dict() hands out the contact's own corroborated_by list, which later merges go on appending to:
        # the snapshot is a deep copy, or an earlier snapshot would show a later state.
        self._send("data", "data", (copy.deepcopy(self.service.get_data()), self.fusion._seq))
        self._send("contacts", "contacts", copy.deepcopy(self.fusion.get_contacts()))

    def set_active(self, name, on):
        self.sensors[name].is_active = on
        self._send(f"sensor {SENSOR_NUMBER[name]} {1 if on else 0}", "number", 1)

    def update(self, frame, epoch, main=(), tfr=(), lidar=(), flir=(), maws=(), esm=()):
        """The service's 5 Hz body at this frame on these detections (dicts as the managers returned them)."""
        self.clock[0] = CLOCK_BASE + frame / 50.0
        self.sensors["main_radar"].staged = list(main)
        self.sensors["terrain_following_radar"].staged = list(tfr)
        self.sensors["lidar"].staged = list(lidar)
        self.sensors["forward_looking_infrared"].staged = list(flir)
        self.sensors["missile_approach_warning"].staged = list(maws)
        self.sensors["electronic_support_measures"].staged = list(esm)
        self.service._update()
        self._send(f"scan_begin {epoch}")
        for d in main:
            self._send(f"radar 0 {d['distance']!r} {d['angle']!r} {d['speed']!r}")
        for d in tfr:
            self._send(f"radar 1 {d['distance']!r} {d['angle']!r} {d['speed']!r}")
        for p in lidar:
            self._send(f"lidar {p['distance']!r} {p['azimuth']!r} {p['elevation']!r}")
        for o in flir:
            self._send(f"ir 3 {o['temperature']!r} {o['angle']!r} {o['distance']!r}")
        for o in maws:
            self._send(f"ir 4 {o['temperature']!r} {o['angle']!r} {o['distance']!r}")
        self._send(f"esm_begin {epoch}")
        for s in esm:
            self._send(f"signal {s['frequency'] / 1e6!r} {s['signal_strength']!r} {s['bearing']!r} 20.0")
        self._send(f"update {frame}")
        self.snapshot()


def radar(distance, angle, speed):
    return {"distance": distance, "angle": angle, "speed": speed}


def lidar(distance, azimuth, elevation):
    return {"distance": distance, "azimuth": azimuth, "elevation": elevation}


def infrared(temperature, angle, distance):
    return {"temperature": temperature, "angle": angle, "distance": distance}


def esm(frequency_hz, strength_dbm, bearing):
    return {"frequency": frequency_hz, "signal_strength": strength_dbm, "bearing": bearing}


@needs("FMOFP_SENSOR_TOOL")
class SensorOracleTest(unittest.TestCase):
    def test_the_contact_table_and_the_health_match_the_service_and_the_fusion(self):
        import FMOFP.Systems.sensorManagement.sensorDataFusion as fusion_module
        import FMOFP.Systems.sensorManagement.sensorService as service_module
        clock = [CLOCK_BASE]
        fake_time = mock.Mock()
        fake_time.time = lambda: clock[0]

        @dataclass
        class ClockedContact(fusion_module.SensorContact):
            first_seen: float = field(default_factory=lambda: clock[0])
            last_seen: float = field(default_factory=lambda: clock[0])

        with mock.patch.object(fusion_module, "time", fake_time), \
                mock.patch.object(fusion_module, "SensorContact", ClockedContact):
            fusion, service, sensors = make_pair(fusion_module, service_module)
            oracle = Oracle(fusion, service, sensors, clock)
            self.assertEqual("INITIALISING", service.get_data()["health"])
            oracle.snapshot()
            oracle.update(10, 1, main=[radar(120000.0, 10.0, 250.0), radar(80000.0, 13.0, 100.0)],
                          tfr=[radar(20000.0, 200.0, 50.0)], lidar=[lidar(500.0, 330.0, 5.0), lidar(600.0, 331.0, 1.0)],
                          flir=[infrared(300.0, -30.0, 4000.0)], maws=[infrared(400.0, 120.0, 8000.0)],
                          esm=[esm(9.5e9, -60.0, 203.5)])
            self.assertEqual(6, fusion.get_contact_count(), "two radar detections merge, the ESM signal merges")
            self.assertEqual(8, fusion._seq, "every detection took a number")
            self.assertEqual("NOMINAL", service.get_data()["health"])
            oracle.update(20, 2, tfr=[radar(21000.0, 201.0, 55.0)], esm=[esm(3.0e9, -70.0, 12.0)])
            fused = [c for c in fusion.get_contacts() if c["source"] == "FUSED"]
            self.assertEqual(["RAD-0001", "RAD-0003"], [c["contact_id"] for c in fused], "a second name makes FUSED")
            # The service reports a switched sensor at its next poll (get_data() is the last _update's snapshot).
            oracle.set_active("lidar", False)
            oracle.set_active("electronic_support_measures", False)
            oracle.update(30, 3, main=[radar(1000.0, 100.0, 1.0)], lidar=[lidar(5.0, 5.0, 5.0)],
                          esm=[esm(1.0e9, -50.0, 100.0)])
            self.assertEqual("FAULT", service.get_data()["health"], "neither suite is whole")
            self.assertEqual(7, fusion.get_contact_count(), "the LIDAR point and the signal of sensors off were skipped")
            oracle.set_active("lidar", True)
            oracle.update(35, 4)
            self.assertEqual("DEGRADED", service.get_data()["health"])
            oracle.set_active("electronic_support_measures", True)
            oracle.update(40, 5)
            self.assertEqual("NOMINAL", service.get_data()["health"])
            for frame in (400, 410, 420, 430, 440):
                oracle.update(frame, 6 + frame // 10)
            self.assertEqual([], fusion.get_contacts(), "everything aged out: 8 s after it was last seen")

            oracle.tool.run()
            for command, kind, expected in oracle.script:
                if kind == "ok":
                    self.assertEqual(["ok"], oracle.tool.line(), command)
                elif kind == "number":
                    self.assertEqual(float(expected), float(oracle.tool.line()[0]), command)
                elif kind == "data":
                    self.compare_data(expected, oracle.tool.line())
                else:
                    self.compare_contacts(expected, oracle.tool.block(), clock)

    def compare_data(self, expected, row):
        py_data, py_seq = expected
        health, main, tfr, lidar_on, flir, maws, esm_on, count, dropped, seq = row
        self.assertEqual(py_data["health"], health)
        if py_data["active_sensors"]:
            flags = {name: py_data["active_sensors"].get(name, py_data["passive_sensors"].get(name))["is_active"]
                     for name in SENSOR_NUMBER}
            self.assertEqual([flags[n] for n in SENSOR_NUMBER],
                             [bool(int(x)) for x in (main, tfr, lidar_on, flir, maws, esm_on)])
        else:
            self.assertEqual("INITIALISING", health, "before the first update the service had no statuses yet")
        self.assertEqual((py_data["sensor_contact_count"], len(py_data["sensor_contacts"])), (int(count), int(count)))
        self.assertEqual(0, int(dropped))
        self.assertEqual(py_seq, int(seq))

    def compare_contacts(self, py_contacts, rows, clock):
        self.assertEqual(len(py_contacts), len(rows), (py_contacts, rows))
        for contact, row in zip(py_contacts, rows):
            cid, origin, source, cls, range_m, bearing, elevation, speed, frequency, signal, band, confidence, \
                last_seen, corroborated = row
            self.assertEqual(contact["contact_id"], f"{ID_PREFIX[origin]}-{int(cid):04d}")
            self.assertEqual((contact["source"], contact["class"]), (source, cls), contact)
            for key, text, places in (("range_m", range_m, 1), ("bearing_deg", bearing, 1), ("elevation_deg", elevation, 1),
                                      ("speed_ms", speed, 1)):
                if text == "-":
                    self.assertIsNone(contact[key], (key, contact))
                else:
                    self.assertEqual(contact[key], round(float(text), places), (key, contact))
            if frequency == "-":
                self.assertIsNone(contact["frequency_hz"])
                self.assertIsNone(contact["band"])
            else:
                self.assertEqual((contact["frequency_hz"], contact["signal_dbm"], contact["band"]),
                                 (float(frequency), float(signal), BAND_LETTERS[band]), contact)
            self.assertEqual(contact["confidence"], round(float(confidence), 2), contact)
            self.assertEqual(contact["last_seen"], CLOCK_BASE + int(last_seen) / 50.0, contact)
            self.assertEqual(set(contact["corroborated_by"]), set() if corroborated == "-" else set(corroborated.split(",")),
                             (contact, row))


if __name__ == "__main__":
    unittest.main()
