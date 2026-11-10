"""The flight surfaces terminal against the frozen flightSurfaceService.py, through fmofp_surfaces_tool.

FlightSurfaceService runs in this process beside the C++ on the same inputs: its flight control computer is a
stand-in whose get_data() answers the staged roll, pitch and angle of attack (the sensed flight state, which the
plant publishes on the bus), its database a stand-in. Each pass both do _sync_from_fcc() and _step_all(dt); the ten
positions, the flap detent and the trim are compared to the last bit, since both sides do the same arithmetic in
the same order; the manual controls nothing in the Python called (set_flaps with its detents, set_speedbrake,
set_rudder, set_trim) are exercised on both, with their clamps.

A second test records the frozen Python's behaviour the port keeps or departs from (ICD README section 2): the
service follows the sensed attitude and never the flight control computer's commanded deflections, the trim moves
nothing, a surface can never become unhealthy, and every pass wrote a snapshot to SQLite.

Needs FMOFP_SURFACES_TOOL for the oracle (CI sets it).
"""

import inspect
import os
import subprocess
import sys
import unittest
from unittest import mock

from fmofp_bus.tests._support import binary_env, needs

B20SS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if B20SS not in sys.path:
    sys.path.insert(0, B20SS)

FCC_MODULE = "FMOFP.Systems.flightControlSys.flightControlComputer.flightControlComputer"
NAMES = ("aileron_l", "aileron_r", "elevator_l", "elevator_r", "rudder", "flap_l", "flap_r", "slat_l", "slat_r",
         "speedbrake")  # FlightSurfaceService._all's order, and FSF_POSITIONS's
PLACES = 12


class SurfacesTool:
    """One fmofp_surfaces_tool run; answers read back in the order asked."""

    def __init__(self):
        self.lines = []
        self.out = []
        self.pos = 0

    def send(self, *commands):
        self.lines += commands

    def run(self):
        result = subprocess.run([os.environ["FMOFP_SURFACES_TOOL"]], input="\n".join(self.lines) + "\n",
                                capture_output=True, text=True, timeout=120, env=binary_env())
        assert result.returncode == 0, result.stderr
        self.out = result.stdout.splitlines()
        self.pos = 0
        return self

    def line(self):
        self.pos += 1
        return self.out[self.pos - 1].split()


class FakeFcc:
    """The flight control computer as _sync_from_fcc sees it: get_data() is the sensed flight state."""

    def __init__(self):
        self.data = {}

    def get_data(self):
        return dict(self.data)


def make_service():
    """The frozen FlightSurfaceService with a stand-in for the SQLite database it snapshotted every pass into."""
    import FMOFP.Systems.flightSurfaces.flightSurfaceService as fss_module
    with mock.patch("FMOFP.storage.DBM.DatabaseManager"):
        service = fss_module.FlightSurfaceService()
    return fss_module, service


def snapshot_of(service):
    return {"positions": [s.position for s in service._all], "flap_cmd": service._flap_cmd,
            "trim": dict(service._trim), "healthy": all(s.healthy for s in service._all),
            "data": service.get_data()}


class Oracle:
    """Runs each pass on the Python and queues it for the tool, recording what to compare afterwards."""

    def __init__(self, service, fcc):
        self.service = service
        self.fcc = fcc
        self.tool = SurfacesTool()
        self.script = []  # (command, kind, expected)

    def send(self, command, kind="ok", expected=None):
        self.tool.send(command)
        self.script.append((command, kind, expected))

    def snapshot(self):
        self.send("data", "data", snapshot_of(self.service))

    def pass_(self, roll, pitch, aoa, dt=0.02):
        """One pass of _update_loop's body (without _persist) on this flight state, on both."""
        self.fcc.data = {"roll": roll, "pitch": pitch, "angle_of_attack": aoa, "altitude": 10000.0, "speed": 500.0}
        self.service._sync_from_fcc()
        self.service._step_all(dt)
        self.send(f"sensors {roll!r} {pitch!r} {aoa!r}")
        self.send(f"step {dt!r}")
        self.snapshot()

    def blind_pass(self, dt=0.02):
        """A pass with nothing from the flight control computer (`if not data: return`): no sync, a step."""
        self.fcc.data = {}
        self.service._sync_from_fcc()
        self.service._step_all(dt)
        self.send(f"step {dt!r}")
        self.snapshot()

    def control(self, command):
        """A manual control already applied to the Python; the tool's answer and a snapshot are compared."""
        self.send(command)
        self.snapshot()


