"""The avionics terminal against the frozen LRUstatus.py, builtInTesting.py, bitControl.py, fmStatus.py and
swConfigure.py, through fmofp_avionics_tool.

The Python reached into the other subsystems (each LRU's accessor returned a live singleton whose get_status()
it read; the built-in test probes imported them). Here every accessor and getter is a stand-in that answers what
the bus view says of the subsystem's terminal, the same view the tool is given, so both sides judge the same
aircraft:

    not listed, or never responded  -> the accessor returns None ("system not started")
    answering, no TERM_STATUS yet   -> get_status() returns {}
    otherwise                       -> {"running": answering, "healthy": ..., "health": the state's string}
    no bus view at all              -> the accessor raises (the poll's exception path, the probe's ABORT)

The terminal state FAILURE is handed to the Python as "FAILED", a string _derive_health knows; its own name is
not one (a test records that). random.random answers 0.5, so the simulated probes of the systems that have no
terminal pass, as the port's always do; a last test records the Python's one-in-a-hundred fault.

Needs FMOFP_AVIONICS_TOOL (CI sets it).
"""

import itertools
import os
import subprocess
import sys
import types
import unittest
from unittest import mock

from fmofp_bus.tests._support import binary_env, needs

B20SS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if B20SS not in sys.path:
    sys.path.insert(0, B20SS)

# The terminal that carries each catalogued LRU (ICD terminal table), in _build_catalogue()'s order.
LRU_RT = {"FCC-1": 5, "FMS-1": 12, "NAV-1": 7, "RDR-1": 9, "ECU-1": 3, "COMMS-1": 2, "MSN-1": 6, "DFS-1": 22,
          "SNS-1": 10, "GCAS-1": 5, "PERF-1": 5}
ALL = 0
for _rt in set(LRU_RT.values()):
    ALL |= 1 << _rt
MASKS = ("listed", "responded", "answering", "status", "healthy", "bit_failed", "normal", "degraded", "failure")

# The modules _probe_system imports its singletons from, the getter it calls and the terminal behind it.
PROBE_MODULES = {
    "FMOFP.Systems.flightControlSys.flightControlComputer.flightControlComputer": ("get_flight_control_computer", 5),
    "FMOFP.Systems.nav.navService": ("get_nav_service", 7),
    "FMOFP.Systems.missionPlanning.missionService": ("get_mission_service", 6),
    "FMOFP.Systems.comms.messaging_service": ("get_comms_service", 2),
    "FMOFP.Systems.radarManagement.radarControl": ("get_radar_management_system", 9),
}


def healthy_view(**changes):
    """A bus on which every terminal answers, healthy and NORMAL; `changes` clears bits: answering=(7,) ..."""
    view = {"valid": True, "bit_failed": 0, "degraded": 0, "failure": 0}
    for name in ("listed", "responded", "answering", "status", "healthy", "normal"):
        view[name] = ALL
    for name, value in changes.items():
        if name in ("valid",):
            view[name] = value
        elif name.startswith("set_"):
            for rt in value:
                view[name[4:]] |= 1 << rt
        else:
            for rt in value:
                view[name] &= ~(1 << rt)
    return view


def view_command(view):
    return "view %d %s" % (1 if view["valid"] else 0, " ".join("%x" % view[name] for name in MASKS))


def bit_of(view, name, rt):
    return bool((view[name] >> rt) & 1)


def running(view, rt):
    return bit_of(view, "responded", rt) and bit_of(view, "answering", rt)


def status_of(view, rt):
    """The get_status() dictionary the subsystem behind terminal `rt` would have answered with."""
    if running(view, rt) and not bit_of(view, "status", rt):
        return {}
    health = ("FAILED" if bit_of(view, "failure", rt) else "DEGRADED" if bit_of(view, "degraded", rt)
              else "NORMAL" if bit_of(view, "normal", rt) else "STANDBY")
    return {"running": running(view, rt),
            "healthy": bit_of(view, "healthy", rt) if bit_of(view, "status", rt) else True, "health": health}


