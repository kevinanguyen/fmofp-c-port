"""The aircraft's timing against its budget (unit 30).

Every C++ partition and the plant (Python, in-process) under the real bus controller, free running, with the
first sixteen seconds of the demo's scripted flight: the five radars switched on, a route loaded, the radio
tuned. The controller's own timing report (`--report`, ofp/README.md) is then held to two limits:

  * the schedule's estimate of the worst minor frame, against the 10000 us budget with a margin;
  * each partition's mean answer to the bus, which contains its frame's work whenever the controller polls it
    right after the sync.

The mean, not the worst: one answer is as slow as the machine's worst moment (40 ms stalls were measured on a
desktop with every partition otherwise at 0.1 ms), and a test must not fail for that. A partition whose step has
grown too long for a 20 ms frame moves its mean, which is what this pins. The displays are not here: they are
Python test equipment, and the real-time demo is where they are watched.

Needs FMOFP_BC and every partition's binary (CI sets them).
"""

import os
import re
import subprocess
import tempfile
import threading
import time
import unittest

from fmofp_bus.status import Status
from fmofp_bus.tests._support import binary_env, free_port_base, needs
from fmofp_demo.demo import PARTITIONS, PLANT_RT, SYNC_HZ, default_events, write_script
from fmofp_plant.plant import PlantModel, PlantTerminal

PORT_BASE = free_port_base(64500)
SCRIPT_SECONDS = 16.0  # the demo's events up to here: every radar on, the mission, the radio
FRAMES = int(SCRIPT_SECONDS * SYNC_HZ) + 200
BINARIES = tuple(f"FMOFP_{name.upper()}" for name, _ in PARTITIONS)

FRAME_BUDGET_US = 10000
# The schedule may fill the budget to here; past it the next message added needs a plan, not luck.
FRAME_ESTIMATE_LIMIT_US = 9500
# A partition's mean answer: a fifth of the 20 ms frame. Measured means are 0.07-0.5 ms on a desktop at -O0.
PARTITION_MEAN_LIMIT_US = 4000

SCHEDULE_LINE = re.compile(r"bc: (\d+) scheduled messages for (\d+) terminals; worst minor frame (\d+) us of (\d+) us")
TIMING_LINE = re.compile(r"rt\s+(\d+) timing: mean_response_us=(\d+) worst_response_us=(\d+) overruns_slowest=(\d+)")
BUS_TIMING_LINE = re.compile(r"bc: timing: overruns_late_start=(\d+) worst_wake_late_us=(-?\d+)")
STATS_LINE = re.compile(r"rt\s+(\d+): transactions=(\d+) retries=(\d+) no_response=(\d+)")


class PlantThread(threading.Thread):
    def __init__(self, plant):
        super().__init__(daemon=True)
        self.plant = plant
        self.stop = threading.Event()

    def run(self):
        while not self.stop.is_set():
            self.plant.poll(0.002)