@needs("FMOFP_SURFACES_TOOL")
class SurfacesOracleTest(unittest.TestCase):
    def test_the_surfaces_follow_the_python_pass_for_pass(self):
        fss_module, service = make_service()
        fcc = FakeFcc()
        with mock.patch(FCC_MODULE + ".get_flight_control_computer", return_value=fcc):
            oracle = Oracle(service, fcc)
            oracle.snapshot()
            # A roll building to 30 degrees with a slight nose-down pitch: the ailerons chase a growing command at
            # 1.2 degrees a pass (the left one down, opposing the right roll) and the elevators settle at +2.4
            # within three passes.
            for i in range(1, 16):
                oracle.pass_(2.0 * i, -3.0, 2.0)
            self.assertAlmostEqual(15.0, service.aileron_l.cmd, msg="-(-30 x 0.5)")
            self.assertAlmostEqual(-15.0, service.aileron_r.cmd)
            self.assertAlmostEqual(2.4, service.elevator_l.position)
            self.assertGreater(service.aileron_l.position, 0.0)
            # Flaps to the 15 detent: 5 degrees a second, a tenth of a degree a pass.
            service.set_flaps(15)
            oracle.control("flaps 15")
            for _ in range(10):
                oracle.pass_(30.0, -3.0, 2.0)
            self.assertAlmostEqual(1.0, service.flap_l.position)
            self.assertEqual(15, service._flap_cmd)
            # The other controls, with their clamps: speedbrake 50 % = 30 degrees, rudder -12.5, the trims (pitch
            # clamped to 10), a nonsense axis ignored.
            service.set_speedbrake(50.0)
            oracle.control("speedbrake 50.0")
            service.set_rudder(-12.5)
            oracle.control("rudder -12.5")
            service.set_trim("yaw", 4.0)
            oracle.control("trim yaw 4.0")
            service.set_trim("pitch", 12.0)
            oracle.control("trim pitch 12.0")
            service.set_trim("roll", -0.75)
            oracle.control("trim roll -0.75")
            self.assertEqual({"pitch": 10, "roll": -0.75, "yaw": 4.0}, service._trim)
            # A high angle of attack puts the slats out (20 degrees at 5 a second); the loop's measured dt varies.
            for i in range(30):
                oracle.pass_(30.0 - i, -3.0 + 0.2 * i, 9.5, dt=(0.02, 0.0213, 0.0187, 0.02)[i % 4])
            self.assertEqual(20.0, service.slat_l.cmd)
            self.assertGreater(service.slat_r.position, 2.0)
            self.assertTrue(15.0 < service.speedbrake.position < 30.0, service.speedbrake.position)  # 0.6 a pass toward 30
            self.assertEqual(-12.5, service.rudder.position)  # 0.8 a pass: there in 16
            # The flight control computer answers nothing for three passes: the commands stand, the surfaces move.
            for _ in range(3):
                oracle.blind_pass()
            # Extreme attitudes saturate the aileron and elevator commands.
            oracle.pass_(120.0, -60.0, 9.5)
            self.assertEqual((25, -25, 30), (service.aileron_l.cmd, service.aileron_r.cmd, service.elevator_l.cmd))
            oracle.pass_(-120.0, 60.0, 9.5)
            self.assertEqual((-25, 25, -30), (service.aileron_l.cmd, service.aileron_r.cmd, service.elevator_r.cmd))
            # The detents: a tie goes to the lower detent, as min() over the tuple had it.
            for asked, detent in ((10, 5), (22, 15), (23, 30), (-4, 0), (100, 30), (5, 5)):
                service.set_flaps(asked)
                oracle.control(f"flaps {asked}")
                self.assertEqual(detent, service._flap_cmd, asked)
            service.set_speedbrake(150.0)
            oracle.control("speedbrake 150.0")
            self.assertEqual(60, service.speedbrake.cmd)
            service.set_speedbrake(-10.0)
            oracle.control("speedbrake -10.0")
            self.assertEqual(0, service.speedbrake.cmd)
            service.set_rudder(45.0)
            oracle.control("rudder 45.0")
            self.assertEqual(30, service.rudder.cmd)
            # Back to a calm attitude at exactly 8 degrees of angle of attack: the slats come in (not above 8).
            for _ in range(20):
                oracle.pass_(0.0, 0.0, 8.0)
            self.assertEqual(0.0, service.slat_l.cmd)

            oracle.tool.run()
            for command, kind, expected in oracle.script:
                if kind == "ok":
                    self.assertEqual(["ok"], oracle.tool.line(), command)
                else:
                    self.compare(expected, oracle.tool.line())

    def compare(self, expected, row):
        self.assertEqual(15, len(row), row)
        positions = [float(x) for x in row[:10]]
        for name, want, got in zip(NAMES, expected["positions"], positions):
            self.assertAlmostEqual(want, got, places=PLACES, msg=name)
        self.assertEqual(expected["flap_cmd"], float(row[10]))
        self.assertEqual((expected["trim"]["pitch"], expected["trim"]["roll"], expected["trim"]["yaw"]),
                         (float(row[11]), float(row[12]), float(row[13])))
        self.assertEqual(expected["healthy"], bool(int(row[14])))
        # get_data(): the positions rounded to two decimals (the lsb of FSF_POSITIONS), the detent, the trim, healthy.
        data = expected["data"]
        self.assertEqual(data["surfaces"], {name: round(p, 2) for name, p in zip(NAMES, positions)})
        self.assertEqual((data["flap_cmd"], data["trim"], data["healthy"]),
                         (expected["flap_cmd"], expected["trim"], expected["healthy"]))

    def test_the_tool_reports_the_terminals_state(self):
        tool = SurfacesTool()
        tool.send("status", "sensors 20.0 5.0 10.0", "step 0.02", "data", "trim bogus 1.0", "status")
        tool.run()
        self.assertEqual(["INITIALIZING", "NONE", "0", "0", "1"], tool.line())
        self.assertEqual(["ok"], tool.line())
        self.assertEqual(["ok"], tool.line())
        row = tool.line()
        self.assertEqual(15, len(row))
        self.assertAlmostEqual(1.2, float(row[0]), places=PLACES)
        self.assertAlmostEqual(-1.2, float(row[1]), places=PLACES)
        self.assertAlmostEqual(-1.0, float(row[2]), places=PLACES)
        self.assertAlmostEqual(0.1, float(row[7]), places=PLACES)
        self.assertEqual(["error", "bad", "axis"], tool.line())
        self.assertEqual("1", tool.line()[3], "the slats commanded out at 10 degrees of angle of attack")