class World:
    """The bus view the stand-in subsystems answer from."""

    def __init__(self):
        self.view = healthy_view()

    def instance(self, rt):
        if not self.view["valid"]:
            raise RuntimeError("no bus view")
        if not (bit_of(self.view, "listed", rt) and bit_of(self.view, "responded", rt)):
            return None
        return types.SimpleNamespace(get_status=lambda: status_of(self.view, rt), running=running(self.view, rt))

    def probe_instance(self, rt):
        """What a built-in test probe finds: a singleton always exists there (its getter makes one), running or not."""
        if not self.view["valid"]:
            raise RuntimeError("no bus view")
        return types.SimpleNamespace(get_status=lambda: {"running": running(self.view, rt)},
                                     running=running(self.view, rt))


class AvionicsTool:
    """One fmofp_avionics_tool run: commands queued with the answer the Python gave, compared after the run."""

    def __init__(self, case):
        self.case = case
        self.script = []  # (command, expected lines or None)

    def send(self, command, *expected):
        self.script.append((command, list(expected) if expected else None))

    def check(self):
        text = "\n".join(command for command, _ in self.script) + "\n"
        result = subprocess.run([os.environ["FMOFP_AVIONICS_TOOL"]], input=text, capture_output=True, text=True,
                                timeout=120, env=binary_env())
        self.case.assertEqual(0, result.returncode, result.stderr)
        out = [line.rstrip() for line in result.stdout.splitlines()]
        pos = 0
        for step, (command, expected) in enumerate(self.script):
            count = len(expected) if expected is not None else 1
            got = out[pos:pos + count]
            pos += count
            if expected is None:
                self.case.assertEqual(["ok"], got, f"step {step}: {command}")
            else:
                self.case.assertEqual(expected, got, f"step {step}: {command}")
        self.case.assertEqual(len(out), pos, "the tool answered every command and nothing more")


def lru_lines(monitor):
    """`lrus` as the tool prints it, from the frozen monitor."""
    lrus = list(monitor._lrus.values())
    lines = [str(len(lrus))]
    for lru in lrus:
        declared = lru.accessor is None
        lines.append(f"{lru.health.value} {1 if lru.lru_id in monitor._forced_faults else 0} "
                     f"{1 if declared else 0} {lru.lru_id}".rstrip())
    return lines


def overall_line(monitor):
    return f"{monitor.overall_health().value} {len(monitor.get_faults())} {len(monitor.get_forced_faults())}"