@needs("FMOFP_BC", *BINARIES)
class AircraftTimingTest(unittest.TestCase):
    processes = []
    plant_thread = None
    plant = None
    output = ""

    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.mkdtemp(prefix="fmofp_timing_")
        script = os.path.join(cls.directory, "events.txt")
        partition_rts = {rt for _, rt in PARTITIONS}
        events = [e for e in default_events() if e.seconds <= SCRIPT_SECONDS and e.message.RT in partition_rts]
        cls.event_count = len(events)
        cls.event_kinds = {type(e.message).__name__ for e in events}
        write_script(script, events)
        try:
            model = PlantModel(seed=5)
            model.hold = dict(speed=450.0, heading=0.0, altitude=5000.0, vertical_speed=0.0)
            cls.plant = PlantTerminal(model, PORT_BASE)
            assert cls.plant.init() == Status.OK, "plant port in use?"
            cls.plant_thread = PlantThread(cls.plant)
            cls.plant_thread.start()
            for binary in BINARIES:
                cls.processes.append(subprocess.Popen(
                    [os.environ[binary], "--port-base", str(PORT_BASE), "--quiet"], stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, env=binary_env()))
            time.sleep(0.3)
            command = [os.environ["FMOFP_BC"], "--rt", str(PLANT_RT)]
            for _, rt in PARTITIONS:
                command += ["--rt", str(rt)]
            command += ["--port-base", str(PORT_BASE), "--frames", str(FRAMES), "--free-run", "--no-monitor",
                        "--no-command-port", "--timeout-ms", "40", "--report", "--script", script]
            # To a file, not a pipe: --report prints a line a second and the timing lines at the end, more than
            # the 4 KB a Windows pipe holds while nobody reads it.
            log = os.path.join(cls.directory, "bc.log")
            with open(log, "w", encoding="utf-8") as out:
                cls.returncode = subprocess.run(command, stdout=out, stderr=subprocess.STDOUT, env=binary_env(),
                                                timeout=300).returncode
            with open(log, encoding="utf-8", errors="replace") as f:
                cls.output = f.read()
        finally:
            cls.stop_everything()

    @classmethod
    def stop_everything(cls):
        for p in cls.processes:
            p.kill()
            p.wait(timeout=10)
        cls.processes = []
        if cls.plant_thread is not None:
            cls.plant_thread.stop.set()
            cls.plant_thread.join(timeout=2)
            cls.plant_thread = None
        if cls.plant is not None:
            cls.plant.shutdown()
            cls.plant = None

    def timing(self):
        """rt -> (mean us, worst us, overrun frames it was slowest in), from the controller's report."""
        return {int(rt): (int(mean), int(worst), int(slowest))
                for rt, mean, worst, slowest in TIMING_LINE.findall(self.output)}

    def test_the_run_is_the_whole_scripted_aircraft(self):
        self.assertEqual(0, self.returncode, self.output[-2000:])
        self.assertIn(f"script: {self.event_count} commands sent of {self.event_count}", self.output)
        # The load worth timing: all five radars working, with the mission and the radio beside them.
        for kind in ("RdrWxModeCmd", "RdrTfrModeCmd", "RdrTgtModeCmd", "RdrAewcModeCmd", "RdrSarModeCmd", "MsnCmd",
                     "ComCmd"):
            self.assertIn(kind, self.event_kinds)
        stats = {int(rt): (int(transactions), int(no_response))
                 for rt, transactions, _, no_response in STATS_LINE.findall(self.output)}
        expected = {PLANT_RT} | {rt for _, rt in PARTITIONS}
        self.assertEqual(expected, set(stats))
        self.assertEqual(expected, set(self.timing()), "a timing line for every terminal")
        for rt, (transactions, no_response) in sorted(stats.items()):
            self.assertGreater(transactions, 0, f"RT {rt}")
            self.assertEqual(0, no_response, f"RT {rt} left a poll unanswered")

    def test_the_schedule_fits_the_frame_with_margin(self):
        match = SCHEDULE_LINE.search(self.output)
        self.assertIsNotNone(match, self.output[:400])
        messages, terminals, estimate, budget = map(int, match.groups())
        self.assertEqual((len(PARTITIONS) + 1, FRAME_BUDGET_US), (terminals, budget))
        self.assertGreater(messages, 60)
        self.assertLessEqual(
            estimate, FRAME_ESTIMATE_LIMIT_US,
            f"the worst minor frame is estimated at {estimate} us: within {FRAME_BUDGET_US - FRAME_ESTIMATE_LIMIT_US} us "
            f"of the budget. Lighten the schedule (a slower rate, a broadcast for a many-relay stream: ICD README "
            f"section 12) before adding to it")

    def test_every_partition_answers_well_inside_the_frame(self):
        timing = self.timing()
        names = {rt: name for name, rt in PARTITIONS}
        table = ", ".join(f"{names[rt]} {timing[rt][0]}" for rt in sorted(names))
        for rt, name in sorted(names.items()):
            mean, worst, _ = timing[rt]
            self.assertGreater(worst, 0, f"{name}: no answer was timed")
            self.assertLessEqual(mean, PARTITION_MEAN_LIMIT_US,
                                 f"{name} (RT {rt}) takes {mean} us on average to answer the bus; mean us: {table}")
        # The plant is Python test equipment, reported for the record and held only to answering at all.
        self.assertGreater(timing[PLANT_RT][1], 0)

    def test_free_running_has_no_deadline_to_miss(self):
        match = BUS_TIMING_LINE.search(self.output)
        self.assertIsNotNone(match, "the controller's timing line (--report)")
        self.assertEqual(0, int(match.group(1)), "late starts are a real-time notion")
        self.assertIn("overruns=0", self.output)
        self.assertEqual(0, sum(slowest for _, _, slowest in self.timing().values()))


if __name__ == "__main__":
    unittest.main()
