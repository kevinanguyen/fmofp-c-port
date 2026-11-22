"""Unit 37: the radars following the mission phase, and the mission briefing (ICD v1.29).

The briefing is held to the frozen MissionControl's set_objectives, set_roe and update_intelligence through
fmofp_mission_tool; the radar configurations to the frozen radarControl's three _configure_* methods; and on the
bus the real mission and radar computers under the real controller: INGRESS puts the radars en route, COMPLETE
stands the targeting, SAR and AEWC radars by, and the briefing's counts reach MSN_STATUS.

Needs FMOFP_MISSION_TOOL for the first class, FMOFP_BC, FMOFP_FCS, FMOFP_NAV, FMOFP_FMS, FMOFP_MISSION and
FMOFP_RADAR for the last.
"""

import os
import random
import subprocess
import tempfile
import threading
import types
import unittest

from fmofp_bus.briefing import brief_command, key_of, pack, text_of, unpack
from fmofp_bus.icd import messages as m
from fmofp_bus.icd.enums import (AewcMode, BriefingCommand, CmdStatus, MissionCommand, MissionPhase, SarMode,
                                 TargetingMode, TerminalState, TfrMode, WeatherMode)
from fmofp_bus.monitor import Monitor
from fmofp_bus.status import Status
from fmofp_bus.tests._support import binary_env, free_port_base, needs
from fmofp_plant.plant import PlantModel, PlantTerminal

PORT_BASE = free_port_base(63250)
FRAMES = 450
SYNC_MODE_CODE = 17

# The port's two configurations (radar::allocation_for), by the frozen enums' names: targeting and AEWC SEARCH are
# TARGET_SEARCH and AEWC_SEARCH on the bus, a STANDBY radar is NONE.
PORT = {
    "enroute": {"weather": "SURVEILLANCE", "tfr": "TERRAIN_FOLLOWING", "targeting": "TARGET_SEARCH",
                "sar": "STRIPMAP", "aewc": "AEWC_SEARCH"},
    "airport": {"weather": "SURVEILLANCE", "tfr": "TERRAIN_FOLLOWING", "targeting": "NONE", "sar": "NONE",
                "aewc": "NONE"},
}
BUS_NAMES = {("targeting", "SEARCH"): "TARGET_SEARCH", ("aewc", "SEARCH"): "AEWC_SEARCH"}


class PackingTest(unittest.TestCase):
    def test_text_round_trips_two_characters_a_word(self):
        self.assertEqual([0x4142, 0x4300, 0, 0], pack("ABC", 4))
        self.assertEqual("ABC", unpack(pack("ABC", 4)))
        message = brief_command(BriefingCommand.UPDATE_INTELLIGENCE, "SAM site north", key="threat")
        self.assertEqual(("SAM site north", "threat"), (text_of(message), key_of(message)))
        self.assertEqual("x" * 24, text_of(brief_command(BriefingCommand.ADD_ROE, "x" * 30)))
        status, _ = message.encode()
        self.assertEqual(Status.OK, status)


class FrozenAllocationTest(unittest.TestCase):
    def test_the_configurations_are_the_frozen_methods(self):
        import FMOFP.Systems.radarManagement.radarControl as rc
        classes = {"weather": rc.weather_radar, "tfr": rc.tfr_radar, "targeting": rc.targeting_radar,
                   "sar": rc.sar_radar, "aewc": rc.aewc_radar}
        for method, config in (("_configure_enroute_surveillance", "enroute"), ("_configure_airport_departure", "airport"),
                               ("_configure_airport_arrival", "airport")):
            calls = {}
            radars = {}
            for name, cls in classes.items():
                radar = cls.__new__(cls)
                radar.name = name
                radar.set_mode = (lambda mode, send_completion=True, request_id=None, _n=name:
                                  calls.__setitem__(_n, mode.name))
                radars[name] = radar
            getattr(rc.RadarManagementSystem, method)(types.SimpleNamespace(radars=radars))
            bus = {name: ("NONE" if mode == "STANDBY" else BUS_NAMES.get((name, mode), mode))
                   for name, mode in calls.items()}
            self.assertEqual(PORT[config], bus, method)

    def test_the_frozen_allocation_keys_on_flight_phases_the_mission_computer_has_not(self):
        from FMOFP.Systems.radarManagement.radar_enums import MissionPhase as FlightPhase
        self.assertEqual({"PRE_FLIGHT", "TAKEOFF", "CLIMB", "CRUISE", "DESCENT", "APPROACH", "LANDING", "POST_FLIGHT"},
                         {p.name for p in FlightPhase})
        self.assertFalse({p.name for p in FlightPhase} & {p.name for p in MissionPhase})