@needs("FMOFP_AVIONICS_TOOL")
class LruMonitorOracleTest(unittest.TestCase):
    def setUp(self):
        from FMOFP.Systems.avionics.hardwareHealth import LRUstatus
        self.module = LRUstatus
        self.world = World()
        self.monitor = LRUstatus.LRUStatusMonitor()  # constructed, never started: the test polls it by hand
        for lru_id, lru in self.monitor._lrus.items():
            lru.accessor = (lambda rt: lambda: self.world.instance(rt))(LRU_RT[lru_id])
        self.assertEqual(list(LRU_RT), list(self.monitor._lrus), "the catalogue's order is the table's")
        self.tool = AvionicsTool(self)

    def compare(self):
        self.tool.send("lrus", *lru_lines(self.monitor))
        self.tool.send("overall", overall_line(self.monitor))

    def poll(self, view):
        self.world.view = view
        self.monitor._poll_all()
        self.tool.send(view_command(view))
        self.tool.send("poll")
        self.compare()

    def force(self, key, state="FAULT"):
        lru_id = self.monitor.force_fault(key, state=self.module.HealthState(state), detail="oracle")
        self.tool.send(f"force {state} {key}", lru_id)
        self.compare()

    def clear(self, key):
        self.tool.send(f"clear {key}", str(self.monitor.clear_forced_fault(key)))
        self.compare()

    def test_derive_health_for_every_status(self):
        health_strings = {"OTHER": "STANDBY", "NOMINAL": "NORMAL", "DEGRADED": "DEGRADED", "FAULT": "FAILED"}
        bits = {"NONE": None, "PASS": "POST-FCC/cpu: PASS", "FAIL": "POST-FCC/cpu: FAIL", "ABORT": "POST-FCC/cpu: ABORT"}
        for empty, is_running, healthy, health, bit in itertools.product((0, 1), (0, 1), (0, 1), health_strings, bits):
            status = {} if empty else {"running": bool(is_running), "healthy": bool(healthy),
                                       "health": health_strings[health]}
            lru = self.module.LRU("X-1", "X", "x", bit_result=bits[bit])
            self.tool.send(f"derive {empty} {is_running} {healthy} {health} {bit}",
                           self.module._derive_health(status, lru).value)
        self.tool.check()

    def test_the_states_own_name_is_not_one_the_python_knew(self):
        """Why FAILURE is handed over as FAILED: _derive_health read FAULT, ERROR or FAILED, so a subsystem
        reporting the terminal state's name would have read NOMINAL."""
        lru = self.module.LRU("X-1", "X", "x")
        derive = self.module._derive_health
        self.assertEqual("NOMINAL", derive({"running": True, "healthy": True, "health": "FAILURE"}, lru).value)
        self.assertEqual("FAULT", derive({"running": True, "healthy": True, "health": "FAILED"}, lru).value)
        self.assertEqual("DEGRADED", derive({"running": True, "healthy": False, "health": "FAILED"}, lru).value,
                         "unhealthy is read before the health string")

    def test_polls_follow_the_bus_view(self):
        self.compare()  # before any poll: UNKNOWN everywhere
        self.poll(healthy_view())
        self.poll(healthy_view(answering=(7,), healthy=(9,), responded=(22,), status=(2,)))
        self.poll(healthy_view(normal=(5,), set_failure=(5,)))
        self.poll(healthy_view(normal=(12, 3), set_degraded=(12,)))  # the FMS DEGRADED, the engine in another state
        self.poll(healthy_view(listed=(6, 10)))
        self.poll(healthy_view(valid=False))
        self.poll(healthy_view())
        self.tool.check()

    def test_a_bit_result_speaks_when_the_status_does_not(self):
        self.monitor.update_bit_result("NAV-1", "POST-NAV/cpu: FAIL")
        self.tool.send("bitresult NAV-1 FAIL", "1")
        self.monitor.update_bit_result("NO-SUCH", "x: FAIL")
        self.tool.send("bitresult NO-SUCH FAIL", "0")
        self.poll(healthy_view())
        self.poll(healthy_view(normal=(7,)))
        self.tool.check()

    def test_resolves_keys(self):
        for key in ("FCC-1", "fcc-1", "  NAV-1 ", "flight_control_computer", "FLIGHTMANAGEMENTSYSTEM", "gcas",
                    "collision", "performance", "flight", "service", "radar management", "hydraulic_system_a", ""):
            self.tool.send(f"resolve {key}", self.monitor.resolve_lru_id(key) or "-")
        self.tool.check()

    def test_forced_faults_through_polls_and_clears(self):
        self.poll(healthy_view())
        self.force("flight_control_computer")
        self.poll(healthy_view())  # the poll does not overwrite it
        self.force("engine_vibration", "DEGRADED")  # names no LRU: declared
        self.force("hydraulic_system_a")
        self.force("ENGINE_VIBRATION", "FAULT")  # the declared entry again, by its id
        self.force("collision", "OFFLINE")  # a part of one name
        self.force("service", "DEGRADED")  # a part of five names: declared as SERVICE
        self.force("fuel_transfer", "NOMINAL")  # any state can be forced
        self.poll(healthy_view(answering=(5,)))
        self.clear("no_such_system")
        self.clear("hydraulic")  # a part of the declared entry's name: it goes with its fault
        self.clear("Flight Control")  # FCC-1's name; UNKNOWN until the next poll
        self.poll(healthy_view())
        self.clear("")  # an empty key is a part of every name: the oldest forced fault
        self.force(" odd key ", "FAULT")
        self.poll(healthy_view())
        self.force("flight_control_computer", "DEGRADED")
        self.force("flight_control_computer", "FAULT")  # set again: it keeps its place in the order
        self.clear("")
        self.tool.send("clear_all", str(self.monitor.clear_forced_fault(None)))
        self.compare()
        self.poll(healthy_view())
        self.tool.check()

    def test_the_scenario_files_failures(self):
        """failureScenario.xml's four system_failure events, as the scenario engine would send them."""
        self.poll(healthy_view())
        for system in ("hydraulic_system_a", "engine_vibration", "flight_control_computer", "fuel_transfer"):
            self.force(system)
        self.poll(healthy_view())
        self.assertEqual(14, len(self.monitor._lrus))
        self.assertEqual("FAULT", self.monitor.overall_health().value)
        self.tool.send("clear_all", str(self.monitor.clear_forced_fault(None)))
        self.compare()
        self.tool.check()