class FlightSurfaceQuirkTest(unittest.TestCase):
    """The frozen Python's behaviour the port keeps or departs from (ICD README section 2)."""

    def test_the_service_follows_the_sensed_attitude_and_nothing_else(self):
        fss_module, service = make_service()
        fcc = FakeFcc()
        with mock.patch(FCC_MODULE + ".get_flight_control_computer", return_value=fcc):
            # The flight control computer's commanded deflections are not read: only roll, pitch and AoA matter.
            fcc.data = {"roll": 20.0, "pitch": 5.0, "angle_of_attack": 2.0, "ailerons": 99.0, "elevator": -99.0,
                        "rudder": 99.0, "control_surfaces": {"ailerons": 99.0}}
            service.set_rudder(7.0)
            service._sync_from_fcc()
            self.assertEqual((10.0, -10.0), (service.aileron_l.cmd, service.aileron_r.cmd))
            self.assertEqual((-4.0, -4.0), (service.elevator_l.cmd, service.elevator_r.cmd))
            self.assertEqual(7.0, service.rudder.cmd, "the sync leaves the rudder to set_rudder")
            self.assertEqual((0.0, 0.0), (service.flap_l.cmd, service.speedbrake.cmd))
            source = inspect.getsource(fss_module.FlightSurfaceService._sync_from_fcc)
            self.assertEqual(["roll", "pitch", "angle_of_attack"],
                             [key for key in ("roll", "pitch", "angle_of_attack", "ailerons", "elevator", "flaps")
                              if f"'{key}'" in source])
            # An empty answer changes nothing.
            fcc.data = {}
            service._sync_from_fcc()
            self.assertEqual(10.0, service.aileron_l.cmd)
        # The trim is bookkeeping: no surface's command moves with it.
        before = [s.cmd for s in service._all]
        service.set_trim("yaw", 4.0)
        service.set_trim("bogus", 9.0)
        self.assertEqual(before, [s.cmd for s in service._all])
        self.assertEqual({"pitch": 0.0, "roll": 0.0, "yaw": 4.0}, service.get_data()["trim"])
        # No code path clears a surface's health, and every loop pass persisted a snapshot (not carried).
        module_source = inspect.getsource(fss_module)
        self.assertNotIn("healthy = False", module_source)
        self.assertNotIn("healthy=False", module_source)
        self.assertTrue(service.get_data()["healthy"])
        self.assertIn("self._persist()", inspect.getsource(fss_module.FlightSurfaceService._update_loop))
        self.assertIn("time.sleep(0.02)", inspect.getsource(fss_module.FlightSurfaceService._update_loop))
        self.assertEqual((0, 5, 15, 30), fss_module.FLAP_DETENTS)


if __name__ == "__main__":
    unittest.main()