@needs("FMOFP_MISSION_TOOL")
class FrozenBriefingTest(unittest.TestCase):
    def frozen(self):
        from FMOFP.Systems.missionPlanning.missionControl import MissionControl
        state = types.SimpleNamespace(_lock=threading.Lock(), _objectives=[], _roe=[], _intelligence={})
        return MissionControl, state

    def test_random_briefings_match_the_frozen_methods(self):
        MissionControl, state = self.frozen()
        rng = random.Random(37)
        words = ["Destroy", "the", "bridge", "Hold", "fire", "SAM", "north", "radar", "site", "egress"]
        lines = []
        for _ in range(300):
            op = rng.choice(["obj", "obj", "roe", "roe", "intel", "intel", "clear_obj", "clear_roe", "clear_intel"])
            text = " ".join(rng.choice(words) for _ in range(rng.randint(1, 3)))[:24]
            if op == "obj" and len(state._objectives) < 8:
                MissionControl.set_objectives(state, state._objectives + [text])
                lines.append(f"brief_objective {text}")
            elif op == "roe" and len(state._roe) < 8:
                MissionControl.set_roe(state, state._roe + [text])
                lines.append(f"brief_roe {text}")
            elif op == "intel":
                key = rng.choice(["threat", "weather", "sam", "radar", "egress", "fuel", "comms", "target", "alt"])
                if key not in state._intelligence and len(state._intelligence) >= 8:
                    continue
                MissionControl.update_intelligence(state, {key: text})
                lines.append(f"brief_intel {key} {text}")
            elif op == "clear_obj":
                MissionControl.set_objectives(state, [])
                lines.append("brief_clear_objectives")
            elif op == "clear_roe":
                MissionControl.set_roe(state, [])
                lines.append("brief_clear_roe")
            elif op == "clear_intel":
                state._intelligence = {}  # the Python had no call for it: the port's CLEAR_INTELLIGENCE
                lines.append("brief_clear_intel")
            else:
                continue
            lines.append("brief_dump")
            expected = ([f"objective {t}" for t in state._objectives] + [f"roe {t}" for t in state._roe]
                        + [f"intel {k}={v}" for k, v in state._intelligence.items()] + ["end"])
            lines.append(("EXPECT", expected))
        commands = [line for line in lines if isinstance(line, str)]
        out = subprocess.run([os.environ["FMOFP_MISSION_TOOL"]], input="\n".join(commands) + "\n",
                             capture_output=True, text=True, env=binary_env(), timeout=60).stdout.splitlines()
        cursor = 0
        checked = 0
        for line in lines:
            if isinstance(line, str):
                if line != "brief_dump":
                    self.assertEqual("ACCEPTED", out[cursor], line)
                    cursor += 1
                continue
            expected = line[1]
            self.assertEqual(expected, out[cursor:cursor + len(expected)])
            cursor += len(expected)
            checked += 1
        self.assertGreater(checked, 150)