@needs("FMOFP_AVIONICS_TOOL")
class BuiltInTestOracleTest(unittest.TestCase):
    def setUp(self):
        from FMOFP.Systems.avionics.hardwareHealth import builtInTesting
        from FMOFP.Systems.builtInTestSystems import bitControl
        self.bit = builtInTesting
        self.world = World()
        self.now = 1000.0
        fakes = {}
        for name, (getter, rt) in PROBE_MODULES.items():
            module = types.ModuleType(name)
            setattr(module, getter, (lambda rt: lambda: self.world.probe_instance(rt))(rt))
            fakes[name] = module
        patches = [mock.patch.dict(sys.modules, fakes),
                   mock.patch.object(builtInTesting, "random", types.SimpleNamespace(random=lambda: 0.5)),
                   mock.patch.object(builtInTesting, "time",
                                     types.SimpleNamespace(time=lambda: self.now, perf_counter=lambda: 0.0))]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.controller = bitControl.BuiltInTestController()
        self.tool = AvionicsTool(self)
        self.last = {}  # (test id, component) -> the last periodic status

    def set_view(self, view):
        self.world.view = view
        self.tool.send(view_command(view))

    def periodic(self, now):
        self.now = now
        results = self.controller.run_periodic_tests()
        for r in results:
            self.last[(r.test_id, r.component)] = r.status.value
        pbit = self.controller._get_pbit()
        order = (("BIT-AVIONICS", "flightControlComputer"), ("BIT-AVIONICS", "missionComputer"),
                 ("BIT-COMM", "datalink"), ("BIT-COMM", "satcom"), ("BIT-COMM", "radios"))
        self.tool.send(f"periodic {now!r}",
                       "%d | %s | %d %d" % (len(results), " ".join(self.last.get(key, "PENDING") for key in order),
                                            len(pbit.get_results("BIT-AVIONICS")), len(pbit.get_results("BIT-COMM"))))

    def test_the_configuration_is_the_tables(self):
        c = self.controller
        self.assertEqual([("POST-FCC", "flightControlComputer", ["cpu", "memory", "databus"]),
                          ("POST-NAV", "navigationSystem", ["cpu", "sensors", "gpsReceiver"])],
                         [(t["id"], t["system"], t["components"]) for t in c.self_tests])
        self.assertEqual([("BIT-AVIONICS", ["flightControlComputer", "missionComputer"], 90),
                          ("BIT-COMM", ["datalink", "satcom", "radios"], 60)],
                         [(t["id"], t["systems"], t["interval"]) for t in c.periodic_tests])
        self.assertEqual([("IFT-FLT-NAV", "flightControlComputer", "navigationSystem"),
                          ("IFT-WPN-FCR", "weaponSystem", "fireControlRadar")],
                         [(t["id"], t["system1"], t["system2"]) for t in c.interface_tests])

    def test_power_on_self_test(self):
        for view in (healthy_view(), healthy_view(answering=(7,)), healthy_view(responded=(5,)),
                     healthy_view(valid=False)):
            self.set_view(view)
            results = self.controller.run_self_tests()
            self.tool.send("post", " ".join(r.status.value for r in results))
        self.tool.check()

    def test_periodic_tests_by_the_clock(self):
        self.set_view(healthy_view(answering=(2,)))
        self.periodic(1000.0)    # a clock near zero: nothing is due until an interval has passed since "never" (0)
        self.periodic(3600.0)    # BIT-COMM, 60 minutes
        self.periodic(5399.0)
        self.periodic(5400.0)    # BIT-AVIONICS, 90 minutes
        self.set_view(healthy_view(answering=(6,)))
        self.periodic(10800.0)   # both: BIT-COMM stores BIT-AVIONICS's results with its own
        self.periodic(10801.0)
        self.set_view(healthy_view(valid=False))
        self.periodic(21600.0)
        self.tool.check()

    def test_the_first_pass_at_wall_clock_time_runs_everything(self):
        """time.time() is far from zero, so the first pass finds both tests due: what the terminal's clock does."""
        self.set_view(healthy_view())
        self.periodic(1.0e9)
        self.periodic(1.0e9 + 1.0)
        self.assertEqual(5, len(self.controller._get_pbit().get_results("BIT-COMM")))
        self.tool.check()

    def test_initiated_test(self):
        for view in (healthy_view(), healthy_view(answering=(7, 2)), healthy_view(valid=False)):
            self.set_view(view)
            results = self.controller.run_interface_tests()  # InitiatedBIT.run_all: all three families
            self.assertEqual(15, len(results))
            self.tool.send("initiated", " ".join(r.status.value for r in results))
        self.assertEqual([], self.controller.get_summary_strings(),
                         "an initiated run leaves the controller's own power-on results alone")
        self.tool.check()

    def test_the_simulated_probe_could_fail(self):
        """The Python's probe of a system with no singleton behind it failed one time in a hundred; the port's
        never does (ICD README section 2)."""
        with mock.patch.object(self.bit, "random", types.SimpleNamespace(random=lambda: 0.001)):
            result = self.bit._probe_system("weaponSystem", "weaponSystem")
        self.assertEqual("FAIL", result.status.value)
        self.assertEqual("simulated fault in weaponSystem", result.detail)