@needs("FMOFP_BC", "FMOFP_FCS", "FMOFP_NAV", "FMOFP_FMS", "FMOFP_MISSION", "FMOFP_RADAR")
class MissionPhaseDrivesTheRadarsTest(unittest.TestCase):
    SCRIPT = [
        (120, m.MsnCmd(cmd_seq=1, command=MissionCommand.SET_PHASE, phase=MissionPhase.INGRESS)),
        (130, brief_command(BriefingCommand.ADD_OBJECTIVE, "Destroy the bridge", cmd_seq=1)),
        (131, brief_command(BriefingCommand.ADD_OBJECTIVE, "Return to base", cmd_seq=2)),
        (132, brief_command(BriefingCommand.ADD_ROE, "Weapons tight", cmd_seq=3)),
        (133, brief_command(BriefingCommand.UPDATE_INTELLIGENCE, "SAM north", key="threat", cmd_seq=4)),
        (134, brief_command(BriefingCommand.UPDATE_INTELLIGENCE, "SAM moved", key="threat", cmd_seq=5)),
        (200, m.MsnCmd(cmd_seq=2, command=MissionCommand.ADVANCE_PHASE)),
        (300, m.MsnCmd(cmd_seq=3, command=MissionCommand.SET_PHASE, phase=MissionPhase.COMPLETE)),
    ]
    RADARS = (("weather", m.RdrWxStatus), ("tfr", m.RdrTfrStatus), ("targeting", m.RdrTgtStatus),
              ("aewc", m.RdrAewcStatus), ("sar", m.RdrSarStatus))

    def setUp(self):
        self.script = os.path.join(tempfile.mkdtemp(prefix="fmofp_unit37_"), "commands.txt")
        with open(self.script, "w", encoding="utf-8") as f:
            for frame, message in self.SCRIPT:
                status, words = message.encode()
                self.assertEqual(Status.OK, status)
                f.write(f"{frame} {message.RT} {message.SUBADDRESS} " + " ".join(f"{w:04X}" for w in words) + "\n")
        self.monitor = Monitor(PORT_BASE)
        self.assertEqual(Status.OK, self.monitor.open(), "monitor port in use?")
        self.plant = PlantTerminal(PlantModel(seed=37, weather=False, traffic=False, ground=False), PORT_BASE)
        self.assertEqual(Status.OK, self.plant.init(), "plant port in use?")
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.pump, daemon=True)
        self.thread.start()
        self.procs = [subprocess.Popen([os.environ[name], "--port-base", str(PORT_BASE), "--quiet"],
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=binary_env())
                      for name in ("FMOFP_FCS", "FMOFP_NAV", "FMOFP_FMS", "FMOFP_MISSION", "FMOFP_RADAR")]

    def pump(self):
        while not self.stop.is_set():
            self.plant.poll(0.005)

    def tearDown(self):
        self.stop.set()
        self.thread.join(timeout=2)
        for proc in self.procs:
            proc.kill()
            proc.wait(timeout=10)
            proc.stdout.close()
        self.plant.shutdown()
        self.monitor.close()

    def last(self, framed, cls, first, last):
        for frame, record in reversed(framed):
            cw = record.command
            if (first <= frame < last and cw.transmit and not cw.is_mode_code and cw.rt == cls.RT
                    and cw.subaddress == cls.SUBADDRESS and record.answered):
                status, msg = cls.decode(record.received)
                self.assertEqual(Status.OK, status)
                return msg
        self.fail(f"no {cls.__name__} in frames {first}..{last - 1}")

    def modes(self, framed, first, last):
        return {name: self.last(framed, cls, first, last).mode.name for name, cls in self.RADARS}

    def test_the_phase_configures_the_radars_and_the_briefing_is_counted(self):
        import time
        time.sleep(0.3)
        bc = subprocess.Popen(
            [os.environ["FMOFP_BC"], "--rt", "27", "--rt", str(m.FcsStatus.RT), "--rt", str(m.NavSolution.RT),
             "--rt", str(m.FmsStatus.RT), "--rt", str(m.MsnStatus.RT), "--rt", str(m.RdrWxStatus.RT),
             "--port-base", str(PORT_BASE), "--frames", str(FRAMES), "--free-run", "--timeout-ms", "40",
             "--script", self.script], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=binary_env())
        records = self.monitor.read_until(lambda: bc.poll() is not None)
        output = bc.stdout.read()
        bc.stdout.close()
        self.assertEqual(0, bc.wait(timeout=60), output)
        frame = -1
        framed = []
        for record in records:
            cw = record.command
            if cw.is_mode_code and cw.count_or_mode == SYNC_MODE_CODE:
                frame += 1
                continue
            framed.append((frame, record))
        self.assertEqual("NONE", self.modes(framed, 100, 120)["targeting"], "PLANNING configures nothing")
        self.assertEqual(PORT["enroute"], self.modes(framed, 250, 300), "INGRESS, then OBJECTIVE: en route")
        self.assertEqual(PORT["airport"], self.modes(framed, 400, FRAMES), "COMPLETE: the airport set")
        status = self.last(framed, m.MsnStatus, 400, FRAMES)
        self.assertEqual(MissionPhase.COMPLETE, status.phase)
        self.assertEqual((2, 1, 1, CmdStatus.ACCEPTED, 5),
                         (status.objective_count, status.roe_count, status.intelligence_count, status.brief_cmd_status,
                          status.last_brief_cmd_seq))
        self.assertEqual(TerminalState.STANDBY, self.last(framed, m.RdrTgtStatus, 400, FRAMES).state)


if __name__ == "__main__":
    unittest.main()