@needs("FMOFP_AVIONICS_TOOL")
class FitnessAndSoftwareOracleTest(unittest.TestCase):
    def test_check_thresholds_is_an_equality(self):
        from FMOFP.Systems.fmFitness import fmStatus
        fitness = fmStatus.FlightManagementFitness()
        self.assertEqual(["flightControlFitness", "navigationFitness", "avionicsFitness"],
                         [c["name"] for c in fitness.components])
        tool = AvionicsTool(self)
        with mock.patch.object(fmStatus, "logger") as logger:
            for cpu, memory in itertools.product((0, 74, 75, 79, 80, 81, 89, 90, 91, 100), (0, 74, 75, 76, 80, 89, 90, 91)):
                fitness.check_thresholds("flightControlFitness", {"cpu": cpu, "memory": memory})
                logged = logger.info.call_args[0][0]  # "<component> status: <status>"
                tool.send(f"fitness {cpu} {memory}", logged.rsplit(" ", 1)[1])
            for index, component in enumerate(c["name"] for c in fitness.components):
                logger.reset_mock()
                fitness.handle_redundancy(component)
                tool.send(f"redundancy {index}", "1" if logger.info.called else "0")
        tool.check()

    def test_software_versions_and_data_loads(self):
        from FMOFP.Systems.configurationManagement import swConfigure
        manager = swConfigure.SoftwareConfigManager()
        self.assertEqual(["fltControlComp", "missionComputer", "commsSoftware"], [c["name"] for c in manager.components])
        # Of each load's specs the parser kept the first component only (three are written for 20190601).
        self.assertEqual([("20190601", [{"component": "fltControlComp", "version": "5.2"}]),
                          ("20191015", [{"component": "fltControlComp", "version": "5.2.1"}])],
                         [(load["id"], load["specs"]) for load in manager.data_loads])
        tool = AvionicsTool(self)

        def versions():
            tool.send("versions", " ".join(c["version"] for c in manager.components))

        versions()
        for load_id in ("20190601", "20200101", "20191015", "20190601"):
            known = any(load["id"] == load_id for load in manager.data_loads)
            manager.perform_update(load_id)
            tool.send(f"load {load_id}", "1" if known else "0")
            versions()
        tool.check()


if __name__ == "__main__":
    unittest.main()
